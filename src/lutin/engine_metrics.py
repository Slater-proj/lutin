"""Ce que chaque moteur donne RÉELLEMENT sur cette machine : une mesure par moteur et par modèle (vitesse d'écriture, délai du premier mot, chargement), gardée et classée.

Le banc existant (bench_moteurs) compare Ollama et llama.cpp avec le même modèle. Ici on mesure N'IMPORTE quel moteur actif (Ollama, llama.cpp, Colibri, LM Studio, tout serveur compatible OpenAI) avec SON modèle,
parce que leurs noms de modèles diffèrent d'un moteur à l'autre. Le classement ne conseille rien d'autre que ce qui a été mesuré ici : pas de règle devinée.
Une mesure charge le modèle et écrit une courte réponse (quelques secondes à quelques minutes selon le modèle) ; elle n'écrit rien dans les conversations."""
import json
import threading
import time
from pathlib import Path

from . import engine_bench
from .i18n import t as _t

FILE = "mesures_moteurs.json"
MAX = 200
STATE = {"en_cours": False, "moteur": "", "modele": "", "erreur": "", "debut": 0.0}
LOCK = threading.Lock()
SERVERS = {"colibri": "Colibri", "lmstudio": "LM Studio", "exllamav3": "ExLlamaV3"}


def display_name(moteur):
    """Le nom que l'utilisateur reconnaît : pour « Serveur compatible OpenAI », le serveur choisi (Colibri, LM Studio) ou son adresse."""
    if getattr(moteur, "id", "") == "openai":
        serveur = str(getattr(moteur, "config", lambda: {})().get("serveur") or "")
        if serveur in SERVERS:
            return SERVERS[serveur]
        adresse = str(moteur.adresse() if hasattr(moteur, "adresse") else "")
        return _t("Serveur compatible OpenAI") + (" (" + adresse + ")" if adresse else "")
    return str(getattr(moteur, "nom", getattr(moteur, "id", "?")))


def load(dossier):
    try:
        d = json.loads((Path(dossier) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [m for m in d if isinstance(m, dict)] if isinstance(d, list) else []


def _write(dossier, mesures):
    p = Path(dossier) / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(mesures[-MAX:], ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def record(dossier, moteur, modele, mesure, mode="rapide", date=None):
    """Garde une mesure (réussie ou non : une panne mesurée est une information). Renvoie l'entrée gardée."""
    entree = {"date": date or time.strftime("%Y-%m-%d %H:%M"), "moteur": moteur.id, "nom": display_name(moteur), "modele": modele, "mode": mode, "ok": bool(mesure.get("ok")),
              "tok_s": mesure.get("tok_s"), "premier_jeton_s": mesure.get("premier_jeton_s"), "charge_s": mesure.get("charge_s"), "lecture_tok_s": mesure.get("lecture_tok_s"),
              "ram": mesure.get("ram"), "vram": mesure.get("vram"), "version": mesure.get("version", ""), "erreur": ("; ".join(mesure.get("erreurs") or []))[:200]}
    with LOCK:
        mesures = load(dossier) + [entree]
        _write(dossier, mesures)
    return entree


def ranking(mesures):
    """La dernière mesure RÉUSSIE de chaque couple (moteur affiché, modèle), la plus rapide d'abord. [{..., rang, le_plus_rapide}]"""
    derniere = {}
    for m in mesures:
        if m.get("ok") and m.get("tok_s"):
            derniere[(m.get("nom"), m.get("modele"))] = m
    liste = sorted(derniere.values(), key=lambda m: -float(m["tok_s"]))
    for i, m in enumerate(liste, 1):
        m["rang"] = i
    return liste


def candidates(moteurs_, reglages):
    """Les moteurs ACTIFS sur lesquels on peut mesurer, avec le modèle qui serait utilisé : [{moteur, nom, modele}]. Un moteur arrêté n'est pas démarré à la place de l'utilisateur."""
    sortie = []
    for mo in moteurs_.values():
        try:
            if not mo.statut().get("actif"):
                continue
            installes = list(mo.modeles().get("installes") or [])
        except Exception:  # noqa: BLE001  (un moteur qui ne répond pas n'est simplement pas proposé)
            continue
        if not installes:
            continue
        voulu = str(reglages.get("modele") or "")
        sortie.append({"moteur": mo.id, "nom": display_name(mo), "modele": voulu if voulu in installes else installes[0], "modeles": installes[:60]})
    return sortie


def view(dossier, moteurs_, reglages):
    return {"etat": dict(STATE), "classement": ranking(load(dossier)), "candidats": candidates(moteurs_, reglages) if not STATE["en_cours"] else [], "nombre": len(load(dossier))}


def launch(dossier, moteur, modele, mode="rapide", ctx=4096, memoire=None, synchrone=False, horloge=time.monotonic):
    """Mesure `moteur` avec `modele` dans un fil. ValueError si une mesure est déjà en cours, si le moteur est arrêté ou si le modèle n'est pas installé chez lui."""
    if mode not in engine_bench.PASSES:
        mode = "rapide"
    if not moteur.statut().get("actif"):
        raise ValueError(_t("Ce moteur ne répond pas : démarre-le d'abord (Réglages > Moteur)."))
    if modele not in (moteur.modeles().get("installes") or []):
        raise ValueError(_t("Ce modèle n'est pas installé sur ce moteur : {}").format(str(modele)[:60]))
    with LOCK:
        if STATE["en_cours"]:
            raise ValueError(_t("Une mesure est déjà en cours : attends sa fin."))
        STATE.update(en_cours=True, moteur=display_name(moteur), modele=modele, erreur="", debut=time.time())

    def travail():
        try:
            mesure = engine_bench.mesurer(moteur, modele, mode, ctx, horloge, memoire)
            record(dossier, moteur, modele, mesure, mode)
            STATE["erreur"] = "" if mesure.get("ok") else ("; ".join(mesure.get("erreurs") or []) or _t("La mesure n'a pas abouti."))[:200]
        except Exception as e:  # noqa: BLE001  (jamais une trace dans la page)
            STATE["erreur"] = str(e)[:200]
        finally:
            STATE["en_cours"] = False
    if synchrone:
        travail()
    else:
        threading.Thread(target=travail, daemon=True, name="mesure-moteur").start()
    return dict(STATE)
