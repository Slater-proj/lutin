"""Les boutons du banc de la page (« Tester mon PC », « Comparer ») mesurent le moteur CHOISI, pas toujours Ollama : avec llama.cpp ou un serveur compatible OpenAI, la mesure passe par l'adaptateur du banc."""
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-bancpage-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_BENCH": str(_TEMP / "bench.json"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import core as A  # noqa: E402
from lutin import bench, agent  # noqa: E402


class MoteurFictif:
    """Un moteur qui n'est pas Ollama : il répond au format d'Ollama (c'est le rôle de son adaptateur de traduire)."""
    id = "fictif"
    nom = "Moteur fictif"

    def __init__(self):
        self.demandes = []

    def modeles(self):
        return {"actif": True, "installes": ["m1"], "tailles": {"m1": 1}}

    def chat(self, corps, delai=60):
        self.demandes.append(corps)
        return {"message": {"role": "assistant", "content": "texte"}, "eval_count": 100, "eval_duration": 2 * 10 ** 9, "load_duration": 10 ** 9, "done": True}


class BancDeLaPage(unittest.TestCase):
    def setUp(self):
        self.moteur = MoteurFictif()
        self.vrai = agent.moteur_local
        A.moteur_local = lambda r=None: self.moteur
        agent.moteur_local = lambda r=None: self.moteur
        A.BENCH.update(en_cours="", etape="", erreur="", file=[])

    def tearDown(self):
        A.moteur_local = self.vrai
        agent.moteur_local = self.vrai

    def test_le_client_du_banc_est_l_adaptateur_pour_un_autre_moteur(self):
        self.assertIsInstance(agent.client_banc(), bench.AdaptateurMoteur)

    def test_la_mesure_rapide_passe_par_le_moteur_choisi(self):
        A._mesurer_un("m1", True)
        self.assertEqual(A.BENCH["erreur"], "")
        self.assertTrue(self.moteur.demandes, "le moteur choisi a reçu la demande de mesure")
        mesure = bench.lire(A.chemin_bench())["m1"]
        self.assertEqual(mesure["resultats"]["vitesse"]["tok_s"], 50.0)

    def test_la_serie_demande_les_modeles_du_moteur_choisi(self):
        with self.assertRaises(ValueError) as e:
            A.lancer_bench_serie(["absent-de-ce-moteur"])
        self.assertIn("absent-de-ce-moteur", str(e.exception))
        self.assertEqual(A.lancer_bench_serie(["m1"], True)["modeles"], ["m1"])


class AvecOllama(unittest.TestCase):
    def test_ollama_reste_interroge_directement(self):
        self.assertNotIsInstance(agent.client_banc({"moteur": "ollama"}), bench.AdaptateurMoteur)


if __name__ == "__main__":
    unittest.main()
