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
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import colibri, updates, external_programs
from .i18n import t as _t
from .engine_replace import replace_folder

REPO_TABBY = "theroyallab/tabbyAPI"
REPO_LIB = "turboderp-org/exllamav3"
API_COMMIT = "https://api.github.com/repos/{}/commits/main".format(REPO_TABBY)
API_LIB = "https://api.github.com/repos/{}/releases/latest".format(REPO_LIB)
URL_ZIP = "https://codeload.github.com/{}/zip/{{}}".format(REPO_TABBY)
HOST = "127.0.0.1"          # jamais une autre adresse
PORT_DEFAUT = 5000
RE_SHA = re.compile(r"^[0-9a-f]{40}$")
RE_VERSION = re.compile(r"^\d{1,3}(\.\d{1,4}){1,3}$")
RE_REPO_MODEL = re.compile(r"^[A-Za-z0-9][\w.-]{0,60}/[A-Za-z0-9][\w.-]{0,100}$")
RE_REVISION = re.compile(r"^[A-Za-z0-9][\w./-]{0,40}$")
TAILLE_ARCHIVE_MAX = 80_000_000
INTERVAL_PROGRESS_S = 1.5          # la progression d'un téléchargement est relue toutes les 1,5 s
FILE_ORIGIN = ".lutin.json"          # dans le dossier d'un modèle : d'où il vient
PYTHON_MIN, PYTHON_MAX = (3, 10), (3, 14)


def folder(dossiers=None):
    from . import docker_engines
    return docker_engines.base_engines((dossiers or colibri.config.folders())["donnees"]) / "exllamav3"


def folder_models(dossiers=None):
    """Où TabbyAPI range les modèles : le dossier choisi par l'utilisateur (dossiers["modeles"]), sinon le sous-dossier « modeles » du dossier d'ExLlamaV3."""
    choisi = (dossiers or {}).get("modeles")
    return Path(choisi) if choisi else folder(dossiers) / "modeles"


def folder_tabby(dossiers=None):
    return folder(dossiers) / "tabby"


def python_venv(dossiers=None):
    venv = folder(dossiers) / "venv"
    return venv / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")


