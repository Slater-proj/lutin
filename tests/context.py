"""Rend le paquet importable sans l'installer : `import context` en tête de chaque fichier de test.

Fixe aussi la langue des tests : les messages attendus sont en français (le test de la langue anglaise change LUTIN_LANGUE lui-même, le temps d'un test)."""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Les tests créent des dossiers temporaires (mkdtemp) et ne les supprimaient jamais : des centaines de dossiers, des Go sur le disque. Ceux qu'un test crée sont retirés à la fin de son processus.
_CREES = []
_mkdtemp = tempfile.mkdtemp


def _mkdtemp_suivi(*args, **kwargs):
    dossier = _mkdtemp(*args, **kwargs)
    _CREES.append(dossier)
    return dossier


tempfile.mkdtemp = _mkdtemp_suivi
atexit.register(lambda: [shutil.rmtree(d, ignore_errors=True) for d in _CREES])

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
os.environ["LUTIN_LANGUE"] = "fr"
