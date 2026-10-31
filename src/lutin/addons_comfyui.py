"""Partie vivante de l'addon ComfyUI : détecter ComfyUI, voir les modèles installés, et le piloter (générer une image, une vidéo, un son) à la demande du modèle de langage.

Lutin ne contient AUCUN workflow en dur : les « workflows » (le graphe de nœuds de ComfyUI, au format API) sont dans le flux de l'addon, donc modifiables : un workflow d'image est livré ; pour la vidéo ou le son,
on colle son propre workflow (ComfyUI : « Enregistrer (format API) »), avec des marques {prompt}, {largeur}, {hauteur}, {graine}, {pas}, {cfg}, {negatif}, {modele} là où Lutin doit mettre ses valeurs.

Règles de solidité :
- désactivé par défaut ; ComfyUI n'a pas besoin d'être ouvert : Lutin le lance quand tu demandes une image (après avoir rendu la mémoire au modèle de langage) et le referme ensuite s'il l'a lancé lui-même ;
- chaque génération demande ton accord (comme une modification de fichier), sauf accord automatique ; dans une tâche planifiée ou un message Telegram (lecture seule) elle est simulée, jamais faite ;
- la carte graphique est libérée du modèle de langage avant de générer (ils se la partagent) ;
- les appels ne visent que ComfyUI sur cette machine (adresse déclarée par le manifeste) ;
- l'attente d'un résultat s'arrête sur le bouton Arrêter et au bout d'un délai (réglable par type de workflow)."""
import atexit
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
NOEUDS = {"checkpoints": "objets_checkpoints", "loras": "objets_loras", "vae": "objets_vae", "diffusion_models": "objets_unet", "text_encoders": "objets_clip"}
ALIAS = {"unet": "diffusion_models", "clip": "text_encoders"}          # anciens noms de dossiers : mêmes modèles
FAMILLES = (("image_zimage", ("z_image", "zimage", "z-image")), ("image_qwen", ("qwen",)), ("image_flux", ("flux",)))          # le nom du fichier dit quelle famille de modèle (donc quels nœuds) il faut
RE_MARQUE = re.compile(r"\{([a-z_][a-z_0-9]*)\}")
RE_MARQUE_ENTIERE = re.compile(r"^\{([a-z_][a-z_0-9]*)\}$")
TYPES = ("image", "video", "son")
DELAI_PAR_DEFAUT = {"image": 600, "video": 3600, "son": 900}
HOTES_TELECHARGEMENT = ("huggingface.co", "hf.co", "civitai.com")          # et leurs sous-domaines (les fichiers sont servis par des réseaux de diffusion de ces sites)
GENRES_TELECHARGEMENT = ("checkpoints", "loras", "vae", "diffusion_models", "text_encoders", "controlnet", "upscale_models")
TAILLE_MODELE_MAX = 60 * 1024 ** 3
TELECHARGEMENT = {"etat": "", "nom": "", "fait": 0, "total": 0, "erreur": "", "arret": threading.Event()}
VERROU_TELECHARGEMENT = threading.Lock()
DELAI_DEMARRAGE = 240                    # secondes laissées à ComfyUI pour répondre après son lancement (le premier démarrage charge beaucoup de choses)
PROCESSUS = {"popen": None}              # le ComfyUI lancé par Lutin (celui de l'utilisateur n'est jamais fermé par Lutin)
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


def normaliser_dossier(chemin):
    """Le dossier qui contient main.py : celui qu'on a donné, ou ComfyUI/ dedans (la version portable range ComfyUI dans un sous-dossier)."""
    p = Path(str(chemin or "").strip())
    for c in (p, p / "ComfyUI", p / "ComfyUI_windows_portable" / "ComfyUI"):
        if dossier_valide(c):
            return str(c)
    return str(p)


