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
os.environ["LUTIN_TESTS"] = "1"          # garde-fou : pendant les tests, rien n'écrit dans le vrai registre Windows ni n'installe un vrai programme (voir alimentation.RegistreWindows, ollama_client.installer_windows)

# Hermetic tests: the result must not depend on what is installed on the machine that runs them. A developer machine usually has a real Ollama
# (a server on 127.0.0.1:11434, an executable on the PATH, OLLAMA_MODELS pointing at its models); the CI has none, so tests passed there and failed here.
# A test that needs an Ollama starts a fake one and sets OLLAMA_URL itself (after this import, by assignment).
os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:9")          # port 9 (discard): nothing answers
os.environ.pop("OLLAMA_MODELS", None)
os.environ["PATH"] = os.pathsep.join(d for d in os.environ.get("PATH", "").split(os.pathsep) if d and not any((Path(d) / nom).is_file() for nom in ("ollama", "ollama.exe")))
