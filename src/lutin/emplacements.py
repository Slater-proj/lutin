"""Où Lutin range ses fichiers, ce que chaque endroit pèse, et le dossier des modèles d'Ollama (visible et modifiable).

Rien n'est caché : la page « Emplacements » liste tous les dossiers utilisés avec leur taille et la place libre du disque qui les porte. Les tailles sont mesurées avec un temps limité
(un dossier immense ou un partage réseau lent ne bloque pas la page) et gardées une minute."""
import os
import sys
from pathlib import Path

from . import moteur as _m
from . import sante as _s
from .i18n import t as _t

DELAI_MESURE = 2.0


def docker():
    return bool(os.environ.get("LUTIN_DOCKER"))


def lire_config_modeles():
    """Le dossier des modèles inscrit dans la configuration de Lutin ('' s'il n'y en a pas ; `null` ou une valeur absurde comptent comme absent)."""
    v = ((_m.config_lue().get("emplacements") or {}).get("modeles"))
    return v.strip() if isinstance(v, str) and v.strip() and v.strip().lower() != "null" else ""


def dossier_modeles():
    """Le dossier des modèles d'Ollama : la variable OLLAMA_MODELS si elle est posée, sinon celui de la configuration de Lutin, sinon l'emplacement habituel d'Ollama."""
    return Path(os.environ.get("OLLAMA_MODELS") or lire_config_modeles() or (Path.home() / ".ollama" / "models"))


def definir_dossier_modeles(chemin):
    """Change le dossier des modèles (configuration + variable utilisateur de Windows + ce processus). Les modèles déjà téléchargés ne sont PAS déplacés. Renvoie le dossier retenu."""
    chemin = str(chemin or "").strip().strip('"')
    if not chemin:
        raise ValueError(_t("Indique un dossier."))
    p = Path(chemin).expanduser()
    if not p.is_absolute():
        raise ValueError(_t("Donne un chemin complet (par exemple D:\\Modeles)."))
    if docker():
        raise ValueError(_t("Dans Docker, le dossier des modèles est le volume monté sur /models : il se change dans le fichier docker-compose."))
    try:
        p.mkdir(parents=True, exist_ok=True)
        essai = p / ".lutin-essai"
        essai.write_text("ok", encoding="utf-8")
        essai.unlink()
    except OSError as e:
        raise ValueError(_t("Ce dossier n'est pas utilisable ({}).").format(e)) from e
    cfg = _m.config_lue()
    cfg.setdefault("emplacements", {})["modeles"] = str(p)
    _m.config_ecrire(cfg)
    os.environ["OLLAMA_MODELS"] = str(p)
    _m.ENV_OLLAMA["OLLAMA_MODELS"] = str(p)
    if os.name == "nt":
        from . import installation
        installation.definir_variables_utilisateur({"OLLAMA_MODELS": str(p)}, "windows")
    _s.oublier_mesures("disques")
    return p


def taille(chemin):
    try:
        return _s.taille_dossier(chemin, DELAI_MESURE) if Path(chemin).is_dir() else 0
    except OSError:
        return None


def ligne(cle, nom, chemin, explication, **plus):
    chemin = Path(chemin)
    disque = _s.espace_disque(chemin)
    return dict({"cle": cle, "nom": nom, "chemin": str(chemin), "explication": explication, "existe": chemin.exists(), "taille": taille(chemin) if plus.pop("mesurer", True) else None,
                 "disque": {"libre": disque["libre"], "total": disque["total"], "racine": disque["racine"]} if disque else None}, **plus)


def lister():
    """Tous les emplacements utilisés : [{cle, nom, chemin, explication, existe, taille, disque}], et le détail du dossier de données."""
    from . import config
    d = config.dossiers()
    cfg_fichier = _m.chemin_config()
    lignes = [ligne("programme", _t("Programme"), Path(sys.prefix), _t("Lutin et son Python (supprimés par la désinstallation)."))]
    lignes.append(ligne("config", _t("Configuration de Lutin"), cfg_fichier.parent if cfg_fichier else d["config"], _t("config.json : niveau d'accès, dossiers de travail, langue.")))
    lignes.append(ligne("donnees", _t("Données"), _m.DONNEES, _t("Conversations, images et fichiers joints, sauvegardes avant import, journal, réglages.")))
    lignes.append(ligne("memoire", _t("Mémoire"), _m.MEMOIRE, _t("Contexte du projet et notes de l'assistant.")))
    lignes.append(ligne("cache", _t("Cache (fichiers temporaires)"), d["cache"], _t("Catalogue et numéro de version récupérés en ligne (sans risque à supprimer).")))
    o = _m.etat_ollama()
    modeles = ligne("modeles", _t("Modèles d'Ollama"), dossier_modeles(), _t("Les modèles téléchargés : c'est en général le plus gros."), mesurer=False,
                    modifiable=not docker(), source="OLLAMA_MODELS" if os.environ.get("OLLAMA_MODELS") else ("config" if lire_config_modeles() else "defaut"))
    if o["actif"] and o.get("tailles"):
        modeles["taille"] = sum(o["tailles"].values())                      # la somme annoncée par Ollama : exacte et instantanée
    else:
        modeles["taille"] = taille(dossier_modeles())
    lignes.append(modeles)
    for t in (_m.travaux_etat().get("liste") or []):
        lignes.append(ligne("travail:" + t["id"], _t("Dossier de travail : {}").format(t["nom"]), t["chemin"], _t("Les fichiers que Lutin peut lire et, avec ton accord, modifier."), mesurer=False))
    detail = []
    try:
        for sous in sorted(p for p in Path(_m.DONNEES).iterdir() if p.is_dir()):
            detail.append({"nom": sous.name, "taille": taille(sous)})
    except OSError:
        pass
    return {"lignes": lignes, "donnees_detail": sorted(detail, key=lambda x: -(x["taille"] or 0))[:8]}


def _jauge():
    dossier = dossier_modeles()
    disque = _s.espace_disque(dossier)
    if not disque:
        return None
    o = _m.etat_ollama()
    return {"chemin": str(dossier), "libre": disque["libre"], "total": disque["total"], "modeles": sum((o.get("tailles") or {}).values()), "racine": disque["racine"]}


def jauge_modeles():
    """La place du disque qui porte les modèles : {chemin, libre, total, modeles} (octets), ou None si le disque ne répond pas. Gardée quelques secondes : la page la demande à chaque rafraîchissement."""
    return _s.memo("jauge", _jauge)
