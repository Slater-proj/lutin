"""Colibri (moteur expérimental, voir docs/EXPERIMENTAL_ENGINES.md) : installer, démarrer, arrêter, en ligne de commande seulement.

Ce que ce module fait, et seulement sur commande explicite de l'utilisateur (`lutin colibri …`) :
  - télécharger l'archive officielle de la dernière publication de JustVugg/colibri et **vérifier sa somme SHA-256** (le SHA256SUMS.txt de la publication est obligatoire) ;
  - la décompresser dans le dossier de données de Lutin (rien n'est écrit ailleurs) ;
  - lancer `coli serve` (adresse locale 127.0.0.1 seulement) et `coli stop`, les commandes décrites par Colibri lui-même.
Ce qu'il ne fait PAS : choisir ou télécharger un modèle (plusieurs dizaines de Go : `coli setup` / `coli import` de Colibri), ni l'exposer sur le réseau.
Les commandes viennent de la lecture du script `coli` de la v2.1.0 ; **Colibri n'a pas été lancé avec un modèle** : le démarrage est à essayer (voir docs/TRIALS.md, S3)."""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import config, miseajour
from .i18n import t as _t

DEPOT = "JustVugg/colibri"
PREFIXE = "https://github.com/{}/releases/download/".format(DEPOT)
RE_NOM = re.compile(r"^colibri-v\d+\.\d+\.\d+-(windows|linux|macos)-[a-z0-9_]+\.(zip|tar\.gz)$")
RE_VERSION = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")
PORT_DEFAUT = 8000
HOTE = "127.0.0.1"          # jamais une autre adresse : Colibri ne sort pas de cette machine


def nom_archive(version, systeme=None, architecture=None):
    """Le nom de l'archive officielle pour ce système (les archives listées par la publication v2.1.0), ou ValueError."""
    systeme = (systeme or sys.platform).lower()
    architecture = (architecture or __import__("platform").machine()).lower()
    x86 = architecture in ("amd64", "x86_64", "x64")
    if systeme.startswith("win") and x86:
        fin = "windows-x86_64.zip"
    elif systeme.startswith("linux") and x86:
        fin = "linux-x86_64.tar.gz"
    elif systeme in ("darwin", "macos") and architecture in ("arm64", "aarch64"):
        fin = "macos-arm64.tar.gz"
    else:
        raise ValueError(_t("Colibri ne publie pas d'archive pour ce système ({} {}).").format(systeme, architecture))
    return "colibri-v{}-{}".format(version, fin)


def derniere_version(http=miseajour.http_get):
    """Le numéro (X.Y.Z) de la dernière publication de Colibri, par l'API de GitHub. OSError sans réseau, ValueError si illisible."""
    statut, _, corps = http("https://api.github.com/repos/{}/releases/latest".format(DEPOT), {"Accept": "application/vnd.github+json"})
    if statut != 200:
        raise ValueError(_t("Impossible de lire la dernière version de Colibri (HTTP {}).").format(statut))
    version = str(json.loads(corps.decode("utf-8")).get("tag_name", "")).lstrip("v")
    if not RE_VERSION.match(version):
        raise ValueError(_t("Numéro de version de Colibri illisible : {}").format(version[:30]))
    return version


def dossier_colibri(dossiers=None):
    return Path((dossiers or config.dossiers())["donnees"]) / "moteurs" / "colibri"


def extraire(archive, cible):
    """Décompresse sans jamais écrire hors de `cible` (un nom de fichier malveillant comme « ../x » est refusé)."""
    cible = Path(cible).resolve()
    cible.mkdir(parents=True, exist_ok=True)

    def sur(nom):
        dest = (cible / nom).resolve()
        if cible != dest and cible not in dest.parents:
            raise ValueError(_t("Archive refusée : un fichier sortirait du dossier d'installation ({}).").format(nom[:80]))
        return dest
    archive = str(archive)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for i in z.infolist():
                sur(i.filename)
            z.extractall(cible)
    else:
        with tarfile.open(archive) as tf:
            for m in tf.getmembers():
                sur(m.name)
                if m.issym() or m.islnk() or m.isdev():
                    raise ValueError(_t("Archive refusée : lien ou fichier spécial ({}).").format(m.name[:80]))
            tf.extractall(cible)          # noqa: S202  (chaque nom a été vérifié au-dessus)


def racine_archive(cible):
    """Le dossier qui contient `coli` (à la racine de l'archive, ou dans un seul sous-dossier)."""
    cible = Path(cible)
    if (cible / "coli").is_file():
        return cible
    for sous in cible.iterdir():
        if sous.is_dir() and (sous / "coli").is_file():
            return sous
    raise ValueError(_t("Le script « coli » est introuvable dans l'archive de Colibri."))


