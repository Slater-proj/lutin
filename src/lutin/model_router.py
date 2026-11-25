"""Le routeur de modèles : choisir le bon modèle pour la demande, sans rien cacher.

Désactivé par défaut (réglage « Choix automatique du modèle »). Quand il est actif, avant chaque demande Lutin range la demande dans un profil, d'après des SIGNAUX OBJECTIFS (pas de modèle appelé, donc aucun délai) :
  - images      : une image est jointe -> le mécanisme existant des modèles « Images » s'en occupe ;
  - code        : du code, une extension de fichier, un mot de programmation -> un modèle « code » installé ;
  - raisonnement: une question qui demande d'analyser, comparer, démontrer, ou une très longue demande -> le plus gros modèle qui sait réfléchir et qui tient sur la machine (ou sur une machine appairée) ;
  - rapide      : une question courte sans fichier ni outil -> un petit modèle, plus vif.
Il ne change de modèle que pour CETTE demande (le réglage du modèle n'est jamais modifié), dit lequel il a pris et pourquoi, et n'agit jamais sur une mission autonome. Il ne propose que des modèles installés
(ou ceux d'une machine appairée qui répond), jamais un modèle noté « trop gros » pour la machine, et ne change que si le gain est net (un modèle au moins 1,3 fois plus gros pour réfléchir, 2 fois plus petit pour aller vite).
`monter` sert à la reprise : quand le modèle échoue (réponse vide, texte qui tourne en rond), Lutin essaie une fois avec un modèle plus gros."""
import re

from .i18n import t as _t

RE_CODE = re.compile(r"```|\b(?:def|class|function|import|return|const|SELECT|CREATE TABLE|docker-compose|Dockerfile)\b|\.(?:py|js|ts|tsx|jsx|cpp|java|rs|go|sh|ps1|sql|html|css|ya?ml)\b"
                     r"|\b(?:code|script|fonction|bug|programme|compil\w*|regex|sql|api|debug\w*|d[ée]bogu\w*|refactor\w*|python|javascript|typescript|powershell|bash|git|algorithme)\b", re.I)
RE_REASONING = re.compile(r"\b(?:pourquoi|compar\w+|analys\w+|d[ée]montr\w+|prouv\w+|calcul\w*|r[ée]sou\w+|strat[ée]gi\w+|optimis\w+|[ée]tape par [ée]tape|raisonn\w+|synth[èe]se|avantages et inconv[ée]nients|plan d[ée]taill[ée]|en d[ée]tail"
                       r"|why|compare|analy[sz]e|prove|step by step|trade-?offs?)\b", re.I)
RE_ACTION = re.compile(r"\b(?:fichiers?|dossiers?|lis|[ée]cris|cr[ée]e|cherche|recherche|web|internet|installe|lance|ex[ée]cute|supprime|modifie|ouvre|t[ée]l[ée]charge)\b", re.I)
RE_PARAMETERS = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)b\b", re.I)
REASONING_GAIN = 1.3          # un modèle au moins 1,3 fois plus gros pour valoir un changement
FAST_GAIN = 2.0          # un modèle au moins 2 fois plus petit pour valoir un changement
LONG_REQUEST = 700          # caractères : une demande aussi longue demande de la réflexion
SHORT_REQUEST = 140


def classify(demande, images=False):
    """(profil, raison) d'après la demande. profil : images, code, raisonnement, rapide ou defaut (rien à changer)."""
    texte = str(demande or "").strip()
    if images:
        return "images", _t("une image est jointe")
    if RE_CODE.search(texte):
        return "code", _t("du code ou une tâche de programmation")
    if RE_REASONING.search(texte) or len(texte) >= LONG_REQUEST:
        return "raisonnement", _t("une demande qui demande de réfléchir (analyser, comparer, une longue explication)")
    if 0 < len(texte) <= SHORT_REQUEST and not RE_ACTION.search(texte):
        return "rapide", _t("une question courte, sans fichier ni outil")
    return "defaut", ""


