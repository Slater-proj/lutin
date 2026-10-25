"""Détection de la machine : carte graphique et sa mémoire, RAM, processeur, disques.

Toutes les lectures du système passent par un `lanceur` (une fonction qui exécute une commande et renvoie sa sortie) : les tests lui donnent des sorties
enregistrées de vraies machines, sans dépendre du PC qui fait tourner les tests. Rien ici n'écrit sur le disque ni n'ouvre le réseau.
"""
import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

GO = 1024 ** 3
FABRICANTS = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}


@dataclass
class Gpu:
    nom: str
    fabricant: str            # nvidia | amd | intel | apple | inconnu
    vram_go: float            # mémoire de la carte (mémoire unifiée pour Apple)
    libre_go: float = 0.0     # 0 = inconnu
    source: str = ""          # d'où vient le chiffre (utile pour comprendre une erreur de détection)


@dataclass
class Disque:
    racine: str
    libre_go: float
    total_go: float


@dataclass
class Profil:
    systeme: str = ""                 # windows | linux | macos
    architecture: str = ""
    cpu: str = ""
    coeurs: int = 0
    ram_go: float = 0.0
    ram_libre_go: float = 0.0
    gpus: list = field(default_factory=list)
    disques: list = field(default_factory=list)

    def gpu_principal(self):
        """La carte qu'Ollama utilisera le plus probablement : la plus grosse mémoire, NVIDIA d'abord à mémoire égale."""
        if not self.gpus:
            return None
        return max(self.gpus, key=lambda g: (g.vram_go, g.fabricant == "nvidia"))

    def budget_go(self):
        """Mémoire qu'on accepte de remplir avec un modèle. 85 % de la carte (le bureau en garde un peu) ; sur Mac la mémoire est partagée ; sans carte, la RAM (60 %)."""
        g = self.gpu_principal()
        if g and g.fabricant == "apple":
            return round(g.vram_go * 0.75, 1)
        if g and g.fabricant in ("nvidia", "amd") and g.vram_go >= 3:
            return round(g.vram_go * 0.85, 1)
        return round(self.ram_go * 0.6, 1)

    def sans_gpu(self):
        g = self.gpu_principal()
        return not (g and (g.fabricant in ("nvidia", "amd", "apple") and g.vram_go >= 3))

    def classe(self):
        b = self.budget_go()
        if self.sans_gpu():
            return "sans_gpu"
        if b < 10:                       # cartes de 4 à 11 Go
            return "petite"
        if b < 18:                       # 12 à 20 Go
            return "moyenne"
        if b < 36:                       # 24 à 40 Go
            return "grande"
        return "tres_grande"

    def resume(self):
        g = self.gpu_principal()
        carte = "{} ({:g} Go)".format(g.nom, g.vram_go) if g else "aucune carte graphique utilisable"
        return "{} · {} Go de RAM · {}".format(self.cpu or "processeur inconnu", round(self.ram_go), carte)

    def en_dict(self):
        return asdict(self)

    @staticmethod
    def depuis_dict(d):
        p = Profil(**{k: v for k, v in d.items() if k not in ("gpus", "disques")})
        p.gpus = [Gpu(**g) for g in d.get("gpus", [])]
        p.disques = [Disque(**x) for x in d.get("disques", [])]
        return p


# ---------------------------------------------------------------- lecture de commandes

