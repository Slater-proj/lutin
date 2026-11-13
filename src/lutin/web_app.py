"""The new interface (ADR 0002): the files Vite builds from `frontend/`, served under `/app/` next to the old page until parity.

The files are built ahead (by the CI, or `npm run build` in `frontend/`) into `web/app/`: running Lutin never needs Node.js. Nothing here executes or
reads anything outside that folder. The page talks to `/api/v1` only; the server writes the page token, the version and the language into it, as it does
for the old page.
"""
from __future__ import annotations

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
# Everything comes from this server: no inline script, no inline style, no other origin. `blob:` and `data:` are for the images of a conversation.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; manifest-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
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
