"""Ce qui est chargé en mémoire en ce moment, et de quoi le décharger : les modèles d'Ollama, le serveur llama.cpp, ComfyUI, et les programmes qui prennent le plus de mémoire.

La page Santé montre « RAM utilisée / mémoire vidéo utilisée » ; ce module dit CE QUI les occupe et propose, pour chaque chose que Lutin sait décharger, un bouton. Rien n'est jamais déchargé sans clic.
- Ollama : chaque modèle chargé (taille, part sur la carte graphique, heure d'expiration) ; décharger = `keep_alive: 0`.
- llama.cpp géré par Lutin : le serveur et le modèle (ou le routeur) ; décharger = arrêter le serveur (il redémarre à la demande).
- ComfyUI : la mémoire vidéo que son cache garde ; décharger = POST /free (modèles et cache libérés).
- Programmes les plus gourmands : à titre d'information (Lutin ne ferme pas les programmes des autres).
Aucune dépendance : mesures par ctypes (Windows), /proc (Linux) ou ps (macOS)."""
import ctypes
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import moteurs
from .i18n import t as _t

RE_MODELE = re.compile(r"^[A-Za-z0-9_./:@+-]{1,200}$")
CONNUS = {"ollama": "Ollama", "ollama app": "Ollama", "ollama_llama_server": "Ollama (modèle)", "llama-server": "llama.cpp", "llama-swap": "llama-swap", "vllm": "vLLM", "lm studio": "LM Studio",
          "lmstudio": "LM Studio", "python": "Python (ComfyUI, scripts…)", "pythonw": "Python (ComfyUI, scripts…)", "python3": "Python (ComfyUI, scripts…)", "comfyui": "ComfyUI"}
MEMO = {"t": 0.0, "v": []}
GO = 1024 ** 3


def _json(url, corps=None, delai=3):
    req = urllib.request.Request(url, data=None if corps is None else json.dumps(corps).encode("utf-8"), headers={"Content-Type": "application/json"}, method="GET" if corps is None else "POST")
    with urllib.request.urlopen(req, timeout=delai) as r:
        texte = r.read().decode("utf-8", "replace")
    return json.loads(texte) if texte.strip() else {}


def adresse_ollama():
    from . import moteur as _m
    return _m.OLLAMA


def adresse_comfy():
    return os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")


# --------------------------------------------------------------------------- mémoire d'un programme, liste des programmes

def memoire_processus(pid):
    """Octets de mémoire vive occupés par ce processus (ensemble de travail), ou None."""
    try:
        if os.name == "nt":
            class Compteurs(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            noyau = ctypes.windll.kernel32
            noyau.OpenProcess.restype = ctypes.c_void_p
            h = noyau.OpenProcess(0x1000 | 0x0010, False, int(pid))
            if not h:
                return None
            try:
                c = Compteurs()
                c.cb = ctypes.sizeof(c)
                ok = ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(h), ctypes.byref(c), c.cb)
                return int(c.WorkingSetSize) if ok else None
            finally:
                noyau.CloseHandle(ctypes.c_void_p(h))
        for ligne in Path("/proc/{}/status".format(int(pid))).read_text(errors="replace").splitlines():
            if ligne.startswith("VmRSS:"):
                return int(ligne.split()[1]) * 1024
    except (OSError, ValueError, AttributeError):
        pass
    return None


def analyser_tasklist(texte):
    """Sortie de `tasklist /FO CSV /NH` -> [(nom sans .exe, octets)]. Le dernier champ est la mémoire (« 123 456 Ko » ou « 123,456 K » selon la langue) : seuls ses chiffres comptent."""
    sortie = []
    for ligne in texte.splitlines():
        champs = [c.strip('"') for c in re.findall(r'"([^"]*)"', ligne)]
        if len(champs) < 5:
            continue
        chiffres = re.sub(r"\D", "", champs[-1])
        if chiffres:
            sortie.append((re.sub(r"\.exe$", "", champs[0], flags=re.I), int(chiffres) * 1024))
    return sortie


