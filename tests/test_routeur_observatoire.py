"""Routeur de modèles (choix selon la demande, reprise avec un modèle plus gros), observatoire (ce que les modèles et outils ont fait) et laboratoire (historique des mesures, régressions)."""
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-routeur-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1",
                    "LUTIN_BENCH": str(_TEMP / "donnees" / "bench.json")}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import moteur as A  # noqa: E402
from lutin import bench, dialogue, observatoire, routeur  # noqa: E402

CATALOGUE = [
    {"id": "qwen3:1.7b", "role": "rapide", "go": 1.4, "capacites": ["outils", "reflexion"]},
    {"id": "granite4:3b", "role": "rapide", "go": 2.1, "capacites": ["outils"]},
    {"id": "qwen3:8b", "role": "polyvalent", "go": 5.2, "capacites": ["outils", "reflexion"]},
    {"id": "qwen3-coder:30b", "role": "code", "go": 18.0, "capacites": ["outils"]},
    {"id": "qwen3:32b", "role": "polyvalent", "go": 20.0, "capacites": ["outils", "reflexion"]},
]
TOUS = ["qwen3:1.7b", "qwen3:8b", "qwen3-coder:30b", "qwen3:32b"]


class Classer(unittest.TestCase):
    def test_profils(self):
        cas = [("salut, ça va ?", "rapide"), ("quelle heure est-il à Tokyo", "rapide"), ("Écris un script python qui renomme des fichiers", "code"), ("pourquoi le ciel est bleu ?", "raisonnement"),
               ("compare ces deux approches et analyse les compromis", "raisonnement"), ("lis le fichier notes.txt et résume", "defaut"), ("x" * 800, "raisonnement"),
               ("```py\nprint(1)\n```", "code"), ("corrige ce bug dans app.js", "code")]
        for texte, attendu in cas:
            self.assertEqual(routeur.classer(texte)[0], attendu, texte)
        self.assertEqual(routeur.classer("regarde cette photo", images=True)[0], "images")
        self.assertEqual(routeur.classer("")[0], "defaut")

    def test_taille_connue_ou_deduite_du_nom(self):
        self.assertEqual(routeur.taille_go("qwen3:8b", CATALOGUE), 5.2)
        self.assertEqual(routeur.taille_go("inconnu:70b", CATALOGUE), 42.0)
        self.assertIsNone(routeur.taille_go("sans-taille", CATALOGUE))


class Choisir(unittest.TestCase):
    def test_code_prend_le_modele_code(self):
        c = routeur.choisir("écris une fonction python", TOUS, "qwen3:8b", CATALOGUE)
        self.assertEqual((c["modele"], c["profil"]), ("qwen3-coder:30b", "code"))
        self.assertIsNone(routeur.choisir("écris une fonction python", TOUS, "qwen3-coder:30b", CATALOGUE), "déjà un modèle code")

    def test_reflexion_prend_le_plus_gros_qui_sait_reflechir_si_le_gain_est_net(self):
        c = routeur.choisir("pourquoi la mer est salée ?", TOUS, "qwen3:8b", CATALOGUE)
        self.assertEqual(c["modele"], "qwen3:32b")
        self.assertIsNone(routeur.choisir("pourquoi la mer est salée ?", TOUS, "qwen3:32b", CATALOGUE))
        self.assertIsNone(routeur.choisir("pourquoi la mer est salée ?", ["qwen3:8b", "granite4:3b"], "qwen3:8b", CATALOGUE), "granite ne sait pas réfléchir : rien à gagner")

    def test_un_modele_trop_gros_pour_la_machine_n_est_jamais_propose(self):
        self.assertIsNone(routeur.choisir("pourquoi la mer est salée ?", TOUS, "qwen3:8b", CATALOGUE, trop_gros={"qwen3:32b"}))
        self.assertIsNone(routeur.choisir("écris une fonction python", TOUS, "qwen3:8b", CATALOGUE, trop_gros={"qwen3-coder:30b"}))

    def test_question_courte_prend_un_petit_modele_seulement_si_c_est_net(self):
        c = routeur.choisir("quelle est la capitale de l'Italie ?", TOUS, "qwen3:8b", CATALOGUE)
        self.assertEqual(c["modele"], "qwen3:1.7b")
        self.assertIsNone(routeur.choisir("quelle est la capitale de l'Italie ?", ["granite4:3b", "qwen3:1.7b"], "granite4:3b", CATALOGUE), "1,4 contre 2,1 Go : pas deux fois plus petit")
        self.assertIsNone(routeur.choisir("salut", TOUS, "modele-inconnu", CATALOGUE), "un modèle inconnu n'est pas rétrogradé à l'aveugle")

    def test_un_seul_modele_installe_rien_a_choisir(self):
        self.assertIsNone(routeur.choisir("écris une fonction python", ["qwen3:8b"], "qwen3:8b", CATALOGUE))

    def test_images_laissees_au_mecanisme_existant(self):
        self.assertIsNone(routeur.choisir("décris", TOUS, "qwen3:8b", CATALOGUE, images=True))

    def test_une_machine_appairee_peut_porter_le_gros_modele(self):
        distants = [{"id": "m" * 32, "nom": "Gros PC", "etat": "operationnel", "modeles": ["llama3.3:70b"]}]
        c = routeur.choisir("analyse en détail les compromis de cette architecture", ["qwen3:8b", "granite4:3b"], "qwen3:8b", CATALOGUE, distants=distants)
        self.assertEqual((c["modele"], c["machine"], c["machine_nom"]), ("llama3.3:70b", "m" * 32, "Gros PC"))
        hors = [dict(distants[0], etat="injoignable")]
        self.assertIsNone(routeur.choisir("analyse en détail les compromis de cette architecture", ["qwen3:8b", "granite4:3b"], "qwen3:8b", CATALOGUE, distants=hors), "une machine éteinte n'est pas proposée")

    def test_plus_gros_pour_la_reprise(self):
        self.assertEqual(routeur.plus_gros("qwen3:1.7b", TOUS, CATALOGUE, exiger_reflexion=False)["modele"], "qwen3:32b")
        self.assertIsNone(routeur.plus_gros("qwen3:32b", TOUS, CATALOGUE, exiger_reflexion=False))


