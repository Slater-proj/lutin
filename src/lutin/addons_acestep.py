"""L'addon ACE-Step : composer de la musique (avec ou sans voix chantée) avec ACE-Step 1.5 (https://github.com/ACE-Step/ACE-Step-1.5) qui tourne sur cette machine.

Un outil pour le modèle : `musique_generer` (un style, des paroles facultatives, une durée) ; il crée un fichier audio dans le dossier de la conversation. Les appels vont à l'API REST d'ACE-Step
(`uv run acestep-api`, port 8001 par défaut) : POST /release_task (met la tâche en file, rend un `task_id`), POST /query_result (l'état de la tâche : 0 en cours, 1 réussie, 2 échouée),
GET /v1/audio?path=… (le fichier), GET /health. Toutes les réponses sont dans une enveloppe `{data, code, error}`.

Règles de sécurité :
- seule cette machine est jointe (127.0.0.1, le port réglé) ; aucune donnée ne part sur internet ;
- chaque génération demande l'accord de l'utilisateur (comme les images et les voix) ;
- le fichier n'est téléchargé que depuis le chemin `/v1/audio?path=…` rendu par ACE-Step : une réponse qui désignerait une autre adresse est refusée ;
- la clé d'API éventuelle ne se retrouve jamais dans un message d'erreur."""
import json
import re
import time
import urllib.error
import urllib.request

from . import addons
from . import core as _m
from .i18n import t as _t

IDENT = "acestep"
FORMATS = ("mp3", "wav", "flac")
MIN_DURATION, MAX_DURATION, DEFAULT_DURATION = 10, 600, 60          # secondes : les bornes d'ACE-Step 1.5
MAX_TEXT = 4000                 # un style ou des paroles plus longs n'ont pas de sens pour le modèle
OUTPUT_MAX_BYTES = 200_000_000
WAIT_MAX_S = 1800               # une chanson de dix minutes sur processeur peut durer longtemps
POLL_S = 2.0
INSTRUMENTAL = "[Instrumental]"          # le repère d'ACE-Step pour un morceau sans voix


def demarrer():
    """Rien à lancer : ACE-Step est une application à part, que l'utilisateur démarre."""


def arreter():
    """Rien à arrêter."""


# ------------------------------------------------------------------------------- appels HTTP
def _port():
    try:
        port = int(str(addons.settings(IDENT).get("port") or "8001").strip())
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise _m.ErreurOutil(_t("Le port d'ACE-Step n'est pas valide (un nombre entre 1 et 65535)."))
    return port


def _request(methode, chemin, json_corps=None, delai=60, max_octets=2_000_000):
    """Un appel à ACE-Step : (type de contenu, octets). Une panne devient une ErreurOutil lisible, sans la clé."""
    valeurs = addons.settings(IDENT)
    cle = str(valeurs.get("cle") or "").strip()
    url = "http://127.0.0.1:{}{}".format(_port(), chemin)
    en_tetes = {"User-Agent": "Lutin", "Accept": "*/*"}
    donnees = None
    if json_corps is not None:
        donnees = json.dumps(json_corps).encode("utf-8")
        en_tetes["Content-Type"] = "application/json"
    if cle:
        en_tetes["Authorization"] = "Bearer " + cle
    req = urllib.request.Request(url, data=donnees, headers=en_tetes, method=methode)
    try:
        with addons.OUVREUR.open(req, timeout=delai) as r:
            brut = r.read(max_octets + 1)
            type_ = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        corps = e.read(3000).decode("utf-8", "replace")
        if e.code == 401:
            raise _m.ErreurOutil(_t("ACE-Step demande une clé API : renseigne-la dans les réglages de l'addon."))
        raise _m.ErreurOutil(addons.masquer(_t("ACE-Step a refusé (HTTP {}) : {}").format(e.code, _summary_error(corps)), valeurs))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise _m.ErreurOutil(addons.masquer(_t("ACE-Step ne répond pas sur le port {} ({}). Il doit être lancé sur cette machine (uv run acestep-api).").format(_port(), e), valeurs))
    if len(brut) > max_octets:
        raise _m.ErreurOutil(_t("La réponse d'ACE-Step est trop grosse."))
    return type_, brut


