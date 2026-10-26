"""Reprendre les données d'un autre assistant dans Lutin : conversations, mémoire, skills, réglages — au choix, sans rien écraser sans le dire.

La source est le **dossier de l'ancien assistant** (celui qui contient `donnees/` et `memoire/` ; les skills sont lus dans `skills/` à côté ou dans le dossier donné) ou une **archive .zip**
(une sauvegarde de Lutin, ou un zip de ces dossiers). Avant toute écriture, l'état actuel de Lutin est gardé dans un zip `donnees/import/avant-import-<date>.zip`.

Règles : une conversation déjà présente n'est pas touchée (sauf `ecraser`) ; une mémoire différente de celle de Lutin est posée à côté (`CONTEXTE.importe-<date>.md`), jamais par-dessus ;
côté réglages, jamais le modèle (il peut ne pas être installé) ni les accords automatiques (c'est à toi de les redonner) ; une archive qui sortirait de ses dossiers est refusée.
"""
import contextlib
import io
import json
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from . import sauvegarde
from .i18n import t as _t

CATEGORIES = ("conversations", "memoire", "skills", "reglages")
REGLAGES_REPRIS = ("num_ctx", "temperature", "reflexion", "mode", "num_predict", "tours_max", "web", "top_p", "top_k", "min_p", "repeat_penalty", "garde_ressources", "seuil_ram_go",
                   "seuil_disque_go", "plafond_donnees_go", "limite_ram_commande_go", "liberer_si_comfy", "rappels_auto", "num_thread", "garde_min")
REGLAGES_JAMAIS = ("modele", "auto_ecriture", "auto_commandes", "avance")
RE_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
RE_NOM_MD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,100}\.md$")
CONVERSATION_MAX = 50_000_000
MEMOIRE_MAX = 1_000_000
ARCHIVE_MAX = 2 * 1024 ** 3
MEMBRES_MAX = 100_000
MODELE_MEMOIRE = ("CONTEXTE.md", "MEMOIRE.md")


class ErreurReprise(ValueError):
    pass


def _premier_dossier(*candidats):
    return next((Path(c) for c in candidats if c and Path(c).is_dir()), None)


def _extraire(archive, destination):
    """Extrait seulement ce qu'on sait reprendre (donnees/conversations/*.json, donnees/reglages.json, memoire/*.md, skills/*.md), après avoir tout vérifié."""
    try:
        z = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as e:
        raise ErreurReprise(_t("Cette archive n'est pas lisible : {}").format(e)) from e
    with z:
        infos = z.infolist()
        if len(infos) > MEMBRES_MAX or sum(i.file_size for i in infos) > ARCHIVE_MAX:
            raise ErreurReprise(_t("Archive trop grande."))
        for i in infos:
            n = i.filename.replace("\\", "/")
            if n.startswith("/") or ".." in n.split("/") or re.match(r"^[A-Za-z]:", n):
                raise ErreurReprise(_t("Archive refusée : « {} » sortirait de ses dossiers.").format(i.filename))
        for i in infos:
            n = i.filename.replace("\\", "/")
            if i.is_dir() or not (re.match(r"^donnees/conversations/[^/]+\.json$", n) or n == "donnees/reglages.json" or re.match(r"^(memoire|skills)/[^/]+\.md$", n)):
                continue
            cible = Path(destination) / n
            cible.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, open(cible, "wb") as dst:
                shutil.copyfileobj(src, dst)