class BrancheeDansLeDialogue(unittest.TestCase):
    def test_le_routage_est_desactive_par_defaut_et_ne_change_pas_le_reglage(self):
        self.assertFalse(A.REGLAGES_DEFAUT["routage"])
        r = {"modele": "qwen3:8b", "machine": ""}
        evenements = []
        self.assertFalse(dialogue.router_la_demande(r, "écris une fonction python", False, evenements.append, "c1"))
        self.assertEqual(r["modele"], "qwen3:8b")
        self.assertEqual(evenements, [])

    def test_le_routage_actif_change_le_modele_de_cette_demande_et_le_dit(self):
        r = {"modele": "qwen3:8b", "machine": "", "routage": True}
        evenements = []
        with mock.patch.object(dialogue, "contexte_routage", lambda: (TOUS, set(), [])), mock.patch.object(A, "MODELES", CATALOGUE):
            self.assertTrue(dialogue.router_la_demande(r, "écris une fonction python", False, evenements.append, "c1"))
        self.assertEqual(r["modele"], "qwen3-coder:30b")
        self.assertIn("Modèle choisi pour cette demande", evenements[0]["texte"])
        self.assertEqual(observatoire.lire(5)[0]["type"], "routage")

    def test_jamais_pendant_une_mission_et_jamais_une_erreur(self):
        r = {"modele": "qwen3:8b", "machine": "", "routage": True, "_mission": True}
        self.assertFalse(dialogue.router_la_demande(r, "écris une fonction python", False, lambda e: None, "c1"))
        r = {"modele": "qwen3:8b", "machine": "", "routage": True}
        with mock.patch.object(dialogue, "contexte_routage", side_effect=RuntimeError("boum")):
            self.assertFalse(dialogue.router_la_demande(r, "écris une fonction python", False, lambda e: None, "c1"))
        self.assertEqual(r["modele"], "qwen3:8b")

    def test_reprise_avec_un_modele_plus_gros_une_seule_fois(self):
        r = {"modele": "qwen3:1.7b", "machine": "", "routage": True}
        corps = {"model": "qwen3:1.7b"}
        evenements = []
        with mock.patch.object(dialogue, "contexte_routage", lambda: (TOUS, set(), [])), mock.patch.object(A, "MODELES", CATALOGUE):
            self.assertTrue(dialogue.monter_en_gamme(r, corps, evenements.append, "c1", "le modèle n'a rien écrit"))
            self.assertEqual((r["modele"], corps["model"]), ("qwen3:32b", "qwen3:32b"))
            self.assertFalse(dialogue.monter_en_gamme(r, corps, evenements.append, "c1", "encore"), "une seule montée par demande")
        self.assertFalse(dialogue.monter_en_gamme({"modele": "qwen3:1.7b", "machine": "", "routage": False}, {}, evenements.append, "c1", "x"))


