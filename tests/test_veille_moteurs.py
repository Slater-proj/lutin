"""Fiches des moteurs gérés tirées du catalogue signé, et veille hebdomadaire des nouvelles versions (demande de fusion à relire, jamais publiée toute seule)."""
import importlib.util
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-veille-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import core as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon ; enregistre les moteurs)
from lutin import engine_catalog as cm  # noqa: E402
from lutin import ed25519, engines  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("veille_moteurs", RACINE / "tools" / "veille_moteurs.py")
veille = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(veille)
GRAINE = bytes(range(32))


def bloc(**plus):
    base = {"id": "ollama", "nom": "Ollama", "genre": "ollama", "type": "gere", "description": {"fr": "Fiche du catalogue."}}
    base.update(plus)
    return base


class Fiches(unittest.TestCase):
    def test_les_cartes_d_ollama_et_de_llamacpp_viennent_du_catalogue(self):
        for ident in ("ollama", "llamacpp"):
            f = cm.fiche(ident)
            self.assertIsNotNone(f, ident)
            vue = engines.MOTEURS[ident].vue()
            self.assertEqual(vue["source_fiche"], "catalogue")
            self.assertEqual(vue["description"], f["description"])
            self.assertEqual(vue["points_forts"], f["points_forts"])
            self.assertTrue(vue["points_faibles"] and vue["site"].startswith("https://"))

    def test_langue_et_repli_sur_le_code(self):
        os.environ["LUTIN_LANGUE"] = "en"
        try:
            self.assertIn("Ollama", engines.MOTEURS["ollama"].vue()["description"])
            self.assertIn("managed by Lutin", engines.MOTEURS["ollama"].vue()["description"])
        finally:
            os.environ.pop("LUTIN_LANGUE", None)
        self.assertIsNone(cm.fiche("ollama", {"moteurs": []}), "pas dans le catalogue : la page garde les textes du code")
        self.assertEqual(engines.MOTEURS["openai"].vue()["source_fiche"], "code", "le serveur externe n'est pas un moteur géré")

    def test_les_moteurs_geres_ne_sont_pas_des_prereglages(self):
        ids = [p["id"] for p in cm.prereglages()]
        self.assertNotIn("ollama", ids)
        self.assertNotIn("llamacpp", ids)
        self.assertIn("lmstudio", ids)

    def test_schema_des_moteurs_geres(self):
        def ok(m):
            return cm.valider({"version": 1, "moteurs": [m]})
        ok(bloc(depot="ollama/ollama", version_testee="0.12.0"))
        ok(bloc(id="llamacpp", genre="openai", nom="llama.cpp", etiquette="^b[0-9]+$"))
        for mauvais in (bloc(type="gere", id="vllm"),                      # un moteur géré porte un identifiant réservé
                        bloc(type="externe"),                              # et un identifiant réservé ne sert pas à un serveur externe
                        bloc(genre="ollama", id="llamacpp"),               # seul Ollama a le genre « ollama »
                        bloc(depot="pas un depot"), bloc(depot="a/b/c"), bloc(version_testee=""), bloc(version_testee="x" * 50),
                        bloc(etiquette="(["), bloc(etiquette=3), bloc(type="autre")):
            with self.assertRaises(cm.ErreurCatalogue, msg=str(mauvais)):
                ok(mauvais)

    def test_un_catalogue_falsifie_ne_change_pas_les_fiches(self):
        ancien = dict(cm.CLES_PUBLIQUES)
        cm.CLES_PUBLIQUES["test"] = ed25519.cle_publique(GRAINE).hex()
        try:
            e = cm.signer({"version": 99, "moteurs": [bloc(description={"fr": "Pirate."})]}, GRAINE, "test")
            e["catalogue"]["moteurs"][0]["description"] = {"fr": "Autre texte, signature périmée."}
            f = _TEMP / "falsifie.json"
            f.write_text(json.dumps(e), encoding="utf-8")
            self.assertLess(cm.charger(f)["version"], 99)
        finally:
            cm.CLES_PUBLIQUES.clear()
            cm.CLES_PUBLIQUES.update(ancien)


