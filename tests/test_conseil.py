"""« Tester mon PC » : les conseils tirés de la vitesse mesurée."""
import os
import unittest
from unittest import mock

import context  # noqa: F401
from lutin import catalogue, conseil
from lutin.machine import Gpu, Profil

CAT = catalogue.charger()


def pc(gpu=None, ram=32.0):
    return Profil(systeme="windows", cpu="Ryzen", coeurs=8, ram_go=ram, ram_libre_go=ram * 0.7, gpus=[gpu] if gpu else [])


def textes(lignes):
    return "\n".join(l["texte"] for l in lignes)


class Seuils(unittest.TestCase):
    def test_qualite(self):
        self.assertEqual([conseil.qualite(v) for v in (60, 25, 24.9, 10, 9.9, 5, 4.9, 0)], ["tres_bien", "tres_bien", "bien", "bien", "lent", "lent", "tres_lent", "tres_lent"])


class Conseils(unittest.TestCase):
    def test_pc_rapide_rien_a_changer(self):
        gpu = Gpu("NVIDIA RTX 4090", "nvidia", 24.0, 22.0, "nvidia-smi")
        l = conseil.analyser({"tok_s": 54.2, "charge_s": 2.1}, pc(gpu), {"modele": "qwen3:8b", "num_ctx": 24576, "num_thread": None}, CAT, ["qwen3:8b"])
        self.assertEqual(l[0]["niveau"], "ok")
        t = textes(l)
        self.assertIn("54 jetons par seconde", t)
        self.assertIn("très confortable", t)
        self.assertIn("300 mots prend environ 7 secondes", t)
        self.assertIn("profil « Discret »", t, "il propose d'être discret quand tout va vite")
        self.assertNotIn("attention", [x["niveau"] for x in l])

    def test_pc_sans_carte_lent_propose_le_modele_rapide_et_un_contexte_plus_court(self):
        l = conseil.analyser({"tok_s": 3.0, "charge_s": 12.0}, pc(None, 32.0), {"modele": "qwen3:30b", "num_ctx": 32768, "num_thread": None}, CAT, [])
        t = textes(l)
        self.assertEqual(l[0]["niveau"], "attention")
        self.assertIn("trop lent", t)
        self.assertIn("Aucune carte graphique utilisable", t)
        self.assertIn("Le modèle rapide conseillé", t)
        self.assertIn("à installer", t)
        self.assertIn("16 384", t)
        self.assertNotIn("profil « Discret »", t)

    def test_modele_deborde_de_la_carte(self):
        gpu = Gpu("NVIDIA RTX 3060", "nvidia", 12.0, 10.0, "nvidia-smi")
        l = conseil.analyser({"tok_s": 6.0}, pc(gpu), {"modele": "qwen3:30b", "num_ctx": 8192}, CAT, ["qwen3:30b"], charge={"taille": 20_000_000_000, "vram": 11_000_000_000})
        self.assertIn("55 % dessus", textes(l))

    def test_modele_rapide_deja_installe_et_dans_les_deux_langues(self):
        choix = conseil.selection.choisir(pc(None, 32.0), CAT)["rapide"]
        l = conseil.analyser({"tok_s": 4.0}, pc(None, 32.0), {"modele": "gros:70b", "num_ctx": 4096}, CAT, [choix.id])
        self.assertIn("déjà installé", textes(l))
        with mock.patch.dict(os.environ, {"LUTIN_LANGUE": "en"}):
            l = conseil.analyser({"tok_s": 4.0}, pc(None, 32.0), {"modele": "gros:70b", "num_ctx": 4096}, CAT, [choix.id])
        self.assertIn("already installed", textes(l))
        self.assertIn("too slow", textes(l))

    def test_vitesse_nulle_ne_plante_pas(self):
        l = conseil.analyser({"tok_s": 0}, pc(None), {"modele": "x", "num_ctx": 8192}, CAT)
        self.assertIn("Vitesse non mesurée", textes(l))


if __name__ == "__main__":
    unittest.main()
