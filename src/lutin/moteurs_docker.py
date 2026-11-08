"""Les moteurs dans Docker : l'image de Lutin est légère (Lutin seul), les moteurs s'installent depuis la page et vivent dans un volume.

Avant, l'image contenait Ollama (plus d'1,5 Go) : chaque mise à jour de l'image le re-téléchargeait, et llama.cpp ou un serveur compatible OpenAI ne pouvaient rien installer. Maintenant :
  - Lutin installe le moteur choisi (Ollama, llama.cpp) dans le dossier des moteurs, comme il le fait hors Docker ;
  - ce dossier est `/engines` quand le compose le monte (volume ou dossier de l'hôte), sinon `moteurs/` dans le volume des données `/data` : dans les deux cas, une mise à jour de l'image ne l'efface pas ;
  - les modèles restent dans `/models`.
Ce module ne contient que ce qui est propre à Docker pour Ollama (llama.cpp se gère dans moteur_llamacpp.py, avec le même dossier). Aucune dépendance."""
import hashlib
import os
import platform
import shutil
import signal
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import moteurs
from .i18n import t as _t

API_OLLAMA = "https://api.github.com/repos/ollama/ollama/releases/latest"
MONTAGE = "/engines"
PROCESSUS = {"proc": None}


def en_docker(env=None):
    return (os.environ if env is None else env).get("LUTIN_DOCKER") == "1"


def est_monte(dossier, mountinfo="/proc/self/mountinfo"):
    """Le dossier est-il un point de montage (volume ou dossier de l'hôte) ? Sinon il disparaîtrait avec le conteneur."""
    try:
        for ligne in Path(mountinfo).read_text(errors="replace").splitlines():
            champs = ligne.split()
            if len(champs) > 4 and champs[4] == str(dossier):
                return True
    except OSError:
        pass
    return False


def dossier_moteurs(env=None, monte=est_monte):
    """Où les moteurs s'installent dans Docker : `LUTIN_MOTEURS` si donné, sinon `/engines` s'il est monté, sinon `moteurs/` dans les données. None hors Docker."""
    env = os.environ if env is None else env
    if not en_docker(env):
        return None
    choisi = (env.get("LUTIN_MOTEURS") or "").strip()
    if choisi:
        return Path(choisi)
    if monte(MONTAGE) and os.access(MONTAGE, os.W_OK):
        return Path(MONTAGE)
    donnees = moteurs.CONTEXTE["donnees"]() or env.get("LUTIN_HOME")
    return Path(donnees) / "moteurs" if donnees else None


def ollama_dossier():
    d = dossier_moteurs()
    return d / "ollama" if d else None


def ollama_installe_par_lutin():
    """Le programme `ollama` installé par Lutin dans le dossier des moteurs, ou ''."""
    d = ollama_dossier()
    exe = d / "bin" / "ollama" if d else None
    return str(exe) if exe and exe.is_file() else ""


def chemin_ollama():
    """Le programme `ollama` à lancer dans Docker : celui du dossier des moteurs, sinon un `ollama` du PATH (ancienne image complète)."""
    return ollama_installe_par_lutin() or (shutil.which("ollama") or "")


def ollama_externe(env=None):
    """OLLAMA_URL désigne-t-il un autre conteneur (profil Compose « ollama ») ? Alors Lutin n'installe ni ne lance rien."""
    adresse = ((os.environ if env is None else env).get("OLLAMA_URL") or "").strip()
    return bool(adresse) and not moteurs.est_local(adresse)


# --------------------------------------------------------------------------- installation d'Ollama

def _http_json(url, delai=20):
    from .moteur_llamacpp import _http_json as lire          # même patience que pour llama.cpp : trois essais si GitHub a une panne passagère
    return lire(url, delai)


def fichiers_ollama(release, arch, rocm=False):
    """Les fichiers de cette version pour Linux : le programme (+ la bibliothèque ROCm pour les cartes AMD). [] si rien ne correspond."""
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(arch.lower())
    if not arch:
        return []
    voulus = ["ollama-linux-{}.tar.zst".format(arch)] + (["ollama-linux-{}-rocm.tar.zst".format(arch)] if rocm and arch == "amd64" else [])
    par_nom = {a.get("name"): a for a in release.get("assets", [])}
    return [par_nom[n] for n in voulus if n in par_nom] if all(n in par_nom for n in voulus) else []


