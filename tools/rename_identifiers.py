"""Renames top-level identifiers of ONE module of `src/lutin`, everywhere they are used (plan step 3, ADR 0001).

    python tools/rename_identifiers.py --list MODULE                      the top-level names, and who uses the module
    python tools/rename_identifiers.py MODULE old=new [old=new ...]       dry run: what would change, and what must be looked at
    python tools/rename_identifiers.py MODULE old=new ... --apply         writes the files

Why a tool and not a search-and-replace: `ruff` does not see module attributes (`cli.miseajour`) nor names written in strings, and a French word is
often also a local variable or an English word. The tool reads the syntax tree and changes only:

- the definitions and every use of the name inside the module itself (refused if the name is also an argument or a local of another function: nothing is changed);
- `from .module import old` and the uses of that name in the importing file;
- `alias.old` where `alias` is the module, however it was imported (`from . import module as _m`, `from lutin import module`);
- `mock.patch.object(alias, "old")` and `mock.patch("lutin.module.old")`.

What it does NOT change, and lists instead (`CHECK`): the same word written in other strings, in documentation, in JSON or in a stored file. Those are read by a person.
After `--apply`, run `ruff` and the full suite: a green suite is the proof, not this tool.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "lutin"
FOLDERS = (PACKAGE, ROOT / "tests", ROOT / "tools")


def python_files():
    return sorted(path for folder in FOLDERS for path in folder.rglob("*.py") if "__pycache__" not in path.parts)


def parse(path):
    text = path.read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)          # old escapes in strings of other files: not this tool's business
        return text, ast.parse(text)


def top_level_names(tree):
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names += [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names


def uses_of(module, tree, own):
    """(aliases of the module, {local name: original name} imported from it) in this file."""
    aliases, imported = set(), {}
    if own:
        return aliases, imported
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level >= 1 and base == "" or (node.level == 0 and base == "lutin"):
                for item in node.names:
                    if item.name == module:
                        aliases.add(item.asname or item.name)
            elif (node.level >= 1 or base.startswith("lutin.")) and base.split(".")[-1] == module:
                for item in node.names:
                    imported[item.asname or item.name] = item.name
        elif isinstance(node, ast.Import):
            for item in node.names:
                if item.name == "lutin." + module:
                    aliases.add(item.asname or item.name)
    return aliases, imported


class Edits:
    """Replacements by line and by UTF-8 byte column, applied from the end of each line."""

    def __init__(self, text):
        self.lines = text.split("\n")
        self.found = []

    def add(self, line, start, end, new):
        self.found.append((line - 1, start, end, new))

    def result(self):
        lines = list(self.lines)
        for line, start, end, new in sorted(set(self.found), reverse=True):
            raw = lines[line].encode("utf-8")
            lines[line] = (raw[:start] + new.encode("utf-8") + raw[end:]).decode("utf-8")
        return "\n".join(lines)


def name_position(edits, node, old):
    """The byte columns of `old` in the line of a definition (`def old(`, `class old`), searching after the keyword."""
    raw = edits.lines[node.lineno - 1].encode("utf-8")
    match = re.compile(rb"\b" + re.escape(old.encode("utf-8")) + rb"\b").search(raw, node.col_offset)
    return (match.start(), match.end()) if match else None


def collisions(tree, old_names):
    """A name that is also an argument or is assigned in a function: renaming it everywhere would change another variable."""
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            arguments = node.args
            every = arguments.posonlyargs + arguments.args + arguments.kwonlyargs + ([arguments.vararg] if arguments.vararg else []) + ([arguments.kwarg] if arguments.kwarg else [])
            problems += [(arg.arg, arg.lineno) for arg in every if arg.arg in old_names]
            if isinstance(node, ast.Lambda):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Store) and inner.id in old_names and not any(
                        isinstance(g, ast.Global) and inner.id in g.names for g in ast.walk(node)):
                    problems.append((inner.id, inner.lineno))
    return problems


def chain_names(module, files):
    """Every name the module is imported under in some file, and its own name: `cli.backup.export` is a use when `backup` is one of them."""
    names = {module}
    for path, text, tree in files:
        aliases, _ = uses_of(module, tree, False)
        names |= aliases
    return names


def plan(module, mapping, sweep=False):
    own_path = PACKAGE / (module + ".py")
    if not own_path.is_file():
        sys.exit("no such module: " + module)
    own_text, own_tree = parse(own_path)
    defined = set(top_level_names(own_tree))
    for old, new in mapping.items():
        if sweep:
            if new not in defined:
                sys.exit("--sweep: `{}` is not defined in {}: this is for names that were already renamed there".format(new, module))
            continue
        if old not in defined:
            sys.exit("`{}` is not a top-level name of {}".format(old, module))
        if new in defined or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", new):
            sys.exit("`{}` cannot be the new name of `{}` (already defined, or not an identifier)".format(new, old))
    if not sweep:
        clash = collisions(own_tree, set(mapping))
        if clash:
            sys.exit("refused, the name is also a local or an argument: " + ", ".join("{} (line {})".format(n, l) for n, l in clash))
        clash = collisions(own_tree, set(mapping.values()))          # the new name would be hidden inside a function that has a variable of that name
        if clash:
            sys.exit("refused, the NEW name is already a local or an argument of this module: " + ", ".join("{} (line {})".format(n, l) for n, l in clash))
    changes, checks = {}, []
    files = [(path,) + parse(path) for path in python_files()]
    targets = [(module, dict(mapping))]
    chains = {module: chain_names(module, files)}
    # A module that imports the name BY NAME and does not rename it re-exports it (`core` does for many modules): `core.old` is then a use of the name too.
    for path, text, tree in files:
        if path != own_path and path.parent == PACKAGE:
            _, imported = uses_of(module, tree, False)
            taken = {orig: mapping[orig] for local, orig in imported.items() if orig in mapping and local == orig}
            if taken:
                targets.append((path.stem, taken))
                chains[path.stem] = chain_names(path.stem, files)
    for path, text, tree in files:
        own = path == own_path
        edits = Edits(text)
        for index, (target, wanted_map) in enumerate(targets):
            aliases, imported = uses_of(target, tree, own and index == 0)
            if own and index == 0:
                if not sweep:
                    outside_none(edits, tree, mapping)
                continue
            outside_uses(edits, tree, target, wanted_map, aliases, imported, chains[target])
        if edits.found:
            changes[path] = edits.result()
        checks += string_checks(path, tree, set(mapping))
    return changes, checks


def outside_none(edits, tree, mapping):
    """Inside the module itself: its definitions and every use of the names."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in mapping:
            position = name_position(edits, node, node.name)
            if position:
                edits.add(node.lineno, position[0], position[1], mapping[node.name])
        elif isinstance(node, ast.Name) and node.id in mapping:
            edits.add(node.lineno, node.col_offset, node.end_col_offset, mapping[node.id])
        elif isinstance(node, ast.Global):
            for name in node.names:
                if name in mapping:
                    raw = edits.lines[node.lineno - 1].encode("utf-8")
                    match = re.compile(rb"\b" + name.encode() + rb"\b").search(raw, node.col_offset + 6)
                    if match:
                        edits.add(node.lineno, match.start(), match.end(), mapping[name])


