"""Le nettoyage du registre ne supprime que les anciennes candidates, jamais une image publiée."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import context  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import nettoyer_images as N  # noqa: E402

MAINTENANT = datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()


def version(ident, etiquettes, jours):
    quand = datetime.fromtimestamp(MAINTENANT, timezone.utc) - timedelta(days=jours)
    return {"id": ident, "updated_at": quand.isoformat().replace("+00:00", "Z"), "metadata": {"container": {"tags": etiquettes}}}


class Selection(unittest.TestCase):
    def test_reconnait_les_candidates(self):
        for e in (["rc-i18n"], ["0.2.0rc12-i18n"], ["rc-i18n-slim", "0.2.0rc15-i18n-slim"], ["0.2.1rc18-dependabot.github.actions.x.1"]):
            self.assertTrue(N.est_candidate(e), e)
        for e in ([], ["latest"], ["0.2.0"], ["slim"], ["0.2.0-slim"], ["rc-x", "latest"], ["1.0.0", "0.9.0rc1"]):
            self.assertFalse(N.est_candidate(e), e)

    def test_on_garde_les_plus_recentes_et_ce_qui_est_recent(self):
        versions = [version(1, ["rc-a"], 100), version(2, ["rc-b"], 50), version(3, ["rc-c"], 30), version(4, ["rc-d"], 20), version(5, ["rc-e"], 3), version(6, ["rc-f"], 1)]
        assert_ids = sorted(v["id"] for v in N.selectionner(versions, garder=3, jours=14, maintenant=MAINTENANT))
        self.assertEqual(assert_ids, [1, 2, 3], "les 3 plus récentes (4, 5, 6) restent")
        self.assertEqual(sorted(v["id"] for v in N.selectionner(versions, garder=1, jours=14, maintenant=MAINTENANT)), [1, 2, 3, 4], "5 a moins de 14 jours : gardée")

    def test_jamais_une_image_publiee_ni_une_version_sans_etiquette(self):
        versions = [version(1, ["latest", "0.3.0"], 400), version(2, ["slim"], 400), version(3, ["0.1.0"], 400), version(4, [], 400), version(5, ["rc-vieille"], 400)]
        self.assertEqual([v["id"] for v in N.selectionner(versions, garder=0, jours=1, maintenant=MAINTENANT)], [5])


if __name__ == "__main__":
    unittest.main()
