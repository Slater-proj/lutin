"""Archive d'une conversation : les messages que le résumé automatique retire de la conversation.

Le résumé garde l'essentiel mais perd des détails. Pour que rien ne soit définitivement perdu, les messages retirés sont gardés dans donnees/archives/<identifiant>.jsonl ;
l'outil « rappeler » les retrouve par mots-clés (voir recall.py). L'archive disparaît avec la conversation, et les archives orphelines sont nettoyées."""
import json
import re

from . import core as _m

RE_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
MAX_SIZE = 20_000_000                 # au-delà, l'archive n'est plus agrandie (la conversation, elle, continue)


def folder():
    return _m.DONNEES / "archives"


def path_of(ident):
    if not RE_ID.match(str(ident or "")):
        raise ValueError("Conversation inconnue.")
    return folder() / (str(ident) + ".jsonl")


def add(ident, messages):
    """Ajoute des messages à l'archive. Renvoie le nombre de messages gardés (0 si l'archive est pleine ou illisible : on ne bloque jamais la conversation)."""
    lignes = []
    for m in messages:
        role, contenu = m.get("role"), (m.get("content") or "").strip()
        if role not in ("user", "assistant", "tool") or not contenu:
            continue
        lignes.append(json.dumps({"role": role, "content": contenu[:1500 if role == "tool" else 20000]}, ensure_ascii=False))
    if not lignes:
        return 0
    try:
        f = path_of(ident)
        if f.is_file() and f.stat().st_size > MAX_SIZE:
            return 0
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8", newline="\n") as sortie:
            sortie.write("\n".join(lignes) + "\n")
        return len(lignes)
    except (OSError, ValueError) as erreur:
        _m.journaliser("Archive non écrite (conversation {}) : {!r}".format(ident, erreur))
        return 0


RESULT_MAX = 200_000                 # characters of one tool result kept in full (a result cut to fit the window, ADR 0019 decision 5)


def add_result(ident, tool_name, text):
    """Keeps the full text of a tool result that was cut to fit the window, so that « rappeler » with ici=true finds the part the model did not see.
    Written in the same file as the archived messages, under its own role: `text_of` does not read it. Returns True when written."""
    text = str(text or "").strip()
    if not text:
        return False
    try:
        f = path_of(ident)
        if f.is_file() and f.stat().st_size > MAX_SIZE:
            return False
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8", newline="\n") as out:
            out.write(json.dumps({"role": "result", "tool_name": str(tool_name or ""), "content": text[:RESULT_MAX]}, ensure_ascii=False) + "\n")
        return True
    except (OSError, ValueError) as error:
        _m.journaliser("Archive non écrite (conversation {}) : {!r}".format(ident, error))
        return False


def results_of(ident):
    """The full tool results kept by `add_result`, oldest first, each as (tool name, text)."""
    try:
        raw = path_of(ident).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return []
    out = []
    for line in raw.splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if isinstance(m, dict) and m.get("role") == "result" and m.get("content"):
            out.append((str(m.get("tool_name") or ""), str(m["content"])))
    return out


def text_of(ident):
    """Les messages archivés, en texte lisible (« [moi] … », « [assistant] … »). Les outils ne sont pas repris : leur sortie ne servirait qu'à brouiller la recherche."""
    try:
        f = path_of(ident)
        brut = f.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""
    sortie = []
    for ligne in brut.splitlines():
        try:
            m = json.loads(ligne)
        except ValueError:
            continue
        if m.get("role") in ("user", "assistant") and m.get("content"):
            sortie.append("[{}] {}".format("moi" if m["role"] == "user" else "assistant", m["content"]))
    return "\n\n".join(sortie)


def remove(ident):
    try:
        f = path_of(ident)
    except ValueError:
        return False
    existait = f.is_file()
    f.unlink(missing_ok=True)
    return existait


def clean_orphans(ids_existants):
    n = 0
    try:
        for f in folder().glob("*.jsonl"):
            if f.stem not in ids_existants:
                f.unlink(missing_ok=True)
                n += 1
    except OSError:
        pass
    return n
