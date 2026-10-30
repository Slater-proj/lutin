"""Où Lutin range ses fichiers, ce que chaque endroit pèse, et le dossier des modèles d'Ollama (visible et modifiable).

Rien n'est caché : la page « Emplacements » liste tous les dossiers utilisés avec leur taille et la place libre du disque qui les porte. Les tailles sont mesurées avec un temps limité
(un dossier immense ou un partage réseau lent ne bloque pas la page) et gardées une minute."""
import os
import sys
import threading
import time
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


# --------------------------------------------------------------------------- changer de dossier de modèles : copie des modèles déjà téléchargés, débit, redémarrage d'Ollama
COPIE = {"etat": "", "fait": 0, "total": 0, "fichier": "", "erreur": "", "source": "", "cible": ""}
_verrou_copie = threading.Lock()
DEBIT_ESSAI_MO = 16
DEBIT_LENT_MO_S = 100            # en dessous, charger un gros modèle prend des minutes : on prévient


def mesurer_debit(dossier):
    """Mo/s en écriture dans ce dossier (un fichier d'essai de 16 Mo, supprimé ensuite), ou None si l'écriture échoue. Un partage réseau lent se voit tout de suite."""
    f = Path(dossier) / ".lutin-debit"
    bloc = os.urandom(1024 * 1024)
    try:
        debut = time.time()
        with open(f, "wb") as sortie:
            for _ in range(DEBIT_ESSAI_MO):
                sortie.write(bloc)
            sortie.flush()
            os.fsync(sortie.fileno())
        duree = max(time.time() - debut, 1e-3)
        return round(DEBIT_ESSAI_MO / duree, 1)
    except OSError:
        return None
    finally:
        f.unlink(missing_ok=True)


def analyse_dossier(chemin):
    """Ce qu'il faut savoir avant d'utiliser ce dossier pour les modèles : réseau ou local, débit, place libre, modèles déjà présents."""
    from . import travaux
    p = Path(str(chemin).strip().strip('"'))
    reseau = travaux.est_reseau(p) or (os.name == "nt" and p.drive[:1].isalpha() and _lecteur_reseau(p.drive))
    avert = []
    fini, existe = travaux.avec_delai(p.is_dir, 4)                      # un partage éteint ne doit pas figer la page
    existe = bool(fini and existe)
    debit = mesurer_debit(p) if existe else None
    if reseau:
        avert.append(_t("C'est un dossier réseau : Ollama relit le modèle depuis le réseau à chaque chargement (un modèle de 17 Go prend plusieurs minutes sur un réseau gigabit) et ne marche plus si le NAS est éteint ou injoignable."))
        if p.drive[:1].isalpha() and not travaux.est_reseau(p):
            avert.append(_t("Préfère l'adresse réseau complète (\\\\serveur\\partage\\dossier) à une lettre de lecteur : une lettre mappée n'existe pas pour Ollama quand il tourne en service ou dans une autre session."))
    if debit is not None and debit < DEBIT_LENT_MO_S:
        avert.append(_t("Débit d'écriture mesuré : {} Mo/s. C'est lent pour des modèles de plusieurs Go : prévois {} min pour copier 17 Go.").format(debit, round(17 * 1024 / max(debit, 1) / 60)))
    disque = _s.espace_disque(p)
    ancien = dossier_modeles()
    return {"chemin": str(p), "reseau": bool(reseau), "debit": debit, "avertissements": avert, "libre": disque["libre"] if disque else None,
            "existe": existe, "modeles_ici": existe and (p / "manifests").is_dir(), "source": str(ancien), "source_existe": ancien.is_dir(), "source_octets": taille_modeles_installes()}


def _lecteur_reseau(lecteur):
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(lecteur + "\\") == 4          # DRIVE_REMOTE
    except (AttributeError, OSError):
        return False


def taille_modeles_installes():
    o = _m.etat_ollama()
    return sum((o.get("tailles") or {}).values()) if o.get("actif") else 0


def _fichiers(source):
    for sous in ("blobs", "manifests"):
        racine = Path(source) / sous
        if racine.is_dir():
            for f in racine.rglob("*"):
                if f.is_file():
                    yield f


def copier_modeles(cible):
    """Copie les modèles déjà téléchargés (blobs et manifests) vers le nouveau dossier, en arrière-plan. La source n'est JAMAIS supprimée ici. Un fichier déjà copié (même taille) est sauté : on peut relancer."""
    source, cible = dossier_modeles(), Path(cible)
    if source.resolve() == cible.resolve():
        raise ValueError(_t("C'est déjà le dossier des modèles."))
    if not source.is_dir():
        raise ValueError(_t("Il n'y a pas de modèle à copier : le dossier actuel n'existe pas."))
    if str(cible.resolve()).startswith(str(source.resolve()) + os.sep):
        raise ValueError(_t("Le nouveau dossier ne peut pas être dans l'ancien."))
    fichiers = list(_fichiers(source))
    total = sum(f.stat().st_size for f in fichiers)
    disque = _s.espace_disque(cible)
    if disque and total > disque["libre"] * 0.98:
        raise ValueError(_t("Pas assez de place : il faut {} Go et il en reste {} sur ce disque.").format(round(total / 1e9, 1), round(disque["libre"] / 1e9, 1)))
    with _verrou_copie:
        if COPIE["etat"] == "en cours":
            raise ValueError(_t("Une copie est déjà en cours."))
        COPIE.update(etat="en cours", fait=0, total=total, fichier="", erreur="", source=str(source), cible=str(cible))

    def travail():
        try:
            for f in fichiers:
                dest = cible / f.relative_to(source)
                COPIE["fichier"] = f.name[:40]
                if dest.is_file() and dest.stat().st_size == f.stat().st_size:
                    COPIE["fait"] += f.stat().st_size
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + ".lutin-tmp")
                with open(f, "rb") as entree, open(tmp, "wb") as sortie:
                    while True:
                        morceau = entree.read(8 * 1024 * 1024)
                        if not morceau:
                            break
                        sortie.write(morceau)
                        COPIE["fait"] += len(morceau)
                tmp.replace(dest)
            ecart = [f.name for f in fichiers if not (cible / f.relative_to(source)).is_file() or (cible / f.relative_to(source)).stat().st_size != f.stat().st_size]
            if ecart:
                raise OSError(_t("Copie incomplète : {} fichier(s) différent(s) ({}).").format(len(ecart), ", ".join(ecart[:3])))
            COPIE["etat"] = "fini"
        except OSError as e:
            COPIE.update(etat="erreur", erreur=str(e))
    threading.Thread(target=travail, daemon=True, name="copie-modeles").start()
    return dict(COPIE)


def etat_copie():
    return dict(COPIE)