def diagnostic_dossier(dossier):
    """(valide, raison) : ce dossier est-il bien celui de ComfyUI, et sinon pourquoi."""
    if not dossier:
        return False, _t("Dossier de ComfyUI non défini.")
    p = Path(dossier)
    if not p.is_dir():
        return False, _t("Ce dossier n'existe pas.")
    if not (p / "main.py").is_file():
        return False, _t("Il n'y a pas de main.py dans ce dossier : choisis celui de ComfyUI (il contient main.py et models).")
    if not (p / "models").is_dir():
        return False, _t("Il n'y a pas de dossier models ici : ce n'est pas une installation de ComfyUI.")
    return True, ""


def dossier_comfy():
    """Le dossier de ComfyUI à utiliser : celui qui est réglé s'il est valide, sinon celui qu'on trouve tout seul."""
    regle = addons.reglages(IDENT).get("dossier") or ""
    if regle and dossier_valide(regle):
        return regle
    return trouver_dossier("", profond=False) or ""


def pythons_possibles(dossier):
    d = Path(dossier)
    racine = d.parent
    candidats = [racine / "python_embeded" / "python.exe", d / "python_embeded" / "python.exe"]
    for v in (".venv", "venv"):
        for base in (d, racine):
            candidats += [base / v / "Scripts" / "python.exe", base / v / "bin" / "python"]
    return candidats


def commande_lancement(dossier, port):
    """La commande qui démarre ComfyUI avec SON Python (celui de la version portable ou de son environnement virtuel), sans ouvrir de navigateur. [] si on ne trouve pas ce Python."""
    for py in pythons_possibles(dossier):
        if py.is_file():
            commande = [str(py), "-s", "main.py", "--port", str(port), "--disable-auto-launch"]
            if "python_embeded" in str(py):
                commande.append("--windows-standalone-build")
            return commande
    return []


def en_marche():
    return addons.appeler(IDENT, "etat", delai=2)["ok"]


def assurer_comfyui():
    """Fait en sorte que ComfyUI tourne. S'il ne tourne pas, Lutin le lance : il rend d'abord la mémoire au modèle de langage (ils ne tiennent pas ensemble), démarre ComfyUI et attend qu'il réponde.
    Renvoie True si c'est Lutin qui l'a lancé (il le refermera ensuite)."""
    if en_marche():
        return False
    dossier = dossier_comfy()
    if not dossier:
        raise _m.ErreurOutil(_t("Je ne trouve pas ComfyUI : l'utilisateur doit choisir son dossier (Automatisation > Extensions > ComfyUI)."))
    port = addons.reglages(IDENT).get("port") or "8188"
    commande = commande_lancement(dossier, port)
    if not commande:
        raise _m.ErreurOutil(_t("ComfyUI ne tourne pas et je ne trouve pas son Python pour le lancer : l'utilisateur doit le lancer lui-même."))
    try:
        _m.liberer_vram()                                                       # le modèle de langage cède la carte graphique et la mémoire
    except Exception as erreur:  # noqa: BLE001
        _m.journaliser("ComfyUI : libération de la mémoire impossible ({!r}).".format(erreur))
    journal = open(_m.DONNEES / "comfyui.log", "ab")
    options = {"creationflags": 0x08000000} if os.name == "nt" else {}          # pas de fenêtre de console
    try:
        processus = subprocess.Popen(commande, cwd=dossier, stdout=journal, stderr=journal, stdin=subprocess.DEVNULL, **options)
    except OSError as erreur:
        raise _m.ErreurOutil(_t("Impossible de lancer ComfyUI : {}").format(erreur))
    finally:
        journal.close()
    PROCESSUS["popen"] = processus
    _m.journaliser("ComfyUI lancé par Lutin ({}).".format(" ".join(commande[:3])))
    fin = time.time() + DELAI_DEMARRAGE
    while time.time() < fin:
        if processus.poll() is not None:
            PROCESSUS["popen"] = None
            raise _m.ErreurOutil(_t("ComfyUI s'est arrêté au démarrage (voir donnees/comfyui.log)."))
        if en_marche():
            return True
        time.sleep(2)
    arreter_comfyui()
    raise _m.ErreurOutil(_t("ComfyUI n'a pas répondu après {} secondes (voir donnees/comfyui.log).").format(DELAI_DEMARRAGE))


