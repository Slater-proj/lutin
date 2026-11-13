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

PRINCIPAL = "principal"


class ErreurTravail(ValueError):
    pass


def _id_depuis(nom, deja):
    base = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()).strip("-") or "dossier"
    ident, n = base, 2
    while ident in deja:
        ident, n = "{}-{}".format(base, n), n + 1
    return ident


def liste(cfg):
    """[{id, nom, chemin}] : le dossier principal d'abord (s'il est défini), puis les autres. Ne modifie pas cfg."""
    em = cfg.get("emplacements", {})
    sortie, chemins = [], set()
    principal = (em.get("travail") or "").strip()
    if principal:
        sortie.append({"id": PRINCIPAL, "nom": Path(principal).name or principal, "chemin": principal})
        chemins.add(cle(principal))
    for t in em.get("travaux", []):
        if isinstance(t, dict) and t.get("chemin") and cle(t["chemin"]) not in chemins and t.get("id") != PRINCIPAL:
            sortie.append({"id": str(t.get("id") or _id_depuis(t.get("nom", ""), {x["id"] for x in sortie})), "nom": str(t.get("nom") or Path(t["chemin"]).name), "chemin": t["chemin"]})
            chemins.add(cle(t["chemin"]))
    return sortie


def cle(chemin):
    try:
        return str(Path(chemin).expanduser().resolve()).lower()
    except OSError:
        return str(chemin).lower()


def actif(cfg):
    """Le dossier actif (celui du choix enregistré, sinon le premier), ou None s'il n'y en a aucun."""
    tous = liste(cfg)
    voulu = cfg.get("emplacements", {}).get("travail_actif")
    return next((t for t in tous if t["id"] == voulu), tous[0] if tous else None)


def par_id(cfg, ident):
    return next((t for t in liste(cfg) if t["id"] == ident), None)


DELAI_DISQUE_S = 10          # un partage réseau éteint peut faire attendre Windows une minute : on rend la main avant


def est_reseau(chemin):
    """Un chemin réseau Windows (deux barres obliques inverses ou deux barres obliques, puis le nom du serveur)."""
    return str(chemin).startswith((chr(92) * 2, "//"))


def avec_delai(fonction, delai=DELAI_DISQUE_S):
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
    fini, valeur = avec_delai(lambda: (p.exists(), p.is_dir(), os.access(str(p), os.R_OK | os.X_OK)))
    if fini is None:
        return _t("Le dossier « {} » ne répond pas (plus de {} s) : un partage réseau éteint, un disque déconnecté ?").format(p, DELAI_DISQUE_S)
    if not fini:
        if isinstance(valeur, PermissionError):
            return _t("Accès refusé à « {} » : Lutin tourne avec ton compte Windows, qui n'a pas le droit d'y entrer.").format(p)
        return _t("Dossier illisible « {} » : {}").format(p, valeur)
    existe, est_dossier, lisible = valeur
    if not existe:
        if est_reseau(p):
            return _t("Le dossier réseau « {} » est introuvable ou inaccessible depuis cet ordinateur. Vérifie que le partage répond (ouvre-le dans l'Explorateur avec le même compte Windows, ou connecte les identifiants du partage), puis réessaie.").format(p)
        return _t("Ce dossier n'existe pas : {}").format(p)
    if not est_dossier:
        return _t("« {} » est un fichier, pas un dossier.").format(p)
    if not lisible:
        return _t("Accès refusé à « {} » : Lutin tourne avec ton compte Windows, qui n'a pas le droit d'y entrer.").format(p)
    return None


def en_conflit(p, interdits):
    """Le dossier de Lutin (configuration, données, mémoire, cache) avec lequel `p` se chevauche, ou None."""
    for i in interdits:
        try:
            ri = Path(i).resolve()
        except OSError:
            continue
        if p == ri or ri in p.parents or p in ri.parents:
            return ri
    return None


def verifier_chemin(chemin, interdits=()):
    """Le chemin résolu, ou ErreurTravail. `interdits` : dossiers de Lutin (configuration, données, mémoire, cache) qu'on ne peut ni contenir ni être."""
    texte = str(chemin or "").strip().strip('"')
    if not texte:
        raise ErreurTravail(_t("Indique un dossier."))
    p = Path(texte).expanduser()
    fini, valeur = avec_delai(p.resolve)
    if fini is None:
        raise ErreurTravail(_t("Le dossier « {} » ne répond pas (plus de {} s) : un partage réseau éteint, un disque déconnecté ?").format(texte, DELAI_DISQUE_S))
    p = valeur if fini else p
    raison = diagnostic(p)
    if raison:
        raise ErreurTravail(raison)
    if p == Path(p.anchor):
        raise ErreurTravail(_t("Un disque entier n'est pas un dossier de travail : choisis un dossier précis."))
    conflit = en_conflit(p, interdits)
    if conflit:
        raise ErreurTravail(_t("Ce dossier contient ou est dans les dossiers de Lutin ({}) : choisis-en un autre.").format(conflit))
    return p


