import os
import unittest
import unittest.mock

import context  # noqa: F401
from lutin import catalogue, diagnostic
from lutin.machine import Profil

CAT = catalogue.charger()
PROFIL = Profil(systeme="linux", ram_go=32.0, ram_libre_go=20.0, gpus=[])


def diag(**kw):
    base = dict(ollama_actif=True, ollama_installe=True, installes=["qwen3:4b"], reglages={"modele": "qwen3:4b"}, docker=False)
    base.update(kw)
    return diagnostic.diagnostiquer(**base)


class Diagnostic(unittest.TestCase):
    def test_tout_va_bien(self):
        self.assertEqual(diag(), [])

    def test_ollama_tourne_sans_modele_propose_le_modele_conseille(self):
        p, = diag(installes=[], profil=PROFIL, catalogue=CAT)
        self.assertEqual((p["code"], p["niveau"], p["action"]["type"]), ("aucun_modele", "erreur", "installer_modele"))
        self.assertTrue(p["action"]["modele"])
        self.assertIn(p["action"]["modele"], p["texte"])

    def test_colibri_installe_sans_modele_dit_de_preparer_un_modele_au_lieu_d_un_bouton_muet(self):
        """« Colibri ne répond pas » + « Démarrer » qui ne faisait rien : Colibri ne démarre qu'avec un modèle qu'il a préparé."""
        r = diagnostic.premier_lancement("Serveur compatible OpenAI", False, "", gere={"nom": "Colibri", "installe": True, "sans_modele": True})
        self.assertIn("aucun modèle", r["raison"])
        self.assertNotIn("démarre-le", r["raison"])
        r = diagnostic.premier_lancement("Serveur compatible OpenAI", False, "", gere={"nom": "Colibri", "installe": True})
        self.assertIn("démarre-le", r["raison"])

    def test_sans_modele_et_machine_inconnue_renvoie_aux_modeles(self):
        p, = diag(installes=[])
        self.assertEqual(p["action"], {"type": "onglet", "nom": "modeles"})

    def test_premier_lancement_dit_ou_le_moteur_sera_installe_sous_docker(self):
        emp = {"dossier": "/data/moteurs", "dedie": False}
        r = diagnostic.premier_lancement("Ollama", False, "", None, emp)
        self.assertEqual(r["emplacement"], emp)
        self.assertIsNone(diagnostic.premier_lancement("Ollama", False, "")["emplacement"])          # hors Docker : rien à dire

    def test_ollama_arrete(self):
        p, = diag(ollama_actif=False)
        self.assertEqual((p["code"], p["action"]["type"]), ("ollama_arret", "demarrer_ollama"))
        p, = diag(ollama_actif=False, ollama_installe=False)
        self.assertEqual(p["action"]["type"], "onglet")
        with unittest.mock.patch.dict(os.environ, {"OLLAMA_URL": "http://ollama:11434"}):
            p, = diag(ollama_actif=False, docker=True)
        self.assertIn("docker logs", p["texte"])
        p, = diag(ollama_actif=False, docker=True)          # Ollama installé par Lutin dans le volume : on propose de le démarrer
        self.assertEqual(p["action"]["type"], "demarrer_ollama")

    def test_modele_choisi_absent_ou_trop_gros_et_disque_plein(self):
        p, = diag(reglages={"modele": "autre:7b"})
        self.assertEqual(p["code"], "modele_absent")
        p, = diag(adequation={"qwen3:4b": {"niveau": "trop_gros", "texte": "dépasse la mémoire"}})
        self.assertEqual(p["code"], "modele_trop_gros")
        p, = diag(disque_libre_go=0.5)
        self.assertEqual(p["code"], "disque")


if __name__ == "__main__":
    unittest.main()