def arreter_comfyui():
    """Ferme le ComfyUI lancé par Lutin (jamais celui de l'utilisateur)."""
    processus, PROCESSUS["popen"] = PROCESSUS["popen"], None
    if processus is None or processus.poll() is not None:
        return
    processus.terminate()
    try:
        processus.wait(15)
    except subprocess.TimeoutExpired:
        processus.kill()
    _m.journaliser("ComfyUI refermé par Lutin.")


atexit.register(arreter_comfyui)


def verifier():
    """La vérification de l'addon : trouve (ou valide) le dossier de ComfyUI et regarde si Lutin saura le lancer. ComfyUI n'a PAS besoin de tourner."""
    etapes = []
    regle = addons.reglages(IDENT).get("dossier") or ""
    dossier = regle or trouver_dossier("", profond=True)                         # un dossier choisi est jugé tel quel ; sinon on le cherche
    valide, raison = diagnostic_dossier(dossier)
    if not valide:
        return [{"appel": "dossier", "ok": False, "message": raison if regle else _t("Je ne trouve pas ComfyUI tout seul : choisis son dossier (celui qui contient main.py).")}]
    if dossier != regle:
        addons.enregistrer_reglages(IDENT, {"dossier": dossier})                  # trouvé tout seul : retenu
    n = sum(len(v) for v in _scan_dossier(dossier).values())
    etapes.append({"appel": "dossier", "ok": True, "message": _t("ComfyUI trouvé dans {} ({} modèle(s))").format(dossier, n)})
    tourne = en_marche()
    lanceur = commande_lancement(dossier, addons.reglages(IDENT).get("port") or "8188")
    if lanceur or tourne:
        etapes.append({"appel": "lancement", "ok": True, "message": _t("il tourne en ce moment") if tourne else _t("Lutin saura le lancer quand tu demanderas une image")})
    else:
        etapes.append({"appel": "lancement", "ok": False, "message": _t("je ne trouve pas son Python (python_embeded ou venv) : lance ComfyUI toi-même avant de demander une image")})
    return etapes


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


def _options(entree):
    """Les choix d'une entrée de liste de ComfyUI : l'ancien format est [[choix…], {…}], le nouveau ["COMBO", {"options": [choix…], …}]."""
    if isinstance(entree, list) and entree:
        if isinstance(entree[0], list):
            return entree[0]
        if entree[0] == "COMBO" and len(entree) > 1 and isinstance(entree[1], dict):
            return entree[1].get("options") or []
    return []


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
            noms = _options((r["extrait"] or {}).get("liste"))
            if noms:
                modeles[genre] = [str(n) for n in noms][:2000]
    if source == "aucune":
        dossier = dossier_comfy()
        if dossier and dossier_valide(dossier):
            modeles, source = _scan_dossier(dossier), "dossier"
    for ancien, nouveau in ALIAS.items():
        if ancien in modeles:
            modeles[nouveau] = sorted(set(modeles.get(nouveau, []) + modeles.pop(ancien)))
    valeur = {"source": source, "modeles": modeles}
    CACHE["modeles"] = (time.time(), valeur)
    return valeur


def modeles_utilisables():
    """[{nom, genre, famille}] : les checkpoints (workflow « image ») et les modèles de diffusion dont la famille est connue. Les autres ne sont pas proposés : Lutin ne saurait pas les faire tourner."""
    r = lister_modeles().get("modeles", {})
    sortie = [{"nom": n, "genre": "checkpoint", "famille": _t("Checkpoint")} for n in r.get("checkpoints", [])]
    for n in r.get("diffusion_models", []):
        cle = famille_de(n)
        if cle:
            sortie.append({"nom": n, "genre": "diffusion", "famille": libelle_famille(cle)})
    return sortie


def modeles_inutilisables():
    """Les modèles de diffusion dont la famille est inconnue (aucun workflow pour eux)."""
    return [n for n in lister_modeles().get("modeles", {}).get("diffusion_models", []) if not famille_de(n)]


