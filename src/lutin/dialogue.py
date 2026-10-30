"""Le dialogue avec Ollama : démarrage et état d'Ollama, requêtes au modèle, boucle de l'agent (tours d'outils), résumé des conversations, titres. L'état reste dans moteur (« _m.NOM »)."""
from pathlib import Path
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
import threading
import time
import urllib.request
from . import moteur as _m


# --------------------------------------------------------------------------- dialogue avec Ollama
RE_APPEL_MAL_FORME = re.compile(r"XML|syntax|parse|parsing|tool", re.I)


RAPPEL_APPEL = "Ton dernier appel d'outil était mal formé et a été rejeté. Recommence en appelant l'outil avec des arguments simples ; pour un long contenu, fais plusieurs petits appels."


RE_PLANTAGE = re.compile(r"llama-server|out.of.memory|cudaMalloc|exit status|terminated|runner|connection (reset|refused)|unexpectedly", re.I)      # Ollama a planté ou manque de mémoire vidéo : on réessaie avec moins de contexte


CAPACITES = {}          # modèle -> capacités annoncées par Ollama (« tools », « thinking »...), gardées en mémoire


RE_APPEL_BALISE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


RE_APPEL_XML = re.compile(r"<function=([A-Za-z_]+)>(.*?)</function>", re.S)


