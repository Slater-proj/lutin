"""Les programmes dont Lutin se sert et que beaucoup de machines n'ont pas : **uv** (Python isolé, serveurs MCP en Python, environnement d'ExLlamaV3) et **Node.js** (serveurs MCP en JavaScript).

Un clic pour les installer, un clic pour les retirer, sans rien toucher à ton système : ils vivent dans le dossier de données de Lutin (outils/uv, outils/node), jamais dans le PATH. Si le programme
est déjà installé sur la machine, Lutin s'en sert tel quel et ne propose pas de le doubler.

Règles de solidité :
- les versions sont épinglées (celles qui ont été essayées), pas « la dernière » ;
- chaque archive est vérifiée par sa somme SHA-256 publiée par l'éditeur avant d'être décompressée ; sans somme, rien n'est installé ;
- la décompression refuse tout fichier qui sortirait du dossier, et tout lien qui pointerait hors de lui ;
- l'ancienne version n'est remplacée qu'une fois la nouvelle entière et vérifiée ;
- retirer ne supprime que ce que Lutin a installé lui-même."""
import hashlib
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

from . import config, updates
from .i18n import t as _t
from .engine_replace import remplacer_dossier

VERSION_UV = "0.13.7"
VERSION_NODE = "24.22.2"
DEPOT_UV = "astral-sh/uv"
OUTILS = {
    "uv": {"libelle": "uv", "aide": "Python isolé : serveurs MCP en Python (Pages web, Git, Heure, SQLite) et environnement d'ExLlamaV3. https://docs.astral.sh/uv"},
    "node": {"libelle": "Node.js", "aide": "Serveurs MCP en JavaScript (Fichiers, Mémoire en graphe, Raisonnement). https://nodejs.org"},
}
RE_SOMME = re.compile(r"^[0-9a-f]{64}$")


def dossier(nom=None, dossiers=None):
    base = Path((dossiers or config.dossiers())["donnees"]) / "outils"
    return base / nom if nom else base


def _plateforme(systeme=None, architecture=None):
    """('windows'|'linux'|'macos', 'x64'|'arm64') ou ValueError."""
    s = (systeme or sys.platform).lower()
    a = (architecture or platform.machine()).lower()
    systeme = "windows" if s.startswith("win") else "linux" if s.startswith("linux") else "macos" if s in ("darwin", "macos") else ""
    arch = "x64" if a in ("amd64", "x86_64", "x64") else "arm64" if a in ("arm64", "aarch64") else ""
    if not systeme or not arch:
        raise ValueError(_t("Ce système n'est pas pris en charge ({} {}).").format(s, a))
    return systeme, arch


def archive_uv(systeme=None, architecture=None):
    s, a = _plateforme(systeme, architecture)
    cible = {"windows": "{}-pc-windows-msvc.zip", "linux": "{}-unknown-linux-gnu.tar.gz", "macos": "{}-apple-darwin.tar.gz"}[s]
    return "uv-" + cible.format("x86_64" if a == "x64" else "aarch64")


def archive_node(systeme=None, architecture=None):
    s, a = _plateforme(systeme, architecture)
    fin = {"windows": "win-{}.zip", "linux": "linux-{}.tar.xz", "macos": "darwin-{}.tar.gz"}[s].format(a)
    return "node-v{}-{}".format(VERSION_NODE, fin)


def _trouver(racine, noms):
    """Le premier fichier de ce nom sous `racine` (les archives ont un sous-dossier ou non selon le programme)."""
    racine = Path(racine)
    if not racine.is_dir():
        return ""
    for nom in noms:
        for f in sorted(racine.rglob(nom), key=lambda p: len(p.parts)):
            if f.is_file() and "node_modules" not in f.parts:
                return str(f)
    return ""


def chemin(nom, dossiers=None, chercher=shutil.which):
    """Le programme à lancer : celui que Lutin a installé d'abord, sinon celui de la machine ; '' s'il n'y en a pas. nom : uv, node, npx."""
    propre = {"uv": ("uv.exe", "uv"), "node": ("node.exe", "node"), "npx": ("npx.cmd", "npx")}.get(nom, ())
    base = dossier("uv" if nom == "uv" else "node", dossiers)
    trouve = _trouver(base / "bin", propre) or _trouver(base, propre) if propre else ""
    return trouve or chercher(nom) or ""


