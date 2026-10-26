"""La zone de notification (lutin zone) : la logique de supervision du serveur, sans fenêtre. La fenêtre elle-même n'est testée que sous Windows."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401
from lutin import zone


class Enfant:
    """Un faux processus : attend `code`, et sait qu'on l'a arrêté."""

    def __init__(self, code):
        self.code = code
        self.arrete = False

    def wait(self):
        return self.code

    def poll(self):
        return None if not self.arrete else self.code

    def terminate(self):
        self.arrete = True


class Serveur(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix="zone-test-"))
        self.dossiers = {"donnees": str(self.dossier)}

    def test_lance_le_serveur_sans_fenetre_et_sans_navigateur_apres_la_premiere_fois(self):
        s = zone.Serveur(self.dossiers)
        with mock.patch.object(zone.subprocess, "Popen", return_value=Enfant(0)) as popen:
            self.assertEqual(s.lancer(True), 0)
            commande = popen.call_args[0][0]
            self.assertIn("serve", commande)
            self.assertNotIn("--sans-navigateur", commande, "la première fois, le navigateur s'ouvre")
            self.assertEqual(popen.call_args[1]["creationflags"], zone.CREATE_NO_WINDOW, "aucune console")
            s.lancer(False)
            self.assertIn("--sans-navigateur", popen.call_args[0][0], "les relances n'ouvrent pas le navigateur une deuxième fois")

    def test_redemarrer_rend_le_code_de_redemarrage_du_superviseur(self):
        from lutin.cli import CODE_REDEMARRAGE
        s = zone.Serveur(self.dossiers)
        s.redemarrage = True
        with mock.patch.object(zone.subprocess, "Popen", return_value=Enfant(1)):
            self.assertEqual(s.lancer(False), CODE_REDEMARRAGE, "le superviseur relance sans compter une panne")
        self.assertFalse(s.redemarrage, "le drapeau est remis à zéro")

    def test_arreter_ne_relance_jamais(self):
        s = zone.Serveur(self.dossiers)
        s.arreter()
        with mock.patch.object(zone.subprocess, "Popen") as popen:
            self.assertEqual(s.lancer(False), 0)
            popen.assert_not_called()

    def test_arret_pendant_le_serveur_le_termine(self):
        s = zone.Serveur(self.dossiers)
        enfant = Enfant(1)
        s.enfant = enfant
        s.arreter()
        self.assertTrue(enfant.arrete)

    def test_la_sortie_du_serveur_va_dans_un_journal(self):
        s = zone.Serveur(self.dossiers)
        with mock.patch.object(zone.subprocess, "Popen", return_value=Enfant(0)):
            s.lancer(True)
        self.assertTrue((self.dossier / "serveur.log").is_file())


class Commande(unittest.TestCase):
    def test_refuse_hors_windows_avec_un_message(self):
        with mock.patch.object(zone, "disponible", return_value=False), mock.patch("sys.stderr"):
            self.assertEqual(zone.commande({"donnees": "x"}, {"installe": True}), 1)

    def test_sans_installation_le_dit_au_lieu_de_demander_des_reponses(self):
        if not zone.disponible():
            self.skipTest("fenêtre : Windows seulement")
        with mock.patch.object(zone, "message") as message:
            self.assertEqual(zone.commande({"donnees": "x"}, {"installe": False}), 1)
            message.assert_called_once()

    def test_adresse_selon_le_port(self):
        self.assertEqual(zone.adresse({"securite": {"port": 8790}}), "http://127.0.0.1:8790/")


if __name__ == "__main__":
    unittest.main()