class Observatoire(unittest.TestCase):
    def setUp(self):
        observatoire.vider()

    def test_noter_lire_resumer(self):
        observatoire.noter("tour", "c1", modele="qwen3:8b", machine="", jetons=100, tok_s=50.0, duree_s=2.0)
        observatoire.noter("tour", "c1", modele="qwen3:8b", machine="", jetons=100, tok_s=25.0, duree_s=4.0)
        observatoire.noter("tour", "c2", modele="gros:70b", machine="m1", jetons=10, tok_s=None)
        observatoire.noter("outil", "c1", outil="lire", duree_ms=40, ok=True, modele="qwen3:8b")
        observatoire.noter("outil", "c1", outil="lire", duree_ms=60, ok=False, detail="Erreur : introuvable")
        observatoire.noter("relance", "c1", motif="réponse vide")
        observatoire.noter("routage", "c1", profil="code", modele="x", raison="code")
        observatoire.noter("inconnu", "c1")          # ignoré
        s = observatoire.resume()
        m = {x["modele"]: x for x in s["modeles"]}
        self.assertEqual((m["qwen3:8b"]["tours"], m["qwen3:8b"]["jetons"], m["qwen3:8b"]["tok_s"]), (2, 200, 33.3), "vitesse moyenne pondérée par les jetons")
        self.assertIsNone(m["gros:70b"]["tok_s"])
        self.assertEqual(m["gros:70b"]["machine"], "m1")
        o = s["outils"][0]
        self.assertEqual((o["outil"], o["appels"], o["echecs"], o["duree_ms"]), ("lire", 2, 1, 50))
        self.assertEqual((s["relances"], s["routages"]), ({"réponse vide": 1}, 1))
        self.assertEqual(len(observatoire.lire()), 7)

    def test_jamais_le_contenu_des_messages_et_valeurs_bornees(self):
        observatoire.noter("outil", "c1", outil="x" * 500, ok=True, args={"secret": 1}, detail="y" * 500)
        e = observatoire.lire()[0]
        self.assertLessEqual(len(e["outil"]), 160)
        self.assertLessEqual(len(e["detail"]), 160)

    def test_borne_et_fichier_abime(self):
        for i in range(observatoire.MAX_EVENEMENTS + 100):
            observatoire.noter("relance", "c", motif="m%d" % i)
        self.assertLessEqual(len(observatoire.lire(10 ** 6)), observatoire.MAX_EVENEMENTS)
        observatoire._chemin().write_text("pas du json\n{\"type\": \"relance\", \"motif\": \"ok\"}\n", encoding="utf-8")
        self.assertEqual([e["motif"] for e in observatoire.lire()], ["ok"])

    def test_ecrire_ne_leve_jamais(self):
        with mock.patch.object(observatoire, "_chemin", side_effect=OSError("disque plein")):
            observatoire.noter("relance", "c", motif="x")


