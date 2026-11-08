"""L'observatoire : ce que Lutin et ses modèles ont fait, pour comprendre et déboguer.

Chaque tour de modèle (quel modèle, sur quelle machine, combien de jetons, à quelle vitesse), chaque appel d'outil (lequel, combien de temps, réussi ou non), chaque relance ou changement de modèle
est noté dans `observatoire.jsonl`. Jamais le texte des messages ni les arguments des outils : seulement des noms, des durées et des compteurs. Le fichier garde 2000 évènements au plus ;
la page Santé en montre un résumé par modèle et les derniers évènements. Écrire dans l'observatoire ne lève jamais d'erreur : il ne doit rien ralentir ni rien casser."""
import json
import threading
import time

from . import donnees as _donnees

MAX_EVENEMENTS = 2000
TYPES = ("tour", "outil", "relance", "routage", "erreur")
VERROU = threading.Lock()


def _chemin():
    from . import moteur as _m
    return _m.DONNEES / "observatoire.jsonl"


def noter(genre, conversation="", **champs):
    """Un évènement de plus. `champs` : valeurs simples seulement (texte court, nombre, booléen)."""
    if genre not in TYPES:
        return
    try:
        propres = {}
        for cle, valeur in champs.items():
            if isinstance(valeur, bool) or valeur is None or isinstance(valeur, (int, float)):
                propres[cle] = valeur
            else:
                propres[cle] = str(valeur)[:160]
        ligne = json.dumps(dict(propres, quand=time.strftime("%Y-%m-%d %H:%M:%S"), type=genre, conv=str(conversation)[:16]), ensure_ascii=False)
        with VERROU:
            chemin = _chemin()
            chemin.parent.mkdir(parents=True, exist_ok=True)
            with open(chemin, "a", encoding="utf-8") as f:
                f.write(ligne + "\n")
            if chemin.stat().st_size > MAX_EVENEMENTS * 400:          # rogner de temps en temps, sans relire le fichier à chaque évènement
                lignes = chemin.read_text(encoding="utf-8", errors="replace").splitlines()[-MAX_EVENEMENTS:]
                _donnees.ecrire_atomique(chemin, "\n".join(lignes) + "\n")
    except (OSError, ValueError, TypeError):
        pass


def lire(n=400):
    """Les derniers évènements, du plus récent au plus ancien."""
    try:
        lignes = _chemin().read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(int(n), MAX_EVENEMENTS)):]
    except OSError:
        return []
    sortie = []
    for ligne in reversed(lignes):
        try:
            x = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(x, dict) and x.get("type") in TYPES:
            sortie.append(x)
    return sortie


def resume(evenements=None):
    """Par modèle : nombre de tours, vitesse moyenne d'écriture (pondérée par les jetons), jetons écrits ; et globalement les outils (appels, échecs, durée moyenne) et les relances.
    {modeles: [{modele, machine, tours, jetons, tok_s}], outils: [{outil, appels, echecs, duree_ms}], relances: {motif: nombre}, routages: nombre}."""
    evenements = lire() if evenements is None else evenements
    modeles, outils, relances, routages = {}, {}, {}, 0
    for e in evenements:
        if e["type"] == "tour":
            cle = (str(e.get("modele", "?")), str(e.get("machine", "")))
            m = modeles.setdefault(cle, {"modele": cle[0], "machine": cle[1], "tours": 0, "jetons": 0, "_secondes": 0.0})
            m["tours"] += 1
            jetons, vitesse = int(e.get("jetons") or 0), float(e.get("tok_s") or 0)
            m["jetons"] += jetons
            if vitesse > 0 and jetons > 0:
                m["_secondes"] += jetons / vitesse
        elif e["type"] == "outil":
            o = outils.setdefault(str(e.get("outil", "?")), {"outil": str(e.get("outil", "?")), "appels": 0, "echecs": 0, "_ms": 0})
            o["appels"] += 1
            o["echecs"] += 0 if e.get("ok", True) else 1
            o["_ms"] += int(e.get("duree_ms") or 0)
        elif e["type"] == "relance":
            motif = str(e.get("motif", "?"))
            relances[motif] = relances.get(motif, 0) + 1
        elif e["type"] == "routage":
            routages += 1
    sortie_modeles = []
    for m in modeles.values():
        secondes = m.pop("_secondes")
        m["tok_s"] = round(m["jetons"] / secondes, 1) if secondes > 0 else None
        sortie_modeles.append(m)
    sortie_outils = []
    for o in outils.values():
        ms = o.pop("_ms")
        o["duree_ms"] = round(ms / o["appels"]) if o["appels"] else 0
        sortie_outils.append(o)
    return {"modeles": sorted(sortie_modeles, key=lambda m: -m["tours"]), "outils": sorted(sortie_outils, key=lambda o: -o["appels"]), "relances": relances, "routages": routages}


def vider():
    try:
        _chemin().unlink(missing_ok=True)
    except OSError:
        pass
