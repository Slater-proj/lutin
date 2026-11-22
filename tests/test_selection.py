import copy
import json
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import model_catalog, model_selection
from lutin.hardware import Gpu, Profile

CAT = model_catalog.load()


def profil(vram=None, ram=32.0, fabricant="nvidia"):
    return Profile(systeme="windows", ram_go=ram, ram_libre_go=ram * 0.6, gpus=[Gpu("Carte", fabricant, vram)] if vram is not None else [])


class Catalogue(unittest.TestCase):
    def test_le_catalogue_livre_est_valide(self):
        model_catalog.validate(CAT)

    def test_chaque_role_a_au_moins_un_modele_et_une_phrase(self):
        for role in model_catalog.ROLES:
            self.assertTrue([m for m in CAT["modeles"] if m["notes"].get(role, 0) >= model_selection.SCORE_THRESHOLD and "outils" in m["capacites"]], role)
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
            with self.assertRaises(model_catalog.CatalogError):
                model_catalog.validate(c)

    def test_cache_plus_recent_gagne_cache_abime_ignore(self):
        with tempfile.TemporaryDirectory() as t:
            cache = Path(t) / "c.json"
            plus_recent = copy.deepcopy(CAT); plus_recent["version"] += 1
            cache.write_text(json.dumps(plus_recent), encoding="utf-8")
            self.assertEqual(model_catalog.load(cache)["version"], CAT["version"] + 1)
            cache.write_text("{pas du json", encoding="utf-8")
            self.assertEqual(model_catalog.load(cache)["version"], CAT["version"])
            plus_vieux = copy.deepcopy(CAT); plus_vieux["version"] = 0
            cache.write_text(json.dumps(plus_vieux), encoding="utf-8")
            self.assertEqual(model_catalog.load(cache)["version"], CAT["version"])


