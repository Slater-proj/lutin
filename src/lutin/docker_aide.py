"""Le diagnostic Docker de `lutin doctor` : ce qui fait perdre des modèles ou des données (volumes absents), ce qui ralentit (mémoire donnée à Docker, carte invisible) et ce qui empêche de joindre un moteur.

Deux situations, aucune dépendance :
- DANS le conteneur Lutin (variable LUTIN_DOCKER) : les dossiers /data et /models sont-ils de vrais volumes (sinon tout disparaît quand le conteneur est recréé), sont-ils accessibles en écriture,
  quelle mémoire le conteneur a-t-il, les moteurs à côté (Ollama, llama.cpp) répondent-ils, la carte graphique est-elle visible.
- SUR L'HÔTE, si `docker` est installé : version, Compose v2, mémoire donnée à Docker (sous Windows, celle de WSL2 : souvent 50 % de la RAM par défaut), système.
Chaque ligne est (niveau, texte) : « ok », « info », « attention » ou « erreur ». Rien de personnel (pas de chemins de l'utilisateur, pas de noms)."""
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .i18n import t as _t

MEMOIRE_MINI_GO = 8.0


def en_conteneur(env=None):
    return (os.environ if env is None else env).get("LUTIN_DOCKER") == "1"


def points_de_montage(texte):
    """Les dossiers montés d'après le contenu de /proc/self/mountinfo (5e champ de chaque ligne)."""
    sortie = set()
    for ligne in texte.splitlines():
        champs = ligne.split()
        if len(champs) > 4:
            sortie.add(champs[4])
    return sortie


def memoire_conteneur(lire=lambda chemin: Path(chemin).read_text(errors="replace")):
    """(limite du conteneur en octets ou None si aucune, mémoire totale vue par le conteneur en octets ou None)."""
    limite = None
    for chemin in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            v = lire(chemin).strip()
            if v.isdigit() and int(v) < 1 << 60:
                limite = int(v)
            break
        except OSError:
            continue
    total = None
    try:
        for ligne in lire("/proc/meminfo").splitlines():
            if ligne.startswith("MemTotal:"):
                total = int(ligne.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return limite, total


def joint(url, ouvrir=urllib.request.urlopen, delai=3):
    """Vrai si ce moteur répond (n'importe quelle réponse HTTP : même une erreur d'accès prouve que quelqu'un écoute)."""
    try:
        with ouvrir(urllib.request.Request(url), timeout=delai):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def verifier_conteneur(env=None, montages=None, memoire=None, ouvrir=urllib.request.urlopen, ecriture=os.access, libre=lambda d: shutil.disk_usage(d).free):
    """Les lignes du diagnostic pour un Lutin qui tourne dans un conteneur."""
    env = os.environ if env is None else env
    if montages is None:
        try:
            montages = points_de_montage(Path("/proc/self/mountinfo").read_text(errors="replace"))
        except OSError:
            montages = None
    lignes = [("info", _t("Lutin tourne dans un conteneur Docker."))]
    for nom, dossier, role in (("/data", env.get("LUTIN_HOME") or "/data", _t("tes réglages et tes conversations")), ("/models", env.get("OLLAMA_MODELS") or "/models", _t("tes modèles"))):
        if not Path(dossier).exists():
            if nom == "/data":
                lignes.append(("erreur", _t("Le dossier {} n'existe pas.").format(dossier)))
            continue
        if not ecriture(dossier, os.W_OK):
            lignes.append(("erreur", _t("{} n'est pas accessible en écriture pour l'utilisateur du conteneur (1000) : sudo chown -R 1000:1000 sur le dossier de l'hôte.").format(dossier)))
        elif montages is not None and str(dossier) not in montages:
            lignes.append(("erreur", _t("{} n'est pas un volume : {} disparaîtront quand le conteneur sera recréé. Ajoute « - lutin-{}:{} » dans les volumes du docker-compose.").format(dossier, role, nom.strip("/"), dossier)))
        else:
            try:
                go = libre(dossier) / 1e9
            except OSError:
                go = None
            lignes.append(("ok" if go is None or go >= 5 else "attention", _t("{} : volume monté, {} Go libres.").format(dossier, "{:.0f}".format(go) if go is not None else "?")))
    limite, total = memoire if memoire is not None else memoire_conteneur()
    if limite:
        lignes.append(("attention" if limite / 1e9 < MEMOIRE_MINI_GO else "info", _t("Mémoire limitée pour ce conteneur : {:.1f} Go.").format(limite / 1e9)))
    elif total:
        lignes.append(("attention" if total / 1e9 < MEMOIRE_MINI_GO else "info", _t("Mémoire vue par le conteneur : {:.1f} Go (sous Windows : celle de WSL2, voir .wslconfig).").format(total / 1e9)))
    for nom, variable, defaut in (("Ollama", "OLLAMA_URL", ""), ("llama.cpp", "LUTIN_LLAMACPP_URL", "")):
        url = (env.get(variable) or defaut).strip()
        if url:
            sonde = url.rstrip("/") + ("/api/version" if variable == "OLLAMA_URL" else "/models")
            lignes.append(("ok", _t("{} répond à {}.").format(nom, url)) if joint(sonde, ouvrir) else ("erreur", _t("{} ne répond pas à {} : le conteneur du moteur est-il démarré (profil Compose) et sur le même réseau ?").format(nom, url)))
    return lignes


def verifier_hote(lanceur=subprocess.run, qui=shutil.which, systeme=None):
    """Les lignes du diagnostic pour la machine qui héberge (ou hébergerait) Docker. Vide si Docker n'est pas installé : ce n'est pas un problème."""
    exe = qui("docker")
    if not exe:
        return []

    def lancer(*args):
        try:
            r = lanceur([exe, *args], capture_output=True, timeout=8)
            return r.returncode, r.stdout.decode("utf-8", "replace").strip()
        except (OSError, subprocess.SubprocessError):
            return 1, ""
    lignes = []
    code, version = lancer("version", "--format", "{{.Server.Version}}")
    if code != 0 or not version:
        return [("attention", _t("Docker est installé mais ne répond pas (le démon est-il lancé ? Docker Desktop est-il ouvert ?)."))]
    lignes.append(("ok", _t("Docker {} répond.").format(version)))
    code, compose = lancer("compose", "version", "--short")
    lignes.append(("ok", "Docker Compose {} (v2).".format(compose)) if code == 0 and compose else ("attention", _t("Docker Compose v2 est absent : la commande est « docker compose » (avec un espace).")))
    code, infos = lancer("info", "--format", "{{.MemTotal}}|{{.OperatingSystem}}")
    if code == 0 and "|" in infos:
        memoire, _, os_nom = infos.partition("|")
        if memoire.isdigit():
            go = int(memoire) / 1e9
            conseil = _t(" Sous Windows, augmente-la dans le fichier .wslconfig (memory=…).") if "desktop" in os_nom.lower() or "wsl" in os_nom.lower() else ""
            lignes.append(("attention" if go < MEMOIRE_MINI_GO else "info", _t("Mémoire donnée à Docker : {:.1f} Go.").format(go) + (_t(" Trop peu pour un modèle de taille moyenne.") + conseil if go < MEMOIRE_MINI_GO else "")))
    return lignes


def diagnostiquer(env=None):
    """Les lignes à ajouter à `lutin doctor`."""
    lignes = verifier_conteneur(env) if en_conteneur(env) else []
    if not en_conteneur(env):
        lignes += verifier_hote()
    return lignes
