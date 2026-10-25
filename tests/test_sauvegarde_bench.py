import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import context  # noqa: F401
from lutin import bench, config, sauvegarde
from lutin.ollama_client import ErreurOllama


def installation(racine):
    d = config.dossiers({"LUTIN_HOME": str(racine)})
    config.preparer(d)
    (d["config"] / "config.json").write_text(json.dumps({"installe": True}), encoding="utf-8")
    (d["config"] / "appareils.json").write_text(json.dumps({"hash": {"nom": "Téléphone"}}), encoding="utf-8")
    (d["donnees"] / "conversations").mkdir(parents=True, exist_ok=True)
    (d["donnees"] / "conversations" / "abcd1234.json").write_text(json.dumps({"id": "abcd1234", "titre": "Une conversation", "messages": []}), encoding="utf-8")
    (d["donnees"] / "conversations" / "abcd1234.json.bak").write_text("copie", encoding="utf-8")
    (d["donnees"] / "reglages.json").write_text(json.dumps({"modele": "qwen3:8b"}), encoding="utf-8")
    (d["donnees"] / "console.json").write_text(json.dumps({"jeton": "secret"}), encoding="utf-8")
    (d["donnees"] / "lutin.log").write_text("journal technique", encoding="utf-8")
    (d["donnees"] / "sauvegardes").mkdir(exist_ok=True)
    (d["donnees"] / "sauvegardes" / "gros.bin").write_bytes(b"x" * 1000)
    (d["memoire"] / "MEMOIRE.md").write_text("# Mémoire\nje préfère le thé\n", encoding="utf-8")
    (d["cache"] / "catalogue.json").write_text("{}", encoding="utf-8")
    return d


