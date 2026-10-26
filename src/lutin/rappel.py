"""Rappel : recherche par mots dans les documents et les anciennes conversations."""
from pathlib import Path
from .i18n import t as _t
import collections
import fnmatch
import math
import os
import re
import unicodedata
from . import moteur as _m


# --------------------------------------------------------------------------- rappel : recherche par mots dans les documents et les anciennes conversations
MOTS_VIDES = set("les des une dans pour par sur avec sans est sont ete etre elle ils elles nous vous leur leurs cette ces cet que qui quoi dont mais donc car aux son sa ses mon ma mes ton ta tes the and for with that this from not are was has have".split())


RAPPEL = {"signature": None, "morceaux": [], "df": collections.Counter(), "moyenne": 1.0}


def mots(texte):
    t = unicodedata.normalize("NFD", str(texte).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return [m for m in re.findall(r"[a-z0-9_]{3,}", t) if m not in MOTS_VIDES]


def sources_rappel():
    """Les documents interrogeables : docs/, skills/, mémoires de l'assistant, puis les conversations enregistrées."""
    if (_m.RACINE / "CLAUDE.md").is_file():
        yield _m.RACINE / "CLAUDE.md"
    for dossier, motifs in ((_m.RACINE / "docs", ("*.md", "*.txt")), (_m.RACINE / "skills", ("*.md",)), (_m.RACINE / ".claude", ("*.md",)), (_m.MEMOIRE, ("*.md",))):
        if dossier.is_dir():
            for racine, sous, noms in os.walk(str(dossier)):
                sous[:] = sorted(s for s in sous if s not in _m.DOSSIERS_IGNORES)
                for nom in sorted(noms):
                    if any(fnmatch.fnmatch(nom.lower(), p) for p in motifs):
                        yield Path(racine) / nom
    dossier = _m.DONNEES / "conversations"
    if dossier.is_dir():
        yield from sorted(dossier.glob("*.json"))


def decouper(texte, source, titre_defaut=""):
    """Morceaux d'environ 800 caractères, coupés aux titres Markdown et aux paragraphes."""
    morceaux, courant, titre = [], [], titre_defaut

    def clore():
        if courant:
            corps = "\n".join(courant).strip()
            if len(corps) > 40:
                morceaux.append({"source": source, "titre": titre, "texte": corps})
            courant.clear()
    taille = 0
    for ligne in texte.splitlines():
        if ligne.startswith("#"):
            clore()
            taille = 0
            titre = ligne.lstrip("# ").strip()[:80]
        courant.append(ligne)
        taille += len(ligne) + 1
        if taille > 800 and not ligne.strip():
            clore()
            taille = 0
    clore()
    return morceaux


def etiquette_rappel(f):
    """Nom affiché d'un document : chemin dans le dossier de travail, ou « memoire/… » pour les mémoires (qui vivent dans le dossier de données, hors du projet)."""
    try:
        return _m.rel(f)
    except ValueError:
        try:
            return "memoire/" + Path(f).resolve().relative_to(_m.MEMOIRE.resolve()).as_posix()
        except ValueError:
            return Path(f).name


def indexer_rappel():
    """Reconstruit l'index seulement si un document a changé."""
    fichiers = list(sources_rappel())
    signature = []
    for f in fichiers:
        try:
            st = f.stat()
            signature.append((str(f), st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    signature = tuple(signature)
    if RAPPEL["signature"] == signature:
        return
    morceaux = []
    for f in fichiers:
        try:
            if f.stat().st_size > 600_000:
                continue
            if f.suffix.lower() == ".json":
                c = _m.lire_json(f, None)
                if not c:
                    continue
                nom = "conversation « {} »".format(c.get("titre", "")[:60])
                texte = "\n\n".join("[{}] {}".format("moi" if m.get("role") == "user" else "assistant", m.get("content", "")) for m in c.get("messages", []) if m.get("role") in ("user", "assistant") and m.get("content"))
                if c.get("resume"):
                    texte = "# Résumé\n" + c["resume"] + "\n\n" + texte
                for m_ in decouper(texte, nom):
                    m_["conv"] = c.get("id")
                    morceaux.append(m_)
            else:
                morceaux += decouper(f.read_text(encoding="utf-8", errors="replace"), etiquette_rappel(f))
        except OSError:
            continue
    df = collections.Counter()
    for m in morceaux:
        m["tf"] = collections.Counter(mots(m["titre"] + " " + m["texte"]))
        m["longueur"] = sum(m["tf"].values()) or 1
        df.update(m["tf"].keys())
    RAPPEL.update({"signature": signature, "morceaux": morceaux, "df": df, "moyenne": (sum(m["longueur"] for m in morceaux) / len(morceaux)) if morceaux else 1.0})


def passages_rappel(requete, nombre=5, exclure_conv="", min_termes=1):
    """Les passages les plus pertinents (méthode BM25) : liste de {score, m, trouves}. exclure_conv : conversation à ignorer (celle en cours) ;
    min_termes : nombre minimal de mots de la requête présents dans le passage (pour ne garder que des passages vraiment liés)."""
    termes = set(mots(requete))
    if not termes:
        return []
    indexer_rappel()
    n = len(RAPPEL["morceaux"])
    scores = []
    for m in RAPPEL["morceaux"]:
        if exclure_conv and m.get("conv") == exclure_conv:
            continue
        score, trouves = 0.0, 0
        for t in termes:
            tf = m["tf"].get(t, 0)
            if tf:
                trouves += 1
                idf = math.log(1 + (n - RAPPEL["df"][t] + 0.5) / (RAPPEL["df"][t] + 0.5))
                score += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * m["longueur"] / RAPPEL["moyenne"]))
        if score > 0 and trouves >= min(min_termes, len(termes)):
            scores.append({"score": score, "m": m, "trouves": trouves, "termes": termes})
    scores.sort(key=lambda x: -x["score"])
    return scores[:nombre]


def formater_passages(passages, taille=600):
    lignes = []
    for i, p in enumerate(passages, 1):
        m, termes = p["m"], p["termes"]
        extrait = " ".join(m["texte"].split())
        pos = min((extrait.lower().find(t) for t in termes if extrait.lower().find(t) >= 0), default=0)
        debut = max(0, pos - 150)
        lignes.append("{}. {}{}\n   {}{}{}".format(i, m["source"], (" — " + m["titre"]) if m["titre"] else "", "…" if debut else "", extrait[debut:debut + taille], "…" if debut + taille < len(extrait) else ""))
    return "\n\n".join(lignes)


def outil_rappeler(requete, nombre=5):
    """Les passages les plus pertinents dans docs/, skills/, les mémoires et les anciennes conversations."""
    if not mots(requete):
        raise _m.ErreurOutil(_t("Requête vide ou trop vague : donne quelques mots-clés."))
    try:
        nombre = max(1, min(10, int(nombre or 5)))
    except (TypeError, ValueError):
        nombre = 5
    passages = passages_rappel(requete, nombre)
    if not passages:
        return _t("Aucun passage pertinent dans les documents ni dans les conversations enregistrées.")
    return formater_passages(passages) + _t("\n\n(lis le document complet avec « lire » si un passage t'intéresse)")


def rappels_automatiques(conv, r):
    """Passages des documents et des anciennes conversations liés à la dernière question, ajoutés au prompt sans que le modèle ait à les demander (mode scénariste par défaut).
    Renvoie (texte pour le prompt, liste des sources) ; vide si le réglage est coupé ou si rien de vraiment lié n'existe."""
    mode = r.get("rappels_auto", "scenario")
    if mode == "jamais" or (mode == "scenario" and r.get("mode") != "scenario"):
        return "", []
    question = next((m["content"] for m in reversed(conv["messages"]) if m.get("role") == "user" and m.get("content") and not m["content"].startswith("[")), "")
    if len(question) < 15:
        return "", []
    passages = passages_rappel(question[:600], 4, exclure_conv=conv.get("id", ""), min_termes=2)
    if not passages:
        return "", []
    sources = []
    for p in passages:
        if p["m"]["source"] not in sources:
            sources.append(p["m"]["source"])
    texte = (_t("\n\n# RAPPELS POSSIBLEMENT PERTINENTS (extraits automatiques des documents et des anciennes conversations ; ils peuvent être hors sujet : ignore-les alors, "
             "et ouvre le document avec « lire » si un détail compte)\n") + formater_passages(passages, 450)[:2200] + "\n")
    return texte, sources
