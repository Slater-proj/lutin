"""The HTTP contract between the page and the server does not drift silently (characterization test for the modernization, docs/adr/0001 and 0002).

`tests/fixtures/api_contract.json` is the inventory of the routes and stream events as they are today, read from the source by `tools/api_inventory.py`.
A route or an event that appears or disappears makes this test fail: if the change is intended, update the inventory in the same commit:

    python tools/api_inventory.py --write
"""
import importlib.util
import json
import unittest
from pathlib import Path

import context  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("api_inventory", ROOT / "tools" / "api_inventory.py")
api_inventory = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api_inventory)


def flatten(data):
    """Every (where, kind, route) of an inventory, to name precisely what changed."""
    found = {(method, kind, route) for method in ("GET", "POST") for kind in ("exact", "prefix") for route in data.get(method, {}).get(kind, [])}
    found |= {(helper, kind, route) for helper, entry in data.get("helpers", {}).items() for kind in ("exact", "prefix") for route in entry.get(kind, [])}
    return found | {("stream", "event", name) for name in data.get("events", [])} | {("server", "dynamic", name) for name in data.get("dynamic", [])}


class Contract(unittest.TestCase):
    def test_the_inventory_matches_the_source(self):
        recorded = json.loads(api_inventory.FIXTURE.read_text(encoding="utf-8"))
        current = api_inventory.inventory()
        added, removed = sorted(flatten(current) - flatten(recorded)), sorted(flatten(recorded) - flatten(current))
        self.assertEqual((added, removed), ([], []), "the HTTP contract changed (added, removed). Intended? Run: python tools/api_inventory.py --write")
        self.assertEqual(api_inventory.render(current), api_inventory.FIXTURE.read_text(encoding="utf-8"), "same content, different layout: run python tools/api_inventory.py --write")

    def test_the_reader_sees_the_contract(self):
        """Guards the reader itself: if the handler is reorganised and the reader stops seeing routes, the inventory must not shrink without notice."""
        current = api_inventory.inventory()
        self.assertGreater(len(current["GET"]["exact"]), 40)
        self.assertGreater(len(current["POST"]["exact"]), 80)
        for method, route in (("GET", "/api/etat"), ("POST", "/api/chat"), ("POST", "/api/approuver"), ("POST", "/api/reglages"), ("POST", "/api/appairer")):
            self.assertIn(route, current[method]["exact"], route)
        self.assertIn("/api/noeud/relais/", current["GET"]["prefix"])
        for event in ("texte", "outil", "resultat", "approbation", "erreur", "fin"):
            self.assertIn(event, current["events"], event)

    def test_the_reader_reads_each_form_of_comparison(self):
        source = ROOT / "tests" / "fixtures"          # any folder: the stream events are searched in its *.py files
        sample = Path(context.tempfile.mkdtemp(prefix="lutin-api-")) / "serveur.py"
        sample.write_text(
            "class Gestionnaire:\n"
            "    def do_GET(self):\n"
            "        chemin = self.path.split('?')[0]\n"
            "        if chemin == '/api/a' or chemin in ('/api/b', '/c'):\n            pass\n"
            "        if chemin.startswith('/api/d/') or chemin.split('?')[0] in ROUTES:\n            pass\n"
            "        if chemin == 'not-a-route':\n            pass\n"
            "    def do_POST(self):\n"
            "        if self.path == '/api/e' or self.path.startswith('/api/f-'):\n            pass\n"
            "    def _helper(self, chemin):\n"
            "        if chemin != '/api/g':\n            pass\n", encoding="utf-8")
        data = api_inventory.inventory(sample, source)
        self.assertEqual(data["GET"], {"exact": ["/api/a", "/api/b", "/c"], "prefix": ["/api/d/"]})
        self.assertEqual(data["POST"], {"exact": ["/api/e"], "prefix": ["/api/f-"]})
        self.assertEqual(data["helpers"], {"_helper": {"exact": ["/api/g"], "prefix": []}})
        self.assertEqual(data["dynamic"], ["ROUTES"])


if __name__ == "__main__":
    unittest.main()
