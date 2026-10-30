"""Le moteur de Lutin : un agent de conversation (comme Claude Code) branché sur un modèle local (Ollama).

Il sait lister / lire / chercher dans un dossier de travail choisi par l'utilisateur, écrire ou modifier un fichier (sauvegarde automatique + accord demandé,
avec les différences), lancer une commande (accord demandé, sauf lectures simples), garder des notes durables, chercher sur le web si la case est cochée.
Contexte durable, comme un CLAUDE.md : memoire/CONTEXTE.md (consignes, modifiables à la main) + memoire/MEMOIRE.md (notes de l'assistant).
Les conversations sont gardées dans le dossier de données ; quand elles deviennent trop longues, le début est résumé par le modèle.

Tout est local. Bibliothèque standard seulement. Le lanceur (lutin.demarrage) fixe les dossiers et le niveau de sécurité avant de démarrer le serveur.
"""
import json
import os
import re
import secrets
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import socket
from http.server import ThreadingHTTPServer
from pathlib import Path
import zlib

from . import __version__ as _VERSION_LUTIN
from . import bench as _bench
from . import catalogue as _catalogue
from . import config as _config
from . import i18n as _i18n
from . import securite as _sec
from .i18n import t as _t
from .i18n import traduire as _tr
from .ollama_client import Ollama as _Ollama

ICI = Path(__file__).resolve().parent
WEB = ICI / "web"
RACINE = Path(os.environ.get("LUTIN_RACINE") or Path.cwd()).resolve()          # le dossier de travail : la seule partie du disque que l'assistant peut lire et modifier
DONNEES = Path(os.environ.get("LUTIN_DONNEES") or Path.home() / ".lutin" / "donnees")
MEMOIRE = Path(os.environ.get("LUTIN_MEMOIRE") or DONNEES.parent / "memoire")
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OUTIL = os.environ.get("LUTIN_OUTIL_URL", "").rstrip("/")          # extension facultative (outil d'images) : sans adresse, ses outils ne sont pas proposés au modèle
PORT = int(os.environ.get("LUTIN_PORT", "8777"))
VERSION = _VERSION_LUTIN
JETON = secrets.token_hex(16)                 # écrit dans la page : protège contre les requêtes venant d'autres sites
JETON_CONSOLE = secrets.token_hex(16)         # écrit dans un fichier réservé à l'utilisateur : sert à la ligne de commande (lutin chat), n'est jamais dans la page

# Sécurité : le lanceur remplace ces valeurs avant de démarrer le serveur (voir lutin.securite).
SECURITE = _sec.Securite()
APPAREILS = _sec.Appareils()
LIMITEUR_PIN = _sec.LimiteurDebit(10, 60)
IP_LAN = ""
VERIFICATEUR = None          # fonction(portee) -> propositions de modèles ; fournie par le lanceur (boutons « chercher » de l'onglet Modèles)

# Modèles proposés : le catalogue livré avec Lutin (lutin/data/modeles.json), pas du code. Le lanceur peut y ajouter une copie plus récente.
_CATALOGUE = _catalogue.charger(os.environ.get("LUTIN_CATALOGUE") or None)
MODELES = [{"id": m["id"], "nom": m["nom"], "phrase": m["phrase"], "go": m["go"], "role": max(m["notes"], key=m["notes"].get), "avance": bool(m.get("avance")),
            "avertissement": m.get("avertissement", ""), "licence": m["licence"], "capacites": m["capacites"]} for m in _CATALOGUE["modeles"]]
REGLAGES_DEFAUT = {"modele": os.environ.get("LUTIN_MODELE") or "qwen3:8b", "avance": False, "num_ctx": 24576, "temperature": 0.6, "reflexion": False, "auto_ecriture": False, "auto_commandes": False, "mode": "polyvalent", "num_predict": 0, "tours_max": 14, "web": True,
                    "top_p": None, "top_k": None, "min_p": None, "repeat_penalty": None,          # None = valeur conseillée pour la famille du modèle (voir profil_echantillonnage)
                    "garde_ressources": True, "seuil_ram_go": 3.0, "seuil_disque_go": 10.0, "plafond_donnees_go": 2.0, "limite_ram_commande_go": 0.0,
                    "liberer_si_comfy": True, "rappels_auto": "scenario",
                    "num_thread": None, "garde_min": None, "essai_a_blanc": False, "copie_conversations": False, "memoire_longue": "demander"}          # charge de la machine : cœurs du processeur utilisés et minutes de garde du modèle en mémoire (None = automatique)          # rappels_auto : « scenario » (mode scénariste seulement), « toujours » ou « jamais »
CHOIX_RAPPELS = ("scenario", "toujours", "jamais")
BORNES_CHARGE = {"num_thread": (1, 256), "garde_min": (0, 240)}
BORNES_RESSOURCES = {"seuil_ram_go": (0.5, 64.0), "seuil_disque_go": (1.0, 2000.0), "plafond_donnees_go": (0.2, 500.0), "limite_ram_commande_go": (0.0, 256.0)}


