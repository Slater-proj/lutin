"""La zone de notification (lutin zone) : la supervision du serveur, la première installation, le menu et ses actions. La fenêtre réelle n'est testée que sous Windows."""
import tempfile
import threading
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

    def test_redemarrer_arrete_le_serveur_en_cours(self):
        s = zone.Serveur(self.dossiers)
        s.enfant = Enfant(1)
        s.redemarrer()
        self.assertTrue(s.enfant.arrete)
        self.assertTrue(s.redemarrage)

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


class PremiereUtilisation(unittest.TestCase):
    """Sans console, la zone ne pourrait pas poser les questions de l'installation guidée : elle l'ouvre dans une console, comme le faisait l'ancien raccourci."""

    def test_deja_installe_rien_a_faire(self):
        with mock.patch.object(zone.subprocess, "run") as run:
            cfg = {"installe": True}
            self.assertIs(zone.preparer({"donnees": "x"}, cfg), cfg)
            run.assert_not_called()

    def test_pas_installe_l_installation_guidee_s_ouvre_dans_une_console(self):
        from lutin import config
        with mock.patch.object(zone.subprocess, "run") as run, mock.patch.object(config, "charger", return_value={"installe": True, "x": 1}):
            cfg = zone.preparer({"donnees": "x"}, {"installe": False})
        self.assertEqual(cfg, {"installe": True, "x": 1}, "on repart de la configuration que l'installation vient d'écrire")
        commande = run.call_args[0][0]
        self.assertEqual(commande[1:], ["-m", "lutin", "setup"])
        self.assertEqual(run.call_args[1]["creationflags"], zone.CREATE_NEW_CONSOLE, "une vraie console, pour pouvoir répondre")

    def test_installation_abandonnee_on_ne_demarre_pas(self):
        from lutin import config
        with mock.patch.object(zone.subprocess, "run"), mock.patch.object(config, "charger", return_value={"installe": False}):
            self.assertIsNone(zone.preparer({"donnees": "x"}, {"installe": False}))

    def test_python_console_prefere_python_exe_a_pythonw(self):
        d = Path(tempfile.mkdtemp(prefix="zone-py-"))
        (d / "pythonw.exe").write_text("")
        (d / "python.exe").write_text("")
        with mock.patch.object(zone.sys, "executable", str(d / "pythonw.exe")):
            self.assertEqual(Path(zone.python_console()).name, "python.exe")


class Commande(unittest.TestCase):
    def test_refuse_hors_windows_avec_un_message(self):
        with mock.patch.object(zone, "disponible", return_value=False), mock.patch("sys.stderr"):
            self.assertEqual(zone.commande({"donnees": "x"}, {"installe": True}), 1)

    def test_adresse_selon_le_port(self):
        self.assertEqual(zone.adresse({"securite": {"port": 8790}}), "http://127.0.0.1:8790/")

    def test_au_niveau_local_l_adresse_est_simple(self):
        cfg = {"securite": {"niveau": "local", "port": 8790}}
        self.assertEqual(zone.adresse_ouverture({"donnees": "x"}, cfg), "http://127.0.0.1:8790/")

    def test_au_niveau_reseau_le_navigateur_de_cette_machine_s_appaire_avec_un_pin(self):
        """Au niveau réseau, la page demande un code PIN même ici : l'icône en demande un au serveur et le glisse dans l'adresse (#pin=), la page de connexion le valide seule."""
        from lutin import client
        cfg = {"securite": {"niveau": "reseau", "port": 8790}}
        with mock.patch.object(client.ClientLocal, "envoyer", return_value={"pin": "123456", "valable_s": 600}) as envoyer:
            self.assertEqual(zone.adresse_ouverture({"donnees": "x"}, cfg), "http://127.0.0.1:8790/#pin=123456")
        envoyer.assert_called_once_with("/api/nouveau-pin", {})

    def test_serveur_pas_encore_pret_l_adresse_simple_suffit(self):
        from lutin import client
        cfg = {"securite": {"niveau": "reseau", "port": 8790}}
        with mock.patch.object(client.ClientLocal, "envoyer", side_effect=client.ErreurClient("pas prêt")):
            self.assertEqual(zone.adresse_ouverture({"donnees": "x"}, cfg), "http://127.0.0.1:8790/")


