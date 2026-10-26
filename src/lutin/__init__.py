"""Lutin : un assistant IA local, simple à installer, qui choisit lui-même les modèles adaptés à ta machine."""
import re
from importlib.metadata import PackageNotFoundError, distributions, version

NOM = "Lutin"


def _numeros(texte):
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", texte or "")
    return tuple(int(n) for n in m.groups()) if m else (0, 0, 0)


def version_installee():
    """La version de Lutin installée : la plus haute des métadonnées trouvées. Une mise à jour par-dessus un dossier existant (installateur Windows, copie) peut laisser les métadonnées
    d'une ancienne version à côté des nouvelles ; « la première trouvée » afficherait alors l'ancienne alors que le code est le nouveau."""
    try:
        versions = [d.version for d in distributions(name="lutin") if d.version]
    except Exception:  # noqa: BLE001 — jamais bloquant au démarrage
        versions = []
    if versions:
        return max(versions, key=_numeros)
    return version("lutin")


try:
    __version__ = version_installee()           # installé : la version vient des étiquettes git (voir pyproject.toml)
except PackageNotFoundError:
    __version__ = "0.0.0+source"             # lancé depuis les sources, sans installation (tests, développement)
