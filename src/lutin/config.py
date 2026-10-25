"""Où Lutin range ses fichiers, et le fichier de configuration (versionné, avec migrations).

Quatre dossiers, tous séparés du programme (une mise à jour ou une désinstallation ne touche jamais aux données) :
  config    config.json, appareils appairés
  donnees   conversations, réglages, journal, sauvegardes
  memoire   CONTEXTE.md, MEMOIRE.md, skills
  cache     catalogue récupéré en ligne, propositions de mise à jour, téléchargements partiels (supprimable sans perte)
Variable LUTIN_HOME : tout est rangé sous ce dossier (mode portable, tests).
"""
import copy
import json
import os
import platform
import shutil
import sys
from pathlib import Path

SCHEMA = 1
DEFAUT = {
    "schema": SCHEMA,
    "installe": False,
    "securite": {"niveau": "local", "port": 8777, "url_publique": "", "proxy_ips": []},
    "emplacements": {"modeles": "", "travail": ""},           # modeles : dossier OLLAMA_MODELS ('' = emplacement habituel d'Ollama) ; travail : le dossier que Lutin peut lire et modifier
    "modeles": {"choisis": {}, "ignores": []},               # choisis : rôle -> identifiant installé par l'assistant ; ignores : propositions refusées
    "verifier_maj": True,
    "catalogue_url": "",
    "avance": False,
}


def systeme():
    return {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(platform.system(), "linux")


def dossiers(env=None, os_=None):
    """{config, donnees, memoire, cache} pour ce système."""
    env = os.environ if env is None else env
    os_ = os_ or systeme()
    home = env.get("LUTIN_HOME")
    if home:
        b = Path(home)
        return {"config": b / "config", "donnees": b / "donnees", "memoire": b / "memoire", "cache": b / "cache"}
    utilisateur = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    if os_ == "windows":
        roaming = Path(env.get("APPDATA") or utilisateur / "AppData" / "Roaming") / "Lutin"
        local = Path(env.get("LOCALAPPDATA") or utilisateur / "AppData" / "Local") / "Lutin"
        return {"config": roaming, "donnees": roaming / "donnees", "memoire": roaming / "memoire", "cache": local / "cache"}
    if os_ == "macos":
        base = utilisateur / "Library" / "Application Support" / "Lutin"
        return {"config": base, "donnees": base / "donnees", "memoire": base / "memoire", "cache": utilisateur / "Library" / "Caches" / "Lutin"}
    config = Path(env.get("XDG_CONFIG_HOME") or utilisateur / ".config") / "lutin"
    donnees = Path(env.get("XDG_DATA_HOME") or utilisateur / ".local" / "share") / "lutin"
    return {"config": config, "donnees": donnees, "memoire": donnees / "memoire", "cache": Path(env.get("XDG_CACHE_HOME") or utilisateur / ".cache") / "lutin"}


def lire_source(env=None):
    """D'où Lutin a été installé (adresse ou roue donnée à pip), pour `lutin update` : variable LUTIN_SOURCE, sinon le fichier `source.txt` que l'installateur pose à côté de l'environnement privé."""
    env = os.environ if env is None else env
    if env.get("LUTIN_SOURCE"):
        return env["LUTIN_SOURCE"].strip()
    try:
        return (Path(sys.prefix).parent / "source.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


MIGRATIONS = {}          # {version_de_départ: fonction(dict) -> dict} ; ajoutée à chaque changement de schéma, testée avec un ancien fichier réel


def migrer(d):
    """Amène une configuration quelconque au schéma courant en gardant tout ce qui est connu ; ne plante jamais sur un fichier inattendu."""
    if not isinstance(d, dict):
        return copy.deepcopy(DEFAUT)
    version = d.get("schema") if isinstance(d.get("schema"), int) else 0
    while version < SCHEMA:
        d = MIGRATIONS.get(version, lambda x: x)(d)
        version += 1
    sortie = copy.deepcopy(DEFAUT)
    for cle, valeur in d.items():
        if cle in sortie and isinstance(sortie[cle], dict) and isinstance(valeur, dict):
            sortie[cle].update(valeur)
        elif cle in sortie:
            sortie[cle] = valeur
    sortie["schema"] = SCHEMA
    return sortie


def charger(d):
    f = Path(d["config"]) / "config.json"
    try:
        brut = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        brut = None
    return migrer(brut)


def enregistrer(d, cfg):
    f = Path(d["config"]) / "config.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    if f.is_file():
        try:
            shutil.copyfile(f, str(f) + ".bak")               # la version précédente reste disponible
        except OSError:
            pass
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def preparer(d):
    """Crée les dossiers et pose les fichiers de mémoire de départ (sans jamais écraser ceux de l'utilisateur)."""
    for chemin in d.values():
        Path(chemin).mkdir(parents=True, exist_ok=True)
    modeles = Path(__file__).resolve().parent / "data"
    for nom in ("CONTEXTE.md", "MEMOIRE.md"):
        cible = Path(d["memoire"]) / nom
        if not cible.exists():
            shutil.copyfile(modeles / nom, cible)