def analyser_ps(texte):
    """Sortie de `ps -axo rss=,comm=` -> [(nom, octets)] (RSS en Ko)."""
    sortie = []
    for ligne in texte.splitlines():
        m = re.match(r"^\s*(\d+)\s+(.+?)\s*$", ligne)
        if m:
            sortie.append((Path(m.group(2)).name, int(m.group(1)) * 1024))
    return sortie


def lire_proc(racine="/proc"):
    """[(nom, octets)] de tous les processus lisibles de /proc (Linux)."""
    sortie = []
    try:
        dossiers = [d for d in Path(racine).iterdir() if d.name.isdigit()]
    except OSError:
        return sortie
    for d in dossiers:
        try:
            nom, rss = "", 0
            for ligne in (d / "status").read_text(errors="replace").splitlines():
                if ligne.startswith("Name:"):
                    nom = ligne.split(None, 1)[1].strip()
                elif ligne.startswith("VmRSS:"):
                    rss = int(ligne.split()[1]) * 1024
            if nom and rss:
                sortie.append((nom, rss))
        except (OSError, ValueError, IndexError):
            continue
    return sortie


def lister_processus(lanceur=subprocess.run):
    """[(nom, octets)] des processus de la machine (un par processus ; regroupés ensuite). [] si on ne sait pas."""
    try:
        if os.name == "nt":
            r = lanceur(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, timeout=10)
            return analyser_tasklist(r.stdout.decode("oem", "replace"))          # la console Windows écrit dans sa page de code
        if sys.platform == "darwin":
            r = lanceur(["ps", "-axo", "rss=,comm="], capture_output=True, timeout=10)
            return analyser_ps(r.stdout.decode("utf-8", "replace"))
        return lire_proc()
    except (OSError, subprocess.SubprocessError):
        return []


def regrouper(processus, nombre=8):
    """Les programmes les plus gourmands : [{nom, libelle, nombre, octets, ia}] (les processus du même nom sont additionnés), du plus gros au plus petit."""
    groupes = {}
    for nom, octets in processus:
        g = groupes.setdefault(nom.lower(), {"nom": nom, "nombre": 0, "octets": 0})
        g["nombre"] += 1
        g["octets"] += octets
    liste = sorted(groupes.values(), key=lambda g: -g["octets"])[:nombre]
    return [{"nom": g["nom"], "libelle": _t(CONNUS[g["nom"].lower()]) if g["nom"].lower() in CONNUS else g["nom"], "nombre": g["nombre"], "octets": g["octets"], "ia": g["nom"].lower() in CONNUS} for g in liste]


def programmes_gourmands(nombre=8):
    """Gardé 5 secondes : lister les processus lance un programme sous Windows."""
    if time.monotonic() - MEMO["t"] > 5:
        MEMO.update(t=time.monotonic(), v=regrouper(lister_processus(), nombre))
    return MEMO["v"]


# --------------------------------------------------------------------------- ce qui est chargé

def charges_ollama():
    try:
        modeles = _json(adresse_ollama() + "/api/ps", None, 3).get("models", [])
    except (urllib.error.URLError, OSError, ValueError):
        return []
    sortie = []
    for m in modeles:
        nom = m.get("name") or m.get("model") or "?"
        taille, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
        sortie.append({"id": "ollama:" + nom, "genre": "ollama", "moteur": "Ollama", "nom": nom, "vram": vram, "ram": max(0, taille - vram), "taille": taille,
                       "detail": _t("garde en mémoire jusqu'à {}").format(str(m["expires_at"])[11:16]) if m.get("expires_at") and str(m["expires_at"])[:4].isdigit() and not str(m["expires_at"]).startswith("0001") else "",
                       "dechargeable": True})
    return sortie


