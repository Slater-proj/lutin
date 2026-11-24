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

from . import config, updates
from .engine_replace import replace_folder
from .i18n import t as _t

REPO = "JustVugg/colibri"
PREFIX = "https://github.com/{}/releases/download/".format(REPO)
RE_NAME = re.compile(r"^colibri-v\d+\.\d+\.\d+-(windows|linux|macos)-[a-z0-9_]+\.(zip|tar\.gz)$")
RE_VERSION = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")
DEFAULT_PORT = 8000
HOST = "127.0.0.1"          # jamais une autre adresse : Colibri ne sort pas de cette machine


def archive_name(version, systeme=None, architecture=None):
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


def latest_version(http=updates.http_get):
    """Le numéro (X.Y.Z) de la dernière publication de Colibri, par l'API de GitHub. OSError sans réseau, ValueError si illisible."""
    cause = ""
    try:
        statut, _, corps = http("https://api.github.com/repos/{}/releases/latest".format(REPO), {"Accept": "application/vnd.github+json"})
        if statut == 200:
            version = str(json.loads(corps.decode("utf-8")).get("tag_name", "")).lstrip("v")
            if not RE_VERSION.match(version):
                raise ValueError(_t("Numéro de version de Colibri illisible : {}").format(version[:30]))
            return version
        cause = "HTTP {}".format(statut)
    except OSError as e:
        cause = str(e)
    try:          # l'API de GitHub refuse (limite de requêtes : HTTP 403) ou ne répond pas : la page publique des publications dit la même chose
        version = (updates.version_from_page(REPO, http) or "").lstrip("v")
        if RE_VERSION.match(version):
            return version
    except OSError:
        pass
    raise ValueError(_t("Impossible de lire la dernière version de Colibri ({}). {}").format(cause, updates.followup_error(cause)))


def folder_colibri(dossiers=None):
    from . import docker_engines
    return docker_engines.base_engines((dossiers or config.folders())["donnees"]) / "colibri"


def extract(archive, cible):
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
            tf.extractall(cible, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))          # noqa: S202  (chaque nom a été vérifié au-dessus ; le filtre vérifie chaque membre à l'écriture)


def archive_root(cible):
    """Le dossier qui contient `coli` (à la racine de l'archive, ou dans un seul sous-dossier)."""
    cible = Path(cible)
    if (cible / "coli").is_file():
        return cible
    for sous in cible.iterdir():
        if sous.is_dir() and (sous / "coli").is_file():
            return sous
    raise ValueError(_t("Le script « coli » est introuvable dans l'archive de Colibri."))


def install(version=None, dossiers=None, http=updates.http_get, ouvrir=urllib.request.urlopen, systeme=None, architecture=None, dire=print):
    """Télécharge, vérifie et décompresse Colibri. Renvoie (version, dossier contenant `coli`). Ne fait rien si cette version est déjà là."""
    version = (version or latest_version(http)).lstrip("v")
    if not RE_VERSION.match(version):
        raise ValueError(_t("Numéro de version invalide (exemple : 2.1.0)."))
    nom = archive_name(version, systeme, architecture)
    base = folder_colibri(dossiers)
    cible = base / ("v" + version)
    if (cible / "coli").is_file() or (cible.is_dir() and any(cible.glob("*/coli"))):
        dire(_t("Colibri {} est déjà installé.").format(version))
    else:
        url = "{}v{}/{}".format(PREFIX, version, nom)
        with tempfile.TemporaryDirectory(prefix="lutin-colibri-") as tmp:
            dire(_t("Téléchargement de {} …").format(nom))
            archive, _ = updates.download_verified_wheel(url, tmp, http=http, ouvrir=ouvrir, nom_valide=RE_NAME, exiger_sommes=True, prefixe=PREFIX)
            dire(_t("✔ Somme SHA-256 vérifiée."))
            partiel = base / ("v" + version + ".partiel")
            shutil.rmtree(partiel, ignore_errors=True)
            try:
                extract(archive, partiel)
                archive_root(partiel)
            except (ValueError, OSError, zipfile.BadZipFile, tarfile.TarError):
                shutil.rmtree(partiel, ignore_errors=True)
                raise
            replace_folder(partiel, cible)          # même remplacement robuste que llama.cpp (antivirus, fichiers ouverts sous Windows)
    (base / "actuelle.txt").write_text(version, encoding="utf-8")
    return version, archive_root(cible)


def installed(dossiers=None):
    """(version, dossier contenant `coli`), ou None."""
    base = folder_colibri(dossiers)
    try:
        version = (base / "actuelle.txt").read_text(encoding="utf-8").strip()
        return version, archive_root(base / ("v" + version))
    except (OSError, ValueError):
        return None