RE_APPEL_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```|^\s*(\{\s*\"name\".*\})\s*$", re.S)


OUTILS_WEB = {"web_chercher", "web_lire"}


def memoire_longue(conv, r):
    """Comment cette conversation garde son fil : « resume » (le début est résumé par le modèle) ou « fichier » (fiche de suivi). Le choix de la conversation l'emporte sur le réglage général."""
    choix = (conv or {}).get("memoire_longue") or r.get("memoire_longue") or "resume"
    return choix if choix in ("resume", "fichier") else "resume"


def outils_du_mode(r):
    """Les outils envoyés au modèle : ceux du mode (voir modes.py), sans web si la case « Web » est décochée ou en mode hors ligne, sans l'outil d'images s'il n'est pas branché."""
    exclus = _modes.outils_exclus(r.get("mode"), [t["function"]["name"] for t in _m.OUTILS])
    if not r.get("web", True) or _hl.actif():
        exclus |= OUTILS_WEB
    if not _m.OUTIL:
        exclus |= _modes.IMAGES
    if r.get("memoire_longue") != "fichier":
        exclus.add("suivi")                                             # sans fiche de suivi, l'outil n'a pas de sens
    return [t for t in _m.OUTILS if t["function"]["name"] not in exclus]


def extraire_appels_texte(contenu, autorises=None):
    """Certains modèles écrivent leur appel d'outil dans la réponse (<tool_call>{...}</tool_call>, <function=nom><parameter=...>, ou un bloc JSON seul)
    au lieu d'utiliser le mécanisme prévu : on le retrouve pour l'exécuter. Renvoie (appels, texte sans les appels)."""
    noms = set(autorises) if autorises is not None else {t["function"]["name"] for t in _m.OUTILS}
    appels, morceaux = [], []

    def ajouter(nom, args, span):
        if nom in noms:
            appels.append({"function": {"name": nom, "arguments": args}})
            morceaux.append(span)
    for m in RE_APPEL_BALISE.finditer(contenu):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(d, dict):
            ajouter(d.get("name"), d.get("arguments", d.get("parameters", {})), m.span())
    for m in RE_APPEL_XML.finditer(contenu):
        ajouter(m.group(1), dict(re.findall(r"<parameter=([A-Za-z_]+)>\s*(.*?)\s*</parameter>", m.group(2), re.S)), m.span())
    if not appels:                      # un bloc JSON n'est un appel que s'il est (presque) toute la réponse : un exemple cité dans une explication ne doit pas s'exécuter
        for m in RE_APPEL_JSON.finditer(contenu):
            brut = m.group(1) or m.group(2)
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
    installes = etat_ollama()["installes"]
    candidats = [m["id"] for m in _m.MODELES if m["id"] in installes and "vision" in (m.get("capacites") or [])]
    candidats.sort(key=lambda i: next((0 for m in _m.MODELES if m["id"] == i and m["role"] == "vision"), 1))
    return next((i for i in candidats if i != courant), None)


def modele_de_repli(courant, genre):
    """Un autre modèle déjà installé, pour dépanner quand le modèle courant échoue : un modèle rapide pour les appels d'outils ratés, un plus léger pour les plantages."""
    installes = etat_ollama()["installes"]
    ordre = ("rapide", "leger") if genre == "outil" else ("leger", "rapide")
    for role in ordre:
        for m in _m.MODELES:
            if m["role"] == role and m["id"] != courant and m["id"] in installes:
                return m["id"]
    return None


def capacites(modele):
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


def ps_modele(nom):
    """Le modèle est-il en mémoire, et quelle part est sur la carte graphique ? (None = pas chargé ou Ollama muet)"""
    try:
        for m in ollama_json("/api/ps", None, 3).get("models", []):
            if m.get("name") == nom or m.get("model") == nom:
                return {"taille": m.get("size") or 0, "vram": m.get("size_vram") or 0}
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return None


def etat_ollama():
    try:
        tags = ollama_json("/api/tags", None, 3)
        return {"actif": True, "installes": [m["name"] for m in tags.get("models", [])], "tailles": {m["name"]: int(m.get("size") or 0) for m in tags.get("models", [])}}
    except (urllib.error.URLError, OSError, ValueError):
        return {"actif": False, "installes": [], "tailles": {}}


def chemin_ollama():
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
    for nom in reg["perso"] + [n for n in installes if n not in reg["perso"]]:
        if nom in vus:
            continue
        vus.add(nom)
        liste.append({"id": nom, "nom": nom, "go": round(tailles.get(nom, 0) / 1e9, 1), "role": "perso", "origine": "perso" if nom in reg["perso"] else "installe"})
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
    if modele not in [m["id"] for m in _m.MODELES] and not RE_NOM_MODELE.match(modele):
        raise ValueError("Nom de modèle invalide.")
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
            PULLS[modele].update({"statut": "erreur", "texte": str(erreur)[:300]})
    threading.Thread(target=travail, daemon=True).start()
    return PULLS[modele]


def supprimer_modele(modele):
    if modele not in [m["id"] for m in _m.MODELES] and not re.match(r"^[A-Za-z0-9_./:-]{1,100}$", modele):
        raise ValueError("Nom de modèle invalide.")
    if _m.reglages()["modele"] == modele:
        raise ValueError("C'est le modèle actif : change de modèle actif avant de supprimer.")
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
    return {"ok": True, "modele": modele}


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
            + (_t("\n\n# ESSAI À BLANC\nTes écritures et tes commandes ne sont PAS exécutées : c'est une simulation, l'utilisateur voit ce que tu proposes. Propose ce que tu ferais (fichiers, contenu, commandes), sans insister ni réessayer. Lire et chercher fonctionnent normalement.\n") if r.get("essai_a_blanc") else "")
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
    msgs = [{"role": "system", "content": consignes_systeme(r) + _m.texte_taches(conv)}]
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
            if msgs[i]["role"] in ("user", "assistant", "tool") and not msgs[i].get("content", "").startswith(("[Résumé", "[Fiche de suivi", "Compris, je m'appuie")):
                del msgs[i]
                dernier_user -= 1
                break
        else:
            break
    return msgs


def compacter(conv, r, emit, forcer=False):
    """Quand la conversation approche de la taille du contexte, le début est résumé par le modèle. forcer (commande /compact) : on résume tout sauf le dernier échange,
    même si la conversation est encore courte. Renvoie True si un résumé a été fait."""
    limite = int(r["num_ctx"] * 0.6)
    msgs = conv["messages"]
    if forcer:
        coupe = max((i for i, m in enumerate(msgs) if m["role"] == "user"), default=0)
        if coupe < 2:
            return False
    else:
        if estimer(msgs) + len(conv.get("resume", "")) // 3 < limite or len(msgs) < 8:
            return False
        coupe = max(2, len(msgs) // 2)
        while coupe < len(msgs) and msgs[coupe]["role"] != "user":             # on coupe avant un message de l'utilisateur
            coupe += 1
    ancien = msgs[:coupe]
    texte = "\n".join("[{}] {}".format(m["role"], (m.get("content") or ("(outils : " + ", ".join(t["function"]["name"] for t in m.get("tool_calls", [])) + ")"))[:1500]) for m in ancien)
    texte = texte[-int(r["num_ctx"] * 1.8):]          # le texte à résumer doit lui aussi tenir dans le contexte
    emit({"type": "info", "texte": "Conversation longue : résumé du début..."})
    try:
        rep = ollama_json("/api/chat", {"model": r["modele"], "stream": False, "think": False, "options": _m.options_modele(r, 0.2),
                                        "messages": [{"role": "system", "content": "Tu résumes une conversation pour pouvoir la continuer plus tard. Garde : les décisions, les fichiers modifiés, ce qui reste à faire, les préférences de l'utilisateur. Sois dense, en français."},
                                                     {"role": "user", "content": (conv.get("resume", "") + "\n\n" if conv.get("resume") else "") + texte}]}, 600)
        nouveau_resume = (rep.get("message", {}).get("content") or "").strip()[:6000]
        if not nouveau_resume:                      # résumé vide : on garde tout plutôt que de perdre le début
            _m.journaliser("Résumé vide : conversation {} gardée entière.".format(conv.get("id")))
            return False
        conv["resume"] = nouveau_resume
        conv["messages"] = msgs[coupe:]
        conv.pop("jetons", None)                    # le chiffre de contexte d'avant le résumé n'est plus vrai
        return True
    except (urllib.error.URLError, OSError, ValueError) as erreur:
        # Le résumé a échoué : on ne supprime rien (ajuster_contexte raccourcit déjà ce qui est envoyé au modèle).
        _m.journaliser("Résumé impossible ({}) : conversation {} gardée entière.".format(erreur, conv.get("id")))
        return False


def compacter_conversation(ident):
    """Commande /compact : résume le début de la conversation maintenant (le modèle est sollicité, comptez quelques secondes)."""
    if ident in _m.TOURS_ACTIFS:
        raise ValueError("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la.")
    conv = _m.conv_lire(ident)
    avant = len(conv["messages"])
    info = []
    if not compacter(conv, _m.reglages(), info.append, forcer=True):
        raise ValueError("Rien à résumer (conversation trop courte) ou le résumé a échoué : voir donnees/lutin.log.")
    _m.conv_ecrire(conv)
    return {"ok": True, "avant": avant, "apres": len(conv["messages"]), "jauge": jauge_contexte(conv)}


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
        if auto and ctx.get("web_lu"):
            # Garde-fou : du texte venu d'internet a été lu pendant ce tour, il pourrait contenir une consigne piégée. Plus d'accord automatique jusqu'à la fin du tour.
            emit({"type": "info", "texte": "Du contenu web a été lu : l'accord automatique est suspendu pour la suite de cette demande, ta confirmation est demandée."})
            auto = False
        if auto:
            emit({"type": "info", "texte": "Accord automatique : " + titre})
            ctx["dernier_accord"] = "auto"
            return True
        a = _m.Attente(titre, detail, diff)
        emit({"type": "approbation", "id": a.id, "titre": titre, "detail": detail, "diff": diff})
        ok = a.attendre(stop=stop)
        if stop.is_set():
            raise _m.Arret()
        emit({"type": "info", "texte": (_t("Accepté : {}") if ok else _t("Refusé : {}")).format(titre)})
        ctx["dernier_accord"] = "manuel"
        return ok
    ctx = {"essai": bool(r.get("essai_a_blanc")), "identite": identite, "accord": accord, "auto_ecriture": bool(r.get("auto_ecriture")), "auto_commandes": bool(r.get("auto_commandes")), "stop": stop, "conv": conv, "emit": emit, "web": bool(r.get("web", True)), "limite_ram": int(r.get("limite_ram_commande_go", 0) * _m.GO),
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
    if not _m.controle_avant_demande(r, emit, conv["id"]):
        _m.conv_ecrire(conv)                             # la demande est gardée : « continue » la relancera quand le problème sera réglé
        emit({"type": "fin", "conversation": {"id": conv["id"], "titre": conv["titre"]}})
        return
    r["memoire_longue"] = memoire_longue(conv, r)
    try:
        if r["memoire_longue"] == "resume":
            compacter(conv, r, emit)
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
        except (OSError, ValueError) as erreur:
            _m.journaliser("Fiche de suivi non mise à jour (conversation {}) : {!r}".format(conv.get("id"), erreur))
    if ctx["tour"]["fichiers"]:                       # cette demande a touché des fichiers : le bouton « Annuler » les rétablira
        conv["annulable"] = {"id": ctx["tour"]["id"], "fichiers": sorted(ctx["tour"]["fichiers"])}
    _m.conv_ecrire(conv)
    if time.time() - _m.PURGE["derniere"] > 1800:        # au plus une fois toutes les 30 minutes
        try:
            _m.purger_donnees()
        except OSError as erreur:
            _m.journaliser("Purge impossible : {!r}".format(erreur))
    emit({"type": "fin", "conversation": {"id": conv["id"], "titre": conv["titre"]}})


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
    if r.get("memoire_longue") == "fichier":
        try:
            fiche = _suivi.texte_pour_modele(conv["id"], r["num_ctx"])            # lue UNE fois pour tout le tour : le début de la requête reste identique, Ollama le garde en cache
        except ValueError:
            fiche = ""
    derniere_demande = next((m.get("content") or "" for m in reversed(conv["messages"]) if m.get("role") == "user"), "")
    try:
        consigne = _suivi.directive_execution(conv, derniere_demande, conv["id"])
    except ValueError:
        consigne = ""
    if consigne:
        emit({"type": "info", "texte": _t("▶ Validation reçue : j'exécute l'étape en cours sans replanifier.")})
    for idx_tour in range(tours_max):
        msgs = [{"role": "system", "content": consignes_systeme(r) + _m.texte_taches(conv) + rappels_texte}]
        if conv.get("resume"):
            msgs.append({"role": "user", "content": "[Résumé de la conversation jusqu'ici]\n" + conv["resume"]})
            msgs.append({"role": "assistant", "content": "Compris, je continue."})
        historique = _pieces.pour_le_modele(conv["messages"], _pieces.budget_caracteres(r["num_ctx"]))          # le texte des fichiers joints s'ajoute ici, jamais dans la conversation enregistrée
        dernier_user = max((i for i, m in enumerate(historique) if m.get("role") == "user"), default=-1)
        if consigne and dernier_user >= 0:
            historique = list(historique)
            historique[dernier_user] = dict(historique[dernier_user], content=(historique[dernier_user].get("content") or "") + "\n\n[" + consigne + "]")
        if fiche and dernier_user >= 0:          # la fiche passe juste AVANT la dernière question : tout ce qui précède est identique d'une réponse à l'autre (cache d'Ollama)
            historique = historique[:dernier_user] + [{"role": "user", "content": fiche}, {"role": "assistant", "content": "Compris, je m'appuie sur cette fiche."}] + historique[dernier_user:]
        msgs += historique
        dernier_tour = idx_tour == tours_max - 1
        if dernier_tour:             # plus d'outils : le modèle doit répondre avec ce qu'il a trouvé
            msgs.append({"role": "user", "content": "Tu as assez d'informations. Réponds maintenant à ma demande avec ce que tu as vu, sans appeler d'outil. Si quelque chose manque, dis-le."})
        msgs_base = msgs
        options = _m.options_modele(r, r["temperature"])
        if r.get("num_predict", 0) > 0:
            options["num_predict"] = r["num_predict"]
        caps = capacites(r["modele"])
        reflechit = bool(r["reflexion"])
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
                    caps = capacites(autre)
                else:
                    emit({"type": "info", "texte": _t("Ce modèle ne voit pas les images et aucun modèle « Images » n'est installé : elles sont ignorées. Onglet Modèles pour en installer un.")})
        corps = {"model": r["modele"], "messages": ajuster_contexte(msgs, r["num_ctx"], 1.0, outils), "stream": True, "options": options, "think": reflechit}
        if not dernier_tour and outils:                      # mode « discussion » : aucun outil, donc rien à envoyer ni à signaler
            if caps is not None and "tools" not in caps:
                if idx_tour == 0:
                    emit({"type": "info", "texte": "Ce modèle ne sait pas appeler d'outils : il répondra sans lire ni modifier les fichiers. Choisis un autre modèle (Qwen 3.8 ou Gemma 4) pour cela."})
            else:
                corps["tools"] = outils
        fini, verifie, relance_outil, repli_demande = False, False, False, False
        if ps_modele(r["modele"]) is None:
            emit({"type": "etat", "texte": "Chargement du modèle en mémoire (30 s à 2 min la première fois, ou si ComfyUI lui a pris la carte)."})
        for tentative in range(3):
            contenu, pensee, appels = "", "", []
            corps_t = corps if tentative == 0 else dict(corps, messages=ajuster_contexte(msgs_base, r["num_ctx"], 0.7 ** tentative, outils) + ([{"role": "user", "content": RAPPEL_APPEL}] if relance_outil else []), options=dict(corps["options"], temperature=0.3))
            try:
                corps_t = dict(corps_t, messages=_images.pour_le_modele(corps_t["messages"], caps is None or "vision" in caps))
                req = urllib.request.Request(_m.OLLAMA + "/api/chat", data=json.dumps(avec_garde(corps_t)).encode("utf-8"), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=900) as flux:
                    for brut in flux:
                        if stop.is_set():                    # la sortie du « with » ferme la connexion : Ollama arrête de générer
                            if contenu.strip():
                                conv["messages"].append({"role": "assistant", "content": contenu})
                            raise _m.Arret()
                        try:
                            e = json.loads(brut.decode("utf-8"))
                        except ValueError:
                            continue
                        if e.get("error"):
                            raise RuntimeError(e["error"])
                        m = e.get("message") or {}
                        if e.get("done") and e.get("prompt_eval_count"):          # chiffres réels d'Ollama : jetons lus + écrits = place prise dans la fenêtre de contexte
                            conv["jetons"] = {"utilise": int(e["prompt_eval_count"]) + int(e.get("eval_count") or 0), "total": r["num_ctx"]}
                            emit(dict(conv["jetons"], type="jetons", reel=True))
                        if e.get("done"):
                            vitesse = calculer_vitesse(e)
                            if vitesse:
                                conv["vitesse"] = vitesse
                                emit(dict(vitesse, type="vitesse"))
                        if not verifie:
                            verifie = True
                            ps = ps_modele(r["modele"])
                            if ps and ps["taille"] and ps["vram"] < 0.9 * ps["taille"]:
                                emit({"type": "info", "texte": "Attention : seulement {} % du modèle tient sur la carte graphique, le reste tourne sur le processeur, donc c'est lent. Ferme ComfyUI et le navigateur d'images, ou baisse le contexte dans Réglages.".format(round(100 * ps["vram"] / ps["taille"]))})
                        if m.get("thinking"):
                            pensee += m["thinking"]
                            emit({"type": "pensee", "texte": m["thinking"]})
                        if m.get("content"):
                            contenu += m["content"]
                            emit({"type": "texte", "texte": m["content"]})
                        appels += m.get("tool_calls") or []
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
            appels, contenu_net = extraire_appels_texte(contenu, ctx["outils_autorises"])
            if appels:
                contenu = contenu_net
                emit({"type": "info", "texte": "Le modèle a écrit son appel d'outil en texte au lieu d'utiliser le mécanisme prévu : je l'exécute quand même."})
        message = {"role": "assistant", "content": contenu}
        if appels:
            message["tool_calls"] = appels
        conv["messages"].append(message)
        if not appels:
            break
        for position, a in enumerate(appels):
            if stop.is_set():                        # arrêt demandé : les appels restants reçoivent une réponse, pour garder une conversation cohérente
                for b in appels[position:]:
                    conv["messages"].append({"role": "tool", "tool_name": (b.get("function") or {}).get("name", ""), "content": "Interrompu par l'utilisateur."})
                raise _m.Arret()
            f = a.get("function") or {}
            nom, args = f.get("name", ""), f.get("arguments") or {}
            if isinstance(args, str):
                texte = args.strip()
                try:
                    args = json.loads(texte)
                except ValueError:
                    # certains modèles renvoient « clé=valeur » ou une chaîne nue
                    if "=" in texte and not texte.startswith("{"):
                        args = dict(p.split("=", 1) for p in texte.split("&") if "=" in p)
                    elif nom in ("executer", "memoriser"):
                        args = {"commande": texte} if nom == "executer" else {"note": texte}
                    else:
                        args = {}
            if not isinstance(args, dict):
                args = {}
            emit({"type": "outil", "nom": nom, "args": {k: (v if not isinstance(v, str) or len(v) < 300 else v[:300] + "...") for k, v in args.items()}})
            try:
                if nom not in ctx["outils_autorises"]:
                    raise _m.ErreurOutil("L'outil « {} » n'est pas disponible ici (mode ou option désactivés). Outils disponibles : {}.".format(nom, ", ".join(sorted(ctx["outils_autorises"]))))
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
            emit({"type": "resultat", "nom": nom, "texte": resultat[:1500]})
            conv["messages"].append({"role": "tool", "tool_name": nom, "content": resultat[:_m.LECTURE_MAX + 2000]})
            _m.conv_ecrire(conv)                        # enregistré à chaque étape : un plantage du PC en pleine demande ne perd que l'étape en cours
    else:
        emit({"type": "info", "texte": "Beaucoup d'étapes d'outils dans ce tour : écris « continue » pour que je poursuive."})