@contextlib.contextmanager
def ouvrir(source, dossier_skills=None):
    """Rend la détection de ce que la source contient : {conversations, memoire, skills, reglages} (listes de chemins sur le disque, valables pendant le `with`)."""
    source = Path(str(source).strip().strip('"')).expanduser()
    if not source.exists():
        raise ErreurReprise(_t("Ce dossier n'existe pas : {}").format(source))
    nettoyage = None
    try:
        if source.is_file():
            if source.suffix.lower() != ".zip":
                raise ErreurReprise(_t("Donne le dossier de l'ancien assistant, ou une archive .zip."))
            nettoyage = tempfile.TemporaryDirectory(prefix="lutin-reprise-")
            _extraire(source, nettoyage.name)
            base = Path(nettoyage.name)
            donnees, memoire = base / "donnees", base / "memoire"
            skills = _premier_dossier(dossier_skills, base / "skills")
        else:
            base = source
            if (base / "conversations").is_dir() and not (base / "donnees").is_dir():                 # on a donné le dossier « donnees » lui-même
                donnees, memoire = base, _premier_dossier(base.parent / "memoire")
                skills = _premier_dossier(dossier_skills, base.parent.parent / "skills")
            else:
                donnees, memoire = base / "donnees", base / "memoire"
                skills = _premier_dossier(dossier_skills, base / "skills", base.parent / "skills")          # l'ancien assistant range ses skills dans le dossier du projet, au-dessus de lui
        conv = sorted(p for p in (donnees / "conversations").glob("*.json") if p.is_file()) if donnees and (donnees / "conversations").is_dir() else []
        mem = sorted(p for p in memoire.glob("*.md") if p.is_file()) if memoire and Path(memoire).is_dir() else []
        sk = sorted(p for p in skills.glob("*.md") if p.is_file()) if skills else []
        reg = donnees / "reglages.json" if donnees and (donnees / "reglages.json").is_file() else None
        d = {"conversations": conv, "memoire": mem, "skills": sk, "reglages": reg, "origine": str(source), "dossier_skills": str(skills) if skills else ""}
        if not (conv or mem or sk or reg):
            raise ErreurReprise(_t("Rien à reprendre dans {} (il faut des dossiers donnees/ et memoire/, ou des skills).").format(source))
        yield d
    finally:
        if nettoyage:
            nettoyage.cleanup()


def decrire(d):
    """Ce que la détection a trouvé, pour l'affichage : {conversations: n, memoire: [noms], skills: n, reglages: bool}."""
    return {"conversations": len(d["conversations"]), "memoire": [p.name for p in d["memoire"]], "skills": len(d["skills"]), "reglages": bool(d["reglages"])}


def _ecrire(chemin, texte):
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(texte, encoding="utf-8")
    tmp.replace(chemin)


def _lire_json(chemin):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _gabarits_memoire():
    """Les textes de départ de Lutin (français et anglais) : une mémoire qui leur est identique n'a jamais été touchée, on peut la remplacer sans rien perdre."""
    base = Path(__file__).resolve().parent / "data"
    sortie = {}
    for nom in MODELE_MEMOIRE:
        sortie[nom] = [p.read_text(encoding="utf-8").strip() for p in (base / nom, base / "en" / nom) if p.is_file()]
    return sortie


def _importer_conversations(d, dossiers, ecraser, workspaces, rapport):
    dest = Path(dossiers["donnees"]) / "conversations"
    ok = ignorees = invalides = 0
    for src in d["conversations"]:
        if src.stat().st_size > CONVERSATION_MAX:
            invalides += 1
            continue
        c = _lire_json(src)
        if not isinstance(c, dict) or not isinstance(c.get("messages"), list) or not RE_ID.match(str(c.get("id", ""))):
            invalides += 1
            continue
        cible = dest / (str(c["id"]) + ".json")
        if cible.exists() and not ecraser:
            ignorees += 1
            continue
        c.pop("annulable", None)          # renvoie à des sauvegardes de fichiers de l'ancien assistant, absentes ici
        if c.get("travail") and c["travail"] not in workspaces:
            c.pop("travail")              # un dossier de travail qui n'existe pas ici : la conversation prendra le dossier actif à sa première utilisation
        _ecrire(cible, json.dumps(c, ensure_ascii=False))
        ok += 1
    rapport["conversations"] = {"importees": ok, "deja_presentes": ignorees, "illisibles": invalides}


def _importer_memoire(d, dossiers, ecraser, rapport):
    dest = Path(dossiers["memoire"])
    modeles = _gabarits_memoire()
    stamp = time.strftime("%Y%m%d")
    posees, a_cote, identiques = [], [], []
    for src in d["memoire"]:
        if src.stat().st_size > MEMOIRE_MAX:
            continue
        texte = src.read_text(encoding="utf-8-sig", errors="replace")
        cible = dest / src.name
        if not cible.exists():
            _ecrire(cible, texte)
            posees.append(src.name)
            continue
        actuel = cible.read_text(encoding="utf-8-sig", errors="replace")
        if actuel.strip() == texte.strip():
            identiques.append(src.name)
        elif ecraser or actuel.strip() in modeles.get(src.name, []):
            _ecrire(cible, texte)
            posees.append(src.name)
        else:
            _ecrire(dest / "{}.importe-{}.md".format(src.stem, stamp), texte)
            a_cote.append("{}.importe-{}.md".format(src.stem, stamp))
    rapport["memoire"] = {"posees": posees, "a_cote": a_cote, "identiques": identiques}