def command_server(racine, modele, port=DEFAULT_PORT, python=None):
    """La commande de Colibri (`coli serve`), toujours sur 127.0.0.1."""
    return [python or sys.executable, str(Path(racine) / "coli"), "serve", "--host", HOST, "--port", str(int(port)), "--model", str(modele)]


def responds(port):
    """Le serveur de Colibri répond-il sur /v1/models ? (en clair, sur la boucle locale seulement)"""
    try:
        with urllib.request.urlopen("http://{}:{}/v1/models".format(HOST, int(port)), timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start(modele, port=DEFAULT_PORT, dossiers=None, attente_s=90, lancer=subprocess.Popen, repond_=responds, dormir=time.sleep):
    """Lance `coli serve` sur un dossier de modèle déjà préparé par Colibri (`coli setup` ou `coli import`), puis attend qu'il réponde. ValueError avec la fin du journal s'il s'arrête."""
    trouve = installed(dossiers)
    if not trouve:
        raise ValueError(_t("Colibri n'est pas installé : lance d'abord « lutin colibri install »."))
    if not Path(modele).is_dir():
        raise ValueError(_t("Le dossier de modèle n'existe pas : {} (prépare-le avec « coli setup » ou « coli import » de Colibri).").format(modele))
    _, racine = trouve
    journal = folder_colibri(dossiers) / "colibri.log"
    journal.parent.mkdir(parents=True, exist_ok=True)
    extra = {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)} if sys.platform.startswith("win") else {"start_new_session": True}
    with open(journal, "wb") as sortie:
        proc = lancer(command_server(racine, modele, port), cwd=str(racine), stdout=sortie, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **extra)
    fin = time.time() + attente_s
    while time.time() < fin:
        if proc.poll() is not None:
            fin_journal = journal.read_text(encoding="utf-8", errors="replace")[-600:] if journal.exists() else ""
            raise ValueError(_t("Colibri s'est arrêté au démarrage. Fin de son journal :\n{}").format(fin_journal))
        if repond_(port):
            return port
        dormir(1)
    raise ValueError(_t("Colibri ne répond pas après {} s (son journal : {}).").format(attente_s, journal))


def setup_home():
    """Où `coli setup` garde sa configuration (la même règle que Colibri : COLI_SETUP_HOME, sinon le dossier de données de l'utilisateur)."""
    import os
    explicite = os.environ.get("COLI_SETUP_HOME")
    if explicite:
        return Path(explicite).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "colibri"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "colibri"
    return Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "colibri"


def model_of_setup():
    """Le dossier du modèle que `coli setup` a préparé (lu dans son setup.json, sans rien lancer), ou '' : Lutin sait alors démarrer Colibri sans qu'on lui indique le dossier."""
    try:
        d = json.loads((setup_home() / "setup.json").read_text(encoding="utf-8"))
        m = str(d.get("model_dir") or "")
    except (OSError, ValueError, AttributeError):
        return ""
    return m if m and Path(m).is_dir() else ""


RE_CATALOGUE_LINE = re.compile(r"^\s+([a-z0-9][a-z0-9._-]{1,40})\s+(\d+(?:\.\d+)?) GB\s+(\S+)\s*(.*)$")