def installer(version=None, dossiers=None, http=miseajour.http_get, ouvrir=urllib.request.urlopen, systeme=None, architecture=None, dire=print):
    """Télécharge, vérifie et décompresse Colibri. Renvoie (version, dossier contenant `coli`). Ne fait rien si cette version est déjà là."""
    version = (version or derniere_version(http)).lstrip("v")
    if not RE_VERSION.match(version):
        raise ValueError(_t("Numéro de version invalide (exemple : 2.1.0)."))
    nom = nom_archive(version, systeme, architecture)
    base = dossier_colibri(dossiers)
    cible = base / ("v" + version)
    if (cible / "coli").is_file() or (cible.is_dir() and any(cible.glob("*/coli"))):
        dire(_t("Colibri {} est déjà installé.").format(version))
    else:
        url = "{}v{}/{}".format(PREFIXE, version, nom)
        with tempfile.TemporaryDirectory(prefix="lutin-colibri-") as tmp:
            dire(_t("Téléchargement de {} …").format(nom))
            archive, _ = miseajour.telecharger_roue_verifiee(url, tmp, http=http, ouvrir=ouvrir, nom_valide=RE_NOM, exiger_sommes=True, prefixe=PREFIXE)
            dire(_t("✔ Somme SHA-256 vérifiée."))
            partiel = base / ("v" + version + ".partiel")
            shutil.rmtree(partiel, ignore_errors=True)
            try:
                extraire(archive, partiel)
                racine_archive(partiel)
            except (ValueError, OSError, zipfile.BadZipFile, tarfile.TarError):
                shutil.rmtree(partiel, ignore_errors=True)
                raise
            shutil.rmtree(cible, ignore_errors=True)
            os.replace(partiel, cible)
    (base / "actuelle.txt").write_text(version, encoding="utf-8")
    return version, racine_archive(cible)


def installee(dossiers=None):
    """(version, dossier contenant `coli`), ou None."""
    base = dossier_colibri(dossiers)
    try:
        version = (base / "actuelle.txt").read_text(encoding="utf-8").strip()
        return version, racine_archive(base / ("v" + version))
    except (OSError, ValueError):
        return None


def commande_serveur(racine, modele, port=PORT_DEFAUT, python=None):
    """La commande de Colibri (`coli serve`), toujours sur 127.0.0.1."""
    return [python or sys.executable, str(Path(racine) / "coli"), "serve", "--host", HOTE, "--port", str(int(port)), "--model", str(modele)]


def repond(port):
    """Le serveur de Colibri répond-il sur /v1/models ? (en clair, sur la boucle locale seulement)"""
    try:
        with urllib.request.urlopen("http://{}:{}/v1/models".format(HOTE, int(port)), timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def demarrer(modele, port=PORT_DEFAUT, dossiers=None, attente_s=90, lancer=subprocess.Popen, repond_=repond, dormir=time.sleep):
    """Lance `coli serve` sur un dossier de modèle déjà préparé par Colibri (`coli setup` ou `coli import`), puis attend qu'il réponde. ValueError avec la fin du journal s'il s'arrête."""
    trouve = installee(dossiers)
    if not trouve:
        raise ValueError(_t("Colibri n'est pas installé : lance d'abord « lutin colibri installer »."))
    if not Path(modele).is_dir():
        raise ValueError(_t("Le dossier de modèle n'existe pas : {} (prépare-le avec « coli setup » ou « coli import » de Colibri).").format(modele))
    _, racine = trouve
    journal = dossier_colibri(dossiers) / "colibri.log"
    journal.parent.mkdir(parents=True, exist_ok=True)
    extra = {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)} if sys.platform.startswith("win") else {"start_new_session": True}
    with open(journal, "wb") as sortie:
        proc = lancer(commande_serveur(racine, modele, port), cwd=str(racine), stdout=sortie, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **extra)
    fin = time.time() + attente_s
    while time.time() < fin:
        if proc.poll() is not None:
            fin_journal = journal.read_text(encoding="utf-8", errors="replace")[-600:] if journal.exists() else ""
            raise ValueError(_t("Colibri s'est arrêté au démarrage. Fin de son journal :\n{}").format(fin_journal))
        if repond_(port):
            return port
        dormir(1)
    raise ValueError(_t("Colibri ne répond pas après {} s (son journal : {}).").format(attente_s, journal))


def arreter(port=PORT_DEFAUT, dossiers=None, lancer=subprocess.run):
    """`coli stop --port N` : Colibri arrête son serveur et son moteur."""
    trouve = installee(dossiers)
    if not trouve:
        raise ValueError(_t("Colibri n'est pas installé : lance d'abord « lutin colibri installer »."))
    r = lancer([sys.executable, str(Path(trouve[1]) / "coli"), "stop", "--port", str(int(port))], cwd=str(trouve[1]), capture_output=True, text=True, timeout=60)
    return r.returncode == 0
