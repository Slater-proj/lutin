"""L'addon VoiceStudio : donner une voix à Lutin, avec VoiceStudio (https://github.com/debpalash/voicestudio) qui tourne sur cette machine.

Quatre outils pour le modèle : `voix_liste` (les voix disponibles), `voix_parler` (lire un texte avec une voix), `voix_transcrire` (écrire ce qui se dit dans un enregistrement) et `voix_cloner`
(créer une voix à partir d'un enregistrement). Les appels vont à l'API de VoiceStudio, compatible avec celle d'OpenAI : POST /v1/audio/speech, POST /v1/audio/transcriptions, GET /v1/audio/voices,
puis POST /profiles pour le clonage.

Règles de sécurité :
- seule cette machine est jointe (127.0.0.1, le port réglé) ; aucune donnée ne part sur internet ;
- chaque génération demande l'accord de l'utilisateur (comme les images) ;
- CLONER UNE VOIX demande TOUJOURS un accord explicite qui affirme que la voix est celle de l'utilisateur ou qu'il en a la permission ; la case « accord automatique » ne vaut jamais pour cela ;
  la déclaration est aussi transmise à VoiceStudio, qui la garde avec le profil ;
- la clé d'API éventuelle ne se retrouve jamais dans un message d'erreur."""
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import addons
from . import core as _m
from .i18n import t as _t

