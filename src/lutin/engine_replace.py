"""Remplacer le dossier d'un moteur par sa nouvelle version, sans que Windows ne s'en mêle : llama.cpp, Colibri et les suivants passent par ici.

Sous Windows, un antivirus qui analyse les fichiers tout juste écrits, ou un programme resté ouvert dans le dossier, fait échouer le renommage (« Accès refusé ») pendant quelques secondes.
On réessaie donc avec des pauses, on arrête les programmes restés dans le dossier, et en dernier recours on copie au lieu de renommer."""
import os
import shutil
import subprocess
import time
from pathlib import Path

from .i18n import t as _t


class ErreurRemplacement(ValueError):
    """Le dossier n'a pas pu être remplacé ; le message dit pourquoi et quoi faire."""


def liberer_processus(dossier):
    """Windows : arrête les programmes qui tournent encore depuis ce dossier (un llama-server resté en vie, ou un processus fils du mode routeur) ; ils empêchent de remplacer ou supprimer les fichiers.
    Ailleurs, un fichier utilisé se supprime sans gêne : rien à faire. Renvoie le nombre de processus arrêtés."""
    if os.name != "nt":
        return 0
    chemin = str(Path(dossier).resolve()).replace("'", "''")
    script = ("$d='{}'; $n=0; Get-CimInstance Win32_Process | Where-Object {{ $_.ExecutablePath -and $_.ExecutablePath.StartsWith($d, [StringComparison]::OrdinalIgnoreCase) -and $_.ProcessId -ne $PID }} | "
              "ForEach-Object {{ try {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; $n++ }} catch {{}} }}; $n").format(chemin)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return int((r.stdout or "0").strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return 0


def supprimer_arbre(dossier):
    """Supprime un dossier ; un fichier en lecture seule est d'abord rendu modifiable (Windows). Ce qui reste (fichier verrouillé) fait échouer le test d'existence de l'appelant."""
    def _force(fonction, chemin, _info):
        try:
            os.chmod(chemin, 0o700)
            fonction(chemin)
        except OSError:
            pass
    shutil.rmtree(dossier, onerror=_force)


def remplacer_dossier(neuf, cible, dormir=None, liberer=None, pauses=(0, 1, 2, 4, 8)):
    """Met `neuf` à la place de `cible`. Sous Windows, un antivirus qui analyse les fichiers tout juste écrits, ou un programme encore ouvert, fait échouer le renommage (« Accès refusé ») pendant quelques secondes :
    on réessaie avec des pauses, on arrête les processus restés dans le dossier, et en dernier recours on copie au lieu de renommer. ErreurMoteur avec la cause si rien n'y fait."""
    dormir = dormir or time.sleep
    neuf, cible = Path(neuf), Path(cible)
    derniere = None
    for rang, pause in enumerate(pauses):
        if pause:
            dormir(pause)
        try:
            if cible.exists():
                supprimer_arbre(cible)
            if cible.exists():
                if liberer is not None and rang >= 1:
                    liberer()
                raise PermissionError(_t("un fichier de l'ancienne version est encore utilisé ({})").format(cible))
            os.replace(neuf, cible)
            return
        except OSError as e:
            derniere = e
    try:
        if cible.exists():
            supprimer_arbre(cible)
        shutil.copytree(neuf, cible, dirs_exist_ok=True)          # dernier recours : copier au lieu de renommer
        shutil.rmtree(neuf, ignore_errors=True)
        return
    except OSError as e:
        derniere = e
    raise ErreurRemplacement(_t("Impossible de remplacer l'ancienne version ({}). Ferme tout ce qui utilise llama.cpp (un llama-server encore ouvert, un antivirus qui analyse le dossier) puis relance la mise à jour.").format(derniere))