def moteurs():
    """Ce que Lutin peut produire : {type: [moteurs]}. L'image a toujours des moteurs livrés ; la vidéo et le son n'en ont que si l'utilisateur a collé un workflow (clés « video… » et « son… »)."""
    ws = addons.flux(IDENT).get("workflows") or {}
    sortie = {"image": sorted({"Checkpoint"} | {libelle_famille(c) for c, _ in familles_connues() if c in ws})}
    for type_ in ("video", "son"):
        sortie[type_] = sorted(k for k in ws if k == type_ or k.startswith(type_ + "_"))
    return sortie


def choix(cle):
    """Les valeurs d'un réglage à liste déroulante dynamique (addons.decrire) : le modèle à utiliser = « automatique » ou l'un des modèles que Lutin sait faire tourner."""
    if cle != "modele":
        return None
    return [["", _t("Automatique (le premier installé, ou celui que Lutin choisit selon ta demande)")]] + [[m["nom"], "{} — {}".format(m["nom"], m["famille"])] for m in modeles_utilisables()]


def adapter_outil(outil):
    """Une copie de l'outil comfy_generer qui ne propose que ce qui marche : les types qui ont un workflow, et les modèles que Lutin sait faire tourner."""
    import copy
    o = copy.deepcopy(outil)
    props = o["function"]["parameters"]["properties"]
    types = [t for t, m in moteurs().items() if m]
    props["type"] = {"type": "string", "enum": types, "description": _t("Ce qu'il faut générer (défaut : image). Seuls les types disponibles sont proposés.")}
    noms = [m["nom"] for m in modeles_utilisables()]
    if noms:
        reglage = str(addons.reglages(IDENT).get("modele") or "").strip()
        props["modele"] = {"type": "string", "description": _t("Nom exact d'un de ces modèles (les autres ne fonctionnent pas) : {}.").format(", ".join(noms[:30]) + (" …" if len(noms) > 30 else ""))
                           + (_t(" L'utilisateur a choisi « {} » dans ses réglages : ne propose un autre modèle que s'il l'a demandé.").format(reglage) if reglage else "")}
    return o


def texte_modeles():
    r = lister_modeles()
    if r["source"] == "aucune":
        return _t("ComfyUI ne répond pas et aucun dossier d'installation n'est réglé : impossible de lister les modèles.")
    lignes = [_t("Modèles installés (lus {}) :").format(_t("dans ComfyUI") if r["source"] == "api" else _t("dans le dossier d'installation"))]
    for genre, noms in r["modeles"].items():
        lignes.append("- {} ({}) : {}".format(genre, len(noms), ", ".join(noms[:40]) + (" …" if len(noms) > 40 else "")))
        if genre == "diffusion_models":
            lignes.append("  " + _t("Famille reconnue : ") + ", ".join("{} → {}".format(n, famille_de(n) or _t("inconnue")) for n in noms[:15]))
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


LIBELLES_FAMILLE = {"image_flux": "Flux", "image_qwen": "Qwen-Image", "image_zimage": "Z-Image"}


def familles_connues():
    """Les familles de modèles que Lutin sait faire tourner : celles qui sont livrées (Flux, Qwen-Image, Z-Image) et celles que l'utilisateur ajoute dans le flux, SI le workflow du même nom existe :
    {"familles": {"image_hidream": ["hidream"]}, "workflows": {"image_hidream": {…}}, "ressources": {"image_hidream": {…}}}."""
    f = addons.flux(IDENT)
    workflows = f.get("workflows") or {}
    ajoutees = []
    for cle, mots in (f.get("familles") or {}).items():
        if isinstance(mots, list) and str(cle) in workflows:
            ajoutees.append((str(cle), tuple(str(m).lower() for m in mots if str(m).strip())))
    return tuple(ajoutees) + FAMILLES                  # les siennes d'abord : il peut remplacer une famille livrée


def libelle_famille(cle):
    return LIBELLES_FAMILLE.get(cle) or str(cle).replace("image_", "").replace("_", " ").strip().title()


