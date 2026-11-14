"""Dossiers de travail multiples : plusieurs projets, un seul actif à la fois, chaque conversation garde le sien.

La liste est dans config.json (`emplacements.travaux`) ; `emplacements.travail` reste le dossier principal choisi à l'installation.
Règles de prudence : un dossier doit exister, ne pas être la racine d'un disque, ni contenir ou être dans les dossiers de Lutin lui-même.
"""
import os
import re
import shutil
import threading
import unicodedata
from pathlib import Path
from .i18n import t as _t

MAIN = "principal"


class WorkError(ValueError):
    pass


def _id_from(nom, deja):
    base = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()).strip("-") or "dossier"
    ident, n = base, 2
    while ident in deja:
        ident, n = "{}-{}".format(base, n), n + 1
    return ident


def entries(cfg):
    """[{id, nom, chemin}] : le dossier principal d'abord (s'il est défini), puis les autres. Ne modifie pas cfg."""
    em = cfg.get("emplacements", {})
    sortie, chemins = [], set()
    principal = (em.get("travail") or "").strip()
    if principal:
        sortie.append({"id": MAIN, "nom": Path(principal).name or principal, "chemin": principal})
        chemins.add(key(principal))
    for t in em.get("travaux", []):
        if isinstance(t, dict) and t.get("chemin") and key(t["chemin"]) not in chemins and t.get("id") != MAIN:
            sortie.append({"id": str(t.get("id") or _id_from(t.get("nom", ""), {x["id"] for x in sortie})), "nom": str(t.get("nom") or Path(t["chemin"]).name), "chemin": t["chemin"]})
            chemins.add(key(t["chemin"]))
    return sortie


def key(chemin):
    try:
        return str(Path(chemin).expanduser().resolve()).lower()
    except OSError:
        return str(chemin).lower()


def active(cfg):
    """Le dossier actif (celui du choix enregistré, sinon le premier), ou None s'il n'y en a aucun."""
    tous = entries(cfg)
    voulu = cfg.get("emplacements", {}).get("travail_actif")
    return next((t for t in tous if t["id"] == voulu), tous[0] if tous else None)


def by_id(cfg, ident):
    return next((t for t in entries(cfg) if t["id"] == ident), None)


DISK_TIMEOUT_S = 10          # un partage réseau éteint peut faire attendre Windows une minute : on rend la main avant


def is_network(chemin):
    """Un chemin réseau Windows (deux barres obliques inverses ou deux barres obliques, puis le nom du serveur)."""
    return str(chemin).startswith((chr(92) * 2, "//"))


def with_timeout(fonction, delai=DISK_TIMEOUT_S):
    """(réussi, résultat ou exception) : la fonction tourne dans un fil ; sans réponse au bout de `delai` secondes on renonce (réussi = None)."""
    sortie = []

    def travail():
        try:
            sortie.append((True, fonction()))
        except Exception as e:  # noqa: BLE001
            sortie.append((False, e))
    fil = threading.Thread(target=travail, daemon=True, name="acces-disque")
    fil.start()
    fil.join(delai)
    return sortie[0] if sortie else (None, None)


def diagnostic(p):
    """Pourquoi ce dossier n'est pas utilisable, en une phrase qui dit quoi faire ; None s'il l'est (existe, est un dossier, se lit)."""
    fini, valeur = with_timeout(lambda: (p.exists(), p.is_dir(), os.access(str(p), os.R_OK | os.X_OK)))
    if fini is None:
        return _t("Le dossier « {} » ne répond pas (plus de {} s) : un partage réseau éteint, un disque déconnecté ?").format(p, DISK_TIMEOUT_S)
    if not fini:
        if isinstance(valeur, PermissionError):
            return _t("Accès refusé à « {} » : Lutin tourne avec ton compte Windows, qui n'a pas le droit d'y entrer.").format(p)
        return _t("Dossier illisible « {} » : {}").format(p, valeur)
    existe, est_dossier, lisible = valeur
    if not existe:
        if is_network(p):
            return _t("Le dossier réseau « {} » est introuvable ou inaccessible depuis cet ordinateur. Vérifie que le partage répond (ouvre-le dans l'Explorateur avec le même compte Windows, ou connecte les identifiants du partage), puis réessaie.").format(p)
        return _t("Ce dossier n'existe pas : {}").format(p)
    if not est_dossier:
        return _t("« {} » est un fichier, pas un dossier.").format(p)
    if not lisible:
        return _t("Accès refusé à « {} » : Lutin tourne avec ton compte Windows, qui n'a pas le droit d'y entrer.").format(p)
    return None


def in_conflict(p, interdits):
    """Le dossier de Lutin (configuration, données, mémoire, cache) avec lequel `p` se chevauche, ou None."""
    for i in interdits:
        try:
            ri = Path(i).resolve()
        except OSError:
            continue
        if p == ri or ri in p.parents or p in ri.parents:
            return ri
    return None


def check_path(chemin, interdits=()):
    """Le chemin résolu, ou ErreurTravail. `interdits` : dossiers de Lutin (configuration, données, mémoire, cache) qu'on ne peut ni contenir ni être."""
    texte = str(chemin or "").strip().strip('"')
    if not texte:
        raise WorkError(_t("Indique un dossier."))
    p = Path(texte).expanduser()
    fini, valeur = with_timeout(p.resolve)
    if fini is None:
        raise WorkError(_t("Le dossier « {} » ne répond pas (plus de {} s) : un partage réseau éteint, un disque déconnecté ?").format(texte, DISK_TIMEOUT_S))
    p = valeur if fini else p
    raison = diagnostic(p)
    if raison:
        raise WorkError(raison)
    if p == Path(p.anchor):
        raise WorkError(_t("Un disque entier n'est pas un dossier de travail : choisis un dossier précis."))
    conflit = in_conflict(p, interdits)
    if conflit:
        raise WorkError(_t("Ce dossier contient ou est dans les dossiers de Lutin ({}) : choisis-en un autre.").format(conflit))
    return p


