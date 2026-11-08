"""Le dialogue avec Ollama : démarrage et état d'Ollama, requêtes au modèle, boucle de l'agent (tours d'outils), résumé des conversations, titres. L'état reste dans moteur (« _m.NOM »)."""
from pathlib import Path
from . import archive as _archive
from . import infos_modele as _infos
from . import affirmations as _affirmations
from . import boucles as _boucles
from . import observatoire as _observatoire
from . import routeur as _routeur
from . import actualites as _actualites
from . import mcp as _mcp
from . import moteur_llamacpp as _llamacpp
from . import moteurs as _moteurs
from . import ollama_client
from . import fichiers as _fichiers
from . import mission as _mission
from . import horsligne as _hl
from . import images as _images
from . import modes as _modes
from . import pieces as _pieces
from . import suivi as _suivi
from . import projet_claude as _pc
from .i18n import t as _t
from datetime import datetime
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
from . import moteur as _m


# --------------------------------------------------------------------------- dialogue avec Ollama
RE_APPEL_MAL_FORME = re.compile(r"XML|syntax|parse|parsing|tool", re.I)


RAPPEL_VIDE = "Ta dernière réponse était vide. Réponds maintenant à la demande de l'utilisateur, en t'appuyant sur ce que tu viens de lire ou de faire, ou appelle l'outil nécessaire."
RAPPEL_REPETITION = "Ta réflexion tournait en rond (les mêmes phrases revenaient). Ne réfléchis plus : réponds maintenant directement et brièvement à la demande de l'utilisateur."
RAPPEL_APPEL = "Ton dernier appel d'outil était mal formé et a été rejeté. Recommence en appelant l'outil avec des arguments simples ; pour un long contenu, fais plusieurs petits appels."


RE_PLANTAGE = re.compile(r"llama-server|out.of.memory|cudaMalloc|exit status|terminated|runner|connection (reset|refused)|unexpectedly", re.I)      # Ollama a planté ou manque de mémoire vidéo : on réessaie avec moins de contexte


CAPACITES = {}          # modèle -> capacités annoncées par Ollama (« tools », « thinking »...), gardées en mémoire


RE_APPEL_BALISE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


RE_APPEL_XML = re.compile(r"<function=([A-Za-z_]+)>(.*?)</function>", re.S)