def dossiers_a_ajouter_au_path(nom, dossiers=None):
    """Les dossiers à mettre devant le PATH d'un programme lancé par Lutin : celui de Node.js installé par Lutin (npx cherche `node` dans son PATH sous Linux)."""
    if nom != "node":
        return []
    exe = _trouver(dossier("node", dossiers), ("node.exe", "node"))
    return [str(Path(exe).parent)] if exe else []


def par_lutin(nom, dossiers=None):
    return bool(_trouver(dossier(nom, dossiers), ("uv.exe", "uv") if nom == "uv" else ("node.exe", "node")))


def version(nom, dossiers=None, lancer=subprocess.run, chercher=shutil.which):
    exe = chemin(nom, dossiers, chercher)
    if not exe:
        return ""
    try:
        sortie = (lancer([exe, "--version"], capture_output=True, text=True, timeout=15).stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"(\d+\.\d+\.\d+)", sortie)
    return m.group(1) if m else ""


def etat(dossiers=None, lancer=subprocess.run, chercher=shutil.which):
    """Pour chaque programme : {nom, libelle, aide, installe, par_lutin, version}."""
    sortie = []
    for nom, d in OUTILS.items():
        exe = chemin(nom, dossiers, chercher)
        sortie.append({"nom": nom, "libelle": d["libelle"], "aide": _t(d["aide"]), "installe": bool(exe), "par_lutin": par_lutin(nom, dossiers),
                       "version": version(nom, dossiers, lancer, chercher) if exe else ""})
    return sortie


