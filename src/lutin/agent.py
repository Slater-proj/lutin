"""Le dialogue avec Ollama : démarrage et état d'Ollama, requêtes au modèle, boucle de l'agent (tours d'outils), résumé des conversations, titres. L'état reste dans moteur (« _m.NOM »)."""
from pathlib import Path
from . import archive as _archive
from . import model_info as _infos
from . import false_claims as _affirmations
from . import loop_detection as _boucles
from . import observatory as _observatoire
from . import model_router as _routeur
from . import news as _actualites
from . import mcp as _mcp
from . import llamacpp_engine as _llamacpp
from . import engines as _moteurs
from . import engine_capabilities as _aptitudes
from . import ollama_client
from . import produced_files as _fichiers
from . import mission as _mission
from . import offline as _hl
from . import images as _images
from . import modes as _modes
from . import thinking as _pensee
from . import attachments as _pieces
from . import progress_sheet as _suivi
from . import tool_table as _tool_table
from . import turn_state as _etat_tour
from . import prompt_layout as _disposition
from . import claude_project as _pc
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
import types
import urllib.request
from . import core as _m


# --------------------------------------------------------------------------- dialogue avec Ollama
RE_APPEL_MAL_FORME = re.compile(r"XML|syntax|parse|parsing|tool", re.I)


RAPPEL_VIDE = "Ta dernière réponse était vide. Réponds maintenant à la demande de l'utilisateur, en t'appuyant sur ce que tu viens de lire ou de faire, ou appelle l'outil nécessaire."
RAPPEL_REPETITION = "Ta réflexion tournait en rond (les mêmes phrases revenaient). Ne réfléchis plus : réponds maintenant directement et brièvement à la demande de l'utilisateur."
RAPPEL_APPEL = "Ton dernier appel d'outil était mal formé et a été rejeté. Recommence en appelant l'outil avec des arguments simples ; pour un long contenu, fais plusieurs petits appels."


# Le gabarit de conversation du modèle (jinja, dans le modèle lui-même) refuse les outils ou le rôle « tool » : Ollama répond 400 « Unable to generate parser for this template »
# (certains Mistral : « Only user, system and assistant roles are supported », ou « roles must alternate »). Ce n'est ni un plantage ni un appel mal écrit : ce modèle ne peut pas servir avec des outils.
RE_GABARIT = re.compile(r"Unable to generate parser|raise_exception|roles? (are|must)|chat template|jinja|template", re.I)
GABARIT_SANS_OUTILS = set()          # modèles dont le gabarit refuse les outils (gardé aussi dans gabarits.json, pour ne pas refaire l'essai à chaque démarrage)


def _fichier_gabarits():
    return _m.DONNEES / "gabarits.json"


def gabarits_connus():
    GABARIT_SANS_OUTILS.update(str(x) for x in (_m.lire_json(_fichier_gabarits(), []) or []) if isinstance(x, str))
    return GABARIT_SANS_OUTILS


def noter_gabarit(modele):
    GABARIT_SANS_OUTILS.add(modele)
    try:
        _m.ecrire_atomique(_fichier_gabarits(), json.dumps(sorted(GABARIT_SANS_OUTILS)))
    except OSError:
        pass


def aplatir_sans_outils(corps):
    """Le même échange sans outils ni rôle « tool » : un résultat d'outil devient un message de l'utilisateur, un appel d'outil une phrase, et deux messages de même rôle à la suite sont fusionnés
    (les gabarits les plus stricts exigent l'alternance utilisateur / assistant). Ce que le modèle a lu reste donc sous ses yeux, en texte."""
    sortie = []
    for m in corps.get("messages", []):
        role, texte = m.get("role"), str(m.get("content") or "")
        if role == "tool":
            role, texte = "user", "[" + _t("Résultat de l'outil") + " " + str(m.get("tool_name") or "") + "]\n" + texte
        elif role == "assistant" and m.get("tool_calls"):
            appels = ", ".join(str((c.get("function") or {}).get("name") or "") for c in m["tool_calls"])
            texte = (texte + "\n" if texte else "") + "[" + _t("Appel de l'outil") + " " + appels + "]"
        elif role not in ("system", "user", "assistant"):
            role = "user"
        if sortie and sortie[-1]["role"] == role and role != "system":
            sortie[-1]["content"] += "\n\n" + texte
        else:
            sortie.append({"role": role, "content": texte})
    return {k: v for k, v in dict(corps, messages=sortie).items() if k != "tools"}


RE_REPETITION = re.compile(r"token repeat limit|repeat limit reached|prediction aborted", re.I)      # le modèle s'est mis à radoter en boucle : Ollama coupe la génération
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
    from . import model_fit
    profil = model_fit.profil_pret()
    return profil is None or not profil.sans_gpu()


def _estimer_avant_charge(r, emit):
    """Avant de charger le modèle : s'il ne tient pas (ou à peine), le dire et proposer quoi faire, une fois par modèle et par demi-heure. Ne bloque rien (le garde-fou des ressources s'en charge)."""
    try:
        from . import model_fit, memory_estimate
        m = next((x for x in _m._CATALOGUE["modeles"] if x["id"] == r["modele"]), None)
        profil = model_fit.profil_pret()
        if m is None or profil is None or moteur_actuel(r).en_memoire(r["modele"]):
            return
        e = memory_estimate.estimate(m, int(r["num_ctx"]), profil)
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
    """Comment cette conversation garde son fil : toujours « fichier », la fiche de suivi (ADR 0019, décision 1). Le résumé par le modèle et la
    question « fiche ou résumé ? » sont retirés ; les anciennes valeurs (« resume », « demander ») d'un réglage ou d'une conversation restent
    acceptées et valent la fiche. Une conversation qui a déjà un résumé le garde en tête de la requête (bloc_du_debut)."""
    return "fichier"


def reformuler_recherche(texte, r):
    """La demande de l'utilisateur transformée en requête de recherche web (3 à 8 mots-clés, fautes corrigées) par un appel court au modèle des petites tâches. '' si le modèle ne répond pas : l'appelant nettoie alors la demande lui-même."""
    try:
        rep = moteur_actuel(r).chat({"model": modele_annexe(r), "stream": False, "think": False, "options": _m.options_modele(r, 0.1),
                                     "messages": [{"role": "system", "content": "Tu transformes une demande en requête pour un moteur de recherche web. Réponds par la requête seulement : 3 à 8 mots-clés, sans phrase, sans ponctuation, sans date, fautes corrigées, dans la langue de la demande. Garde le sujet précis demandé."},
                                                  {"role": "user", "content": str(texte)[:300]}]}, 30)
        return (rep.get("message", {}).get("content") or "").strip()
    except (urllib.error.URLError, OSError, ValueError):
        return ""


PART_REQUETE = 0.68          # part de la fenêtre que la requête peut prendre (ajuster_contexte rogne au-delà) : le reste est la place de la réponse
PART_MAX = 0.85              # jusqu'où la requête peut aller quand le système et les outils ne laissent pas à l'historique son plancher (un quart de la fenêtre)