IDENT = "voicestudio"
FORMATS = ("wav", "mp3", "flac")
TYPES_AUDIO = (".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".webm", ".mp4", ".mkv")
TEXTE_MAX = 4096                 # limite de VoiceStudio pour un appel de synthèse
REF_MAX_OCTETS = 30_000_000      # un enregistrement de référence pour cloner : quelques secondes suffisent
TRANSCRIPTION_MAX_OCTETS = 64_000_000
SORTIE_MAX_OCTETS = 200_000_000
DELAI = 600                      # une synthèse longue sur processeur peut durer


def demarrer():
    """Rien à lancer : VoiceStudio est une application à part, que l'utilisateur démarre."""


def arreter():
    """Rien à arrêter."""


# ------------------------------------------------------------------------------- appels HTTP
def _port():
    try:
        port = int(str(addons.reglages(IDENT).get("port") or "3900").strip())
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise _m.ErreurOutil(_t("Le port de VoiceStudio n'est pas valide (un nombre entre 1 et 65535)."))
    return port


def _requete(methode, chemin, json_corps=None, champs=None, fichier=None, delai=DELAI, max_octets=SORTIE_MAX_OCTETS):
    """Un appel à VoiceStudio : (code, type de contenu, octets). `champs` + `fichier` = (nom du champ, nom, octets) font un envoi multipart. Une panne devient une ErreurOutil lisible, sans la clé."""
    valeurs = addons.reglages(IDENT)
    cle = str(valeurs.get("cle") or "").strip()
    url = "http://127.0.0.1:{}{}".format(_port(), chemin)
    en_tetes = {"User-Agent": "Lutin", "Accept": "*/*"}
    donnees = None
    if json_corps is not None:
        donnees = json.dumps(json_corps).encode("utf-8")
        en_tetes["Content-Type"] = "application/json"
    elif fichier is not None or champs:
        limite = "lutin" + secrets.token_hex(12)
        morceaux = []
        for nom, valeur in (champs or {}).items():
            morceaux.append('--{}\r\nContent-Disposition: form-data; name="{}"\r\n\r\n{}\r\n'.format(limite, nom, valeur).encode("utf-8"))
        if fichier is not None:
            champ, nom_fichier, octets = fichier
            nom_sur = re.sub(r"[^\w.\-]", "_", nom_fichier)[:80] or "audio"
            morceaux.append('--{}\r\nContent-Disposition: form-data; name="{}"; filename="{}"\r\nContent-Type: application/octet-stream\r\n\r\n'.format(limite, champ, nom_sur).encode("utf-8") + octets + b"\r\n")
        morceaux.append("--{}--\r\n".format(limite).encode("utf-8"))
        donnees = b"".join(morceaux)
        en_tetes["Content-Type"] = "multipart/form-data; boundary=" + limite
    if cle:
        en_tetes["Authorization"] = "Bearer " + cle
    req = urllib.request.Request(url, data=donnees, headers=en_tetes, method=methode)
    try:
        with addons.OUVREUR.open(req, timeout=delai) as r:
            brut = r.read(max_octets + 1)
            type_ = r.headers.get("Content-Type", "")
            code = r.status
    except urllib.error.HTTPError as e:
        corps = e.read(3000).decode("utf-8", "replace")
        if e.code == 401:
            raise _m.ErreurOutil(_t("VoiceStudio demande une clé API : renseigne-la dans les réglages de l'addon (la valeur de OMNIVOICE_API_KEY)."))
        raise _m.ErreurOutil(addons.masquer(_t("VoiceStudio a refusé (HTTP {}) : {}").format(e.code, _resume_erreur(corps)), valeurs))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise _m.ErreurOutil(addons.masquer(_t("VoiceStudio ne répond pas sur le port {} ({}). Il doit être lancé sur cette machine.").format(_port(), e), valeurs))
    if len(brut) > max_octets:
        raise _m.ErreurOutil(_t("La réponse de VoiceStudio est trop grosse."))
    return code, type_, brut


def _resume_erreur(corps):
    """Le message d'une erreur de VoiceStudio : forme OpenAI {"error": {"message"}} ou {"detail"}, sinon le début du texte."""
    try:
        d = json.loads(corps)
    except ValueError:
        return corps.strip()[:300]
    if isinstance(d, dict):
        e = d.get("error")
        if isinstance(e, dict) and e.get("message"):
            return str(e["message"])[:300]
        if d.get("detail"):
            return str(d["detail"])[:300]
    return corps.strip()[:300]


def _json(brut):
    try:
        return json.loads(brut.decode("utf-8", "replace"))
    except ValueError:
        raise _m.ErreurOutil(_t("VoiceStudio n'a pas répondu comme prévu (le service a-t-il changé ?)."))


# ------------------------------------------------------------------------------- voix
def liste_voix():
    """Les voix de VoiceStudio : [{id, nom, langue}]. Accepte une liste ou un objet qui la contient."""
    _, _, brut = _requete("GET", "/v1/audio/voices", delai=30, max_octets=2_000_000)
    d = _json(brut)
    if isinstance(d, dict):
        d = d.get("voices") or d.get("data") or []
    sortie = []
    for v in d if isinstance(d, list) else []:
        if isinstance(v, dict):
            sortie.append({"id": str(v.get("id") or v.get("voice_id") or ""), "nom": str(v.get("name") or v.get("voice_id") or v.get("id") or ""), "langue": str(v.get("language") or "")})
        elif isinstance(v, str):
            sortie.append({"id": v, "nom": v, "langue": ""})
    return [v for v in sortie if v["id"] or v["nom"]]


def verifier():
    """La vérification de l'addon (appelée à l'activation et chaque jour) : VoiceStudio répond-il, avec combien de voix ?"""
    try:
        voix = liste_voix()
    except _m.ErreurOutil as e:
        return [{"appel": "voix", "ok": False, "message": str(e)}]
    return [{"appel": "voix", "ok": True, "message": _t("VoiceStudio répond : {} voix disponible(s).").format(len(voix))}]


def texte_voix():
    voix = liste_voix()
    if not voix:
        return _t("Aucune voix enregistrée dans VoiceStudio. Les voix par défaut du moteur restent utilisables avec le nom « default ». Pour en créer une à partir d'un enregistrement : voix_cloner.")
    lignes = ["- {}{}{}".format(v["nom"], " (id : {})".format(v["id"]) if v["id"] and v["id"] != v["nom"] else "", " · " + v["langue"] if v["langue"] else "") for v in voix[:60]]
    if len(voix) > 60:
        lignes.append(_t("... ({} voix en tout)").format(len(voix)))
    return _t("Voix disponibles (le nom ou l'id va dans « voix » de voix_parler ; « default » = la voix par défaut du moteur) :\n") + "\n".join(lignes)


# ------------------------------------------------------------------------------- fichiers
def dossier_sortie():
    d = addons.dossier_donnees() / IDENT / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dossier_audio(ctx):
    """Où ranger l'audio créé : le dossier de la conversation (dans le dossier de travail) quand on la connaît, sinon le dossier de l'addon."""
    conv = (ctx or {}).get("conv") or {}
    if conv.get("id"):
        try:
            from . import produced_files
            return produced_files.dossier_de_conversation(conv["id"], conv.get("titre", ""), creer=True)
        except OSError:
            pass
    return dossier_sortie()


def _fichier_audio(chemin, maximum):
    """Un fichier audio du projet, ou produit plus tôt par l'addon. Lève ErreurOutil sinon (type, taille, chemin hors zone)."""
    from .tools import chemin_sur
    brut = str(chemin or "").strip()
    if not brut:
        raise _m.ErreurOutil(_t("Il faut le chemin d'un enregistrement."))
    try:
        p = chemin_sur(brut)
    except _m.ErreurOutil:
        p = Path(brut).resolve()
        sortie = dossier_sortie().resolve()
        if sortie not in p.parents:
            raise
    if not p.is_file():
        raise _m.ErreurOutil(_t("Fichier introuvable : ") + str(chemin))
    if p.suffix.lower() not in TYPES_AUDIO:
        raise _m.ErreurOutil(_t("Ce n'est pas un enregistrement lisible ({}).").format(", ".join(TYPES_AUDIO)))
    if p.stat().st_size > maximum:
        raise _m.ErreurOutil(_t("Enregistrement trop gros ({} Mo au plus).").format(maximum // 1_000_000))
    return p


def _nom_fichier(texte, extension):
    mots = re.sub(r"[^\w]+", "-", str(texte).lower(), flags=re.UNICODE).strip("-")[:40] or "voix"
    return "{}-{}.{}".format(time.strftime("%Y%m%d-%H%M%S"), mots, extension)


# ------------------------------------------------------------------------------- outils
def _refus(ctx):
    from . import tools
    return tools.refus(ctx, _t("Refusé par l'utilisateur."))


def outil_parler(args, ctx):
    texte = str(args.get("texte") or "").strip()
    if not texte:
        raise _m.ErreurOutil(_t("Il faut un texte à lire."))
    if len(texte) > TEXTE_MAX:
        raise _m.ErreurOutil(_t("Texte trop long ({} caractères au plus par appel) : découpe-le en plusieurs appels.").format(TEXTE_MAX))
    voix = str(args.get("voix") or "default").strip()[:120] or "default"
    format_ = str(args.get("format") or addons.reglages(IDENT).get("format") or "wav").lower()
    if format_ not in FORMATS:
        raise _m.ErreurOutil(_t("Format inconnu : « {} » ({}).").format(format_, ", ".join(FORMATS)))
    corps = {"model": "omnivoice", "input": texte, "voice": voix, "response_format": format_}
    try:
        vitesse = float(args.get("vitesse") or 1.0)
    except (TypeError, ValueError):
        vitesse = 1.0
    if vitesse != 1.0:
        corps["speed"] = max(0.25, min(4.0, vitesse))
    if args.get("langue"):
        corps["language"] = str(args["langue"])[:30]
    if args.get("instructions"):
        corps["instructions"] = str(args["instructions"])[:TEXTE_MAX]
    detail = _t("Voix : {}\nFormat : {}\nTexte : {}").format(voix, format_, texte[:300] + ("…" if len(texte) > 300 else ""))
    if not ctx["accord"](_t("Lire un texte à voix haute avec VoiceStudio"), detail, "", auto=bool(ctx.get("auto_commandes"))):
        return _refus(ctx)
    _, type_, audio = _requete("POST", "/v1/audio/speech", json_corps=corps)
    if "json" in type_.lower() or audio[:1] == b"{" or len(audio) < 100:          # une erreur déguisée en réponse : on la montre, on n'enregistre pas un faux fichier audio
        raise _m.ErreurOutil(_t("VoiceStudio n'a pas rendu d'audio : {}").format(_resume_erreur(audio.decode("utf-8", "replace"))))
    chemin = _dossier_audio(ctx) / _nom_fichier(texte, format_)
    chemin.write_bytes(audio)
    ctx.setdefault("fichiers_joints", []).append(str(chemin))
    return _t("Audio créé : {} ({} Ko, voix « {} », {}). L'utilisateur peut l'écouter et le télécharger depuis la carte sous ton message.").format(chemin, max(1, len(audio) // 1024), voix, format_)


def outil_transcrire(args, ctx):
    fichier = _fichier_audio(args.get("chemin"), TRANSCRIPTION_MAX_OCTETS)
    champs = {"response_format": "json"}
    if args.get("langue"):
        champs["language"] = str(args["langue"])[:10]
    _, _, brut = _requete("POST", "/v1/audio/transcriptions", champs=champs, fichier=("file", fichier.name, fichier.read_bytes()), max_octets=5_000_000)
    d = _json(brut)
    texte = str(d.get("text") or "").strip() if isinstance(d, dict) else ""
    if not texte:
        return _t("VoiceStudio n'a rien entendu dans cet enregistrement (silence, ou langue mal reconnue : précise « langue »).")
    return _t("Transcription de {} :\n\n").format(fichier.name) + texte


def outil_cloner(args, ctx):
    nom = re.sub(r"\s+", " ", str(args.get("nom") or "")).strip()[:80]
    if not nom:
        raise _m.ErreurOutil(_t("Il faut un nom pour la nouvelle voix."))
    base = str(args.get("base") or "").lower()
    if base not in ("ma_voix", "permission"):
        raise _m.ErreurOutil(_t("Précise « base » : « ma_voix » (c'est la voix de l'utilisateur) ou « permission » (la personne a donné son accord). Demande-le à l'utilisateur ; ne le suppose jamais."))
    fichier = _fichier_audio(args.get("chemin"), REF_MAX_OCTETS)
    champs = {"name": nom, "kind": "clone", "language": str(args.get("langue") or "Auto")[:30]}
    if args.get("texte_reference"):
        champs["ref_text"] = str(args["texte_reference"])[:2000]
    garantie = _t("C'est la voix de l'utilisateur lui-même.") if base == "ma_voix" else _t("La personne dont c'est la voix a donné sa permission de la cloner.")
    detail = _t("Nouvelle voix : {}\nEnregistrement : {}\n\nEn acceptant, tu déclares : {}\nNe clone jamais la voix de quelqu'un sans son accord.").format(nom, fichier.name, garantie)
    if not ctx["accord"](_t("Cloner une voix avec VoiceStudio"), detail, "", auto=False):          # jamais d'accord automatique pour cela
        return _refus(ctx)
    _, _, brut = _requete("POST", "/profiles", champs=champs, fichier=("ref_audio", fichier.name, fichier.read_bytes()), delai=180, max_octets=2_000_000)
    profil = _json(brut)
    ident = str(profil.get("id") or "") if isinstance(profil, dict) else ""
    suite = ""
    if ident:
        try:
            _requete("POST", "/profiles/{}/attestation".format(urllib.parse.quote(ident, safe="")), json_corps={"basis": "own_voice" if base == "ma_voix" else "speaker_permission"}, delai=30, max_octets=200_000)
        except _m.ErreurOutil as e:
            suite = _t(" (la déclaration d'autorisation n'a pas pu être enregistrée dans VoiceStudio : {})").format(str(e)[:150])
    return _t("Voix « {} » créée (id : {}){}. Utilise-la avec voix_parler en mettant son nom dans « voix ».").format(nom, ident or "?", suite)


def outil_voix(nom, args, ctx):
    """Aiguillage des quatre outils de l'addon (change_review.py)."""
    if not addons.actif(IDENT):
        raise _m.ErreurOutil(_t("L'addon VoiceStudio n'est pas activé."))
    if nom == "voix_liste":
        return texte_voix()
    if nom == "voix_parler":
        return outil_parler(args, ctx)
    if nom == "voix_transcrire":
        return outil_transcrire(args, ctx)
    if nom == "voix_cloner":
        return outil_cloner(args, ctx)
    raise _m.ErreurOutil(_t("Outil inconnu : {}").format(nom))
