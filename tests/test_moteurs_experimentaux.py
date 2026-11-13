"""Moteurs expérimentaux (Colibri, Strata) : des préréglages externes étiquetés « expérimental », jamais proposés par défaut, indépendants, essayés avec un faux serveur."""
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-exper-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import core as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import engine_bench, engine_catalog as cm, llamacpp_engine as ml, engines  # noqa: E402
from test_conformite_moteurs import FauxOpenAI  # noqa: E402

EXPERIMENTAUX = ("colibri", "strata")
RACINE = Path(__file__).resolve().parent.parent


class Catalogue(unittest.TestCase):
    def entrees(self):
        return {m["id"]: m for m in cm.charger()["moteurs"]}

    def test_colibri_et_strata_sont_des_preregalages_externes_experimentaux(self):
        e = self.entrees()
        for ident in EXPERIMENTAUX:
            self.assertIn(ident, e)
            self.assertTrue(e[ident]["experimental"])
            self.assertEqual(e[ident].get("type", "externe"), "externe", "pas d'intégration gérée sans l'essai S3")
            self.assertEqual(e[ident]["genre"], "openai")

    def test_aucun_moteur_experimental_n_a_d_adaptateur_propre(self):
        for ident in EXPERIMENTAUX:
            self.assertNotIn(ident, engines.MOTEURS)
            self.assertNotIn(ident, cm.GERES)

    def test_ils_sont_dans_la_liste_des_preregalages_mais_marques(self):
        pre = {p["id"]: p for p in cm.prereglages()}
        for ident in EXPERIMENTAUX:
            self.assertTrue(pre[ident]["experimental"])
        self.assertFalse(pre["lmstudio"]["experimental"])

    def test_les_limites_sont_dites(self):
        pre = {p["id"]: p for p in cm.prereglages()}
        self.assertTrue(any("recherche" in t for t in pre["colibri"]["points_faibles"]))
        self.assertTrue(any("ni ne le démarre" in t for t in pre["colibri"]["points_faibles"]))
        self.assertIn("recommandation", pre["strata"]["remarque"])

    def test_le_schema_refuse_un_experimental_qui_n_est_pas_booleen(self):
        c = json.loads(json.dumps(cm.charger()))
        for m in c["moteurs"]:
            if m["id"] == "colibri":
                m["experimental"] = "oui"
        with self.assertRaises(cm.ErreurCatalogue):
            cm.valider(c)

    def test_le_catalogue_livre_est_bien_signe(self):
        enveloppe = json.loads((RACINE / "src" / "lutin" / "data" / "moteurs.json").read_text(encoding="utf-8"))
        cm.verifier(enveloppe)


class JamaisParDefaut(unittest.TestCase):
    def test_le_banc_et_la_recommandation_ne_les_connaissent_pas(self):
        for ident in EXPERIMENTAUX:
            self.assertNotIn(ident, engine_bench.MOTEURS_BANC)
        for docker in (False, True):
            r = engine_bench.recommander(None, docker=docker)
            self.assertNotIn(r["moteur"], EXPERIMENTAUX)

    def test_le_moteur_par_defaut_reste_ollama(self):
        self.assertEqual(_m.REGLAGES_DEFAUT["moteur"], "ollama")


class AvecUnFauxServeur(unittest.TestCase):
    """Chaque moteur expérimental se règle comme n'importe quel serveur externe : une adresse, et c'est tout. Indépendant des autres."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), FauxOpenAI)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.adresse = "http://127.0.0.1:%d/v1" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.ancien = dict(engines.CONTEXTE)
        dossier = Path(tempfile.mkdtemp(prefix="lutin-exper-d-"))
        engines.CONTEXTE.update(donnees=lambda: dossier, en_docker=lambda: False, hors_ligne=lambda: False, profil=lambda: None)
        self.addCleanup(engines.CONTEXTE.update, self.ancien)

    def test_un_serveur_experimental_repond_comme_un_serveur_externe(self):
        mo = engines.MOTEURS["openai"]
        ml.regler("openai", self.adresse, None)
        self.assertEqual(mo.modeles()["installes"], ["modele-test"])
        rep = mo.chat({"model": "modele-test", "messages": [{"role": "user", "content": "Salut"}], "stream": False}, 20)
        self.assertEqual(rep["message"]["content"], "réponse complète")

    def test_regler_un_moteur_experimental_ne_touche_pas_a_llama_cpp(self):
        avant = json.dumps(ml.lire_config().get("llamacpp", {}), sort_keys=True)
        ml.regler("openai", self.adresse, None)
        self.assertEqual(json.dumps(ml.lire_config().get("llamacpp", {}), sort_keys=True), avant)


if __name__ == "__main__":
    unittest.main()
