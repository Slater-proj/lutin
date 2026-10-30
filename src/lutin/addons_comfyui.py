"""Partie vivante de l'addon ComfyUI : détecter ComfyUI, voir les modèles installés, et le piloter (générer une image, une vidéo, un son) à la demande du modèle de langage.

Lutin ne contient AUCUN workflow en dur : les « workflows » (le graphe de nœuds de ComfyUI, au format API) sont dans le flux de l'addon, donc modifiables : un workflow d'image est livré ; pour la vidéo ou le son,
on colle son propre workflow (ComfyUI : « Enregistrer (format API) »), avec des marques {prompt}, {largeur}, {hauteur}, {graine}, {pas}, {cfg}, {negatif}, {modele} là où Lutin doit mettre ses valeurs.

Règles de solidité :
- désactivé par défaut ; ComfyUI doit être déjà lancé (Lutin ne le démarre pas, il le pilote) ;
- chaque génération demande ton accord (comme une modification de fichier), sauf accord automatique ; dans une tâche planifiée ou un message Telegram (lecture seule) elle est simulée, jamais faite ;
- la carte graphique est libérée du modèle de langage avant de générer (ils se la partagent) ;
- les appels ne visent que ComfyUI sur cette machine (adresse déclarée par le manifeste) ;
- l'attente d'un résultat s'arrête sur le bouton Arrêter et au bout d'un délai (réglable par type de workflow)."""
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import addons
from . import moteur as _m
from .i18n import t as _t

IDENT = "comfyui"
EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".bin", ".sft")
DOSSIERS_MODELES = ("checkpoints", "loras", "vae", "diffusion_models", "unet", "text_encoders", "clip", "controlnet", "upscale_models")
NOEUDS = {"checkpoints": "objets_checkpoints", "loras": "objets_loras", "vae": "objets_vae", "diffusion_models": "objets_unet"}
RE_MARQUE = re.compile(r"\{([a-z_]+)\}")
RE_MARQUE_ENTIERE = re.compile(r"^\{([a-z_]+)\}$")
TYPES = ("image", "video", "son")
DELAI_PAR_DEFAUT = {"image": 600, "video": 3600, "son": 900}
HOTES_TELECHARGEMENT = ("huggingface.co", "hf.co", "civitai.com")          # et leurs sous-domaines (les fichiers sont servis par des réseaux de diffusion de ces sites)
GENRES_TELECHARGEMENT = ("checkpoints", "loras", "vae", "diffusion_models", "text_encoders", "controlnet", "upscale_models")
TAILLE_MODELE_MAX = 60 * 1024 ** 3
TELECHARGEMENT = {"etat": "", "nom": "", "fait": 0, "total": 0, "erreur": "", "arret": threading.Event()}
VERROU_TELECHARGEMENT = threading.Lock()
CACHE = {"modeles": (0, None)}
DETECTION = {"dossier": ""}               # le dernier dossier d'installation trouvé : le chercher dans les processus coûte (PowerShell), donc seulement à la demande


def demarrer():
    pass                                   # rien à faire tourner en arrière-plan : ComfyUI est piloté à la demande


def arreter():
    pass


# --------------------------------------------------------------------------- détection
def _argv_absolu(r):
    """Le chemin de main.py annoncé par ComfyUI lui-même (system_stats), s'il est absolu."""
    argv = ((r.get("donnees") or {}).get("system") or {}).get("argv") or []
    for a in argv:
        if str(a).lower().endswith("main.py") and os.path.isabs(str(a)):
            return str(a)
    return ""


def _depuis_processus():
    """La ligne de commande des processus qui lancent ComfyUI (best effort : Windows via PowerShell, Linux/macOS via ps)."""
    try:
        if os.name == "nt":
            sortie = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'main\\.py' } | ForEach-Object { $_.CommandLine }"],
                                    capture_output=True, text=True, timeout=20).stdout
        else:
            sortie = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for ligne in sortie.splitlines():
        m = re.search(r'((?:[A-Za-z]:)?[\\/][^"\n]*?main\.py)', ligne)
        if m and "comfy" in ligne.lower():
            return m.group(1).strip()
    return ""


def _usuels():
    base = Path.home()
    for c in (base / "ComfyUI", base / "Documents" / "ComfyUI", base / "Desktop" / "ComfyUI", base / "Downloads" / "ComfyUI", Path("C:/ComfyUI"), Path("D:/ComfyUI"), Path("/opt/ComfyUI")):
        yield c


def dossier_valide(c):
    c = Path(c)
    return c.is_dir() and (c / "main.py").is_file() and (c / "models").is_dir()