def _verifier_empreinte(fichier, asset):
    attendu = str(asset.get("digest") or "")
    if not attendu.startswith("sha256:"):
        return
    h = hashlib.sha256()
    with open(fichier, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    if h.hexdigest() != attendu[7:]:
        Path(fichier).unlink(missing_ok=True)
        raise ValueError(_t("Le fichier téléchargé est corrompu (empreinte différente de celle publiée) : réessaie."))


class _Zstd:
    """Lit un fichier .tar.zst avec le programme `zstd` (absent de Python avant la 3.14) : un flux, rien n'est décompressé sur le disque."""

    def __init__(self, chemin):
        exe = shutil.which("zstd")
        if not exe:
            raise ValueError(_t("Le programme « zstd » manque dans l'image : mets l'image de Lutin à jour."))
        self.p = subprocess.Popen([exe, "-dc", str(chemin)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.stdout = self.p.stdout

    def read(self, n=-1):
        return self.p.stdout.read(n)

    def close(self):
        self.p.stdout.close()
        self.p.wait(30)


def extraire_tar(flux, destination):
    """Extrait un flux tar en refusant tout ce qui sortirait du dossier (chemins absolus ou avec « .. », liens vers l'extérieur, fichiers spéciaux)."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    racine = destination.resolve()
    with tarfile.open(fileobj=flux, mode="r|") as archive:
        for m in archive:
            cible = (racine / m.name).resolve()
            if racine not in cible.parents and cible != racine:
                raise ValueError(_t("Archive refusée : un fichier sortirait du dossier d'installation."))
            if m.issym() or m.islnk():
                lien = (cible.parent / m.linkname).resolve() if m.issym() else (racine / m.linkname).resolve()
                if racine not in lien.parents and lien != racine:
                    raise ValueError(_t("Archive refusée : un lien sortirait du dossier d'installation."))
            elif not (m.isfile() or m.isdir()):
                continue
            archive.extract(m, str(racine), set_attrs=False) if not hasattr(tarfile, "data_filter") else archive.extract(m, str(racine), set_attrs=False, filter="data")
            if m.isfile() and (m.mode & 0o111):
                try:
                    cible.chmod(cible.stat().st_mode | 0o755)
                except OSError:
                    pass


def installer_ollama(progression, rocm=False, http_json=None, telecharger=None, ouvrir_archive=None):
    """Télécharge la dernière version d'Ollama (vérifiée par son empreinte) et l'installe dans `<moteurs>/ollama/`. Les modèles ne sont pas touchés (ils sont dans /models)."""
    base = ollama_dossier()
    if base is None:
        raise ValueError(_t("Aucun dossier pour les moteurs."))
    from . import ollama_client
    progression(_t("Recherche de la dernière version…"), 0, 0)
    try:
        release = (http_json or _http_json)(API_OLLAMA)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ValueError(_t("GitHub ne répond pas : {}").format(e))
    fichiers = fichiers_ollama(release, platform.machine(), rocm)
    if not fichiers:
        raise ValueError(_t("Aucun programme Ollama publié pour cette machine ({}).").format(platform.machine()))
    cache, neuf = base / "telechargement", base / "neuf"
    for d in (neuf,):
        shutil.rmtree(d, ignore_errors=True)
    total = sum(int(a.get("size") or 0) for a in fichiers)
    deja = 0
    for a in fichiers:
        nom = a["name"]
        try:
            f = (telecharger or ollama_client.telecharger_fichier)(a["browser_download_url"], cache / nom, lambda t, fait, tot, d=deja, n=nom: progression(_t("Téléchargement de {}").format(n), d + fait, total), taille_min=100_000)
        except (RuntimeError, OSError) as e:
            raise ValueError(str(e))
        _verifier_empreinte(f, a)
        deja += int(a.get("size") or 0)
        progression(_t("Installation…"), deja, total)
        flux = (ouvrir_archive or _Zstd)(f)
        try:
            extraire_tar(flux, neuf)
        finally:
            if hasattr(flux, "close"):
                flux.close()
        Path(f).unlink(missing_ok=True)          # l'archive n'est plus utile : le disque est précieux
    exe = neuf / "bin" / "ollama"
    if not exe.is_file():
        shutil.rmtree(neuf, ignore_errors=True)
        raise ValueError(_t("Le programme « ollama » est introuvable dans l'archive téléchargée."))
    arreter_ollama()
    for sous in ("bin", "lib"):
        shutil.rmtree(base / sous, ignore_errors=True)
        if (neuf / sous).exists():
            (neuf / sous).replace(base / sous)
    shutil.rmtree(neuf, ignore_errors=True)
    shutil.rmtree(cache, ignore_errors=True)
    (base / "version.txt").write_text(str(release.get("tag_name") or ""), encoding="utf-8")
    progression(_t("Installé : {}.").format(release.get("tag_name") or "Ollama"), 1, 1)


def desinstaller_ollama():
    base = ollama_dossier()
    if base is None or not ollama_installe_par_lutin():
        raise ValueError(_t("Ollama n'a pas été installé par Lutin : il n'y a rien à supprimer ici."))
    arreter_ollama()
    for sous in ("bin", "lib"):
        shutil.rmtree(base / sous, ignore_errors=True)
    (base / "version.txt").unlink(missing_ok=True)


# --------------------------------------------------------------------------- démarrage et arrêt

def variables_ollama(env=None):
    env = os.environ if env is None else env
    return {"OLLAMA_HOST": env.get("OLLAMA_HOST") or "127.0.0.1:11434", "OLLAMA_MODELS": env.get("OLLAMA_MODELS") or "/models", "OLLAMA_KEEP_ALIVE": env.get("OLLAMA_KEEP_ALIVE") or "5m"}


def demarrer_ollama(attendre=lambda: False, delai=30, lanceur=subprocess.Popen):
    """Lance `ollama serve` (journal : <données>/ollama.log) et attend qu'il réponde. `attendre()` rend vrai quand il répond."""
    exe = chemin_ollama()
    if not exe:
        raise ValueError(_t("Ollama n'est pas installé."))
    if attendre():
        return
    donnees = moteurs.CONTEXTE["donnees"]() or os.environ.get("LUTIN_HOME") or "/data"
    journal = open(Path(donnees) / "ollama.log", "ab")
    env = dict(os.environ, **variables_ollama())
    PROCESSUS["proc"] = lanceur([exe, "serve"], env=env, stdout=journal, stderr=journal, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(int(delai * 2)):
        time.sleep(0.5)
        if attendre():
            return
    raise ValueError(_t("Ollama ne répond pas après son démarrage : regarde le journal ollama.log dans le dossier des données."))


def _pids_ollama():
    """Les processus nommés « ollama » (lecture de /proc : `pkill` n'existe pas dans l'image légère)."""
    sortie = []
    try:
        for p in Path("/proc").iterdir():
            if p.name.isdigit() and (p / "comm").read_text(errors="replace").strip() == "ollama":
                sortie.append(int(p.name))
    except OSError:
        pass
    return sortie


def arreter_ollama():
    p = PROCESSUS.get("proc")
    PROCESSUS["proc"] = None
    if p is not None and p.poll() is None:
        try:
            p.terminate()
            p.wait(10)
        except (OSError, subprocess.TimeoutExpired):
            pass
    for pid in _pids_ollama():
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    time.sleep(0.5)


# --------------------------------------------------------------------------- ce que la page peut faire avec Ollama dans Docker

def actions_ollama(installe, actif, hors_ligne):
    pas, deja = _t("Pas installé."), _t("Déjà installé.")
    if ollama_externe():
        raison = _t("Cet Ollama est un autre conteneur (OLLAMA_URL) : il se gère avec docker compose.")
        return {a: {"possible": False, "raison": raison} for a in moteurs.ACTIONS}
    par_lutin = bool(ollama_installe_par_lutin())
    hl = _t("Mode hors ligne : aucun téléchargement.")
    emplacement = ollama_dossier()
    return {"installer": {"possible": not installe and not hors_ligne, "raison": deja if installe else (hl if hors_ligne else _t("Télécharge Ollama (environ 1,5 Go) dans {} : il reste là quand l'image de Lutin est mise à jour.").format(emplacement))},
            "mettre_a_jour": {"possible": par_lutin and not hors_ligne, "raison": (hl if hors_ligne else _t("Télécharge la dernière version ; tes modèles sont gardés.")) if par_lutin else (_t("Ollama fait partie de l'image : mets l'image à jour.") if installe else pas)},
            "desinstaller": {"possible": par_lutin, "raison": _t("Supprime le programme (tes modèles restent dans /models).") if par_lutin else (_t("Ollama fait partie de l'image : il ne se supprime pas ici.") if installe else pas)},
            "reinstaller": {"possible": par_lutin and not hors_ligne, "raison": (hl if hors_ligne else _t("Télécharge de nouveau la dernière version, en gardant tes modèles.")) if par_lutin else (_t("Ollama fait partie de l'image : mets l'image à jour.") if installe else pas)},
            "demarrer": {"possible": installe and not actif, "raison": _t("Démarre Ollama.") if installe else pas},
            "arreter": {"possible": actif, "raison": _t("Arrête Ollama et libère la mémoire.") if actif else _t("Il n'est pas démarré.")}}


def faire_ollama(action, progression, attendre, rocm=False):
    """Fait une action d'Ollama dans Docker (appelée par MoteurOllama.faire, une fois l'action reconnue possible)."""
    if action == "demarrer":
        progression(_t("Démarrage d'Ollama…"), 0, 0)
        return demarrer_ollama(attendre)
    if action == "arreter":
        return arreter_ollama()
    if action == "desinstaller":
        progression(_t("Désinstallation…"), 0, 0)
        return desinstaller_ollama()
    installer_ollama(progression, rocm=rocm)
    progression(_t("Démarrage d'Ollama…"), 0, 0)
    demarrer_ollama(attendre)
