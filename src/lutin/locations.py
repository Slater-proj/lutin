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

DELAI_MESURE = 2.0


def docker():
    return bool(os.environ.get("LUTIN_DOCKER"))


def read_models_config():
    """Le dossier des modèles inscrit dans la configuration de Lutin ('' s'il n'y en a pas ; `null` ou une valeur absurde comptent comme absent)."""
    v = ((_m.config_lue().get("emplacements") or {}).get("modeles"))
    return v.strip() if isinstance(v, str) and v.strip() and v.strip().lower() != "null" else ""


def _seen_file():
    return _m.DONNEES / "dossier_modeles_vu.json"


def remember_seen_folder(dossier):
    """Garde le dossier de modèles qu'Ollama utilisait quand il répondait (et contenait des modèles). Si Ollama est un jour relancé SANS son réglage habituel (par exemple démarré par Lutin avant l'application
    d'Ollama, ou après un redémarrage), il retomberait sur le dossier par défaut, vide : tous les modèles sembleraient perdus. Avec cette mémoire, Lutin sait où ils sont."""
    dossier = str(dossier or "").strip()
    if not dossier or not (Path(dossier) / "manifests").is_dir():
        return
    try:
        _m.ecrire_atomique(_seen_file(), json.dumps({"dossier": dossier}))
    except OSError:
        pass


def seen_folder():
    """Le dernier dossier de modèles vu par Ollama, s'il existe encore et contient des modèles ; '' sinon."""
    try:
        d = str(json.loads(_seen_file().read_text(encoding="utf-8")).get("dossier") or "")
    except (OSError, ValueError, AttributeError):
        return ""
    return d if d and (Path(d) / "manifests").is_dir() else ""


USUAL_NAMES = ("", "IA", "AI", "ia", "ai", "Models", "models", "Modeles", "LLM", "llm", "Ollama", "ollama")
SUBFOLDERS = ("", "Ollama", "ollama", "models", "Ollama/models", "ollama/models", "OLLAMA/models", "Models/Ollama", "models/ollama")


def roots_to_visit():
    """Les endroits où un dossier de modèles se range d'habitude : la racine de chaque disque (Windows), ou le dossier personnel et les montages (Linux/macOS). Seulement ceux qui existent."""
    if os.name == "nt":
        cibles = [Path(chr(c) + ":/") for c in range(ord("C"), ord("Z") + 1)]
    else:
        cibles = [Path.home(), Path("/srv"), Path("/data"), Path("/mnt"), Path("/media")] + [p for base in (Path("/mnt"), Path("/media")) if base.is_dir() for p in base.glob("*")][:20]
    return [p for p in cibles if p.is_dir()]


def find_models_folders(connus=()):
    """Les dossiers qui contiennent déjà des modèles d'Ollama, pour retrouver ceux qu'on a téléchargés ailleurs : [{chemin, modeles, octets}], le plus fourni d'abord. On ne regarde que les emplacements usuels
    (racines des disques, « IA », « Models », « Ollama »…), jamais tout le disque : c'est rapide, et un disque réseau lent ne bloque rien."""
    from . import ollama_shared_models
    vus, resultat = set(), []
    candidats = [Path(c) for c in connus if c]
    for r in roots_to_visit():
        for base in USUAL_NAMES:
            for sous in SUBFOLDERS:
                candidats.append(r / base / sous if base or sous else r)
    candidats.append(Path.home() / ".ollama" / "models")
    for c in candidats:
        try:
            cle = os.path.normcase(str(c.resolve()))
            if cle in vus or not (c / "manifests").is_dir():
                continue
            vus.add(cle)
            lus = ollama_shared_models.read_shared(c)
        except OSError:
            continue
        if lus:
            resultat.append({"chemin": str(c), "modeles": len(lus), "octets": sum(v["taille"] for v in lus.values())})
    return sorted(resultat, key=lambda x: -x["octets"])


def models_elsewhere(installes):
    """Si Ollama ne voit aucun modèle alors que le dernier dossier connu en contient : (dossier, nombre de modèles) ; None sinon."""
    if installes:
        return None
    d = seen_folder()
    if d:
        from . import ollama_shared_models
        n = len(ollama_shared_models.read_shared(d))
        if n:
            return (d, n)
    if time.time() - _RECHERCHE["t"] > 300:          # jamais retenu : on cherche dans les emplacements usuels, sans insister, en arrière-plan (un disque réseau lent ne doit pas bloquer la page)
        _RECHERCHE["t"] = time.time()
        actuel = os.path.normcase(str(models_folder()))

        def chercher():
            _RECHERCHE["v"] = [x for x in find_models_folders(connus=[os.environ.get("OLLAMA_MODELS", "")]) if os.path.normcase(x["chemin"]) != actuel]
        threading.Thread(target=chercher, daemon=True, name="recherche-modeles").start()
    return (_RECHERCHE["v"][0]["chemin"], _RECHERCHE["v"][0]["modeles"]) if _RECHERCHE["v"] else None