def trouver_dossier(argv="", profond=True):
    """Le dossier d'installation de ComfyUI, ou ''. Ordre : ce qu'annonce ComfyUI, la ligne de commande du processus (seulement si profond : lent), les emplacements usuels."""
    for source in (argv, _depuis_processus() if profond else ""):
        if source:
            c = Path(source).parent
            if dossier_valide(c):
                return str(c)
    for c in _usuels():
        if dossier_valide(c):
            return str(c)
    return ""


def detecter(profond=True):
    """Cherche ComfyUI : tourne-t-il (réponse sur son port), quelle version, sur quelle carte, et où est-il installé ? Ne modifie rien. profond=False : sonde légère (le panneau se rafraîchit toutes les 4 secondes)."""
    r = addons.appeler(IDENT, "etat", delai=4 if profond else 1.5)
    trouve = trouver_dossier(_argv_absolu(r), profond)
    if profond or trouve:
        DETECTION["dossier"] = trouve
    resultat = {"tourne": r["ok"], "erreur": "" if r["ok"] else r["erreur"], "version": (r["extrait"] or {}).get("version") or "", "gpu": (r["extrait"] or {}).get("gpu") or "",
                "dossier": trouve or DETECTION["dossier"], "dossier_regle": addons.reglages(IDENT).get("dossier", "")}
    return resultat


# --------------------------------------------------------------------------- modèles installés
def _scan_dossier(dossier):
    sortie = {}
    for genre in DOSSIERS_MODELES:
        d = Path(dossier) / "models" / genre
        if d.is_dir():
            noms = []
            for racine, _, fichiers in os.walk(str(d)):
                for nom in sorted(fichiers):
                    if nom.lower().endswith(EXTENSIONS):
                        noms.append(str((Path(racine) / nom).relative_to(d)).replace("\\", "/"))
                if len(noms) > 2000:
                    break
            if noms:
                sortie[genre] = noms
    return sortie


def lister_modeles(forcer=False):
    """Les modèles installés : par l'API de ComfyUI s'il tourne (ce qu'il voit vraiment), sinon en lisant le dossier d'installation. {source, modeles: {genre: [noms]}}."""
    quand, valeur = CACHE["modeles"]
    if not forcer and valeur is not None and time.time() - quand < 10:
        return valeur
    modeles, source = {}, "aucune"
    for genre, appel in NOEUDS.items():
        r = addons.appeler(IDENT, appel, delai=6)
        if r["ok"]:
            source = "api"
            noms = (r["extrait"] or {}).get("liste")
            if isinstance(noms, list) and noms:
                modeles[genre] = [str(n) for n in noms][:2000]
    if source == "aucune":
        dossier = addons.reglages(IDENT).get("dossier") or ""
        if dossier and dossier_valide(dossier):
            modeles, source = _scan_dossier(dossier), "dossier"
    valeur = {"source": source, "modeles": modeles}
    CACHE["modeles"] = (time.time(), valeur)
    return valeur


def texte_modeles():
    r = lister_modeles()
    if r["source"] == "aucune":
        return _t("ComfyUI ne répond pas et aucun dossier d'installation n'est réglé : impossible de lister les modèles.")
    lignes = [_t("Modèles installés (lus {}) :").format(_t("dans ComfyUI") if r["source"] == "api" else _t("dans le dossier d'installation"))]
    for genre, noms in r["modeles"].items():
        lignes.append("- {} ({}) : {}".format(genre, len(noms), ", ".join(noms[:40]) + (" …" if len(noms) > 40 else "")))
    if len(lignes) == 1:
        lignes.append(_t("(aucun modèle trouvé)"))
    return "\n".join(lignes)


# --------------------------------------------------------------------------- générer
def remplir_workflow(wf, valeurs):
    """Remplace les marques {nom} d'un workflow par leurs valeurs. Une marque qui occupe toute la valeur garde son type (nombre)."""
    if isinstance(wf, dict):
        return {k: remplir_workflow(v, valeurs) for k, v in wf.items()}
    if isinstance(wf, list):
        return [remplir_workflow(v, valeurs) for v in wf]
    if isinstance(wf, str):
        m = RE_MARQUE_ENTIERE.match(wf)
        if m and m.group(1) in valeurs:
            return valeurs[m.group(1)]
        return RE_MARQUE.sub(lambda mo: str(valeurs[mo.group(1)]) if mo.group(1) in valeurs else mo.group(0), wf)
    return wf


def marques_restantes(wf):
    trouvees = set()
    if isinstance(wf, dict):
        for v in wf.values():
            trouvees |= marques_restantes(v)
    elif isinstance(wf, list):
        for v in wf:
            trouvees |= marques_restantes(v)
    elif isinstance(wf, str):
        trouvees |= set(RE_MARQUE.findall(wf))
    return trouvees