def famille_de(nom):
    """La famille d'un modèle de diffusion d'après son nom de fichier (« image_flux », « image_qwen », « image_zimage », ou une famille ajoutée par l'utilisateur), ou ''."""
    n = str(nom).lower()
    for cle, mots in familles_connues():
        if any(m in n for m in mots):
            return cle
    return ""


def _installes(genre):
    return list(lister_modeles().get("modeles", {}).get(genre, []))


def _correspond(liste, voulu):
    """Le fichier installé qui correspond à ce que demande le modèle : le même nom, ou à la casse près, ou un seul fichier qui contient ces mots."""
    voulu = str(voulu).strip().lower()
    for n in liste:
        if n.lower() == voulu or n.lower().rsplit("/", 1)[-1] == voulu:
            return n
    contenant = [n for n in liste if voulu and voulu in n.lower()]
    return contenant[0] if len(contenant) == 1 else ""


MOTS_BANALS = {"safetensors", "ckpt", "base", "fp8", "fp16", "fp32", "bf16", "dev", "pruned", "emaonly", "ema", "final", "model", "models", "checkpoint", "diffusion", "scaled", "lora", "vae"}


def _nomme(nom, demande, message):
    """L'utilisateur a-t-il nommé ce modèle dans ses messages ? Par le nom que propose le modèle de langage, par le nom du fichier, ou par un mot distinctif du fichier (« sdxl », « flux »…)."""
    msg = str(message or "").lower()
    if not msg:
        return False
    racine = str(nom).rsplit("/", 1)[-1].lower().rsplit(".", 1)[0]
    mots = {str(demande).lower().strip(), racine} | {m for m in re.split(r"[^a-z0-9]+", racine) if len(m) >= 4 and m not in MOTS_BANALS and not m.isdigit()}
    return any(m and m in msg for m in mots)


def choisir_modele(demande="", message="", detail=False):
    """(clé du workflow, nom du fichier) : un checkpoint → le workflow « image » ; un modèle de diffusion (Flux, Qwen-Image, Z-Image…) → celui de sa famille. Sans demande : le réglage, puis le premier modèle utilisable."""
    reglage = str(addons.reglages(IDENT).get("modele") or "").strip()
    demande = str(demande or "").strip()
    checkpoints, diffusion = _installes("checkpoints"), _installes("diffusion_models")
    if not checkpoints and not diffusion:
        raise _m.ErreurOutil(_t("Je ne vois aucun modèle d'image dans ComfyUI (ni dans checkpoints ni dans diffusion_models) : l'utilisateur doit en installer un."))
    ecarte = ""
    if reglage and demande:
        proposee = _correspond(checkpoints, demande) or _correspond(diffusion, demande) or demande
        if not _nomme(proposee, demande, message):
            ecarte, demande = demande, ""                  # le modèle de langage propose un modèle que l'utilisateur n'a pas nommé : le réglage de l'utilisateur l'emporte

    def fin(r):
        return r + ((ecarte,) if detail else ())
    source_reglage = bool(reglage) and not demande
    demande = demande or reglage
    if demande:
        trouve = _correspond(checkpoints, demande)
        if trouve:
            return fin(("image", trouve))
        trouve = _correspond(diffusion, demande)
        if trouve:
            cle = famille_de(trouve)
            if not cle:
                raise _m.ErreurOutil(_t("Je ne connais pas la famille du modèle « {} » (Flux, Qwen-Image et Z-Image sont gérés) : l'utilisateur peut coller son propre workflow dans « Flux… ».").format(trouve))
            return fin((cle, trouve))
        raise _m.ErreurOutil(_t("Le modèle « {} » n'est pas installé{}. Disponibles : {}").format(demande, _t(" (c'est le réglage de l'utilisateur)") if source_reglage else "", ", ".join((checkpoints + diffusion)[:25])))
    if checkpoints:
        return fin(("image", checkpoints[0]))
    for n in diffusion:
        if famille_de(n):
            return fin((famille_de(n), n))
    raise _m.ErreurOutil(_t("Aucun de tes modèles de diffusion n'est d'une famille que je connais (Flux, Qwen-Image, Z-Image) : {}").format(", ".join(diffusion[:15])))