class Laboratoire(unittest.TestCase):
    def mesure(self, tok_s, outils=(4, 4), code=(3, 3), moteur=("ollama", "0.12"), date="2026-11-01T10:00:00"):
        return {"modele": "qwen3:8b", "date": date, "moteur": {"id": moteur[0], "version": moteur[1]}, "machine": "x",
                "resultats": {"vitesse": {"tok_s": tok_s}, "outils": {"points": outils[0], "sur": outils[1]}, "code": {"points": code[0], "sur": code[1]}}, "notes": {}}

    def setUp(self):
        self.chemin = _TEMP / "donnees" / "bench-lab.json"
        bench.chemin_historique(self.chemin).unlink(missing_ok=True)

    def test_chaque_mesure_est_gardee_et_la_derniere_remplace_la_precedente_dans_bench_json(self):
        bench.enregistrer(self.chemin, self.mesure(40))
        bench.enregistrer(self.chemin, self.mesure(41))
        self.assertEqual(len(bench.lire_historique(self.chemin)["qwen3:8b"]), 2)
        self.assertEqual(bench.lire(self.chemin)["qwen3:8b"]["resultats"]["vitesse"]["tok_s"], 41)

    def test_une_baisse_nette_de_vitesse_est_une_regression_et_dit_si_le_moteur_a_change(self):
        bench.enregistrer(self.chemin, self.mesure(40))
        bench.enregistrer(self.chemin, self.mesure(25, moteur=("ollama", "0.13"), date="2026-11-08T10:00:00"))
        g = bench.regressions(self.chemin)
        self.assertEqual([(x["genre"], x["avant"], x["apres"], x["moteur_change"]) for x in g], [("vitesse", 40, 25, True)])

    def test_une_epreuve_qui_chute_est_signalee_une_petite_variation_non(self):
        bench.enregistrer(self.chemin, self.mesure(40, outils=(4, 4)))
        bench.enregistrer(self.chemin, self.mesure(38, outils=(2, 4), code=(3, 3)))
        self.assertEqual([(x["genre"], x["avant"], x["apres"]) for x in bench.regressions(self.chemin)], [("outils", 1.0, 0.5)])

    def test_une_seule_mesure_ou_une_amelioration_ne_signale_rien(self):
        bench.enregistrer(self.chemin, self.mesure(30))
        self.assertEqual(bench.regressions(self.chemin), [])
        bench.enregistrer(self.chemin, self.mesure(45))
        self.assertEqual(bench.regressions(self.chemin), [])

    def test_historique_borne_et_abime(self):
        bench.chemin_historique(self.chemin).write_text("pas du json\n", encoding="utf-8")
        bench.enregistrer(self.chemin, self.mesure(40))
        self.assertEqual(len(bench.lire_historique(self.chemin)["qwen3:8b"]), 1)
        bench.noter_historique(self.chemin, {"pas": "une mesure"})          # ne lève pas


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lutin import securite as S
        cls.serveur = ThreadingHTTPServer(("127.0.0.1", 0), A.Gestionnaire)
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()
        cls.port = cls.serveur.server_address[1]
        cls.avant = A.SECURITE
        A.SECURITE = S.Securite(niveau=S.LOCAL)

    @classmethod
    def tearDownClass(cls):
        A.SECURITE = cls.avant
        cls.serveur.shutdown()

    def appel(self, methode, chemin, corps=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": "127.0.0.1:%d" % self.port, "X-Token": A.JETON}
        donnees = json.dumps(corps).encode() if corps is not None else None
        if donnees:
            h["Content-Type"] = "application/json"
        c.request(methode, chemin, body=donnees, headers=h)
        r = c.getresponse()
        texte = r.read().decode("utf-8")
        c.close()
        return r.status, json.loads(texte) if texte else {}

    def test_observatoire_par_l_api(self):
        observatoire.vider()
        observatoire.noter("tour", "c1", modele="qwen3:8b", machine="", jetons=50, tok_s=25.0)
        observatoire.noter("outil", "c1", outil="lire", duree_ms=10, ok=True)
        statut, r = self.appel("GET", "/api/observatoire")
        self.assertEqual(statut, 200)
        self.assertEqual(r["resume"]["modeles"][0]["modele"], "qwen3:8b")
        self.assertEqual([e["type"] for e in r["recents"]], ["outil"], "les tours sont dans le résumé, pas dans la liste des évènements")
        self.assertEqual(self.appel("POST", "/api/observatoire-vider", {})[0], 200)
        self.assertEqual(self.appel("GET", "/api/observatoire")[1]["resume"]["modeles"], [])

    def test_historique_des_mesures_par_l_api(self):
        chemin = A.chemin_bench()
        bench.chemin_historique(chemin).unlink(missing_ok=True)
        l = Laboratoire()
        bench.enregistrer(chemin, l.mesure(40))
        bench.enregistrer(chemin, l.mesure(20, date="2026-11-08T10:00:00"))
        statut, r = self.appel("GET", "/api/bench-historique")
        self.assertEqual(statut, 200)
        self.assertEqual(r["regressions"][0]["genre"], "vitesse")
        self.assertEqual(len(r["modeles"][0]["mesures"]), 2)

    def test_le_reglage_routage_se_enregistre(self):
        statut, r = self.appel("POST", "/api/reglages", {"routage": True})
        self.assertEqual((statut, r.get("routage")), (200, True))
        self.assertTrue(self.appel("GET", "/api/etat")[1]["reglages"]["routage"])
        self.appel("POST", "/api/reglages", {"routage": False})


if __name__ == "__main__":
    unittest.main()
