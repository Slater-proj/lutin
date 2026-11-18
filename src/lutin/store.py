"""The store of the conversations: one SQLite database, `donnees/lutin.db` (docs/adr/0017-conversations-in-sqlite.md).

A conversation is one row (its fields as JSON, plus the few the list and the search need as columns), its messages one row each, in order, its
options one row, and a full-text index (FTS5) of its title and texts. Every write is one transaction: a reader never sees half a conversation, on
any system. Standard library only.

The JSON files of 0.x are imported once, with a backup first: any `<id>.json` found in `donnees/conversations/` (the 0.x folder, a restore, or
`lutin migrate`) is imported and then moved to `donnees/archives/avant-1.0/`, never deleted. The functions keep the dictionaries of 0.x (French
keys: they are the stored format, renamed with the data migration of step 3), so their callers do not change."""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sqlite3
import sys
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from .i18n import t as _t

SCHEMA_VERSION = 1
LOCK = threading.RLock()          # one connection per database, shared by the threads: sqlite3 serialises them, the lock keeps a write in one piece
_STATE = {"path": None, "connection": None, "fts": False, "set_aside": None}
SUMMARY = ("id", "titre", "maj", "messages", "epingle", "memoire", "origine")


def _data_folder() -> Path:
    from . import core as _m
    return Path(_m.DONNEES)


def database_path() -> Path:
    return _data_folder() / "lutin.db"


def _open(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=15, isolation_level=None, check_same_thread=False)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        _schema(connection)
    except BaseException:
        connection.close()                                         # Windows: an open file cannot be moved aside
        raise
    return connection


def _open_or_set_aside(path: Path) -> sqlite3.Connection:
    """Opens the database. One that cannot be read (damaged: « file is not a database », « malformed ») is never replaced in silence (ADR 0017,
    item 8): its files are moved to donnees/archives/base-illisible-<date>/, the log, the start and the health screen say so, and Lutin goes on
    with an empty one. A database that is locked, on a full disk or not readable by this account is not damaged: the error goes up, nothing moves."""
    try:
        return _open(path)
    except sqlite3.OperationalError:
        raise
    except sqlite3.DatabaseError as error:
        if not path.is_file():
            raise
        folder = _set_aside(path)
        _STATE["set_aside"] = {"database": str(path), "folder": str(folder), "error": str(error)}
        from . import core as _m
        _m.journaliser("Base des conversations illisible ({}) : mise de côté dans {}, nouvelle base vide.".format(error, folder))
        return _open(path)


