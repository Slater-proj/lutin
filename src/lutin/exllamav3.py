"""ExLlamaV3, piloté par Lutin à travers TabbyAPI, son serveur officiel compatible OpenAI (https://github.com/theroyallab/tabbyAPI).

ExLlamaV3 est le successeur d'ExLlamaV2 (même auteur, formats de modèles « EXL3 » plus fins, meilleure qualité à taille égale) ; TabbyAPI ne charge plus que lui. Il demande une carte graphique NVIDIA
(Windows ou Linux) et Python 3.10 à 3.14. Ce que ce module fait, sur clic explicite de l'utilisateur :
  - installer : récupérer le code de TabbyAPI à un commit précis (archive GitHub en HTTPS), créer un environnement Python dédié et y installer ses dépendances (`pip install .[cu12]`, plusieurs Go : torch) ;
  - démarrer et arrêter le serveur (127.0.0.1 seulement, sans clé : même niveau de confiance qu'Ollama sur cette machine, navigateurs distants refusés), le mettre à jour ;
  - télécharger un modèle EXL3 depuis Hugging Face (`main.py download`) et lister ceux qui sont là.
Rien n'est écrit hors du dossier du moteur. TabbyAPI n'a ni publications ni étiquettes : la version suivie est celle de la bibliothèque ExLlamaV3 (ses publications), le code de TabbyAPI est épinglé par son commit.
**Cette intégration n'a pas été essayée par Lutin sur une vraie carte NVIDIA** : les commandes viennent de la documentation de TabbyAPI."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import colibri, miseajour, outils_externes
from .i18n import t as _t
from .remplacement import remplacer_dossier

DEPOT_TABBY = "theroyallab/tabbyAPI"
DEPOT_LIB = "turboderp-org/exllamav3"
API_COMMIT = "https://api.github.com/repos/{}/commits/main".format(DEPOT_TABBY)
API_LIB = "https://api.github.com/repos/{}/releases/latest".format(DEPOT_LIB)
URL_ZIP = "https://codeload.github.com/{}/zip/{{}}".format(DEPOT_TABBY)
HOTE = "127.0.0.1"          # jamais une autre adresse
PORT_DEFAUT = 5000
RE_SHA = re.compile(r"^[0-9a-f]{40}$")
RE_VERSION = re.compile(r"^\d{1,3}(\.\d{1,4}){1,3}$")
RE_DEPOT_MODELE = re.compile(r"^[A-Za-z0-9][\w.-]{0,60}/[A-Za-z0-9][\w.-]{0,100}$")
RE_REVISION = re.compile(r"^[A-Za-z0-9][\w./-]{0,40}$")
TAILLE_ARCHIVE_MAX = 80_000_000
PYTHON_MIN, PYTHON_MAX = (3, 10), (3, 14)


def dossier(dossiers=None):
    from . import moteurs_docker
    return moteurs_docker.base_moteurs((dossiers or colibri.config.dossiers())["donnees"]) / "exllamav3"


def dossier_modeles(dossiers=None):
    return dossier(dossiers) / "modeles"


def dossier_tabby(dossiers=None):
    return dossier(dossiers) / "tabby"


def python_venv(dossiers=None):
    venv = dossier(dossiers) / "venv"
    return venv / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")


def lire_version(dossiers=None):
    try:
        d = json.loads((dossier(dossiers) / "version.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def installee(dossiers=None):
    """{tabby (commit), lib (version d'ExLlamaV3)} si TabbyAPI et son environnement sont là, sinon None."""
    v = lire_version(dossiers)
    if (dossier_tabby(dossiers) / "main.py").is_file() and python_venv(dossiers).is_file() and v.get("tabby"):
        return {"tabby": str(v.get("tabby", "")), "lib": str(v.get("lib", ""))}
    return None


def python_compatible(version=None):
    v = tuple(version or sys.version_info[:2])
    return PYTHON_MIN <= v <= PYTHON_MAX


def derniere_version_lib(http=miseajour.http_get):
    """La dernière version publiée d'ExLlamaV3 (X.Y.Z). ValueError si illisible, OSError sans réseau."""
    cause = ""
    try:
        statut, _, corps = http(API_LIB, {"Accept": "application/vnd.github+json"})
        if statut == 200:
            version = str(json.loads(corps.decode("utf-8")).get("tag_name", "")).lstrip("v")
            if not RE_VERSION.match(version):
                raise ValueError(_t("Numéro de version d'ExLlamaV3 illisible : {}").format(version[:30]))
            return version
        cause = "HTTP {}".format(statut)
    except OSError as e:
        cause = str(e)
    try:          # l'API de GitHub refuse (limite de requêtes) : la page publique des publications
        version = (miseajour.version_par_page(DEPOT_LIB, http) or "").lstrip("v")
        if RE_VERSION.match(version):
            return version
    except OSError:
        pass
    raise ValueError(_t("Impossible de lire la dernière version d'ExLlamaV3 ({}). GitHub limite parfois les requêtes : réessaie dans quelques minutes.").format(cause))


def dernier_commit(http=miseajour.http_get):
    cause = ""
    try:
        statut, _, corps = http(API_COMMIT, {"Accept": "application/vnd.github+json"})
        if statut == 200:
            sha = str(json.loads(corps.decode("utf-8")).get("sha", ""))
            if not RE_SHA.match(sha):
                raise ValueError(_t("Identifiant de version de TabbyAPI illisible."))
            return sha
        cause = "HTTP {}".format(statut)
    except OSError as e:
        cause = str(e)
    try:          # l'API refuse (limite de requêtes) : le flux public des modifications de la branche donne le même identifiant
        statut, _, corps = http("https://github.com/{}/commits/main.atom".format(DEPOT_TABBY), {"Accept": "application/atom+xml"})
        m = re.search(r"Commit/([0-9a-f]{40})", corps.decode("utf-8", "replace")) if statut == 200 else None
        if m:
            return m.group(1)
    except OSError:
        pass
    raise ValueError(_t("Impossible de lire le dernier code de TabbyAPI ({}). GitHub limite parfois les requêtes : réessaie dans quelques minutes.").format(cause))


def config_yaml(port, modeles):
    """Le config.yml de TabbyAPI : adresse locale, aucune clé (réservé à cette machine), pas de page web, aucune origine de navigateur admise, modèle chargé à la demande."""
    chemin = Path(modeles).as_posix()
    if "#" in chemin or "\n" in chemin or chemin.startswith(("'", '"')):
        raise ValueError(_t("Le chemin du dossier des modèles contient un caractère que TabbyAPI ne sait pas lire ('#', guillemet ou retour à la ligne)."))
    return ("network:\n  host: {}\n  port: {}\n  disable_auth: true\n  allowed_origins: []\n  web_ui: false\n"
            "logging:\n  log_auth_keys: false\nmodel:\n  model_dir: {}\n  inline_model_loading: true\n").format(HOTE, int(port), chemin)


def _suivre(proc, dire, annule=lambda: False):
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
    return code, fin


def _telecharger_zip(sha, destination, ouvrir=urllib.request.urlopen):
    req = urllib.request.Request(URL_ZIP.format(sha), headers={"User-Agent": "Lutin"})
    with ouvrir(req, timeout=60) as r:
        if urllib.parse.urlparse(str(r.geturl())).hostname not in ("codeload.github.com", "github.com"):
            raise ValueError(_t("Le code de TabbyAPI a été redirigé hors de GitHub : refusé."))
        corps = r.read(TAILLE_ARCHIVE_MAX + 1)
    if len(corps) > TAILLE_ARCHIVE_MAX or len(corps) < 100:
        raise ValueError(_t("L'archive de TabbyAPI est vide ou trop grosse : refusée."))
    Path(destination).write_bytes(corps)


def version_lib(dossiers=None, lancer=subprocess.run):
    """La version d'ExLlamaV3 installée dans l'environnement dédié (`pip show`), ou ''."""
    try:
        r = lancer([str(python_venv(dossiers)), "-m", "pip", "show", "exllamav3"], capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"^Version:\s*(\S+)", r.stdout or "", re.M)
    return m.group(1) if m and RE_VERSION.match(m.group(1)) else ""


def installer(dossiers=None, port=PORT_DEFAUT, dire=print, http=miseajour.http_get, ouvrir=urllib.request.urlopen, lancer=subprocess.Popen, annule=lambda: False, executer=subprocess.run, installer_uv=None):
    """Installe (ou met à jour) TabbyAPI + ExLlamaV3. Renvoie {tabby, lib}. Longue : torch pèse plusieurs Go. ValueError claire à chaque étape qui échoue."""
    if not python_compatible():
        raise ValueError(_t("Python {}.{} n'est pas pris en charge par TabbyAPI (3.10 à 3.14).").format(*sys.version_info[:2]))
    base = dossier(dossiers)
    base.mkdir(parents=True, exist_ok=True)
    dire(_t("Recherche du dernier code de TabbyAPI…"))
    sha = dernier_commit(http)
    cible = dossier_tabby(dossiers)
    with tempfile.TemporaryDirectory(prefix="lutin-tabby-") as tmp:
        archive = Path(tmp) / "tabby.zip"
        dire(_t("Téléchargement de TabbyAPI ({})…").format(sha[:7]))
        _telecharger_zip(sha, archive, ouvrir)
        partiel = base / "tabby.partiel"
        shutil.rmtree(partiel, ignore_errors=True)
        try:
            colibri.extraire(archive, partiel)
            racine = next((p for p in [partiel, *partiel.iterdir()] if p.is_dir() and (p / "main.py").is_file() and (p / "pyproject.toml").is_file()), None)
            if racine is None:
                raise ValueError(_t("TabbyAPI est introuvable dans l'archive."))
        except Exception:
            shutil.rmtree(partiel, ignore_errors=True)
            raise
        remplacer_dossier(racine, cible)
        shutil.rmtree(partiel, ignore_errors=True)
    venv = base / "venv"
    if not python_venv(dossiers).is_file():
        dire(_t("Création de l'environnement Python dédié…"))
        outils_externes.creer_venv(venv, dossiers, dire, executer, installer_uv)          # le Python de l'installateur Windows n'a pas « venv » : uv le remplace, installé au besoin
    dire(_t("Installation des dépendances (torch et ExLlamaV3 : plusieurs Go, patience)…"))
    proc = lancer([str(python_venv(dossiers)), "-m", "pip", "install", "-U", ".[cu12]"], cwd=str(cible), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    code, fin = _suivre(proc, dire, annule)
    if code != 0 and not annule():
        raise ValueError(_t("L'installation des dépendances a échoué (code {}). Fin du message :\n{}").format(code, "\n".join(fin[-6:])))
    lib = version_lib(dossiers, executer)
    dossier_modeles(dossiers).mkdir(parents=True, exist_ok=True)
    (cible / "config.yml").write_text(config_yaml(port, dossier_modeles(dossiers)), encoding="utf-8")
    (base / "version.json").write_text(json.dumps({"tabby": sha, "lib": lib, "installe": time.strftime("%Y-%m-%d %H:%M")}), encoding="utf-8")
    return {"tabby": sha, "lib": lib}


def repond(port):
    try:
        with urllib.request.urlopen("http://{}:{}/v1/models".format(HOTE, int(port)), timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def demarrer(port=PORT_DEFAUT, dossiers=None, attente_s=240, lancer=subprocess.Popen, repond_=repond, dormir=time.sleep):
    """Écrit le config.yml (port demandé), lance `main.py` de TabbyAPI dans son environnement, attend que /v1/models réponde (le premier démarrage charge torch : long)."""
    if repond_(port):
        return port
    if not installee(dossiers):
        raise ValueError(_t("ExLlamaV3 n'est pas installé : installe-le d'abord (Réglages > Moteur)."))
    tabby, base = dossier_tabby(dossiers), dossier(dossiers)
    (tabby / "config.yml").write_text(config_yaml(port, dossier_modeles(dossiers)), encoding="utf-8")
    journal = base / "tabby.log"
    extra = {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)} if os.name == "nt" else {"start_new_session": True}
    with open(journal, "wb") as sortie:
        proc = lancer([str(python_venv(dossiers)), "main.py"], cwd=str(tabby), stdout=sortie, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=dict(os.environ, PYTHONUNBUFFERED="1"), **extra)
    (base / "tabby.pid").write_text(str(proc.pid), encoding="utf-8")
    fin = time.time() + attente_s
    while time.time() < fin:
        if proc.poll() is not None:
            queue = journal.read_text(encoding="utf-8", errors="replace")[-600:] if journal.exists() else ""
            raise ValueError(_t("TabbyAPI s'est arrêté au démarrage. Fin de son journal :\n{}").format(queue))
        if repond_(port):
            return port
        dormir(1)
    raise ValueError(_t("TabbyAPI ne répond pas après {} s (son journal : {}).").format(attente_s, journal))


def arreter(dossiers=None, tuer=None):
    """Arrête TabbyAPI (et ses sous-processus) d'après le numéro de processus noté au démarrage. True s'il y avait quelque chose à arrêter ou si rien ne tournait."""
    if tuer is None:
        from .outils import tuer_arbre as tuer
    pid_fichier = dossier(dossiers) / "tabby.pid"
    try:
        pid = int(pid_fichier.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    try:
        tuer(pid)
    finally:
        try:
            pid_fichier.unlink()
        except OSError:
            pass
    return True


def desinstaller(dossiers=None):
    """Supprime le programme (code et environnement) ; les modèles téléchargés restent dans leur dossier."""
    arreter(dossiers)
    for nom in ("tabby", "venv", "tabby.partiel"):
        shutil.rmtree(dossier(dossiers) / nom, ignore_errors=True)
    for nom in ("version.json", "tabby.pid", "tabby.log"):
        try:
            (dossier(dossiers) / nom).unlink()
        except OSError:
            pass


def telecharger_modele(depot, revision="", dossiers=None, dire=print, lancer=subprocess.Popen, annule=lambda: False):
    """`main.py download <propriétaire/modèle> [--revision X]` : le téléchargeur de TabbyAPI (Hugging Face) dans le dossier des modèles."""
    depot, revision = str(depot or "").strip(), str(revision or "").strip()
    if not RE_DEPOT_MODELE.match(depot):
        raise ValueError(_t("Nom de dépôt invalide : écris « propriétaire/modèle » (Hugging Face)."))
    if revision and not RE_REVISION.match(revision):
        raise ValueError(_t("Révision invalide : {}").format(revision[:40]))
    if not installee(dossiers):
        raise ValueError(_t("ExLlamaV3 n'est pas installé : installe-le d'abord (Réglages > Moteur)."))
    tabby = dossier_tabby(dossiers)
    (tabby / "config.yml").write_text(config_yaml(PORT_DEFAUT, dossier_modeles(dossiers)), encoding="utf-8")
    cmd = [str(python_venv(dossiers)), "main.py", "download", depot] + (["--revision", revision] if revision else [])
    proc = lancer(cmd, cwd=str(tabby), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    code, fin = _suivre(proc, dire, annule)
    if code != 0 and not annule():
        raise ValueError(_t("Le téléchargement du modèle a échoué (code {}). Fin du message :\n{}").format(code, "\n".join(fin[-6:])))
    return True


def modeles(dossiers=None):
    """Les modèles téléchargés : [{nom, taille_go}] (un dossier avec un config.json)."""
    sortie = []
    racine = dossier_modeles(dossiers)
    try:
        sous = sorted(p for p in racine.iterdir() if p.is_dir() and (p / "config.json").is_file())
    except OSError:
        return []
    for p in sous:
        taille = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        sortie.append({"nom": p.name, "taille_go": round(taille / 1e9, 1)})
    return sortie