def charges_llamacpp():
    mo = moteurs.MOTEURS.get("llamacpp")
    if mo is None or not hasattr(mo, "routeur_actif") or mo.externe():
        return []
    from . import moteur_llamacpp as ml
    with ml.SERVEUR["verrou"]:
        p = ml.SERVEUR["proc"]
        tourne = p is not None and p.poll() is None
        nom, noms = ml.SERVEUR["modele"], ml.SERVEUR["noms"]
    if not tourne:
        return []
    ram = memoire_processus(p.pid)
    routeur = nom == ml.ROUTEUR
    return [{"id": "llamacpp", "genre": "llamacpp", "moteur": "llama.cpp", "nom": _t("routeur ({} modèles disponibles)").format(len(noms)) if routeur else nom, "vram": None, "ram": ram, "taille": ram or 0,
             "detail": _t("le serveur garde les modèles demandés ; arrêté, il redémarre tout seul au prochain message") if routeur else _t("redémarre tout seul au prochain message"), "dechargeable": True}]


def charges_comfy():
    try:
        stats = _json(adresse_comfy() + "/system_stats", None, 1.5)
    except (urllib.error.URLError, OSError, ValueError):
        return []
    appareil = (stats.get("devices") or [{}])[0]
    reserve = None
    if appareil.get("torch_vram_total") is not None and appareil.get("torch_vram_free") is not None:
        reserve = max(0, int(appareil["torch_vram_total"]) - int(appareil["torch_vram_free"]))          # ce que le cache de ComfyUI garde réservé sur la carte
    try:
        q = _json(adresse_comfy() + "/queue", None, 1.5)
        travail = len(q.get("queue_running") or [])
    except (urllib.error.URLError, OSError, ValueError):
        travail = 0
    return [{"id": "comfyui", "genre": "comfyui", "moteur": "ComfyUI", "nom": "ComfyUI", "vram": reserve, "ram": None, "taille": reserve or 0,
             "detail": _t("génère {} image(s) : attends la fin avant de décharger").format(travail) if travail else _t("modèles d'images gardés en mémoire vidéo (cache)"), "dechargeable": not travail}]


def etat():
    """Tout ce qu'il faut à la page : mémoire de la machine, ce qui est chargé (avec de quoi le décharger), programmes les plus gourmands."""
    from . import moteur as _m
    ram, vram = _m.memoire_vive(), _m.memoire_video()
    charges = charges_ollama() + charges_llamacpp() + charges_comfy()
    return {"ram": ram, "vram": vram, "charges": charges, "programmes": programmes_gourmands(), "quand": time.time()}


# --------------------------------------------------------------------------- décharger

def decharger(ident):
    """Décharge une chose de la liste (par son identifiant) : {ok, message}. Lève ValueError pour une demande invalide."""
    ident = str(ident or "")
    if ident.startswith("ollama:"):
        nom = ident[7:]
        if not RE_MODELE.match(nom) or ".." in nom:
            raise ValueError(_t("Nom de modèle invalide."))
        try:
            _json(adresse_ollama() + "/api/generate", {"model": nom, "prompt": "", "keep_alive": 0}, 60)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ValueError(_t("Ollama n'a pas déchargé « {} » : {}").format(nom, e))
        return {"ok": True, "message": _t("« {} » est déchargé : la mémoire est libre.").format(nom)}
    if ident == "llamacpp":
        mo = moteurs.MOTEURS.get("llamacpp")
        if mo is None or not hasattr(mo, "arreter"):
            raise ValueError(_t("llama.cpp n'est pas disponible."))
        mo.arreter()
        return {"ok": True, "message": _t("Le serveur llama.cpp est arrêté : la mémoire est libre (il redémarre tout seul au prochain message).")}
    if ident == "comfyui":
        try:
            _json(adresse_comfy() + "/free", {"unload_models": True, "free_memory": True}, 10)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ValueError(_t("ComfyUI n'a pas libéré sa mémoire : {}").format(e))
        return {"ok": True, "message": _t("ComfyUI libère ses modèles : la mémoire vidéo sera libre dans un instant.")}
    raise ValueError(_t("On ne sait pas décharger cette ressource."))