def nettoyer_ressources(r):
    """Seuils de surveillance : des nombres dans leurs bornes (valeur par défaut si absurde)."""
    r["garde_ressources"] = bool(r.get("garde_ressources", True))
    r["liberer_si_comfy"] = bool(r.get("liberer_si_comfy", True))
    if r.get("rappels_auto") not in CHOIX_RAPPELS:
        r["rappels_auto"] = "scenario"
    for cle, (bas, haut) in BORNES_RESSOURCES.items():
        try:
            r[cle] = max(bas, min(haut, float(r.get(cle, REGLAGES_DEFAUT[cle]))))
        except (TypeError, ValueError):
            r[cle] = REGLAGES_DEFAUT[cle]
    for cle, (bas, haut) in BORNES_CHARGE.items():          # entiers, ou None = automatique
        v = r.get(cle)
        try:
            r[cle] = None if v in (None, "") else int(max(bas, min(haut, int(float(v)))))
        except (TypeError, ValueError):
            r[cle] = None
    return r
BORNES_ECHANTILLONNAGE = {"top_p": (0.0, 1.0), "top_k": (0, 200), "min_p": (0.0, 1.0), "repeat_penalty": (0.8, 2.0)}


def nettoyer_echantillonnage(r):
    """Chaque paramètre vaut None (automatique) ou un nombre dans ses bornes."""
    for cle, (bas, haut) in BORNES_ECHANTILLONNAGE.items():
        v = r.get(cle)
        if v is None or v == "":
            r[cle] = None
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            r[cle] = None
            continue
        v = max(bas, min(haut, v))
        r[cle] = int(v) if cle == "top_k" else round(v, 3)
    return r


def profil_echantillonnage(modele, reflechit):
    """Réglages d'échantillonnage conseillés par les éditeurs pour la famille du modèle (à vérifier sur la fiche de ton modèle exact) : moins de boucles et de dérives
    qu'avec la température seule. Qwen : réflexion → top_p 0,95 ; sans réflexion → top_p 0,8. Gemma : top_k 64, top_p 0,95."""
    m = str(modele).lower()
    if "qwen" in m:
        return {"top_p": 0.95 if reflechit else 0.8, "top_k": 20, "min_p": 0.0}
    if "gemma" in m:
        return {"top_p": 0.95, "top_k": 64, "min_p": 0.0}
    return {}


def options_modele(r, temperature, **extra):
    """Les options Ollama communes à TOUTES les requêtes au modèle : un seul jeu de valeurs, sinon Ollama recharge le modèle entre deux requêtes (lent, et risque de manquer de mémoire)."""
    options = {"num_ctx": r["num_ctx"], "temperature": temperature}
    if r.get("num_thread"):
        options["num_thread"] = r["num_thread"]
    options.update(extra)
    return options


def options_echantillonnage(r, reflechit):
    """Profil du modèle, puis les valeurs que l'utilisateur a fixées à la main par-dessus."""
    options = profil_echantillonnage(r["modele"], reflechit)
    for cle in BORNES_ECHANTILLONNAGE:
        if r.get(cle) is not None:
            options[cle] = r[cle]
    return options
ENV_OLLAMA = {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0", "OLLAMA_KEEP_ALIVE": "5m"}
TOURS_MAX = 14
GARDE_RESSOURCES_ACTIF = os.environ.get("LUTIN_SANS_GARDE") != "1"          # désactivé dans les tests (qui ne doivent pas dépendre de l'état réel de la machine)
AUTO_DEMARRAGE = os.environ.get("LUTIN_SANS_DEMARRAGE") != "1"          # démarre Ollama tout seul s'il est arrêté au moment d'une demande (désactivé dans les tests)
LECTURE_MAX = 7000
SORTIE_MAX = 9000
def construire_commandes_lecture(posix):
    """Les lectures simples lancées sans accord : git en lecture, echo, et les commandes de lecture du système (dir / type / where sous Windows ; ls / cat / pwd / which ailleurs)."""
    commun = r"git (status|diff|log|show|branch|ls-files)\b[^|&;<>]*|python -V|echo [^|&;<>]*"
    systeme = r"ls\b[^|&;<>]*|cat [^|&;<>]+|pwd|which [^|&;<>]+" if posix else r"dir\b[^|&;<>]*|type [^|&;<>]+|where [^|&;<>]+"
    return re.compile("^(" + commun + "|" + systeme + ")$", re.I)


COMMANDES_LECTURE = construire_commandes_lecture(os.name != "nt")
DOSSIERS_IGNORES = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode", "dist", "build", ".pytest_cache", ".ruff_cache", ".mypy_cache", "target"}
CHEMINS_IGNORES = ()          # chemins précis à sauter (en plus des noms de DOSSIERS_IGNORES)
CHERCHER_DELAI = 25                                              # secondes au plus pour une recherche (gros dossier sur le réseau)
JOURNAL_MAX = 1_000_000


class ErreurOutil(Exception):
    """Une erreur que le modèle doit voir et corriger (chemin refusé, fichier absent...)."""


class Arret(Exception):
    """L'utilisateur a appuyé sur Arrêter (ou a fermé la page) : le tour s'arrête là."""


def journaliser(texte):
    """Trace dans donnees/lutin.log (erreurs d'Ollama, d'outils...) pour pouvoir diagnostiquer après coup. Ne plante jamais."""
    try:
        f = DONNEES / "lutin.log"
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.is_file() and f.stat().st_size > JOURNAL_MAX:
            os.replace(str(f), str(f.with_name("lutin.log.1")))
        with open(f, "a", encoding="utf-8") as fh:
            fh.write("{} {}\n".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), " ".join(str(texte).split())[:1200]))
    except OSError:
        pass