def ressources_pour(cle, flux_actuel):
    """Les fichiers dont le workflow a besoin en plus du modèle (encodeur de texte, VAE) : choisis parmi ceux qui sont installés, d'après les mots du flux (« ressources »)."""
    voulues = (flux_actuel.get("ressources") or {}).get(cle) or {}
    trouvees = {}
    for nom, (genre, mots) in {"clip": ("text_encoders", voulues.get("clip")), "clip2": ("text_encoders", voulues.get("clip2")), "vae": ("vae", voulues.get("vae"))}.items():
        if not mots:
            continue
        installes = _installes(genre)
        choix = next((n for mot in mots for n in installes if mot.lower() in n.lower().rsplit("/", 1)[-1]), "")
        if not choix:
            raise _m.ErreurOutil(_t("Il me manque un fichier pour ce modèle : {} (dossier {}, nom contenant {}). L'utilisateur doit l'installer.").format({"clip": _t("encodeur de texte"), "clip2": _t("second encodeur de texte"), "vae": "VAE"}[nom], genre, " / ".join(mots)))
        trouvees[nom] = choix
    return trouvees


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
    v["guidance"] = float(base.get("guidance", 3.5))
    v["decalage"] = float(base.get("decalage", 3.0))
    v["modele"] = str(args.get("modele") or addons.reglages(IDENT).get("modele") or base.get("modele") or "").strip()
    return v


def outil_generer(args, ctx):
    """L'outil « comfy_generer » : image, vidéo ou son. Demande ton accord, libère la carte graphique, envoie le workflow et attend le résultat."""
    type_ = str(args.get("type") or "image").lower()
    if type_ not in TYPES:
        raise _m.ErreurOutil(_t("Type inconnu : « {} » (image, video ou son).").format(type_))
    f = addons.flux(IDENT)
    ecrit = " ".join(str(m.get("content") or "") for m in ((ctx.get("conv") or {}).get("messages") or [])[-40:] if m.get("role") == "user")          # ce que l'utilisateur a écrit : un modèle qu'il nomme lui-même est respecté
    if ctx.get("mission"):
        from . import mission as _mission
        cahier = _mission.trouver(ctx["mission"]) or {}
        ecrit += " " + str(cahier.get("cahier") or "") + " " + str(cahier.get("note") or "")             # dans une mission, la demande est le cahier des charges
    cle, modele, ignore = choisir_modele(args.get("modele"), ecrit, detail=True) if type_ == "image" else (type_, "", "")          # image : le modèle choisi décide du workflow (checkpoint, Flux, Qwen-Image, Z-Image)
    wf = (f.get("workflows") or {}).get(cle)
    if not wf:
        raise _m.ErreurOutil(_t("Aucun workflow « {} » dans le flux de l'addon ComfyUI : l'utilisateur doit en coller un, ou revenir à la version livrée (Extensions > ComfyUI > Flux…).").format(cle))
    v = parametres(args, f, cle)
    if modele:
        v["modele"] = modele
        v.update(ressources_pour(cle, f))
    complet = remplir_workflow(wf, v)
    restantes = marques_restantes(complet)
    if restantes:
        raise _m.ErreurOutil(_t("Le workflow contient des marques que Lutin ne sait pas remplir : {}.").format(", ".join(sorted("{" + x + "}" for x in restantes))))
    detail = _t("Description : {}\nTaille : {}×{} · modèle : {}").format(v["prompt"][:300], v["largeur"], v["hauteur"], v["modele"] or _t("(celui du workflow)"))
    auto = bool(ctx.get("auto_commandes"))          # générer lance ComfyUI et prend la carte graphique : la case « Commandes automatiques » vaut aussi pour cela
    if not ctx["accord"](_t("Générer {} avec ComfyUI").format({"image": _t("une image"), "video": _t("une vidéo"), "son": _t("un son")}[type_]), detail, "", auto=auto):
        from . import outils
        return outils.refus(ctx, _t("Refusé par l'utilisateur."))
    lance = assurer_comfyui()
    try:
        res = _soumettre_et_attendre(f, v, complet, type_, ctx)
        if ignore:
            res += _t("\nModèle utilisé : {} (réglage de l'utilisateur) ; le modèle « {} » que tu demandais n'a pas été retenu car l'utilisateur ne l'a pas nommé.").format(modele, ignore)
        return res
    finally:
        if lance and addons.reglages(IDENT).get("fermer_apres", "oui") != "non":
            arreter_comfyui()                                                      # ComfyUI rend la mémoire : le modèle de langage la retrouve à la prochaine question


