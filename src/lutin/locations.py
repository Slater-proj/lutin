"""Où Lutin range ses fichiers, ce que chaque endroit pèse, et le dossier des modèles d'Ollama (visible et modifiable).

Rien n'est caché : la page « Emplacements » liste tous les dossiers utilisés avec leur taille et la place libre du disque qui les porte. Les tailles sont mesurées avec un temps limité
(un dossier immense ou un partage réseau lent ne bloque pas la page) et gardées une minute."""
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from . import core as _m
from . import health as _s
from .i18n import t as _t

MEASURE_TIMEOUT = 2.0


def docker():
    return bool(os.environ.get("LUTIN_DOCKER"))


def read_models_config():
    """Le dossier des modèles inscrit dans la configuration de Lutin ('' s'il n'y en a pas ; `null` ou une valeur absurde comptent comme absent)."""
    v = ((_m.read_config().get("emplacements") or {}).get("modeles"))
    return v.strip() if isinstance(v, str) and v.strip() and v.strip().lower() != "null" else ""


def _seen_file():
    return _m.DATA / "dossier_modeles_vu.json"


def remember_seen_folder(dossier):
    """Garde le dossier de modèles qu'Ollama utilisait quand il répondait (et contenait des modèles). Si Ollama est un jour relancé SANS son réglage habituel (par exemple démarré par Lutin avant l'application
    d'Ollama, ou après un redémarrage), il retomberait sur le dossier par défaut, vide : tous les modèles sembleraient perdus. Avec cette mémoire, Lutin sait où ils sont."""
    dossier = str(dossier or "").strip()
    if not dossier or not (Path(dossier) / "manifests").is_dir():
        return
    try:
        _m.write_atomic(_seen_file(), json.dumps({"dossier": dossier}))
    except OSError:
        pass


def seen_folder():
    """Le dernier dossier de modèles vu par Ollama, s'il existe encore et contient des modèles ; '' sinon."""
    try:
        d = str(json.loads(_seen_file().read_text(encoding="utf-8")).get("dossier") or "")
    except (OSError, ValueError, AttributeError):
        return ""
    return d if d and (Path(d) / "manifests").is_dir() else ""


SUBFOLDERS = ("", "Ollama", "ollama", "models", "Ollama/models", "ollama/models", "OLLAMA/models", "Models/Ollama", "models/ollama")


RE_FROM = re.compile(r"^FROM\s+(.+)$", re.M)
RE_BLOB = re.compile(r"^(.*)[\\/]blobs[\\/][^\\/]+$")
_REAL = {"t": 0.0, "v": "", "nom": ""}


def from_modelfile(texte):
    """Le dossier des modèles d'après le « Modelfile » d'un modèle installé : sa ligne FROM donne le chemin du fichier réel (…/models/blobs/sha256-…). '' si on n'en trouve pas."""
    for brut in RE_FROM.findall(texte or ""):
        m = RE_BLOB.match(brut.strip().strip('"'))
        if m:
            return m.group(1)
    return ""


def folder_reported_by_ollama(maintenant=time.time):
    """Le dossier des modèles tel qu'Ollama LUI-MÊME l'utilise : on le lui demande (Modelfile d'un modèle installé), sans deviner d'après des variables qui ne sont pas forcément celles
    du serveur Ollama (le réglage de l'application Ollama, par exemple, n'est pas visible de Lutin). Gardé une minute. '' si Ollama est éteint ou n'a aucun modèle."""
    if maintenant() - _REAL["t"] < 60:
        return _REAL["v"]
    trouve = ""
    try:
        o = _m.ollama_state()
        if o["actif"]:
            from . import agent
            for nom in o["installes"][:3]:
                try:
                    trouve = from_modelfile(agent.ollama_json("/api/show", {"model": nom}, 5).get("modelfile"))
                except (OSError, ValueError):
                    continue
                if trouve:
                    break
    except (OSError, ValueError, KeyError):
        trouve = ""
    _REAL.update(t=maintenant(), v=trouve)
    if trouve:
        remember_seen_folder(trouve)
    return trouve


def models_folder():
    """Le dossier des modèles d'Ollama : celui qu'Ollama dit utiliser s'il répond, sinon la variable OLLAMA_MODELS, sinon la configuration de Lutin, sinon l'emplacement habituel."""
    reel = folder_reported_by_ollama()
    return Path(reel or os.environ.get("OLLAMA_MODELS") or read_models_config() or (Path.home() / ".ollama" / "models"))


def set_models_folder(chemin):
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
    cfg = _m.read_config()
    cfg.setdefault("emplacements", {})["modeles"] = str(p)
    _m.write_config(cfg)
    os.environ["OLLAMA_MODELS"] = str(p)
    _m.ENV_OLLAMA["OLLAMA_MODELS"] = str(p)
    if os.name == "nt":
        from . import setup_wizard
        setup_wizard.set_variables_user({"OLLAMA_MODELS": str(p)}, "windows")
    _s.forget_measures("disques")
    _REAL["t"] = 0.0                                                      # l'avis d'Ollama sera redemandé (il ne changera qu'à son redémarrage)
    return p


