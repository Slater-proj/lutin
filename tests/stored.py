"""What a Lutin server running in another process (the demonstration server of tools/captures.py) has stored: its conversations are in its database,
`donnees/lutin.db` (lutin.store, docs/adr/0017-conversations-in-sqlite.md), read here directly. A 0.x file dropped in `donnees/conversations/` is
imported by that server at its next reading: `has` counts it as there."""
import json
import sqlite3
from pathlib import Path


def conversation(donnees, ident):
    """The conversation `ident` as the server stored it, or None."""
    db = Path(donnees) / "lutin.db"
    if not db.is_file():
        return None
    con = sqlite3.connect(str(db), timeout=10)
    try:
        row = con.execute("SELECT fields FROM conversations WHERE id = ?", (ident,)).fetchone()
        if row is None:
            return None
        c = json.loads(row[0])
        c["messages"] = [json.loads(body) for (body,) in con.execute("SELECT body FROM messages WHERE conversation = ? ORDER BY position", (ident,))]
        return c
    finally:
        con.close()


def options(donnees, ident):
    """The options of one conversation as the server stored them ({} when none)."""
    db = Path(donnees) / "lutin.db"
    if not db.is_file():
        return {}
    con = sqlite3.connect(str(db), timeout=10)
    try:
        row = con.execute("SELECT fields FROM options WHERE conversation = ?", (ident,)).fetchone()
        return json.loads(row[0]) if row else {}
    finally:
        con.close()


def has(donnees, ident):
    """The conversation is there: stored, or dropped as a file the server imports at its next reading."""
    return conversation(donnees, ident) is not None or (Path(donnees) / "conversations" / (ident + ".json")).is_file()


def put(donnees, c):
    """Hands a conversation to the running server: a file it imports, as it is, at its next reading."""
    folder = Path(donnees) / "conversations"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (c["id"] + ".json")).write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