def _entier(valeur, nom, mini, maxi, defaut):
    if valeur in (None, ""):
        return defaut
    try:
        n = int(float(valeur))
    except (TypeError, ValueError):
        raise _m.ErreurOutil(_t("« {} » doit être un nombre.").format(nom))
    return max(mini, min(maxi, n))


def parametres(args, flux_actuel, type_):
    """Les valeurs mises dans le workflow : défauts du flux, réglage de l'addon, puis ce que le modèle a demandé (borné)."""
    base = dict((flux_actuel.get("parametres") or {}).get(type_) or {})
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise _m.ErreurOutil(_t("Il faut une description (« prompt »)."))
    v = {"prompt": prompt[:2000], "negatif": str(args.get("negatif") if args.get("negatif") is not None else base.get("negatif", ""))[:1000],
         "largeur": _entier(args.get("largeur"), "largeur", 64, 4096, int(base.get("largeur", 1024))), "hauteur": _entier(args.get("hauteur"), "hauteur", 64, 4096, int(base.get("hauteur", 1024))),
         "pas": _entier(args.get("pas"), "pas", 1, 150, int(base.get("pas", 25))), "graine": _entier(args.get("graine"), "graine", 0, 2 ** 53, secrets.randbelow(2 ** 40))}
    v["largeur"], v["hauteur"] = v["largeur"] // 8 * 8, v["hauteur"] // 8 * 8
    try:
        v["cfg"] = max(1.0, min(30.0, float(args.get("cfg") if args.get("cfg") not in (None, "") else base.get("cfg", 6.5))))
    except (TypeError, ValueError):
        raise _m.ErreurOutil(_t("« {} » doit être un nombre.").format("cfg"))
    modele = str(args.get("modele") or addons.reglages(IDENT).get("modele") or base.get("modele") or "").strip()
    if not modele and type_ == "image":
        premiers = lister_modeles().get("modeles", {}).get("checkpoints") or []
        modele = premiers[0] if premiers else ""
    v["modele"] = modele
    return v


def outil_generer(args, ctx):
    """L'outil « comfy_generer » : image, vidéo ou son. Demande ton accord, libère la carte graphique, envoie le workflow et attend le résultat."""
    type_ = str(args.get("type") or "image").lower()
    if type_ not in TYPES:
        raise _m.ErreurOutil(_t("Type inconnu : « {} » (image, video ou son).").format(type_))
    f = addons.flux(IDENT)
    wf = (f.get("workflows") or {}).get(type_)
    if not wf:
        raise _m.ErreurOutil(_t("Aucun workflow « {} » dans le flux de l'addon ComfyUI : l'utilisateur doit en coller un (Extensions > ComfyUI > Flux…).").format(type_))
    v = parametres(args, f, type_)
    complet = remplir_workflow(wf, v)
    restantes = marques_restantes(complet)
    if restantes:
        raise _m.ErreurOutil(_t("Le workflow contient des marques que Lutin ne sait pas remplir : {}.").format(", ".join(sorted("{" + x + "}" for x in restantes))))
    detail = _t("Description : {}\nTaille : {}×{} · modèle : {}").format(v["prompt"][:300], v["largeur"], v["hauteur"], v["modele"] or _t("(celui du workflow)"))
    if not ctx["accord"](_t("Générer {} avec ComfyUI").format({"image": _t("une image"), "video": _t("une vidéo"), "son": _t("un son")}[type_]), detail, ""):
        from . import outils
        return outils.refus(ctx, _t("Refusé par l'utilisateur."))
    try:
        if _m.reglages().get("liberer_si_comfy", True):
            _m.liberer_vram()                                                      # le modèle de langage cède la carte graphique à ComfyUI
    except Exception as erreur:  # noqa: BLE001  (ne pas échouer pour ça)
        _m.journaliser("ComfyUI : libération de la carte impossible ({!r}).".format(erreur))
    r = addons.appeler(IDENT, "soumettre", {"workflow": complet}, delai=30)
    if not r["ok"]:
        return _t("ComfyUI a refusé le travail : {}").format(r["erreur"])
    ident = (r["extrait"] or {}).get("id")
    if not ident:
        return _t("ComfyUI n'a pas donné d'identifiant de travail.")
    delai = int((f.get("parametres") or {}).get(type_, {}).get("delai", DELAI_PAR_DEFAUT[type_]))
    fin = time.time() + delai
    stop = ctx.get("stop")
    while time.time() < fin:
        if stop is not None and stop.is_set():
            addons.appeler(IDENT, "interrompre", {}, delai=5)
            raise _m.Arret()
        h = addons.appeler(IDENT, "historique", {"id": ident}, delai=15)
        entree = ((h["donnees"] or {}).get(ident) or {}) if h["ok"] else {}
        if entree:
            statut = (entree.get("status") or {}).get("status_str")
            if statut == "error":
                messages = json.dumps((entree.get("status") or {}).get("messages", [])[-2:], ensure_ascii=False)[:400]
                return _t("ComfyUI a échoué : {}").format(messages)
            fichiers = []
            for sortie in (entree.get("outputs") or {}).values():
                for genre in ("images", "gifs", "videos", "audio"):
                    for x in sortie.get(genre, []) or []:
                        if isinstance(x, dict) and x.get("filename") and x.get("type", "output") == "output":
                            fichiers.append("/".join(p for p in (x.get("subfolder"), x["filename"]) if p))
            if fichiers or statut == "success":
                dossier = addons.reglages(IDENT).get("dossier") or ""
                chemins = [str(Path(dossier) / "output" / f_) if dossier else "output/" + f_ for f_ in fichiers]
                return _t("Terminé ({} fichier(s)) :\n{}\nGraine : {}.").format(len(fichiers), "\n".join(chemins) or _t("(ComfyUI n'a rien enregistré)"), v["graine"])
        time.sleep(2)
    return _t("ComfyUI n'a pas fini dans le délai ({} s) : le travail continue peut-être de son côté.").format(delai)


