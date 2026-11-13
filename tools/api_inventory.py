"""Inventory of the HTTP contract between the page and the server, read from the source without running it.

    python tools/api_inventory.py            prints the inventory (JSON)
    python tools/api_inventory.py --write    updates tests/fixtures/api_contract.json

Why: the routes live in two long `if` chains (`do_GET`, `do_POST` in src/lutin/serveur.py), with no table to read. Before the page is rebuilt and the API
gets a versioned English form (docs/adr/0001, 0002), the present contract has to be written down and kept from drifting silently:
`tests/test_api_contract.py` fails when a route or a stream event appears or disappears without this inventory being updated on purpose.

What it sees: every comparison of the request path with a text starting with « / » inside the request handler — `chemin == "/api/x"`,
`self.path in ("/a", "/b")`, `chemin.startswith("/api/x-")` — filed under the method whose handler holds it, or under the helper it is delegated to.
What it does not see (listed, not guessed): routes built at import time (`dynamic`), the fields of each request and answer, and the stream events
that are not written as a literal `emit({"type": "..."})`. Those need the contract tests planned with the new API, not a reader of source code.
"""
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "src" / "lutin" / "serveur.py"
SOURCES = ROOT / "src" / "lutin"
FIXTURE = ROOT / "tests" / "fixtures" / "api_contract.json"
HANDLER = "Gestionnaire"
METHODS = {"do_GET": "GET", "do_POST": "POST"}
EVENT = re.compile(r'emit\(\{"type": "([a-z_]+)"')


def _is_path(node):
    """`chemin`, `self.path`, or either one cut at the query string (`chemin.split("?")[0]`)."""
    if isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "split":
        node = node.func.value
    return (isinstance(node, ast.Name) and node.id == "chemin") or (isinstance(node, ast.Attribute) and node.attr == "path" and isinstance(node.value, ast.Name) and node.value.id == "self")


def _texts(node):
    """The route texts of a constant or of a tuple, list or set of constants."""
    nodes = node.elts if isinstance(node, (ast.Tuple, ast.List, ast.Set)) else [node]
    return [n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("/")]


def _routes(function):
    exact, prefix, dynamic = set(), set(), set()
    for node in ast.walk(function):
        if isinstance(node, ast.Compare) and _is_path(node.left) and len(node.ops) == 1:
            other = node.comparators[0]
            if isinstance(node.ops[0], (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
                exact.update(_texts(other))
                if isinstance(other, ast.Name) and other.id.isupper():
                    dynamic.add(other.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "startswith" and _is_path(node.func.value) and node.args:
            prefix.update(_texts(node.args[0]))
    return exact, prefix, dynamic


def inventory(server=SERVER, sources=SOURCES):
    tree = ast.parse(Path(server).read_text(encoding="utf-8"))
    handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == HANDLER)
    result, dynamic = {"GET": {}, "POST": {}, "helpers": {}}, set()
    for function in handler.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        exact, prefix, found = _routes(function)
        dynamic |= found
        if not (exact or prefix):
            continue
        entry = {"exact": sorted(exact), "prefix": sorted(prefix)}
        if function.name in METHODS:
            result[METHODS[function.name]] = entry
        else:
            result["helpers"][function.name] = entry
    events = set()
    for source in sorted(Path(sources).glob("*.py")):
        events.update(EVENT.findall(source.read_text(encoding="utf-8")))
    result["dynamic"] = sorted(dynamic)
    result["events"] = sorted(events)
    return result


def render(data):
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main(args):
    text = render(inventory())
    if "--write" in args:
        FIXTURE.write_text(text, encoding="utf-8", newline="\n")
        print("written:", FIXTURE.relative_to(ROOT).as_posix())
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
