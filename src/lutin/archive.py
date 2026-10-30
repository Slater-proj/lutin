"""Archive d'une conversation : les messages que le résumé automatique retire de la conversation.

Le résumé garde l'essentiel mais perd des détails. Pour que rien ne soit définitivement perdu, les messages retirés sont gardés dans donnees/archives/<identifiant>.jsonl ;
l'outil « rappeler » les retrouve par mots-clés (voir rappel.py). L'archive disparaît avec la conversation, et les archives orphelines sont nettoyées."""
import json
import re

from . import moteur as _m

RE_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
TAILLE_MAX = 20_000_000                 # au-delà, l'archive n'est plus agrandie (la conversation, elle, continue)


def dossier():
    return _m.DONNEES / "archives"


def chemin(ident):
    if not RE_ID.match(str(ident or "")):
        raise ValueError("Conversation inconnue.")
    return dossier() / (str(ident) + ".jsonl")


def ajouter(ident, messages):
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
        f = chemin(ident)
        if f.is_file() and f.stat().st_size > TAILLE_MAX:
            return 0
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8", newline="\n") as sortie:
            sortie.write("\n".join(lignes) + "\n")
        return len(lignes)
    except (OSError, ValueError) as erreur:
        _m.journaliser("Archive non écrite (conversation {}) : {!r}".format(ident, erreur))
        return 0


def texte(ident):
    """Les messages archivés, en texte lisible (« [moi] … », « [assistant] … »). Les outils ne sont pas repris : leur sortie ne servirait qu'à brouiller la recherche."""
    try:
        f = chemin(ident)
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


def supprimer(ident):
    try:
        f = chemin(ident)
    except ValueError:
        return False
    existait = f.is_file()
    f.unlink(missing_ok=True)
    return existait


def nettoyer_orphelins(ids_existants):
    n = 0
    try:
        for f in dossier().glob("*.jsonl"):
            if f.stem not in ids_existants:
                f.unlink(missing_ok=True)
                n += 1
    except OSError:
        pass
    return n