def place_de_l_historique(conv, r, outils=None):
    """Ce que la requête laisse aux messages de la conversation, en jetons : la part de la fenêtre que garde ajuster_contexte, moins les outils
    réellement envoyés et le message système (ADR 0018). Les seuils du retrait et du rappel se règlent sur ce chiffre : sur une fenêtre de
    8 192 jetons, les schémas des outils en prennent près de la moitié, et la requête était rognée bien avant que le début sorte (le début de
    la requête changeait à chaque réponse, le cache du moteur ne servait plus). Jamais moins du quart de la fenêtre : en dessous, chaque réponse
    demanderait un retrait."""
    outils = outils_du_mode(r) if outils is None else outils
    prise = (len(json.dumps(outils, ensure_ascii=False)) + len(consignes_systeme(r) + _fichiers.instruction_folder(conv))) // 3
    return max(int(r["num_ctx"] * PART_REQUETE) - prise, r["num_ctx"] // 4)


PART_DEBUT_FICHE = 0.5        # la fiche de suivi démarre quand l'historique atteint cette part du seuil du retrait (ADR 0019)


def fiche_active(conv, r, place=None):
    """Vrai quand la fiche de suivi tient le fil de cette conversation (ADR 0019) : une mission, une fiche déjà remplie (par le scribe, le modèle ou la
    personne), un début déjà retiré ou résumé, ou un historique à mi-chemin du seuil du retrait. En deçà, la conversation est courte : le modèle a tout
    sous les yeux, la fiche ne ferait que répéter les dernières demandes, son outil prendrait 240 jetons, et le scribe coûterait un appel au modèle
    tous les trois échanges pour rien. À mi-chemin, le scribe a le temps de lire le début avant que le retrait ait besoin de lui.
    place : place_de_l_historique, si elle est déjà calculée."""
    if r.get("_mission") or conv.get("depart") or conv.get("resume"):
        return True
    try:
        if conv.get("id") and any(_suivi.read(conv["id"]).values()):
            return True
    except ValueError:
        pass
    msgs = conv.get("messages") or []
    if not msgs:
        return False
    place = place_de_l_historique(conv, r) if place is None else place
    return estimer(msgs) >= int(min(int(r["num_ctx"] * SEUIL_ELAGAGE), place) * PART_DEBUT_FICHE)


def repondre_choix_memoire(ident, choix, garder):
    """L'ancienne réponse de la page à la question « fiche ou résumé ? ». La question n'est plus posée (ADR 0019) : un choix connu reçoit « pas de
    question en attente » (False), un choix inconnu une erreur, comme avant."""
    if choix not in ("resume", "fichier"):
        raise ValueError(_t("Mémoire des longues conversations inconnue (resume ou fichier)."))
    return False


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
    sections = _suivi.read(ident)
    consigne = ("Tu tiens la fiche de suivi d'une conversation. On te donne la fiche actuelle et les derniers échanges. Réponds en JSON avec ces clés (listes de phrases courtes, 150 caractères au plus) : "
                "objectif (seulement si le but a changé ou vient d'être dit), plan (seulement si un plan vient d'être décidé ou modifié), etape (l'étape en cours maintenant), decisions (NOUVELLES décisions prises), "
                "fait (ce qui vient d'être terminé), ouvert (NOUVELLES questions restées sans réponse), resolu (questions de la fiche qui ont maintenant une réponse, recopiées telles quelles). "
                "N'invente rien : ne note que ce qui est dit dans les échanges. Liste vide si rien à ajouter.")
    try:
        corps_scribe = {"model": modele_annexe(r), "stream": False, "think": False, "format": "json", "options": _m.options_modele(r, 0.1),
                        "messages": [{"role": "system", "content": consigne}, {"role": "user", "content": "FICHE ACTUELLE :\n" + _suivi.serialize(ident, sections) + "\n\nDERNIERS ÉCHANGES :\n" + echange}]}
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
        return [x for x in (_suivi.clean_line(str(i)) for i in v if i) if x]
    n = 0
    try:
        for cle in ("objectif", "plan", "etape"):                                      # remplacés seulement si le modèle a quelque chose à dire
            nouveau = lignes(cle)[:LIGNES_REMPLACEES.get(cle, 3)]
            if nouveau and nouveau != sections[cle]:
                _suivi.modify(ident, cle, "\n".join(nouveau), "remplacer")
                n += len(nouveau)
        for cle in ("decisions", "fait", "ouvert"):                                   # ajoutés sans doublon
            existantes = {x.lower() for x in sections[cle]}
            neuves = [x for x in lignes(cle) if x.lower() not in existantes][:SCRIBE_AJOUTS_MAX]
            if neuves:
                _suivi.modify(ident, cle, "\n".join(neuves), "ajouter")
                n += len(neuves)
        for question in lignes("resolu")[:SCRIBE_AJOUTS_MAX]:                         # une question ouverte n'est retirée que si le modèle la recopie vraiment (jamais une décision)
            if len(question) >= 12 and any(question.lower() in x.lower() for x in sections["ouvert"]):
                _suivi.modify(ident, "ouvert", question, "retirer")
    except (ValueError, _m.ErreurOutil) as erreur:
        _m.journaliser("Scribe : consigne refusée (conversation {}) : {!r}".format(ident, erreur))
    return n


LIGNES_REMPLACEES = {"objectif": 3, "plan": 12, "etape": 3}


def outils_du_mode(r):
    """Les outils envoyés au modèle : ceux du mode (voir modes.py), sans web si la case « Web » est décochée ou en mode hors ligne, sans l'outil d'images s'il n'est pas branché."""
    exclus = _modes.excluded_tools(r.get("mode"), [t["function"]["name"] for t in _m.OUTILS])
    if not r.get("web", True) or _hl.is_active():
        exclus |= OUTILS_WEB
    exclus |= set(r.get("outils_desactives") or [])                     # outils coupés par l'utilisateur (Réglages > Outils)
    exclus |= _tool_table.spare_tools(r.get("num_ctx"))                 # petite fenêtre : les outils qu'un autre couvre laissent leur place à la conversation ; à 4 096 jetons, un noyau seulement (ADR 0018)
    if not _m.OUTIL:
        exclus |= _modes.IMAGE_TOOLS
    if not r.get("fiche_active"):
        exclus.add("suivi")                                             # conversation courte : pas encore de fiche de suivi (fiche_active)
    elif r.get("fiche_scribe", True) and int(r.get("num_ctx") or 0) and int(r["num_ctx"]) <= _tool_table.TINY_WINDOW:
        exclus.add("suivi")                                             # 4 096 jetons : le scribe tient la fiche, l'outil (240 jetons, 6 % de la fenêtre) laisse sa place (ADR 0019, ADR 0018 décision 9)
    if not r.get("_mission"):
        exclus |= {"mission_terminer", "mission_bloquee"}               # ces deux outils n'existent que pendant une mission longue
    from . import addons
    if not addons.actif("comfyui"):
        exclus |= {"comfy_modeles", "comfy_generer"}                    # les outils de ComfyUI n'existent que si l'addon est activé
    if not addons.actif("voicestudio"):
        exclus |= {"voix_liste", "voix_parler", "voix_transcrire", "voix_cloner"}          # idem pour les outils de voix
    outils = [t for t in _m.OUTILS if t["function"]["name"] not in exclus]
    if not _modes.without_tools(r.get("mode")):
        try:
            outils += _mcp.exposed_tools(_modes.read_only(r.get("mode")))          # connecteurs MCP : seulement les outils autorisés un par un (voir mcp.py)
        except Exception as erreur:  # noqa: BLE001  (un connecteur en panne ne doit pas empêcher de répondre)
            _m.journaliser("Connecteurs MCP : liste impossible ({!r}).".format(erreur))
    if any(t["function"]["name"] == "comfy_generer" for t in outils):
        try:
            from . import addons_comfyui
            outils = [addons_comfyui.adapt_tool(t) if t["function"]["name"] == "comfy_generer" else t for t in outils]
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
    else:
        from . import local_ports
        local_ports.check(_m.OLLAMA)          # une lecture (liste, état) : un Ollama local arrêté se sait en 0,25 s, pas en 2 s sous Windows
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
            from . import docker_engines
            choisi = docker_engines.setting_folder_engines()          # tu as choisi un dossier pour tous les moteurs : Ollama s'y installe aussi (sous-dossier ollama)
            if choisi:
                return Path(choisi) / "ollama"
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / "Programs" / "Ollama" if base and os.name == "nt" else None

    def dossier_installation(self):
        """Le dossier passé à l'installateur d'Ollama (Windows) : celui choisi pour Ollama seul, sinon le dossier des moteurs si tu en as choisi un, sinon l'emplacement habituel d'Ollama (None)."""
        propre = self.config().get("dossier")
        if propre:
            return propre
        from . import docker_engines
        return str(self.dossier_defaut()) if os.name == "nt" and docker_engines.setting_folder_engines() else None

    def info_dossier(self):
        """Comme pour llama.cpp : où il s'installe (choisi avant l'installation, sous Windows seulement : l'installateur d'Ollama accepte un dossier) et où sont ses modèles (réglés dans l'onglet Modèles)."""
        exe = chemin_ollama()
        defaut = self.dossier_defaut()
        choisi = self.config().get("dossier")
        actuel = Path(exe).parent if exe else (Path(choisi) if choisi else defaut)
        if os.environ.get("LUTIN_DOCKER"):
            from . import docker_engines
            defaut = docker_engines.ollama_folder()
            actuel = Path(exe).parent.parent if exe and defaut and str(defaut) in exe else (defaut or actuel)
        modeles = __import__("lutin.locations", fromlist=["x"]).models_folder()
        return {"actuel": str(actuel or ""), "propose": "", "defaut": str(defaut or ""), "personnalise": bool(choisi), "libre_go": {"actuel": _llamacpp.espace_libre(actuel), "propose": None, "defaut": _llamacpp.espace_libre(defaut)},
                "installe": exe is not None, "modifiable": os.name == "nt" and not os.environ.get("LUTIN_DOCKER"),
                "modeles": {"actuel": str(modeles), "libre_go": _llamacpp.espace_libre(modeles), "modifiable": False}}

    def _retenir_dossier_modeles(self):
        """Le dossier où Ollama range ses modèles AVANT une installation, s'il contient des modèles : une installation (ou une réinstallation) peut le faire retomber sur le dossier par défaut, vide."""
        try:
            from . import locations
            dossier = locations.models_folder()
            if (Path(dossier) / "manifests").is_dir():
                locations.remember_seen_folder(dossier)
                return str(dossier)
        except (OSError, ValueError):
            pass
        return ""

    def _rendre_dossier_modeles(self, dossier):
        """Après l'installation : le même dossier de modèles est remis (configuration de Lutin + variable de l'utilisateur), si ce n'était pas le dossier par défaut d'Ollama."""
        if not dossier or Path(dossier) == Path.home() / ".ollama" / "models":
            return
        try:
            from . import locations
            locations.set_models_folder(dossier)
        except (OSError, ValueError) as erreur:
            _m.journaliser("Dossier des modèles d'Ollama non rétabli après l'installation ({!r}).".format(erreur))

    def statut(self):
        actif = etat_ollama()["actif"]
        installe = bool(chemin_ollama()) or actif
        return {"installe": installe, "actif": actif, "version": "", "mode": "gere",
                "detail": _t("Ollama répond.") if actif else (_t("Installé, mais arrêté.") if installe else _t("Pas installé."))}

    def actions(self):
        if os.environ.get("LUTIN_DOCKER"):
            from . import docker_engines
            st = self.statut()
            return docker_engines.actions_ollama(st["installe"], st["actif"], _hl.is_active())
        st = self.statut()
        hors = _hl.is_active()
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
            installer = _t("Sous Linux, l'installation demande les droits administrateur : lance dans un terminal « {} ».").format(ollama_client.COMMAND_LINUX)
            retirer = _t("Sous Linux, la désinstallation demande les droits administrateur : suis la procédure de https://docs.ollama.com/linux#uninstall.")
        return {"mettre_a_jour": {"possible": False, "raison": _t("Relance la commande d'installation dans un terminal.") if st["installe"] else pas_installe},
                "installer": {"possible": False, "raison": deja if st["installe"] else installer}, "desinstaller": {"possible": False, "raison": retirer if st["installe"] else pas_installe},
                "reinstaller": {"possible": False, "raison": _t("Relance la commande d'installation dans un terminal.") if st["installe"] else pas_installe}, "demarrer": demarrer, "arreter": arreter}

    def faire(self, action, progression):
        a = self.actions().get(action) or {}
        if not a.get("possible"):
            raise ValueError(a.get("raison") or _t("Action impossible avec ce moteur."))
        if os.environ.get("LUTIN_DOCKER"):
            from . import docker_engines
            try:
                gpus = getattr(_moteurs.CONTEXT["profil"](), "gpus", None) or []
                docker_engines.do_ollama(action, progression, lambda: etat_ollama()["actif"], rocm=any(getattr(g, "fabricant", "") == "amd" for g in gpus))
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
                ollama_client.install_windows(cache, progression)          # par-dessus l'existant : le même dossier, rien n'est désinstallé
                self._rendre_dossier_modeles(dossier_modeles)
                _m.demarrer_ollama()
            elif action in ("desinstaller", "reinstaller"):
                progression(_t("Arrêt d'Ollama…"), 0, 0)
                _m.arreter_ollama()
                progression(_t("Désinstallation…"), 0, 0)
                ollama_client.uninstall_windows()
                if action == "reinstaller":
                    ollama_client.install_windows(cache, progression, dossier=self.dossier_installation())
                    self._rendre_dossier_modeles(dossier_modeles)
                    _m.demarrer_ollama()
            elif action == "installer":
                ollama_client.install_windows(cache, progression, dossier=self.dossier_installation())
                self._rendre_dossier_modeles(dossier_modeles)
                _m.demarrer_ollama()
        except ollama_client.ErreurOllama as e:
            raise ValueError(str(e))
        CAPACITES.clear()

    def telechargeable(self):
        if _hl.is_active():
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

    def aptitudes(self):
        # Ollama lit et écrit lui-même les appels d'outils, garde tout seul le début d'une requête, accepte un schéma JSON (« format »), n'a pas de place réservée par conversation ;
        # un modèle trop gros pour la carte déborde sur le processeur au lieu d'échouer ; et Lutin sait le démarrer.
        return _aptitudes.EngineCapabilities(tools=_aptitudes.NATIVE, grammar=_aptitudes.YES, slots=_aptitudes.NO, prompt_cache=_aptitudes.AUTOMATIC, embeddings=_aptitudes.YES,
                                             token_counts=_aptitudes.YES, starts_on_demand=True, spills_to_cpu=True)

    def demarrer_sur_demande(self):
        return _m.demarrer_ollama()

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


_moteurs.save(MoteurOllama())
_moteurs.CONTEXT.update(donnees=lambda: _m.DONNEES, en_docker=lambda: bool(os.environ.get("LUTIN_DOCKER")), hors_ligne=lambda: _hl.is_active(),
                         profil=lambda: __import__("lutin.model_fit", fromlist=["x"]).profil_pret(),
                         profil_attendu=lambda: __import__("lutin.model_fit", fromlist=["x"]).profil_attendu(),
                         dossier_ollama=lambda: (None if os.environ.get("LUTIN_DOCKER") else __import__("lutin.locations", fromlist=["x"]).models_folder()))
_moteurs.save(_llamacpp.MoteurLlamaCpp())
_moteurs.save(_llamacpp.MoteurExterne())


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
        from . import docker_engines
        return docker_engines.path_ollama()          # celui que Lutin a installé dans le dossier des moteurs (volume)
    exe = shutil.which("ollama")
    if exe:
        return exe
    if os.environ.get("LUTIN_TESTS") == "1":          # tests never look at the real machine's standard install folders (tests/context.py also removes Ollama from the PATH)
        return ""
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
            infos = _infos.already_known(entree["id"], _m.DONNEES)
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
            infos = _infos.already_known(nom, _m.DONNEES)
            if infos is None:
                a_lire.append(nom)
            elif infos:
                entree.update({k: infos[k] for k in ("params_b", "actifs_b", "ctx_max", "kv_mo_1k", "quantification") if k in infos})          # les vrais chiffres d'Ollama au lieu d'une estimation
                if "capacites" in infos:
                    entree["capacites"] = infos["capacites"]
                if infos.get("embedding"):
                    entree["embedding"] = True                                          # la page ne propose ni « Utiliser » ni banc d'essai pour un modèle de recherche
                entree["phrase"] = _infos.sentence(infos)
        liste.append(entree)
    if a_lire:
        _infos.ask(a_lire, _m.DONNEES, lambda n: ollama_json("/api/show", {"model": n}, 8))          # en arrière-plan : la liste s'améliore au rafraîchissement suivant
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
    _hl.require_online("télécharger un modèle")
    if moteur_actuel().id != _moteurs.OLLAMA and not hasattr(moteur_actuel(), "telecharger_ollama"):
        raise ValueError(_t("Ce moteur gère ses modèles lui-même : installe-les depuis le moteur."))
    if modele not in [m["id"] for m in _m.MODELES] and not RE_NOM_MODELE.match(modele):
        raise ValueError("Nom de modèle invalide.")
    catalogue_m = next((m for m in _m._CATALOGUE["modeles"] if m["id"] == modele), None)
    if catalogue_m is not None:          # un modèle du catalogue que ce moteur ne sait pas faire tourner n'est jamais installé
        from . import model_compat
        verdict = model_compat.evaluate(catalogue_m, moteur_actuel(), etat_moteur()["installes"])
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
        restants = [n for n in etat_ollama().get("installes", []) if n != modele and not embeddings.is_search_model(n)]
        if restants:
            nouveau = restants[0]
            _m.enregistrer_reglages({"modele": nouveau})
    return {"ok": True, "modele": modele, "nouveau_actif": nouveau}


PART_CONTEXTE = 0.05         # part de la fenêtre que CONTEXTE.md peut prendre (décision du mainteneur, 2026-11-19 : le borner selon la fenêtre)
CONTEXTE_MIN = 600           # caractères relus au moins, même sur une toute petite fenêtre


def limite_contexte(num_ctx):
    """Les caractères de CONTEXTE.md relus à chaque requête : 5 % de la fenêtre, jamais moins de CONTEXTE_MIN ni plus de LIMITE_CONTEXTE. Sur 4 096
    jetons, le texte livré (763 jetons) prenait 19 % de la fenêtre ; il est entier dès 16 384 jetons. Le fichier n'est pas modifié : seul ce que le
    modèle en relit change, et la coupure est dite (COUPURES)."""
    if not num_ctx:
        return _m.LIMITE_CONTEXTE
    return max(CONTEXTE_MIN, min(_m.LIMITE_CONTEXTE, int(num_ctx * PART_CONTEXTE * _disposition.CHARS_PER_TOKEN)))


def consignes_systeme(r):
    contexte, memoire = _m.lire_memoire("CONTEXTE.md"), _m.lire_memoire("MEMOIRE.md")
    mode = _modes.instruction(r["mode"])
    skills = _m.lister_skills()
    bloc_skills = ""
    if skills:
        lignes = "\n".join("- skills/{} : {}{}".format(nom, titre, (_t(" — à lire quand ") + d) if (d := _m.description_skill(nom)) else "") for nom, titre in skills)
        bloc_skills = (_t("\n\n# SKILLS (fiches du projet, à lire avec l'outil « lire » quand le sujet t'est demandé)\n"
                       "Ces fiches décrivent le projet de l'utilisateur (univers, règles, outil). Lis-les au moment où tu en as besoin, pas avant.\n") + lignes + "\n")
    return (_t("Tu es Lutin, l'assistant local de l'utilisateur. Tu réponds dans la langue de l'utilisateur, de façon directe et concise. Tu disposes d'outils pour lire et modifier le projet : utilise-les plutôt que de deviner. "
            "Chaque modification de fichier garde une sauvegarde de l'ancienne version et passe par l'accord de l'utilisateur, sauf s'il a activé l'accord automatique.\n\n") + mode + _t("\n\n# CONTEXTE DU PROJET (memoire/CONTEXTE.md)\n") + _m.borner_contexte(contexte, limite_contexte(r.get("num_ctx") or 0)) + _t("\n\n# NOTES DURABLES (memoire/MEMOIRE.md)\n") + (_m.texte_memoire(memoire) or _t("(aucune pour l'instant)"))
            + bloc_skills
            + (_mission.instruction_system() if r.get("_mission") else "")
            + ("" if r.get("mode") in ("discussion", "recherche") else _t("\n\n# CRÉER UN FICHIER\nQuand on te demande de créer ou d'écrire un fichier (docker-compose, script, configuration, document), appelle l'outil « ecrire » avec le chemin et le contenu complet, y compris après une recherche web. Ne te contente pas de montrer le contenu dans ta réponse."))
            + (_t("\n\n# ESSAI À BLANC\nTes écritures et tes commandes ne sont PAS exécutées : c'est une simulation, l'utilisateur voit ce que tu proposes. Propose ce que tu ferais (fichiers, contenu, commandes), sans insister ni réessayer. Ce que tu simules n'existe PAS ensuite : un fichier « créé » ici ne se relira pas, une commande « lancée » n'a rien produit. Ne dis jamais que c'est fait : conclus par « voici ce que je ferais ». Lire et chercher fonctionnent normalement.\n") if r.get("essai_a_blanc") else "")
            + (_t("\n\n# DÉBUT DE LA CONVERSATION\nLes premiers échanges ne sont plus tous sous tes yeux (fiche de suivi ou résumé). Pour retrouver un détail précis (une décision, un nom, un chiffre, un texte), appelle « rappeler » avec quelques mots-clés et ici=true : ne le devine pas.\n") if r.get("rappel_ici") else "")
            + _pc.prompt_block(_m.RACINE)
            + bloc_plan(r)
            + _t("\n\nDate : ") + datetime.now().strftime("%Y-%m-%d") + _t(". Dossier du projet : ") + str(_m.RACINE))


def bloc_plan(r):
    """Le plan du projet dans le prompt (un quart de la fenêtre au plus, 6 500 caractères au plus) : le modèle sait où chercher sans dix recherches."""
    sans_lister = "lister" in _tool_table.spare_tools(r.get("num_ctx"))          # fenêtre minuscule : « lister » n'est pas envoyé (ADR 0018)
    plan = _m.plan_text(min(_m.PLAN_MAX, int(r["num_ctx"] * 0.25)), "  ... (suite : « executer » avec dir ou ls)" if sans_lister else None)
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
    msgs = [{"role": "system", "content": consignes_systeme(r) + _fichiers.instruction_folder(conv) + _m.text_tasks(conv)}]
    if conv.get("resume"):
        msgs.append({"role": "user", "content": conv["resume"]})
    msgs += conv.get("messages", [])
    if conv.get("id"):
        try:
            msgs.append({"role": "user", "content": _suivi.text_for_model(conv["id"], r["num_ctx"])})          # la place de la fiche compte dans la jauge
        except ValueError:
            pass
    outils = outils_du_mode(dict(r, fiche_active=fiche_active(conv, r)))
    return {"utilise": estimer(msgs) + len(json.dumps(outils, ensure_ascii=False)) // 3, "total": r["num_ctx"], "reel": False}          # les outils réellement envoyés, pas toute la liste


# Une erreur d'Ollama qui parle d'une conversation trop longue pour la fenêtre : des expressions précises. Le mot « prompt » ou « context » seul se retrouve dans des erreurs sans rapport (gabarit, option inconnue…).
RE_CONTEXTE = re.compile(r"no query found|context (length|window|size|limit)|(exceeds?|exceeded) .{0,40}(context|maximum|limit)|maximum context|n_ctx|too long|truncat(ed|ing) (the )?(prompt|input)|prompt .{0,30}(too long|exceed)|input .{0,30}too (long|large)", re.I)


COUPURES_DITES = set()          # (conversation, fichier, taille) : l'avertissement « fichier de mémoire trop long » n'est donné qu'une fois


DITS = {"reduction": {}, "rappel": {}}          # id de conversation -> ce qui a déjà été annoncé (une information répétée à chaque réponse n'informe plus : elle prend de la place pour rien)
PAS_DE_NOUVEL_AVIS = 6          # une réduction du contexte n'est redite que si elle a grossi d'au moins ça (résultats raccourcis + messages retirés)


RE_MEMOIRE_VIDEO = re.compile(r"insufficient\s+vram|out\s+of\s+memory|cuda\s+out\s+of\s+memory|failed\s+to\s+load|not\s+enough\s+(?:gpu\s+)?memory|oom\b", re.I)


def nom_du_moteur(r):
    """Le nom que l'utilisateur reconnaît pour le moteur de cette réponse (Ollama, llama.cpp, ExLlamaV3, Colibri, LM Studio…) : une erreur d'ExLlamaV3 ne doit pas commencer par « Ollama »."""
    try:
        from . import engine_metrics
        return engine_metrics.display_name(moteur_actuel(r))
    except Exception:  # noqa: BLE001  (un nom de plus : jamais une réponse perdue)
        return "Ollama"


def annoncer_reduction(rapport, emit, ctx, num_ctx):
    """Dit à l'utilisateur, avec des chiffres, ce qui a été raccourci ou retiré pour tenir dans la fenêtre de contexte (au lieu de le faire sans rien dire). Une seule fois par conversation tant que
    la situation ne change pas : un nouvel avis seulement si la réduction a nettement grossi (le contexte est plein en continu dans une longue conversation, le dire à chaque réponse est du bruit)."""
    total = sum(rapport.values()) if rapport else 0
    ident = (ctx.get("conv") or {}).get("id") or ctx.get("conversation") or "?"
    deja = DITS["reduction"].get(ident, 0)
    if not total or total <= ctx.get("reduction_dite", 0) or (deja and total < deja + PAS_DE_NOUVEL_AVIS):
        return
    ctx["reduction_dite"] = total
    DITS["reduction"][ident] = total
    parties = []
    if rapport["raccourcis"] or rapport["tronques"]:
        parties.append(_t("{} ancien(s) résultat(s) d'outil raccourci(s)").format(rapport["raccourcis"] + rapport["tronques"]))
    if rapport["retires"]:
        parties.append(_t("{} échange(s) d'outils retiré(s)").format(rapport["retires"]))
    if rapport["tours"]:
        parties.append(_t("{} ancien(s) message(s) retiré(s)").format(rapport["tours"]))
    emit({"type": "info", "texte": _t("↧ Pour tenir dans la fenêtre de contexte ({} jetons) : {}. Ce qui a été raccourci peut se relire (outil « lire »). Une fenêtre plus grande (Réglages > Conversation) évite cela.").format(num_ctx, ", ".join(parties))})


def ajuster_contexte(msgs, num_ctx, facteur=1.0, outils=None, rapport=None):
    """Garde la requête de l'utilisateur et le plus récent ; rétrécit les anciens résultats d'outils, puis retire les anciens échanges d'outils,
    pour que le total tienne dans num_ctx (avec de la place pour la réponse). outils : les outils réellement envoyés (leur place est déduite).
    rapport (un dictionnaire) : reçoit ce qui a été raccourci ou retiré (« raccourcis », « retires », « tronques », « tours »), pour le dire à l'utilisateur."""
    rapport = rapport if rapport is not None else {}
    rapport.update(raccourcis=0, retires=0, tronques=0, tours=0)
    poids_outils = len(json.dumps(_m.OUTILS if outils is None else outils, ensure_ascii=False)) // 3
    budget = int(num_ctx * PART_REQUETE * facteur) - poids_outils
    # Le plancher de place_de_l_historique (un quart de la fenêtre au-delà du message système) vaut aussi ici : sans lui, sur une petite fenêtre, le
    # système et les outils prenaient toute la part de la requête et même le dernier échange était retiré (ADR 0018, suite d'évaluation). La réponse
    # garde toujours au moins 1 - PART_MAX de la fenêtre ; une nouvelle tentative (facteur < 1) réduit l'un et l'autre.
    systeme = estimer(msgs[:1]) if msgs and msgs[0].get("role") == "system" else 0
    budget = max(budget, min(systeme + int(num_ctx // 4 * facteur), int(num_ctx * PART_MAX * facteur) - poids_outils))
    msgs = [dict(m) for m in msgs]
    dernier_user = max((i for i, m in enumerate(msgs) if m["role"] == "user"), default=-1)
    # les messages épinglés ne sont jamais retirés, dans la limite d'un quart du budget (les plus récents d'abord : au-delà, les plus anciens redeviennent retirables)
    protege, total = set(), 0
    for i in reversed(range(len(msgs))):
        if msgs[i].get("epingle"):
            total += len(json.dumps(msgs[i], ensure_ascii=False)) // 3
            if total <= budget // 4:
                protege.add(id(msgs[i]))

    # la demande de départ (le premier message de l'utilisateur encore là, avant la question actuelle) n'est jamais retirée : sans elle, une longue
    # conversation perd son objectif et le modèle le redemande. Trop longue, elle est raccourcie (un sixième du budget au plus).
    depart = next((i for i in range(1, max(dernier_user, 0)) if msgs[i]["role"] == "user" and not str(msgs[i].get("content", "")).startswith(("[Résumé", "[Fiche de suivi", "[Extraits"))), None)
    if any(str(m.get("content", "")).startswith("[Résumé") for m in msgs[1:]):
        depart = None                  # le résumé porte la demande de départ (bloc_du_debut) : le plus ancien message restant n'est qu'un vieux message, il ne vaut pas le dernier échange
    if depart is not None:
        plafond = max(300, (budget // 6) * 3)
        if len(str(msgs[depart].get("content", ""))) > plafond:
            msgs[depart]["content"] = str(msgs[depart]["content"])[:plafond] + "\n[... demande de départ raccourcie]"
        protege.add(id(msgs[depart]))

    def taille():
        return estimer(msgs)
    # 1) résultats d'outils anciens raccourcis (on garde les deux plus récents entiers)
    outils = [i for i, m in enumerate(msgs) if m["role"] == "tool"]
    for i in outils[:-2]:
        if taille() <= budget:
            break
        if len(msgs[i].get("content", "")) > 500:
            msgs[i]["content"] = msgs[i]["content"][:400] + "\n[... résultat ancien raccourci pour économiser le contexte ; relis le fichier si besoin]"
            rapport["raccourcis"] += 1
    # 2) puis les échanges d'outils les plus anciens sont retirés (jamais la question de l'utilisateur ni ce qui la précède immédiatement)
    i = 1
    while taille() > budget and i < len(msgs) - 2:
        if i != dernier_user and msgs[i]["role"] in ("assistant", "tool") and i > 0 and (dernier_user < 0 or i > dernier_user):
            del msgs[i]
            rapport["retires"] += 1
            continue
        i += 1
    # 3) en dernier recours, les derniers résultats sont tronqués
    for i in reversed(range(len(msgs))):
        if taille() <= budget:
            break
        if msgs[i]["role"] == "tool" and len(msgs[i].get("content", "")) > 1500:
            msgs[i]["content"] = msgs[i]["content"][:1500] + "\n[... tronqué]"
            rapport["tronques"] += 1
    # 4) les anciens tours de conversation (avant la question actuelle) sont retirés s'il le faut, en gardant le système, le résumé et la question
    while taille() > budget and dernier_user > 2:
        for i in range(1, dernier_user):
            if msgs[i]["role"] in ("user", "assistant", "tool") and id(msgs[i]) not in protege and not msgs[i].get(_disposition.KEPT) and not msgs[i].get("content", "").startswith(("[Résumé", "[Fiche de suivi", "[Extraits", "Compris, je m'appuie")):
                del msgs[i]
                rapport["tours"] += 1
                dernier_user -= 1
                break
        else:
            break
    for m in msgs:
        m.pop("epingle", None)                                   # le marquage est à nous : Ollama ne le reçoit pas
        m.pop("ts", None)                                        # l'horodatage aussi : il sert à la page, pas au modèle
        m.pop("reflexion", None)                                 # et la réflexion enregistrée pour l'affichage
        m.pop("medias", None)
        m.pop("medias_fichiers", None)
        m.pop("fichiers_joints", None)
        _disposition.merge_tail(m)                               # ce qui s'écrit à la fin d'un message (la liste de tâches) s'écrit ici, la place une fois faite : un résultat coupé ne l'emporte pas
    return msgs


def deborde(conv, r, place=None):
    """Vrai quand l'historique ne tient plus dans la place que la requête lui laisse : des échanges anciens vont être retirés de ce qui part au
    modèle. Le rappel du fil s'allume alors, sans attendre un résumé ou une fiche (avant, les plus anciens messages disparaissaient sans retour)."""
    place = place_de_l_historique(conv, r) if place is None else place
    return estimer(conv.get("messages") or []) > place


def document_de_reprise(conv, r):
    """Un document de reprise en Markdown (objectif, ce qui est fait, état, suite, contraintes, fichiers, notes), écrit par le modèle, pour continuer la
    conversation avec un autre modèle d'IA. Par le moteur en cours (l'ancienne page ne passait que par Ollama). ValueError si le modèle ne répond rien."""
    morceaux = []
    if conv.get("depart"):
        morceaux.append(_t("[DEMANDE DE DÉPART]\n") + conv["depart"])
    if conv.get("resume"):
        morceaux.append(_t("[RÉSUMÉ ANTÉRIEUR]\n") + conv["resume"])
    for m in conv.get("messages", []):
        contenu = (m.get("content") or "").strip()
        if not contenu:
            continue
        if m.get("role") == "tool":
            morceaux.append("[OUTIL " + (m.get("tool_name") or "?") + "]\n" + contenu[:800])
        else:
            morceaux.append(("[UTILISATEUR] " if m.get("role") == "user" else "[ASSISTANT] ") + contenu[:2000])
    texte = "\n\n".join(morceaux)
    if len(texte) > 40000:
        texte = texte[:40000] + "\n[…tronqué…]"
    consigne = _t("Tu vas produire un document de reprise pour un AUTRE modèle d'IA qui doit continuer le travail.\n"
                  "Le document doit contenir, dans cet ordre, en markdown :\n"
                  "1. ## Objectif — ce que l'utilisateur voulait faire (1-3 phrases)\n"
                  "2. ## Ce qui a été fait — liste des tâches terminées, fichiers modifiés, décisions prises\n"
                  "3. ## État actuel — où en est-on, ce qui marche, ce qui est en attente\n"
                  "4. ## À faire ensuite — les prochaines étapes concrètes, dans l'ordre\n"
                  "5. ## Contraintes et règles — préférences utilisateur, règles du projet, limites connues\n"
                  "6. ## Fichiers clés — chemins des fichiers importants et leur rôle\n"
                  "7. ## Notes techniques — détails utiles (versions, réglages, bugs connus)\n"
                  "Sois précis, concis, sans répétition. Pas de blabla. Le document doit être directement collable comme contexte system/user message.\n"
                  "Réponds UNIQUEMENT avec le document markdown, sans préambule.\n\n"
                  "CONVERSATION :\n") + texte
    rep = moteur_actuel(r).chat({"model": r["modele"], "stream": False, "messages": [{"role": "user", "content": consigne}], "options": _m.options_modele(r, 0.3)}, 300)
    sortie = (rep.get("message", {}).get("content") or "").strip()
    if not sortie:
        raise ValueError(_t("Le modèle n'a pas répondu."))
    return sortie


DEPART_MAX = 800          # caractères de la demande de départ gardés mot pour mot en tête de la requête (bloc_du_debut)


def retenir_depart(conv, ancien):
    """Garde la demande de départ de la personne, mot pour mot, quand le début de la conversation sort de l'historique (résumé ou fiche)."""
    if not conv.get("depart"):
        premiere = next((m for m in ancien if m.get("role") == "user" and (m.get("content") or "").strip()), None)
        if premiere:
            conv["depart"] = premiere["content"].strip()[:DEPART_MAX]


def _decaler_scribe(conv, coupe, gardes):
    """Le scribe retient un RANG dans la liste des messages : quand le début est retiré, ce rang doit suivre, sinon il saute des messages ou croit en avoir lu qu'il n'a pas lus."""
    if conv.get("scribe_a"):
        conv["scribe_a"] = max(0, int(conv["scribe_a"]) - coupe) + gardes


SEUIL_PLEIN = 0.6              # au-delà (ou bien au-delà de ce que la requête laisse aux messages : MARGE_PLEIN), le retrait n'attend plus le scribe : mieux vaut une fiche en retard (le début reste retrouvable avec « rappeler ») qu'une conversation qui n'a plus de place pour répondre
SEUIL_PLEIN_REEL = 0.8         # idem d'après le chiffre réel d'Ollama
PART_GARDEE = 0.25            # /compact en mode fiche : les messages récents gardés tels quels tiennent dans ce quart de la fenêtre
PART_APRES_RETRAIT = 0.4     # après un retrait, les messages gardés tiennent dans cette part du seuil (ADR 0019, décision 2)
SEUIL_ELAGAGE = 0.45         # part de la fenêtre que les messages peuvent prendre avant le retrait (ou ce que la requête leur laisse une fois la fiche comptée, si c'est moins)
MARGE_PLEIN = 0.1            # au-delà de ce que la requête leur laisse, de cette part de la fenêtre : le retrait n'attend plus le scribe


def _taille_fiche(conv, r):
    """La place de la fiche de suivi dans la requête, en jetons (0 sans fiche)."""
    try:
        return len(_suivi.text_for_model(conv["id"], r["num_ctx"])) // 3 if conv.get("id") else 0
    except ValueError:
        return 0


def elaguer(conv, r, emit, forcer=False, place=None):
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
        if len(msgs) < 8:
            return False
        place = (place_de_l_historique(conv, r) if place is None else place) - _taille_fiche(conv, r)
        taille = estimer(msgs)
        plein = taille >= min(int(r["num_ctx"] * SEUIL_PLEIN), place + int(r["num_ctx"] * MARGE_PLEIN)) or reel >= int(r["num_ctx"] * SEUIL_PLEIN_REEL)
        if taille < min(int(r["num_ctx"] * SEUIL_ELAGAGE), place) and reel < int(r["num_ctx"] * SEUIL_PLEIN_REEL):
            return False
        coupe = max(2, len(msgs) // 2)
        while coupe < len(msgs) and msgs[coupe]["role"] != "user":              # on coupe avant un message de l'utilisateur
            coupe += 1
        # ADR 0019, décision 2 : le reste descend bien sous le seuil (PART_APRES_RETRAIT), pour que plusieurs échanges tiennent avant le retrait
        # suivant ; avant, la moitié sortait et l'historique revenait au seuil un ou deux échanges plus tard (9 retraits en 22 tours, chacun change
        # le début de la requête et le moteur relit tout). Le dernier échange reste toujours tel quel.
        moitie = coupe
        cible = int(min(int(r["num_ctx"] * SEUIL_ELAGAGE), place) * PART_APRES_RETRAIT)
        users = [i for i, m in enumerate(msgs) if m["role"] == "user"]
        garde = users[-2] if len(users) >= 2 else coupe                            # le dernier échange : la demande précédente, sa réponse et la question
        while coupe < garde and estimer(msgs[coupe:]) > cible:
            coupe += 1
            while coupe < garde and msgs[coupe]["role"] != "user":
                coupe += 1
        lu = int(conv.get("scribe_a") or 0)
        if r.get("fiche_scribe", True) and lu < coupe:                            # jamais de message que le scribe n'a pas encore lu : il ne serait plus dans la fiche
            limite = lu
            while limite > 0 and limite < len(msgs) and msgs[limite]["role"] != "user":
                limite -= 1
            # fenêtre presque pleine : mieux vaut une fiche en retard (le début reste retrouvable avec « rappeler »), mais pas plus de la moitié de ce
            # qu'il n'a pas lu, comme avant la cible : sinon presque tout sortait sans être passé dans la fiche
            coupe = max(limite, min(coupe, moitie)) if plein else limite
    if coupe < 2 or coupe >= len(msgs):
        return False
    if forcer and r.get("fiche_scribe", True):
        scribe(conv, r, jusqua=coupe, forcer=True)                              # la fiche se met à jour avant que le début disparaisse : tout ce qui sort doit y être passé
        if messages_non_lus(conv, coupe):
            raise ValueError(_t("La fiche de suivi n'a pas pu être mise à jour (le modèle ne répond pas ?) : rien n'est retiré, pour ne rien perdre. Réessaie dans un moment."))
    ancien = msgs[:coupe]
    _archive.add(conv["id"], ancien)
    retenir_depart(conv, ancien)                                                # la fiche ne la garde pas forcément : elle passe en tête de la requête (bloc_du_debut)
    conv["messages"] = [m for m in ancien if m.get("epingle")] + msgs[coupe:]
    _decaler_scribe(conv, coupe, len([m for m in ancien if m.get("epingle")]))
    conv.pop("jetons", None)                                                    # le chiffre de contexte d'avant le retrait n'est plus vrai
    emit({"type": "info", "texte": _t("Conversation longue : les {} plus anciens messages sortent du contexte (la fiche de suivi garde le fil, et tu peux les retrouver avec « rappeler »).").format(len(ancien))})
    return True


def compacter_conversation(ident):
    """Commande /compact : le début de la conversation sort maintenant du contexte, la fiche de suivi mise à jour d'abord (le modèle est sollicité
    par le scribe, comptez quelques secondes). « fiche » reste dans la réponse pour les anciennes pages : toujours vrai (ADR 0019)."""
    if ident in _m.TOURS_ACTIFS:
        raise ValueError("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la.")
    conv = _m.conv_lire(ident)
    avant = len(conv["messages"])
    info = []
    r = _m.reglages()
    if not elaguer(conv, r, info.append, forcer=True):
        raise ValueError(_t("Rien à retirer : la conversation est encore courte."))
    _m.conv_ecrire(conv)
    return {"ok": True, "avant": avant, "apres": len(conv["messages"]), "jauge": jauge_contexte(conv), "fiche": True}


def horodatage():
    """La date et l'heure (locales, à la seconde) d'un message : la page les montre sous chaque bulle."""
    return datetime.now().isoformat(timespec="seconds")


LECTURES_ENSEMBLE = 4          # au plus quatre lectures à la fois : le disque, pas le processeur, est la limite


def lectures_groupees(appels, preparer, executer, autorises):
    """Les appels d'une même étape qui ne font que LIRE (tool_table.batchable) et se suivent sont lancés ensemble : {position: Future}. Tout le reste reste séquentiel,
    et la boucle garde l'ordre des appels pour les évènements et pour la conversation. Une lecture seule n'est pas lancée d'avance : il n'y a rien à gagner.
    Une lecture lancée d'avance dont la boucle ne veut finalement pas (appel répété, arrêt) est simplement ignorée : elle n'a rien changé."""
    from concurrent.futures import ThreadPoolExecutor
    from . import tool_table
    lisibles = tool_table.batchable()
    groupes, courant = [], []
    for position, appel in enumerate(appels):
        nom = (appel.get("function") or {}).get("name", "")
        if nom in lisibles and nom in autorises:
            courant.append((position, nom, (appel.get("function") or {}).get("arguments")))
        else:
            if len(courant) > 1:
                groupes.append(courant)
            courant = []
    if len(courant) > 1:
        groupes.append(courant)
    if not groupes:
        return {}
    avance = {}
    bassin = ThreadPoolExecutor(max_workers=LECTURES_ENSEMBLE, thread_name_prefix="lecture")
    try:
        for groupe in groupes:
            for position, nom, brut in groupe:
                avance[position] = bassin.submit(lambda n=nom, b=brut: executer(n, preparer(n, b)))
    finally:
        bassin.shutdown(wait=False)          # les lectures lancées se terminent ; la boucle attend chacune à son tour
    return avance


def tour(conv, texte, emit, r=None, stop=None, remplacer_depuis=None, identite="", lecture_seule=False, images=(), pieces=()):
    """Un tour de conversation : message de l'utilisateur, puis la boucle de l'agent (réponse, outils, réponse...). emit(evenement) envoie à la page.
    stop (threading.Event) : déclenché par le bouton Arrêter ; le tour s'arrête alors pour de bon (modèle, outils, accords). Fermer la page ne l'arrête pas.
    remplacer_depuis : indice d'un message de l'utilisateur à remplacer (modifier un message / régénérer) ; ce message et tout ce qui le suit sont retirés d'abord.
    images : identifiants d'images jointes à ce message (voir images.py). pieces : documents et fichiers texte joints, [{id, nom}] (voir attachments.py).
    lecture_seule : tâches planifiées, où personne ne peut accepter : lecture et recherche seulement, tout le reste est simulé comme dans l'essai à blanc."""
    r = dict(r or _m.reglages())
    if lecture_seule:
        r["essai_a_blanc"] = True
    stop = stop if stop is not None else threading.Event()
    etat = _etat_tour.begin(conv["id"], stop)          # le tour dit lui-même où il en est (turn_state.py), quel que soit celui qui le lance : page, tâche planifiée, mission, addon
    try:
        _derouler_tour(conv, texte, emit, r, stop, remplacer_depuis, identite, lecture_seule, images, pieces)
    finally:
        _etat_tour.end(etat)


def _derouler_tour(conv, texte, emit, r, stop, remplacer_depuis, identite, lecture_seule, images, pieces):
    """Le corps de `tour` : `r` est déjà une copie des réglages et `stop` existe."""
    sortie_page, parle = emit, {"texte": False}

    def emit(evenement):                                                  # noqa: F811  (même nom : tout le tour passe par ici, pour savoir si la page a reçu une réponse)
        if evenement.get("type") in ("texte", "erreur"):
            parle["texte"] = True
        _etat_tour.touch(conv["id"])                                      # un signe de vie : un tour qui n'en donne plus est dit « sans signe de vie », pas « en cours »
        sortie_page(evenement)
    _m.refresh_plan()
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
            ctx["essai_titre"] = str(titre)[:120]          # le modèle le relit dans le résultat : de QUOI il s'agit, et que cela n'existe pas
            return False
        sujet = ctx.get("sujet_accord") or {}          # posé par l'outil qui demande (une commande) : ce qui peut être retenu, et pourquoi on demande
        raison = "" if auto else (sujet.get("raison") or _t("La case d'accord automatique correspondante n'est pas cochée pour cette conversation."))          # pourquoi on te demande : jamais un mystère
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
        with _etat_tour.waiting(conv["id"], titre):          # dit AVANT la carte : quand la page la reçoit, le tour est déjà « en attente d'un accord »
            emit({"type": "approbation", "id": a.id, "titre": titre, "detail": detail, "diff": diff, "raison": raison, "suspendu": suspendu, "retenir": bool(sujet.get("retenir"))})
            ok = a.attendre(stop=stop)
        if stop.is_set():
            raise _m.Arret()
        if ok and a.retenir != "once" and sujet.get("retenir") and sujet.get("commande"):
            from . import approval_rules
            try:
                if approval_rules.remember(sujet["commande"], a.retenir, conv["id"]):
                    emit({"type": "info", "texte": _t("Retenu : cette commande ne sera plus demandée ({}).").format(_t("dans cette conversation") if a.retenir == "chat" else _t("règle enregistrée, à retirer dans Réglages"))})
            except ValueError as refus_regle:
                emit({"type": "info", "texte": str(refus_regle)})
        if ok and a.reactiver and suspendu:
            ctx["web_confiance"] = True                                          # choisi sur la carte : l'accord automatique reprend pour la suite de CETTE demande
            emit({"type": "accord_retabli"})
        emit({"type": "info", "texte": (_t("Accepté : {}") if ok else _t("Refusé : {}")).format(titre)})
        ctx["dernier_accord"] = "manuel"
        return ok
    ctx = {"essai": bool(r.get("essai_a_blanc")), "identite": identite, "accord": accord, "auto_ecriture": bool(r.get("auto_ecriture")), "auto_commandes": bool(r.get("auto_commandes")), "mission": r.get("_mission", ""), "stop": stop, "conv": conv, "emit": emit, "web": bool(r.get("web", True)), "limite_ram": int(r.get("limite_ram_commande_go", 0) * _m.GB),
           "tour": {"id": datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2), "conversation": conv["id"], "fichiers": {}}}
    dernier = conv["messages"][-1] if conv["messages"] else None
    if dernier and dernier.get("role") == "user" and dernier.get("content") == texte:
        emit({"type": "info", "texte": "Cette demande est déjà dans la conversation sans réponse : je la reprends sans la dupliquer."})
    else:
        conv["messages"].append(dict({"role": "user", "content": texte, "ts": horodatage()}, **({"images": list(images)} if images else {}), **({"pieces": list(pieces)} if pieces else {})))
    if images and not any(m.get("images") for m in conv["messages"][-1:]):
        conv["messages"][-1]["images"] = list(images)           # demande reprise sans doublon : on lui rend ses images
    if pieces and not conv["messages"][-1].get("pieces"):
        conv["messages"][-1]["pieces"] = list(pieces)
    if conv["titre"] == "Nouvelle conversation":
        conv["titre"] = " ".join(texte.split())[:60]
    _m.reparer_conversation(conv)
    if not _m.check_before_request(r, emit, conv["id"], stop):
        _m.conv_ecrire(conv)                             # la demande est gardée : « continue » la relancera quand le problème sera réglé
        emit({"type": "fin", "conversation": {"id": conv["id"], "titre": conv["titre"]}})
        return
    _estimer_avant_charge(r, emit)
    r["memoire_longue"] = memoire_longue(conv, r)                                      # la fiche de suivi, pour toute conversation (ADR 0019)
    try:
        place = place_de_l_historique(conv, r)                                          # une fois pour le tour : les outils et le système ne changent pas d'ici la réponse
        r["fiche_active"] = fiche_active(conv, r, place)
        if r["fiche_active"]:
            place = place_de_l_historique(conv, r)                                      # avec l'outil de la fiche
        elaguer(conv, r, emit, place=place)                                             # tâches planifiées et réponses automatiques comprises : elles prenaient le résumé, leur conversation ne doit pas grossir sans fin
        # le rappel du fil (et sa consigne dans le système) seulement quand le modèle ne voit plus tout : un début retiré (la demande de départ est
        # alors retenue), un ancien résumé, ou un historique qui déborde. Avant ADR 0019, le mode fiche l'allumait dès le premier message.
        r["rappel_ici"] = bool(conv.get("depart") or conv.get("resume")) or deborde(conv, r, place)
        boucle_agent(conv, r, emit, ctx, stop)
    except _m.Arret:
        _m.journaliser("Tour arrêté par l'utilisateur (conversation {}).".format(conv["id"]))
        emit({"type": "info", "texte": "Arrêté. Ce qui était déjà fait est gardé dans la conversation ; écris « continue » pour reprendre."})
    except Exception as erreur:  # noqa: BLE001
        _m.journaliser("Erreur inattendue dans le tour (conversation {}) : {!r}".format(conv["id"], erreur))
        emit({"type": "erreur", "texte": _t("Erreur inattendue : {} (détail dans donnees/lutin.log). Ta demande est gardée.").format(str(erreur)[:300])})
    try:
        if r.get("fiche_active") or fiche_active(conv, r):                              # la réponse a pu faire passer la conversation à mi-chemin du retrait
            reponse = next((m.get("content") or "" for m in reversed(conv["messages"]) if m.get("role") == "assistant" and m.get("content")), "")
            _suivi.after_turn(conv["id"], texte, reponse, sorted(ctx["tour"]["fichiers"]))
            if r.get("fiche_scribe", True) and not stop.is_set():
                scribe(conv, r, emit)
    except (OSError, ValueError) as erreur:
        _m.journaliser("Fiche de suivi non mise à jour (conversation {}) : {!r}".format(conv.get("id"), erreur))
    try:
        if _boucles.repeats_last_answer(conv):
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
    installes = [n for n in etat_moteur().get("installes", []) if not embeddings.is_search_model(n)]
    try:
        vram, ram = _m.video_memory(), _m.system_memory()
        budget = (vram["total"] / 1024 ** 3) if vram else ((ram["total"] / 1024 ** 3) * 0.6 if ram else 0)
    except Exception:  # noqa: BLE001  (une mesure qui échoue ne doit pas empêcher de répondre)
        budget = 0
    trop_gros = {n for n in installes if budget and (_routeur.size_gb(n, _m.MODELES) or 0) > budget * 0.95}
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
    _observatoire.record("routage", conv_id, profil=choix.get("profil", "reprise"), modele=choix["modele"], machine=choix.get("machine", ""), raison=motif_court)


def router_la_demande(r, demande, images, emit, conv_id):
    """Choix automatique du modèle (réglage « routage »), une fois par demande, jamais pendant une mission. Ne lève jamais : au pire, le modèle choisi reste le même."""
    try:
        if not r.get("routage") or r.get("_mission") or r.get("essai_a_blanc"):
            return False
        installes, trop_gros, distants = contexte_routage()
        choix = _routeur.choose(demande, installes, r["modele"], _m.MODELES, images, trop_gros, distants)
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
        choix = _routeur.biggest(r["modele"], installes, _m.MODELES, trop_gros, distants, exiger_reflexion=False)
        if not choix:
            return False
        r["_monte"] = True
        appliquer_choix(r, dict(choix, profil="reprise"), emit, conv_id, motif)
        corps["model"] = r["modele"]
        return True
    except Exception as erreur:  # noqa: BLE001
        _m.journaliser("Routeur de modèles (reprise) : {!r}".format(erreur))
        return False


def bloc_du_debut(conv):
    """Ce qui tient lieu du début retiré de la conversation, en tête de l'historique (ADR 0018, décision 2) : le résumé avec la demande de départ mot
    pour mot, ou, en mode fiche, la demande de départ seule (la fiche ne la garde pas forcément : le scribe ne note un objectif que s'il est dit). Le
    même dans la requête et dans ce que le rappel croit envoyé. [] tant que rien n'a été retiré : la demande de départ est alors encore dans l'historique."""
    depart = conv.get("depart") or ""
    if conv.get("resume"):
        texte = "[Résumé de la conversation jusqu'ici]\n" + (("Demande de départ : " + depart + "\n\n") if depart else "") + conv["resume"]
    elif depart:
        texte = "[Demande de départ]\n" + depart
    else:
        return []
    return [{"role": "user", "content": texte}, {"role": "assistant", "content": "Compris, je continue."}]


MARGE_RAPPELS = 120          # jetons : les en-têtes des blocs du tour et l'accusé de réception qui les suit


def place_des_rappels(conv, r, outils, fiche=""):
    """Les caractères que les passages rappelés (fil et documents) peuvent prendre sans pousser la requête au-delà de PART_MAX : ce qui reste une fois
    comptés le système, les outils, le bloc du début, la fiche et la question.
    Avant, leur part était fixe (un dixième de la fenêtre) : sur 4 096 jetons en mode fiche, la requête montait à 95 % de la fenêtre, la réponse
    n'avait presque plus de place et un moteur pouvait refuser la requête (ADR 0018, décision 10)."""
    recents = estimer((conv.get("messages") or [])[-1:])          # la question ; le dernier échange, lui, cède sa place si besoin (le rappel le remet : ADR 0018, décision 7)
    pris =(len(json.dumps(outils, ensure_ascii=False)) + len(consignes_systeme(r) + _fichiers.instruction_folder(conv)) + len(fiche)) // 3
    reste = int(r["num_ctx"] * PART_MAX) - pris - estimer(bloc_du_debut(conv)) - recents - MARGE_RAPPELS
    return max(0, reste) * _disposition.CHARS_PER_TOKEN


def ce_que_voit_le_modele(conv, r, outils, fiche=""):
    """Les messages de la conversation que la requête enverra vraiment, une fois ajustée à la fenêtre (ADR 0018) : le rappel du fil ne remet pas ce
    que le modèle a sous les yeux, et cherche d'abord dans ce que l'ajustement retire. La requête est reconstruite comme dans _messages_de_l_etape
    (système, résumé, fiche), avec la place des extraits réservée ; le système n'est pas rendu."""
    msgs = [{"role": "system", "content": consignes_systeme(r) + _fichiers.instruction_folder(conv)}] + bloc_du_debut(conv)
    reserve ="·" * _disposition.thread_budget(r["num_ctx"])                   # les extraits eux-mêmes prendront cette place
    msgs += _disposition.before_last_question(list(conv.get("messages") or []), _disposition.turn_block(fiche, reserve, ""))
    return ajuster_contexte(msgs, r["num_ctx"], 1.0, outils)[1:]


def _preparer_boucle(conv, r, emit, ctx):
    """Contexte du tour, lu UNE fois : les outils du mode, la fiche de suivi, les extraits du fil, les rappels tirés des documents, la consigne d'exécution, la recherche guidée.
    Rien de ce qui est lu ici ne change d'une étape à l'autre du tour : le début de la requête reste identique, et le moteur le garde en cache.
    Les passages rappelés (fil et documents) se partagent une part de la fenêtre, le fil servi d'abord (prompt_layout, ADR 0013)."""
    tours_max = max(4, int(r.get("tours_max", _m.TOURS_MAX)))
    outils = outils_du_mode(r)                                      # seulement les outils utiles dans ce mode : moins de jetons, moins de confusion
    ctx["outils_autorises"] = {t["function"]["name"] for t in outils}
    fiche, consigne = "", ""
    forcer_fin = False                                                # le modèle tourne en rond : un dernier tour SANS outil pour qu'il conclue, au lieu de couper net
    try:
        fiche = _suivi.text_for_model(conv["id"], r["num_ctx"])                # lue UNE fois pour tout le tour : le début de la requête reste identique, Ollama le garde en cache
    except ValueError:
        fiche = ""
    extraits = ""
    place = place_des_rappels(conv, r, outils, fiche)
    if r.get("rappel_ici") and min(_disposition.thread_budget(r["num_ctx"]), place) >= _disposition.RECALL_MIN:          # le début de la conversation n'est plus sous les yeux du modèle : on lui remet ce qui touche à la demande
        try:
            etape = " ".join(_suivi.read(conv["id"])["etape"] + _suivi.read(conv["id"])["objectif"])
            vus = ce_que_voit_le_modele(conv, r, outils, fiche)
            extraits, nb_extraits = _m.thread_recall(conv, etape, min(_disposition.thread_budget(r["num_ctx"]), place), vus)
            if nb_extraits and DITS["rappel"].get(conv["id"]) != nb_extraits:          # dit une fois, et quand le nombre change : pas à chaque réponse
                DITS["rappel"][conv["id"]] = nb_extraits
                emit({"type": "info", "texte": _t("📎 {} passage(s) retrouvé(s) plus tôt dans cette conversation.").format(nb_extraits)})
        except Exception as erreur:  # noqa: BLE001  (la recherche ne doit jamais empêcher de répondre)
            _m.journaliser("Rappel du fil impossible : {!r}".format(erreur))
    rappels_texte, rappels_sources = "", []
    place_documents = min(_disposition.documents_budget(r["num_ctx"], extraits), place - len(extraits))          # ce que le fil a laissé de la part des rappels
    place_documents = place_documents if place_documents >= _disposition.RECALL_MIN else 0
    if place_documents:
        try:
            rappels_texte, rappels_sources = _m.automatic_recalls(conv, r, place_documents)
        except Exception as erreur:  # noqa: BLE001
            _m.journaliser("Rappels automatiques impossibles : {!r}".format(erreur))
    if rappels_sources:
        emit({"type": "info", "texte": _t("📎 Rappels ajoutés d'après tes documents : {}").format(" ; ".join(rappels_sources[:4]))})
    derniere_demande = next((m.get("content") or "" for m in reversed(conv["messages"]) if m.get("role") == "user"), "")
    try:
        consigne = _suivi.execution_directive(conv, derniere_demande, conv["id"])
    except ValueError:
        consigne = ""
    if consigne:
        emit({"type": "info", "texte": _t("▶ Validation reçue : j'exécute l'étape en cours sans replanifier.")})
    elif conv.get("boucle"):                                      # la dernière réponse répétait la précédente : cette fois on ordonne d'agir
        consigne = _boucles.instruction()
    garde = _boucles.Guard()
    guide = ""
    if not consigne and not r.get("_mission") and "web_chercher" in ctx["outils_autorises"] and conv["messages"] and conv["messages"][-1].get("role") == "user":
        guide = _actualites.guided_mode(derniere_demande, r["modele"])
    if guide:
        try:                                                              # actualités, recherche demandée, adresse collée : Lutin cherche et lit lui-même, le modèle ne fait que répondre d'après ce qu'on lui montre
            consigne = _actualites.prepare(conv, derniere_demande, ctx, emit, reformuler=lambda t: reformuler_recherche(t, r), mode=guide) or ""
            forcer_fin = bool(consigne)
        except (_m.ErreurOutil, OSError) as erreur:
            _m.journaliser("Actualités guidées impossibles : {!r}".format(erreur))
            emit({"type": "info", "texte": _t("La recherche d'actualités n'a pas pu se faire ({}) : je continue normalement.").format(erreur)})
    return types.SimpleNamespace(tours_max=tours_max, outils=outils, rappels_texte=rappels_texte, fiche=fiche, extraits=extraits, consigne=consigne, derniere_demande=derniere_demande, garde=garde, forcer_fin=forcer_fin)


def _messages_de_l_etape(conv, r, emit, p, idx_tour, dernier_tour, faux_accompli):
    """Les messages d'UNE étape : consignes, résumé, historique (la consigne, la fiche, les extraits et les rappels passent juste avant la dernière question), puis ce qui ne vaut que pour
    cette étape (l'ordre de conclure au dernier tour, la remarque faite à un modèle qui dit avoir agi sans l'avoir fait), et tout à la fin la liste de tâches, qui change en plein tour.
    Le message système ne contient rien qui suive la demande : le moteur garde ce qu'il a déjà lu (prompt_layout, ADR 0013). `p` est ce que `_preparer_boucle` a lu."""
    rappels_texte, consigne, fiche, extraits = p.rappels_texte, p.consigne, p.fiche, p.extraits
    msgs = [{"role": "system", "content": consignes_systeme(r) + _fichiers.instruction_folder(conv)}]
    if idx_tour == 0:
        for nom_coupe, (taille_coupe, relu_coupe) in sorted(_m.COUPURES.items()):          # un fichier de mémoire plus long que ce que le modèle relit : tu le sais, au lieu de le découvrir plus tard
            if (conv.get("id"), nom_coupe, taille_coupe) in COUPURES_DITES:          # une fois par conversation et par taille, pas à chaque message
                continue
            COUPURES_DITES.add((conv.get("id"), nom_coupe, taille_coupe))
            emit({"type": "info", "texte": _t("⚠ {} fait {} caractères et l'assistant n'en relit que {} à chaque conversation : le reste est ignoré. Raccourcis-le (onglet Mémoire) si des informations manquent.").format(nom_coupe, taille_coupe, relu_coupe)})
    msgs += bloc_du_debut(conv)
    historique =_pieces.for_model(conv["messages"], _pieces.character_budget(r["num_ctx"]))          # le texte des fichiers joints s'ajoute ici, jamais dans la conversation enregistrée
    dernier_user = max((i for i, m in enumerate(historique) if m.get("role") == "user"), default=-1)
    if consigne and dernier_user >= 0:
        historique = list(historique)
        historique[dernier_user] = dict(historique[dernier_user], content=(historique[dernier_user].get("content") or "") + "\n\n[" + consigne + "]")
    msgs += _disposition.before_last_question(list(historique), _disposition.turn_block(fiche, extraits, rappels_texte))          # juste AVANT la dernière question : tout ce qui précède est identique d'une réponse à l'autre (cache du moteur)
    if dernier_tour:             # plus d'outils : le modèle doit répondre avec ce qu'il a trouvé
        msgs.append({"role": "user", "content": "Tu as assez d'informations. Réponds maintenant à ma demande avec ce que tu as vu, sans appeler d'outil. Si quelque chose manque, dis-le."})
    if faux_accompli:
        msgs += [{"role": "assistant", "content": faux_accompli[0]}, {"role": "user", "content": faux_accompli[1]}]
    return _disposition.attach_tail(msgs, _m.text_tasks(conv))          # la liste de tâches à la fin du dernier message : quand elle change, rien de ce qui précède ne change


def _preparer_requete(conv, r, emit, ctx, msgs, outils, idx_tour, dernier_tour, derniere_demande):
    """La requête d'une étape : options, ce que le modèle sait faire (réflexion, images, outils), modèle choisi par le routeur, contexte ajusté à la fenêtre.
    Peut changer `r["modele"]` (un modèle qui voit, le choix du routeur). Renvoie (corps, caps, plat) : la requête, les capacités du modèle, et si son gabarit refuse les outils."""
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
    if idx_tour == 0 and any(m.get("images") for m in conv["messages"][-_images.RECENT:]):
        voit = caps is None or "vision" in caps
        if not voit:
            autre = modele_qui_voit(r["modele"])
            if autre:
                emit({"type": "info", "texte": _t("Ce modèle ne voit pas les images : je passe sur « {} » pour cette demande.").format(autre)})
                r["modele"] = autre
                caps = moteur_actuel(r).capacites(autre)
            else:
                emit({"type": "info", "texte": _t("Ce modèle ne voit pas les images et aucun modèle « Images » n'est installé : elles sont ignorées. Onglet Modèles pour en installer un.")})
    if idx_tour == 0 and router_la_demande(r, derniere_demande, any(m.get("images") for m in conv["messages"][-_images.RECENT:]), emit, conv["id"]):
        caps = moteur_actuel(r).capacites(r["modele"])
        reflechit = reflechit and (caps is None or "thinking" in caps)
    rapport_contexte = {}
    corps = {"model": r["modele"], "messages": ajuster_contexte(msgs, r["num_ctx"], 1.0, outils, rapport_contexte), "stream": True, "options": options, "think": reflechit}
    if not dernier_tour and outils:                      # mode « discussion » : aucun outil, donc rien à envoyer ni à signaler
        if caps is not None and "tools" not in caps:
            if idx_tour == 0:
                emit({"type": "info", "texte": "Ce modèle ne sait pas appeler d'outils : il répondra sans lire ni modifier les fichiers. Choisis un autre modèle (Qwen 3.8 ou Gemma 4) pour cela."})
        else:
            corps["tools"] = outils
    annoncer_reduction(rapport_contexte, emit, ctx, r["num_ctx"])
    plat = r["modele"] in gabarits_connus()
    if plat:
        corps = aplatir_sans_outils(corps)
        if idx_tour == 0 and outils:
            emit({"type": "info", "texte": _t("Le gabarit de ce modèle refuse les outils : il répond sans lire ni modifier de fichiers. Pour cela, choisis un autre modèle (Qwen ou Gemma).")})
    if moteur_actuel(r).en_memoire(r["modele"]) is None:
        emit({"type": "etat", "texte": "Chargement du modèle en mémoire (30 s à 2 min la première fois, ou si ComfyUI lui a pris la carte)."})
    return corps, caps, plat


def _appeler_modele(conv, r, emit, ctx, stop, corps, msgs_base, outils, caps, plat):
    """L'appel du modèle pour une étape, avec ses reprises (trois essais) : lit le flux, sépare réflexion, texte et appels d'outils, reconnaît une réponse vide ou qui tourne en rond,
    classe les erreurs du moteur et décide quoi changer à l'essai suivant. Renvoie (fini, repli_demande, contenu, pensee, appels) ; `repli_demande` : refaire l'étape avec le modèle de repli."""
    fini, verifie, relance_outil, repli_demande, relance_vide, relance_repetition = False, False, False, False, False, False
    for tentative in range(3):
        contenu, pensee, appels = "", "", []
        separateur = _pensee.Splitter()          # une réflexion laissée dans le texte (<think>…</think>) est rendue à part, comme celle que le moteur sépare lui-même
        rond, verifie_rond, raison_fin, rond_de_suite = False, 0, "", 0
        corps_t = corps if tentative == 0 else dict(corps, messages=ajuster_contexte(msgs_base, r["num_ctx"], 0.7 ** tentative, outils) + ([{"role": "user", "content": RAPPEL_APPEL}] if relance_outil else [{"role": "user", "content": RAPPEL_REPETITION}] if relance_repetition else [{"role": "user", "content": RAPPEL_VIDE}] if relance_vide else []), options=dict(corps["options"], temperature=0.3, **({"repeat_penalty": 1.15} if relance_repetition else {})), think=False if (relance_vide or relance_repetition) else corps["think"])
        if plat:
            corps_t = aplatir_sans_outils(corps_t)
        if relance_vide and tentative >= 2 and "tools" in corps_t:
            corps_t = {k: v for k, v in corps_t.items() if k != "tools"}          # dernier essai SANS outils : certains petits modèles ne produisent plus rien quand les outils sont déclarés ; mieux vaut une réponse en texte
        try:
            corps_t = dict(corps_t, messages=_images.for_model(corps_t["messages"], caps is None or "vision" in caps))
            moteur_choisi = moteur_actuel(r)
            with _moteurs.FluxInterruptible(lambda: moteur_choisi.chat_flux(corps_t, 900), stop) as flux:          # le moteur choisi (engines.py) ; Arrêter coupe même un modèle qui charge ou qui se fige
                for e in flux:
                    if stop.is_set():
                        if contenu.strip():
                            conv["messages"].append({"role": "assistant", "content": contenu, "ts": horodatage()})
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
                        _observatoire.record("tour", conv["id"], modele=r["modele"], machine=r.get("machine", ""), jetons=int(e.get("eval_count") or 0), tok_s=vitesse["ecriture"] if vitesse else None,
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
                    for genre_m, morceau in separateur.alimenter(m.get("content")):
                        if genre_m == "pensee":
                            pensee += morceau
                            emit({"type": "pensee", "texte": morceau})
                        else:
                            contenu += morceau
                            emit({"type": "texte", "texte": morceau})
                    appels += m.get("tool_calls") or []
                    if len(pensee) + len(contenu) - verifie_rond >= 400:                       # toutes les 400 lettres : le texte tourne-t-il en rond ? (sortir du « with » ferme la connexion, Ollama arrête de générer)
                        verifie_rond = len(pensee) + len(contenu)
                        if _boucles.repeated_text(pensee) or _boucles.repeated_text(contenu):
                            rond_de_suite += 1
                            if rond_de_suite >= _boucles.CONSECUTIVE_CHECKS:          # il TOURNE en rond : un seul contrôle positif ne coupe pas une analyse qui se répète un instant
                                rond = True
                                break
                        else:
                            rond_de_suite = 0
            for genre_m, morceau in separateur.fin():          # ce que la détection de balise retenait encore
                if genre_m == "pensee":
                    pensee += morceau
                    emit({"type": "pensee", "texte": morceau})
                else:
                    contenu += morceau
                    emit({"type": "texte", "texte": morceau})
            if rond:
                _m.journaliser("Texte répété par le modèle {} (pensée : {} caractères, réponse : {}, essai {})".format(r["modele"], len(pensee), len(contenu), tentative + 1))
                _observatoire.record("relance", conv["id"], motif="texte répété", modele=r["modele"])
                if tentative < 2:
                    relance_repetition = True
                    emit({"type": "info", "texte": _t("Le modèle répète les mêmes phrases : je l'arrête et je relance sans réflexion, avec une pénalité de répétition.")})
                    if tentative >= 1:
                        monter_en_gamme(r, corps, emit, conv["id"], _t("le modèle répète les mêmes phrases"))
                    continue
                emit({"type": "info", "texte": _t("Le modèle répète encore les mêmes phrases : j'arrête là. Reformule en plus court, ou choisis un autre modèle.")})
            if not contenu.strip() and not appels:             # le modèle a (peut-être) réfléchi puis s'est tu : sans ceci la page restait sur « Réflexion » sans aucune réponse ni explication
                _m.journaliser("Réponse vide du modèle {} (pensée : {} caractères, raison de fin : {!r}, essai {}, outils : {})".format(r["modele"], len(pensee), raison_fin, tentative + 1, "tools" in corps_t))
                _observatoire.record("relance", conv["id"], motif="réponse vide", modele=r["modele"])
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
            if (not http or erreur.code in (400, 500)) and RE_GABARIT.search(detail) and not plat:
                genre = "gabarit"
            elif (http and erreur.code == 500) or isinstance(erreur, RuntimeError):
                genre = "repetition" if RE_REPETITION.search(detail) else "outil" if RE_APPEL_MAL_FORME.search(detail) else "contexte" if RE_CONTEXTE.search(detail) else "plantage" if RE_PLANTAGE.search(detail) else ""
            else:
                genre = ""
            nom_mo = nom_du_moteur(r)
            if not _aptitudes.of(moteur_actuel(r)).spills_to_cpu and RE_MEMOIRE_VIDEO.search(detail):          # le modèle ne tient pas avec sa mémoire de conversation : le dire clairement, sans relancer pour rien
                emit({"type": "erreur", "texte": _t("{} n'a pas pu charger « {} » : la mémoire de la carte graphique ne suffit pas pour le modèle ET sa mémoire de conversation. Choisis une quantification plus légère (onglet Modèles), ou une fenêtre de contexte plus petite (Réglages > Conversation), puis redémarre {} (Réglages > Moteur). Détail : {}").format(nom_mo, r["modele"], nom_mo, detail[:160])})
                break
            if not http and not isinstance(erreur, RuntimeError) and _m.AUTO_DEMARRAGE and tentative < 2 and not ctx.get("ollama_relance") and _aptitudes.of(moteur_actuel(r)).starts_on_demand:
                ctx["ollama_relance"] = True                        # Ollama est arrêté (ou a planté) : on le démarre et on réessaie, une seule fois par demande
                emit({"type": "info", "texte": "Ollama ne répond pas : je le démarre (quelques secondes)..."})
                try:
                    moteur_actuel(r).demarrer_sur_demande()          # le moteur dit lui-même qu'il se démarre à la demande (aptitudes) : la boucle ne demande plus « est-ce Ollama ? »
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
            if genre == "gabarit" and tentative < 2:
                noter_gabarit(r["modele"])
                plat = True
                emit({"type": "info", "texte": _t("Le gabarit de conversation de « {} » refuse les outils (erreur d'Ollama : {}). Je réponds sans outils, en texte seulement ; ce modèle est retenu comme tel. Pour lire ou modifier des fichiers, choisis un autre modèle (Qwen ou Gemma).").format(r["modele"], detail[:90])})
                continue
            if genre and tentative < 2:
                if genre == "outil":
                    relance_outil = True
                    emit({"type": "info", "texte": _t("Le modèle a mal écrit un appel d'outil (erreur d'Ollama : {}). Nouvelle tentative...").format(detail[:120])})
                elif genre == "repetition":
                    emit({"type": "info", "texte": _t("Le modèle s'est mis à se répéter en boucle et Ollama a coupé la réponse. Je relance.")})
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
            elif genre == "repetition":
                emit({"type": "erreur", "texte": _t("Le modèle se répète en boucle (Ollama : « token repeat limit reached ») : ce n'est pas un bug de Lutin. Dans Réglages > Avancé, monte la pénalité de répétition (1,1 à 1,2) ou baisse la température, ou essaie une autre quantification ou un autre modèle. Reformule ou écris « continue » pour reprendre.")})
            elif genre == "plantage":
                emit({"type": "erreur", "texte": _t("Ollama plante encore ({}). Ferme ComfyUI ou clique sur « 🧹 VRAM », baisse la fenêtre de contexte dans Réglages, puis écris « continue ».").format(detail[:200])})
            elif http or isinstance(erreur, RuntimeError):
                emit({"type": "erreur", "texte": _t("{} a répondu une erreur : {}{}").format(nom_mo, detail, _t(" (le modèle est-il installé ? onglet Modèles)") if http and erreur.code == 404 else "")})
            elif moteur_actuel(r).id != "ollama":
                emit({"type": "erreur", "texte": _t("{} ne répond pas : {}. Démarre-le (bouton « Démarrer » de la page Modèles, ou Réglages > Moteur).").format(nom_mo, detail)})
            else:
                emit({"type": "erreur", "texte": _t("Ollama ne répond pas : {}. Clique sur « Démarrer Ollama ».").format(detail)})
            break
    return fini, repli_demande, contenu, pensee, appels


def _executer_appels(conv, r, emit, ctx, stop, appels, outils, garde):
    """Les outils demandés par le modèle, dans l'ordre des appels : garde contre les boucles, exécution (l'accord se demande dans l'outil), résultat rendu au modèle et montré à la page,
    conversation enregistrée après chaque outil."""
    avance = lectures_groupees(appels, lambda nom, brut: normaliser_arguments(nom, brut, next((t["function"].get("parameters") for t in outils if t["function"]["name"] == nom), None)),
                               lambda nom, args: _m.call_tool(nom, args, ctx), ctx["outils_autorises"])
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
        _etat_tour.phase(conv["id"], _etat_tour.TOOL, nom)
        emit({"type": "outil", "nom": nom, "args": {k: (v if not isinstance(v, str) or len(v) < 300 else v[:300] + "...") for k, v in args.items()}})
        try:
            if repetitions >= _boucles.CALL_THRESHOLD:                  # le même appel pour la énième fois : on n'exécute plus, on dit de passer à autre chose
                emit({"type": "info", "texte": _t("↻ Le modèle refait le même appel ({} fois) : je lui dis de passer à autre chose.").format(repetitions)})
                resultat = _boucles.Guard.message(repetitions)
            elif nom not in ctx["outils_autorises"]:
                raise _m.ErreurOutil("L'outil « {} » n'est pas disponible ici (mode ou option désactivés). Outils disponibles : {}.".format(nom, ", ".join(sorted(ctx["outils_autorises"]))))
            elif position in avance:
                resultat = avance[position].result()          # lu en même temps que les lectures voisines ; l'ordre des évènements reste celui des appels
            else:
                resultat = _m.call_tool(nom, args, ctx)
        except _m.Arret:
            for b in appels[position:]:
                conv["messages"].append({"role": "tool", "tool_name": (b.get("function") or {}).get("name", ""), "content": "Interrompu par l'utilisateur."})
            raise
        except _m.ErreurOutil as erreur:
            resultat = "Erreur : " + str(erreur)
        except Exception as erreur:  # noqa: BLE001
            _m.journaliser("Outil « {} » : erreur inattendue {!r}".format(nom, erreur))
            resultat = "Erreur inattendue : " + str(erreur)[:300]
        if repetitions >= _boucles.CALL_THRESHOLD:
            garde.refuser(nom, args)
        else:
            garde.noter_resultat(nom, args, resultat)          # un résultat qui change n'est pas une boucle
        _observatoire.record("outil", conv["id"], outil=nom, duree_ms=int((time.monotonic() - debut_outil) * 1000), ok=not str(resultat).startswith(("Erreur", "Interrompu")), modele=r["modele"],
                            detail=str(resultat)[:100] if str(resultat).startswith("Erreur") else "")
        medias, fichiers = ctx.pop("medias", []), ctx.pop("medias_fichiers", {})          # images produites par l'outil (et où elles sont), affichées dans la conversation
        extra = {"medias": medias, "medias_fichiers": fichiers} if medias else {}
        joints = [_fichiers.entree(c) for c in ctx.pop("fichiers_joints", [])][:8]           # documents et médias créés : une carte (ouvrir, télécharger, supprimer) sous le message
        if joints:
            extra["fichiers_joints"] = joints
        try:
            _fichiers.save([dict(e, genre="fichier") for e in joints] + [_fichiers.entree_image(i, fichiers.get(i)) for i in medias if fichiers.get(i)], conv["id"])
        except Exception as erreur:  # noqa: BLE001  (le registre aide au ménage, il ne doit jamais gêner une réponse)
            _m.journaliser("Registre des fichiers créés : {!r}".format(erreur))
        affiche = _t("(résultat transmis à l'assistant, non affiché)") if (nom in OUTILS_INTERNES or _mcp.is_tool(nom)) and ("CONTENU WEB NON FIABLE" in resultat[:60] or _mcp.MARKER in resultat[:60]) else resultat[:1500]          # la recherche web sert à l'assistant, pas à remplir la conversation : c'est à lui d'en tirer la réponse
        emit(dict({"type": "resultat", "nom": nom, "texte": affiche}, **extra))
        conv["messages"].append(dict({"role": "tool", "tool_name": nom, "content": resultat[:_m.LECTURE_MAX + 2000]}, **extra))
        _m.conv_ecrire(conv)                        # enregistré à chaque étape : un plantage du PC en pleine demande ne perd que l'étape en cours


def boucle_agent(conv, r, emit, ctx, stop):
    """La boucle de l'agent : le modèle répond, appelle des outils, on lui rend les résultats, jusqu'à la réponse finale.
    Ses parties : `_preparer_boucle` (le contexte du tour), puis à chaque étape `_messages_de_l_etape`, `_preparer_requete`, `_appeler_modele` et `_executer_appels` ;
    ce qui reste ici est la décision : continuer, relancer, conclure, garder la réponse."""
    p = _preparer_boucle(conv, r, emit, ctx)
    tours_max, outils, derniere_demande, garde, forcer_fin = p.tours_max, p.outils, p.derniere_demande, p.garde, p.forcer_fin
    faux_accompli = None                                              # texte d'un modèle qui prétend avoir écrit un fichier sans l'avoir fait (corrigé une seule fois par demande)
    corrige_affirmation = False
    for idx_tour in range(tours_max):
        _etat_tour.phase(conv["id"], _etat_tour.CONTEXT, step=idx_tour)
        dernier_tour = idx_tour == tours_max - 1 or forcer_fin
        msgs = _messages_de_l_etape(conv, r, emit, p, idx_tour, dernier_tour, faux_accompli)
        faux_accompli = None
        corps, caps, plat = _preparer_requete(conv, r, emit, ctx, msgs, outils, idx_tour, dernier_tour, derniere_demande)
        _etat_tour.phase(conv["id"], _etat_tour.MODEL, r["modele"])
        fini, repli_demande, contenu, pensee, appels = _appeler_modele(conv, r, emit, ctx, stop, corps, msgs, outils, caps, plat)
        if repli_demande:
            continue                                 # on refait ce tour avec le modèle de repli (capacités, échantillonnage et contexte recalculés)
        if not fini:
            if contenu.strip():                      # le texte déjà écrit est gardé dans la conversation
                conv["messages"].append({"role": "assistant", "content": contenu, "ts": horodatage()})
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
        if pensee.strip():
            message["reflexion"] = pensee.strip()[:20000]          # gardée pour l'affichage de la conversation (bloc repliable) ; le modèle ne la reçoit jamais
        if appels:
            message["tool_calls"] = appels
        rappel_faux = "" if appels or corrige_affirmation or dernier_tour else (_affirmations.claims_without_acting(contenu, conv["messages"], ctx["outils_autorises"])
                                                                              or _affirmations.announces_without_acting(contenu, appels, ctx["outils_autorises"])
                                                                              or ("" if r.get("_mission") or r.get("essai_a_blanc") else _affirmations.forgot_to_write(derniere_demande, conv["messages"], ctx["outils_autorises"]))
                                                                              or ("" if r.get("essai_a_blanc") else _affirmations.wrongful_refusal(derniere_demande, contenu, conv["messages"], ctx["outils_autorises"])))
        if rappel_faux:
            corrige_affirmation, faux_accompli = True, (contenu, rappel_faux)
            _m.journaliser("Le modèle {} affirme avoir agi sans appeler d'outil : je le lui fais remarquer.".format(r["modele"]))
            _observatoire.record("relance", conv["id"], motif="affirme sans agir", modele=r["modele"])
            emit({"type": "info", "texte": _t("Le modèle dit avoir agi (fichier, commande, recherche…) sans appeler d'outil : je lui demande de le faire pour de vrai.")})
            continue
        message.setdefault("ts", horodatage())
        conv["messages"].append(message)
        if not appels:
            break
        _executer_appels(conv, r, emit, ctx, stop, appels, outils, garde)
        if garde.abandon:
            if forcer_fin:
                break
            forcer_fin = True
            emit({"type": "info", "texte": _t("↻ Le modèle tourne en rond (le même appel {} fois) : je lui demande de conclure avec ce qu'il a déjà obtenu.").format(_boucles.GIVE_UP_THRESHOLD)})
            continue
    else:
        emit({"type": "info", "texte": "Beaucoup d'étapes d'outils dans ce tour : écris « continue » pour que je poursuive."})