def ignore_chemin(p):
    """Vrai si p (dans le projet) est un dossier technique à sauter (noms ignorés partout, ou chemins précis)."""
    try:
        r = Path(p).resolve().relative_to(RACINE)
    except ValueError:                      # lien qui sort du projet : on ne s'en occupe pas ici (chemin_sur le refusera à la lecture)
        return True
    if any(part in DOSSIERS_IGNORES for part in r.parts):
        return True
    posix = r.as_posix().lower()
    return any(posix == c or posix.startswith(c + "/") for c in CHEMINS_IGNORES)


from .donnees import (  # noqa: F401  (déplacé dans donnees.py : moteur ré-exporte ses noms)
    CACHE_CONV,
    MARQUES_NOTES,
    MARQUE_NOTES,
    RE_CONV,
    RE_DESC_SKILL,
    RE_SKILL,
    _fichier_skill,
    conv_chemin,
    conv_ecrire,
    conv_lire,
    conv_liste,
    conv_nouvelle,
    conv_renommer,
    conv_supprimer,
    description_skill,
    ecrire_atomique,
    ecrire_memoire,
    ecrire_skill,
    enregistrer_reglages,
    lire_json,
    lire_memoire,
    lire_skill,
    lister_skills,
    noter,
    position_notes,
    reparer_conversation,
    supprimer_skill,
    texte_memoire,
)


def reglages():
    r = dict(REGLAGES_DEFAUT)
    brut = lire_json(DONNEES / "reglages.json", {})
    r.update({k: v for k, v in brut.items() if k in REGLAGES_DEFAUT})
    if brut.get("memoire_v") != 2 and r["memoire_longue"] == "resume":
        r["memoire_longue"] = "demander"                                             # avant la 0.6.4, « résumé » n'était qu'une valeur par défaut : on pose maintenant la question au premier résumé
    r["num_ctx"] = max(4096, min(131072, int(r["num_ctx"])))
    r["temperature"] = max(0.0, min(2.0, float(r["temperature"])))
    r["num_predict"] = max(0, min(32768, int(r.get("num_predict", 0))))
    r["tours_max"] = max(4, min(40, int(r.get("tours_max", 14))))
    r["avance"] = bool(r.get("avance"))
    r["essai_a_blanc"] = bool(r.get("essai_a_blanc"))
    return _sec.reglages_surs(SECURITE, nettoyer_ressources(nettoyer_echantillonnage(r)))          # hors niveau « local » : jamais d'accord automatique, quoi que dise le fichier


from .outils import (  # noqa: F401  (déplacé dans outils.py : moteur ré-exporte ses noms)
    Attente,
    EXTENSIONS_BINAIRES,
    OUTILS,
    PURGE,
    RE_HORS_PROJET,
    SAUVEGARDES_JOURS,
    SORTIE_BORNE,
    Tampon,
    VERIFICATION_FAITE,
    chemin_sur,
    commande_lecture_sure,
    construire_hors_projet,
    difference,
    ecrire_et_verifier,
    ecrire_exact,
    jeton_outil,
    lancer_processus,
    limiter_memoire_processus,
    lire_exact,
    lire_flux,
    noter_apres,
    octets_dossier,
    outil_chercher,
    outil_ecrire,
    outil_etat,
    outil_executer,
    outil_installer_module,
    outil_lire,
    outil_lire_plusieurs,
    outil_lister,
    outil_modifier,
    outil_modifier_plusieurs,
    outil_symboles,
    parcourir,
    passage_proche,
    positions_ligne,
    purger_donnees,
    purger_sauvegardes,
    rel,
    remplacer_une_fois,
    repondre_attente,
    sauvegarder,
    sha_fichier,
    tuer_arbre,
    verifier_js,
    verifier_syntaxe,
)


from .web import (  # noqa: F401  (déplacé dans web.py : moteur ré-exporte ses noms)
    AGENT_WEB,
    AVERTISSEMENT_WEB,
    DDG_URL,
    ETATS_TACHE,
    HtmlEnTexte,
    ResultatsDDG,
    SIGNES_TACHE,
    WEB_MAX_OCTETS,
    WEB_PAGE,
    adresse_resultat,
    normaliser_taches,
    outil_taches,
    outil_web_chercher,
    outil_web_lire,
    texte_taches,
    verifier_hote_web,
    web_telecharger,
)


from .plan import (  # noqa: F401  (déplacé dans plan.py : moteur ré-exporte ses noms)
    PLAN,
    PLAN_CACHE,
    PLAN_DELAI,
    PLAN_EXT,
    PLAN_MAX,
    RE_SYM_JS,
    RE_SYM_PY,
    construire_plan,
    rafraichir_plan,
    resume_fichier,
    texte_plan,
)


from .rappel import (  # noqa: F401  (déplacé dans rappel.py : moteur ré-exporte ses noms)
    MOTS_VIDES,
    RAPPEL,
    decouper,
    etiquette_rappel,
    formater_passages,
    indexer_rappel,
    mots,
    outil_rappeler,
    passages_rappel,
    rappels_automatiques,
    sources_rappel,
)