def _joindre(fichiers, ctx):
    """Les fichiers qui ne sont pas des images (vidéo, son) : une carte sous le message pour les ouvrir, les télécharger ou les supprimer."""
    dossier = addons.reglages(IDENT).get("dossier") or ""
    if not dossier:
        return
    sortie = (Path(dossier) / "output").resolve()
    for f_ in fichiers[:8]:
        try:
            p = (sortie / f_).resolve()
            if sortie in p.parents and p.is_file() and p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                ctx.setdefault("fichiers_joints", []).append(str(p))
        except OSError:
            continue


def detail_erreur(corps):
    """Le diagnostic d'un refus de ComfyUI (HTTP 400) : le message général, puis pour chaque nœud fautif sa classe et ses erreurs (« Value not in list: ckpt_name… »). Le texte brut si ce n'est pas du JSON de ComfyUI."""
    try:
        d = json.loads(corps)
    except (TypeError, ValueError):
        return str(corps or "")[:600]
    if not isinstance(d, dict):
        return str(corps)[:600]
    lignes = []
    e = d.get("error")
    if isinstance(e, dict):
        lignes.append(" — ".join(str(x) for x in (e.get("type"), e.get("message"), e.get("details")) if x))
    elif e:
        lignes.append(str(e))
    for noeud, info in list((d.get("node_errors") or {}).items())[:8]:
        if not isinstance(info, dict):
            continue
        erreurs = "; ".join(" ".join(str(x) for x in (x_.get("message"), x_.get("details")) if x) for x_ in (info.get("errors") or [])[:3] if isinstance(x_, dict))
        lignes.append(_t("Nœud {} ({}) : {}").format(noeud, info.get("class_type", "?"), erreurs or "?"))
    return "\n".join(lignes)[:1500] or str(corps)[:600]


def detail_execution(messages):
    """L'erreur d'exécution d'un travail raté (historique de ComfyUI) : nœud, type d'exception, message."""
    for m in reversed(messages or []):
        if isinstance(m, list) and len(m) == 2 and m[0] == "execution_error" and isinstance(m[1], dict):
            x = m[1]
            return _t("Nœud {} ({}) : {} — {}").format(x.get("node_id", "?"), x.get("node_type", "?"), x.get("exception_type", "?"), str(x.get("exception_message", "")).strip()[:600])
    return ""


def _afficher(fichiers, ctx):
    """Copie les images produites (PNG, JPEG, WebP, GIF animé) dans les images de Lutin et les attache au résultat de l'outil : la page les affiche dans la conversation. Renvoie les identifiants."""
    from . import images
    dossier = addons.reglages(IDENT).get("dossier") or ""
    if not dossier:
        return []
    sortie = (Path(dossier) / "output").resolve()
    ids = []
    for f_ in fichiers[:4]:
        try:
            p = (sortie / f_).resolve()
            if sortie in p.parents and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif") and p.is_file():
                ident = images.enregistrer(p.read_bytes())
                ids.append(ident)
                ctx.setdefault("medias_fichiers", {})[ident] = str(p)
        except (OSError, ValueError):
            continue                                                       # trop grosse, illisible : le chemin reste dans le résultat
    if ids:
        ctx.setdefault("medias", []).extend(ids)
    return ids