@unittest.skipUnless(zone.disponible(), "fenêtre : Windows seulement")
class MenuEtFenetre(unittest.TestCase):
    """Le vrai menu est essayé à la main et dans tests/ (voir DECISIONS) ; ici : ses actions, avec le choix de l'utilisateur simulé."""

    def zone(self):
        serveur = mock.Mock()
        z = zone.Zone({"securite": {"port": 8793}}, {"donnees": tempfile.mkdtemp(prefix="zone-menu-")}, serveur)
        return z, serveur

    def test_le_menu_a_les_quatre_entrees_dans_l_ordre(self):
        z, _ = self.zone()
        with mock.patch.object(zone.user32, "AppendMenuW") as ajout:
            z.menu()
        self.assertEqual([c.args[2] for c in ajout.call_args_list], [zone.MENU_PIN, zone.MENU_OUVRIR, zone.MENU_REDEMARRER, zone.MENU_QUITTER])

    def test_ouvrir_ouvre_l_interface(self):
        z, _ = self.zone()
        with mock.patch.object(zone, "ouvrir_interface") as ouvrir:
            z.action(zone.MENU_OUVRIR)
        ouvrir.assert_called_once_with(z.dossiers, z.cfg)

    def test_redemarrer_redemarre_le_serveur(self):
        z, serveur = self.zone()
        with mock.patch.object(zone.threading, "Thread") as fil:
            z.action(zone.MENU_REDEMARRER)
        self.assertEqual(fil.call_args[1]["target"], serveur.redemarrer)

    def test_quitter_arrete_le_serveur_puis_ferme_la_fenetre(self):
        z, serveur = self.zone()
        with mock.patch.object(zone.user32, "PostMessageW") as poste:
            z.hwnd = 1234
            z.quitter()
        serveur.arreter.assert_called_once()
        poste.assert_called_once_with(1234, zone.WM_CLOSE, 0, 0)

    def test_pin_affiche_le_code_dans_une_boite(self):
        z, _ = self.zone()
        fait = threading.Event()
        with mock.patch.object(zone, "code_pin", return_value="Code : 123456"), mock.patch.object(zone, "message", side_effect=lambda t, m: fait.set()) as boite:
            z.action(zone.MENU_PIN)
            self.assertTrue(fait.wait(5))
        self.assertEqual(boite.call_args[0][1], "Code : 123456")

    def test_clic_droit_ouvre_le_menu_et_execute_le_choix(self):
        z, _ = self.zone()
        z.hwnd = 1
        with mock.patch.object(zone.user32, "TrackPopupMenu", return_value=zone.MENU_OUVRIR), mock.patch.object(zone.user32, "SetForegroundWindow"), \
                mock.patch.object(zone.user32, "PostMessageW"), mock.patch.object(zone, "ouvrir_interface") as ouvrir:
            z.traiter(1, zone.MESSAGE_ICONE, 1, zone.WM_RBUTTONUP)
        ouvrir.assert_called_once()

    def test_clic_gauche_ouvre_l_interface_sans_menu(self):
        z, _ = self.zone()
        with mock.patch.object(zone, "ouvrir_interface") as ouvrir, mock.patch.object(zone.user32, "TrackPopupMenu") as menu:
            z.traiter(1, zone.MESSAGE_ICONE, 1, zone.WM_LBUTTONUP)
        ouvrir.assert_called_once()
        menu.assert_not_called()

    def test_une_erreur_dans_le_menu_va_dans_le_journal_au_lieu_de_disparaitre(self):
        z, _ = self.zone()
        with mock.patch.object(zone.user32, "GetCursorPos", side_effect=RuntimeError("boum")):
            z.traiter(1, zone.MESSAGE_ICONE, 1, zone.WM_RBUTTONUP)
        self.assertIn("boum", (Path(z.dossiers["donnees"]) / "zone.log").read_text(encoding="utf-8"))

    def test_l_explorateur_redemarre_l_icone_revient(self):
        z, _ = self.zone()
        z.msg_barre = 0xC123
        with mock.patch.object(z, "ajouter_icone") as ajout:
            z.traiter(1, 0xC123, 0, 0)
        ajout.assert_called_once()

    def test_la_vraie_fenetre_se_cree_et_se_ferme(self):
        z, _ = self.zone()
        try:
            z.creer()
        except OSError as erreur:
            self.skipTest("pas de session de bureau : {}".format(erreur))
        self.assertTrue(z.hwnd)
        self.assertTrue(z.icone, "web/lutin.ico se charge")
        threading.Timer(0.5, lambda: zone.user32.PostMessageW(z.hwnd, zone.WM_CLOSE, 0, 0)).start()
        z.boucle()                                   # rend la main quand la fenêtre est fermée


if __name__ == "__main__":
    unittest.main()
