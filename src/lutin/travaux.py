"""Dossiers de travail multiples : plusieurs projets, un seul actif à la fois, chaque conversation garde le sien.

La liste est dans config.json (`emplacements.travaux`) ; `emplacements.travail` reste le dossier principal choisi à l'installation.
Règles de prudence : un dossier doit exister, ne pas être la racine d'un disque, ni contenir ou être dans les dossiers de Lutin lui-même.
"""
import re
import unicodedata
from pathlib import Path

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


def verifier_chemin(chemin, interdits=()):
    """Le chemin résolu, ou ErreurTravail. `interdits` : dossiers de Lutin (configuration, données, mémoire, cache) qu'on ne peut ni contenir ni être."""
    texte = str(chemin or "").strip().strip('"')
    if not texte:
        raise ErreurTravail("Indique un dossier.")
    p = Path(texte).expanduser()
    try:
        p = p.resolve()
    except OSError as e:
        raise ErreurTravail("Dossier illisible : {}".format(e))
    if not p.is_dir():
        raise ErreurTravail("Ce dossier n'existe pas : {}".format(p))
    if p == Path(p.anchor):
        raise ErreurTravail("Un disque entier n'est pas un dossier de travail : choisis un dossier précis.")
    for i in interdits:
        try:
            ri = Path(i).resolve()
        except OSError:
            continue
        if p == ri or ri in p.parents or p in ri.parents:
            raise ErreurTravail("Ce dossier contient ou est dans les dossiers de Lutin ({}) : choisis-en un autre.".format(ri))
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
    """Retire un dossier de la liste (les fichiers ne sont pas touchés). Le dossier principal ne se retire pas ici (il se change par `lutin setup --travail`)."""
    if ident == PRINCIPAL:
        raise ErreurTravail("Le dossier principal se change avec « lutin setup --travail ».")
    em = cfg.setdefault("emplacements", {})
    avant = len(em.get("travaux", []))
    em["travaux"] = [t for t in em.get("travaux", []) if t.get("id") != ident]
    if len(em["travaux"]) == avant:
        raise ErreurTravail("Dossier inconnu : {}".format(ident))
    if em.get("travail_actif") == ident:
        em["travail_actif"] = ""


def choisir(cfg, ident):
    t = par_id(cfg, ident)
    if not t:
        raise ErreurTravail("Dossier inconnu : {}".format(ident))
    cfg.setdefault("emplacements", {})["travail_actif"] = ident
    return t
