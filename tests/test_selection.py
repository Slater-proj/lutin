import copy
import json
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import catalogue, selection
from lutin.machine import Gpu, Profil

CAT = catalogue.charger()


def profil(vram=None, ram=32.0, fabricant="nvidia"):
    return Profil(systeme="windows", ram_go=ram, ram_libre_go=ram * 0.6, gpus=[Gpu("Carte", fabricant, vram)] if vram is not None else [])


class Catalogue(unittest.TestCase):
    def test_le_catalogue_livre_est_valide(self):
        catalogue.valider(CAT)

    def test_chaque_role_a_au_moins_un_modele_et_une_phrase(self):
        for role in catalogue.ROLES:
            self.assertTrue([m for m in CAT["modeles"] if m["notes"].get(role, 0) >= selection.SEUIL_NOTE and "outils" in m["capacites"]], role)
        for m in CAT["modeles"]:
            self.assertTrue(m["phrase"].endswith("."), m["id"])

    def test_defauts_detectes(self):
        mauvais = []
        c = copy.deepcopy(CAT); c["modeles"][0].pop("go"); mauvais.append(c)
        c = copy.deepcopy(CAT); c["modeles"][1]["id"] = c["modeles"][0]["id"]; mauvais.append(c)
        c = copy.deepcopy(CAT); c["modeles"][0]["capacites"] = ["telepathie"]; mauvais.append(c)
        c = copy.deepcopy(CAT); c["modeles"][0]["phrase"] = "x" * 200; mauvais.append(c)
        c = copy.deepcopy(CAT); c["modeles"][0]["notes"] = {"rapide": 11}; mauvais.append(c)
        c = copy.deepcopy(CAT); c["modeles"][0]["notes"] = {"vision": 7}; c["modeles"][0]["capacites"] = ["outils"]; mauvais.append(c)
        c = copy.deepcopy(CAT); [m for m in c["modeles"] if m.get("avance")][0].pop("avertissement"); mauvais.append(c)
        mauvais += [{}, {"version": 1, "modeles": []}, {"modeles": [{}]}]
        for c in mauvais:
            with self.assertRaises(catalogue.ErreurCatalogue):
                catalogue.valider(c)

    def test_cache_plus_recent_gagne_cache_abime_ignore(self):
        with tempfile.TemporaryDirectory() as t:
            cache = Path(t) / "c.json"
            plus_recent = copy.deepcopy(CAT); plus_recent["version"] += 1
            cache.write_text(json.dumps(plus_recent), encoding="utf-8")
            self.assertEqual(catalogue.charger(cache)["version"], CAT["version"] + 1)
            cache.write_text("{pas du json", encoding="utf-8")
            self.assertEqual(catalogue.charger(cache)["version"], CAT["version"])
            plus_vieux = copy.deepcopy(CAT); plus_vieux["version"] = 0
            cache.write_text(json.dumps(plus_vieux), encoding="utf-8")
            self.assertEqual(catalogue.charger(cache)["version"], CAT["version"])


class Selection(unittest.TestCase):
    def test_propriete_tout_choix_tient_dans_le_budget(self):
        """Pour toute taille de mémoire vidéo de 0 à 96 Go, aucun choix ne dépasse ce que la machine peut porter."""
        for vram in [None] + [v / 2 for v in range(2, 193)]:
            p = profil(vram, ram=32)
            for role, c in selection.choisir(p, CAT).items():
                if c is None:
                    continue
                limite = p.budget_go() + (p.ram_libre_go * 0.5 if c.tient == "partiel" else 0)
                self.assertLessEqual(c.memoire_go, limite + 1e-6, "{} Go / {} : {} dépasse".format(vram, role, c.id))
                self.assertIn("outils", c.modele["capacites"])
                self.assertGreaterEqual(c.modele["notes"][role], selection.SEUIL_NOTE)
                self.assertGreaterEqual(c.num_ctx, 1024)

    def test_propriete_plus_de_memoire_jamais_un_modele_moins_bien_note(self):
        for role in ("polyvalent", "code", "creatif"):
            precedent = 0
            for vram in range(4, 97, 2):
                c = selection.choisir(profil(vram), CAT)[role]
                note = c.modele["notes"][role] if c else 0
                self.assertGreaterEqual(note, precedent - 1, "{} Go {}".format(vram, role))      # tolérance 1 : un partiel peut céder la place
                precedent = max(precedent, note)

    def test_polyvalent_existe_des_8_go(self):
        for vram in (8, 12, 16, 24, 48):
            self.assertIsNotNone(selection.choisir(profil(vram), CAT)["polyvalent"], vram)

    def test_machine_modeste_et_sans_gpu_ont_un_choix_honnete(self):
        c = selection.choisir(profil(None, ram=16), CAT)
        self.assertEqual(c["polyvalent"].tient, "cpu")
        self.assertLessEqual(c["polyvalent"].modele["go"], 9.6)
        tout_petit = selection.choisir(profil(None, ram=4), CAT)
        self.assertTrue(all(x is None or x.modele["go"] < 2.5 for x in tout_petit.values()))

    def test_carte_24_go_prend_un_gros_modele_et_un_rapide_leger(self):
        c = selection.choisir(profil(24), CAT)
        self.assertGreaterEqual(c["polyvalent"].modele["go"], 13)
        self.assertGreaterEqual(c["code"].modele["notes"]["code"], 8)
        self.assertLessEqual(c["rapide"].memoire_go, 20.4)
        self.assertIn("vision", c["vision"].modele["capacites"])

    def test_un_modele_sans_filtre_n_est_jamais_choisi_automatiquement(self):
        for vram in (8, 24, 48, 96):
            for c in selection.choisir(profil(vram), CAT).values():
                self.assertFalse(c and c.modele.get("avance"))

    def test_liste_cache_les_avances_sauf_option(self):
        sans = [x["modele"]["id"] for x in selection.lister(profil(24), CAT)]
        avec = [x["modele"]["id"] for x in selection.lister(profil(24), CAT, avance=True)]
        self.assertFalse([i for i in sans if "abliterated" in i])
        self.assertTrue([i for i in avec if "abliterated" in i])

    def test_liste_marque_ce_qui_ne_tient_pas(self):
        par_id = {x["modele"]["id"]: x for x in selection.lister(profil(8), CAT)}
        self.assertIsNone(par_id["llama3.3:70b"]["tient"])
        self.assertEqual(par_id["qwen3:4b"]["tient"], "gpu")

    def test_moe_deborde_en_ram_et_le_dit(self):
        c = selection.meilleur_contexte(next(m for m in CAT["modeles"] if m["id"] == "qwen3:30b"), budget_go=14, ram_libre_go=30)
        self.assertEqual(c[2], "partiel")
        self.assertIsNone(selection.meilleur_contexte(next(m for m in CAT["modeles"] if m["id"] == "qwen3:32b"), budget_go=14, ram_libre_go=60), "un modèle dense ne déborde pas")

    def test_defaut_et_total_a_telecharger(self):
        c = selection.choisir(profil(24), CAT)
        coches = selection.par_defaut(c)
        self.assertEqual(coches[0], "polyvalent")
        liste, total = selection.a_telecharger(c, ["polyvalent", "rapide", "code"])
        self.assertEqual(len({x.id for x in liste}), len(liste), "pas de doublon")
        self.assertAlmostEqual(total, sum(x.modele["go"] for x in liste), places=1)
        _, rien = selection.a_telecharger(c, ["polyvalent"], deja_installes=[c["polyvalent"].id])
        self.assertEqual(rien, 0)


if __name__ == "__main__":
    unittest.main()