def dynamic_import_of(node, target):
    """`__import__("lutin.target", ...)` or `importlib.import_module("lutin.target")`: the module reached by its name written in a string."""
    if not (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
        return False
    function = node.func
    named = (isinstance(function, ast.Name) and function.id == "__import__") or (isinstance(function, ast.Attribute) and function.attr == "import_module")
    return named and node.args[0].value == "lutin." + target


def outside_uses(edits, tree, target, mapping, aliases, imported, chain):
    """In another file: `from .target import old`, `alias.old`, and the uses of a name imported without a new local name."""
    wanted = {local: mapping[orig] for local, orig in imported.items() if orig in mapping and local == orig}   # `import old as _x`: the uses keep `_x`
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in mapping and (
                (isinstance(node.value, ast.Name) and node.value.id in aliases) or (isinstance(node.value, ast.Attribute) and node.value.attr in chain)
                or dynamic_import_of(node.value, target)):
            edits.add(node.end_lineno, node.end_col_offset - len(node.attr.encode("utf-8")), node.end_col_offset, mapping[node.attr])
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[-1] == target and (node.level >= 1 or (node.module or "").startswith("lutin.")):
            for item in node.names:
                if item.name in mapping:
                    pattern = re.compile(rb"\b" + item.name.encode() + rb"\b")
                    for line_number in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                        raw = edits.lines[line_number - 1].encode("utf-8")
                        match = pattern.search(raw, node.col_offset + 4 if line_number == node.lineno else 0)
                        if match:
                            edits.add(line_number, match.start(), match.end(), mapping[item.name])
                            break
                    if item.asname is None:
                        wanted[item.name] = mapping[item.name]
        elif isinstance(node, ast.Call):
            function = node.func
            first = node.args[0] if node.args else None
            patched = isinstance(function, ast.Attribute) and function.attr == "object" and len(node.args) >= 2 and (
                (isinstance(first, ast.Name) and first.id in aliases) or (isinstance(first, ast.Attribute) and first.attr in chain))
            if patched and isinstance(node.args[1], ast.Constant) and node.args[1].value in mapping:
                constant = node.args[1]
                edits.add(constant.lineno, constant.col_offset + 1, constant.end_col_offset - 1, mapping[constant.value])
            if isinstance(function, ast.Attribute) and function.attr == "patch" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                string = node.args[0]
                prefix = "lutin." + target + "."
                if string.value.startswith(prefix) and string.value[len(prefix):].split(".")[0] in mapping:
                    old = string.value[len(prefix):].split(".")[0]
                    start = string.col_offset + 1 + len(prefix.encode())
                    edits.add(string.lineno, start, start + len(old.encode()), mapping[old])
    if wanted:
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in wanted:
                edits.add(node.lineno, node.col_offset, node.end_col_offset, wanted[node.id])


def string_checks(path, tree, names):
    """The strings (real ones, read from the syntax tree) that may name one of the identifiers: `.name`, `name(`, or the name given to getattr/setattr/hasattr.
    A French sentence that contains the word is not a reference, a key of a stored file is not one, and a tool name seen by the models is not one (ADR 0007)."""
    found, by_name = [], {}
    for name in names:
        by_name[name] = re.compile(r"\." + re.escape(name) + r"\b|\b" + re.escape(name) + r"\(")
    named = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("getattr", "setattr", "hasattr", "delattr") and len(node.args) >= 2:
            named.add(id(node.args[1]))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for name, pattern in by_name.items():
                if pattern.search(node.value) or (node.value == name and id(node) in named):
                    found.append((path, node.lineno, name, node.value.strip().split("\n")[0][:100]))
    return found


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")          # a Windows console would refuse the accents of the lines it shows
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("module")
    parser.add_argument("pairs", nargs="*", help="old=new")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--sweep", action="store_true", help="the names were already renamed in the module: only look for the uses that were missed")
    args = parser.parse_args(argv)
    module = args.module.removesuffix(".py")
    if args.list:
        path = PACKAGE / (module + ".py")
        text, tree = parse(path)
        users = []
        for other in python_files():
            if other == path:
                continue
            body, other_tree = parse(other)
            aliases, imported = uses_of(module, other_tree, False)
            if aliases or imported:
                users.append(other.relative_to(ROOT).as_posix())
        print("{}: {} lines, used by {} file(s): {}".format(module, len(text.split("\n")), len(users), ", ".join(users[:8]) + (" …" if len(users) > 8 else "")))
        print("top-level names: " + ", ".join(top_level_names(tree)))
        return 0
    mapping = dict(pair.split("=", 1) for pair in args.pairs)
    if not mapping:
        parser.error("give old=new pairs, or --list")
    changes, checks = plan(module, mapping, args.sweep)
    for path, new_text in changes.items():
        print("{} {}".format("WRITE" if args.apply else "WOULD CHANGE", path.relative_to(ROOT).as_posix()))
        if args.apply:
            path.write_text(new_text, encoding="utf-8", newline="\n")
    for path, number, old, line in checks:
        print("CHECK {}:{}  `{}` in a string: {}".format(path.relative_to(ROOT).as_posix(), number, old, line))
    print("{} file(s) {}; {} string(s) to look at.".format(len(changes), "written" if args.apply else "would change", len(checks)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