from .sante import (  # noqa: F401  (déplacé dans sante.py : moteur ré-exporte ses noms)
    ALERTES_VUES,
    CACHE_TAILLES,
    GO,
    MARGE_VRAM,
    boucle_surveillance,
    controle_avant_demande,
    dossier_modeles_ollama,
    espace_disque,
    etat_sante,
    evaluer_sante,
    go,
    lancer_autotest,
    memo,
    memoire_video,
    oublier_mesures,
    memoire_vive,
    niveau_seuil,
    surveiller_comfy_une_fois,
    taille_dossier,
    taille_modele,
)


def etat_comfy():
    """ComfyUI tourne-t-il, et est-il en train de générer ? (il se partage la carte graphique avec le modèle de langage)"""
    try:
        with urllib.request.urlopen(os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/") + "/queue", timeout=0.8) as r:
            q = json.loads(r.read().decode("utf-8"))
        return {"actif": True, "en_cours": len(q.get("queue_running") or []), "attente": len(q.get("queue_pending") or [])}
    except (urllib.error.URLError, OSError, ValueError):
        return {"actif": False, "en_cours": 0, "attente": 0}


def mesurer_disques():
    return {"Ollama (modèles)": espace_disque(dossier_modeles_ollama()), "Projet": espace_disque(RACINE), "Données de l'assistant": espace_disque(DONNEES)}


def mesures_systeme():
    """Toutes les mesures brutes d'un coup (séparées de leur interprétation, pour pouvoir tester celle-ci). Les mesures lentes (carte graphique, ComfyUI, disques) se font en parallèle et
    sont gardées quelques secondes (sante.memo) ; la taille du dossier de données se refait en arrière-plan."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        vram, comfy, disques = pool.submit(memo, "vram", memoire_video), pool.submit(memo, "comfy", etat_comfy), pool.submit(memo, "disques", mesurer_disques)
        ram, octets = memoire_vive(), taille_dossier(DONNEES)
        return {"ram": ram, "vram": vram.result(), "comfy": comfy.result(), "disques": disques.result(), "donnees_octets": octets}


from .revue import (  # noqa: F401  (déplacé dans revue.py : moteur ré-exporte ses noms)
    ETATS_GIT,
    _appeler_outil,
    annuler_tour,
    appeler_outil,
    chemins_git,
    chercher_conversations,
    epingler_conversation,
    git_commit,
    git_etat,
    git_message,
    lire_utf8,
    manifeste_annulable,
    retablir_fichier,
    revue_tour,
)


def git(args, delai=60):
    """Lance git dans le projet. Renvoie (code, sortie, erreur).
    « -c safe.directory=* » : sur un partage réseau (NAS), git refuse sinon le dossier (« dubious ownership »). Le réglage ne vaut que pour cet appel, rien n'est écrit dans ta configuration git."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(["git", "-c", "core.quotepath=false", "-c", "safe.directory=*", "-C", str(RACINE)] + args, capture_output=True, timeout=delai, env=env)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


from .dialogue import (  # noqa: F401  (déplacé dans dialogue.py : moteur ré-exporte ses noms)
    CAPACITES,
    OUTILS_WEB,
    PULLS,
    RAPPEL_APPEL,
    RE_APPEL_BALISE,
    RE_APPEL_JSON,
    RE_APPEL_MAL_FORME,
    RE_APPEL_XML,
    RE_CONTEXTE,
    RE_NOM_MODELE,
    RE_PLANTAGE,
    ajuster_contexte,
    avec_garde,
    bloc_plan,
    boucle_agent,
    calculer_vitesse,
    capacites,
    chemin_ollama,
    CHOIX_MEMOIRE,
    a_compacter,
    amorcer_fiche,
    compacter,
    compacter_conversation,
    memoire_longue,
    repondre_choix_memoire,
    consignes_systeme,
    duree_garde,
    ecrire_registre_modeles,
    estimer,
    etat_ollama,
    extraire_appels_texte,
    installer_modele,
    jauge_contexte,
    lire_registre_modeles,
    modele_de_repli,
    modeles_connus,
    ollama_json,
    oublier_modele,
    outils_du_mode,
    ps_modele,
    restaurer_modeles,
    supprimer_modele,
    tour,
)


def liberer_vram():
    """Décharge les modèles chargés en mémoire Ollama (libère la VRAM)."""
    try:
        charges = ollama_json("/api/ps", None, 3).get("models", [])
    except (urllib.error.URLError, OSError, ValueError):
        return {"ok": True, "message": "Ollama inaccessible — rien à faire."}
    if not charges:
        return {"ok": True, "message": "Aucun modèle en mémoire, VRAM déjà libre."}
    decharges = []
    for m in charges:
        nom = m.get("name") or m.get("model", "?")
        try:
            req = urllib.request.Request(
                OLLAMA + "/api/generate",
                data=json.dumps({"model": nom, "prompt": "x", "keep_alive": 0}).encode(),
                method="POST",
            )
            urllib.request.urlopen(req, timeout=60)
            decharges.append(nom)
        except (urllib.error.URLError, OSError) as e:
            decharges.append(_t("{} (échec : {})").format(nom, str(e)[:60]))
    return {"ok": True, "message": _t("Déchargé(s) : {}").format(", ".join(decharges))}


def demarrer_ollama():
    exe = chemin_ollama()
    if not exe:
        raise ValueError("Ollama n'est pas installé : lance installer-assistant.bat.")
    if etat_ollama()["actif"]:
        return "Ollama tourne déjà."
    env = dict(os.environ, **ENV_OLLAMA)
    from . import emplacements
    if emplacements.lire_config_modeles() and not os.environ.get("OLLAMA_MODELS"):
        env["OLLAMA_MODELS"] = emplacements.lire_config_modeles()          # le dossier choisi à l'installation, même si la variable de Windows n'est pas arrivée jusqu'ici
    drapeaux = 0x00000008 | 0x00000200 if os.name == "nt" else 0                 # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([exe, "serve"], env=env, creationflags=drapeaux, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(0.5)
        if etat_ollama()["actif"]:
            return "Ollama démarré."
    raise ValueError("Ollama ne répond pas après 15 secondes.")


def arreter_ollama():
    """Arrête Ollama (le service ou l'icône d'Ollama comprise), à la demande de l'utilisateur : nécessaire pour qu'il relise OLLAMA_MODELS. Renvoie True s'il ne répond plus ensuite."""
    if os.environ.get("LUTIN_DOCKER"):
        raise ValueError(_t("Dans Docker, Ollama se redémarre avec le conteneur."))
    if os.name == "nt":
        for nom in ("ollama.exe", "ollama app.exe"):
            subprocess.run(["taskkill", "/F", "/IM", nom], capture_output=True, timeout=20)
    else:
        subprocess.run(["pkill", "-x", "ollama"], capture_output=True, timeout=20)
    for _ in range(20):
        time.sleep(0.5)
        if not etat_ollama()["actif"]:
            return True
    return False


def redemarrer_ollama():
    """Arrête puis relance Ollama avec le dossier de modèles choisi. Les modèles chargés en mémoire sont perdus (rechargés à la prochaine question)."""
    if TOURS_ACTIFS:
        raise ValueError(_t("Une réponse est en cours : attends sa fin avant de redémarrer Ollama."))
    if not arreter_ollama():
        raise ValueError(_t("Ollama ne s'arrête pas : quitte-le toi-même (icône en bas à droite) puis clique sur « Démarrer Ollama »."))
    return demarrer_ollama()


# --------------------------------------------------------------------------- serveur HTTP
try:
    ICONE_SVG = (WEB / "logo.svg").read_text(encoding="utf-8")
except OSError:
    ICONE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#0b0f14"/>'
                 '<circle cx="50" cy="50" r="38" fill="#5aa9ff" opacity=".18"/><circle cx="50" cy="50" r="27" fill="#5aa9ff"/></svg>')