def _summary_error(corps):
    """Le message d'une erreur d'ACE-Step : enveloppe {"error": "…"} ou {"detail": "…"}, sinon le début du texte."""
    try:
        d = json.loads(corps)
    except ValueError:
        return corps.strip()[:300]
    if isinstance(d, dict):
        for cle in ("error", "detail", "message"):
            if d.get(cle):
                return str(d[cle])[:300]
    return corps.strip()[:300]


def _answer(brut):
    """Le contenu `data` d'une réponse enveloppée {data, code, error} ; ErreurOutil si `code` n'est pas 200 ou si `error` est dit."""
    try:
        d = json.loads(brut.decode("utf-8", "replace"))
    except ValueError:
        raise _m.ErreurOutil(_t("ACE-Step n'a pas répondu comme prévu (le service a-t-il changé ?)."))
    if not isinstance(d, dict) or "data" not in d:
        raise _m.ErreurOutil(_t("ACE-Step n'a pas répondu comme prévu (le service a-t-il changé ?)."))
    if d.get("error") or int(d.get("code") or 200) != 200:
        raise _m.ErreurOutil(_t("ACE-Step a refusé : {}").format(str(d.get("error") or d.get("code"))[:300]))
    return d["data"]


def verifier():
    """La vérification de l'addon (à l'activation et chaque jour) : ACE-Step répond-il ?"""
    try:
        _, brut = _request("GET", "/health", delai=15, max_octets=100_000)
        data = _answer(brut)
    except _m.ErreurOutil as e:
        return [{"appel": "sante", "ok": False, "message": str(e)}]
    version = str(data.get("version") or "") if isinstance(data, dict) else ""
    return [{"appel": "sante", "ok": True, "message": _t("ACE-Step répond (version {}).").format(version or "?")}]


# ------------------------------------------------------------------------------- fichiers
def folder_output():
    d = addons.folder_data() / IDENT / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _folder_audio(ctx):
    """Où ranger l'audio créé : le dossier de la conversation (dans le dossier de travail) quand on la connaît, sinon le dossier de l'addon."""
    conv = (ctx or {}).get("conv") or {}
    if conv.get("id"):
        try:
            from . import produced_files
            return produced_files.folder_of_conversation(conv["id"], conv.get("titre", ""), creer=True)
        except OSError:
            pass
    return folder_output()


def _name_file(texte, extension):
    mots = re.sub(r"[^\w]+", "-", str(texte).lower(), flags=re.UNICODE).strip("-")[:40] or "musique"
    return "{}-{}.{}".format(time.strftime("%Y%m%d-%H%M%S"), mots, extension)


# ------------------------------------------------------------------------------- l'outil
def _refusal(ctx):
    from . import tools
    return tools.refus(ctx, _t("Refusé par l'utilisateur."))