# --------------------------------------------------------------------------- télécharger un modèle
def hote_telechargement_permis(hote):
    hote = (hote or "").lower()
    if os.environ.get("LUTIN_WEB_LOCAL") == "1" and hote in ("127.0.0.1", "localhost"):          # pour les tests seulement
        return True
    return any(hote == h or hote.endswith("." + h) for h in HOTES_TELECHARGEMENT)


def nom_de_fichier(url, entete=""):
    """Le nom du fichier à créer : celui de l'en-tête de téléchargement ou de l'adresse, réduit à un simple nom (jamais un chemin), avec une extension de modèle."""
    nom = ""
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', entete or "")
    if m:
        nom = urllib.parse.unquote(m.group(1))
    if not nom:
        nom = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
    nom = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(nom.replace(chr(92), "/")).name).strip(" .")
    if not nom.lower().endswith(EXTENSIONS):
        raise addons.ErreurAddon(_t("Ce n'est pas un fichier de modèle ({}).").format(", ".join(EXTENSIONS[:3]) + "…"))
    return nom[:150]


class _RedirectionControlee(urllib.request.HTTPRedirectHandler):
    """Une redirection n'est suivie que vers un site permis, en https : la vérification a lieu AVANT de contacter le nouveau site."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urllib.parse.urlsplit(newurl)
        local = os.environ.get("LUTIN_WEB_LOCAL") == "1" and p.hostname in ("127.0.0.1", "localhost")
        if (p.scheme != "https" and not local) or not hote_telechargement_permis(p.hostname):
            raise addons.ErreurAddon(_t("Le site redirige vers {} : refusé (seuls Hugging Face et Civitai sont permis).").format(p.hostname or "?"))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _telecharger(url, destination_dossier):
    t = TELECHARGEMENT
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Lutin"})
        with urllib.request.build_opener(_RedirectionControlee).open(req, timeout=60) as r:
            final = urllib.parse.urlsplit(r.geturl())
            if final.scheme != "https" and not (os.environ.get("LUTIN_WEB_LOCAL") == "1" and final.hostname in ("127.0.0.1", "localhost")):
                raise addons.ErreurAddon(_t("Le site redirige vers une adresse non chiffrée : refusé."))
            if not hote_telechargement_permis(final.hostname):
                raise addons.ErreurAddon(_t("Le site redirige vers {} : refusé (seuls Hugging Face et Civitai sont permis).").format(final.hostname))
            if os.environ.get("LUTIN_WEB_LOCAL") != "1":
                from . import web
                web.verifier_hote_web(r.geturl())
            nom = nom_de_fichier(r.geturl(), r.headers.get("Content-Disposition", "")) if not t["nom"] else t["nom"]
            if r.headers.get_content_type() == "text/html":
                raise addons.ErreurAddon(_t("Le site a renvoyé une page web, pas un fichier (le modèle demande peut-être une connexion à ton compte)."))
            t["total"] = int(r.headers.get("Content-Length") or 0)
            if t["total"] > TAILLE_MODELE_MAX:
                raise addons.ErreurAddon(_t("Fichier trop gros ({} Go au plus).").format(TAILLE_MODELE_MAX // 1024 ** 3))
            Path(destination_dossier).mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(str(destination_dossier)).free < t["total"] + 2 * 1024 ** 3:
                raise addons.ErreurAddon(_t("Pas assez de place sur le disque pour ce fichier ({} Go).").format(round(t["total"] / 1e9, 1)))
            cible = Path(destination_dossier) / nom
            if cible.exists():
                raise addons.ErreurAddon(_t("Un fichier « {} » existe déjà : rien n'est écrasé.").format(nom))
            t["nom"] = nom
            partiel = cible.with_name(nom + ".part")
            try:
                with open(partiel, "wb") as sortie:
                    while True:
                        bloc = r.read(1024 * 1024)
                        if not bloc:
                            break
                        if t["arret"].is_set():
                            raise addons.ErreurAddon(_t("Téléchargement annulé."))
                        sortie.write(bloc)
                        t["fait"] += len(bloc)
                        if t["fait"] > TAILLE_MODELE_MAX:
                            raise addons.ErreurAddon(_t("Fichier trop gros ({} Go au plus).").format(TAILLE_MODELE_MAX // 1024 ** 3))
                if t["total"] and t["fait"] != t["total"]:
                    raise addons.ErreurAddon(_t("Téléchargement incomplet ({} sur {} octets).").format(t["fait"], t["total"]))
                partiel.replace(cible)
            finally:
                partiel.unlink(missing_ok=True)
        t["etat"] = "fini"
        CACHE["modeles"] = (0, None)
    except addons.ErreurAddon as erreur:
        t.update(etat="erreur", erreur=str(erreur))
    except (urllib.error.URLError, OSError, ValueError) as erreur:
        t.update(etat="erreur", erreur=_t("Téléchargement impossible : {}").format(erreur))


def demarrer_telechargement(url, genre):
    """Lance le téléchargement d'un modèle dans models/<genre> de ComfyUI, en arrière-plan. Seuls Hugging Face et Civitai sont permis, en https ; rien n'est écrasé."""
    url = str(url or "").strip()
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" and not (os.environ.get("LUTIN_WEB_LOCAL") == "1" and p.scheme == "http"):
        raise addons.ErreurAddon(_t("Colle l'adresse complète du fichier (https://…)."))
    if not hote_telechargement_permis(p.hostname):
        raise addons.ErreurAddon(_t("Seuls les téléchargements depuis Hugging Face et Civitai sont permis."))
    if genre not in GENRES_TELECHARGEMENT:
        raise addons.ErreurAddon(_t("Type de modèle inconnu."))
    dossier = addons.reglages(IDENT).get("dossier") or ""
    if not dossier or not dossier_valide(dossier):
        raise addons.ErreurAddon(_t("Choisis d'abord le dossier d'installation de ComfyUI."))
    nom = nom_de_fichier(url)
    with VERROU_TELECHARGEMENT:
        if TELECHARGEMENT["etat"] == "en cours":
            raise addons.ErreurAddon(_t("Un téléchargement est déjà en cours."))
        TELECHARGEMENT.update(etat="en cours", nom=nom, fait=0, total=0, erreur="")
        TELECHARGEMENT["arret"].clear()
    threading.Thread(target=_telecharger, args=(url, Path(dossier) / "models" / genre), daemon=True, name="comfy-telechargement").start()


# --------------------------------------------------------------------------- panneau de la page
def etat():
    r = detecter(profond=False)
    r["modeles"] = lister_modeles()
    r["workflows"] = sorted((addons.flux(IDENT).get("workflows") or {}).keys())
    r["telechargement"] = {k: v for k, v in TELECHARGEMENT.items() if k != "arret"}
    r["genres"] = list(GENRES_TELECHARGEMENT)
    return r


def action(nom, donnees):
    if nom == "detecter":
        return detecter()
    if nom == "modeles":
        return lister_modeles(forcer=True)
    if nom == "telecharger":
        demarrer_telechargement(donnees.get("url"), str(donnees.get("genre") or ""))
        return etat()
    if nom == "annuler_telechargement":
        TELECHARGEMENT["arret"].set()
        return etat()
    if nom == "utiliser_dossier":
        dossier = str(donnees.get("dossier") or "").strip()
        if not dossier_valide(dossier):
            raise addons.ErreurAddon(_t("Ce dossier n'est pas une installation de ComfyUI (main.py et models attendus)."))
        addons.enregistrer_reglages(IDENT, {"dossier": dossier})
        CACHE["modeles"] = (0, None)
        return detecter()
    raise addons.ErreurAddon(_t("Action inconnue."))