ICONES = {}


def icone_png(n):
    """Icône carrée n x n : le logo de Lutin (web/icones/icone-n.png). Sans ce fichier : un point lumineux dessiné à la main (PNG fabriqué avec zlib). Gardée en mémoire."""
    if n in ICONES:
        return ICONES[n]
    try:
        ICONES[n] = (WEB / "icones" / "icone-{}.png".format(n)).read_bytes()
        return ICONES[n]
    except OSError:
        pass
    centre, rayon, halo = n / 2, n * 0.27, n * 0.38
    fond, bleu = (11, 15, 20), (90, 169, 255)
    lignes = bytearray()
    for y in range(n):
        lignes.append(0)                                      # filtre « aucun » de la ligne
        dy = y + 0.5 - centre
        for x in range(n):
            d = ((x + 0.5 - centre) ** 2 + dy * dy) ** 0.5
            if d >= halo:
                lignes += bytes(fond)
                continue
            if d <= rayon - 0.7:
                t = 1.0
            elif d <= rayon + 0.7:
                t = (rayon + 0.7 - d) / 1.4
            else:
                t = 0.35 * ((halo - d) / (halo - rayon)) ** 2
            lignes += bytes(int(fond[i] + (bleu[i] - fond[i]) * t) for i in range(3))

    def bloc(genre, donnees):
        return struct.pack(">I", len(donnees)) + genre + donnees + struct.pack(">I", zlib.crc32(genre + donnees) & 0xFFFFFFFF)
    ICONES[n] = b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0)) + bloc(b"IDAT", zlib.compress(bytes(lignes), 9)) + bloc(b"IEND", b"")
    return ICONES[n]


TOURS_SIMULTANES = 2       # au plus deux réponses à la fois (une seule carte graphique : plus, ce serait lent et risqué pour la mémoire)
TOURS_ACTIFS = {}          # id de conversation -> threading.Event « stop » du tour en cours (une conversation = un tour à la fois)
VERROU_TOURS = threading.Lock()
RACINE_TOURS = {}          # id de conversation -> dossier de travail utilisé par sa réponse en cours (une seule racine à la fois, voir activer_travail)
BENCH = {"en_cours": "", "etape": "", "erreur": ""}


# --------------------------------------------------------------------------- dossiers de travail multiples
def chemin_config():
    c = os.environ.get("LUTIN_CONFIG")
    return Path(c) if c else None


def config_lue():
    c = chemin_config()
    return _config.migrer(lire_json(c, {})) if c else _config.migrer({})


def config_ecrire(cfg):
    c = chemin_config()
    if not c:
        raise ValueError("Pas de fichier de configuration.")
    _config.enregistrer({"config": c.parent}, cfg)