RE_APPEL_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```|^\s*(\{\s*\"name\".*\})\s*$", re.S)


OUTILS_WEB = {"web_chercher", "web_lire"}
OUTILS_INTERNES = OUTILS_WEB          # outils dont le résultat n'est lu que par le modèle (jamais recopié dans la conversation)


def modele_annexe(r):
    """Le modèle des petites tâches qui ne demandent pas de réfléchir (mise à jour de la fiche, résumés, titres) : celui choisi dans Réglages s'il est installé, sinon le modèle de la conversation.
    Un petit modèle y est plus rapide, mais deux modèles chargés demandent de la mémoire (et Ollama en recharge un à chaque changement si OLLAMA_MAX_LOADED_MODELS vaut 1) : c'est un choix, jamais un défaut."""
    choisi = str(r.get("modele_annexe") or "").strip()
    if choisi and choisi != r["modele"]:
        try:
            if choisi in etat_moteur()["installes"]:
                return choisi
        except (KeyError, OSError, ValueError):
            pass
    return r["modele"]


AVERTIS_CARTE = {}                  # modèle -> instant du dernier avertissement « il ne tient pas sur la carte graphique »
DELAI_AVERTISSEMENT_CARTE = 1800    # secondes : une fois par modèle et par demi-heure, pas à chaque réponse


def a_une_carte_graphique():
    """Faux sur une machine sans carte graphique utilisable : tout tourne sur le processeur, c'est connu, inutile de le répéter à chaque réponse. Vrai si on ne sait pas encore."""
    from . import adequation
    profil = adequation.profil_pret()
    return profil is None or not profil.sans_gpu()


def _estimer_avant_charge(r, emit):
    """Avant de charger le modèle : s'il ne tient pas (ou à peine), le dire et proposer quoi faire, une fois par modèle et par demi-heure. Ne bloque rien (le garde-fou des ressources s'en charge)."""
    try:
        from . import adequation, estimation
        m = next((x for x in _m._CATALOGUE["modeles"] if x["id"] == r["modele"]), None)
        profil = adequation.profil_pret()
        if m is None or profil is None or moteur_actuel(r).en_memoire(r["modele"]):
            return
        e = estimation.estimer(m, int(r["num_ctx"]), profil)
        if e["niveau"] in ("trop_gros", "sature") and _avertir_une_fois("estimation:" + r["modele"]):
            emit({"type": "info", "texte": "⚠ " + e["texte"] + (" " + " ".join(e["conseils"]) if e["conseils"] else "")})
    except Exception:  # noqa: BLE001  (une estimation ratée ne doit jamais empêcher de répondre)
        pass


def _avertir_une_fois(modele, maintenant=time.time):
    t = maintenant()
    if t - AVERTIS_CARTE.get(modele, 0) < DELAI_AVERTISSEMENT_CARTE:
        return False
    AVERTIS_CARTE[modele] = t
    return True


def memoire_longue(conv, r):
    """Comment cette conversation garde son fil : « resume » (le début est résumé par le modèle), « fichier » (fiche de suivi) ou « demander » (on pose la question au premier résumé).
    Le choix de la conversation l'emporte sur le réglage général."""
    choix = (conv or {}).get("memoire_longue") or r.get("memoire_longue") or "demander"
    return choix if choix in ("resume", "fichier", "demander") else "demander"


CHOIX_MEMOIRE = {}                  # conversation -> {"evenement", "choix", "garder"} : la question « fiche de suivi ou résumé ? » en attente de réponse
ATTENTE_CHOIX = 300                 # secondes avant de prendre le résumé automatique (page fermée, téléphone verrouillé)


def reformuler_recherche(texte, r):
    """La demande de l'utilisateur transformée en requête de recherche web (3 à 8 mots-clés, fautes corrigées) par un appel court au modèle des petites tâches. '' si le modèle ne répond pas : l'appelant nettoie alors la demande lui-même."""
    try:
        rep = moteur_actuel(r).chat({"model": modele_annexe(r), "stream": False, "think": False, "options": _m.options_modele(r, 0.1),
                                     "messages": [{"role": "system", "content": "Tu transformes une demande en requête pour un moteur de recherche web. Réponds par la requête seulement : 3 à 8 mots-clés, sans phrase, sans ponctuation, sans date, fautes corrigées, dans la langue de la demande. Garde le sujet précis demandé."},
                                                  {"role": "user", "content": str(texte)[:300]}]}, 30)
        return (rep.get("message", {}).get("content") or "").strip()
    except (urllib.error.URLError, OSError, ValueError):
        return ""


def a_compacter(conv, r):
    """Vrai quand la conversation approche de la taille du contexte : c'est le moment où le résumé automatique se déclencherait."""
    msgs = conv["messages"]
    return not (estimer(msgs) + len(conv.get("resume", "")) // 3 < int(r["num_ctx"] * 0.6) or len(msgs) < 8)


def repondre_choix_memoire(ident, choix, garder):
    """La réponse de la page à la question : renvoie False s'il n'y a pas de question en attente pour cette conversation."""
    if choix not in ("resume", "fichier"):
        raise ValueError(_t("Mémoire des longues conversations inconnue (resume ou fichier)."))
    attente = CHOIX_MEMOIRE.get(str(ident))
    if not attente:
        return False
    attente["choix"], attente["garder"] = choix, bool(garder)
    attente["evenement"].set()
    return True


SCRIBE_MESSAGES = 6                  # le scribe passe toutes les trois réponses environ (six messages)
SCRIBE_AJOUTS_MAX = 4               # lignes ajoutées au plus par section et par passage : un modèle bavard ne peut pas inonder la fiche


SCRIBE_LOT = 7000                    # caractères d'échanges donnés au scribe en un appel
SCRIBE_LOTS_MAX = 3                  # appels au plus par passage (tour normal) ; un retrait demandé (/compact) en fait davantage : rien ne doit disparaître sans être passé dans la fiche
SCRIBE_LOTS_MAX_FORCE = 8


def messages_non_lus(conv, fin=None):
    """Les messages (rang, message) que le scribe n'a pas encore lus, avant le rang « fin » : du texte seulement (ni outils, ni blocs système comme « [Résumé »)."""
    msgs = conv["messages"]
    deja = int(conv.get("scribe_a") or 0)
    if deja > len(msgs):
        deja = 0
    fin = len(msgs) if fin is None else min(fin, len(msgs))
    return [(i, m) for i, m in enumerate(msgs[:fin]) if i >= deja and m.get("role") in ("user", "assistant") and (m.get("content") or "").strip() and not str(m["content"]).startswith("[")]


def scribe(conv, r, emit=None, jusqua=None, forcer=False):
    """Met la fiche à jour d'après les derniers échanges, par des appels courts et SÉPARÉS au modèle : la fiche ne dépend plus de la bonne volonté du modèle qui répond (il oublie souvent l'outil « suivi »).
    Les consignes sont contrôlées (clés connues, lignes courtes, pas de doublon, aucune décision retirée). Renvoie le nombre de lignes écrites ; 0 si rien à faire ou si l'appel a échoué.
    Les échanges sont lus par lots : rien n'est sauté quand il y en a beaucoup (le rang lu n'avance que de ce qui l'a vraiment été).
    jusqua : ne lit pas au-delà de ce rang ; forcer : même un seul message est lu (avant un retrait demandé, où tout ce qui sort doit être passé dans la fiche)."""
    ident = conv.get("id")
    nouveaux = messages_non_lus(conv, jusqua)
    if len(nouveaux) < (1 if forcer else SCRIBE_MESSAGES):
        return 0
    if emit:
        emit({"type": "etat", "texte": _t("Mise à jour de la fiche de suivi…")})
    lots, courant, taille = [], [], 0
    for i, m in nouveaux:
        ligne = "[{}] {}".format("moi" if m["role"] == "user" else "assistant", " ".join(m["content"].split())[:900])
        if courant and taille + len(ligne) > SCRIBE_LOT:
            lots.append(courant)
            courant, taille = [], 0
        courant.append((i, ligne))
        taille += len(ligne) + 1
    lots.append(courant)
    total, tous = 0, True
    for lot in lots[:SCRIBE_LOTS_MAX_FORCE if forcer else SCRIBE_LOTS_MAX]:
        n = _scribe_lot(conv, r, ident, "\n".join(ligne for _, ligne in lot))
        if n is None:
            tous = False
            break
        total += n
        conv["scribe_a"] = lot[-1][0] + 1
    else:
        tous = len(lots) <= (SCRIBE_LOTS_MAX_FORCE if forcer else SCRIBE_LOTS_MAX)
    if tous:                                                                    # tout ce qui était à lire l'a été : les messages sans texte qui suivent (outils) n'ont rien à apporter
        conv["scribe_a"] = len(conv["messages"]) if jusqua is None else max(int(conv.get("scribe_a") or 0), min(jusqua, len(conv["messages"])))
    return total


def _scribe_lot(conv, r, ident, echange):
    """Un appel au modèle pour un lot d'échanges ; renvoie le nombre de lignes écrites, ou None si l'appel a échoué (le lot sera relu au prochain passage)."""
    sections = _suivi.lire(ident)
    consigne = ("Tu tiens la fiche de suivi d'une conversation. On te donne la fiche actuelle et les derniers échanges. Réponds en JSON avec ces clés (listes de phrases courtes, 150 caractères au plus) : "
                "objectif (seulement si le but a changé ou vient d'être dit), plan (seulement si un plan vient d'être décidé ou modifié), etape (l'étape en cours maintenant), decisions (NOUVELLES décisions prises), "
                "fait (ce qui vient d'être terminé), ouvert (NOUVELLES questions restées sans réponse), resolu (questions de la fiche qui ont maintenant une réponse, recopiées telles quelles). "
                "N'invente rien : ne note que ce qui est dit dans les échanges. Liste vide si rien à ajouter.")
    try:
        corps_scribe = {"model": modele_annexe(r), "stream": False, "think": False, "format": "json", "options": _m.options_modele(r, 0.1),
                        "messages": [{"role": "system", "content": consigne}, {"role": "user", "content": "FICHE ACTUELLE :\n" + _suivi.serialiser(ident, sections) + "\n\nDERNIERS ÉCHANGES :\n" + echange}]}
        with _m.tache_de_fond("fiche:" + str(ident), _t("Mise à jour de la fiche de suivi")):          # montré dans la barre d'état de la page
            rep = moteur_actuel(r).chat(corps_scribe, 300)
        ops = json.loads((rep.get("message", {}).get("content") or "{}").strip() or "{}")
    except (urllib.error.URLError, OSError, ValueError) as erreur:
        _m.journaliser("Scribe : fiche non mise à jour (conversation {}) : {!r}".format(ident, erreur))
        return None
    if not isinstance(ops, dict):
        return 0

    def lignes(cle):
        v = ops.get(cle)
        v = v if isinstance(v, list) else ([v] if v else [])
        return [x for x in (_suivi.nettoyer_ligne(str(i)) for i in v if i) if x]
    n = 0
    try:
        for cle in ("objectif", "plan", "etape"):                                      # remplacés seulement si le modèle a quelque chose à dire
            nouveau = lignes(cle)[:LIGNES_REMPLACEES.get(cle, 3)]
            if nouveau and nouveau != sections[cle]:
                _suivi.modifier(ident, cle, "\n".join(nouveau), "remplacer")
                n += len(nouveau)
        for cle in ("decisions", "fait", "ouvert"):                                   # ajoutés sans doublon
            existantes = {x.lower() for x in sections[cle]}
            neuves = [x for x in lignes(cle) if x.lower() not in existantes][:SCRIBE_AJOUTS_MAX]
            if neuves:
                _suivi.modifier(ident, cle, "\n".join(neuves), "ajouter")
                n += len(neuves)
        for question in lignes("resolu")[:SCRIBE_AJOUTS_MAX]:                         # une question ouverte n'est retirée que si le modèle la recopie vraiment (jamais une décision)
            if len(question) >= 12 and any(question.lower() in x.lower() for x in sections["ouvert"]):
                _suivi.modifier(ident, "ouvert", question, "retirer")
    except (ValueError, _m.ErreurOutil) as erreur:
        _m.journaliser("Scribe : consigne refusée (conversation {}) : {!r}".format(ident, erreur))
    return n


LIGNES_REMPLACEES = {"objectif": 3, "plan": 12, "etape": 3}


def demander_memoire(conv, r, emit, stop):
    """Au premier résumé automatique, laisse choisir : fiche de suivi (garde mieux le fil, coûte un peu de contexte à chaque réponse) ou résumé (perd des détails).
    Case « garder pour cette conversation » : sinon la question revient au résumé suivant. Sans réponse, résumé automatique pour cette fois. Renvoie « resume » ou « fichier »."""
    ident = conv["id"]
    attente = {"evenement": threading.Event(), "choix": None, "garder": False}
    CHOIX_MEMOIRE[ident] = attente
    try:
        emit({"type": "choix_memoire", "conversation": ident})
        fin = time.time() + ATTENTE_CHOIX
        while time.time() < fin and not stop.is_set() and not attente["evenement"].wait(0.4):
            pass
    finally:
        CHOIX_MEMOIRE.pop(ident, None)
    if stop.is_set():
        raise _m.Arret()
    if attente["choix"] is None:
        emit({"type": "info", "texte": _t("Pas de réponse : résumé automatique cette fois (la question sera reposée).")})
        return "resume"
    if attente["garder"]:
        conv["memoire_longue"] = attente["choix"]
        _m.conv_ecrire(conv)
    return attente["choix"]


def amorcer_fiche(conv, r, emit=None):
    """Remplit une fiche de suivi vide à partir du début de la conversation (un appel au modèle, comme le résumé). Les détails restent retrouvables avec « rappeler ».
    Renvoie le nombre de lignes écrites ; 0 si la fiche n'était pas vide ou si l'appel a échoué (la conversation n'en souffre pas : la fiche se remplira ensuite)."""
    ident = conv.get("id")
    try:
        if any(_suivi.lire(ident).values()):
            return 0
    except ValueError:
        return 0
    msgs = conv["messages"]
    coupe = max((i for i, m in enumerate(msgs) if m["role"] == "user"), default=0)
    ancien = msgs[:coupe]
    if len(ancien) < 2 and not conv.get("resume"):
        return 0
    texte = "\n".join("[{}] {}".format(m["role"], (m.get("content") or "")[:1200]) for m in ancien if m.get("role") in ("user", "assistant") and m.get("content"))
    texte = (("[Résumé précédent] " + conv["resume"] + "\n") if conv.get("resume") else "") + texte[-int(r["num_ctx"] * 1.5):]
    if emit:
        emit({"type": "info", "texte": _t("Fiche de suivi : préparation à partir du début de la conversation…")})
    try:
        rep = moteur_actuel(r).chat({"model": modele_annexe(r), "stream": False, "think": False, "format": "json", "options": _m.options_modele(r, 0.1),
                                        "messages": [{"role": "system", "content": "Tu remplis la fiche de suivi d'une conversation pour pouvoir la continuer. Réponds en JSON avec ces clés (listes de phrases courtes, 150 caractères au plus chacune) : "
                                                      "objectif, decisions, plan, etape (l'étape en cours), fait, ouvert (questions ouvertes), fichiers. N'invente rien : laisse une liste vide si tu ne sais pas. En français."},
                                                     {"role": "user", "content": texte}]}, 600)
        donnees = json.loads((rep.get("message", {}).get("content") or "{}").strip() or "{}")
    except (urllib.error.URLError, OSError, ValueError) as erreur:
        _m.journaliser("Fiche de suivi non amorcée (conversation {}) : {!r}".format(ident, erreur))
        return 0
    n = 0
    for cle in _suivi.CLES:
        valeur = donnees.get(cle) if isinstance(donnees, dict) else None
        lignes = [str(x) for x in (valeur if isinstance(valeur, list) else [valeur]) if x and str(x).strip()]
        if lignes:
            try:
                _suivi.modifier(ident, cle, "\n".join(lignes), "remplacer")
                n += len(lignes)
            except (ValueError, _m.ErreurOutil):
                continue
    return n


def outils_du_mode(r):
    """Les outils envoyés au modèle : ceux du mode (voir modes.py), sans web si la case « Web » est décochée ou en mode hors ligne, sans l'outil d'images s'il n'est pas branché."""
    exclus = _modes.outils_exclus(r.get("mode"), [t["function"]["name"] for t in _m.OUTILS])
    if not r.get("web", True) or _hl.actif():
        exclus |= OUTILS_WEB
    if not _m.OUTIL:
        exclus |= _modes.IMAGES
    if r.get("memoire_longue") != "fichier":
        exclus.add("suivi")                                             # sans fiche de suivi, l'outil n'a pas de sens
    if not r.get("_mission"):
        exclus |= {"mission_terminer", "mission_bloquee"}               # ces deux outils n'existent que pendant une mission longue
    from . import addons
    if not addons.actif("comfyui"):
        exclus |= {"comfy_modeles", "comfy_generer"}                    # les outils de ComfyUI n'existent que si l'addon est activé
    if not addons.actif("voicestudio"):
        exclus |= {"voix_liste", "voix_parler", "voix_transcrire", "voix_cloner"}          # idem pour les outils de voix
    outils = [t for t in _m.OUTILS if t["function"]["name"] not in exclus]
    if not _modes.sans_outils(r.get("mode")):
        try:
            outils += _mcp.outils_exposes(_modes.lecture_seule(r.get("mode")))          # connecteurs MCP : seulement les outils autorisés un par un (voir mcp.py)
        except Exception as erreur:  # noqa: BLE001  (un connecteur en panne ne doit pas empêcher de répondre)
            _m.journaliser("Connecteurs MCP : liste impossible ({!r}).".format(erreur))
    if any(t["function"]["name"] == "comfy_generer" for t in outils):
        try:
            from . import addons_comfyui
            outils = [addons_comfyui.adapter_outil(t) if t["function"]["name"] == "comfy_generer" else t for t in outils]
        except Exception as erreur:  # noqa: BLE001  (l'outil reste utilisable avec sa description générale)
            _m.journaliser("Outil d'images : description adaptée impossible ({!r}).".format(erreur))
    return outils


def _compact(texte):
    return re.sub(r"\s+", " ", str(texte or ""))


def extraire_appels_texte(contenu, autorises=None, sources=""):
    """Certains modèles écrivent leur appel d'outil dans la réponse (<tool_call>{...}</tool_call>, <function=nom><parameter=...>, ou un bloc JSON seul)
    au lieu d'utiliser le mécanisme prévu : on le retrouve pour l'exécuter. Renvoie (appels, texte sans les appels).
    `sources` : ce que le modèle vient de lire (résultats d'outils, documents joints). Un bloc d'appel qui s'y trouve mot pour mot est une CITATION (un document piégé qui contient un faux appel d'outil) : il n'est jamais exécuté."""
    noms = set(autorises) if autorises is not None else {t["function"]["name"] for t in _m.OUTILS}
    appels, morceaux = [], []
    lu = _compact(sources)

    def cite(brut):
        return bool(lu) and _compact(brut) in lu

    def ajouter(nom, args, span):
        if nom in noms:
            appels.append({"function": {"name": nom, "arguments": args}})
            morceaux.append(span)
    for m in RE_APPEL_BALISE.finditer(contenu):
        if cite(m.group(0)) or cite(m.group(1)):
            continue
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(d, dict):
            ajouter(d.get("name"), d.get("arguments", d.get("parameters", {})), m.span())
    for m in RE_APPEL_XML.finditer(contenu):
        if cite(m.group(0)):
            continue
        ajouter(m.group(1), dict(re.findall(r"<parameter=([A-Za-z_]+)>\s*(.*?)\s*</parameter>", m.group(2), re.S)), m.span())
    if not appels:                      # un bloc JSON n'est un appel que s'il est (presque) toute la réponse : un exemple cité dans une explication ne doit pas s'exécuter
        for m in RE_APPEL_JSON.finditer(contenu):
            brut = m.group(1) or m.group(2)
            if cite(brut):
                continue
            try:
                d = json.loads(brut)
            except ValueError:
                continue
            if isinstance(d, dict) and ("arguments" in d or "parameters" in d) and len(contenu) - (m.end() - m.start()) < 60:
                ajouter(d.get("name"), d.get("arguments", d.get("parameters", {})), m.span())
    net = contenu
    for debut, fin in sorted(morceaux, reverse=True):
        net = net[:debut] + net[fin:]
    return appels, re.sub(r"</?tool_call>", "", net).strip()


def modele_qui_voit(courant):
    """Un modèle déjà installé qui comprend les images (rôle « vision » du catalogue d'abord), ou None."""
    installes = etat_moteur()["installes"]
    candidats = [m["id"] for m in _m.MODELES if m["id"] in installes and "vision" in (m.get("capacites") or [])]
    candidats.sort(key=lambda i: next((0 for m in _m.MODELES if m["id"] == i and m["role"] == "vision"), 1))
    return next((i for i in candidats if i != courant), None)


def modele_de_repli(courant, genre):
    """Un autre modèle déjà installé, pour dépanner quand le modèle courant échoue : un modèle rapide pour les appels d'outils ratés, un plus léger pour les plantages."""
    installes = etat_moteur()["installes"]
    ordre = ("rapide", "leger") if genre == "outil" else ("leger", "rapide")
    for role in ordre:
        for m in _m.MODELES:
            if m["role"] == role and m["id"] != courant and m["id"] in installes:
                return m["id"]
    return None


def capacites_ollama(modele):
    """Ce que le modèle sait faire d'après Ollama (/api/show). None si Ollama ne le dit pas (ancienne version) ou ne répond pas."""
    if modele in CAPACITES:
        return CAPACITES[modele]
    try:
        caps = ollama_json("/api/show", {"model": modele}, 5).get("capabilities")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if isinstance(caps, list):
        CAPACITES[modele] = set(caps)
        return CAPACITES[modele]
    return None


def duree_garde():
    """Combien de temps Ollama garde le modèle en mémoire après une réponse. Avec « Décharger le modèle quand ComfyUI génère », on peut le garder longtemps (pas de rechargement
    de 30 s à 2 min entre deux questions) : la surveillance le décharge d'elle-même dès que ComfyUI a besoin de la carte. Sinon, le réglage d'Ollama (5 minutes)."""
    r = _m.reglages()
    if r.get("garde_min") is not None:
        return "{}m".format(r["garde_min"])          # réglé à la main : 0 = déchargé dès la fin de la réponse
    return "30m" if r.get("liberer_si_comfy", True) else None


def avec_garde(corps):
    """Ajoute la durée de garde du modèle à une requête /api/chat (sinon Ollama remet son délai par défaut de 5 minutes à chaque requête)."""
    ka = duree_garde() if isinstance(corps, dict) and "keep_alive" not in corps else None
    return dict(corps, keep_alive=ka) if ka else corps


def ollama_json(chemin, corps=None, delai=8):
    if chemin in ("/api/chat", "/api/generate"):
        corps = avec_garde(corps)
    donnees = None if corps is None else json.dumps(corps).encode("utf-8")
    req = urllib.request.Request(_m.OLLAMA + chemin, data=donnees, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=delai) as r:
        return json.loads(r.read().decode("utf-8"))


def ps_ollama(nom):
    """Le modèle est-il en mémoire, et quelle part est sur la carte graphique ? (None = pas chargé ou Ollama muet)"""
    try:
        for m in ollama_json("/api/ps", None, 3).get("models", []):
            if m.get("name") == nom or m.get("model") == nom:
                return {"taille": m.get("size") or 0, "vram": m.get("size_vram") or 0}
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return None


class _FluxOllama:
    """Les évènements d'une réponse en flux d'Ollama (une ligne JSON par évènement). Fermer le gestionnaire ferme la connexion : Ollama arrête de générer."""

    def __init__(self, reponse):
        self.reponse = reponse

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.reponse.close()
        return False

    def __iter__(self):
        for brut in self.reponse:
            try:
                yield json.loads(brut.decode("utf-8"))
            except ValueError:
                continue


class MoteurOllama(_moteurs.Moteur):
    """Ollama : le moteur d'origine de Lutin. Il enveloppe les fonctions de ce module (ollama_json, etat_ollama, capacites, ps_modele) : rien de ce qui marchait ne change."""
    id = _moteurs.OLLAMA
    nom = "Ollama"
    genre = "ollama"
    gere_modeles = True

    @property
    def description(self):
        return _t("Le moteur installé et géré par Lutin : modèles téléchargés depuis la bibliothèque d'Ollama, réglages de vitesse et de mémoire.")

    @property
    def points_forts(self):
        return (_t("Le plus simple : un clic pour télécharger un modèle de sa bibliothèque, qui garde plusieurs modèles prêts."),
                _t("Décharge tout seul un modèle inutilisé et en recharge un autre à la demande."),
                _t("Lutin sait le régler (cœurs, mémoire, contexte) et en mesurer la vitesse."))

    @property
    def points_faibles(self):
        return (_t("Un peu moins rapide que llama.cpp utilisé directement, surtout avec les modèles à experts."),
                _t("Reçoit les nouveaux modèles et les optimisations avec un peu de retard."),
                _t("Un service de plus qui tourne en arrière-plan."))

    def config(self):
        return _llamacpp.lire_config().get(self.id, {})

    def serveur_installe(self):
        return chemin_ollama()

    def dossier_defaut(self):
        if os.name == "nt":
            from . import moteurs_docker
            choisi = moteurs_docker.reglage_dossier_moteurs()          # tu as choisi un dossier pour tous les moteurs : Ollama s'y installe aussi (sous-dossier ollama)
            if choisi:
                return Path(choisi) / "ollama"
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / "Programs" / "Ollama" if base and os.name == "nt" else None

    def dossier_installation(self):
        """Le dossier passé à l'installateur d'Ollama (Windows) : celui choisi pour Ollama seul, sinon le dossier des moteurs si tu en as choisi un, sinon l'emplacement habituel d'Ollama (None)."""
        propre = self.config().get("dossier")
        if propre:
            return propre
        from . import moteurs_docker
        return str(self.dossier_defaut()) if os.name == "nt" and moteurs_docker.reglage_dossier_moteurs() else None

    def info_dossier(self):
        """Comme pour llama.cpp : où il s'installe (choisi avant l'installation, sous Windows seulement : l'installateur d'Ollama accepte un dossier) et où sont ses modèles (réglés dans l'onglet Modèles)."""
        exe = chemin_ollama()
        defaut = self.dossier_defaut()
        choisi = self.config().get("dossier")
        actuel = Path(exe).parent if exe else (Path(choisi) if choisi else defaut)
        if os.environ.get("LUTIN_DOCKER"):
            from . import moteurs_docker
            defaut = moteurs_docker.ollama_dossier()
            actuel = Path(exe).parent.parent if exe and defaut and str(defaut) in exe else (defaut or actuel)
        modeles = __import__("lutin.emplacements", fromlist=["x"]).dossier_modeles()
        return {"actuel": str(actuel or ""), "propose": "", "defaut": str(defaut or ""), "personnalise": bool(choisi), "libre_go": {"actuel": _llamacpp.espace_libre(actuel), "propose": None, "defaut": _llamacpp.espace_libre(defaut)},
                "installe": exe is not None, "modifiable": os.name == "nt" and not os.environ.get("LUTIN_DOCKER"),
                "modeles": {"actuel": str(modeles), "libre_go": _llamacpp.espace_libre(modeles), "modifiable": False}}

    def _retenir_dossier_modeles(self):
        """Le dossier où Ollama range ses modèles AVANT une installation, s'il contient des modèles : une installation (ou une réinstallation) peut le faire retomber sur le dossier par défaut, vide."""
        try:
            from . import emplacements
            dossier = emplacements.dossier_modeles()
            if (Path(dossier) / "manifests").is_dir():
                emplacements.retenir_dossier_vu(dossier)
                return str(dossier)
        except (OSError, ValueError):
            pass
        return ""

    def _rendre_dossier_modeles(self, dossier):
        """Après l'installation : le même dossier de modèles est remis (configuration de Lutin + variable de l'utilisateur), si ce n'était pas le dossier par défaut d'Ollama."""
        if not dossier or Path(dossier) == Path.home() / ".ollama" / "models":
            return
        try:
            from . import emplacements
            emplacements.definir_dossier_modeles(dossier)
        except (OSError, ValueError) as erreur:
            _m.journaliser("Dossier des modèles d'Ollama non rétabli après l'installation ({!r}).".format(erreur))

    def statut(self):
        actif = etat_ollama()["actif"]
        installe = bool(chemin_ollama()) or actif
        return {"installe": installe, "actif": actif, "version": "", "mode": "gere",
                "detail": _t("Ollama répond.") if actif else (_t("Installé, mais arrêté.") if installe else _t("Pas installé."))}

    def actions(self):
        if os.environ.get("LUTIN_DOCKER"):
            from . import moteurs_docker
            st = self.statut()
            return moteurs_docker.actions_ollama(st["installe"], st["actif"], _hl.actif())
        st = self.statut()
        hors = _hl.actif()
        pas_installe, deja = _t("Pas installé."), _t("Déjà installé.")
        demarrer = {"possible": st["installe"] and not st["actif"], "raison": _t("Démarre Ollama.") if st["installe"] else pas_installe}
        arreter = {"possible": st["actif"], "raison": _t("Arrête Ollama et libère la mémoire.") if st["actif"] else _t("Il n'est pas démarré.")}
        if os.name == "nt":
            unins = ollama_client.desinstalleur_windows()
            gardes = _t("Tes modèles téléchargés sont gardés.")
            maj = {"possible": st["installe"] and not hors, "raison": _t("Installe la dernière version par-dessus l'actuelle (sans désinstaller) ; tes modèles, leur dossier et tes réglages sont gardés.") if st["installe"] else pas_installe}
            if hors:
                maj["raison"] = _t("Hors ligne : aucun téléchargement.")
            return {"mettre_a_jour": maj, "installer": {"possible": not st["installe"] and not hors, "raison": (_t("Hors ligne : aucun téléchargement.") if hors else _t("Télécharge l'installateur officiel, vérifie sa signature et l'installe pour toi (sans droits administrateur).")) if not st["installe"] else deja},
                    "desinstaller": {"possible": st["installe"] and unins is not None, "raison": _t("Désinstalle Ollama. ") + gardes if unins else (pas_installe if not st["installe"] else _t("Désinstalleur introuvable : utilise « Applications installées » de Windows."))},
                    "reinstaller": {"possible": st["installe"] and unins is not None and not hors, "raison": _t("Désinstalle puis réinstalle la dernière version. ") + gardes if st["installe"] else pas_installe},
                    "demarrer": demarrer, "arreter": arreter}
        if sys.platform == "darwin":
            installer = _t("Télécharge Ollama sur https://ollama.com/download, puis ouvre-le.")
            retirer = _t("Glisse l'application Ollama dans la corbeille.")
        else:
            installer = _t("Sous Linux, l'installation demande les droits administrateur : lance dans un terminal « {} ».").format(ollama_client.COMMANDE_LINUX)
            retirer = _t("Sous Linux, la désinstallation demande les droits administrateur : suis la procédure de https://docs.ollama.com/linux#uninstall.")
        return {"mettre_a_jour": {"possible": False, "raison": _t("Relance la commande d'installation dans un terminal.") if st["installe"] else pas_installe},
                "installer": {"possible": False, "raison": deja if st["installe"] else installer}, "desinstaller": {"possible": False, "raison": retirer if st["installe"] else pas_installe},
                "reinstaller": {"possible": False, "raison": _t("Relance la commande d'installation dans un terminal.") if st["installe"] else pas_installe}, "demarrer": demarrer, "arreter": arreter}

    def faire(self, action, progression):
        a = self.actions().get(action) or {}
        if not a.get("possible"):
            raise ValueError(a.get("raison") or _t("Action impossible avec ce moteur."))
        if os.environ.get("LUTIN_DOCKER"):
            from . import moteurs_docker
            try:
                gpus = getattr(_moteurs.CONTEXTE["profil"](), "gpus", None) or []
                moteurs_docker.faire_ollama(action, progression, lambda: etat_ollama()["actif"], rocm=any(getattr(g, "fabricant", "") == "amd" for g in gpus))
            finally:
                CAPACITES.clear()
            return
        cache = Path(tempfile.gettempdir()) / "lutin-ollama"
        dossier_modeles = self._retenir_dossier_modeles() if action in ("mettre_a_jour", "reinstaller", "installer") else ""
        try:
            if action == "demarrer":
                progression(_t("Démarrage d'Ollama…"), 0, 0)
                _m.demarrer_ollama()
            elif action == "arreter":
                _m.arreter_ollama()
            elif action == "mettre_a_jour":
                progression(_t("Arrêt d'Ollama…"), 0, 0)
                _m.arreter_ollama()
                ollama_client.installer_windows(cache, progression)          # par-dessus l'existant : le même dossier, rien n'est désinstallé
                self._rendre_dossier_modeles(dossier_modeles)
                _m.demarrer_ollama()
            elif action in ("desinstaller", "reinstaller"):
                progression(_t("Arrêt d'Ollama…"), 0, 0)
                _m.arreter_ollama()
                progression(_t("Désinstallation…"), 0, 0)
                ollama_client.desinstaller_windows()
                if action == "reinstaller":
                    ollama_client.installer_windows(cache, progression, dossier=self.dossier_installation())
                    self._rendre_dossier_modeles(dossier_modeles)
                    _m.demarrer_ollama()
            elif action == "installer":
                ollama_client.installer_windows(cache, progression, dossier=self.dossier_installation())
                self._rendre_dossier_modeles(dossier_modeles)
                _m.demarrer_ollama()
        except ollama_client.ErreurOllama as e:
            raise ValueError(str(e))
        CAPACITES.clear()

    def telechargeable(self):
        if _hl.actif():
            return {"possible": False, "raison": _t("Hors ligne : aucun téléchargement."), "genre": "bibliotheque"}
        return {"possible": True, "raison": _t("La bibliothèque d'Ollama : un clic par modèle."), "genre": "bibliotheque"}

    def supprimer_modele(self, nom):
        return supprimer_modele(nom)

    def actif(self):
        return etat_ollama()["actif"]

    def modeles(self):
        return etat_ollama()

    def capacites(self, modele):
        return capacites_ollama(modele)

    def en_memoire(self, modele):
        return ps_ollama(modele)

    def grille(self):
        natif = ("natif", "")
        return {"discuter": natif, "flux": natif, "arret": natif, "outils": natif, "reflexion": natif, "vision": natif, "embeddings": natif,
                "plusieurs_modeles": ("natif", _t("Ollama garde plusieurs modèles en mémoire et décharge les plus anciens.")), "telechargement": natif, "installation": natif}

    def vecteurs(self, modele, textes, delai=60):
        corps = json.dumps({"model": modele, "input": [str(t) for t in textes]}).encode("utf-8")
        req = urllib.request.Request(_m.OLLAMA + "/api/embed", data=corps, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=delai) as r:
            donnees = json.loads(r.read().decode("utf-8"))
        liste = donnees.get("embeddings")
        if not isinstance(liste, list) or len(liste) != len(textes) or not all(isinstance(v, list) and v for v in liste):
            raise ValueError(_t("Réponse d'embeddings inattendue."))
        return liste

    def chat(self, corps, delai=60):
        return ollama_json("/api/chat", corps, delai)

    def chat_flux(self, corps, delai=900):
        req = urllib.request.Request(_m.OLLAMA + "/api/chat", data=json.dumps(avec_garde(corps)).encode("utf-8"), headers={"Content-Type": "application/json"})
        return _FluxOllama(urllib.request.urlopen(req, timeout=delai))          # l'erreur de connexion ou HTTP est levée ici, chez l'appelant


_moteurs.enregistrer(MoteurOllama())
_moteurs.CONTEXTE.update(donnees=lambda: _m.DONNEES, en_docker=lambda: bool(os.environ.get("LUTIN_DOCKER")), hors_ligne=lambda: _hl.actif(),
                         profil=lambda: __import__("lutin.adequation", fromlist=["x"]).profil_pret(),
                         profil_attendu=lambda: __import__("lutin.adequation", fromlist=["x"]).profil_attendu(),
                         dossier_ollama=lambda: (None if os.environ.get("LUTIN_DOCKER") else __import__("lutin.emplacements", fromlist=["x"]).dossier_modeles()))
_moteurs.enregistrer(_llamacpp.MoteurLlamaCpp())
_moteurs.enregistrer(_llamacpp.MoteurExterne())


def capacites(modele):
    """Ce que le modèle sait faire d'après le moteur choisi."""
    return moteur_actuel().capacites(modele)


def ps_modele(nom):
    """Le modèle est-il chargé (et sa taille), d'après le moteur choisi ?"""
    return moteur_actuel().en_memoire(nom)


def etat_moteur():
    """{actif, installes, tailles} du moteur choisi : ses modèles, et s'il est prêt."""
    return moteur_actuel().modeles()


def moteur_local(r=None):
    """Le moteur de CETTE machine (celui des réglages), jamais une machine prêtée : c'est lui qu'on mesure, qu'on décharge, dont on lit la mémoire."""
    r = r if r is not None else _m.reglages()
    return _moteurs.par_id(r.get("moteur") or _moteurs.OLLAMA)


def client_banc(r=None):
    """Ce que le banc d'essai interroge : Ollama directement, ou le moteur choisi (llama.cpp, serveur compatible OpenAI) derrière l'adaptateur du banc."""
    from . import bench
    local = moteur_local(r)
    return _m._Ollama(_m.OLLAMA) if local.id == _moteurs.OLLAMA else bench.AdaptateurMoteur(local)


def moteur_actuel(r=None):
    """Le moteur choisi dans les réglages (Ollama par défaut, et si le réglage est inconnu)."""
    r = r if r is not None else _m.reglages()
    local = _moteurs.par_id(r.get("moteur") or _moteurs.OLLAMA)
    if r.get("machine"):          # une machine est choisie : ses demandes de conversation partent chez elle quand elle est opérationnelle, sinon ce moteur répond (en silence)
        from . import machines
        return machines.acheminer(local, r)
    return local


def etat_ollama():
    """Ollama lui-même : ses modèles installés et s'il répond (voir etat_moteur pour le moteur choisi)."""
    try:
        tags = ollama_json("/api/tags", None, 3)
        return {"actif": True, "installes": [m["name"] for m in tags.get("models", [])], "tailles": {m["name"]: int(m.get("size") or 0) for m in tags.get("models", [])}}
    except (urllib.error.URLError, OSError, ValueError):
        return {"actif": False, "installes": [], "tailles": {}}


def chemin_ollama():
    if os.environ.get("LUTIN_DOCKER"):
        from . import moteurs_docker
        return moteurs_docker.chemin_ollama()          # celui que Lutin a installé dans le dossier des moteurs (volume)
    exe = shutil.which("ollama")
    if exe:
        return exe
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")):
        c = Path(base) / "Programs" / "Ollama" / "ollama.exe" if base else None
        if c and c.is_file():
            return str(c)
    return ""


PULLS = {}


RE_NOM_MODELE = re.compile(r"^[A-Za-z0-9_./:-]{1,100}$")


def lire_registre_modeles():
    """donnees/modeles.json : les modèles ajoutés par l'utilisateur (« perso ») et ceux du catalogue qu'il a retirés de la liste (« masques »)."""
    d = _m.lire_json(_m.DONNEES / "modeles.json", {})
    d = d if isinstance(d, dict) else {}

    def propre(liste):
        return [x for x in (liste if isinstance(liste, list) else []) if isinstance(x, str) and RE_NOM_MODELE.match(x)]
    return {"perso": propre(d.get("perso")), "masques": propre(d.get("masques"))}


def ecrire_registre_modeles(registre):
    _m.ecrire_atomique(_m.DONNEES / "modeles.json", json.dumps(registre, ensure_ascii=False, indent=1))


def modeles_connus(installes, tailles=None):
    """La liste affichée dans l'onglet Modèles : le catalogue (sauf ce que l'utilisateur a retiré), les modèles qu'il a ajoutés, et ceux qui sont installés dans Ollama
    sans figurer ici (installés à la main) : tous ont les mêmes boutons (utiliser, supprimer...). Un modèle retiré mais installé reste affiché : on ne perd jamais l'option de le désinstaller."""
    tailles = tailles or {}
    reg = lire_registre_modeles()
    catalogue = {m["id"] for m in _m.MODELES}
    avance = bool(_m.reglages().get("avance"))
    liste = [dict(m, origine="catalogue") for m in _m.MODELES if (m["id"] not in reg["masques"] and (avance or not m["avance"])) or m["id"] in installes]
    vus = set(catalogue)
    a_lire = []
    for entree in liste:                                                                   # la précision installée (4 bits, 8 bits…) de chaque modèle du catalogue qui est installé
        if entree["id"] in installes:
            infos = _infos.deja_connu(entree["id"], _m.DONNEES)
            if infos is None:
                a_lire.append(entree["id"])
            elif infos.get("quantification"):
                entree["quantification"] = infos["quantification"]
    for nom in reg["perso"] + [n for n in installes if n not in reg["perso"]]:
        if nom in vus:
            continue
        vus.add(nom)
        entree = {"id": nom, "nom": nom, "go": round(tailles.get(nom, 0) / 1e9, 1), "role": "perso", "origine": "perso" if nom in reg["perso"] else "installe"}
        if nom in installes:
            infos = _infos.deja_connu(nom, _m.DONNEES)
            if infos is None:
                a_lire.append(nom)
            elif infos:
                entree.update({k: infos[k] for k in ("params_b", "actifs_b", "ctx_max", "kv_mo_1k", "quantification") if k in infos})          # les vrais chiffres d'Ollama au lieu d'une estimation
                if "capacites" in infos:
                    entree["capacites"] = infos["capacites"]
                if infos.get("embedding"):
                    entree["embedding"] = True                                          # la page ne propose ni « Utiliser » ni banc d'essai pour un modèle de recherche
                entree["phrase"] = _infos.phrase(infos)
        liste.append(entree)
    if a_lire:
        _infos.demander(a_lire, _m.DONNEES, lambda n: ollama_json("/api/show", {"model": n}, 8))          # en arrière-plan : la liste s'améliore au rafraîchissement suivant
    return liste


def oublier_modele(modele):
    """Retire un modèle de la liste (le fichier n'est pas touché). Seulement s'il n'est PAS installé : sinon on perdrait le bouton de désinstallation."""
    modele = str(modele)
    if not RE_NOM_MODELE.match(modele):
        raise ValueError("Nom de modèle invalide.")
    o = etat_ollama()
    if not o["actif"]:
        raise ValueError("Ollama ne répond pas : je ne peux pas vérifier que ce modèle n'est pas installé. Démarre Ollama d'abord.")
    if modele in o["installes"]:
        raise ValueError("Ce modèle est installé : désinstalle-le d'abord (sinon tu perdrais le bouton de nettoyage). Tu pourras ensuite le retirer de la liste.")
    if _m.reglages()["modele"] == modele:
        raise ValueError("C'est le modèle actif : choisis-en un autre avant de le retirer.")
    if PULLS.get(modele, {}).get("statut") == "en cours":
        raise ValueError("Un téléchargement de ce modèle est en cours.")
    reg = lire_registre_modeles()
    if modele in [m["id"] for m in _m.MODELES]:
        if modele not in reg["masques"]:
            reg["masques"].append(modele)
    elif modele in reg["perso"]:
        reg["perso"].remove(modele)
    else:
        raise ValueError("Ce modèle n'est pas dans la liste.")
    ecrire_registre_modeles(reg)
    PULLS.pop(modele, None)
    CAPACITES.pop(modele, None)
    _m.journaliser("Modèle retiré de la liste : " + modele)
    return {"ok": True, "modele": modele}


def restaurer_modeles():
    """Remet dans la liste les modèles du catalogue qui avaient été retirés."""
    reg = lire_registre_modeles()
    reg["masques"] = []
    ecrire_registre_modeles(reg)
    return {"ok": True}


def installer_modele(modele):
    _hl.exiger_en_ligne("télécharger un modèle")
    if moteur_actuel().id != _moteurs.OLLAMA and not hasattr(moteur_actuel(), "telecharger_ollama"):
        raise ValueError(_t("Ce moteur gère ses modèles lui-même : installe-les depuis le moteur."))
    if modele not in [m["id"] for m in _m.MODELES] and not RE_NOM_MODELE.match(modele):
        raise ValueError("Nom de modèle invalide.")
    catalogue_m = next((m for m in _m._CATALOGUE["modeles"] if m["id"] == modele), None)
    if catalogue_m is not None:          # un modèle du catalogue que ce moteur ne sait pas faire tourner n'est jamais installé
        from . import compat_modeles
        verdict = compat_modeles.evaluer(catalogue_m, moteur_actuel(), etat_moteur()["installes"])
        if not verdict["compatible"]:
            raise ValueError(" ".join(verdict["raisons"]))
    if PULLS.get(modele, {}).get("statut") == "en cours":
        return PULLS[modele]
    reg = lire_registre_modeles()                       # le modèle entre dans la liste dès le début du téléchargement (et y reste, pour pouvoir le suivre, le supprimer ou le retirer)
    if modele in [m["id"] for m in _m.MODELES]:
        if modele in reg["masques"]:
            reg["masques"].remove(modele)
            ecrire_registre_modeles(reg)
    elif modele not in reg["perso"]:
        reg["perso"].append(modele)
        ecrire_registre_modeles(reg)
    PULLS[modele] = {"statut": "en cours", "fait": 0, "total": 0, "texte": "démarrage..."}

    def travail():
        try:
            if moteur_actuel().id != _moteurs.OLLAMA:          # un autre moteur : le même modèle, téléchargé depuis la bibliothèque d'Ollama sans Ollama
                def progression(texte="", fait=0, total=0):
                    PULLS[modele].update({"texte": _t("téléchargement"), "fait": fait, "total": total})
                moteur_actuel().telecharger_ollama(modele, progression)
                PULLS[modele]["statut"] = "termine"
                return
            req = urllib.request.Request(_m.OLLAMA + "/api/pull", data=json.dumps({"model": modele, "stream": True}).encode("utf-8"), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3600) as r:
                for brut in r:
                    try:
                        e = json.loads(brut.decode("utf-8"))
                    except ValueError:
                        continue
                    if e.get("error"):
                        raise RuntimeError(e["error"])
                    PULLS[modele].update({"texte": e.get("status", ""), "fait": e.get("completed", PULLS[modele]["fait"]), "total": e.get("total", PULLS[modele]["total"])})
            PULLS[modele]["statut"] = "termine"
        except Exception as erreur:  # noqa: BLE001
            texte = str(erreur)[:300]
            if "id_ed25519" in texte:
                # Ollama signe ses demandes au registre avec une clé gardée dans son dossier « .ollama » (à côté de son historique, PAS dans le dossier des modèles). Si ce dossier a été supprimé ou
                # déplacé pendant qu'Ollama tournait, il ne la retrouve plus : il la recrée à son démarrage.
                PULLS[modele].update({"statut": "erreur", "aide": "redemarrer", "texte": _t("Ollama ne retrouve plus son fichier d'identité (id_ed25519, dans son dossier .ollama : il a été supprimé ou déplacé). Il le recrée à son démarrage : redémarre Ollama, puis réessaie.")})
            elif "does not exist" in texte.lower() or "requires mlx" in texte.lower() or "mlx runtime" in texte.lower():
                if "mlx" in texte.lower():
                    message = _t("« {} » est fait pour les Mac (MLX, la puce Apple) : il ne tourne pas sur cette machine. Choisis un autre modèle, ou une autre taille sans « mlx » dans son nom. Il est retiré de ta liste.").format(modele)
                else:
                    message = _t("Ce modèle (ou cette taille) n'existe pas dans la bibliothèque d'Ollama : « {} ». Vérifie son nom exact sur sa page ollama.com. Il est retiré de ta liste.").format(modele)
                try:          # retiré de la liste AVANT d'annoncer l'échec : la page (et les tests) qui voient « erreur » trouvent déjà la liste à jour
                    reg2 = lire_registre_modeles()
                    if modele in reg2["perso"]:
                        reg2["perso"].remove(modele)
                        ecrire_registre_modeles(reg2)
                except (OSError, KeyError, ValueError):
                    pass
                PULLS[modele].update({"statut": "erreur", "texte": message})
            else:
                PULLS[modele].update({"statut": "erreur", "texte": texte})
    threading.Thread(target=travail, daemon=True).start()
    return PULLS[modele]


def supprimer_modele(modele):
    if modele not in [m["id"] for m in _m.MODELES] and not re.match(r"^[A-Za-z0-9_./:-]{1,100}$", modele):
        raise ValueError("Nom de modèle invalide.")
    if moteur_actuel().id != _moteurs.OLLAMA:
        mo = moteur_actuel()
        actif = _m.reglages()["modele"] == modele
        try:
            mo.supprimer_modele(modele)
        except Exception as erreur:  # noqa: BLE001  (le message du moteur est montré tel quel)
            raise ValueError(str(erreur))
        nouveau = ""
        if actif:
            restants = [n for n in mo.modeles().get("installes", []) if n != modele]
            if restants:
                nouveau = restants[0]
                _m.enregistrer_reglages({"modele": nouveau})
        return {"ok": True, "modele": modele, "nouveau_actif": nouveau}
    suppression_active = _m.reglages()["modele"] == modele          # permis : sinon impossible de supprimer son seul modèle (pour déplacer le dossier, par exemple) ; on bascule sur un autre s'il y en a un
    req = urllib.request.Request(_m.OLLAMA + "/api/delete", data=json.dumps({"model": modele}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            r.read()
    except urllib.error.HTTPError as e:
        corps = e.read().decode("utf-8", "ignore")
        if "not found" in corps.lower() or "n'existe pas" in corps.lower():
            raise ValueError("Ce modèle n'est pas installé.")
        raise ValueError(_t("Ollama a refusé la suppression : {}").format(corps[:200]))
    CAPACITES.pop(modele, None)
    nouveau = ""
    if suppression_active:
        from . import embeddings
        restants = [n for n in etat_ollama().get("installes", []) if n != modele and not embeddings.est_modele_de_recherche(n)]
        if restants:
            nouveau = restants[0]
            _m.enregistrer_reglages({"modele": nouveau})
    return {"ok": True, "modele": modele, "nouveau_actif": nouveau}


def consignes_systeme(r):
    contexte, memoire = _m.lire_memoire("CONTEXTE.md"), _m.lire_memoire("MEMOIRE.md")
    mode = _modes.consigne(r["mode"])
    skills = _m.lister_skills()
    bloc_skills = ""
    if skills:
        lignes = "\n".join("- skills/{} : {}{}".format(nom, titre, (_t(" — à lire quand ") + d) if (d := _m.description_skill(nom)) else "") for nom, titre in skills)
        bloc_skills = (_t("\n\n# SKILLS (fiches du projet, à lire avec l'outil « lire » quand le sujet t'est demandé)\n"
                       "Ces fiches décrivent le projet de l'utilisateur (univers, règles, outil). Lis-les au moment où tu en as besoin, pas avant.\n") + lignes + "\n")
    return (_t("Tu es Lutin, l'assistant local de l'utilisateur. Tu réponds dans la langue de l'utilisateur, de façon directe et concise. Tu disposes d'outils pour lire et modifier le projet : utilise-les plutôt que de deviner. "
            "Chaque modification de fichier garde une sauvegarde de l'ancienne version et passe par l'accord de l'utilisateur, sauf s'il a activé l'accord automatique.\n\n") + mode + _t("\n\n# CONTEXTE DU PROJET (memoire/CONTEXTE.md)\n") + contexte[:14000] + _t("\n\n# NOTES DURABLES (memoire/MEMOIRE.md)\n") + (_m.texte_memoire(memoire) or _t("(aucune pour l'instant)"))
            + bloc_skills
            + (_mission.consigne_systeme() if r.get("_mission") else "")
            + ("" if r.get("mode") in ("discussion", "recherche") else _t("\n\n# CRÉER UN FICHIER\nQuand on te demande de créer ou d'écrire un fichier (docker-compose, script, configuration, document), appelle l'outil « ecrire » avec le chemin et le contenu complet, y compris après une recherche web. Ne te contente pas de montrer le contenu dans ta réponse."))
            + (_t("\n\n# ESSAI À BLANC\nTes écritures et tes commandes ne sont PAS exécutées : c'est une simulation, l'utilisateur voit ce que tu proposes. Propose ce que tu ferais (fichiers, contenu, commandes), sans insister ni réessayer. Lire et chercher fonctionnent normalement.\n") if r.get("essai_a_blanc") else "")
            + (_t("\n\n# DÉBUT DE LA CONVERSATION\nLes premiers échanges ne sont plus tous sous tes yeux (fiche de suivi ou résumé). Pour retrouver un détail précis (une décision, un nom, un chiffre, un texte), appelle « rappeler » avec quelques mots-clés et ici=true : ne le devine pas.\n") if r.get("rappel_ici") else "")
            + _pc.bloc_prompt(_m.RACINE)
            + bloc_plan(r)
            + _t("\n\nDate : ") + datetime.now().strftime("%Y-%m-%d") + _t(". Dossier du projet : ") + str(_m.RACINE))


def bloc_plan(r):
    """Le plan du projet dans le prompt (un quart de la fenêtre au plus, 6 500 caractères au plus) : le modèle sait où chercher sans dix recherches."""
    plan = _m.texte_plan(min(_m.PLAN_MAX, int(r["num_ctx"] * 0.25)))
    if not plan:
        return ""
    return _t("\n\n# PLAN DU PROJET (dossiers, fichiers, taille en lignes et fonctions principales ; il peut être en retard de quelques minutes : vérifie avec « lire » avant de modifier)\n") + plan + "\n"


def estimer(messages):
    return (sum(len(json.dumps(m, ensure_ascii=False)) for m in messages) + 2400 * sum(len(m.get("images") or ()) for m in messages)) // 3     # une image coûte environ 800 jetons


def calculer_vitesse(e):
    """Vitesses tirées des chiffres que donne Ollama à la fin d'une réponse : jetons/s écrits, jetons/s lus, temps de chargement du modèle.
    None si la réponse est trop courte pour que la mesure ait un sens."""
    ecrits, lus = int(e.get("eval_count") or 0), int(e.get("prompt_eval_count") or 0)
    d_ecrit, d_lu = (e.get("eval_duration") or 0) / 1e9, (e.get("prompt_eval_duration") or 0) / 1e9
    if ecrits < 5 or d_ecrit <= 0:
        return None
    return {"ecriture": round(ecrits / d_ecrit, 1), "lecture": round(lus / d_lu) if d_lu > 0 and lus >= 50 else None,
            "chargement": round((e.get("load_duration") or 0) / 1e9, 1), "total": round((e.get("total_duration") or 0) / 1e9, 1), "jetons": ecrits}


def jauge_contexte(conv, r=None):
    """Place prise dans la fenêtre de contexte : le chiffre réel d'Ollama s'il existe (dernière réponse), sinon une estimation."""
    r = r or _m.reglages()
    if conv.get("jetons"):
        return {"utilise": int(conv["jetons"]["utilise"]), "total": r["num_ctx"], "reel": True}
    msgs = [{"role": "system", "content": consignes_systeme(r) + _fichiers.consigne_dossier(conv) + _m.texte_taches(conv)}]
    if conv.get("resume"):
        msgs.append({"role": "user", "content": conv["resume"]})
    msgs += conv.get("messages", [])
    if memoire_longue(conv, r) == "fichier" and conv.get("id"):
        try:
            msgs.append({"role": "user", "content": _suivi.texte_pour_modele(conv["id"], r["num_ctx"])})          # la place de la fiche compte dans la jauge
        except ValueError:
            pass
    return {"utilise": estimer(msgs) + len(json.dumps(_m.OUTILS, ensure_ascii=False)) // 3, "total": r["num_ctx"], "reel": False}


RE_CONTEXTE = re.compile(r"no query found|context|too long|exceed|truncat|prompt", re.I)


def ajuster_contexte(msgs, num_ctx, facteur=1.0, outils=None):
    """Garde la requête de l'utilisateur et le plus récent ; rétrécit les anciens résultats d'outils, puis retire les anciens échanges d'outils,
    pour que le total tienne dans num_ctx (avec de la place pour la réponse). outils : les outils réellement envoyés (leur place est déduite)."""
    budget = int(num_ctx * 0.68 * facteur) - len(json.dumps(_m.OUTILS if outils is None else outils, ensure_ascii=False)) // 3
    msgs = [dict(m) for m in msgs]
    dernier_user = max((i for i, m in enumerate(msgs) if m["role"] == "user"), default=-1)
    # les messages épinglés ne sont jamais retirés, dans la limite d'un quart du budget (les plus récents d'abord : au-delà, les plus anciens redeviennent retirables)
    protege, total = set(), 0
    for i in reversed(range(len(msgs))):
        if msgs[i].get("epingle"):
            total += len(json.dumps(msgs[i], ensure_ascii=False)) // 3
            if total <= budget // 4:
                protege.add(id(msgs[i]))

    def taille():
        return estimer(msgs)
    # 1) résultats d'outils anciens raccourcis (on garde les deux plus récents entiers)
    outils = [i for i, m in enumerate(msgs) if m["role"] == "tool"]
    for i in outils[:-2]:
        if taille() <= budget:
            break
        if len(msgs[i].get("content", "")) > 500:
            msgs[i]["content"] = msgs[i]["content"][:400] + "\n[... résultat ancien raccourci pour économiser le contexte ; relis le fichier si besoin]"
    # 2) puis les échanges d'outils les plus anciens sont retirés (jamais la question de l'utilisateur ni ce qui la précède immédiatement)
    i = 1
    while taille() > budget and i < len(msgs) - 2:
        if i != dernier_user and msgs[i]["role"] in ("assistant", "tool") and i > 0 and (dernier_user < 0 or i > dernier_user):
            del msgs[i]
            continue
        i += 1
    # 3) en dernier recours, les derniers résultats sont tronqués
    for i in reversed(range(len(msgs))):
        if taille() <= budget:
            break
        if msgs[i]["role"] == "tool" and len(msgs[i].get("content", "")) > 1500:
            msgs[i]["content"] = msgs[i]["content"][:1500] + "\n[... tronqué]"
    # 4) les anciens tours de conversation (avant la question actuelle) sont retirés s'il le faut, en gardant le système, le résumé et la question
    while taille() > budget and dernier_user > 2:
        for i in range(1, dernier_user):
            if msgs[i]["role"] in ("user", "assistant", "tool") and id(msgs[i]) not in protege and not msgs[i].get("content", "").startswith(("[Résumé", "[Fiche de suivi", "[Extraits", "Compris, je m'appuie")):
                del msgs[i]
                dernier_user -= 1
                break
        else:
            break
    for m in msgs:
        m.pop("epingle", None)                                   # le marquage est à nous : Ollama ne le reçoit pas
        m.pop("medias", None)
        m.pop("medias_fichiers", None)
        m.pop("fichiers_joints", None)
    return msgs


def compacter(conv, r, emit, forcer=False):
    """Quand la conversation approche de la taille du contexte, le début est résumé par le modèle. forcer (commande /compact) : on résume tout sauf le dernier échange,
    même si la conversation est encore courte. Renvoie True si un résumé a été fait."""
    msgs = conv["messages"]
    if forcer:
        coupe = max((i for i, m in enumerate(msgs) if m["role"] == "user"), default=0)
        if coupe < 2:
            return False
    else:
        if not a_compacter(conv, r):
            return False
        coupe = max(2, len(msgs) // 2)
        while coupe < len(msgs) and msgs[coupe]["role"] != "user":             # on coupe avant un message de l'utilisateur
            coupe += 1
    ancien = msgs[:coupe]
    texte = "\n".join("[{}] {}".format(m["role"], (m.get("content") or ("(outils : " + ", ".join(t["function"]["name"] for t in m.get("tool_calls", [])) + ")"))[:1500]) for m in ancien)
    texte = texte[-int(r["num_ctx"] * 1.8):]          # le texte à résumer doit lui aussi tenir dans le contexte
    emit({"type": "info", "texte": "Conversation longue : résumé du début..."})
    try:
        rep = moteur_actuel(r).chat({"model": modele_annexe(r), "stream": False, "think": False, "options": _m.options_modele(r, 0.2),
                                        "messages": [{"role": "system", "content": "Tu résumes une conversation pour pouvoir la continuer plus tard. Garde : les décisions, les fichiers modifiés, ce qui reste à faire, les préférences de l'utilisateur. Sois dense, en français."},
                                                     {"role": "user", "content": (conv.get("resume", "") + "\n\n" if conv.get("resume") else "") + texte}]}, 600)
        nouveau_resume = (rep.get("message", {}).get("content") or "").strip()[:6000]
        if not nouveau_resume:                      # résumé vide : on garde tout plutôt que de perdre le début
            _m.journaliser("Résumé vide : conversation {} gardée entière.".format(conv.get("id")))
            return False
        _archive.ajouter(conv["id"], ancien)                  # le résumé perd des détails : le début reste retrouvable (« rappeler »)
        conv["resume"] = nouveau_resume
        conv["messages"] = [m for m in ancien if m.get("epingle")] + msgs[coupe:]          # les messages épinglés restent tels quels, en plus du résumé
        _decaler_scribe(conv, coupe, len([m for m in ancien if m.get("epingle")]))
        conv.pop("jetons", None)                    # le chiffre de contexte d'avant le résumé n'est plus vrai
        return True
    except (urllib.error.URLError, OSError, ValueError) as erreur:
        # Le résumé a échoué : on ne supprime rien (ajuster_contexte raccourcit déjà ce qui est envoyé au modèle).
        _m.journaliser("Résumé impossible ({}) : conversation {} gardée entière.".format(erreur, conv.get("id")))
        return False


def _decaler_scribe(conv, coupe, gardes):
    """Le scribe retient un RANG dans la liste des messages : quand le début est retiré, ce rang doit suivre, sinon il saute des messages ou croit en avoir lu qu'il n'a pas lus."""
    if conv.get("scribe_a"):
        conv["scribe_a"] = max(0, int(conv["scribe_a"]) - coupe) + gardes


SEUIL_PLEIN = 0.6              # au-delà, le retrait n'attend plus le scribe : mieux vaut une fiche en retard (le début reste retrouvable avec « rappeler ») qu'une conversation qui n'a plus de place pour répondre
SEUIL_PLEIN_REEL = 0.8         # idem d'après le chiffre réel d'Ollama
PART_GARDEE = 0.25            # /compact en mode fiche : les messages récents gardés tels quels tiennent dans ce quart de la fenêtre
SEUIL_ELAGAGE = 0.45         # part de la fenêtre que les messages peuvent prendre avant le retrait : avec la fiche (jusqu'à 10 %), le système et les outils, le total reste sous les 68 % où ajuster_contexte se mettrait à rogner


def elaguer(conv, r, emit, forcer=False):
    """Mode « fiche de suivi » : la fiche garde le fil, donc le début de la conversation est retiré EN BLOC (la moitié, ou tout sauf le dernier échange si forcer), sans appeler le modèle, et mis à l'archive (« rappeler »).
    Sans ce retrait, la conversation grossissait sans fin et ajuster_contexte rognait le début à CHAQUE réponse : le début de la requête changeait à chaque fois, Ollama ne pouvait plus réutiliser son cache
    (tout relu à chaque réponse : des minutes sur processeur) et la jauge restait pleine. Là, le début ne change qu'à chaque retrait. Renvoie True si quelque chose a été retiré."""
    msgs = conv["messages"]
    if forcer:
        derniere = max((i for i, m in enumerate(msgs) if m["role"] == "user"), default=0)
        coupe = max(2, len(msgs) // 2)                                          # au moins la moitié sort…
        while coupe < derniere and msgs[coupe]["role"] != "user":
            coupe += 1
        while coupe < derniere and estimer(msgs[coupe:]) > int(r["num_ctx"] * PART_GARDEE):          # …et plus encore jusqu'à ce que le reste tienne dans le quart de la fenêtre : les VRAIS messages récents restent, la fiche garde le fil
            coupe += 1
            while coupe < derniere and msgs[coupe]["role"] != "user":
                coupe += 1
        coupe = min(coupe, derniere)
    else:
        reel = int((conv.get("jetons") or {}).get("utilise") or 0)                # le chiffre d'Ollama après la dernière réponse : l'estimation (caractères / 3) peut se tromper
        plein = estimer(msgs) >= int(r["num_ctx"] * SEUIL_PLEIN) or reel >= int(r["num_ctx"] * SEUIL_PLEIN_REEL)
        if len(msgs) < 8 or (estimer(msgs) < int(r["num_ctx"] * SEUIL_ELAGAGE) and reel < int(r["num_ctx"] * SEUIL_PLEIN_REEL)):
            return False
        coupe = max(2, len(msgs) // 2)
        while coupe < len(msgs) and msgs[coupe]["role"] != "user":              # on coupe avant un message de l'utilisateur
            coupe += 1
        if r.get("fiche_scribe", True) and int(conv.get("scribe_a") or 0) < coupe and not plein:       # jamais de message que le scribe n'a pas encore lu : il ne serait plus dans la fiche
            lu = int(conv.get("scribe_a") or 0)                                                      # (sauf fenêtre presque pleine : mieux vaut une fiche en retard, le début reste retrouvable avec « rappeler »)
            while coupe > lu:
                coupe -= 1
            while coupe > 0 and coupe < len(msgs) and msgs[coupe]["role"] != "user":
                coupe -= 1
    if coupe < 2 or coupe >= len(msgs):
        return False
    if forcer and r.get("fiche_scribe", True):
        scribe(conv, r, jusqua=coupe, forcer=True)                              # la fiche se met à jour avant que le début disparaisse : tout ce qui sort doit y être passé
        if messages_non_lus(conv, coupe):
            raise ValueError(_t("La fiche de suivi n'a pas pu être mise à jour (le modèle ne répond pas ?) : rien n'est retiré, pour ne rien perdre. Réessaie dans un moment."))
    ancien = msgs[:coupe]
    _archive.ajouter(conv["id"], ancien)
    conv["messages"] = [m for m in ancien if m.get("epingle")] + msgs[coupe:]
    _decaler_scribe(conv, coupe, len([m for m in ancien if m.get("epingle")]))
    conv.pop("jetons", None)                                                    # le chiffre de contexte d'avant le retrait n'est plus vrai
    emit({"type": "info", "texte": _t("Conversation longue : les {} plus anciens messages sortent du contexte (la fiche de suivi garde le fil, et tu peux les retrouver avec « rappeler »).").format(len(ancien))})
    return True


def compacter_conversation(ident):
    """Commande /compact : résume le début de la conversation maintenant (le modèle est sollicité, comptez quelques secondes)."""
    if ident in _m.TOURS_ACTIFS:
        raise ValueError("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la.")
    conv = _m.conv_lire(ident)
    avant = len(conv["messages"])
    info = []
    r = _m.reglages()
    fiche = memoire_longue(conv, r) == "fichier"
    if not (elaguer(conv, r, info.append, forcer=True) if fiche else compacter(conv, r, info.append, forcer=True)):
        raise ValueError("Rien à résumer (conversation trop courte) ou le résumé a échoué : voir donnees/lutin.log.")
    _m.conv_ecrire(conv)
    return {"ok": True, "avant": avant, "apres": len(conv["messages"]), "jauge": jauge_contexte(conv), "fiche": fiche}


def tour(conv, texte, emit, r=None, stop=None, remplacer_depuis=None, identite="", lecture_seule=False, images=(), pieces=()):
    """Un tour de conversation : message de l'utilisateur, puis la boucle de l'agent (réponse, outils, réponse...). emit(evenement) envoie à la page.
    stop (threading.Event) : déclenché par le bouton Arrêter ; le tour s'arrête alors pour de bon (modèle, outils, accords). Fermer la page ne l'arrête pas.
    remplacer_depuis : indice d'un message de l'utilisateur à remplacer (modifier un message / régénérer) ; ce message et tout ce qui le suit sont retirés d'abord.
    images : identifiants d'images jointes à ce message (voir images.py). pieces : documents et fichiers texte joints, [{id, nom}] (voir pieces.py).
    lecture_seule : tâches planifiées, où personne ne peut accepter : lecture et recherche seulement, tout le reste est simulé comme dans l'essai à blanc."""
    r = dict(r or _m.reglages())
    if lecture_seule:
        r["essai_a_blanc"] = True
    stop = stop if stop is not None else threading.Event()
    sortie_page, parle = emit, {"texte": False}

    def emit(evenement):                                                  # noqa: F811  (même nom : tout le tour passe par ici, pour savoir si la page a reçu une réponse)
        if evenement.get("type") in ("texte", "erreur"):
            parle["texte"] = True
        sortie_page(evenement)
    _m.rafraichir_plan()
    if remplacer_depuis is not None:
        i = int(remplacer_depuis)
        if not (0 <= i < len(conv["messages"]) and conv["messages"][i].get("role") == "user"):
            raise ValueError("Ce message n'existe plus dans la conversation (recharge-la).")
        del conv["messages"][i:]
        conv["taches"] = []                       # la liste de tâches venait de la suite supprimée
        conv.pop("jetons", None)                  # le chiffre de contexte de l'ancienne suite n'est plus vrai
    if conv.get("taches") and all(t.get("etat") == "fait" for t in conv["taches"]):
        conv["taches"] = []                       # la liste de la demande précédente est entièrement faite : on repart d'une page blanche
        emit({"type": "taches", "liste": []})

    def accord(titre, detail, diff, auto=False):
        if stop.is_set():
            raise _m.Arret()
        if ctx.get("essai"):
            # Essai à blanc : on montre ce qui aurait été fait, rien n'est écrit ni lancé, personne n'a à répondre.
            emit({"type": "essai", "titre": titre, "detail": detail, "diff": diff})
            ctx["dernier_accord"] = "essai"
            return False
        raison = "" if auto else _t("La case d'accord automatique correspondante n'est pas cochée pour cette conversation.")          # pourquoi on te demande : jamais un mystère
        if auto and ctx.get("web_lu") and not ctx.get("web_confiance"):
            # Garde-fou : du texte venu d'internet a été lu pendant ce tour, il pourrait contenir une consigne piégée. Plus d'accord automatique jusqu'à la fin du tour.
            emit({"type": "info", "texte": _t("Du contenu web a été lu : l'accord automatique est suspendu pour la suite de cette demande (il revient tout seul à la demande suivante), ta confirmation est demandée.")})
            auto = False
            raison = _t("Accord automatique suspendu : du contenu web a été lu pendant cette demande, il pourrait contenir une consigne piégée.")
            if not ctx.get("suspension_signalee"):
                ctx["suspension_signalee"] = True
                emit({"type": "accord_suspendu", "raison": raison})                # la page marque les cases : cochées, mais suspendues jusqu'à la fin de CETTE demande seulement
        if auto:
            emit({"type": "info", "texte": "Accord automatique : " + titre})
            ctx["dernier_accord"] = "auto"
            return True
        if ctx.get("mission"):
            # Mission longue : personne ne peut accepter. Ce qui n'est pas accordé d'office (contenu web lu pendant le tour, accord non coché) est refusé, et le modèle le sait.
            emit({"type": "info", "texte": _t("Refusé (mission sans surveillance) : {}").format(titre)})
            ctx["dernier_accord"] = "refuse"
            return False
        a = _m.Attente(titre, detail, diff, conv["id"])
        suspendu = bool(ctx.get("suspension_signalee"))
        emit({"type": "approbation", "id": a.id, "titre": titre, "detail": detail, "diff": diff, "raison": raison, "suspendu": suspendu})
        ok = a.attendre(stop=stop)
        if stop.is_set():
            raise _m.Arret()
        if ok and a.reactiver and suspendu:
            ctx["web_confiance"] = True                                          # choisi sur la carte : l'accord automatique reprend pour la suite de CETTE demande
            emit({"type": "accord_retabli"})
        emit({"type": "info", "texte": (_t("Accepté : {}") if ok else _t("Refusé : {}")).format(titre)})
        ctx["dernier_accord"] = "manuel"
        return ok
    ctx = {"essai": bool(r.get("essai_a_blanc")), "identite": identite, "accord": accord, "auto_ecriture": bool(r.get("auto_ecriture")), "auto_commandes": bool(r.get("auto_commandes")), "mission": r.get("_mission", ""), "stop": stop, "conv": conv, "emit": emit, "web": bool(r.get("web", True)), "limite_ram": int(r.get("limite_ram_commande_go", 0) * _m.GO),
           "tour": {"id": datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2), "conversation": conv["id"], "fichiers": {}}}
    dernier = conv["messages"][-1] if conv["messages"] else None
    if dernier and dernier.get("role") == "user" and dernier.get("content") == texte:
        emit({"type": "info", "texte": "Cette demande est déjà dans la conversation sans réponse : je la reprends sans la dupliquer."})
    else:
        conv["messages"].append(dict({"role": "user", "content": texte}, **({"images": list(images)} if images else {}), **({"pieces": list(pieces)} if pieces else {})))
    if images and not any(m.get("images") for m in conv["messages"][-1:]):
        conv["messages"][-1]["images"] = list(images)           # demande reprise sans doublon : on lui rend ses images
    if pieces and not conv["messages"][-1].get("pieces"):
        conv["messages"][-1]["pieces"] = list(pieces)
    if conv["titre"] == "Nouvelle conversation":
        conv["titre"] = " ".join(texte.split())[:60]
    _m.reparer_conversation(conv)
    if not _m.controle_avant_demande(r, emit, conv["id"], stop):
        _m.conv_ecrire(conv)                             # la demande est gardée : « continue » la relancera quand le problème sera réglé
        emit({"type": "fin", "conversation": {"id": conv["id"], "titre": conv["titre"]}})
        return
    _estimer_avant_charge(r, emit)
    r["memoire_longue"] = memoire_longue(conv, r)
    try:
        if r["memoire_longue"] == "demander":
            provisoire = conv.get("memoire_provisoire") or {}
            if lecture_seule:
                r["memoire_longue"] = "resume"                                          # une tâche planifiée ne peut pas répondre
            elif provisoire.get("choix") == "fichier" and len(conv["messages"]) < provisoire.get("jusqua", 0):
                r["memoire_longue"] = "fichier"                                         # choisi « pour cette fois » : on ne repose pas la question à chaque réponse
            elif a_compacter(conv, r):
                r["memoire_longue"] = demander_memoire(conv, r, emit, stop)
                conv.pop("memoire_provisoire", None)
                if r["memoire_longue"] == "fichier":
                    amorcer_fiche(conv, r, emit)
                    if not conv.get("memoire_longue"):
                        conv["memoire_provisoire"] = {"choix": "fichier", "jusqua": len(conv["messages"]) + 20}
        if r["memoire_longue"] != "fichier":
            compacter(conv, r, emit)
        elif not lecture_seule:
            elaguer(conv, r, emit)
        r["rappel_ici"] = r["memoire_longue"] == "fichier" or bool(conv.get("resume"))
        boucle_agent(conv, r, emit, ctx, stop)
    except _m.Arret:
        _m.journaliser("Tour arrêté par l'utilisateur (conversation {}).".format(conv["id"]))
        emit({"type": "info", "texte": "Arrêté. Ce qui était déjà fait est gardé dans la conversation ; écris « continue » pour reprendre."})
    except Exception as erreur:  # noqa: BLE001
        _m.journaliser("Erreur inattendue dans le tour (conversation {}) : {!r}".format(conv["id"], erreur))
        emit({"type": "erreur", "texte": _t("Erreur inattendue : {} (détail dans donnees/lutin.log). Ta demande est gardée.").format(str(erreur)[:300])})
    if r["memoire_longue"] == "fichier" and not lecture_seule:
        try:
            reponse = next((m.get("content") or "" for m in reversed(conv["messages"]) if m.get("role") == "assistant" and m.get("content")), "")
            _suivi.apres_tour(conv["id"], texte, reponse, sorted(ctx["tour"]["fichiers"]))
            if r.get("fiche_scribe", True) and not stop.is_set():
                scribe(conv, r, emit)
        except (OSError, ValueError) as erreur:
            _m.journaliser("Fiche de suivi non mise à jour (conversation {}) : {!r}".format(conv.get("id"), erreur))
    try:
        if _boucles.repete_derniere_reponse(conv):
            conv["boucle"] = int(conv.get("boucle") or 0) + 1
            emit({"type": "info", "texte": _t("↻ Cette réponse ressemble presque mot pour mot à la précédente : à ta prochaine demande, j'ordonnerai au modèle d'agir au lieu de répéter.")})
        else:
            conv.pop("boucle", None)
    except Exception as erreur:  # noqa: BLE001
        _m.journaliser("Détection de boucle impossible : {!r}".format(erreur))
    if conv.get("taches") and not ctx.get("taches_maj") and not lecture_seule:
        conv["taches_age"] = int(conv.get("taches_age") or 0) + 1
        if conv["taches_age"] >= _m.AGE_TACHES_MAX:               # le modèle est parti sur autre chose : la liste n'est plus vraie, elle ne doit pas rester là pour toujours
            conv["taches"], conv["taches_age"] = [], 0
            emit({"type": "taches", "liste": []})
            emit({"type": "info", "texte": _t("La liste de tâches n'était plus mise à jour depuis {} réponses : je la ferme.").format(_m.AGE_TACHES_MAX)})
    if not parle["texte"] and not stop.is_set() and not lecture_seule and not r.get("_mission"):
        _m.journaliser("Demande terminée sans aucune réponse écrite (conversation {}, modèle {}).".format(conv["id"], r["modele"]))
        emit({"type": "erreur", "texte": _t("Aucune réponse n'a été écrite. Causes fréquentes : la fenêtre de contexte est pleine (jauge en haut de la page : écris /compact ou ouvre une nouvelle conversation), ou le modèle manque de mémoire (ComfyUI occupe la carte graphique). Ta demande est gardée : écris « continue » pour réessayer.")})
    if ctx["tour"]["fichiers"]:                       # cette demande a touché des fichiers : le bouton « Annuler » les rétablira
        conv["annulable"] = {"id": ctx["tour"]["id"], "fichiers": sorted(ctx["tour"]["fichiers"])}
    _m.conv_ecrire(conv)
    if time.time() - _m.PURGE["derniere"] > 1800:        # au plus une fois toutes les 30 minutes
        try:
            _m.purger_donnees()
        except OSError as erreur:
            _m.journaliser("Purge impossible : {!r}".format(erreur))
    emit({"type": "fin", "conversation": {"id": conv["id"], "titre": conv["titre"]}})


PARAMETRE_UNIQUE = {"executer": "commande", "memoriser": "note"}          # outils dont l'argument principal est une chaîne : un modèle l'envoie parfois « nue », sans objet autour


NOMS_VOISINS = {"command": "commande", "cmd": "commande", "path": "chemin", "file": "chemin", "filepath": "chemin", "filename": "chemin", "folder": "dossier", "directory": "dossier",
                "dir": "dossier", "content": "contenu", "text": "contenu", "pattern": "motif", "query": "requete", "old": "ancien", "new": "nouveau"}


def _noms_voisins(args, proprietes):
    """Un modèle écrit parfois « command » ou « path » au lieu de « commande » ou « chemin » : on rattache le paramètre qu'il voulait dire, seulement s'il est déclaré par l'outil et absent des arguments."""
    if not proprietes:
        return args
    corrige = dict(args)
    for faux, vrai in NOMS_VOISINS.items():
        if faux in corrige and faux not in proprietes and vrai in proprietes and vrai not in corrige:
            corrige[vrai] = corrige.pop(faux)
    return corrige


def normaliser_arguments(nom, args, parametres=None):
    """Les arguments d'un appel d'outil sous forme de dictionnaire, quoi que le modèle ait envoyé (objet, texte JSON, chaîne nue, « clé=valeur », liste, rien).
    `parametres` : le schéma de l'outil (propriétés et champs obligatoires), pour savoir à quel paramètre rattacher une chaîne nue.
    Règle : « clé=valeur » n'est lu comme tel que si CHAQUE clé est un paramètre de l'outil ; sinon c'est du texte à rattacher à l'argument principal
    (« echo a=b » est une commande, pas {"echo a": "b"})."""
    parametres = parametres if isinstance(parametres, dict) else {}
    proprietes = set(parametres.get("properties") or {})
    requis = list(parametres.get("required") or [])
    principal = requis[0] if len(requis) == 1 else (next(iter(proprietes)) if len(proprietes) == 1 else PARAMETRE_UNIQUE.get(nom))
    if isinstance(args, dict):
        return _noms_voisins(args, proprietes)
    if args is None:
        return {}
    if isinstance(args, str):
        texte = args.strip()
        try:
            lu = json.loads(texte)
        except ValueError:
            lu = None
            decode = False
        else:
            decode = True
        if decode:
            if isinstance(lu, dict):
                return _noms_voisins(lu, proprietes)
            return {principal: lu if isinstance(lu, str) else texte} if principal and lu is not None else {}
        morceaux = [p for p in texte.split("&")]
        paires = [p.split("=", 1) for p in morceaux if "=" in p]
        if proprietes and paires and len(paires) == len(morceaux) and all(k.strip() in proprietes for k, _ in paires):
            return {k.strip(): v for k, v in paires}                      # « commande=dir&shell=cmd »
        return {principal: texte} if principal and texte else {}
    if isinstance(args, (int, float)) and not isinstance(args, bool):
        return {principal: str(args)} if principal else {}
    return {}


def contexte_routage():
    """(modèles installés pour discuter, ceux qui sont trop gros pour la machine, modèles des machines appairées) : ce dont le routeur a besoin. Jamais d'attente réseau (les machines sont lues en cache)."""
    from . import embeddings, machines
    installes = [n for n in etat_moteur().get("installes", []) if not embeddings.est_modele_de_recherche(n)]
    try:
        vram, ram = _m.memoire_video(), _m.memoire_vive()
        budget = (vram["total"] / 1024 ** 3) if vram else ((ram["total"] / 1024 ** 3) * 0.6 if ram else 0)
    except Exception:  # noqa: BLE001  (une mesure qui échoue ne doit pas empêcher de répondre)
        budget = 0
    trop_gros = {n for n in installes if budget and (_routeur.taille_go(n, _m.MODELES) or 0) > budget * 0.95}
    try:
        distants = machines.modeles_distants()
    except Exception:  # noqa: BLE001
        distants = []
    return installes, trop_gros, distants


def appliquer_choix(r, choix, emit, conv_id, motif_court):
    """Prend le modèle choisi pour CETTE demande (jamais le réglage), le dit et le note dans l'observatoire."""
    r["modele"], r["machine"] = choix["modele"], choix.get("machine", "")
    chez = _t(" (sur la machine « {} »)").format(choix["machine_nom"]) if choix.get("machine") else ""
    emit({"type": "info", "texte": "🧭 " + _t("Modèle choisi pour cette demande : {}{} — {}.").format(choix["modele"], chez, motif_court)})
    _observatoire.noter("routage", conv_id, profil=choix.get("profil", "reprise"), modele=choix["modele"], machine=choix.get("machine", ""), raison=motif_court)


def router_la_demande(r, demande, images, emit, conv_id):
    """Choix automatique du modèle (réglage « routage »), une fois par demande, jamais pendant une mission. Ne lève jamais : au pire, le modèle choisi reste le même."""
    try:
        if not r.get("routage") or r.get("_mission") or r.get("essai_a_blanc"):
            return False
        installes, trop_gros, distants = contexte_routage()
        choix = _routeur.choisir(demande, installes, r["modele"], _m.MODELES, images, trop_gros, distants)
        if choix:
            appliquer_choix(r, choix, emit, conv_id, choix["raison"])
            return True
    except Exception as erreur:  # noqa: BLE001
        _m.journaliser("Routeur de modèles : {!r}".format(erreur))
    return False


def monter_en_gamme(r, corps, emit, conv_id, motif):
    """Reprise : le modèle vient d'échouer (réponse vide, texte qui tourne en rond). Avec le routeur actif, UN essai avec un modèle plus gros. True si on a changé de modèle."""
    try:
        if not r.get("routage") or r.get("_mission") or r.get("_monte"):
            return False
        installes, trop_gros, distants = contexte_routage()
        choix = _routeur.plus_gros(r["modele"], installes, _m.MODELES, trop_gros, distants, exiger_reflexion=False)
        if not choix:
            return False
        r["_monte"] = True
        appliquer_choix(r, dict(choix, profil="reprise"), emit, conv_id, motif)
        corps["model"] = r["modele"]
        return True
    except Exception as erreur:  # noqa: BLE001
        _m.journaliser("Routeur de modèles (reprise) : {!r}".format(erreur))
        return False


def boucle_agent(conv, r, emit, ctx, stop):
    """La boucle de l'agent : le modèle répond, appelle des outils, on lui rend les résultats, jusqu'à la réponse finale."""
    tours_max = max(4, int(r.get("tours_max", _m.TOURS_MAX)))
    outils = outils_du_mode(r)                                      # seulement les outils utiles dans ce mode : moins de jetons, moins de confusion
    ctx["outils_autorises"] = {t["function"]["name"] for t in outils}
    try:
        rappels_texte, rappels_sources = _m.rappels_automatiques(conv, r)
    except Exception as erreur:  # noqa: BLE001
        _m.journaliser("Rappels automatiques impossibles : {!r}".format(erreur))
        rappels_texte, rappels_sources = "", []
    if rappels_sources:
        emit({"type": "info", "texte": _t("📎 Rappels ajoutés d'après tes documents : {}").format(" ; ".join(rappels_sources[:4]))})
    fiche, consigne = "", ""
    faux_accompli = None                                              # texte d'un modèle qui prétend avoir écrit un fichier sans l'avoir fait (corrigé une seule fois par demande)
    corrige_affirmation = False
    forcer_fin = False                                                # le modèle tourne en rond : un dernier tour SANS outil pour qu'il conclue, au lieu de couper net
    if r.get("memoire_longue") == "fichier":
        try:
            fiche = _suivi.texte_pour_modele(conv["id"], r["num_ctx"])            # lue UNE fois pour tout le tour : le début de la requête reste identique, Ollama le garde en cache
        except ValueError:
            fiche = ""
    extraits = ""
    if r.get("rappel_ici"):                       # le début de la conversation n'est plus sous les yeux du modèle : on lui remet ce qui touche à la demande
        try:
            etape = " ".join(_suivi.lire(conv["id"])["etape"] + _suivi.lire(conv["id"])["objectif"])
            extraits, nb_extraits = _m.rappel_du_fil(conv, etape)
            if nb_extraits:
                emit({"type": "info", "texte": _t("📎 {} passage(s) retrouvé(s) plus tôt dans cette conversation.").format(nb_extraits)})
        except Exception as erreur:  # noqa: BLE001  (la recherche ne doit jamais empêcher de répondre)
            _m.journaliser("Rappel du fil impossible : {!r}".format(erreur))
    derniere_demande = next((m.get("content") or "" for m in reversed(conv["messages"]) if m.get("role") == "user"), "")
    try:
        consigne = _suivi.directive_execution(conv, derniere_demande, conv["id"])
    except ValueError:
        consigne = ""
    if consigne:
        emit({"type": "info", "texte": _t("▶ Validation reçue : j'exécute l'étape en cours sans replanifier.")})
    elif conv.get("boucle"):                                      # la dernière réponse répétait la précédente : cette fois on ordonne d'agir
        consigne = _boucles.consigne()
    garde = _boucles.Garde()
    guide = ""
    if not consigne and not r.get("_mission") and "web_chercher" in ctx["outils_autorises"] and conv["messages"] and conv["messages"][-1].get("role") == "user":
        guide = _actualites.mode_guide(derniere_demande, r["modele"])
    if guide:
        try:                                                              # actualités, recherche demandée, adresse collée : Lutin cherche et lit lui-même, le modèle ne fait que répondre d'après ce qu'on lui montre
            consigne = _actualites.preparer(conv, derniere_demande, ctx, emit, reformuler=lambda t: reformuler_recherche(t, r), mode=guide) or ""
            forcer_fin = bool(consigne)
        except (_m.ErreurOutil, OSError) as erreur:
            _m.journaliser("Actualités guidées impossibles : {!r}".format(erreur))
            emit({"type": "info", "texte": _t("La recherche d'actualités n'a pas pu se faire ({}) : je continue normalement.").format(erreur)})
    for idx_tour in range(tours_max):
        msgs = [{"role": "system", "content": consignes_systeme(r) + _fichiers.consigne_dossier(conv) + _m.texte_taches(conv) + rappels_texte}]
        if conv.get("resume"):
            msgs.append({"role": "user", "content": "[Résumé de la conversation jusqu'ici]\n" + conv["resume"]})
            msgs.append({"role": "assistant", "content": "Compris, je continue."})
        historique = _pieces.pour_le_modele(conv["messages"], _pieces.budget_caracteres(r["num_ctx"]))          # le texte des fichiers joints s'ajoute ici, jamais dans la conversation enregistrée
        dernier_user = max((i for i, m in enumerate(historique) if m.get("role") == "user"), default=-1)
        if consigne and dernier_user >= 0:
            historique = list(historique)
            historique[dernier_user] = dict(historique[dernier_user], content=(historique[dernier_user].get("content") or "") + "\n\n[" + consigne + "]")
        if (fiche or extraits) and dernier_user >= 0:          # fiche et extraits passent juste AVANT la dernière question : tout ce qui précède est identique d'une réponse à l'autre (cache d'Ollama)
            bloc = "\n\n".join(x for x in (fiche, extraits) if x)
            historique = historique[:dernier_user] + [{"role": "user", "content": bloc}, {"role": "assistant", "content": "Compris, je m'appuie sur " + ("cette fiche." if fiche else "ces extraits.")}] + historique[dernier_user:]
        msgs += historique
        dernier_tour = idx_tour == tours_max - 1 or forcer_fin
        if dernier_tour:             # plus d'outils : le modèle doit répondre avec ce qu'il a trouvé
            msgs.append({"role": "user", "content": "Tu as assez d'informations. Réponds maintenant à ma demande avec ce que tu as vu, sans appeler d'outil. Si quelque chose manque, dis-le."})
        if faux_accompli:
            msgs += [{"role": "assistant", "content": faux_accompli[0]}, {"role": "user", "content": faux_accompli[1]}]
            faux_accompli = None
        msgs_base = msgs
        options = _m.options_modele(r, r["temperature"])
        if r.get("num_predict", 0) > 0:
            options["num_predict"] = r["num_predict"]
        caps = moteur_actuel(r).capacites(r["modele"])
        reflechit = bool(r["reflexion"]) and not (r.get("reflexion_tours") == "premier" and idx_tour > 0)          # option : la réflexion seulement avant la première réponse, pas à chaque retour d'outil
        if reflechit and caps is not None and "thinking" not in caps:
            reflechit = False
            if idx_tour == 0:
                emit({"type": "info", "texte": "Ce modèle n'a pas de mode réflexion : je le désactive pour cette demande."})
        options.update(_m.options_echantillonnage(r, reflechit))
        if idx_tour == 0 and any(m.get("images") for m in conv["messages"][-_images.RECENTS:]):
            voit = caps is None or "vision" in caps
            if not voit:
                autre = modele_qui_voit(r["modele"])
                if autre:
                    emit({"type": "info", "texte": _t("Ce modèle ne voit pas les images : je passe sur « {} » pour cette demande.").format(autre)})
                    r["modele"] = autre
                    caps = moteur_actuel(r).capacites(autre)
                else:
                    emit({"type": "info", "texte": _t("Ce modèle ne voit pas les images et aucun modèle « Images » n'est installé : elles sont ignorées. Onglet Modèles pour en installer un.")})
        if idx_tour == 0 and router_la_demande(r, derniere_demande, any(m.get("images") for m in conv["messages"][-_images.RECENTS:]), emit, conv["id"]):
            caps = moteur_actuel(r).capacites(r["modele"])
            reflechit = reflechit and (caps is None or "thinking" in caps)
        corps = {"model": r["modele"], "messages": ajuster_contexte(msgs, r["num_ctx"], 1.0, outils), "stream": True, "options": options, "think": reflechit}
        if not dernier_tour and outils:                      # mode « discussion » : aucun outil, donc rien à envoyer ni à signaler
            if caps is not None and "tools" not in caps:
                if idx_tour == 0:
                    emit({"type": "info", "texte": "Ce modèle ne sait pas appeler d'outils : il répondra sans lire ni modifier les fichiers. Choisis un autre modèle (Qwen 3.8 ou Gemma 4) pour cela."})
            else:
                corps["tools"] = outils
        fini, verifie, relance_outil, repli_demande, relance_vide, relance_repetition = False, False, False, False, False, False
        if moteur_actuel(r).en_memoire(r["modele"]) is None:
            emit({"type": "etat", "texte": "Chargement du modèle en mémoire (30 s à 2 min la première fois, ou si ComfyUI lui a pris la carte)."})
        for tentative in range(3):
            contenu, pensee, appels = "", "", []
            rond, verifie_rond, raison_fin = False, 0, ""
            corps_t = corps if tentative == 0 else dict(corps, messages=ajuster_contexte(msgs_base, r["num_ctx"], 0.7 ** tentative, outils) + ([{"role": "user", "content": RAPPEL_APPEL}] if relance_outil else [{"role": "user", "content": RAPPEL_REPETITION}] if relance_repetition else [{"role": "user", "content": RAPPEL_VIDE}] if relance_vide else []), options=dict(corps["options"], temperature=0.3, **({"repeat_penalty": 1.15} if relance_repetition else {})), think=False if (relance_vide or relance_repetition) else corps["think"])
            if relance_vide and tentative >= 2 and "tools" in corps_t:
                corps_t = {k: v for k, v in corps_t.items() if k != "tools"}          # dernier essai SANS outils : certains petits modèles ne produisent plus rien quand les outils sont déclarés ; mieux vaut une réponse en texte
            try:
                corps_t = dict(corps_t, messages=_images.pour_le_modele(corps_t["messages"], caps is None or "vision" in caps))
                moteur_choisi = moteur_actuel(r)
                with _moteurs.FluxInterruptible(lambda: moteur_choisi.chat_flux(corps_t, 900), stop) as flux:          # le moteur choisi (moteurs.py) ; Arrêter coupe même un modèle qui charge ou qui se fige
                    for e in flux:
                        if stop.is_set():
                            if contenu.strip():
                                conv["messages"].append({"role": "assistant", "content": contenu})
                            raise _m.Arret()
                        if e.get("error"):
                            raise RuntimeError(e["error"])
                        m = e.get("message") or {}
                        if e.get("done") and e.get("prompt_eval_count"):          # chiffres réels d'Ollama : jetons lus + écrits = place prise dans la fenêtre de contexte
                            conv["jetons"] = {"utilise": int(e["prompt_eval_count"]) + int(e.get("eval_count") or 0), "total": r["num_ctx"]}
                            emit(dict(conv["jetons"], type="jetons", reel=True))
                        if e.get("done"):
                            raison_fin = str(e.get("done_reason") or "")
                            vitesse = calculer_vitesse(e)
                            _observatoire.noter("tour", conv["id"], modele=r["modele"], machine=r.get("machine", ""), jetons=int(e.get("eval_count") or 0), tok_s=vitesse["ecriture"] if vitesse else None,
                                                duree_s=vitesse["total"] if vitesse else None)
                            if vitesse:
                                conv["vitesse"] = vitesse
                                emit(dict(vitesse, type="vitesse"))
                        if not verifie:
                            verifie = True
                            ps = moteur_actuel(r).en_memoire(r["modele"])
                            if ps and ps["taille"] and ps["vram"] < 0.9 * ps["taille"] and a_une_carte_graphique() and _avertir_une_fois(r["modele"]):
                                emit({"type": "info", "texte": "Attention : seulement {} % du modèle tient sur la carte graphique, le reste tourne sur le processeur, donc c'est lent. Ferme ComfyUI et le navigateur d'images, ou baisse le contexte dans Réglages.".format(round(100 * ps["vram"] / ps["taille"]))})
                        if m.get("thinking"):
                            pensee += m["thinking"]
                            emit({"type": "pensee", "texte": m["thinking"]})
                        if m.get("content"):
                            contenu += m["content"]
                            emit({"type": "texte", "texte": m["content"]})
                        appels += m.get("tool_calls") or []
                        if len(pensee) + len(contenu) - verifie_rond >= 400:                       # toutes les 400 lettres : le texte tourne-t-il en rond ? (sortir du « with » ferme la connexion, Ollama arrête de générer)
                            verifie_rond = len(pensee) + len(contenu)
                            if _boucles.texte_repete(pensee) or _boucles.texte_repete(contenu):
                                rond = True
                                break
                if rond:
                    _m.journaliser("Texte répété par le modèle {} (pensée : {} caractères, réponse : {}, essai {})".format(r["modele"], len(pensee), len(contenu), tentative + 1))
                    _observatoire.noter("relance", conv["id"], motif="texte répété", modele=r["modele"])
                    if tentative < 2:
                        relance_repetition = True
                        emit({"type": "info", "texte": _t("Le modèle répète les mêmes phrases : je l'arrête et je relance sans réflexion, avec une pénalité de répétition.")})
                        if tentative >= 1:
                            monter_en_gamme(r, corps, emit, conv["id"], _t("le modèle répète les mêmes phrases"))
                        continue
                    emit({"type": "info", "texte": _t("Le modèle répète encore les mêmes phrases : j'arrête là. Reformule en plus court, ou choisis un autre modèle.")})
                if not contenu.strip() and not appels:             # le modèle a (peut-être) réfléchi puis s'est tu : sans ceci la page restait sur « Réflexion » sans aucune réponse ni explication
                    _m.journaliser("Réponse vide du modèle {} (pensée : {} caractères, raison de fin : {!r}, essai {}, outils : {})".format(r["modele"], len(pensee), raison_fin, tentative + 1, "tools" in corps_t))
                    _observatoire.noter("relance", conv["id"], motif="réponse vide", modele=r["modele"])
                    if tentative < 2:
                        relance_vide = True
                        if tentative >= 1:
                            monter_en_gamme(r, corps, emit, conv["id"], _t("le modèle n'a rien écrit"))
                        if pensee:
                            emit({"type": "info", "texte": _t("Le modèle a réfléchi sans rien répondre : je relance (réflexion coupée pour cet essai).")})
                        else:
                            emit({"type": "info", "texte": _t("Le modèle n'a rien écrit : je relance{}.").format(_t(", sans outils cette fois") if tentative == 1 and "tools" in corps else "")})
                        continue
                    utilise = int((conv.get("jetons") or {}).get("utilise") or 0)
                    if utilise >= int(r["num_ctx"] * 0.85):
                        emit({"type": "erreur", "texte": _t("Le modèle n'a rien répondu, même après deux relances. Cause fréquente : la conversation dépasse sa fenêtre de contexte ({} jetons) ; ouvre une nouvelle conversation, ou augmente la fenêtre dans Réglages. Tu peux aussi écrire « continue ».").format(r["num_ctx"])})
                    else:
                        emit({"type": "erreur", "texte": _t("Le modèle n'a rien produit, même après trois essais (dont un sans outils), alors que la fenêtre de contexte n'est pas pleine ({} / {} jetons). Ce n'est pas ta conversation : ce modèle ne répond pas correctement ici. Essaie un autre modèle (Réglages), ou écris « continue ».").format(utilise, r["num_ctx"])})
                fini = True
                break
            except _m.Arret:
                raise
            except (urllib.error.URLError, OSError, RuntimeError) as erreur:
                http = isinstance(erreur, urllib.error.HTTPError)
                if http:
                    detail = erreur.read().decode("utf-8", "replace")[:300]
                else:
                    detail = str(erreur)[:300]
                _m.journaliser("Ollama ({}, essai {}) : {}".format("HTTP {}".format(erreur.code) if http else type(erreur).__name__, tentative + 1, detail))
                # Une erreur d'Ollama qu'on peut réessayer (HTTP 500, ou erreur arrivée dans le flux) : le genre dit quoi changer au prochain essai.
                if (http and erreur.code == 500) or isinstance(erreur, RuntimeError):
                    genre = "outil" if RE_APPEL_MAL_FORME.search(detail) else "contexte" if RE_CONTEXTE.search(detail) else "plantage" if RE_PLANTAGE.search(detail) else ""
                else:
                    genre = ""
                if not http and not isinstance(erreur, RuntimeError) and _m.AUTO_DEMARRAGE and tentative < 2 and not ctx.get("ollama_relance"):
                    ctx["ollama_relance"] = True                        # Ollama est arrêté (ou a planté) : on le démarre et on réessaie, une seule fois par demande
                    emit({"type": "info", "texte": "Ollama ne répond pas : je le démarre (quelques secondes)..."})
                    try:
                        _m.demarrer_ollama()
                    except ValueError as e2:
                        emit({"type": "erreur", "texte": _t("Ollama ne répond pas et je n'ai pas pu le démarrer : {}").format(e2)})
                        break
                    continue
                if genre in ("outil", "plantage") and not ctx.get("repli_fait") and (tentative >= 2 or not genre):
                    repli = modele_de_repli(r["modele"], genre)
                    if repli:
                        ctx["repli_fait"] = True
                        emit({"type": "info", "texte": "Le modèle {} échoue ({}). Je bascule sur {} pour cette demande.".format(r["modele"], "appels d'outils mal formés" if genre == "outil" else "plantage ou mémoire vidéo", repli)})
                        r["modele"] = repli
                        repli_demande = True
                        break
                if genre and tentative < 2:
                    if genre == "outil":
                        relance_outil = True
                        emit({"type": "info", "texte": _t("Le modèle a mal écrit un appel d'outil (erreur d'Ollama : {}). Nouvelle tentative...").format(detail[:120])})
                    elif genre == "contexte":
                        emit({"type": "info", "texte": _t("Ollama a perdu le début de la conversation (contexte trop plein : {}). Je réduis les anciens résultats et je relance, ta demande est gardée.").format(detail[:80])})
                    else:
                        emit({"type": "info", "texte": _t("Ollama a planté ou manque de mémoire vidéo ({}). J'attends quelques secondes et je relance avec moins de contexte, ta demande est gardée.").format(detail[:100])})
                        for _ in range(6):                  # le temps qu'Ollama relance son moteur (3 s), en restant interruptible
                            if stop.wait(0.5):
                                raise _m.Arret()
                    continue
                if genre == "outil":
                    emit({"type": "erreur", "texte": _t("Le modèle écrit mal ses appels d'outils ({}). Reformule en une demande plus simple, ou choisis un autre modèle dans Réglages (gemma4:26b).").format(detail[:200])})
                elif genre == "plantage":
                    emit({"type": "erreur", "texte": _t("Ollama plante encore ({}). Ferme ComfyUI ou clique sur « 🧹 VRAM », baisse la fenêtre de contexte dans Réglages, puis écris « continue ».").format(detail[:200])})
                elif http or isinstance(erreur, RuntimeError):
                    emit({"type": "erreur", "texte": _t("Ollama a répondu une erreur : {}{}").format(detail, _t(" (le modèle est-il installé ? onglet Modèles)") if http and erreur.code == 404 else "")})
                else:
                    emit({"type": "erreur", "texte": _t("Ollama ne répond pas : {}. Clique sur « Démarrer Ollama ».").format(detail)})
                break
        if repli_demande:
            continue                                 # on refait ce tour avec le modèle de repli (capacités, échantillonnage et contexte recalculés)
        if not fini:
            if contenu.strip():                      # le texte déjà écrit est gardé dans la conversation
                conv["messages"].append({"role": "assistant", "content": contenu})
            emit({"type": "info", "texte": "Ta demande est gardée dans la conversation. Écris « continue » pour que je reprenne là où ça s'est arrêté."})
            break
        if not appels and contenu and "tools" in corps:
            recu = []                                     # ce que le modèle a lu depuis la dernière demande de l'utilisateur : résultats d'outils (fichiers, pages web)
            for x in reversed(conv["messages"]):
                if x.get("role") == "user":
                    break
                if x.get("role") == "tool":
                    recu.append(str(x.get("content") or ""))
            appels, contenu_net = extraire_appels_texte(contenu, ctx["outils_autorises"], " ".join(recu))
            if appels:
                contenu = contenu_net
                emit({"type": "info", "texte": "Le modèle a écrit son appel d'outil en texte au lieu d'utiliser le mécanisme prévu : je l'exécute quand même."})
        if forcer_fin and appels:                                   # le dernier tour est sans outil : un appel quand même demandé n'est pas exécuté (ce serait recommencer la boucle)
            appels = []
            if not contenu.strip():
                emit({"type": "info", "texte": _t("Le modèle n'a pas conclu. Écris « continue », ou reformule ta demande.")})
        message = {"role": "assistant", "content": contenu}
        if appels:
            message["tool_calls"] = appels
        rappel_faux = "" if appels or corrige_affirmation or dernier_tour else (_affirmations.affirme_sans_agir(contenu, conv["messages"], ctx["outils_autorises"])
                                                                              or _affirmations.annonce_sans_agir(contenu, appels, ctx["outils_autorises"])
                                                                              or ("" if r.get("_mission") or r.get("essai_a_blanc") else _affirmations.oubli_d_ecrire(derniere_demande, conv["messages"], ctx["outils_autorises"]))
                                                                              or ("" if r.get("essai_a_blanc") else _affirmations.refus_a_tort(derniere_demande, contenu, conv["messages"], ctx["outils_autorises"])))
        if rappel_faux:
            corrige_affirmation, faux_accompli = True, (contenu, rappel_faux)
            _m.journaliser("Le modèle {} affirme avoir agi sans appeler d'outil : je le lui fais remarquer.".format(r["modele"]))
            _observatoire.noter("relance", conv["id"], motif="affirme sans agir", modele=r["modele"])
            emit({"type": "info", "texte": _t("Le modèle dit avoir agi (fichier, commande, recherche…) sans appeler d'outil : je lui demande de le faire pour de vrai.")})
            continue
        conv["messages"].append(message)
        if not appels:
            break
        for position, a in enumerate(appels):
            if stop.is_set():                        # arrêt demandé : les appels restants reçoivent une réponse, pour garder une conversation cohérente
                for b in appels[position:]:
                    conv["messages"].append({"role": "tool", "tool_name": (b.get("function") or {}).get("name", ""), "content": "Interrompu par l'utilisateur."})
                raise _m.Arret()
            f = a.get("function") or {}
            nom = f.get("name", "")
            args = normaliser_arguments(nom, f.get("arguments"), next((t["function"].get("parameters") for t in outils if t["function"]["name"] == nom), None))
            repetitions = garde.compter(nom, args)
            debut_outil = time.monotonic()
            _m.rafraichir_accords(ctx)                                  # une case cochée ou décochée pendant la réponse compte dès cet outil
            emit({"type": "outil", "nom": nom, "args": {k: (v if not isinstance(v, str) or len(v) < 300 else v[:300] + "...") for k, v in args.items()}})
            try:
                if repetitions >= _boucles.SEUIL_APPEL:                  # le même appel pour la énième fois : on n'exécute plus, on dit de passer à autre chose
                    emit({"type": "info", "texte": _t("↻ Le modèle refait le même appel ({} fois) : je lui dis de passer à autre chose.").format(repetitions)})
                    resultat = _boucles.Garde.message(repetitions)
                elif nom not in ctx["outils_autorises"]:
                    raise _m.ErreurOutil("L'outil « {} » n'est pas disponible ici (mode ou option désactivés). Outils disponibles : {}.".format(nom, ", ".join(sorted(ctx["outils_autorises"]))))
                else:
                    resultat = _m.appeler_outil(nom, args, ctx)
            except _m.Arret:
                for b in appels[position:]:
                    conv["messages"].append({"role": "tool", "tool_name": (b.get("function") or {}).get("name", ""), "content": "Interrompu par l'utilisateur."})
                raise
            except _m.ErreurOutil as erreur:
                resultat = "Erreur : " + str(erreur)
            except Exception as erreur:  # noqa: BLE001
                _m.journaliser("Outil « {} » : erreur inattendue {!r}".format(nom, erreur))
                resultat = "Erreur inattendue : " + str(erreur)[:300]
            _observatoire.noter("outil", conv["id"], outil=nom, duree_ms=int((time.monotonic() - debut_outil) * 1000), ok=not str(resultat).startswith(("Erreur", "Interrompu")), modele=r["modele"],
                                detail=str(resultat)[:100] if str(resultat).startswith("Erreur") else "")
            medias, fichiers = ctx.pop("medias", []), ctx.pop("medias_fichiers", {})          # images produites par l'outil (et où elles sont), affichées dans la conversation
            extra = {"medias": medias, "medias_fichiers": fichiers} if medias else {}
            joints = [_fichiers.entree(c) for c in ctx.pop("fichiers_joints", [])][:8]           # documents et médias créés : une carte (ouvrir, télécharger, supprimer) sous le message
            if joints:
                extra["fichiers_joints"] = joints
            try:
                _fichiers.enregistrer([dict(e, genre="fichier") for e in joints] + [_fichiers.entree_image(i, fichiers.get(i)) for i in medias if fichiers.get(i)], conv["id"])
            except Exception as erreur:  # noqa: BLE001  (le registre aide au ménage, il ne doit jamais gêner une réponse)
                _m.journaliser("Registre des fichiers créés : {!r}".format(erreur))
            affiche = _t("(résultat transmis à l'assistant, non affiché)") if (nom in OUTILS_INTERNES or _mcp.est_outil(nom)) and ("CONTENU WEB NON FIABLE" in resultat[:60] or _mcp.MARQUEUR in resultat[:60]) else resultat[:1500]          # la recherche web sert à l'assistant, pas à remplir la conversation : c'est à lui d'en tirer la réponse
            emit(dict({"type": "resultat", "nom": nom, "texte": affiche}, **extra))
            conv["messages"].append(dict({"role": "tool", "tool_name": nom, "content": resultat[:_m.LECTURE_MAX + 2000]}, **extra))
            _m.conv_ecrire(conv)                        # enregistré à chaque étape : un plantage du PC en pleine demande ne perd que l'étape en cours
        if garde.abandon:
            if forcer_fin:
                break
            forcer_fin = True
            emit({"type": "info", "texte": _t("↻ Le modèle tourne en rond (le même appel {} fois) : je lui demande de conclure avec ce qu'il a déjà obtenu.").format(_boucles.SEUIL_ABANDON)})
            continue
    else:
        emit({"type": "info", "texte": "Beaucoup d'étapes d'outils dans ce tour : écris « continue » pour que je poursuive."})
