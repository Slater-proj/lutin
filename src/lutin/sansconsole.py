"""Windows, Lutin sans console (l'icône de la zone de notification, `pythonw`) : aucun programme lancé par Lutin ne doit ouvrir de fenêtre noire.

Quand un programme sans console lance un programme à console (nvidia-smi pour la carte graphique, git, taskkill, une commande de l'assistant…), Windows ouvre une console pour lui : une fenêtre
qui clignote, à chaque lancement. Plutôt que d'ajouter `creationflags` à chaque appel (et d'en oublier un), on le fait à un seul endroit : `subprocess.Popen` reçoit CREATE_NO_WINDOW.
Dans un vrai terminal (`lutin`, `lutin chat`, l'installation guidée) rien ne change : la console existe, les programmes y restent visibles."""
import os
import subprocess

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_CONSOLE = 0x00000010
_actif = False


def console_visible():
    """Vrai si ce processus a une fenêtre de console (un terminal)."""
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except (AttributeError, OSError):
        return True


def drapeaux(creationflags):
    """Les drapeaux de création avec « pas de fenêtre », sauf si l'appelant a demandé autre chose (une console à lui, ou un processus détaché)."""
    if creationflags & (DETACHED_PROCESS | CREATE_NEW_CONSOLE | CREATE_NO_WINDOW):
        return creationflags
    return creationflags | CREATE_NO_WINDOW


def envelopper(init):
    def popen_init(self, *args, **kw):
        kw["creationflags"] = drapeaux(kw.get("creationflags", 0))
        init(self, *args, **kw)
    popen_init.__wrapped__ = init
    return popen_init


def activer(force=False):
    """Active la règle (une seule fois) si Windows et pas de console. Renvoie vrai si elle est active."""
    global _actif
    if os.name != "nt":
        return False
    if _actif:
        return True
    if not force and console_visible():
        return False
    subprocess.Popen.__init__ = envelopper(subprocess.Popen.__init__)
    _actif = True
    return True
