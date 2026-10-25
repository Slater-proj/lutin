"""Lutin : un assistant IA local, simple à installer, qui choisit lui-même les modèles adaptés à ta machine."""
from importlib.metadata import PackageNotFoundError, version

NOM = "Lutin"
try:
    __version__ = version("lutin")           # installé : la version vient des étiquettes git (voir pyproject.toml)
except PackageNotFoundError:
    __version__ = "0.0.0+source"             # lancé depuis les sources, sans installation (tests, développement)