class Sauvegarde(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.d = installation(Path(self.t.name) / "a")

    def tearDown(self):
        self.t.cleanup()

    def noms(self, archive):
        with zipfile.ZipFile(archive) as z:
            return set(z.namelist())

    def test_contenu_et_exclusions(self):
        tampon = io.BytesIO()
        resume = sauvegarde.exporter(self.d, tampon)
        noms = self.noms(tampon)
        self.assertIn("config/config.json", noms)
        self.assertIn("donnees/conversations/abcd1234.json", noms)
        self.assertIn("donnees/reglages.json", noms)
        self.assertIn("memoire/MEMOIRE.md", noms)
        self.assertIn(sauvegarde.MANIFESTE, noms)
        for jamais in ("config/appareils.json", "donnees/console.json", "donnees/lutin.log", "donnees/sauvegardes/gros.bin", "donnees/conversations/abcd1234.json.bak", "cache/catalogue.json"):
            self.assertNotIn(jamais, noms, jamais + " ne doit jamais être exporté")
        self.assertEqual(resume["fichiers"], len(noms) - 1)

    def test_aller_retour_vers_une_autre_installation(self):
        archive = Path(self.t.name) / "sauvegarde.zip"
        sauvegarde.exporter(self.d, archive)
        autre = config.dossiers({"LUTIN_HOME": str(Path(self.t.name) / "b")})
        config.preparer(autre)
        r = sauvegarde.restaurer(autre, archive, autre["cache"])
        self.assertGreaterEqual(r["fichiers"], 4)
        self.assertEqual(json.loads((autre["donnees"] / "conversations" / "abcd1234.json").read_text(encoding="utf-8"))["titre"], "Une conversation")
        self.assertIn("thé", (autre["memoire"] / "MEMOIRE.md").read_text(encoding="utf-8"))
        self.assertFalse((autre["config"] / "appareils.json").exists(), "les accès ne voyagent pas")
        self.assertTrue(list(autre["cache"].glob("avant-restauration-*.zip")), "l'état précédent est gardé")

    def test_restaurer_remplace_et_garde_l_ancien_dans_le_zip_de_secours(self):
        archive = Path(self.t.name) / "s.zip"
        sauvegarde.exporter(self.d, archive)
        (self.d["memoire"] / "MEMOIRE.md").write_text("modifié après la sauvegarde", encoding="utf-8")
        r = sauvegarde.restaurer(self.d, archive, self.d["cache"])
        self.assertIn("thé", (self.d["memoire"] / "MEMOIRE.md").read_text(encoding="utf-8"))
        with zipfile.ZipFile(r["secours"]) as z:
            self.assertEqual(z.read("memoire/MEMOIRE.md").decode("utf-8"), "modifié après la sauvegarde")

    def fabriquer(self, membres):
        chemin = Path(self.t.name) / "piege.zip"
        with zipfile.ZipFile(chemin, "w") as z:
            z.writestr(sauvegarde.MANIFESTE, "{}")
            for nom, contenu in membres.items():
                z.writestr(nom, contenu)
        return chemin

    def test_archives_pieges_refusees_sans_rien_ecrire(self):
        for nom in ("../evil.txt", "config/../../evil.txt", "/etc/passwd", "C:/Windows/x", "config\\..\\x", "autre/fichier.txt", "config/inconnu.exe", "donnees/conversations/sous/x.json",
                    "donnees/conversations/x.exe", "memoire/../../x", "config/", "donnees/lutin.log", "config/appareils.json"):
            with self.subTest(nom):
                archive = self.fabriquer({nom: "x"}) if not nom.endswith("/") else self.fabriquer({"config/ok.json": "x", nom + "../z": "y"})
                avant = sorted(str(p) for p in Path(self.t.name).rglob("*"))
                with self.assertRaises(sauvegarde.ErreurSauvegarde):
                    sauvegarde.restaurer(self.d, archive, self.d["cache"])
                self.assertEqual(sorted(str(p) for p in Path(self.t.name).rglob("*")), avant, "rien n'a été créé ni modifié")

    def test_ce_n_est_pas_une_sauvegarde(self):
        faux = Path(self.t.name) / "faux.zip"
        faux.write_text("pas un zip", encoding="utf-8")
        with self.assertRaises(sauvegarde.ErreurSauvegarde):
            sauvegarde.verifier(faux)
        sans_manifeste = Path(self.t.name) / "sans.zip"
        with zipfile.ZipFile(sans_manifeste, "w") as z:
            z.writestr("config/config.json", "{}")
        with self.assertRaises(sauvegarde.ErreurSauvegarde):
            sauvegarde.verifier(sans_manifeste)

    def test_lien_symbolique_refuse(self):
        chemin = Path(self.t.name) / "lien.zip"
        with zipfile.ZipFile(chemin, "w") as z:
            z.writestr(sauvegarde.MANIFESTE, "{}")
            info = zipfile.ZipInfo("memoire/lien.md")
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
        with self.assertRaises(sauvegarde.ErreurSauvegarde):
            sauvegarde.verifier(chemin)

    def test_verifier_renvoie_le_manifeste(self):
        archive = Path(self.t.name) / "s.zip"
        sauvegarde.exporter(self.d, archive)
        m = sauvegarde.verifier(archive)
        self.assertIn("lutin", m)
        self.assertGreater(m["octets"], 0)


class Faux:
    """Faux Ollama : répond selon la question, avec des durées connues."""

    def __init__(self, bons=True, tok_s=40.0, sans_think=False, panne_a=None):
        self.bons, self.tok_s, self.sans_think, self.panne_a, self.appels = bons, tok_s, sans_think, panne_a, []

    def json(self, chemin, corps=None, delai=5, methode=None):
        self.appels.append(corps)
        if self.sans_think and "think" in corps:
            raise ErreurOllama("does not support thinking")
        question = corps["messages"][-1]["content"]
        if self.panne_a and self.panne_a in question:
            raise ErreurOllama("Ollama s'est arrêté")
        duree = {"load_duration": 2_000_000_000, "eval_count": 200, "eval_duration": int(200 / self.tok_s * 1e9), "prompt_eval_count": 30, "prompt_eval_duration": 100_000_000}
        def r(contenu="", appels=None):
            m = {"role": "assistant", "content": contenu}
            if appels:
                m["tool_calls"] = appels
            return dict({"message": m, "done": True}, **duree)
        if "texte d'environ 150 mots" in question:
            return r("La mer " * 100)
        if corps.get("tools"):
            if "notes.md" in question:
                return r("", [{"function": {"name": "lire", "arguments": {"chemin": "docs/notes.md"}}}] if self.bons else None) if self.bons else r("Voici le fichier.")
            if "connexion" in question:
                return r("", [{"function": {"name": "chercher", "arguments": json.dumps({"motif": "connexion"})}}]) if self.bons else r("Je ne sais pas.")
            return r("Très bien, merci !")
        reponses = {"x[0] * 10": "13", "sum(i * i": "14", "[::-1]": "<think>je réfléchis</think>CBA", "range(2, 10, 3)": "3",
                    "ciel est bleu": "Le ciel est bleu parce que la lumière du soleil est diffusée par l'atmosphère de la Terre.",
                    "3 conseils": "- Couche-toi à heure fixe\n- Évite les écrans le soir\n- Garde la chambre fraîche",
                    "objet JSON": "```json\n{\"ville\": \"Paris\", \"pays\": \"France\"}\n```"}
        for cle, rep in reponses.items():
            if cle in question:
                return r(rep if self.bons else "je ne sais pas, peut-être 42 ou 7 ou autre chose")
        return r("?")


class Banc(unittest.TestCase):
    def test_modele_parfait(self):
        m = bench.executer(Faux(True, 40.0), "qwen3:8b", resume_machine="PC test")
        r = m["resultats"]
        self.assertEqual((r["outils"]["points"], r["code"]["points"], r["francais"]["points"], r["consignes"]["points"]), (3, 4, 2, 1))
        self.assertEqual(r["vitesse"]["tok_s"], 40.0)
        self.assertEqual(r["vitesse"]["charge_s"], 2.0)
        self.assertEqual(m["notes"], {"code": 10, "creatif": 10, "polyvalent": 10, "rapide": 8})
        self.assertTrue(m["complet"] and "erreur" not in m)
        self.assertIn("40 jetons/s", bench.resume(m))

    def test_mauvais_modele(self):
        m = bench.executer(Faux(False, 5.0), "petit")
        self.assertEqual(m["resultats"]["code"]["points"], 0)
        self.assertEqual(m["resultats"]["outils"]["points"], 1, "seule la question sans outil est réussie")
        self.assertLessEqual(m["notes"]["rapide"], 2)
        self.assertLess(m["notes"]["polyvalent"], 4)

    def test_modele_rapide_mais_sans_outils_est_plafonne(self):
        m = bench.executer(Faux(False, 120.0), "rapide-sans-outils")
        self.assertEqual(m["notes"]["rapide"], 4, "très rapide, mais inutilisable pour Lutin sans appel d'outils")

    def test_mode_rapide_ne_fait_que_la_vitesse(self):
        faux = Faux(True, 40.0)
        m = bench.executer(faux, "m", rapide=True)
        self.assertEqual(list(m["resultats"]), ["vitesse"])
        self.assertFalse(m["complet"])
        self.assertEqual(list(m["notes"]), ["rapide"])
        self.assertEqual(len(faux.appels), 1)

    def test_modele_qui_refuse_think_est_reessaye_sans(self):
        faux = Faux(True, sans_think=True)
        m = bench.executer(faux, "ancien")
        self.assertNotIn("erreur", m)
        self.assertEqual(m["resultats"]["code"]["points"], 4)
        self.assertTrue(all("think" not in c for c in faux.appels[1:]))

    def test_panne_en_cours_de_route_garde_ce_qui_est_mesure(self):
        m = bench.executer(Faux(True, panne_a="ciel est bleu"), "tombe")
        self.assertIn("Français", m["erreur"])
        self.assertIn("vitesse", m["resultats"])
        self.assertIn("code", m["resultats"])
        self.assertNotIn("francais", m["resultats"])
        self.assertNotIn("polyvalent", m["notes"], "pas de note globale sur une mesure incomplète")

    def test_progression(self):
        vu = []
        bench.executer(Faux(), "m", progression=lambda nom, i, n: vu.append((nom, i, n)))
        self.assertEqual(vu[0], ("Vitesse", 0, 5))
        self.assertEqual(vu[-1][1:], (4, 5))

    def test_aucun_code_du_modele_n_est_execute(self):
        import inspect
        source = inspect.getsource(bench)
        for interdit in ("exec(", "eval(", "subprocess", "os.system", "compile("):
            self.assertNotIn(interdit, source)

    def test_verifications_pures(self):
        self.assertTrue(bench.reponse_exacte("La valeur est 13", "13"))
        self.assertTrue(bench.reponse_exacte("```\n13\n```", "13"))
        self.assertFalse(bench.reponse_exacte("113", "13"))
        self.assertFalse(bench.reponse_exacte("13.5", "13"))
        self.assertFalse(bench.reponse_exacte("x" * 500 + " 13", "13"))
        self.assertTrue(bench.reponse_exacte("<think>peut-être 7</think>CBA", "cba"))
        self.assertTrue(bench.est_francais("Le ciel est bleu parce que la lumière est diffusée dans l'air."))
        self.assertFalse(bench.est_francais("The sky is blue because of the way light is scattered in the air."))
        self.assertTrue(bench.trois_puces("- a\n- b\n- c"))
        self.assertFalse(bench.trois_puces("Voici :\n- a\n- b\n- c\n- d"))
        self.assertFalse(bench.trois_puces("Intro\nSuite\n- a\n- b\n- c"))
        self.assertTrue(bench.json_valide('```json\n{"ville": "Paris", "pays": "France"}\n```'))
        self.assertFalse(bench.json_valide('Voici : {"ville": "Paris"}'))
        self.assertEqual([bench.note_vitesse(x) for x in (3, 10, 20, 40, 100)], [2, 4, 6, 8, 10])

    def test_enregistrer_lire_exporter(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "cache" / "bench.json"
            self.assertEqual(bench.lire(f), {})
            m = bench.executer(Faux(), "qwen3:8b", resume_machine="PC test")
            bench.enregistrer(f, m)
            bench.enregistrer(f, dict(m, modele="autre"))
            self.assertEqual(set(bench.lire(f)), {"qwen3:8b", "autre"})
            f.write_text("{pas du json", encoding="utf-8")
            self.assertEqual(bench.lire(f), {})
            exporte = json.loads(bench.exporter(m))
            self.assertEqual((exporte["modele"], exporte["machine"]), ("qwen3:8b", "PC test"))
            self.assertNotIn(str(Path(t)), bench.exporter(m))


if __name__ == "__main__":
    unittest.main()