def ajouter(cfg, chemin, nom="", interdits=()):
    """Ajoute un dossier (ou renvoie celui qui existe déjà pour ce chemin). Modifie cfg."""
    p = verifier_chemin(chemin, interdits)
    for t in liste(cfg):
        if cle(t["chemin"]) == str(p).lower():
            return t
    existants = {t["id"] for t in liste(cfg)}
    etait_vide = not existants
    nom = (nom or p.name or str(p)).strip()[:60]
    t = {"id": _id_depuis(nom, existants), "nom": nom, "chemin": str(p)}
    cfg.setdefault("emplacements", {}).setdefault("travaux", []).append(t)
    if etait_vide:
        cfg["emplacements"]["travail_actif"] = t["id"]
    return t


def retirer(cfg, ident):
    """Retire un dossier de la liste (les fichiers ne sont pas touchés). Le dossier principal se retire aussi. Sans dossier restant, Lutin travaille dans son dossier par défaut (~/Lutin)."""
    em = cfg.setdefault("emplacements", {})
    if ident == PRINCIPAL:
        if not (em.get("travail") or "").strip():
            raise ErreurTravail(_t("Dossier inconnu : {}").format(ident))
        em["travail"] = ""
    else:
        avant = len(em.get("travaux", []))
        em["travaux"] = [t for t in em.get("travaux", []) if t.get("id") != ident]
        if len(em["travaux"]) == avant:
            raise ErreurTravail(_t("Dossier inconnu : {}").format(ident))
    if em.get("travail_actif") == ident:
        em["travail_actif"] = ""


def _ecrire_chemin(cfg, ident, chemin):
    em = cfg.setdefault("emplacements", {})
    if ident == PRINCIPAL:
        em["travail"] = chemin
        return
    for t in em.get("travaux", []):
        if t.get("id") == ident:
            t["chemin"] = chemin
            return
    raise ErreurTravail(_t("Dossier inconnu : {}").format(ident))


def changer_chemin(cfg, ident, nouveau, interdits=()):
    """Le dossier a changé de place (déplacé à la main, lecteur réseau renommé…) : on met à jour son chemin, rien d'autre. Le nouveau chemin doit exister."""
    if not par_id(cfg, ident):
        raise ErreurTravail(_t("Dossier inconnu : {}").format(ident))
    p = verifier_chemin(nouveau, interdits)
    for t in liste(cfg):
        if t["id"] != ident and cle(t["chemin"]) == cle(p):
            raise ErreurTravail(_t("Ce dossier est déjà dans la liste (« {} »).").format(t["nom"]))
    _ecrire_chemin(cfg, ident, str(p))
    return par_id(cfg, ident)


def deplacer(cfg, ident, nouveau_parent, nom="", interdits=()):
    """Déplace le dossier (avec ses fichiers) dans `nouveau_parent`, sous le nom `nom` (le sien par défaut), puis met à jour son chemin. Renvoie (dossier, restes) :
    sur un autre disque, le dossier est copié puis l'ancien est supprimé ; ce qui n'a pas pu l'être (fichier ouvert ailleurs) est listé, jamais perdu en silence."""
    t = par_id(cfg, ident)
    if not t:
        raise ErreurTravail(_t("Dossier inconnu : {}").format(ident))
    source = Path(t["chemin"])
    raison = diagnostic(source)
    if raison:
        raise ErreurTravail(raison)
    source = source.resolve()
    parent = verifier_chemin(nouveau_parent, interdits)
    interdits_nom = '\\/:*?"<>|'
    nom = "".join("-" if c in interdits_nom else c for c in (nom or source.name).strip()).strip(". ") or source.name
    destination = parent / nom
    if destination == source:
        raise ErreurTravail(_t("Le dossier est déjà là."))
    if source in destination.parents:
        raise ErreurTravail(_t("On ne peut pas déplacer un dossier dans lui-même."))
    if destination.exists():
        raise ErreurTravail(_t("« {} » existe déjà à cet endroit : choisis un autre nom ou un autre endroit.").format(destination))
    conflit = en_conflit(destination, interdits)
    if conflit:
        raise ErreurTravail(_t("Ce dossier contient ou est dans les dossiers de Lutin ({}) : choisis-en un autre.").format(conflit))
    restes = []
    try:
        os.rename(str(source), str(destination))                 # même disque : instantané
    except OSError:
        try:
            shutil.copytree(str(source), str(destination), symlinks=True)
        except (OSError, shutil.Error) as e:
            shutil.rmtree(str(destination), ignore_errors=True)  # copie partielle : on ne la laisse pas, l'original n'a pas bougé
            raise ErreurTravail(_t("Déplacement impossible, rien n'a changé : {}").format(e))
        shutil.rmtree(str(source), onerror=lambda fonction, chemin, info: restes.append(str(chemin)))
        if source.exists() and not restes:
            restes.append(str(source))
    _ecrire_chemin(cfg, ident, str(destination))
    return par_id(cfg, ident), restes


def choisir(cfg, ident):
    t = par_id(cfg, ident)
    if not t:
        raise ErreurTravail(_t("Dossier inconnu : {}").format(ident))
    cfg.setdefault("emplacements", {})["travail_actif"] = ident
    return t
