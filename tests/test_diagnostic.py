import unittest

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

    def test_sans_modele_et_machine_inconnue_renvoie_aux_modeles(self):
        p, = diag(installes=[])
        self.assertEqual(p["action"], {"type": "onglet", "nom": "modeles"})

    def test_ollama_arrete(self):
        p, = diag(ollama_actif=False)
        self.assertEqual((p["code"], p["action"]["type"]), ("ollama_arret", "demarrer_ollama"))
        p, = diag(ollama_actif=False, ollama_installe=False)
        self.assertEqual(p["action"]["type"], "onglet")
        p, = diag(ollama_actif=False, docker=True)
        self.assertIn("docker logs", p["texte"])

    def test_modele_choisi_absent_ou_trop_gros_et_disque_plein(self):
        p, = diag(reglages={"modele": "autre:7b"})
        self.assertEqual(p["code"], "modele_absent")
        p, = diag(adequation={"qwen3:4b": {"niveau": "trop_gros", "texte": "dépasse la mémoire"}})
        self.assertEqual(p["code"], "modele_trop_gros")
        p, = diag(disque_libre_go=0.5)
        self.assertEqual(p["code"], "disque")


if __name__ == "__main__":
    unittest.main()