def dossiers_de_lutin():
    """Les dossiers de Lutin lui-même : un dossier de travail ne peut ni les contenir ni être dedans."""
    c, cache = chemin_config(), os.environ.get("LUTIN_PROPOSITIONS")
    return [p for p in (c.parent if c else None, DONNEES, MEMOIRE, Path(cache).parent if cache else None) if p]


def definir_racine(chemin):
    """Change le dossier de travail courant. Appelé avec VERROU_TOURS tenu."""
    global RACINE
    nouveau = Path(chemin).resolve()
    if nouveau != RACINE:
        RACINE = nouveau
        PLAN["valide"] = False                      # le plan du projet et l'index de rappel appartiennent à l'ancien dossier
        RAPPEL["signature"] = None


# --------------------------------------------------------------------------- journal des actions (qui a modifié quoi, lancé quelle commande, avec quel accord)
JOURNAL_MAX = 5_000_000
OUTILS_JOURNALISES = {"ecrire", "modifier", "modifier_plusieurs", "executer", "installer_module"}


def chemin_journal():
    return DONNEES / "journal-actions.jsonl"


def noter_action(ctx, outil, args, issue):
    """Une ligne par action qui modifie quelque chose. Jamais le contenu des fichiers ni la sortie des commandes : seulement quoi, où, avec quel accord, pour qui. Ne plante jamais."""
    try:
        cible = ""
        if outil in ("ecrire", "modifier", "modifier_plusieurs"):
            cible = str(args.get("chemin", ""))
        elif outil == "executer":
            cible = str(args.get("commande", ""))
        elif outil == "installer_module":
            cible = str(args.get("module", ""))
        entree = {"ts": datetime.now().isoformat(timespec="seconds"), "conversation": (ctx.get("conv") or {}).get("id", ""), "dossier": str(RACINE), "outil": outil, "cible": cible[:300],
                  "issue": issue[:200], "accord": ctx.pop("dernier_accord", "aucun"), "qui": ctx.get("identite", "")}
        f = chemin_journal()
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.is_file() and f.stat().st_size > JOURNAL_MAX:
            os.replace(str(f), str(f.with_name(f.name + ".1")))
        with open(f, "a", encoding="utf-8") as h:
            h.write(json.dumps(entree, ensure_ascii=False) + "\n")
    except OSError:
        pass


def lire_journal(n=200):
    n = max(1, min(2000, int(n)))
    try:
        lignes = chemin_journal().read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return []
    sortie = []
    for ligne in lignes:
        try:
            sortie.append(json.loads(ligne))
        except ValueError:
            continue
    return sortie[::-1]                                      # la plus récente d'abord


# --------------------------------------------------------------------------- banc d'essai des modèles (vitesse et notes mesurées)
def chemin_bench():
    return Path(os.environ.get("LUTIN_BENCH") or DONNEES / "bench.json")


def lancer_bench(modele, rapide):
    if not RE_NOM_MODELE.match(modele or ""):
        raise ValueError("Nom de modèle invalide.")
    with VERROU_TOURS:
        if TOURS_ACTIFS:
            raise ValueError("Une réponse est en cours : le banc d'essai fausserait les mesures. Attends sa fin.")
        if BENCH["en_cours"]:
            raise ValueError("Un banc d'essai est déjà en cours ({}).".format(BENCH["en_cours"]))
        BENCH.update(en_cours=modele, etape="démarrage", erreur="")

    def travail():
        try:
            from .machine import detecter
            mesure = _bench.executer(_Ollama(OLLAMA), modele, rapide, lambda nom, i, n: BENCH.update(etape="{} ({}/{})".format(nom, i + 1, n)), detecter().resume(), reglages()["num_ctx"])
            _bench.enregistrer(chemin_bench(), mesure)
            if mesure.get("erreur"):
                BENCH["erreur"] = mesure["erreur"]
        except Exception as erreur:  # noqa: BLE001
            BENCH["erreur"] = str(erreur)[:200]
            journaliser("Banc d'essai de {} : {!r}".format(modele, erreur))
        finally:
            BENCH.update(en_cours="", etape="")
    threading.Thread(target=travail, daemon=True, name="banc-essai").start()
    return {"ok": True}


def arreter_conversation(ident):
    """Bouton Arrêter : déclenche le stop du tour en cours (le modèle, les outils et les accords en attente s'arrêtent)."""
    with VERROU_TOURS:
        stop = TOURS_ACTIFS.get(ident)
    if stop is None:
        return {"ok": True, "actif": False}
    stop.set()
    return {"ok": True, "actif": True}


from .espaces import (  # noqa: F401  (déplacé dans espaces.py : moteur ré-exporte ses noms)
    activer_travail,
    ajouter_travail,
    apercu_travail,
    changer_chemin_travail,
    choisir_travail,
    deplacer_travail,
    importer_projet_claude,
    lister_dossiers,
    reprise_detecter,
    reprise_importer,
    retirer_travail,
    travaux_etat,
)

from .serveur import (  # noqa: F401  (déplacé dans serveur.py : moteur ré-exporte ses noms)
    Gestionnaire,
)