def lancer(commande, delai=8):
    """Exécute une commande et renvoie sa sortie texte ('' si absente, en erreur ou trop lente)."""
    try:
        r = subprocess.run(commande, capture_output=True, text=True, timeout=delai, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""


# ---------------------------------------------------------------- analyse des sorties (fonctions pures, testées sur des enregistrements)

def analyser_nvidia_smi(texte):
    """`nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits` -> liste de Gpu (valeurs en Mo)."""
    gpus = []
    for ligne in (texte or "").splitlines():
        morceaux = [m.strip() for m in ligne.split(",")]
        if len(morceaux) < 2:
            continue
        try:
            total = float(morceaux[-2] if len(morceaux) >= 3 else morceaux[-1])
            libre = float(morceaux[-1]) if len(morceaux) >= 3 else 0.0
        except ValueError:
            continue
        nom = ", ".join(morceaux[:-2] if len(morceaux) >= 3 else morceaux[:-1]).strip() or "NVIDIA"
        gpus.append(Gpu(nom, "nvidia", round(total / 1024, 1), round(libre / 1024, 1), "nvidia-smi"))
    return gpus


def _fabricant_depuis_nom(nom):
    n = nom.lower()
    for mot, f in (("nvidia", "nvidia"), ("geforce", "nvidia"), ("quadro", "nvidia"), ("rtx", "nvidia"), ("amd", "amd"), ("radeon", "amd"), ("intel", "intel"), ("arc", "intel"), ("apple", "apple")):
        if mot in n:
            return f
    return "inconnu"


def _entier_registre(valeur):
    """Le registre Windows donne la mémoire vidéo soit en entier, soit en liste d'octets (little-endian)."""
    if isinstance(valeur, int):
        return valeur
    if isinstance(valeur, list) and valeur and all(isinstance(x, int) for x in valeur):
        return int.from_bytes(bytes(x & 255 for x in valeur), "little")
    return 0


SCRIPT_GPU_WINDOWS = (
    "$r=@(); "
    "Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' -ErrorAction SilentlyContinue | "
    "ForEach-Object { if ($_.DriverDesc) { $r += [pscustomobject]@{ nom=$_.DriverDesc; octets=$_.'HardwareInformation.qwMemorySize' } } }; "
    "$c=@(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | ForEach-Object { [pscustomobject]@{ nom=$_.Name; adapter=$_.AdapterRAM } }); "
    "[pscustomobject]@{ registre=$r; wmi=$c } | ConvertTo-Json -Depth 4 -Compress")


def analyser_gpus_windows(texte):
    """Sortie de SCRIPT_GPU_WINDOWS. Le champ AdapterRAM de WMI plafonne à 4 Go : on préfère la valeur du registre (64 bits) quand elle existe."""
    try:
        donnees = json.loads(texte or "{}")
    except ValueError:
        return []
    if not isinstance(donnees, dict):
        return []

    def liste(x):
        return x if isinstance(x, list) else ([x] if x else [])
    registre = {}
    for e in liste(donnees.get("registre")):
        nom, octets = str(e.get("nom") or "").strip(), _entier_registre(e.get("octets"))
        if nom and octets:
            registre[nom] = octets
    gpus = []
    for e in liste(donnees.get("wmi")):
        nom = str(e.get("nom") or "").strip()
        if not nom or "basic render" in nom.lower() or "remote" in nom.lower() or "virtual" in nom.lower():
            continue
        octets, source = registre.get(nom, 0), "registre"
        if not octets:
            octets, source = int(e.get("adapter") or 0), "wmi (plafonné à 4 Go)"
        gpus.append(Gpu(nom, _fabricant_depuis_nom(nom), round(octets / GO, 1), 0.0, source))
    return gpus


def lire_gpus_linux(racine="/sys/class/drm"):
    """Cartes AMD/Intel/NVIDIA vues par le noyau (sans outil à installer). La mémoire vient de mem_info_vram_total (AMD)."""
    gpus = []
    base = Path(racine)
    if not base.is_dir():
        return gpus
    for carte in sorted(base.glob("card[0-9]*")):
        if "-" in carte.name:
            continue
        dev = carte / "device"
        try:
            fabricant = FABRICANTS.get((dev / "vendor").read_text().strip().lower(), "inconnu")
        except OSError:
            continue
        octets = 0
        try:
            octets = int((dev / "mem_info_vram_total").read_text().strip())
        except (OSError, ValueError):
            pass
        gpus.append(Gpu("Carte {} ({})".format(carte.name[4:], fabricant), fabricant, round(octets / GO, 1), 0.0, "sysfs"))
    return gpus


# ---------------------------------------------------------------- mémoire, processeur, disques

def _ram_windows():
    import ctypes

    class Etat(ctypes.Structure):
        _fields_ = [("longueur", ctypes.c_ulong), ("charge", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("libre", ctypes.c_ulonglong), ("e1", ctypes.c_ulonglong),
                    ("e2", ctypes.c_ulonglong), ("e3", ctypes.c_ulonglong), ("e4", ctypes.c_ulonglong), ("e5", ctypes.c_ulonglong)]
    e = Etat()
    e.longueur = ctypes.sizeof(e)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e)):
        return e.total / GO, e.libre / GO
    return 0.0, 0.0