def _wait_for(task_id):
    """Attend la fin de la tâche : renvoie le chemin `/v1/audio?path=…` du morceau. ErreurOutil si elle échoue ou si elle dure trop."""
    fin = time.monotonic() + WAIT_MAX_S
    while time.monotonic() < fin:
        _, brut = _request("POST", "/query_result", json_corps={"task_id_list": [task_id]}, delai=60)
        data = _answer(brut)
        entree = next((x for x in data if isinstance(x, dict) and x.get("task_id") == task_id), None) if isinstance(data, list) else None
        status = int(entree.get("status") or 0) if entree else 0
        if status == 2:
            raise _m.ErreurOutil(_t("ACE-Step n'a pas pu composer ce morceau : {}").format(_failure_reason(entree)))
        if status == 1:
            try:
                resultats = json.loads(entree.get("result") or "[]")
            except (TypeError, ValueError):
                resultats = []
            chemin = next((str(x.get("file") or "") for x in resultats if isinstance(x, dict) and x.get("file")), "") if isinstance(resultats, list) else ""
            if not chemin:
                raise _m.ErreurOutil(_t("ACE-Step a fini sans rendre de fichier audio."))
            return chemin
        time.sleep(POLL_S)
    raise _m.ErreurOutil(_t("ACE-Step n'a pas fini en {} minutes : le travail continue peut-être de son côté.").format(WAIT_MAX_S // 60))


def _failure_reason(entree):
    try:
        resultats = json.loads(entree.get("result") or "[]")
        if isinstance(resultats, list) and resultats and isinstance(resultats[0], dict):
            return str(resultats[0].get("generation_info") or resultats[0].get("error") or "?")[:300]
    except (TypeError, ValueError):
        pass
    return "?"


def outil_musique(args, ctx):
    style = str(args.get("description") or "").strip()
    if not style:
        raise _m.ErreurOutil(_t("Il faut décrire le style du morceau (genre, instruments, ambiance)."))
    if len(style) > MAX_TEXT:
        raise _m.ErreurOutil(_t("Description trop longue ({} caractères au plus).").format(MAX_TEXT))
    paroles = str(args.get("paroles") or "").strip()
    if len(paroles) > MAX_TEXT:
        raise _m.ErreurOutil(_t("Paroles trop longues ({} caractères au plus).").format(MAX_TEXT))
    try:
        duree = int(args.get("duree") or DEFAULT_DURATION)
    except (TypeError, ValueError):
        duree = DEFAULT_DURATION
    duree = max(MIN_DURATION, min(MAX_DURATION, duree))
    format_ = str(args.get("format") or addons.settings(IDENT).get("format") or "mp3").lower()
    if format_ not in FORMATS:
        raise _m.ErreurOutil(_t("Format inconnu : « {} » ({}).").format(format_, ", ".join(FORMATS)))
    langue = re.sub(r"[^A-Za-z-]", "", str(args.get("langue") or "en"))[:10] or "en"
    corps = {"prompt": style, "lyrics": paroles or INSTRUMENTAL, "audio_duration": duree, "audio_format": format_, "vocal_language": langue}
    detail = _t("Style : {}\nParoles : {}\nDurée : {} s\nFormat : {}").format(style[:300] + ("…" if len(style) > 300 else ""),
                                                                       paroles[:300] + ("…" if len(paroles) > 300 else "") if paroles else _t("aucune (morceau instrumental)"), duree, format_)
    if not ctx["accord"](_t("Composer un morceau avec ACE-Step"), detail, "", auto=bool(ctx.get("auto_commandes"))):
        return _refusal(ctx)
    _, brut = _request("POST", "/release_task", json_corps=corps)
    task_id = str((_answer(brut) or {}).get("task_id") or "")
    if not task_id:
        raise _m.ErreurOutil(_t("ACE-Step n'a pas pris la demande en compte (pas de numéro de tâche)."))
    chemin = _wait_for(task_id)
    if not chemin.startswith("/v1/audio?path="):          # le fichier ne vient que de ce service, jamais d'une adresse qu'il désignerait
        raise _m.ErreurOutil(_t("ACE-Step a désigné un fichier à un endroit inattendu : refusé."))
    type_, audio = _request("GET", chemin, delai=300, max_octets=OUTPUT_MAX_BYTES)
    if "json" in type_.lower() or audio[:1] == b"{" or len(audio) < 100:          # une erreur déguisée en réponse : on la montre, on n'enregistre pas un faux fichier audio
        raise _m.ErreurOutil(_t("ACE-Step n'a pas rendu d'audio : {}").format(_summary_error(audio.decode("utf-8", "replace"))))
    sortie = _folder_audio(ctx) / _name_file(style, format_)
    sortie.write_bytes(audio)
    ctx.setdefault("fichiers_joints", []).append(str(sortie))
    return _t("Morceau créé : {} ({} Ko, {} s, {}). L'utilisateur peut l'écouter et le télécharger depuis la carte sous ton message.").format(sortie, max(1, len(audio) // 1024), duree, format_)


def outil_acestep(nom, args, ctx):
    """Aiguillage de l'outil de l'addon (change_review.py)."""
    if not addons.actif(IDENT):
        raise _m.ErreurOutil(_t("L'addon ACE-Step n'est pas activé."))
    if nom == "musique_generer":
        return outil_musique(args, ctx)
    raise _m.ErreurOutil(_t("Outil inconnu : {}").format(nom))