def ip_locale():
    """Adresse IP du réseau local (pour ouvrir l'assistant depuis un téléphone/tablette)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # aucune donnée envoyée : juste pour connaître l'interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


CLES_TEXTE_UI = {"erreur", "raison", "message", "nom", "valeur", "conseil", "detail", "phrase", "avertissement", "etape", "ancien_nom"}          # textes écrits par Lutin (jamais le contenu des conversations ni des fichiers)


def nouvelle_version_lutin():
    """La version de Lutin annoncée par la vérification au lancement (un fichier du cache, jamais le réseau) ; None s'il n'y en a pas de nouvelle ou si tu l'as ignorée."""
    chemin = os.environ.get("LUTIN_VERSION_CACHE")
    if not chemin:
        return None
    from . import miseajour
    return miseajour.nouvelle_version(chemin, VERSION)


def page_web():
    """La page d'accueil, avec le jeton, la version, la langue et (en anglais) le dictionnaire de l'interface."""
    langue = _i18n.langue()
    dico = _i18n.dico("interface") if langue != "fr" else {}
    donnees = json.dumps(dico, ensure_ascii=False).replace("</", "<\\/")          # une chaîne ne doit pas pouvoir fermer la balise <script>
    page = (WEB / "index.html").read_text(encoding="utf-8")
    return page.replace("__TOKEN__", JETON).replace("__VERSION__", VERSION).replace("__LANGUE__", langue).replace("__DICO__", donnees)


def traduire_json(objet, cle=""):
    """Traduit, dans une réponse JSON, les textes que Lutin a écrits lui-même (messages d'erreur, mesures de santé, descriptions de modèles…) quand la langue n'est pas le français."""
    if isinstance(objet, dict):
        return {k: traduire_json(v, k) for k, v in objet.items()}
    if isinstance(objet, list):
        return [traduire_json(v, cle) for v in objet]
    if isinstance(objet, str) and cle in CLES_TEXTE_UI:
        return _tr(objet)
    return objet


def traduire_evenement(e):
    """Évènements du flux de réponse : seuls les messages de Lutin (info, erreur, accord, état) sont traduits, jamais le texte du modèle."""
    if not isinstance(e, dict) or e.get("type") not in ("info", "erreur", "approbation", "etat") or _i18n.langue() == "fr":
        return e
    return dict(e, **{k: _tr(e[k]) for k in ("texte", "titre") if isinstance(e.get(k), str)})


def lire_propositions():
    """Nouveautés de modèles trouvées par la vérification au lancement (voir lutin.miseajour) : un fichier du cache, jamais le réseau."""
    chemin = os.environ.get("LUTIN_PROPOSITIONS")
    d = lire_json(Path(chemin), None) if chemin else None
    return d if isinstance(d, dict) else {"propositions": [], "erreurs": [], "date": 0}


def traiter_proposition(cle, appliquer):
    """« Ne plus proposer » (appliquer=False) ou « installé : c'est maintenant mon modèle pour ce rôle » (appliquer=True). Les deux retirent la proposition de la liste."""
    config_f = os.environ.get("LUTIN_CONFIG")
    prop = next((p for p in lire_propositions().get("propositions", []) if p.get("cle") == cle), None)
    if not config_f or not prop:
        raise ValueError("Proposition introuvable.")
    cfg = lire_json(Path(config_f), {})
    modeles = cfg.setdefault("modeles", {})
    modeles.setdefault("ignores", [])
    if cle not in modeles["ignores"] and not (appliquer and prop.get("type") == "maj"):          # une mise à jour installée ne doit pas faire taire les suivantes
        modeles["ignores"].append(cle)
    if appliquer and prop.get("role"):
        modeles.setdefault("choisis", {})[prop["role"]] = prop["modele"]
    ecrire_atomique(Path(config_f), json.dumps(cfg, ensure_ascii=False, indent=1))
    chemin = os.environ.get("LUTIN_PROPOSITIONS")
    if chemin:
        d = lire_propositions()
        d["propositions"] = [p for p in d.get("propositions", []) if p.get("cle") != cle]
        ecrire_atomique(Path(chemin), json.dumps(d, ensure_ascii=False, indent=1))
    return {"ok": True}


ADRESSES_LOCALES = ("127.0.0.1", "localhost", "::1")


def ecouter_aussi_en_local(hote):
    """Au niveau réseau (ou proxy distant) le serveur se lie à l'adresse du réseau local seulement : 127.0.0.1 ne répondrait plus, donc ni l'icône de la zone de notification ni
    `lutin pin` / `lutin chat` ne pourraient joindre le serveur de leur propre machine. On ouvre alors aussi 127.0.0.1 (même port, même protection). Renvoie ce second serveur, ou None."""
    if hote in ADRESSES_LOCALES or hote in ("0.0.0.0", "", "::"):
        return None
    try:
        local = ThreadingHTTPServer(("127.0.0.1", PORT), Gestionnaire)
    except OSError as erreur:
        journaliser("Impossible d'écouter aussi sur 127.0.0.1:{} : {!r}".format(PORT, erreur))
        return None
    threading.Thread(target=local.serve_forever, daemon=True, name="ecoute-locale").start()
    return local


