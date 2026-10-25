"""Rend le paquet importable sans l'installer : `import context` en tête de chaque fichier de test."""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