def _soumettre_et_attendre(f, v, complet, type_, ctx):
    try:
        if _m.reglages().get("liberer_si_comfy", True):
            _m.liberer_vram()                                                      # le modèle de langage cède la carte graphique à ComfyUI
    except Exception as erreur:  # noqa: BLE001  (ne pas échouer pour ça)
        _m.journaliser("ComfyUI : libération de la carte impossible ({!r}).".format(erreur))
    r = addons.appeler(IDENT, "soumettre", {"workflow": complet}, delai=30)
    if not r["ok"]:
        return _t("ComfyUI a refusé le travail :\n{}").format(detail_erreur(r.get("corps")) if r.get("corps") else r["erreur"])
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
                brut = (entree.get("status") or {}).get("messages", [])
                return _t("ComfyUI a échoué : {}").format(detail_execution(brut) or json.dumps(brut[-2:], ensure_ascii=False)[:400])
            fichiers = []
            for sortie in (entree.get("outputs") or {}).values():
                for genre in ("images", "gifs", "videos", "audio"):
                    for x in sortie.get(genre, []) or []:
                        if isinstance(x, dict) and x.get("filename") and x.get("type", "output") == "output":
                            fichiers.append("/".join(p for p in (x.get("subfolder"), x["filename"]) if p))
            if fichiers or statut == "success":
                dossier = addons.reglages(IDENT).get("dossier") or ""
                chemins = [str(Path(dossier) / "output" / f_) if dossier else "output/" + f_ for f_ in fichiers]
                montrees = _afficher(fichiers, ctx)
                _joindre(fichiers, ctx)
                return _t("Terminé ({} fichier(s)) :\n{}\nGraine : {}.").format(len(fichiers), "\n".join(chemins) or _t("(ComfyUI n'a rien enregistré)"), v["graine"]) + (
                    _t("\nL'image est affichée à l'utilisateur dans la conversation : ne la montre pas toi-même et ne répète pas son chemin.") if montrees else "")
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
    regle = addons.reglages(IDENT).get("dossier") or ""
    r["dossier"] = regle or r["dossier"]
    r["valide"], r["raison"] = diagnostic_dossier(r["dossier"])
    r["lancement"] = bool(r["valide"] and commande_lancement(r["dossier"], addons.reglages(IDENT).get("port") or "8188"))
    r["modeles"] = lister_modeles()
    r["familles"] = {n: famille_de(n) for n in r["modeles"].get("modeles", {}).get("diffusion_models", [])}
    r["libelles_familles"] = {c: libelle_famille(c) for c, _ in familles_connues()}
    r["workflows"] = sorted((addons.flux(IDENT).get("workflows") or {}).keys())
    r["moteurs"] = moteurs()
    r["inutilisables"] = modeles_inutilisables()
    r["telechargement"] = {k: v for k, v in TELECHARGEMENT.items() if k != "arret"}
    r["genres"] = list(GENRES_TELECHARGEMENT)
    return r


def action(nom, donnees):
    if nom == "detecter":
        dossier = trouver_dossier("", profond=True)
        if dossier:
            addons.enregistrer_reglages(IDENT, {"dossier": dossier})
            CACHE["modeles"] = (0, None)
        DETECTION["dossier"] = dossier
        return dict(etat(), introuvable=not dossier)
    if nom == "modeles":
        return lister_modeles(forcer=True)
    if nom == "telecharger":
        demarrer_telechargement(donnees.get("url"), str(donnees.get("genre") or ""))
        return etat()
    if nom == "annuler_telechargement":
        TELECHARGEMENT["arret"].set()
        return etat()
    if nom == "utiliser_dossier":
        dossier = normaliser_dossier(donnees.get("dossier"))
        valide, raison = diagnostic_dossier(dossier)
        if not valide:
            raise addons.ErreurAddon(raison)
        addons.enregistrer_reglages(IDENT, {"dossier": dossier})
        CACHE["modeles"] = (0, None)
        return etat()
    raise addons.ErreurAddon(_t("Action inconnue."))