def analyser_meminfo(texte):
    """/proc/meminfo -> (total, disponible) en Go."""
    valeurs = {}
    for ligne in (texte or "").splitlines():
        if ":" in ligne:
            cle, reste = ligne.split(":", 1)
            morceaux = reste.split()
            if morceaux and morceaux[0].isdigit():
                valeurs[cle] = int(morceaux[0]) * 1024
    return valeurs.get("MemTotal", 0) / GO, valeurs.get("MemAvailable", valeurs.get("MemFree", 0)) / GO


def lire_ram(systeme, lanceur=lancer):
    if systeme == "windows":
        return _ram_windows()
    if systeme == "linux":
        try:
            return analyser_meminfo(Path("/proc/meminfo").read_text())
        except OSError:
            return 0.0, 0.0
    if systeme == "macos":
        total = lanceur(["sysctl", "-n", "hw.memsize"]).strip()
        return (int(total) / GO if total.isdigit() else 0.0), 0.0
    return 0.0, 0.0


def lister_disques(systeme):
    racines = []
    if systeme == "windows":
        import ctypes
        masque = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            lettre = chr(65 + i) + ":\\"
            if masque & (1 << i) and ctypes.windll.kernel32.GetDriveTypeW(lettre) == 3:          # 3 = disque fixe (pas de clé USB, lecteur réseau, CD)
                racines.append(lettre)
    else:
        racines = ["/", str(Path.home())]
    disques, vus = [], set()
    for r in racines:
        try:
            u = shutil.disk_usage(r)
        except OSError:
            continue
        cle = (u.total, u.free)
        if cle in vus:
            continue
        vus.add(cle)
        disques.append(Disque(r, round(u.free / GO, 1), round(u.total / GO, 1)))
    return disques


def detecter(lanceur=lancer):
    """Le profil complet de cette machine."""
    systeme = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(platform.system(), platform.system().lower())
    p = Profil(systeme=systeme, architecture=platform.machine().lower(), cpu=platform.processor() or "", coeurs=os.cpu_count() or 0)
    p.ram_go, p.ram_libre_go = (round(x, 1) for x in lire_ram(systeme, lanceur))
    nvidia = analyser_nvidia_smi(lanceur(["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"])) if shutil.which("nvidia-smi") else []
    autres = []
    if systeme == "windows":
        autres = analyser_gpus_windows(lanceur(["powershell", "-NoProfile", "-Command", SCRIPT_GPU_WINDOWS], 20))
        autres = [g for g in autres if not (g.fabricant == "nvidia" and nvidia)]                  # nvidia-smi est plus fiable pour NVIDIA
    elif systeme == "linux":
        autres = [g for g in lire_gpus_linux() if not (g.fabricant == "nvidia" and nvidia)]
    elif systeme == "macos" and p.architecture in ("arm64", "aarch64"):
        autres = [Gpu("Apple Silicon (mémoire partagée)", "apple", round(p.ram_go, 1), 0.0, "mémoire unifiée")]
    p.gpus = nvidia + autres
    p.disques = lister_disques(systeme)
    return p