RE_FROM = re.compile(r"^FROM\s+(.+)$", re.M)
RE_BLOB = re.compile(r"^(.*)[\\/]blobs[\\/][^\\/]+$")
_RECHERCHE = {"t": 0.0, "v": []}
_REEL = {"t": 0.0, "v": "", "nom": ""}


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
    if maintenant() - _REEL["t"] < 60:
        return _REEL["v"]
    trouve = ""
    try:
        o = _m.etat_ollama()
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
    _REEL.update(t=maintenant(), v=trouve)
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
    cfg = _m.config_lue()
    cfg.setdefault("emplacements", {})["modeles"] = str(p)
    _m.config_ecrire(cfg)
    os.environ["OLLAMA_MODELS"] = str(p)
    _m.ENV_OLLAMA["OLLAMA_MODELS"] = str(p)
    if os.name == "nt":
        from . import setup_wizard
        setup_wizard.set_variables_user({"OLLAMA_MODELS": str(p)}, "windows")
    _s.forget_measures("disques")
    _REEL["t"] = 0.0                                                      # l'avis d'Ollama sera redemandé (il ne changera qu'à son redémarrage)
    return p


def taille(chemin):
    try:
        return _s.folder_size(chemin, DELAI_MESURE) if Path(chemin).is_dir() else 0
    except OSError:
        return None


def ligne(cle, nom, chemin, explication, **plus):
    chemin = Path(chemin)
    disque = _s.disk_space(chemin)
    return dict({"cle": cle, "nom": nom, "chemin": str(chemin), "explication": explication, "existe": chemin.exists(), "taille": taille(chemin) if plus.pop("mesurer", True) else None,
                 "disque": {"libre": disque["libre"], "total": disque["total"], "racine": disque["racine"]} if disque else None}, **plus)


def lister():
    """Tous les emplacements utilisés : [{cle, nom, chemin, explication, existe, taille, disque}], et le détail du dossier de données."""
    from . import config
    d = config.folders()
    cfg_fichier = _m.chemin_config()
    lignes = [ligne("programme", _t("Programme"), Path(sys.prefix), _t("Lutin et son Python (supprimés par la désinstallation)."))]
    lignes.append(ligne("config", _t("Configuration de Lutin"), cfg_fichier.parent if cfg_fichier else d["config"], _t("config.json : niveau d'accès, dossiers de travail, langue.")))
    lignes.append(ligne("donnees", _t("Données"), _m.DONNEES, _t("Conversations, images et fichiers joints, sauvegardes avant import, journal, réglages.")))
    lignes.append(ligne("memoire", _t("Mémoire"), _m.MEMOIRE, _t("Contexte du projet et notes de l'assistant.")))
    lignes.append(ligne("cache", _t("Cache (fichiers temporaires)"), d["cache"], _t("Catalogue et numéro de version récupérés en ligne (sans risque à supprimer).")))
    o = _m.etat_ollama()
    modeles = ligne("modeles", _t("Modèles d'Ollama"), models_folder(), _t("Les modèles téléchargés : c'est en général le plus gros."), mesurer=False,
                    modifiable=not docker(), source="ollama" if folder_reported_by_ollama() else ("OLLAMA_MODELS" if os.environ.get("OLLAMA_MODELS") else ("config" if read_models_config() else "defaut")))
    if o["actif"] and o.get("tailles"):
        modeles["taille"] = sum(o["tailles"].values())                      # la somme annoncée par Ollama : exacte et instantanée
    else:
        modeles["taille"] = taille(models_folder())
    lignes.append(modeles)
    for t in (_m.works_state().get("liste") or []):
        lignes.append(ligne("travail:" + t["id"], _t("Dossier de travail : {}").format(t["nom"]), t["chemin"], _t("Les fichiers que Lutin peut lire et, avec ton accord, modifier."), mesurer=False))
    detail = []
    try:
        for sous in sorted(p for p in Path(_m.DONNEES).iterdir() if p.is_dir()):
            detail.append({"nom": sous.name, "taille": taille(sous)})
    except OSError:
        pass
    return {"lignes": lignes, "donnees_detail": sorted(detail, key=lambda x: -(x["taille"] or 0))[:8]}


def _gauge():
    if os.environ.get("LUTIN_DEMO"):          # captures de la documentation : un disque et un chemin fictifs
        o = _m.etat_ollama()
        return {"chemin": r"C:\Users\demo\.ollama\models", "libre": 412 * 10 ** 9, "total": 931 * 10 ** 9, "modeles": sum((o.get("tailles") or {}).values()), "racine": "C:\\"}
    dossier = models_folder()
    disque = _s.disk_space(dossier)
    if not disque:
        return None
    o = _m.etat_ollama()
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
    o = _m.etat_ollama()
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


def copy_state():
    return dict(COPY)