def _importer_skills(d, racine_travail, ecraser, rapport):
    dest = Path(racine_travail) / "skills"
    ok, ignores, refuses = [], [], []
    for src in d["skills"]:
        if not RE_NOM_MD.match(src.name) or src.stat().st_size > MEMOIRE_MAX:
            refuses.append(src.name)
            continue
        if (dest / src.name).exists() and not ecraser:
            ignores.append(src.name)
            continue
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest / src.name)
        ok.append(src.name)
    rapport["skills"] = {"importes": ok, "deja_presents": ignores, "refuses": refuses, "dossier": str(dest)}


def _importer_reglages(d, dossiers, rapport):
    ancien = _lire_json(d["reglages"])
    if not isinstance(ancien, dict):
        rapport["reglages"] = {"repris": [], "laisses": []}
        return
    chemin = Path(dossiers["donnees"]) / "reglages.json"
    actuel = _lire_json(chemin) if chemin.is_file() else {}
    actuel = actuel if isinstance(actuel, dict) else {}
    repris = [k for k in REGLAGES_REPRIS if k in ancien]
    for k in repris:
        actuel[k] = ancien[k]
    if repris:
        _ecrire(chemin, json.dumps(actuel, ensure_ascii=False, indent=1))
    rapport["reglages"] = {"repris": repris, "laisses": [k for k in REGLAGES_JAMAIS if k in ancien]}


def importer(d, dossiers, choix, racine_travail=None, ecraser=False, workspaces=()):
    """Reprend les catégories de `choix` (sous-ensemble de CATEGORIES). `dossiers` : {config, donnees, memoire} de Lutin ; `racine_travail` : où poser les skills ; `workspaces` : identifiants de
    dossiers de travail connus. Renvoie un rapport. Un zip de l'état actuel est gardé d'abord."""
    choix = [c for c in CATEGORIES if c in set(choix)]
    if not choix:
        raise ErreurReprise(_t("Rien n'est choisi."))
    if "skills" in choix and not racine_travail:
        raise ErreurReprise(_t("Pas de dossier de travail actif pour y poser les skills."))          # avant d'écrire quoi que ce soit : pas d'import à moitié
    rapport = {"choix": choix}
    avant = Path(dossiers["donnees"]) / "import" / "avant-import-{}.zip".format(time.strftime("%Y%m%d-%H%M%S"))
    avant.parent.mkdir(parents=True, exist_ok=True)
    tampon = io.BytesIO()
    sauvegarde.exporter({k: dossiers.get(k) for k in ("config", "donnees", "memoire")}, tampon)
    avant.write_bytes(tampon.getvalue())
    rapport["sauvegarde"] = str(avant)
    if "conversations" in choix:
        _importer_conversations(d, dossiers, ecraser, set(workspaces), rapport)
    if "memoire" in choix:
        _importer_memoire(d, dossiers, ecraser, rapport)
    if "skills" in choix:
        _importer_skills(d, racine_travail, ecraser, rapport)
    if "reglages" in choix and d["reglages"]:
        _importer_reglages(d, dossiers, rapport)
    return rapport


def resume(rapport):
    """Le rapport en lignes lisibles."""
    lignes = []
    c = rapport.get("conversations")
    if c:
        lignes.append(_t("Conversations : {} reprises, {} déjà présentes, {} illisibles.").format(c["importees"], c["deja_presentes"], c["illisibles"]))
    m = rapport.get("memoire")
    if m:
        lignes.append(_t("Mémoire : {} posés, {} mis à côté (ton fichier actuel est différent), {} identiques.").format(len(m["posees"]), len(m["a_cote"]), len(m["identiques"])))
        for n in m["a_cote"]:
            lignes.append("  → " + n)
    s = rapport.get("skills")
    if s:
        lignes.append(_t("Skills : {} repris dans {}, {} déjà présents, {} refusés.").format(len(s["importes"]), s["dossier"], len(s["deja_presents"]), len(s["refuses"])))
    r = rapport.get("reglages")
    if r:
        lignes.append(_t("Réglages : {} repris.").format(len(r["repris"])) + ((" " + _t("Non repris, à redonner toi-même : {}.").format(", ".join(r["laisses"]))) if r["laisses"] else ""))
    lignes.append(_t("Avant l'import, l'état de Lutin a été gardé dans : {}").format(rapport["sauvegarde"]))
    return lignes
