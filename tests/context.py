"""Rend le paquet importable sans l'installer : `import context` en tête de chaque fichier de test.

Fixe aussi la langue des tests : les messages attendus sont en français (le test de la langue anglaise change LUTIN_LANGUE lui-même, le temps d'un test)."""
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
os.environ["LUTIN_LANGUE"] = "fr"