class Veille(unittest.TestCase):
    MOTEURS = [{"id": "llamacpp", "nom": "llama.cpp", "depot": "ggml-org/llama.cpp", "etiquette": "^b[0-9]+$", "version_testee": "b100"},
               {"id": "vllm", "nom": "vLLM", "depot": "vllm-project/vllm"}, {"id": "lmstudio", "nom": "LM Studio"}]

    @staticmethod
    def depots(versions):
        """Un faux GitHub : {depot: [(étiquette, pré-publication)]}."""
        def lire(url):
            depot = url.split("/repos/")[1].split("/releases")[0]
            if depot not in versions:
                raise urllib.error.URLError("pas de réseau")
            return [{"tag_name": t, "prerelease": pre, "html_url": "https://github.com/%s/releases/%s" % (depot, t)} for t, pre in versions[depot]]
        return lire

    def test_une_nouvelle_version_est_annoncee_et_la_premiere_vue_ne_l_est_pas(self):
        lire = self.depots({"ggml-org/llama.cpp": [("v0.9.0", True), ("b200", True), ("b199", True)], "vllm-project/vllm": [("v0.34.0rc1", False), ("v0.33.0", False)]})
        neuf, changements = veille.surveiller(self.MOTEURS, {}, lire)
        self.assertEqual((neuf["llamacpp"]["vue"], neuf["vllm"]["vue"]), ("b200", "v0.33.0"), "motif d'étiquette respecté, rc ignorée")
        self.assertEqual(changements, [], "premier passage : rien à annoncer")
        lire = self.depots({"ggml-org/llama.cpp": [("b210", True), ("b200", True)], "vllm-project/vllm": [("v0.33.0", False)]})
        neuf2, changements = veille.surveiller(self.MOTEURS, neuf, lire)
        self.assertEqual([(c["id"], c["ancienne"], c["nouvelle"]) for c in changements], [("llamacpp", "b200", "b210")])
        self.assertEqual(changements[0]["testee"], "b100")
        self.assertEqual(neuf2["llamacpp"]["vue"], "b210")
        _, encore = veille.surveiller(self.MOTEURS, neuf2, lire)
        self.assertEqual(encore, [], "annoncée une seule fois")

    def test_une_panne_reseau_n_est_pas_une_nouvelle_version(self):
        etat = {"llamacpp": {"depot": "ggml-org/llama.cpp", "vue": "b200"}}
        neuf, changements = veille.surveiller(self.MOTEURS, etat, self.depots({}))
        self.assertEqual(neuf, etat)
        self.assertEqual(changements, [])

    def test_une_version_plus_ancienne_n_est_jamais_une_nouveaute(self):
        etat = {"vllm": {"depot": "vllm-project/vllm", "vue": "v0.40.0"}}
        _, changements = veille.surveiller(self.MOTEURS, etat, self.depots({"vllm-project/vllm": [("v0.33.0", False)]}))
        self.assertEqual(changements, [])

    def test_le_rapport_dit_que_rien_n_est_signe_ni_publie(self):
        self.assertIn("Aucune nouvelle version", veille.rapport([]))
        t = veille.rapport([{"id": "vllm", "nom": "vLLM", "depot": "x/y", "ancienne": "v1", "nouvelle": "v2", "adresse": "https://github.com/x/y/releases/v2", "testee": ""}])
        self.assertIn("vLLM", t)
        self.assertIn("Rien n'a été testé, signé ni publié", t)

    def test_l_etat_livre_couvre_tous_les_moteurs_a_depot(self):
        source = json.loads((RACINE / "tools" / "moteurs.source.json").read_text(encoding="utf-8"))["moteurs"]
        etat = json.loads((RACINE / "tools" / "veille_moteurs.json").read_text(encoding="utf-8"))
        self.assertEqual({m["id"] for m in source if m.get("depot")}, set(etat))

    def test_le_workflow_ne_signe_ni_ne_fusionne_ni_ne_publie(self):
        w = (RACINE / ".github" / "workflows" / "veille.yml").read_text(encoding="utf-8")
        self.assertIn("gh pr create", w)
        for interdit in ("gh pr merge", "signer_catalogue_moteurs", "gh release", "git push origin main", "--auto"):
            self.assertNotIn(interdit, w)


if __name__ == "__main__":
    unittest.main()
