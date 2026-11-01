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


# ---- Enquête : « quel programme ouvre cette fenêtre qui clignote ? »
_trace = {"fichier": None, "origine": None}


def tracer(fichier):
    """Note dans `fichier` chaque programme que Lutin lance (heure, commande, si la fenêtre est masquée). Si une fenêtre clignote mais que rien n'est noté ici, ce n'est pas Lutin.
    Activé par la variable LUTIN_TRACE_PROCESSUS (« 1 » = fichier lutin-processus.log dans le dossier temporaire, ou un chemin de fichier). Renvoie le fichier utilisé."""
    import tempfile
    import time
    if _trace["fichier"]:
        return _trace["fichier"]
    chemin = fichier if fichier not in ("1", "oui", "true") else os.path.join(tempfile.gettempdir(), "lutin-processus.log")
    _trace["fichier"], _trace["origine"] = chemin, subprocess.Popen.__init__
    init = subprocess.Popen.__init__

    def popen_trace(self, *a, **kw):
        try:
            args = a[0] if a else kw.get("args", "")
            masque = bool(int(kw.get("creationflags", 0) or 0) & CREATE_NO_WINDOW) or _actif
            commande = args if isinstance(args, str) else " ".join(str(x) for x in args)
            with open(chemin, "a", encoding="utf-8") as f:
                f.write("{} pid={} fenetre_masquee={} shell={} : {}\n".format(time.strftime("%H:%M:%S"), os.getpid(), masque, bool(kw.get("shell")), commande[:400]))
        except (OSError, ValueError, TypeError):
            pass
        init(self, *a, **kw)
    popen_trace.__wrapped__ = init
    subprocess.Popen.__init__ = popen_trace
    return chemin


def arreter_trace():
    if _trace["origine"] is not None:
        subprocess.Popen.__init__ = _trace["origine"]
    _trace["fichier"] = _trace["origine"] = None