def lire_version(dossiers=None):
    try:
        d = json.loads((folder(dossiers) / "version.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def installed(dossiers=None):
    """{tabby (commit), lib (version d'ExLlamaV3)} si TabbyAPI et son environnement sont là, sinon None."""
    v = lire_version(dossiers)
    if (folder_tabby(dossiers) / "main.py").is_file() and python_venv(dossiers).is_file() and v.get("tabby"):
        return {"tabby": str(v.get("tabby", "")), "lib": str(v.get("lib", ""))}
    return None


def python_compatible(version=None):
    v = tuple(version or sys.version_info[:2])
    return PYTHON_MIN <= v <= PYTHON_MAX


def derniere_version_lib(http=updates.http_get):
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
        version = (updates.version_par_page(REPO_LIB, http) or "").lstrip("v")
        if RE_VERSION.match(version):
            return version
    except OSError:
        pass
    raise ValueError(_t("Impossible de lire la dernière version d'ExLlamaV3 ({}). {}").format(cause, updates.followup_error(cause)))


def dernier_commit(http=updates.http_get):
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
        statut, _, corps = http("https://github.com/{}/commits/main.atom".format(REPO_TABBY), {"Accept": "application/atom+xml"})
        m = re.search(r"Commit/([0-9a-f]{40})", corps.decode("utf-8", "replace")) if statut == 200 else None
        if m:
            return m.group(1)
    except OSError:
        pass
    raise ValueError(_t("Impossible de lire le dernier code de TabbyAPI ({}). {}").format(cause, updates.followup_error(cause)))


DEFAULT_CONTEXT = 16384          # jetons de conversation gardés en mémoire vidéo quand on ne sait pas mieux (le modèle en annonce parfois 128 000 ou plus : sa mémoire à elle seule dépasserait la carte)


def config_yaml(port, modeles, contexte=0):
    """Le config.yml de TabbyAPI : adresse locale, aucune clé (réservé à cette machine), pas de page web, aucune origine de navigateur admise, modèle chargé à la demande.
    `contexte` : la longueur de conversation gardée en mémoire vidéo (celle des réglages de Lutin) et une mémoire de conversation compressée (Q8) : sans cela TabbyAPI réserve la longueur maximale du modèle
    (262 144 jetons pour un Qwen récent) et refuse de le charger (« Insufficient VRAM in split for model and cache »).
    Un modèle chargé à la demande n'hérite de ces trois réglages que s'ils sont nommés dans `use_as_default` (TabbyAPI les ignore sinon, et le dit dans son journal) ;
    `cache_size` est la taille du cache, un multiple de 256 au moins égal à `max_seq_len`."""
    contexte = int(contexte or 0)
    contexte = max(2048, min(262144, contexte)) if contexte else DEFAULT_CONTEXT
    cache = -(-contexte // 256) * 256
    chemin = Path(modeles).as_posix()
    if "#" in chemin or "\n" in chemin or chemin.startswith(("'", '"')):
        raise ValueError(_t("Le chemin du dossier des modèles contient un caractère que TabbyAPI ne sait pas lire ('#', guillemet ou retour à la ligne)."))
    return ("network:\n  host: {}\n  port: {}\n  disable_auth: true\n  allowed_origins: []\n  web_ui: false\n"
            "logging:\n  log_auth_keys: false\nmodel:\n  model_dir: {}\n  inline_model_loading: true\n  use_as_default: [max_seq_len, cache_size, cache_mode]\n"
            "  max_seq_len: {}\n  cache_size: {}\n  cache_mode: Q8\n").format(HOST, int(port), chemin, contexte, cache)


def _follow(proc, dire, annule=lambda: False):
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


def _download_zip(sha, destination, ouvrir=urllib.request.urlopen):
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


ETAPES_INSTALLATION = 5


def install(dossiers=None, port=PORT_DEFAUT, dire=print, http=updates.http_get, ouvrir=urllib.request.urlopen, lancer=subprocess.Popen, annule=lambda: False, executer=subprocess.run, installer_uv=None, etape=None,
            contexte=0):
    """Installe (ou met à jour) TabbyAPI + ExLlamaV3. Renvoie {tabby, lib}. Longue : torch pèse plusieurs Go. ValueError claire à chaque étape qui échoue.
    `etape(n, total)` est appelée au début de chacune des ETAPES_INSTALLATION étapes : la page en fait une barre, et chaque texte annonce « Étape n/total »."""
    if not python_compatible():
        raise ValueError(_t("Python {}.{} n'est pas pris en charge par TabbyAPI (3.10 à 3.14).").format(*sys.version_info[:2]))
    courante = [0]

    def passer(n, texte):
        courante[0] = n
        if etape:
            etape(n, ETAPES_INSTALLATION)
        dire(_t("Étape {}/{} : {}").format(n, ETAPES_INSTALLATION, texte))
    base = folder(dossiers)
    base.mkdir(parents=True, exist_ok=True)
    passer(1, _t("recherche du dernier code de TabbyAPI…"))
    sha = dernier_commit(http)
    cible = folder_tabby(dossiers)
    with tempfile.TemporaryDirectory(prefix="lutin-tabby-") as tmp:
        archive = Path(tmp) / "tabby.zip"
        passer(2, _t("téléchargement de TabbyAPI ({})…").format(sha[:7]))
        _download_zip(sha, archive, ouvrir)
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
        replace_folder(racine, cible)
        shutil.rmtree(partiel, ignore_errors=True)
    venv = base / "venv"
    if not python_venv(dossiers).is_file():
        passer(3, _t("création de l'environnement Python dédié…"))
        external_programs.create_venv(venv, dossiers, dire, executer, installer_uv)          # le Python de l'installateur Windows n'a pas « venv » : uv le remplace, installé au besoin
    else:
        passer(3, _t("environnement Python dédié déjà là."))
    passer(4, _t("installation des dépendances (torch et ExLlamaV3 : plusieurs Go, plusieurs minutes — la ligne ci-dessous montre ce que pip fait)…"))
    proc = lancer([str(python_venv(dossiers)), "-m", "pip", "install", "-U", ".[cu12]"], cwd=str(cible), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    code, fin = _follow(proc, lambda ligne: dire(_t("Étape {}/{} : installation des dépendances — {}").format(4, ETAPES_INSTALLATION, ligne)), annule)
    if code != 0 and not annule():
        raise ValueError(_t("L'installation des dépendances a échoué (code {}). Fin du message :\n{}").format(code, "\n".join(fin[-6:])))
    passer(5, _t("vérification et réglages…"))
    lib = version_lib(dossiers, executer)
    folder_models(dossiers).mkdir(parents=True, exist_ok=True)
    (cible / "config.yml").write_text(config_yaml(port, folder_models(dossiers), contexte), encoding="utf-8")
    (base / "version.json").write_text(json.dumps({"tabby": sha, "lib": lib, "installe": time.strftime("%Y-%m-%d %H:%M")}), encoding="utf-8")
    return {"tabby": sha, "lib": lib}


def repond(port):
    try:
        with urllib.request.urlopen("http://{}:{}/v1/models".format(HOST, int(port)), timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start(port=PORT_DEFAUT, dossiers=None, attente_s=240, lancer=subprocess.Popen, repond_=repond, dormir=time.sleep, contexte=0):
    """Écrit le config.yml (port demandé), lance `main.py` de TabbyAPI dans son environnement, attend que /v1/models réponde (le premier démarrage charge torch : long)."""
    if repond_(port):
        return port
    if not installed(dossiers):
        raise ValueError(_t("ExLlamaV3 n'est pas installé : installe-le d'abord (Réglages > Moteur)."))
    tabby, base = folder_tabby(dossiers), folder(dossiers)
    (tabby / "config.yml").write_text(config_yaml(port, folder_models(dossiers), contexte), encoding="utf-8")
    journal = base / "tabby.log"
    extra = {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)} if os.name == "nt" else {"start_new_session": True}
    with open(journal, "wb") as sortie:
        # UTF-8 : sous Windows, un journal redirigé vers un fichier s'écrit sinon dans la page de code du système, et la barre de chargement de TabbyAPI
        # (des caractères de dessin) y fait échouer le chargement du modèle (« 'charmap' codec can't encode character »).
        proc = lancer([str(python_venv(dossiers)), "main.py"], cwd=str(tabby), stdout=sortie, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                      env=dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1"), **extra)
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


def stop(dossiers=None, tuer=None):
    """Arrête TabbyAPI (et ses sous-processus) d'après le numéro de processus noté au démarrage. True s'il y avait quelque chose à arrêter ou si rien ne tournait."""
    if tuer is None:
        from .tools import tuer_arbre as tuer
    pid_fichier = folder(dossiers) / "tabby.pid"
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


def uninstall(dossiers=None):
    """Supprime le programme (code et environnement) ; les modèles téléchargés restent dans leur dossier."""
    stop(dossiers)
    for nom in ("tabby", "venv", "tabby.partiel"):
        shutil.rmtree(folder(dossiers) / nom, ignore_errors=True)
    for nom in ("version.json", "tabby.pid", "tabby.log"):
        try:
            (folder(dossiers) / nom).unlink()
        except OSError:
            pass


def name_folder_model(depot, revision=""):
    """Le dossier où `main.py download` range un modèle : le nom du dépôt, suivi de « _révision » quand une révision est demandée."""
    nom = str(depot).split("/")[-1]
    return nom + ("_" + revision if revision else "")


def _folders_models(dossiers):
    try:
        return {p.name for p in folder_models(dossiers).iterdir() if p.is_dir()}
    except OSError:
        return set()


def note_model(dossiers, nom, depot, revision, commit):
    """Garde d'où vient un modèle téléchargé (dépôt, révision, empreinte de la révision) : sans cela, impossible de dire plus tard qu'une version plus récente existe."""
    try:
        (folder_models(dossiers) / nom / FILE_ORIGIN).write_text(json.dumps({"depot": depot, "revision": revision, "commit": commit}), encoding="utf-8")
    except OSError:
        pass


def origin_model(dossiers, nom):
    """{depot, revision, commit} d'un modèle téléchargé par Lutin, {} sinon (modèle posé à la main dans le dossier)."""
    try:
        d = json.loads((folder_models(dossiers) / nom / FILE_ORIGIN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: str(d.get(k, "")) for k in ("depot", "revision", "commit")} if isinstance(d, dict) else {}


def bytes_folder(chemin):
    """Octets déjà posés dans un dossier, fichiers en cours de téléchargement compris (ceux de Hugging Face sont dans un sous-dossier caché)."""
    total = 0
    for racine, _, fichiers in os.walk(chemin):
        for f in fichiers:
            try:
                total += os.path.getsize(os.path.join(racine, f))
            except OSError:
                pass
    return total


def _follow_size(cible, total, dire, progres, arret):
    """Toutes les 1,5 s : « 3,2 / 14,8 Go (21 %) · 45 Mo/s ». Le téléchargeur de TabbyAPI écrit une barre sur UNE ligne qui se réécrit : sans cela, rien ne s'affichait jusqu'à la fin."""
    dernier, t0, vitesse = bytes_folder(cible), time.monotonic(), 0.0
    while not arret.wait(INTERVAL_PROGRESS_S):
        maintenant = max(bytes_folder(cible), dernier)          # un fichier qui change de nom en fin de course peut faire passer la taille par un creux : la barre ne recule jamais
        t1 = time.monotonic()
        vitesse = 0.6 * vitesse + 0.4 * ((maintenant - dernier) / max(0.1, t1 - t0)) if maintenant >= dernier else vitesse
        dernier, t0 = maintenant, t1
        go = lambda o: str(round(o / 1e9, 1)).replace(".", ",")  # noqa: E731
        texte = _t("Téléchargement : {} / {} Go ({} %)").format(go(maintenant), go(total), min(100, round(100 * maintenant / total))) if total else _t("Téléchargement : {} Go reçus").format(go(maintenant))
        if vitesse > 0:
            texte += " · {} {}".format(round(vitesse / 1e6), _t("Mo/s"))
        progres(maintenant, total)
        dire(texte)


def download_model(depot, revision="", dossiers=None, dire=print, lancer=subprocess.Popen, annule=lambda: False, http=updates.http_get, progres=None, port=PORT_DEFAUT, contexte=0):
    """`main.py download <propriétaire/modèle> [--revision X]` : le téléchargeur de TabbyAPI (Hugging Face) dans le dossier des modèles. `progres(octets, total)` : l'avancement réel.
    Le téléchargeur lit le dossier des modèles dans config.yml : il est réécrit avec le port et la fenêtre de conversation du serveur (`port`, `contexte`), pas avec
    les valeurs par défaut, sinon le prochain démarrage ne réserverait plus ce que les réglages demandent."""
    depot, revision = str(depot or "").strip(), str(revision or "").strip()
    if not RE_REPO_MODEL.match(depot):
        raise ValueError(_t("Nom de dépôt invalide : écris « propriétaire/modèle » (Hugging Face)."))
    if revision and not RE_REVISION.match(revision):
        raise ValueError(_t("Révision invalide : {}").format(revision[:40]))
    if not installed(dossiers):
        raise ValueError(_t("ExLlamaV3 n'est pas installé : installe-le d'abord (Réglages > Moteur)."))
    tabby = folder_tabby(dossiers)
    (tabby / "config.yml").write_text(config_yaml(port, folder_models(dossiers), contexte), encoding="utf-8")
    avant = _folders_models(dossiers)
    # The folder is named here, not left to TabbyAPI: without « --folder-name » it writes to the name of the repository, and Lutin, watching
    # « name_revision » to show the progress, saw nothing until the end; two quantisations of one repository also refused each other.
    cmd = [str(python_venv(dossiers)), "main.py", "download", depot, "--folder-name", name_folder_model(depot, revision)] + (["--revision", revision] if revision else [])
    proc = lancer(cmd, cwd=str(tabby), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    arret, suivi = threading.Event(), None
    if progres is not None:
        try:
            from . import exllamav3_catalog
            total = int(exllamav3_catalog.revision_size(depot, revision or "main", http))
        except (ValueError, OSError):
            total = 0          # taille inconnue : on montre ce qui est reçu, sans pourcentage
        suivi = threading.Thread(target=_follow_size, args=(folder_models(dossiers) / name_folder_model(depot, revision), total, dire, progres, arret), daemon=True, name="exl3-progression")
        suivi.start()
    try:
        code, fin = _follow(proc, dire, annule)
    finally:
        arret.set()
    if code != 0 and not annule():
        raise ValueError(_t("Le téléchargement du modèle a échoué (code {}). Fin du message :\n{}").format(code, "\n".join(fin[-6:])))
    if code == 0:
        nouveaux = _folders_models(dossiers) - avant
        nom = name_folder_model(depot, revision)
        nom = nom if nom in nouveaux or not nouveaux else (sorted(nouveaux)[0] if len(nouveaux) == 1 else nom)
        if (folder_models(dossiers) / nom).is_dir():
            try:
                from . import exllamav3_catalog
                commit = exllamav3_catalog.commit_of(depot, revision or "main", http)
            except (ValueError, OSError):
                commit = ""
            note_model(dossiers, nom, depot, revision, commit)
    return True


def remove_model(nom, dossiers=None):
    """Supprime un modèle téléchargé (son dossier, et rien d'autre). Le nom est celui d'un sous-dossier direct du dossier des modèles."""
    nom = str(nom or "")
    if not nom or nom in (".", "..") or "/" in nom or "\\" in nom:
        raise ValueError(_t("Nom de modèle invalide."))
    racine = folder_models(dossiers)
    cible = racine / nom
    if not cible.is_dir() or cible.parent.resolve() != racine.resolve():
        raise ValueError(_t("Ce modèle n'est pas dans le dossier des modèles d'ExLlamaV3."))
    a_effacer = racine / (".suppression-" + nom + "-" + secrets.token_hex(3))
    os.replace(cible, a_effacer)          # PermissionError ici = un fichier est utilisé (serveur qui tourne) : RIEN n'a été touché, le modèle reste entier (effacer fichier par fichier le laissait sans config.json, donc « disparu » de la liste mais encore sur le disque)
    shutil.rmtree(a_effacer, ignore_errors=True)
    return True


def clean_removals(dossiers=None):
    """Efface ce que des suppressions interrompues ont laissé (dossiers « .suppression-… »)."""
    try:
        for p in folder_models(dossiers).iterdir():
            if p.is_dir() and p.name.startswith(".suppression-"):
                shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def modeles(dossiers=None):
    """Les modèles téléchargés : [{nom, taille_go, depot, revision, commit}] (un dossier avec un config.json ; depot/revision/commit vides pour un modèle posé à la main)."""
    sortie = []
    racine = folder_models(dossiers)
    clean_removals(dossiers)
    try:
        sous = sorted(p for p in racine.iterdir() if p.is_dir() and not p.name.startswith(".") and ((p / "config.json").is_file() or next(p.glob("*.safetensors"), None) is not None))
    except OSError:
        return []
    for p in sous:
        taille = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        sortie.append(dict({"nom": p.name, "taille_go": round(taille / 1e9, 1), "depot": "", "revision": "", "commit": "", "incomplet": not (p / "config.json").is_file()}, **origin_model(dossiers, p.name)))
    return sortie