def catalogue(dossiers=None, lancer=subprocess.run):
    """Les modèles que Colibri sait préparer, jugés pour CETTE machine par Colibri lui-même (`coli setup --list --all`) : [{id, go, ok, statut, raison}].
    `ok` : le modèle tient (mémoire et disque). Lecture seule : rien n'est téléchargé. ValueError si Colibri n'est pas installé ou ne répond pas."""
    trouve = installed(dossiers)
    if not trouve:
        raise ValueError(_t("Colibri n'est pas installé : installe-le d'abord (Réglages > Moteur)."))
    try:
        r = lancer([sys.executable, str(Path(trouve[1]) / "coli"), "setup", "--list", "--all", "--dir", str(folder_models(dossiers))], cwd=str(trouve[1]), capture_output=True, text=True, timeout=90, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError(_t("Colibri n'a pas pu lister ses modèles : {}").format(e)) from None
    modeles = []
    for ligne in (r.stdout or "").splitlines():
        m = RE_CATALOGUE_LINE.match(ligne)
        if m:
            modeles.append({"id": m.group(1), "go": float(m.group(2)), "ok": not m.group(3).startswith("needs"), "statut": m.group(3), "raison": m.group(4).strip()})
    if not modeles:
        raise ValueError(_t("Colibri n'a rendu aucun modèle (version trop différente ?). Sa réponse : {}").format(((r.stdout or "") + (r.stderr or ""))[-300:]))
    return modeles


def folder_models(dossiers=None):
    """Où Colibri télécharge les modèles qu'on lui fait préparer : le dossier de Colibri dans les données de Lutin."""
    return folder_colibri(dossiers) / "modeles"


def _size_folder(chemin, max_fichiers=20000):
    """Go occupés par un dossier (parcours borné : un modèle de Colibri pèse des centaines de Go, mais pas des millions de fichiers)."""
    total, vus = 0, 0
    for racine, _, fichiers in os.walk(chemin):
        for f in fichiers:
            vus += 1
            if vus > max_fichiers:
                return round(total / 1e9, 1)
            try:
                total += os.path.getsize(os.path.join(racine, f))
            except OSError:
                pass
    return round(total / 1e9, 1)


def installed_models(dossiers=None, modele=""):
    """Les modèles déjà préparés : [{nom, chemin, taille_go, supprimable}] — les sous-dossiers du dossier des modèles de Lutin (supprimables) et, s'il est ailleurs, le dossier réglé ou préparé par `coli setup` (jamais supprimé par Lutin)."""
    racine = folder_models(dossiers)
    sortie, vus = [], set()
    try:
        sous = sorted(p for p in racine.iterdir() if p.is_dir())
    except OSError:
        sous = []
    for p in sous:
        sortie.append({"nom": p.name, "chemin": str(p), "taille_go": _size_folder(p), "supprimable": True})
        vus.add(os.path.normcase(str(p)))
    if modele and Path(modele).is_dir() and os.path.normcase(str(Path(modele))) not in vus:
        sortie.append({"nom": Path(modele).name, "chemin": str(modele), "taille_go": _size_folder(modele), "supprimable": False})
    return sortie


def remove_model(nom, dossiers=None):
    """Supprime un modèle préparé dans le dossier de Lutin (un sous-dossier direct du dossier des modèles, rien d'autre)."""
    nom = str(nom or "")
    racine = folder_models(dossiers)
    cible = racine / nom
    if not nom or nom in (".", "..") or "/" in nom or "\\" in nom or not cible.is_dir() or cible.parent.resolve() != racine.resolve():
        raise ValueError(_t("Ce modèle n'est pas dans le dossier des modèles de Colibri : Lutin ne supprime que ce qu'il a téléchargé."))
    shutil.rmtree(cible)
    return True


def prepare(ident, port=DEFAULT_PORT, dossiers=None, dire=print, lancer=subprocess.Popen, annule=lambda: False):
    """`coli setup --model ID --yes --background` : Colibri vérifie la machine, prend le moteur adapté, télécharge le modèle (reprise possible si on l'interrompt) et démarre son serveur sur 127.0.0.1.
    Le modèle fait de quelques dizaines à plusieurs centaines de Go. Seuls les modèles du catalogue de Colibri sont acceptés. Chaque ligne que Colibri écrit est transmise à `dire`."""
    modeles = {m["id"]: m for m in catalogue(dossiers)}
    if ident not in modeles:
        raise ValueError(_t("Modèle inconnu de Colibri : {}").format(str(ident)[:40]))
    if not modeles[ident]["ok"]:
        raise ValueError(_t("Ce modèle ne tient pas sur cette machine : {}").format(modeles[ident]["raison"]))
    _, racine = installed(dossiers)
    dossier = folder_models(dossiers)
    dossier.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(Path(racine) / "coli"), "setup", "--model", ident, "--yes", "--no-browser", "--background", "--host", HOST, "--port", str(int(port)), "--dir", str(dossier)]
    proc = lancer(cmd, cwd=str(racine), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    fin = []
    try:
        for ligne in proc.stdout:
            ligne = ligne.strip()
            if ligne:
                fin = (fin + [ligne])[-12:]
                dire(ligne[:200])
            if annule():
                proc.terminate()
                break
        code = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if code != 0 and not annule():
        raise ValueError(_t("Colibri s'est arrêté (code {}). Fin de son message :\n{}").format(code, "\n".join(fin[-6:])))
    return True


def stop(port=DEFAULT_PORT, dossiers=None, lancer=subprocess.run):
    """`coli stop --port N` : Colibri arrête son serveur et son moteur."""
    trouve = installed(dossiers)
    if not trouve:
        raise ValueError(_t("Colibri n'est pas installé : lance d'abord « lutin colibri install »."))
    r = lancer([sys.executable, str(Path(trouve[1]) / "coli"), "stop", "--port", str(int(port))], cwd=str(trouve[1]), capture_output=True, text=True, timeout=60)
    return r.returncode == 0
