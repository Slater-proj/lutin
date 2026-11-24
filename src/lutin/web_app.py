"""The new interface (ADR 0002): the files Vite builds from `frontend/`, served under `/app/` and, since 1.0, at `/` (the old page is removed: ADR 0022).

The files are built ahead (by the CI, or `npm run build` in `frontend/`) into `web/app/`: running Lutin never needs Node.js. Nothing here executes or
reads anything outside that folder. The page talks to `/api/v1` only; the server writes the page token, the version and the language into it, as it does
for the old page.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "web" / "app"
SOURCES = Path(__file__).resolve().parents[2] / "frontend"          # present in a checkout, absent from an installed wheel
PREFIX = "/app/"
TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2",
         ".json": "application/json; charset=utf-8"}
ASSET = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)+$")          # one file name: no folder, no « .. », no hidden file
# The build names every file of `assets/` after its content (`index-QzFXTu3w.js`): a name never changes meaning, so the browser keeps it and the page of a new
# version asks for new names. Before, every visit fetched the whole interface again (`no-store`). `private`: the files need a session, no shared cache keeps them.
ASSET_CACHE = "private, max-age=31536000, immutable"
# Everything comes from this server: no inline script, no inline style, no other origin. `blob:` and `data:` are for the images of a conversation
# and for the drawings of the diagrams. The only frame is the one that draws diagrams (ADR 0011): it has its own policy, below.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; manifest-src 'self'; "
       "frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
# The page that draws diagrams (ADR 0011). Mermaid needs inline styles, which the interface forbids: it runs alone in a sandboxed frame, where it has
# no origin (no cookie, no token, no storage), can reach nothing (`default-src 'none'`), and runs only the two scripts whose hashes are named.
DIAGRAM = "diagram.html"
DIAGRAM_CSP = ("default-src 'none'; script-src {}; style-src 'unsafe-inline'; img-src data:; font-src data:; sandbox allow-scripts; "
               "base-uri 'none'; form-action 'none'; frame-ancestors 'self'")
DIAGRAM_SCRIPTS = (Path(__file__).resolve().parent / "web" / "lib" / "mermaid.min.js", Path(__file__).resolve().parent / "web" / "diagram_frame.js")
_diagram = {"key": None, "page": None}
NOT_BUILT = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Lutin</title></head><body><h1>The new interface is not in this copy of Lutin</h1>"
             "<p>It is built from the <code>frontend/</code> folder: <code>npm ci</code> then <code>npm run build</code>. The present interface is at <a href=\"/\">/</a>.</p></body></html>")
STAMPED = ("index.html", "package.json", "package-lock.json", "svelte.config.js", "tsconfig.json", "vite.config.ts")          # with everything under src/: what the build is made from


def built():
    return (ROOT / "index.html").is_file()


def page(token, version, language):
    """The page of the interface, or None when it is not built. The three values are written by the server: a token made of hexadecimal digits, a version and a language code."""
    try:
        text = (ROOT / "index.html").read_text(encoding="utf-8")
    except OSError:
        return None
    for mark, value in (("__TOKEN__", token), ("__VERSION__", version), ("__LANGUAGE__", language)):
        text = text.replace(mark, re.sub(r"[^A-Za-z0-9_.+-]", "", str(value)))
    return text


def asset(name):
    """(bytes, content type) of a built file of `web/app/assets/`, or None: unknown name, unknown type, or anything that is not a plain file name."""
    kind = TYPES.get(Path(name).suffix.lower())
    if kind is None or not ASSET.match(name):
        return None
    try:
        return (ROOT / "assets" / name).read_bytes(), kind
    except OSError:
        return None


def diagram_page():
    """(page, policy) of the frame that draws diagrams, or None when it cannot be made. The two scripts are written into the page itself and the policy
    names their hashes: a document without an origin sends no session cookie, so it could not fetch them from a server that serves nothing without one."""
    try:
        key = tuple((path.stat().st_mtime_ns, path.stat().st_size) for path in DIAGRAM_SCRIPTS)
        if _diagram["key"] != key:
            # Line endings as the browser will read them: the hash is taken on the text of the script after the page is parsed.
            scripts = [path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n") for path in DIAGRAM_SCRIPTS]
            if any(_closes_early(script) for script in scripts):
                _diagram.update(key=key, page=None)          # a script that would end its own tag: never guess, the answer keeps its code block
            else:
                hashes = " ".join("'sha256-{}'".format(base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")) for script in scripts)
                page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Lutin diagrams</title></head><body>"
                        + "".join("<script>{}</script>".format(script) for script in scripts) + "</body></html>")
                _diagram.update(key=key, page=(page, DIAGRAM_CSP.format(hashes)))
        return _diagram["page"]
    except OSError:
        return None


def _closes_early(script):
    """True when a script written between <script> and </script> would not be read whole by the browser: it holds an end tag, or a « <!-- » followed by
    « <script » before its « --> » (after which the parser no longer sees the end tag)."""
    if re.search(r"</script", script, re.I):
        return True
    for opened in re.finditer(r"<!--", script):
        closed = script.find("-->", opened.start() + 2)          # « <!--> » and « <!---> » close themselves
        if re.search(r"<script", script[opened.end():closed if closed >= 0 else len(script)], re.I):
            return True
    return False


def sources_stamp(sources=None):
    """A hash of the sources the interface is built from; the build writes it into `web/app/build.json`. Line endings are ignored, so that the same commit gives
    the same stamp on Windows and on Linux. The same computation is written in `frontend/vite.config.ts`: tests/test_web_app.py compares the two."""
    sources = Path(sources or SOURCES)
    files = [sources / name for name in STAMPED] + sorted((sources / "src").rglob("*"))
    digest = hashlib.sha256()
    for file in sorted((f for f in files if f.is_file()), key=lambda f: f.relative_to(sources).as_posix()):
        digest.update(file.relative_to(sources).as_posix().encode("utf-8") + b"\0" + file.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def build_stamp():
    """The stamp the build left, or "" when there is no build."""
    try:
        return str(json.loads((ROOT / "build.json").read_text(encoding="utf-8")).get("sources") or "")
    except (OSError, ValueError, AttributeError):
        return ""