def size_of(chemin):
    try:
        return _s.folder_size(chemin, MEASURE_TIMEOUT) if Path(chemin).is_dir() else 0
    except OSError:
        return None


def location_row(cle, nom, chemin, explication, **plus):
    chemin = Path(chemin)
    disque = _s.disk_space(chemin)
    return dict({"cle": cle, "nom": nom, "chemin": str(chemin), "explication": explication, "existe": chemin.exists(), "taille": size_of(chemin) if plus.pop("mesurer", True) else None,
                 "disque": {"libre": disque["libre"], "total": disque["total"], "racine": disque["racine"]} if disque else None}, **plus)


def list_locations():
    """Tous les emplacements utilisés : [{cle, nom, chemin, explication, existe, taille, disque}], et le détail du dossier de données."""
    from . import config
    d = config.folders()
    cfg_fichier = _m.config_path()
    lignes = [location_row("programme", _t("Programme"), Path(sys.prefix), _t("Lutin et son Python (supprimés par la désinstallation)."))]
    lignes.append(location_row("config", _t("Configuration de Lutin"), cfg_fichier.parent if cfg_fichier else d["config"], _t("config.json : niveau d'accès, dossiers de travail, langue.")))
    lignes.append(location_row("donnees", _t("Données"), _m.DATA, _t("Conversations, images et fichiers joints, sauvegardes avant import, journal, réglages.")))
    lignes.append(location_row("memoire", _t("Mémoire"), _m.MEMORY, _t("Contexte du projet et notes de l'assistant.")))
    lignes.append(location_row("cache", _t("Cache (fichiers temporaires)"), d["cache"], _t("Catalogue et numéro de version récupérés en ligne (sans risque à supprimer).")))
    o = _m.ollama_state()
    modeles = location_row("modeles", _t("Modèles d'Ollama"), models_folder(), _t("Les modèles téléchargés : c'est en général le plus gros."), mesurer=False,
                    modifiable=not docker(), source="ollama" if folder_reported_by_ollama() else ("OLLAMA_MODELS" if os.environ.get("OLLAMA_MODELS") else ("config" if read_models_config() else "defaut")))
    if o["actif"] and o.get("tailles"):
        modeles["taille"] = sum(o["tailles"].values())                      # la somme annoncée par Ollama : exacte et instantanée
    else:
        modeles["taille"] = size_of(models_folder())
    lignes.append(modeles)
    for t in (_m.works_state().get("liste") or []):
        lignes.append(location_row("travail:" + t["id"], _t("Dossier de travail : {}").format(t["nom"]), t["chemin"], _t("Les fichiers que Lutin peut lire et, avec ton accord, modifier."), mesurer=False))
    detail = []
    try:
        for sous in sorted(p for p in Path(_m.DATA).iterdir() if p.is_dir()):
            detail.append({"nom": sous.name, "taille": size_of(sous)})
    except OSError:
        pass
    return {"lignes": lignes, "donnees_detail": sorted(detail, key=lambda x: -(x["taille"] or 0))[:8]}


def _gauge():
    if os.environ.get("LUTIN_DEMO"):          # captures de la documentation : un disque et un chemin fictifs
        o = _m.ollama_state()
        return {"chemin": r"C:\Users\demo\.ollama\models", "libre": 412 * 10 ** 9, "total": 931 * 10 ** 9, "modeles": sum((o.get("tailles") or {}).values()), "racine": "C:\\"}
    dossier = models_folder()
    disque = _s.disk_space(dossier)
    if not disque:
        return None
    o = _m.ollama_state()
    return {"chemin": str(dossier), "libre": disque["libre"], "total": disque["total"], "modeles": sum((o.get("tailles") or {}).values()), "racine": disque["racine"]}


def models_gauge():
    """La place du disque qui porte les modèles : {chemin, libre, total, modeles} (octets), ou None si le disque ne répond pas. Gardée quelques secondes : la page la demande à chaque rafraîchissement."""
    return _s.memo("jauge", _gauge)


# --------------------------------------------------------------------------- changer de dossier de modèles : copie des modèles déjà téléchargés, débit, redémarrage d'Ollama
COPY = {"etat": "", "fait": 0, "total": 0, "fichier": "", "erreur": "", "source": "", "cible": ""}
_copy_lock = threading.Lock()
TEST_THROUGHPUT_MB = 16
SLOW_THROUGHPUT_MB_S = 100            # en dessous, charger un gros modèle prend des minutes : on prévient


def measure_throughput(dossier):
    """Mo/s en écriture dans ce dossier (un fichier d'essai de 16 Mo, supprimé ensuite), ou None si l'écriture échoue. Un partage réseau lent se voit tout de suite."""
    f = Path(dossier) / ".lutin-debit"
    bloc = os.urandom(1024 * 1024)
    try:
        debut = time.time()
        with open(f, "wb") as sortie:
            for _ in range(TEST_THROUGHPUT_MB):
                sortie.write(bloc)
            sortie.flush()
            os.fsync(sortie.fileno())
        duree = max(time.time() - debut, 1e-3)
        return round(TEST_THROUGHPUT_MB / duree, 1)
    except OSError:
        return None
    finally:
        f.unlink(missing_ok=True)