def add(cfg, chemin, nom="", interdits=()):
    """Ajoute un dossier (ou renvoie celui qui existe déjà pour ce chemin). Modifie cfg."""
    p = check_path(chemin, interdits)
    for t in entries(cfg):
        if key(t["chemin"]) == str(p).lower():
            return t
    existants = {t["id"] for t in entries(cfg)}
    etait_vide = not existants
    nom = (nom or p.name or str(p)).strip()[:60]
    t = {"id": _id_from(nom, existants), "nom": nom, "chemin": str(p)}
    cfg.setdefault("emplacements", {}).setdefault("travaux", []).append(t)
    if etait_vide:
        cfg["emplacements"]["travail_actif"] = t["id"]
    return t


def remove(cfg, ident):
    """Retire un dossier de la liste (les fichiers ne sont pas touchés). Le dossier principal se retire aussi. Sans dossier restant, Lutin travaille dans son dossier par défaut (~/Lutin)."""
    em = cfg.setdefault("emplacements", {})
    if ident == MAIN:
        if not (em.get("travail") or "").strip():
            raise WorkError(_t("Dossier inconnu : {}").format(ident))
        em["travail"] = ""
    else:
        avant = len(em.get("travaux", []))
        em["travaux"] = [t for t in em.get("travaux", []) if t.get("id") != ident]
        if len(em["travaux"]) == avant:
            raise WorkError(_t("Dossier inconnu : {}").format(ident))
    if em.get("travail_actif") == ident:
        em["travail_actif"] = ""


def _write_path(cfg, ident, chemin):
    em = cfg.setdefault("emplacements", {})
    if ident == MAIN:
        em["travail"] = chemin
        return
    for t in em.get("travaux", []):
        if t.get("id") == ident:
            t["chemin"] = chemin
            return
    raise WorkError(_t("Dossier inconnu : {}").format(ident))


def change_path(cfg, ident, nouveau, interdits=()):
    """Le dossier a changé de place (déplacé à la main, lecteur réseau renommé…) : on met à jour son chemin, rien d'autre. Le nouveau chemin doit exister."""
    if not by_id(cfg, ident):
        raise WorkError(_t("Dossier inconnu : {}").format(ident))
    p = check_path(nouveau, interdits)
    for t in entries(cfg):
        if t["id"] != ident and key(t["chemin"]) == key(p):
            raise WorkError(_t("Ce dossier est déjà dans la liste (« {} »).").format(t["nom"]))
    _write_path(cfg, ident, str(p))
    return by_id(cfg, ident)


def move(cfg, ident, nouveau_parent, nom="", interdits=()):
    """Déplace le dossier (avec ses fichiers) dans `nouveau_parent`, sous le nom `nom` (le sien par défaut), puis met à jour son chemin. Renvoie (dossier, restes) :
    sur un autre disque, le dossier est copié puis l'ancien est supprimé ; ce qui n'a pas pu l'être (fichier ouvert ailleurs) est listé, jamais perdu en silence."""
    t = by_id(cfg, ident)
    if not t:
        raise WorkError(_t("Dossier inconnu : {}").format(ident))
    source = Path(t["chemin"])
    raison = diagnostic(source)
    if raison:
        raise WorkError(raison)
    source = source.resolve()
    parent = check_path(nouveau_parent, interdits)
    interdits_nom = '\\/:*?"<>|'
    nom = "".join("-" if c in interdits_nom else c for c in (nom or source.name).strip()).strip(". ") or source.name
    destination = parent / nom
    if destination == source:
        raise WorkError(_t("Le dossier est déjà là."))
    if source in destination.parents:
        raise WorkError(_t("On ne peut pas déplacer un dossier dans lui-même."))
    if destination.exists():
        raise WorkError(_t("« {} » existe déjà à cet endroit : choisis un autre nom ou un autre endroit.").format(destination))
    conflit = in_conflict(destination, interdits)
    if conflit:
        raise WorkError(_t("Ce dossier contient ou est dans les dossiers de Lutin ({}) : choisis-en un autre.").format(conflit))
    restes = []
    try:
        os.rename(str(source), str(destination))                 # même disque : instantané
    except OSError:
        try:
            shutil.copytree(str(source), str(destination), symlinks=True)
        except (OSError, shutil.Error) as e:
            shutil.rmtree(str(destination), ignore_errors=True)  # copie partielle : on ne la laisse pas, l'original n'a pas bougé
            raise WorkError(_t("Déplacement impossible, rien n'a changé : {}").format(e))
        shutil.rmtree(str(source), onerror=lambda fonction, chemin, info: restes.append(str(chemin)))
        if source.exists() and not restes:
            restes.append(str(source))
    _write_path(cfg, ident, str(destination))
    return by_id(cfg, ident), restes


def choose(cfg, ident):
    t = by_id(cfg, ident)
    if not t:
        raise WorkError(_t("Dossier inconnu : {}").format(ident))
    cfg.setdefault("emplacements", {})["travail_actif"] = ident
    return t