def _set_aside(path: Path) -> Path:
    folder = _data_folder() / "archives" / "base-illisible-{}".format(datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    folder.mkdir(parents=True, exist_ok=True)
    for f in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if f.is_file():
            shutil.move(str(f), str(folder / f.name))
    return folder


def set_aside_copies() -> list[Path]:
    """The damaged databases moved aside so far, newest first (`lutin doctor` points to them)."""
    folder = _data_folder() / "archives"
    return sorted((d for d in folder.glob("base-illisible-*") if d.is_dir()), reverse=True) if folder.is_dir() else []


# Types of file systems that live on another machine: SQLite's locking cannot be trusted there (https://www.sqlite.org/useovernet.html).
NETWORK_FILESYSTEMS = frozenset({"nfs", "nfs4", "cifs", "smb3", "smbfs", "sshfs", "fuse.sshfs", "afs", "9p", "ceph", "fuse.ceph", "glusterfs",
                                 "fuse.glusterfs", "davfs", "fuse.davfs", "fuse.rclone", "lustre", "beegfs", "gpfs"})
_MOUNT_ESCAPES = {"\\040": " ", "\\011": "\t", "\\012": "\n", "\\134": "\\"}          # how /proc/mounts writes a space, a tab, a newline, a backslash


def mount_type(path: Path | str, mounts: str) -> str:
    """The type of the file system that holds `path` (a POSIX path), read from the text of /proc/mounts: the mount point that is its longest prefix."""
    best, kind = "", ""
    target = str(path).rstrip("/") + "/"
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        point = parts[1]
        for escaped, plain in _MOUNT_ESCAPES.items():
            point = point.replace(escaped, plain)
        point = point.rstrip("/") + "/"
        if target.startswith(point) and len(point) > len(best):
            best, kind = point, parts[2]
    return kind


def on_network_share(path: Path | str) -> bool:
    """True when `path` is on a network share (ADR 0017, item 7). Windows: a UNC path or a mapped network drive; Linux: the type of the mount that
    holds it. Elsewhere, or when it cannot be told: False (the warning is a help, not a guard)."""
    text = str(path)
    if sys.platform == "win32":
        if text.upper().startswith("\\\\?\\UNC\\") or (text.startswith(("\\\\", "//")) and not text.startswith(("\\\\?\\", "\\\\.\\"))):
            return True
        drive = os.path.splitdrive(os.path.abspath(text))[0]
        if len(drive) != 2 or drive[1] != ":":
            return False
        try:
            import ctypes
            return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 4          # DRIVE_REMOTE: a mapped network drive
        except (AttributeError, OSError):
            return False
    try:
        mounts = Path("/proc/self/mounts").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return mount_type(os.path.realpath(text), mounts) in NETWORK_FILESYSTEMS


def network_notice(folder: Path | str) -> str:
    """The warning about a data folder on a network share, or '' (ADR 0017, item 7)."""
    if not on_network_share(folder):
        return ""
    return _t("Le dossier des données ({}) est sur un partage réseau : SQLite n'y verrouille pas sûrement la base des conversations, qui peut s'abîmer. Garde les données sur un disque de cette machine (variable LUTIN_DONNEES) : les vieilles données peuvent aller sur un disque réseau, la base jamais.").format(folder)


def notices() -> list[tuple[str, str]]:
    """What the person must know about the database, as (level, text), level « attention » or « erreur »: said at start, in `lutin doctor` and in
    the health screen. Never opens the database."""
    found = [("attention", text) for text in [network_notice(_data_folder())] if text]
    aside = _STATE.get("set_aside")
    if aside and aside["database"] == str(database_path()):                  # this data folder's database, not one a test or a restore left before
        found.append(("erreur", _t("La base des conversations était illisible ({}) : elle a été mise de côté dans {}, et Lutin repart d'une base vide. Tes sauvegardes sont dans {} (lutin restore <fichier>).").format(aside["error"], aside["folder"], _data_folder() / "sauvegardes")))
    return found


def export_database(target: Path, path: Path | None = None) -> int:
    """Writes every conversation of the database as a 0.x JSON file in `target`/conversations, with its options in `target`/options (ADR 0017,
    item 6: `lutin export --conversations`). Read-only: the database is opened as such, nothing is imported or migrated, and it can run while Lutin
    runs (WAL). Returns the count. ValueError when there is no database yet: the conversations are then still the 0.x files."""
    path = Path(path or database_path())
    if not path.is_file():
        raise ValueError(_t("Pas encore de base des conversations ({}) : tes conversations sont encore les fichiers de la version 0.x, dans {}.").format(path, path.parent / "conversations"))
    try:
        con = sqlite3.connect("file:{}?mode=ro".format(path.resolve().as_posix()), uri=True, timeout=15)
    except sqlite3.Error as error:
        raise ValueError(_t("La base des conversations ne s'ouvre pas ({}) : {}").format(path, error)) from error
    try:
        target = Path(target)
        (target / "conversations").mkdir(parents=True, exist_ok=True)
        options = dict(con.execute("SELECT conversation, fields FROM options").fetchall())
        count = 0
        for ident, fields in con.execute("SELECT id, fields FROM conversations ORDER BY id").fetchall():
            c = json.loads(fields)
            c["messages"] = [json.loads(body) for (body,) in con.execute("SELECT body FROM messages WHERE conversation = ? ORDER BY position", (ident,))]
            (target / "conversations" / (ident + ".json")).write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
            if ident in options:
                (target / "options").mkdir(parents=True, exist_ok=True)
                (target / "options" / (ident + ".json")).write_text(options[ident], encoding="utf-8")
            count += 1
        return count
    except sqlite3.DatabaseError as error:
        raise ValueError(_t("La base des conversations ne se lit pas ({}) : {}").format(path, error)) from error
    finally:
        con.close()


def _schema(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        _STATE["fts"] = _has_fts(connection)
        return
    with connection:
        connection.execute("CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, fields TEXT NOT NULL, titre TEXT NOT NULL DEFAULT '', maj TEXT NOT NULL DEFAULT '',"
                           " epingle INTEGER NOT NULL DEFAULT 0, nb_messages INTEGER NOT NULL DEFAULT 0, memoire TEXT NOT NULL DEFAULT '', origine TEXT NOT NULL DEFAULT '')")
        connection.execute("CREATE TABLE IF NOT EXISTS messages (conversation TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, position INTEGER NOT NULL,"
                           " body TEXT NOT NULL, PRIMARY KEY (conversation, position)) WITHOUT ROWID")
        connection.execute("CREATE TABLE IF NOT EXISTS options (conversation TEXT PRIMARY KEY, fields TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY, done_at TEXT NOT NULL, report TEXT NOT NULL DEFAULT '')")
        connection.execute("CREATE INDEX IF NOT EXISTS conversations_order ON conversations (epingle DESC, maj DESC)")
        try:
            connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(conversation UNINDEXED, titre, texte, tokenize='unicode61 remove_diacritics 2')")
        except sqlite3.OperationalError:
            pass                                                   # a Python built without FTS5: the search falls back to a plain scan
        connection.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
    _STATE["fts"] = _has_fts(connection)


def _has_fts(connection: sqlite3.Connection) -> bool:
    return connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'search'").fetchone() is not None


def connection() -> sqlite3.Connection:
    """The connection to the database of the data folder in use (the tests change it: a new folder opens a new database), with the 0.x files imported."""
    path = database_path()
    with LOCK:
        if _STATE["path"] != path or _STATE["connection"] is None:
            close()
            _STATE["connection"], _STATE["path"] = _open_or_set_aside(path), path
            import_files()
        return _STATE["connection"]


def _pending() -> bool:
    """A 0.x file waits in donnees/conversations/ (dropped there by `lutin migrate`, a restore or a person): cheap, one directory listing."""
    folder = _data_folder() / "conversations"
    return folder.is_dir() and next(folder.glob("*.json"), None) is not None


def ready() -> sqlite3.Connection:
    """The connection, after importing any 0.x file that arrived since the database was opened."""
    con = connection()
    if _pending():
        with LOCK:
            import_files()
    return con


def close() -> None:
    with LOCK:
        if _STATE["connection"] is not None:
            try:
                _STATE["connection"].close()
            except sqlite3.Error:
                pass
        _STATE["connection"], _STATE["path"] = None, None


atexit.register(close)          # the database is closed when Lutin stops: nothing waits in the journal


def _text(message: dict) -> str:
    """What the search reads of a message: its content and its thinking, not the JSON around them."""
    parts = [message.get("content"), message.get("thinking")]
    return "\n".join(part for part in parts if isinstance(part, str) and part)


def _summary_row(c: dict) -> tuple:
    return (str(c.get("titre", "")), str(c.get("maj", c.get("date", ""))), 1 if c.get("epingle") else 0, len(c.get("messages") or []),
            str(c.get("memoire_longue", "") or ""), str((c.get("origine") or {}).get("machine", "") if isinstance(c.get("origine"), dict) else ""))


def _write(con: sqlite3.Connection, c: dict) -> None:
    fields = {key: value for key, value in c.items() if key != "messages"}
    messages = c.get("messages") or []
    con.execute("INSERT INTO conversations (id, fields, titre, maj, epingle, nb_messages, memoire, origine) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET fields = excluded.fields, titre = excluded.titre, maj = excluded.maj, epingle = excluded.epingle,"
                " nb_messages = excluded.nb_messages, memoire = excluded.memoire, origine = excluded.origine",
                (c["id"], json.dumps(fields, ensure_ascii=False)) + _summary_row(c))
    con.execute("DELETE FROM messages WHERE conversation = ?", (c["id"],))
    con.executemany("INSERT INTO messages (conversation, position, body) VALUES (?, ?, ?)",
                    [(c["id"], position, json.dumps(message, ensure_ascii=False)) for position, message in enumerate(messages)])
    if _STATE["fts"]:
        con.execute("DELETE FROM search WHERE conversation = ?", (c["id"],))
        con.execute("INSERT INTO search (conversation, titre, texte) VALUES (?, ?, ?)",
                    (c["id"], str(c.get("titre", "")), "\n".join(_text(m) for m in messages if isinstance(m, dict))))


def write(c: dict) -> None:
    """Stores the whole conversation in one transaction (its fields, its messages in order, its search entry)."""
    con = connection()
    with LOCK:
        con.execute("BEGIN IMMEDIATE")
        try:
            _write(con, c)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise


def read(ident: str) -> dict | None:
    """The conversation as it was written, or None."""
    con = ready()
    with LOCK:
        row = con.execute("SELECT fields FROM conversations WHERE id = ?", (ident,)).fetchone()
        if row is None:
            return None
        messages = [json.loads(body) for (body,) in con.execute("SELECT body FROM messages WHERE conversation = ? ORDER BY position", (ident,))]
    c = json.loads(row["fields"])
    c["messages"] = messages
    return c


def exists(ident: str) -> bool:
    con = ready()
    with LOCK:
        return con.execute("SELECT 1 FROM conversations WHERE id = ?", (ident,)).fetchone() is not None


def delete(ident: str) -> bool:
    con = connection()
    with LOCK:
        con.execute("BEGIN IMMEDIATE")
        try:
            gone = con.execute("DELETE FROM conversations WHERE id = ?", (ident,)).rowcount > 0
            con.execute("DELETE FROM options WHERE conversation = ?", (ident,))
            if _STATE["fts"]:
                con.execute("DELETE FROM search WHERE conversation = ?", (ident,))
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    return gone


def listing() -> list[dict]:
    """The summary of every conversation, pinned ones first, then the most recent: one query, whatever the number of conversations."""
    con = ready()
    with LOCK:
        rows = con.execute("SELECT id, titre, maj, nb_messages, epingle, memoire, origine FROM conversations ORDER BY epingle DESC, maj DESC").fetchall()
    return [{"id": r["id"], "titre": r["titre"], "maj": r["maj"], "messages": r["nb_messages"], "epingle": bool(r["epingle"]), "memoire": r["memoire"], "origine": r["origine"]}
            for r in rows]


def summary(ident: str) -> dict | None:
    """The list entry of one conversation (as in `listing`), or None: what the recall index compares to know whether it changed."""
    con = ready()
    with LOCK:
        r = con.execute("SELECT id, titre, maj, nb_messages, epingle, memoire, origine FROM conversations WHERE id = ?", (ident,)).fetchone()
    if r is None:
        return None
    return {"id": r["id"], "titre": r["titre"], "maj": r["maj"], "messages": r["nb_messages"], "epingle": bool(r["epingle"]), "memoire": r["memoire"], "origine": r["origine"]}


def ids() -> list[str]:
    con = connection()
    with LOCK:
        return [r[0] for r in con.execute("SELECT id FROM conversations")]


def every() -> list[dict]:
    """Every conversation, whole (for the scans that look for files still referenced): read one at a time, never all in memory at once by the caller."""
    return [c for c in (read(ident) for ident in ids()) if c is not None]


def search(query: str, limit: int = 30) -> list[dict]:
    """The conversations whose title or texts hold the words of `query` (accents ignored), best first, each with an extract."""
    words = [word for word in "".join(ch if ch.isalnum() else " " for ch in str(query)).split() if word]
    if not words:
        return []
    con = connection()
    with LOCK:
        if _STATE["fts"]:
            expression = " ".join('"{}"*'.format(word.replace('"', "")) for word in words)
            rows = con.execute("SELECT s.conversation AS id, c.titre AS titre, c.maj AS maj, snippet(search, 2, '«', '»', '…', 12) AS extrait"
                               " FROM search s JOIN conversations c ON c.id = s.conversation WHERE search MATCH ? ORDER BY rank LIMIT ?", (expression, limit)).fetchall()
            return [{"id": r["id"], "titre": r["titre"], "maj": r["maj"], "extrait": r["extrait"]} for r in rows]
        found = []
        for summary in listing():
            c = read(summary["id"]) or {}
            haystack = (summary["titre"] + "\n" + "\n".join(_text(m) for m in c.get("messages") or [] if isinstance(m, dict))).lower()
            if all(word.lower() in haystack for word in words):
                found.append({"id": summary["id"], "titre": summary["titre"], "maj": summary["maj"], "extrait": ""})
            if len(found) >= limit:
                break
        return found


def options_read(ident: str) -> dict:
    con = connection()
    with LOCK:
        row = con.execute("SELECT fields FROM options WHERE conversation = ?", (ident,)).fetchone()
    try:
        value = json.loads(row["fields"]) if row else {}
    except ValueError:
        value = {}
    return value if isinstance(value, dict) else {}


def options_write(ident: str, fields: dict) -> None:
    con = connection()
    with LOCK:
        con.execute("INSERT INTO options (conversation, fields) VALUES (?, ?) ON CONFLICT(conversation) DO UPDATE SET fields = excluded.fields",
                    (ident, json.dumps(fields, ensure_ascii=False)))


def options_delete(ident: str) -> None:
    con = connection()
    with LOCK:
        con.execute("DELETE FROM options WHERE conversation = ?", (ident,))


def options_ids() -> list[str]:
    con = connection()
    with LOCK:
        return [r[0] for r in con.execute("SELECT conversation FROM options")]


# --------------------------------------------------------------------------- the 0.x files: imported once, backed up first, moved, never deleted

def _archive_folder() -> Path:
    return _data_folder() / "archives" / "avant-1.0"


def _backup(files: list[Path]) -> Path | None:
    """A zip of the files about to be imported, in donnees/sauvegardes/, before anything moves."""
    if not files:
        return None
    folder = _data_folder() / "sauvegardes"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "avant-import-{}.zip".format(datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for f in files:
            archive.write(f, arcname=f.parent.name + "/" + f.name)
    return target


def _read_json(f: Path):
    for attempt in range(20):
        try:
            return json.loads(f.read_text(encoding="utf-8-sig"))
        except PermissionError:
            time.sleep(0.02 * (attempt + 1))                       # Windows: the file is being replaced right now
        except (OSError, ValueError):
            return None
    return None


def _move(f: Path) -> None:
    target = _archive_folder() / f.parent.name
    target.mkdir(parents=True, exist_ok=True)
    destination = target / f.name
    if destination.exists():
        destination = target / "{}.{}{}".format(f.stem, datetime.now().strftime("%Y%m%d%H%M%S%f"), f.suffix)
    shutil.move(str(f), str(destination))


def import_files(replace: bool = False) -> dict:
    """Imports the conversation files found in donnees/conversations/ (and their options in donnees/options/), after a zip backup of them. A file put
    there is taken as it is: it comes from the first migration, a restore, `lutin migrate` (which leaves out what is already here) or a person putting
    a conversation back; it is moved away once imported, so nothing is imported twice. A file that cannot be read stays where it is and is reported.
    `replace` (a restore): the file wins even over a newer stored conversation. Returns {imported, skipped, unreadable, backup}."""
    from . import core as _m
    folder, options = _data_folder() / "conversations", _data_folder() / "options"
    files = sorted(f for f in folder.glob("*.json") if f.is_file()) if folder.is_dir() else []
    option_files = sorted(f for f in options.glob("*.json") if f.is_file()) if options.is_dir() else []
    replace = replace or bool(_STATE.pop("replace", False))          # asked by a restore, whatever opens the database first
    report = {"imported": 0, "skipped": 0, "unreadable": [], "backup": ""}
    if not files and not option_files:
        return report
    con = _STATE["connection"]
    with LOCK:
        backup = _backup(files + option_files + [Path(str(f) + ".bak") for f in files if Path(str(f) + ".bak").is_file()])
        report["backup"] = str(backup or "")
        for f in files:
            c = _read_json(f)
            if c is None:
                c = _read_json(Path(str(f) + ".bak"))          # a damaged file: its copy of the time before, as 0.x did
            if not isinstance(c, dict) or not isinstance(c.get("messages", []), list) or str(c.get("id", "")) != f.stem:
                report["unreadable"].append(f.name)
                continue
            known = con.execute("SELECT fields FROM conversations WHERE id = ?", (f.stem,)).fetchone()
            if known is not None and not replace and json.loads(known["fields"]) == {key: value for key, value in c.items() if key != "messages"} and _same_messages(con, c):
                report["skipped"] += 1                                   # the same conversation dropped again: nothing to write
            else:
                con.execute("BEGIN IMMEDIATE")
                try:
                    _write(con, c)
                    con.execute("COMMIT")
                except BaseException:
                    con.execute("ROLLBACK")
                    raise
                report["imported"] += 1
            _move(f)
            if Path(str(f) + ".bak").is_file():
                _move(Path(str(f) + ".bak"))
        for f in option_files:
            value = _read_json(f)
            if isinstance(value, dict):
                con.execute("INSERT INTO options (conversation, fields) VALUES (?, ?) ON CONFLICT(conversation) DO UPDATE SET fields = excluded.fields",
                            (f.stem, json.dumps(value, ensure_ascii=False)))
                _move(f)
        con.execute("INSERT INTO migrations (name, done_at, report) VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET done_at = excluded.done_at, report = excluded.report",
                    ("import-json-" + datetime.now().strftime("%Y%m%d%H%M%S%f"), datetime.now().isoformat(timespec="seconds"), json.dumps(report, ensure_ascii=False)))
    if report["imported"] or report["unreadable"]:
        _m.journaliser("Conversations importées dans la base : {} (déjà là : {}, illisibles : {}). Sauvegarde : {}".format(
            report["imported"], report["skipped"], ", ".join(report["unreadable"]) or "aucune", report["backup"]))
    return report


def _same_messages(con: sqlite3.Connection, c: dict) -> bool:
    stored = [json.loads(body) for (body,) in con.execute("SELECT body FROM messages WHERE conversation = ? ORDER BY position", (c["id"],))]
    return stored == list(c.get("messages") or [])


def export_files(target: Path) -> int:
    """Writes every conversation of the database in use as a 0.x JSON file in `target`, with its options: export_database on this database,
    after the 0.x files waiting in donnees/conversations/ are imported (the way back of ADR 0017). Returns the count."""
    ready()
    return export_database(target)