def size_gb(modele, catalogue):
    """Place approximative du modèle (Go) : celle du catalogue, sinon d'après le nombre de paramètres de son nom (en 4 bits, environ 0,6 Go par milliard) ; None si on ne sait pas."""
    for m in catalogue:
        if m.get("id") == modele:
            return float(m.get("go") or 0) or None
    p = RE_PARAMETERS.search(str(modele))
    return round(float(p.group(1)) * 0.6, 1) if p else None


def _info(modele, catalogue):
    return next((m for m in catalogue if m.get("id") == modele), None)


def _can_reason(modele, catalogue):
    m = _info(modele, catalogue)
    return bool(m) and "reflexion" in (m.get("capacites") or ())


def _knows_tools(modele, catalogue):
    m = _info(modele, catalogue)
    return bool(m) and "outils" in (m.get("capacites") or ())


def _usable_remote(distants):
    """[(modele, machine_id, nom_machine)] des machines appairées qui répondent."""
    sortie = []
    for d in distants or []:
        if d.get("etat") == "operationnel":
            sortie += [(n, d["id"], d.get("nom", "")) for n in d.get("modeles", [])]
    return sortie


def biggest(courant, installes, catalogue, trop_gros=(), distants=None, exiger_reflexion=True):
    """Le plus gros modèle utilisable, au moins GAIN_RAISONNEMENT fois plus gros que `courant` : {modele, machine, machine_nom} ou None. Les modèles du catalogue qui savent réfléchir sont préférés ;
    un modèle d'une machine appairée n'est retenu que s'il est lui aussi connu comme capable (par son catalogue ou sa taille)."""
    actuel = size_gb(courant, catalogue)
    candidats = []
    for nom in installes:
        if nom == courant or nom in trop_gros or (exiger_reflexion and not _can_reason(nom, catalogue)) or not _knows_tools(nom, catalogue):
            continue
        t = size_gb(nom, catalogue)
        if t:
            candidats.append((t, nom, "", ""))
    for nom, ident, machine_nom in _usable_remote(distants):
        t = size_gb(nom, catalogue)
        if t:
            candidats.append((t, nom, ident, machine_nom))
    candidats = [c for c in candidats if c[0] and (actuel is None or c[0] >= actuel * REASONING_GAIN)]
    if not candidats:
        return None
    t, nom, ident, machine_nom = max(candidats)
    return {"modele": nom, "machine": ident, "machine_nom": machine_nom}


def choose(demande, installes, courant, catalogue, images=False, trop_gros=(), distants=None):
    """Le modèle à utiliser pour CETTE demande, ou None pour garder le courant : {modele, machine, machine_nom, profil, raison}."""
    profil, raison = classify(demande, images)
    if profil in ("defaut", "images") or (len(installes) < 2 and not distants):
        return None
    actuel = size_gb(courant, catalogue)
    if profil == "code":
        codeurs = [(size_gb(n, catalogue) or 0, n) for n in installes if n != courant and n not in trop_gros and (_info(n, catalogue) or {}).get("role") == "code" and _knows_tools(n, catalogue)]
        if not codeurs or (_info(courant, catalogue) or {}).get("role") == "code":
            return None
        return {"modele": max(codeurs)[1], "machine": "", "machine_nom": "", "profil": profil, "raison": raison}
    if profil == "raisonnement":
        choix = biggest(courant, installes, catalogue, trop_gros, distants)
        return dict(choix, profil=profil, raison=raison) if choix else None
    if profil == "rapide":
        if actuel is None:
            return None          # modèle inconnu du catalogue : on ne le « rétrograde » pas à l'aveugle
        petits = [(size_gb(n, catalogue) or 99, n) for n in installes if n != courant and n not in trop_gros and (_info(n, catalogue) or {}).get("role") == "rapide" and _knows_tools(n, catalogue)]
        petits = [p for p in petits if p[0] * FAST_GAIN <= actuel]
        if not petits:
            return None
        return {"modele": min(petits)[1], "machine": "", "machine_nom": "", "profil": profil, "raison": raison}
    return None
