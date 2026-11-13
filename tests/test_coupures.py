"""Rien n'est coupé en silence : CONTEXTE.md et MEMOIRE.md trop longs, anciens résultats d'outils raccourcis, erreurs de contexte reconnues précisément."""
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-coupures-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import core as A  # noqa: E402  (avant dialogue : ils s'importent l'un l'autre)
from lutin import agent  # noqa: E402


class Coupures(unittest.TestCase):
    def setUp(self):
        A.COUPURES.clear()

    def test_contexte_trop_long_est_coupe_avec_un_marqueur_et_signale(self):
        court = "# Projet\n" + "x" * 100
        self.assertEqual(A.borner_contexte(court), court)
        self.assertEqual(A.COUPURES, {})
        long = "# Projet\n" + "y" * (A.LIMITE_CONTEXTE + 500)
        lu = A.borner_contexte(long)
        self.assertTrue(lu.startswith("# Projet\n" + "y" * 100))
        self.assertIn("CONTEXTE.md coupé", lu)
        self.assertIn("non relus", lu)
        self.assertIn(str(len(long) - A.LIMITE_CONTEXTE), lu, "le marqueur dit combien manque")
        self.assertEqual(A.COUPURES["CONTEXTE.md"], (len(long), A.LIMITE_CONTEXTE))
        A.borner_contexte(court)
        self.assertEqual(A.COUPURES, {}, "la mention disparaît quand le fichier tient de nouveau")

    def test_memoire_longue_dit_ce_qui_n_est_pas_relu_sans_depasser_le_budget(self):
        long = "# Mémoire\n\n## Décisions\n- FIXE\n" + A.MARQUE_NOTES + "\n" + "".join("- note %03d %s\n" % (i, "x" * 60) for i in range(200))
        lu = A.texte_memoire(long)
        self.assertLessEqual(len(lu), 6000)
        self.assertIn("FIXE", lu)
        self.assertIn("note 199", lu)
        self.assertIn("plus anciens non relus", lu)
        self.assertIn("MEMOIRE.md", A.COUPURES)
        sans_section = "début\n" + "z" * 7000
        lu = A.texte_memoire(sans_section)
        self.assertLessEqual(len(lu), 6000)
        self.assertIn("plus anciens non relus", lu)
        A.COUPURES.clear()
        self.assertEqual(A.texte_memoire("court sans section"), "court sans section")
        self.assertEqual(A.COUPURES, {})

    def test_les_anciens_resultats_d_outils_raccourcis_sont_comptes(self):
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "lis tout"}]
        for i in range(6):
            msgs += [{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "lire", "arguments": {"chemin": "f%d" % i}}}]},
                     {"role": "tool", "tool_name": "lire", "content": ("page %d " % i) * 400}]
        rapport = {}
        sortie = agent.ajuster_contexte(msgs, 3000, 1.0, [], rapport)
        self.assertGreater(rapport["raccourcis"] + rapport["retires"] + rapport["tronques"], 0, "il a fallu réduire")
        self.assertTrue(any("raccourci" in m.get("content", "") for m in sortie) or rapport["retires"] > 0)
        rapport = {}
        agent.ajuster_contexte(msgs[:4], 100_000, 1.0, [], rapport)
        self.assertEqual(sum(rapport.values()), 0, "rien à réduire : rien n'est dit")

    def test_la_reduction_est_dite_une_fois_puis_seulement_si_elle_augmente(self):
        dits, ctx = [], {}
        rapport = {"raccourcis": 2, "retires": 1, "tronques": 0, "tours": 0}
        agent.annoncer_reduction(rapport, dits.append, ctx, 8192)
        agent.annoncer_reduction(rapport, dits.append, ctx, 8192)
        self.assertEqual(len(dits), 1)
        self.assertIn("8192", dits[0]["texte"])
        self.assertIn("2 ancien(s) résultat(s)", dits[0]["texte"])
        agent.annoncer_reduction(dict(rapport, raccourcis=9), dits.append, ctx, 8192)
        self.assertEqual(len(dits), 2)
        agent.annoncer_reduction({"raccourcis": 0, "retires": 0, "tronques": 0, "tours": 0}, dits.append, {}, 8192)
        self.assertEqual(len(dits), 2, "rien de réduit : rien de dit")

    def test_la_boucle_de_repetition_d_ollama_est_reconnue(self):
        """« prediction aborted, token repeat limit reached » : le modèle radote, Ollama coupe. Ce n'est ni un plantage ni un contexte plein."""
        self.assertTrue(agent.RE_REPETITION.search("prediction aborted, token repeat limit reached"))
        self.assertFalse(agent.RE_REPETITION.search("the request exceeds the available context size"))

    def test_les_erreurs_de_contexte_sont_reconnues_par_des_expressions_precises(self):
        for vraie in ("the request exceeds the available context size", "prompt is too long: 9000 tokens", "no query found for input", "input is too large for n_ctx", "maximum context length is 4096"):
            self.assertTrue(agent.RE_CONTEXTE.search(vraie), vraie)
        for fausse in ("Unable to generate parser for this template", "unknown option prompt_format", "model prompt template invalid", "context deadline exceeded while loading", "invalid value for parameter"):
            self.assertFalse(agent.RE_CONTEXTE.search(fausse), fausse)


if __name__ == "__main__":
    unittest.main()