def analyze_folder(chemin):
    """Ce qu'il faut savoir avant d'utiliser ce dossier pour les modèles : réseau ou local, débit, place libre, modèles déjà présents."""
    from . import workspaces
    p = Path(str(chemin).strip().strip('"'))
    reseau = workspaces.is_network(p) or (os.name == "nt" and p.drive[:1].isalpha() and _network_drive(p.drive))
    avert = []
    fini, existe = workspaces.with_timeout(p.is_dir, 4)                      # un partage éteint ne doit pas figer la page
    existe = bool(fini and existe)
    debit = measure_throughput(p) if existe else None
    if reseau:
        avert.append(_t("C'est un dossier réseau : Ollama relit le modèle depuis le réseau à chaque chargement (un modèle de 17 Go prend plusieurs minutes sur un réseau gigabit) et ne marche plus si le NAS est éteint ou injoignable."))
        if p.drive[:1].isalpha() and not workspaces.is_network(p):
            avert.append(_t("Préfère l'adresse réseau complète (\\\\serveur\\partage\\dossier) à une lettre de lecteur : une lettre mappée n'existe pas pour Ollama quand il tourne en service ou dans une autre session."))
    if debit is not None and debit < SLOW_THROUGHPUT_MB_S:
        avert.append(_t("Débit d'écriture mesuré : {} Mo/s. C'est lent pour des modèles de plusieurs Go : prévois {} min pour copier 17 Go.").format(debit, round(17 * 1024 / max(debit, 1) / 60)))
    disque = _s.disk_space(p)
    ancien = models_folder()
    return {"chemin": str(p), "reseau": bool(reseau), "debit": debit, "avertissements": avert, "libre": disque["libre"] if disque else None,
            "existe": existe, "modeles_ici": existe and (p / "manifests").is_dir(), "source": str(ancien), "source_existe": ancien.is_dir(), "source_octets": installed_models_size()}


def _network_drive(lecteur):
    try:
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(lecteur + "\\") == 4          # DRIVE_REMOTE
    except (AttributeError, OSError):
        return False


def installed_models_size():
    o = _m.ollama_state()
    return sum((o.get("tailles") or {}).values()) if o.get("actif") else 0


def _files(source):
    for sous in ("blobs", "manifests"):
        racine = Path(source) / sous
        if racine.is_dir():
            for f in racine.rglob("*"):
                if f.is_file():
                    yield f


def copy_models(cible):
    """Copie les modèles déjà téléchargés (blobs et manifests) vers le nouveau dossier, en arrière-plan. La source n'est JAMAIS supprimée ici. Un fichier déjà copié (même taille) est sauté : on peut relancer."""
    source, cible = models_folder(), Path(cible)
    if source.resolve() == cible.resolve():
        raise ValueError(_t("C'est déjà le dossier des modèles."))
    if not source.is_dir():
        raise ValueError(_t("Il n'y a pas de modèle à copier : le dossier actuel n'existe pas."))
    if str(cible.resolve()).startswith(str(source.resolve()) + os.sep):
        raise ValueError(_t("Le nouveau dossier ne peut pas être dans l'ancien."))
    fichiers = list(_files(source))
    total = sum(f.stat().st_size for f in fichiers)
    disque = _s.disk_space(cible)
    if disque and total > disque["libre"] * 0.98:
        raise ValueError(_t("Pas assez de place : il faut {} Go et il en reste {} sur ce disque.").format(round(total / 1e9, 1), round(disque["libre"] / 1e9, 1)))
    with _copy_lock:
        if COPY["etat"] == "en cours":
            raise ValueError(_t("Une copie est déjà en cours."))
        COPY.update(etat="en cours", fait=0, total=total, fichier="", erreur="", source=str(source), cible=str(cible))

    def travail():
        try:
            for f in fichiers:
                dest = cible / f.relative_to(source)
                COPY["fichier"] = f.name[:40]
                if dest.is_file() and dest.stat().st_size == f.stat().st_size:
                    COPY["fait"] += f.stat().st_size
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + ".lutin-tmp")
                with open(f, "rb") as entree, open(tmp, "wb") as sortie:
                    while True:
                        morceau = entree.read(8 * 1024 * 1024)
                        if not morceau:
                            break
                        sortie.write(morceau)
                        COPY["fait"] += len(morceau)
                tmp.replace(dest)
            ecart = [f.name for f in fichiers if not (cible / f.relative_to(source)).is_file() or (cible / f.relative_to(source)).stat().st_size != f.stat().st_size]
            if ecart:
                raise OSError(_t("Copie incomplète : {} fichier(s) différent(s) ({}).").format(len(ecart), ", ".join(ecart[:3])))
            COPY["etat"] = "fini"
        except OSError as e:
            COPY.update(etat="erreur", erreur=str(e))
    threading.Thread(target=travail, daemon=True, name="copie-modeles").start()
    return dict(COPY)


