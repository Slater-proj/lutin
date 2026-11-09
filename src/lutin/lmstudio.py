"""LM Studio, piloté par Lutin sans son interface : l'installeur officiel de son démon « llmster », puis la commande `lms` (démon, serveur local, téléchargement et liste des modèles).

Ce que ce module fait, et seulement sur clic explicite de l'utilisateur :
  - télécharger l'installeur officiel (https://lmstudio.ai/install.sh ou install.ps1) et le lancer ; cet installeur vérifie lui-même la somme SHA-512 de ce qu'il télécharge ;
  - démarrer le démon et le serveur local sur 127.0.0.1 (`lms daemon up`, `lms server start`), les arrêter, le mettre à jour (`lms daemon update`) ;
  - télécharger un modèle (`lms get`) et lister ceux qui sont là (`lms ls --json`).
Ce qu'il ne fait PAS : désinstaller (les modèles sont dans le dossier de LM Studio), ni exposer le serveur sur le réseau (adresse 127.0.0.1 imposée).
Les commandes viennent de la documentation de LM Studio (lmstudio.ai/docs/cli) ; **elles n'ont pas été lancées par Lutin sur une vraie installation de LM Studio**."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .i18n import t as _t

URL_SH = "https://lmstudio.ai/install.sh"
URL_PS1 = "https://lmstudio.ai/install.ps1"
HOTE = "127.0.0.1"          # jamais une autre adresse : le serveur de LM Studio ne sort pas de cette machine
PORT_DEFAUT = 1234
TAILLE_SCRIPT_MAX = 400_000
RE_MODELE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/@:]{1,120}$")


def chemin_lms():
    """La commande `lms` (installée par llmster ou par l'application de bureau), ou None."""
    trouve = shutil.which("lms")
    if trouve:
        return trouve
    exe = Path.home() / ".lmstudio" / "bin" / ("lms.exe" if os.name == "nt" else "lms")
    return str(exe) if exe.is_file() else None


def repond(port):
    try:
        with urllib.request.urlopen("http://{}:{}/v1/models".format(HOTE, int(port)), timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _script(url, ouvrir=urllib.request.urlopen):
    req = urllib.request.Request(url, headers={"User-Agent": "Lutin"})
    with ouvrir(req, timeout=30) as r:
        if not str(r.geturl()).startswith("https://lmstudio.ai/"):
            raise ValueError(_t("L'installeur de LM Studio a été redirigé ailleurs : refusé."))
        corps = r.read(TAILLE_SCRIPT_MAX + 1)
    if len(corps) > TAILLE_SCRIPT_MAX or not corps.strip():
        raise ValueError(_t("L'installeur de LM Studio est vide ou trop gros : refusé."))
    return corps


def commande_installeur(chemin_script):
    if os.name == "nt":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(chemin_script)]
    return ["bash", str(chemin_script)]


def _suivre(proc, dire, annule=lambda: False):
    """Transmet chaque ligne écrite par la commande ; renvoie (code, dernières lignes). Une annulation arrête la commande."""
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


def installer(dire=print, ouvrir=urllib.request.urlopen, lancer=subprocess.Popen, annule=lambda: False):
    """Télécharge puis lance l'installeur officiel de llmster (le démon de LM Studio, sans interface). Renvoie le chemin de `lms`."""
    dire(_t("Téléchargement de l'installeur officiel de LM Studio…"))
    corps = _script(URL_PS1 if os.name == "nt" else URL_SH, ouvrir)
    with tempfile.TemporaryDirectory(prefix="lutin-lmstudio-") as tmp:
        script = Path(tmp) / ("install.ps1" if os.name == "nt" else "install.sh")
        script.write_bytes(corps)
        dire(_t("Installation de LM Studio (llmster)…"))
        proc = lancer(commande_installeur(script), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
        code, fin = _suivre(proc, dire, annule)
    if code != 0 and not annule():
        raise ValueError(_t("L'installeur de LM Studio s'est arrêté (code {}). Fin de son message :\n{}").format(code, "\n".join(fin[-6:])))
    lms = chemin_lms()
    if not lms:
        raise ValueError(_t("L'installation s'est terminée mais la commande « lms » est introuvable : ouvre un nouveau terminal ou relance Lutin pour que le PATH soit relu."))
    return lms


def _lms(args, delai=120, lancer=subprocess.run):
    lms = chemin_lms()
    if not lms:
        raise ValueError(_t("LM Studio n'est pas installé : installe-le d'abord (Réglages > Moteur)."))
    try:
        return lancer([lms, *args], capture_output=True, text=True, timeout=delai, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError(_t("La commande « lms » a échoué : {}").format(e)) from None


def demarrer(port=PORT_DEFAUT, attente_s=60, lancer=subprocess.run, repond_=repond, dormir=time.sleep):
    """`lms daemon up` puis `lms server start --port N` (127.0.0.1 par défaut), puis attend que /v1/models réponde."""
    if repond_(port):
        return port
    r = _lms(["daemon", "up"], 90, lancer)
    if r.returncode != 0:
        raise ValueError(_t("Le démon de LM Studio n'a pas démarré : {}").format(((r.stdout or "") + (r.stderr or ""))[-300:]))
    r = _lms(["server", "start", "--port", str(int(port))], 90, lancer)
    if r.returncode != 0:
        raise ValueError(_t("Le serveur de LM Studio n'a pas démarré : {}").format(((r.stdout or "") + (r.stderr or ""))[-300:]))
    fin = time.time() + attente_s
    while time.time() < fin:
        if repond_(port):
            return port
        dormir(1)
    raise ValueError(_t("LM Studio ne répond pas après {} s sur le port {}.").format(attente_s, port))


def arreter(lancer=subprocess.run):
    """`lms server stop` puis `lms daemon down` : le serveur s'arrête et la mémoire est rendue."""
    _lms(["server", "stop"], 60, lancer)
    r = _lms(["daemon", "down"], 60, lancer)
    return r.returncode == 0


def mettre_a_jour(lancer=subprocess.run):
    r = _lms(["daemon", "update"], 600, lancer)
    if r.returncode != 0:
        raise ValueError(_t("La mise à jour de LM Studio a échoué : {}").format(((r.stdout or "") + (r.stderr or ""))[-300:]))
    return True


def telecharger(nom, dire=print, lancer=subprocess.Popen, annule=lambda: False):
    """`lms get <modèle>` : télécharge un modèle dans le dossier de LM Studio. Seuls des noms simples sont acceptés (propriétaire/nom, avec @quantification éventuelle)."""
    nom = str(nom or "").strip()
    if not RE_MODELE.match(nom) or nom.startswith("-"):
        raise ValueError(_t("Nom de modèle invalide : {}").format(nom[:60]))
    lms = chemin_lms()
    if not lms:
        raise ValueError(_t("LM Studio n'est pas installé : installe-le d'abord (Réglages > Moteur)."))
    proc = lancer([lms, "get", nom], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    code, fin = _suivre(proc, dire, annule)
    if code != 0 and not annule():
        raise ValueError(_t("LM Studio n'a pas pu télécharger ce modèle (code {}). Fin de son message :\n{}").format(code, "\n".join(fin[-6:])))
    return True


def modeles(lancer=subprocess.run):
    """Les modèles déjà téléchargés : [{nom, taille_go}] d'après `lms ls --json` (liste vide si la sortie n'est pas lisible)."""
    r = _lms(["ls", "--json"], 60, lancer)
    try:
        donnees = json.loads(r.stdout or "[]")
    except ValueError:
        return []
    sortie = []
    for m in donnees if isinstance(donnees, list) else []:
        if isinstance(m, dict) and m.get("type", "llm") in ("llm", "vlm"):
            nom = str(m.get("modelKey") or m.get("path") or m.get("displayName") or "")
            if nom:
                sortie.append({"nom": nom[:120], "taille_go": round(float(m.get("sizeBytes") or 0) / 1e9, 1)})
    return sortie

