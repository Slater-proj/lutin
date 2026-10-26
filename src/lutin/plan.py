"""Plan du projet : la carte des fichiers et de leurs fonctions donnée au modèle."""
from pathlib import Path
from .i18n import t as _t
import os
import re
import threading
import time
from . import moteur as _m


# --------------------------------------------------------------------------- plan du projet (donne au modèle la carte des fichiers et de leurs fonctions)
PLAN = {"sections": {}, "date": 0.0, "valide": False, "en_cours": False}


PLAN_MAX = 6500                 # caractères au plus dans le prompt (environ 2 000 jetons)


PLAN_DELAI = 300                # secondes avant de reconstruire le plan quand rien n'a changé


PLAN_EXT = {".py", ".js", ".html", ".md", ".bat", ".ps1", ".txt", ".json"}


PLAN_CACHE = {}                 # chemin -> (date, taille, résumé) : seuls les fichiers modifiés sont relus


RE_SYM_PY = re.compile(r"^(?:async\s+)?def\s+(\w+)|^class\s+(\w+)", re.M)


RE_SYM_JS = re.compile(r"^[ \t]*(?:async\s+)?function\s+(\w+)|^[ \t]*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)\n]*\)|\w+)\s*=>", re.M)


def resume_fichier(f, taille):
    """« 120 l. : fonction1, fonction2... » pour le plan. Python et JavaScript : noms des fonctions ; Markdown : premier titre."""
    suffixe = f.suffix.lower()
    if suffixe in (".json", ".txt", ".bat", ".ps1"):
        return "{} Ko".format(max(1, round(taille / 1024)))
    if taille > 800_000:
        return _t("gros fichier, {} Ko").format(round(taille / 1024))
    try:
        texte = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    noms = []
    if suffixe in (".py", ".js", ".html"):
        for m in (RE_SYM_PY if suffixe == ".py" else RE_SYM_JS).finditer(texte):
            n = m.group(1) or m.group(2)
            if n and not n.startswith("_") and n not in noms:
                noms.append(n)
            if len(noms) >= 12:
                break
    elif suffixe == ".md":
        m = re.search(r"^#\s+(.+)$", texte, re.M)
        if m:
            noms.append(m.group(1).strip()[:70])
    return "{} l.".format(texte.count("\n") + 1) + (" : " + ", ".join(noms) if noms else "")


def construire_plan():
    """Parcourt le projet et renvoie {dossier de premier niveau: [lignes]}. Les fichiers inchangés ne sont pas relus."""
    sections = {}
    for racine, sous, noms in os.walk(str(_m.RACINE)):
        sous[:] = sorted(s for s in sous if s not in _m.DOSSIERS_IGNORES and not s.startswith(".") and not _m.ignore_chemin(Path(racine) / s))
        dossier = Path(racine)
        fichiers = [n for n in sorted(noms) if Path(n).suffix.lower() in PLAN_EXT and not n.startswith(".")]
        if not fichiers:
            continue
        chemin = dossier.relative_to(_m.RACINE).as_posix()
        section = chemin.split("/")[0] if chemin != "." else "."
        lignes = sections.setdefault(section, [])
        lignes.append("" if chemin == "." else chemin + "/")
        for n in fichiers[:25]:
            f = dossier / n
            try:
                st = f.stat()
            except OSError:
                continue
            en_cache = PLAN_CACHE.get(str(f))
            if en_cache and en_cache[0] == st.st_mtime_ns and en_cache[1] == st.st_size:
                resume = en_cache[2]
            else:
                resume = resume_fichier(f, st.st_size)
                PLAN_CACHE[str(f)] = (st.st_mtime_ns, st.st_size, resume)
            lignes.append("  {} ({})".format(n, resume) if resume else "  " + n)
        if len(fichiers) > 25:
            lignes.append("  ... +{} autres fichiers".format(len(fichiers) - 25))
    return sections


def rafraichir_plan(force=False):
    """Reconstruit le plan en arrière-plan (jamais bloquant : le tour en cours utilise la dernière version)."""
    if PLAN["en_cours"] or (not force and PLAN["valide"] and time.time() - PLAN["date"] < PLAN_DELAI):
        return
    PLAN["en_cours"] = True

    def travail():
        try:
            PLAN["sections"], PLAN["date"], PLAN["valide"] = construire_plan(), time.time(), True
        except Exception as erreur:  # noqa: BLE001
            _m.journaliser("Plan du projet impossible : {!r}".format(erreur))
        finally:
            PLAN["en_cours"] = False
    threading.Thread(target=travail, daemon=True).start()


def texte_plan(budget):
    """Le plan, réparti équitablement entre les dossiers de premier niveau pour tenir dans budget caractères (un gros dossier n'écrase pas les autres)."""
    sections = {k: "\n".join(v) for k, v in PLAN["sections"].items() if v}
    if not sections or budget < 300:
        return ""
    restant, libre, parts = budget, len(sections), {}
    for nom, texte in sorted(sections.items(), key=lambda kv: len(kv[1])):          # les petits dossiers prennent ce qu'il leur faut, le reste va aux gros
        part = max(200, restant // libre)
        if len(texte) > part:
            coupe = texte[:part].rsplit("\n", 1)[0]
            texte = coupe + "\n  ... (suite : utilise « lister »)"
        parts[nom] = texte
        restant -= len(texte)
        libre -= 1
    return "\n".join(parts[k] for k in sorted(parts, key=lambda k: (k != ".", k)))