def somme_de(fichier):
    h = hashlib.sha256()
    with open(fichier, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def extraire_sur(archive, cible):
    """Décompresse sans jamais écrire hors de `cible` ; les liens (nécessaires à Node.js sous Linux : npx) ne sont acceptés que s'ils restent dans `cible`."""
    cible = Path(cible).resolve()
    cible.mkdir(parents=True, exist_ok=True)

    def dedans(chemin_):
        r = Path(chemin_).resolve()
        return r == cible or cible in r.parents
    archive = str(archive)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for i in z.infolist():
                if not dedans(cible / i.filename):
                    raise ValueError(_t("Archive refusée : un fichier sortirait du dossier d'installation ({}).").format(i.filename[:80]))
            z.extractall(cible)
        return
    with tarfile.open(archive) as tf:
        for m in tf.getmembers():
            if not dedans(cible / m.name):
                raise ValueError(_t("Archive refusée : un fichier sortirait du dossier d'installation ({}).").format(m.name[:80]))
            if m.islnk() or m.isdev():
                raise ValueError(_t("Archive refusée : lien ou fichier spécial ({}).").format(m.name[:80]))
            if m.issym() and not dedans((cible / m.name).parent / m.linkname):
                raise ValueError(_t("Archive refusée : lien ou fichier spécial ({}).").format(m.name[:80]))
        tf.extractall(cible)          # noqa: S202  (chaque nom et chaque lien a été vérifié au-dessus)


def _somme_publiee(nom, archive, http):
    """La somme SHA-256 publiée par l'éditeur pour cette archive, ou ValueError (sans somme, on n'installe pas)."""
    if nom == "uv":
        url = "https://github.com/{}/releases/download/{}/{}.sha256".format(DEPOT_UV, VERSION_UV, archive)
        statut, _, corps = http(url, {})
        texte = corps.decode("utf-8", "replace") if statut == 200 else ""
        m = re.match(r"\s*([0-9a-f]{64})\b", texte)
    else:
        url = "https://nodejs.org/dist/v{}/SHASUMS256.txt".format(VERSION_NODE)
        statut, _, corps = http(url, {})
        m = None
        for ligne in (corps.decode("utf-8", "replace") if statut == 200 else "").splitlines():
            morceaux = ligne.split()
            if len(morceaux) == 2 and morceaux[1] == archive and RE_SOMME.match(morceaux[0]):
                m = re.match(r"([0-9a-f]{64})", morceaux[0])
    if not m:
        raise ValueError(_t("La somme de contrôle de {} n'a pas pu être lue (HTTP {}) : rien n'est installé.").format(archive, statut))
    return m.group(1)


def installer(nom, dossiers=None, dire=print, http=updates.http_get, telecharger=None, systeme=None, architecture=None):
    """Télécharge, vérifie et installe uv ou Node.js dans le dossier de Lutin. Rend le chemin du programme. ValueError claire à chaque étape qui échoue."""
    if nom not in OUTILS:
        raise ValueError(_t("Programme inconnu."))
    from . import offline, ollama_client
    if offline.actif():
        raise ValueError(_t("Mode hors ligne : aucun téléchargement."))
    telecharger = telecharger or ollama_client.telecharger_fichier
    archive = archive_uv(systeme, architecture) if nom == "uv" else archive_node(systeme, architecture)
    url = ("https://github.com/{}/releases/download/{}/{}".format(DEPOT_UV, VERSION_UV, archive) if nom == "uv" else "https://nodejs.org/dist/v{}/{}".format(VERSION_NODE, archive))
    dire(_t("Recherche de la somme de contrôle de {}…").format(OUTILS[nom]["libelle"]))
    attendue = _somme_publiee(nom, archive, http)
    base = dossier(dossiers=dossiers)
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lutin-outil-") as tmp:
        fichier = Path(tmp) / archive
        dire(_t("Téléchargement de {}…").format(archive))
        try:
            telecharger(url, fichier, lambda t, fait, total: None, taille_min=1_000_000)
        except (OSError, RuntimeError) as e:
            raise ValueError(_t("Téléchargement impossible : {}").format(e)) from e
        if somme_de(fichier) != attendue:
            raise ValueError(_t("Le fichier téléchargé est corrompu (somme de contrôle différente de celle publiée) : rien n'est installé, réessaie."))
        partiel = base / (nom + ".partiel")
        shutil.rmtree(partiel, ignore_errors=True)
        try:
            dire(_t("Installation…"))
            extraire_sur(fichier, partiel)
        except Exception:
            shutil.rmtree(partiel, ignore_errors=True)
            raise
        if not _trouver(partiel, ("uv.exe", "uv") if nom == "uv" else ("node.exe", "node")):
            shutil.rmtree(partiel, ignore_errors=True)
            raise ValueError(_t("Le programme est introuvable dans l'archive téléchargée."))
        remplacer_dossier(partiel, base / nom)
    shutil.rmtree(base / (nom + ".partiel"), ignore_errors=True)
    exe = chemin("uv" if nom == "uv" else "node", dossiers)
    if not exe:
        raise ValueError(_t("Le programme est introuvable dans l'archive téléchargée."))
    if sys.platform != "win32":
        for f in Path(base / nom).rglob("*"):          # les archives .tar gardent les droits ; un .zip non
            if f.is_file() and f.name in ("uv", "uvx", "node", "npx"):
                f.chmod(f.stat().st_mode | 0o755)
    return exe


def desinstaller(nom, dossiers=None):
    """Retire ce que Lutin a installé (jamais un programme de la machine)."""
    if nom not in OUTILS:
        raise ValueError(_t("Programme inconnu."))
    if not par_lutin(nom, dossiers):
        raise ValueError(_t("Lutin ne l'a pas installé : il n'y a rien à retirer ici."))
    shutil.rmtree(dossier(nom, dossiers), ignore_errors=True)


def creer_venv(venv, dossiers=None, dire=print, executer=subprocess.run, installer_uv=None):
    """Un environnement Python isolé (avec pip) dans `venv`. Le module « venv » du Python de Lutin d'abord ; s'il manque (le Python fourni avec l'installateur Windows ne l'a pas), uv, installé au besoin,
    crée l'environnement avec son propre Python. ValueError avec la raison si rien ne marche."""
    venv = Path(venv)
    r = executer([sys.executable, "-m", "venv", str(venv)], capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        return
    shutil.rmtree(venv, ignore_errors=True)
    dire(_t("Le module venv manque à ce Python : uv crée l'environnement à sa place…"))
    uv = chemin("uv", dossiers)
    if not uv:
        dire(_t("Installation de uv…"))
        uv = (installer_uv or installer)("uv", dossiers, dire)
    r = executer([uv, "venv", "--seed", "--python", "3.12", str(venv)], capture_output=True, text=True, timeout=900, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        shutil.rmtree(venv, ignore_errors=True)
        raise ValueError(_t("Impossible de créer l'environnement Python : {}").format(((r.stdout or "") + (r.stderr or ""))[-300:]))