class Selection(unittest.TestCase):
    def test_propriete_tout_choix_tient_dans_le_budget(self):
        """Pour toute taille de mémoire vidéo de 0 à 96 Go, aucun choix ne dépasse ce que la machine peut porter."""
        for vram in [None] + [v / 2 for v in range(2, 193)]:
            p = profil(vram, ram=32)
            for role, c in model_selection.choose(p, CAT).items():
                if c is None:
                    continue
                # Un modèle à experts « partiel » : la carte pleine, le reste des experts dans la mémoire vive libre mesurée moins la réserve du système,
                # et tout ce qui n'est pas un expert (plus la conversation) sur la carte.
                limite = p.budget_go() + (max(0.0, p.ram_libre_go - model_selection.RAM_RESERVE_GB) if c.tient == "partiel" else 0)
                self.assertLessEqual(c.memoire_go, limite + 0.1, "{} Go / {} : {} dépasse".format(vram, role, c.id))
                if c.tient == "partiel":
                    socle = model_selection.required_memory_gb(c.modele, c.num_ctx) - c.modele["go"] * model_selection.expert_share(c.modele)
                    self.assertLessEqual(socle, p.budget_go() + 1e-6, "{} Go / {} : {} ne garde pas l'essentiel sur la carte".format(vram, role, c.id))
                self.assertIn("outils", c.modele["capacites"])
                self.assertGreaterEqual(c.modele["notes"][role], model_selection.SCORE_THRESHOLD)
                self.assertGreaterEqual(c.num_ctx, 1024)

    def test_propriete_plus_de_memoire_jamais_un_modele_moins_bien_note(self):
        for role in ("polyvalent", "code", "creatif"):
            precedent = 0
            for vram in range(4, 97, 2):
                c = model_selection.choose(profil(vram), CAT)[role]
                note = c.modele["notes"][role] if c else 0
                self.assertGreaterEqual(note, precedent - 1, "{} Go {}".format(vram, role))      # tolérance 1 : un partiel peut céder la place
                precedent = max(precedent, note)

    def test_polyvalent_existe_des_8_go(self):
        for vram in (8, 12, 16, 24, 48):
            self.assertIsNotNone(model_selection.choose(profil(vram), CAT)["polyvalent"], vram)

    def test_machine_modeste_et_sans_gpu_ont_un_choix_honnete(self):
        c = model_selection.choose(profil(None, ram=16), CAT)
        self.assertEqual(c["polyvalent"].tient, "cpu")
        self.assertLessEqual(c["polyvalent"].modele["go"], 9.6)
        tout_petit = model_selection.choose(profil(None, ram=4), CAT)
        self.assertTrue(all(x is None or x.modele["go"] < 2.5 for x in tout_petit.values()))

    def test_carte_24_go_prend_un_gros_modele_et_un_rapide_leger(self):
        c = model_selection.choose(profil(24), CAT)
        self.assertGreaterEqual(c["polyvalent"].modele["go"], 13)
        self.assertGreaterEqual(c["code"].modele["notes"]["code"], 8)
        self.assertLessEqual(c["rapide"].memoire_go, 20.4)
        self.assertIn("vision", c["vision"].modele["capacites"])

    def test_un_modele_sans_filtre_n_est_jamais_choisi_automatiquement(self):
        for vram in (8, 24, 48, 96):
            for c in model_selection.choose(profil(vram), CAT).values():
                self.assertFalse(c and c.modele.get("avance"))

    def test_liste_cache_les_avances_sauf_option(self):
        sans = [x["modele"]["id"] for x in model_selection.list_models(profil(24), CAT)]
        avec = [x["modele"]["id"] for x in model_selection.list_models(profil(24), CAT, avance=True)]
        self.assertFalse([i for i in sans if "abliterated" in i])
        self.assertTrue([i for i in avec if "abliterated" in i])

    def test_liste_marque_ce_qui_ne_tient_pas(self):
        par_id = {x["modele"]["id"]: x for x in model_selection.list_models(profil(8), CAT)}
        self.assertIsNone(par_id["llama3.3:70b"]["tient"])
        self.assertEqual(par_id["qwen3:4b"]["tient"], "gpu")

    def test_moe_deborde_en_ram_et_le_dit(self):
        c = model_selection.best_context(next(m for m in CAT["modeles"] if m["id"] == "qwen3:30b"), budget_go=14, ram_libre_go=30)
        self.assertEqual(c[2], "partiel")
        self.assertIsNone(model_selection.best_context(next(m for m in CAT["modeles"] if m["id"] == "qwen3:32b"), budget_go=14, ram_libre_go=60), "un modèle dense ne déborde pas")

    def test_un_moe_tient_si_la_carte_garde_l_essentiel_et_la_memoire_vive_mesuree_le_reste(self):
        """Demande du mainteneur (2026-11-20) : cohérent avec la machine mesurée. RTX 4090 (24 Go) et 32 Go de mémoire vive dont 22 libres."""
        par_id = {m["id"]: m for m in CAT["modeles"]}
        budget = 24 * 0.85
        ctx, besoin, tient = model_selection.best_context(par_id["qwen3.6:35b"], budget, 22)
        self.assertEqual((tient, ctx), ("partiel", 32768), "22,6 Go : un peu d'experts en mémoire vive, et toute la conversation")
        self.assertLessEqual(besoin - budget, 22 - model_selection.RAM_RESERVE_GB)
        self.assertIsNone(model_selection.best_context(par_id["qwen3-next:80b"], budget, 22), "50 Go : 30 en mémoire vive, il n'y en a que 20 de disponibles")
        self.assertIsNone(model_selection.best_context(par_id["gpt-oss:120b"], budget, 22))
        self.assertEqual(model_selection.best_context(par_id["qwen3-next:80b"], budget, 52)[2], "partiel", "avec 64 Go (52 libres), il tient")

    def test_un_moe_ne_deborde_que_si_le_moteur_sait_le_faire(self):
        m = next(m for m in CAT["modeles"] if m["id"] == "qwen3.6:35b")
        self.assertEqual(model_selection.best_context(m, 20.4, 22)[2], "partiel")
        self.assertIsNone(model_selection.best_context(m, 20.4, 22, experts_en_ram=False))
        roles = model_selection.choose(profil(24, ram=32), CAT, experts_en_ram=False)
        self.assertFalse([c for c in roles.values() if c is not None and c.tient == "partiel"], "aucun choix ne compte sur des experts en mémoire vive")

    def test_ce_qui_n_est_pas_un_expert_reste_sur_la_carte(self):
        m = next(m for m in CAT["modeles"] if m["id"] == "qwen3-next:80b")
        self.assertIsNone(model_selection.best_context(m, 2.0, 500), "même avec beaucoup de mémoire vive, l'attention et la conversation doivent tenir sur la carte")
        self.assertEqual(model_selection.expert_share({"params_b": 32, "actifs_b": 32}), 0.0, "un modèle dense n'a pas d'experts")
        self.assertAlmostEqual(model_selection.expert_share(m), 1 - 3.9 / 79.7)

    def test_la_conversation_la_plus_longue_qui_tient_encore(self):
        m = next(m for m in CAT["modeles"] if m["id"] == "glm-4.7-flash:latest")          # 105 Mo par millier de jetons : la conversation pèse
        larges = model_selection.best_context(m, 10.2, 40)
        serre = model_selection.best_context(m, 10.2, 12.5)
        self.assertEqual((larges[2], serre[2]), ("partiel", "partiel"))
        self.assertGreater(larges[0], serre[0], "moins de mémoire vive : une conversation plus courte plutôt que rien")

    def test_un_moe_prefere_quelques_experts_en_memoire_vive_a_une_courte_conversation(self):
        m = next(m for m in CAT["modeles"] if m["id"] == "gemma4:26b")          # 19 Go et une conversation lourde : sur 20,4 Go, la carte seule laisse 8 192 jetons
        self.assertEqual(model_selection.best_context(m, 20.4, 22, experts_en_ram=False)[::2], (8192, "gpu"))
        ctx, _, tient = model_selection.best_context(m, 20.4, 22)
        self.assertEqual(tient, "partiel")
        self.assertGreaterEqual(ctx, model_selection.COMFORT_CTX)
        self.assertEqual(model_selection.best_context(m, 20.4, 2)[::2], (8192, "gpu"), "sans mémoire vive libre, la carte seule reste le choix")

    def test_defaut_et_total_a_telecharger(self):
        c = model_selection.choose(profil(24), CAT)
        coches = model_selection.default_choice(c)
        self.assertEqual(coches[0], "polyvalent")
        liste, total = model_selection.to_download(c, ["polyvalent", "rapide", "code"])
        self.assertEqual(len({x.id for x in liste}), len(liste), "pas de doublon")
        self.assertAlmostEqual(total, sum(x.modele["go"] for x in liste), places=1)
        _, rien = model_selection.to_download(c, ["polyvalent"], deja_installes=[c["polyvalent"].id])
        self.assertEqual(rien, 0)


if __name__ == "__main__":
    unittest.main()