def ecrire_fichier_console(hote):
    """Adresse et jeton de la console locale (lutin chat) : un fichier que seul l'utilisateur de cette machine peut lire."""
    f = DONNEES / "console.json"
    ecrire_atomique(f, json.dumps({"adresse": "http://{}:{}".format("127.0.0.1" if hote in ("0.0.0.0", "") else hote, PORT), "jeton": JETON_CONSOLE, "pid": os.getpid()}))
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


TEXTES_PAGE_CONNEXION = ("Lutin : connexion", "Entre le code à 6 chiffres affiché sur l'ordinateur qui fait tourner Lutin (commande <code>lutin pin</code> pour en obtenir un nouveau).",
                         "Nom de cet appareil (facultatif)", "Se connecter", "Erreur ")
PAGE_CONNEXION = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Lutin : connexion</title>
<style>body{font-family:system-ui,sans-serif;background:#0b0f14;color:#e6edf3;display:grid;place-items:center;min-height:100vh;margin:0}main{max-width:340px;padding:24px}
input,button{font:inherit;padding:10px 12px;border-radius:8px;border:1px solid #30363d;background:#161b22;color:inherit;width:100%;box-sizing:border-box;margin-top:10px}
button{background:#238636;border-color:#238636;cursor:pointer}#m{color:#f85149;min-height:1.4em;margin-top:8px}</style></head><body><main>
<img src="/logo.svg" alt="" width="72" height="72" style="display:block;margin:0 auto 6px"><h1 style="text-align:center">Lutin</h1><p>Entre le code à 6 chiffres affiché sur l'ordinateur qui fait tourner Lutin (commande <code>lutin pin</code> pour en obtenir un nouveau).</p>
<form id="f"><input id="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="000000" autofocus><input id="nom" placeholder="Nom de cet appareil (facultatif)"><button>Se connecter</button></form><div id="m"></div>
<script>document.getElementById('f').addEventListener('submit',async e=>{e.preventDefault();const r=await fetch('/api/appairer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:document.getElementById('pin').value,nom:document.getElementById('nom').value})});
const d=await r.json().catch(()=>({}));if(r.ok)location.reload();else document.getElementById('m').textContent=d.erreur||'Erreur '+r.status;});
const q=(location.hash.match(/pin=([0-9]{6})/)||[])[1];if(q){document.getElementById('pin').value=q;document.getElementById('nom').value=document.getElementById('nom').value;history.replaceState(null,'',location.pathname);document.querySelector('#f button').click();}</script></main></body></html>"""


def principal():
    for d in (DONNEES, MEMOIRE):
        d.mkdir(parents=True, exist_ok=True)
    sys.excepthook = lambda genre, valeur, trace: (journaliser("Exception non gérée : {!r}".format(valeur)), sys.__excepthook__(genre, valeur, trace))
    threading.excepthook = lambda a: journaliser("Exception dans un thread ({}) : {!r}".format(a.thread.name if a.thread else "?", a.exc_value))
    purger_sauvegardes()
    try:
        purger_donnees()
    except OSError as erreur:
        journaliser("Purge impossible : {!r}".format(erreur))
    rafraichir_plan(force=True)
    threading.Thread(target=boucle_surveillance, daemon=True).start()
    from . import planifie
    planifie.demarrer()
    from . import addons
    addons.demarrer_actifs()
    journaliser("Démarrage de Lutin (version {}, dossier de travail {}).".format(VERSION, RACINE))
    global IP_LAN
    problemes = SECURITE.valider()
    if problemes:
        raise SystemExit(_t("Configuration de sécurité invalide : {}").format(" ; ".join(problemes)))
    IP_LAN = ip_locale() if SECURITE.niveau != _sec.LOCAL else ""
    hote = _sec.adresse_ecoute(SECURITE, IP_LAN)
    serveur = ThreadingHTTPServer((hote, PORT), Gestionnaire)
    boucle_locale = ecouter_aussi_en_local(hote)
    en_local = boucle_locale is not None or hote in ADRESSES_LOCALES
    ecrire_fichier_console("127.0.0.1" if en_local else hote)          # la console de cette machine (lutin pin, lutin chat, l'icône) passe toujours par 127.0.0.1
    adresse = "http://{}:{}".format("127.0.0.1" if en_local or hote in ("0.0.0.0", "") else hote, PORT)
    print(_t("Lutin        : {}   (niveau de sécurité : {})").format(adresse, SECURITE.niveau))
    pin = ""
    if SECURITE.niveau == _sec.RESEAU:
        pin = APPAREILS.nouveau_pin()
        print(_t("Code PIN     : {}   (valable {} min ; pour appairer un appareil)").format(pin, _sec.DUREE_PIN_S // 60))
    if SECURITE.niveau == _sec.PROXY:
        print(_t("Adresse publique : {}   (proxy de confiance : {})").format(SECURITE.url_publique, ", ".join(SECURITE.proxy_ips)))
    print(_t("Journal      : {}").format(DONNEES / "lutin.log"))
    print(_t("(dossier de travail : {})").format(RACINE))
    if "--sans-navigateur" not in sys.argv and not os.environ.get("LUTIN_SANS_NAVIGATEUR"):
        try:
            import webbrowser
            threading.Timer(1.0, lambda: webbrowser.open(adresse + ("/#pin=" + pin if pin else ""))).start()          # au niveau réseau, le navigateur de cette machine s'appaire tout seul avec ce code
        except Exception:  # noqa: BLE001
            pass
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    principal()
