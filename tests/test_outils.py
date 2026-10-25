import sys
import unittest
from pathlib import Path

import context  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import verifier_catalogue  # noqa: E402
from lutin import catalogue  # noqa: E402

CAT = catalogue.charger()


class VerifierCatalogue(unittest.TestCase):
    def test_tout_existe(self):
        manquants, incertains = verifier_catalogue.disparus(CAT, lambda url, h=None: (200, {}, b""))
        self.assertEqual((manquants, incertains), ([], []))

    def test_un_modele_disparu_est_signale_mais_pas_une_panne_reseau(self):
        def http(url, h=None):
            if "/qwen3/manifests/8b" in url:
                return 404, {}, b""
            if "/gpt-oss/" in url:
                raise OSError("hors ligne")
            if "/llama3.2/" in url:
                return 503, {}, b""
            return 200, {}, b""
        manquants, incertains = verifier_catalogue.disparus(CAT, http)
        self.assertEqual([m[0] for m in manquants], ["qwen3:8b"])
        self.assertTrue({"gpt-oss:20b", "llama3.2:3b"} <= {i[0] for i in incertains})


if __name__ == "__main__":
    unittest.main()
