"""Lutin dans la zone de notification de Windows (en bas à droite) : pas de fenêtre de console, seulement une icône.

- Clic gauche ou « Ouvrir l'interface » : ouvre la page de Lutin dans le navigateur.
- Clic droit : code PIN (pour connecter un téléphone), ouvrir l'interface, redémarrer, quitter.

Le serveur tourne dans un processus enfant (comme `lutin serve`) : s'il s'arrête sur une erreur, il est relancé. Sa sortie va dans donnees/serveur.log.
Quitter et redémarrer arrêtent le serveur (dans un environnement venv, `pythonw.exe` est un lanceur qui met le vrai Python dans un job Windows : en arrêtant le lanceur, il s'arrête aussi ;
mesuré). Ollama, s'il a été lancé par le serveur, n'est pas touché : d'autres programmes peuvent l'utiliser.
Première utilisation : la configuration de base se fait sans fenêtre (valeurs conseillées) ; les questions sont posées par le guide, dans le navigateur.
Tout passe par ctypes (la bibliothèque standard) : Lutin n'a toujours aucune dépendance. Sur un autre système, la commande le dit et s'arrête."""
import ctypes
import os
import subprocess
import sys
import threading
import traceback
import webbrowser
from ctypes import wintypes
from pathlib import Path

from .i18n import t as _t

CREATE_NO_WINDOW, CREATE_NEW_CONSOLE = 0x08000000, 0x00000010
MENU_PIN, MENU_OUVRIR, MENU_REDEMARRER, MENU_QUITTER, MENU_MAJ = 1, 2, 3, 4, 5
ICON_MESSAGE = 0x0400 + 1          # WM_USER + 1 : message envoyé par l'icône
WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0203, 0x0205, 0x007B
WM_NULL, WM_CLOSE, WM_DESTROY = 0x0000, 0x0010, 0x0002
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
MF_STRING = 0x0000
TPM_RIGHTBUTTON, TPM_BOTTOMALIGN, TPM_RETURNCMD = 0x0002, 0x0020, 0x0100
WS_EX_TOOLWINDOW = 0x00000080       # fenêtre cachée, jamais dans la barre des tâches
MB_OK, MB_ICONINFORMATION, MB_TOPMOST = 0x0000, 0x0040, 0x00040000
ERROR_ALREADY_EXISTS = 183


def available():
    return sys.platform == "win32"


