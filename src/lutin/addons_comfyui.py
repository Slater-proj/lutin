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
import subprocess
import time
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
CACHE = {"modeles": (0, None)}


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


def trouver_dossier(argv=""):
    """Le dossier d'installation de ComfyUI, ou ''. Ordre : ce qu'annonce ComfyUI, la ligne de commande du processus, les emplacements usuels."""
    for source in (argv, _depuis_processus()):
        if source:
            c = Path(source).parent
            if dossier_valide(c):
                return str(c)
    for c in _usuels():
        if dossier_valide(c):
            return str(c)
    return ""


def detecter():
    """Cherche ComfyUI : tourne-t-il (réponse sur son port), quelle version, sur quelle carte, et où est-il installé ? Ne modifie rien."""
    r = addons.appeler(IDENT, "etat", delai=4)
    resultat = {"tourne": r["ok"], "erreur": "" if r["ok"] else r["erreur"], "version": (r["extrait"] or {}).get("version") or "", "gpu": (r["extrait"] or {}).get("gpu") or "",
                "dossier": trouver_dossier(_argv_absolu(r)), "dossier_regle": addons.reglages(IDENT).get("dossier", "")}
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


# --------------------------------------------------------------------------- panneau de la page
def etat():
    r = detecter()
    r["modeles"] = lister_modeles()
    r["workflows"] = sorted((addons.flux(IDENT).get("workflows") or {}).keys())
    return r


def action(nom, donnees):
    if nom == "detecter":
        return detecter()
    if nom == "modeles":
        return lister_modeles(forcer=True)
    if nom == "utiliser_dossier":
        dossier = str(donnees.get("dossier") or "").strip()
        if not dossier_valide(dossier):
            raise addons.ErreurAddon(_t("Ce dossier n'est pas une installation de ComfyUI (main.py et models attendus)."))
        addons.enregistrer_reglages(IDENT, {"dossier": dossier})
        CACHE["modeles"] = (0, None)
        return detecter()
    raise addons.ErreurAddon(_t("Action inconnue."))
