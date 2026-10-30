"""Lutin dans la zone de notification de Windows (en bas à droite) : pas de fenêtre de console, seulement une icône.

- Clic gauche ou « Ouvrir l'interface » : ouvre la page de Lutin dans le navigateur.
- Clic droit : code PIN (pour connecter un téléphone), ouvrir l'interface, redémarrer, quitter.

Le serveur tourne dans un processus enfant (comme `lutin serve`) : s'il s'arrête sur une erreur, il est relancé. Sa sortie va dans donnees/serveur.log.
Quitter et redémarrer arrêtent le serveur (dans un environnement venv, `pythonw.exe` est un lanceur qui met le vrai Python dans un job Windows : en arrêtant le lanceur, il s'arrête aussi ;
mesuré). Ollama, s'il a été lancé par le serveur, n'est pas touché : d'autres programmes peuvent l'utiliser.
Première utilisation : l'installation guidée s'ouvre dans une console (sans console, on ne pourrait pas lui répondre).
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
MENU_PIN, MENU_OUVRIR, MENU_REDEMARRER, MENU_QUITTER = 1, 2, 3, 4
MESSAGE_ICONE = 0x0400 + 1          # WM_USER + 1 : message envoyé par l'icône
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


def disponible():
    return sys.platform == "win32"


if disponible():
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


def adresse(cfg):
    return "http://127.0.0.1:{}/".format(cfg["securite"]["port"])


def adresse_ouverture(dossiers, cfg):
    """L'adresse à ouvrir dans le navigateur. Au niveau « réseau », même le navigateur de cette machine s'appaire par code PIN : on en demande un au serveur (par la console, qui ne sert qu'à cette
    machine) et on le met dans l'adresse (#pin=…), la page de connexion le valide toute seule. Sans réponse du serveur, l'adresse simple."""
    base = adresse(cfg)
    if cfg.get("securite", {}).get("niveau") == "reseau":
        try:
            from . import client
            return base + "#pin=" + client.ClientLocal(dossiers["donnees"]).envoyer("/api/nouveau-pin", {})["pin"]
        except Exception:  # noqa: BLE001 — le serveur démarre peut-être encore : la page de connexion demandera le code
            pass
    return base


def ouvrir_interface(dossiers, cfg):
    threading.Thread(target=lambda: webbrowser.open(adresse_ouverture(dossiers, cfg)), daemon=True, name="zone-ouvrir").start()


def journaliser(dossiers, texte):
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


def preparer(dossiers, cfg):
    """La configuration à utiliser, ou None. Première utilisation : l'installation guidée s'ouvre dans une console (on attend qu'elle se termine), puis on repart de ce qu'elle a écrit."""
    if cfg.get("installe"):
        return cfg
    from . import config
    subprocess.run([python_console(), "-m", "lutin", "setup"], creationflags=CREATE_NEW_CONSOLE)
    cfg = config.charger(dossiers)
    return cfg if cfg.get("installe") else None


class Serveur:
    """Le serveur de Lutin dans un processus enfant sans fenêtre. `lancer` est ce que la supervision appelle à chaque démarrage."""

    def __init__(self, dossiers):
        self.dossiers = dossiers
        self.enfant = None
        self.arret = False
        self.redemarrage = False

    def lancer(self, premiere):
        from .cli import CODE_REDEMARRAGE
        if self.arret:
            return 0
        commande = [sys.executable, "-m", "lutin", "serve", "--sans-superviseur"] + ([] if premiere else ["--sans-navigateur"])
        Path(self.dossiers["donnees"]).mkdir(parents=True, exist_ok=True)
        with open(Path(self.dossiers["donnees"]) / "serveur.log", "a", encoding="utf-8") as sortie:
            self.enfant = subprocess.Popen(commande, env=dict(os.environ, LUTIN_SUPERVISE="1"), stdout=sortie, stderr=subprocess.STDOUT,
                                           creationflags=CREATE_NO_WINDOW)
            code = self.enfant.wait()
        if self.arret:
            return 0
        if self.redemarrage:
            self.redemarrage = False
            return CODE_REDEMARRAGE
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


def code_pin(dossiers):
    """Lance `lutin pin` (le même code que la commande) et renvoie son texte."""
    r = subprocess.run([sys.executable, "-m", "lutin", "pin"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=CREATE_NO_WINDOW)
    texte = (r.stdout or "").strip() or (r.stderr or "").strip()
    return texte or _t("Lutin ne répond pas : relance-le depuis l'icône.")


def message(titre, texte):
    user32.MessageBoxW(None, texte, titre, MB_OK | MB_ICONINFORMATION | MB_TOPMOST)


class Zone:
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
        data.uCallbackMessage = MESSAGE_ICONE
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
            ouvrir_interface(self.dossiers, self.cfg)
        elif choix == MENU_PIN:
            threading.Thread(target=lambda: message(_t("Lutin : code PIN"), code_pin(self.dossiers)), daemon=True, name="zone-pin").start()
        elif choix == MENU_REDEMARRER:
            threading.Thread(target=self.serveur.redemarrer, daemon=True, name="zone-redemarrer").start()
        elif choix == MENU_QUITTER:
            threading.Thread(target=self.quitter, daemon=True, name="zone-quitter").start()

    def quitter(self):
        self.serveur.arreter()
        user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def traiter(self, hwnd, msg, wparam, lparam):
        """Les messages de la fenêtre. Une exception ici resterait invisible (pas de console) : elle va dans zone.log."""
        try:
            if msg == MESSAGE_ICONE:
                evenement = lparam & 0xFFFF
                if evenement in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    ouvrir_interface(self.dossiers, self.cfg)
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
            journaliser(self.dossiers, traceback.format_exc())
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def boucle(self):
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def commande(dossiers, cfg):
    """Lance Lutin dans la zone de notification. Renvoie un code de sortie."""
    if not disponible():
        print(_t("L'icône de zone de notification n'existe que sous Windows : utilise « lutin » dans un terminal."), file=sys.stderr)
        return 1
    mutex = kernel32.CreateMutexW(None, True, "Local\\LutinZone")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        webbrowser.open(adresse_ouverture(dossiers, cfg))                 # déjà lancé : on montre l'interface au lieu d'en lancer une deuxième
        return 0
    try:
        cfg = preparer(dossiers, cfg)
        if cfg is None:
            message("Lutin", _t("L'installation n'est pas terminée : relance Lutin pour la reprendre."))
            return 1
        serveur = Serveur(dossiers)
        zone = Zone(cfg, dossiers, serveur)
        zone.creer()
        from . import cli
        threading.Thread(target=lambda: cli.superviser(serveur.lancer, ecrire=lambda t: journaliser(dossiers, t)) or user32.PostMessageW(zone.hwnd, WM_CLOSE, 0, 0),
                         daemon=True, name="zone-serveur").start()
        zone.boucle()
        serveur.arreter()
    except Exception:  # noqa: BLE001 — pas de fenêtre pour montrer l'erreur : le journal la garde
        journaliser(dossiers, traceback.format_exc())
        return 1
    finally:
        kernel32.CloseHandle(mutex)
    return 0