if available():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    HANDLE = ctypes.c_void_p
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HANDLE, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", HANDLE), ("hIcon", HANDLE),
                    ("hCursor", HANDLE), ("hbrBackground", HANDLE), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", HANDLE), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
                    ("hIcon", HANDLE), ("szTip", wintypes.WCHAR * 128)]

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class MSG(ctypes.Structure):
        _fields_ = [("hWnd", HANDLE), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", POINT)]

    user32.DefWindowProcW.restype, user32.DefWindowProcW.argtypes = LRESULT, [HANDLE, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.RegisterClassW.restype, user32.RegisterClassW.argtypes = wintypes.ATOM, [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterWindowMessageW.restype, user32.RegisterWindowMessageW.argtypes = wintypes.UINT, [wintypes.LPCWSTR]
    user32.CreateWindowExW.restype = HANDLE
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, HANDLE, HANDLE, HANDLE, HANDLE]
    user32.DestroyWindow.argtypes = [HANDLE]
    user32.LoadImageW.restype = HANDLE
    user32.LoadImageW.argtypes = [HANDLE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), HANDLE, wintypes.UINT, wintypes.UINT]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostMessageW.argtypes = [HANDLE, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.CreatePopupMenu.restype = HANDLE
    user32.AppendMenuW.argtypes = [HANDLE, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.TrackPopupMenu.restype = ctypes.c_int
    user32.TrackPopupMenu.argtypes = [HANDLE, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, HANDLE, HANDLE]
    user32.DestroyMenu.argtypes = [HANDLE]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.SetForegroundWindow.argtypes = [HANDLE]
    user32.MessageBoxW.argtypes = [HANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    kernel32.CreateMutexW.restype = HANDLE
    kernel32.CreateMutexW.argtypes = [HANDLE, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = HANDLE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.CloseHandle.argtypes = [HANDLE]


def address(cfg):
    return "http://127.0.0.1:{}/".format(cfg["securite"]["port"])


def address_opening(dossiers, cfg):
    """L'adresse à ouvrir dans le navigateur. Au niveau « réseau », même le navigateur de cette machine s'appaire par code PIN : on en demande un au serveur (par la console, qui ne sert qu'à cette
    machine) et on le met dans l'adresse (#pin=…), la page de connexion le valide toute seule. Sans réponse du serveur, l'adresse simple."""
    base = address(cfg)
    if cfg.get("securite", {}).get("niveau") == "reseau":
        try:
            from . import client
            return base + "#pin=" + client.LocalClient(dossiers["donnees"]).envoyer("/api/nouveau-pin", {})["pin"]
        except Exception:  # noqa: BLE001 — le serveur démarre peut-être encore : la page de connexion demandera le code
            pass
    return base


def open_interface(dossiers, cfg):
    threading.Thread(target=lambda: webbrowser.open(address_opening(dossiers, cfg)), daemon=True, name="zone-ouvrir").start()


def log(dossiers, texte):
    try:
        Path(dossiers["donnees"]).mkdir(parents=True, exist_ok=True)
        with open(Path(dossiers["donnees"]) / "zone.log", "a", encoding="utf-8") as f:
            f.write(texte + "\n")
    except OSError:
        pass


def python_console():
    """python.exe à côté de pythonw.exe : l'installation guidée a besoin d'une console."""
    exe = Path(sys.executable)
    candidat = exe.with_name("python.exe")
    return str(candidat) if candidat.is_file() else str(exe)


FIRST_SETUP = ["setup", "--yes", "--no-models", "--no-ollama"]


def prepare(dossiers, cfg):
    """La configuration à utiliser, ou None. Première utilisation : la configuration de base se fait sans fenêtre, avec les valeurs conseillées (langue
    du système, accès depuis cette machine seulement, dossier de travail habituel), sans installer de moteur ni télécharger de modèle. Les vraies
    questions (moteur, usage, modèle, avec la taille avant chaque téléchargement) sont posées par le guide du premier lancement, dans le navigateur.
    Avant, une console posait ses questions puis la page les reposait (remarque du mainteneur, 2026-11-19). `lutin` en ligne de commande garde la console."""
    if cfg.get("installe"):
        return cfg
    from . import config
    r = subprocess.run([python_console(), "-m", "lutin"] + FIRST_SETUP, creationflags=CREATE_NO_WINDOW, capture_output=True, text=True, encoding="utf-8", errors="replace")
    cfg = config.load(dossiers)
    if not cfg.get("installe"):
        log(dossiers, "Configuration de base impossible (code {}) :\n{}\n{}".format(getattr(r, "returncode", "?"), getattr(r, "stdout", "") or "", getattr(r, "stderr", "") or ""))
        return None
    return cfg


class Server:
    """Le serveur de Lutin dans un processus enfant sans fenêtre. `lancer` est ce que la supervision appelle à chaque démarrage."""

    def __init__(self, dossiers, ouvrir=True):
        self.dossiers = dossiers
        self.ouvrir = ouvrir
        self.enfant = None
        self.arret = False
        self.redemarrage = False

    def lancer(self, premiere):
        from .cli import RESTART_CODE
        if self.arret:
            return 0
        cmd = [sys.executable, "-m", "lutin", "serve", "--no-supervisor"] + ([] if premiere and self.ouvrir else ["--no-browser"])
        Path(self.dossiers["donnees"]).mkdir(parents=True, exist_ok=True)
        with open(Path(self.dossiers["donnees"]) / "serveur.log", "a", encoding="utf-8") as sortie:
            self.enfant = subprocess.Popen(cmd, env=dict(os.environ, LUTIN_SUPERVISE="1"), stdout=sortie, stderr=subprocess.STDOUT,
                                           creationflags=CREATE_NO_WINDOW)
            code = self.enfant.wait()
        if self.arret:
            return 0
        if self.redemarrage:
            self.redemarrage = False
            return RESTART_CODE
        return code

    def tuer(self):
        """Arrête le serveur (le lanceur de venv arrête aussi le vrai Python qu'il a démarré)."""
        if self.enfant and self.enfant.poll() is None:
            self.enfant.terminate()

    def redemarrer(self):
        self.redemarrage = True
        self.tuer()

    def arreter(self):
        self.arret = True
        self.tuer()


def pin_code(dossiers):
    """Lance `lutin pin` (le même code que la commande) et renvoie son texte."""
    r = subprocess.run([sys.executable, "-m", "lutin", "pin"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=CREATE_NO_WINDOW)
    texte = (r.stdout or "").strip() or (r.stderr or "").strip()
    return texte or _t("Lutin ne répond pas : relance-le depuis l'icône.")


def relaunch_icon_after_quit(delai=4):
    """Lance, dans quelques secondes et sans fenêtre, une nouvelle icône Lutin (la mise à jour a remplacé le code : l'ancienne icône doit quitter et la nouvelle prendre sa place)."""
    code = "import time, subprocess, sys; time.sleep({}); subprocess.Popen([sys.executable, '-m', 'lutin', 'zone'])".format(int(delai))
    subprocess.Popen([sys.executable, "-c", code], creationflags=CREATE_NO_WINDOW | 0x00000008, close_fds=True)          # 0x8 = DETACHED_PROCESS


def message(titre, texte):
    user32.MessageBoxW(None, texte, titre, MB_OK | MB_ICONINFORMATION | MB_TOPMOST)


class Tray:
    """L'icône et son menu. Une seule boucle de messages (le fil principal) ; les actions lentes tournent dans leur propre fil."""

    def __init__(self, cfg, dossiers, serveur):
        self.cfg, self.dossiers, self.serveur = cfg, dossiers, serveur
        self.hwnd = None
        self.icone = None
        self.data = None
        self.msg_barre = 0
        self.proc = WNDPROC(self.traiter)
        self.classe = "LutinZone"

    def creer(self):
        instance = kernel32.GetModuleHandleW(None)
        classe = WNDCLASSW()
        classe.lpfnWndProc = self.proc
        classe.hInstance = instance
        classe.lpszClassName = self.classe
        if not user32.RegisterClassW(ctypes.byref(classe)):
            raise ctypes.WinError(ctypes.get_last_error())
        # une vraie fenêtre, cachée et absente de la barre des tâches (pas une fenêtre « message seulement » : celle-là ne peut pas passer au premier plan, or le menu en a besoin)
        self.hwnd = user32.CreateWindowExW(WS_EX_TOOLWINDOW, self.classe, "Lutin", 0, 0, 0, 0, 0, None, None, instance, None)
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.msg_barre = user32.RegisterWindowMessageW("TaskbarCreated")          # l'Explorateur a redémarré : il faut remettre l'icône
        self.icone = self.charger_icone()
        self.ajouter_icone()

    def ajouter_icone(self):
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = ICON_MESSAGE
        data.hIcon = self.icone
        data.szTip = "Lutin"
        self.data = data
        return bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)))

    def charger_icone(self):
        chemin = Path(__file__).resolve().parent / "web" / "lutin.ico"
        return user32.LoadImageW(None, str(chemin), IMAGE_ICON, 0, 0, LR_LOADFROMFILE) if chemin.is_file() else None

    def menu(self):
        m = user32.CreatePopupMenu()
        user32.AppendMenuW(m, MF_STRING, MENU_PIN, _t("Code PIN (connecter un téléphone)"))
        user32.AppendMenuW(m, MF_STRING, MENU_OUVRIR, _t("Ouvrir l'interface"))
        user32.AppendMenuW(m, MF_STRING, MENU_MAJ, _t("Mettre à jour Lutin"))
        user32.AppendMenuW(m, MF_STRING, MENU_REDEMARRER, _t("Redémarrer"))
        user32.AppendMenuW(m, MF_STRING, MENU_QUITTER, _t("Quitter"))
        return m

    def afficher_menu(self):
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        m = self.menu()
        user32.SetForegroundWindow(self.hwnd)
        choix = user32.TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN | TPM_RETURNCMD, pt.x, pt.y, 0, self.hwnd, None)
        user32.DestroyMenu(m)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)           # le menu se referme proprement au prochain clic
        if choix:
            self.action(choix)

    def action(self, choix):
        if choix == MENU_OUVRIR:
            open_interface(self.dossiers, self.cfg)
        elif choix == MENU_PIN:
            threading.Thread(target=lambda: message(_t("Lutin : code PIN"), pin_code(self.dossiers)), daemon=True, name="zone-pin").start()
        elif choix == MENU_REDEMARRER:
            threading.Thread(target=self.serveur.redemarrer, daemon=True, name="zone-redemarrer").start()
        elif choix == MENU_MAJ:
            threading.Thread(target=self.mettre_a_jour, daemon=True, name="zone-maj").start()
        elif choix == MENU_QUITTER:
            threading.Thread(target=self.quitter, daemon=True, name="zone-quitter").start()

    def mettre_a_jour(self):
        """Met Lutin à jour (comme `lutin update --app`), le dit dans une fenêtre, puis relance le serveur ET l'icône pour que la nouvelle version tourne vraiment."""
        from . import cli
        lignes = []
        try:
            code, _, apres = cli.detailed_update(lignes.append, lignes.append, capturer=True)
        except Exception as erreur:  # noqa: BLE001 — pas de console : la fenêtre dit ce qui s'est passé
            code, apres = 1, None
            lignes.append(str(erreur)[:300])
        message(_t("Lutin : mise à jour"), chr(10).join(lignes))
        if code == 0 and apres:
            relaunch_icon_after_quit()
            self.quitter()

    def quitter(self):
        self.serveur.arreter()
        user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def traiter(self, hwnd, msg, wparam, lparam):
        """Les messages de la fenêtre. Une exception ici resterait invisible (pas de console) : elle va dans zone.log."""
        try:
            if msg == ICON_MESSAGE:
                evenement = lparam & 0xFFFF
                if evenement in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    open_interface(self.dossiers, self.cfg)
                elif evenement in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self.afficher_menu()
                return 0
            if self.msg_barre and msg == self.msg_barre:
                self.ajouter_icone()
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                if self.data is not None:
                    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.data))
                user32.PostQuitMessage(0)
                return 0
        except Exception:  # noqa: BLE001
            log(self.dossiers, traceback.format_exc())
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def boucle(self):
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def command(dossiers, cfg, ouvrir=True):
    """Lance Lutin dans la zone de notification. Renvoie un code de sortie."""
    if not available():
        print(_t("L'icône de zone de notification n'existe que sous Windows : utilise « lutin » dans un terminal."), file=sys.stderr)
        return 1
    mutex = kernel32.CreateMutexW(None, True, "Local\\LutinZone")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        if ouvrir:
            webbrowser.open(address_opening(dossiers, cfg))                 # déjà lancé : on montre l'interface au lieu d'en lancer une deuxième
        return 0
    try:
        cfg = prepare(dossiers, cfg)
        if cfg is None:
            message("Lutin", _t("La configuration de Lutin n'a pas pu se faire : le détail est dans zone.log (dossier des données). Relance Lutin pour réessayer."))
            return 1
        serveur = Server(dossiers, ouvrir)
        zone = Tray(cfg, dossiers, serveur)
        zone.creer()
        from . import cli
        threading.Thread(target=lambda: cli.supervise(serveur.lancer, ecrire=lambda t: log(dossiers, t)) or user32.PostMessageW(zone.hwnd, WM_CLOSE, 0, 0),
                         daemon=True, name="zone-serveur").start()
        zone.boucle()
        serveur.arreter()
    except Exception:  # noqa: BLE001 — pas de fenêtre pour montrer l'erreur : le journal la garde
        log(dossiers, traceback.format_exc())
        return 1
    finally:
        kernel32.CloseHandle(mutex)
    return 0
