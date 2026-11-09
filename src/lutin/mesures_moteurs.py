"""Ce que chaque moteur donne RÉELLEMENT sur cette machine : une mesure par moteur et par modèle (vitesse d'écriture, délai du premier mot, chargement), gardée et classée.

Le banc existant (bench_moteurs) compare Ollama et llama.cpp avec le même modèle. Ici on mesure N'IMPORTE quel moteur actif (Ollama, llama.cpp, Colibri, LM Studio, tout serveur compatible OpenAI) avec SON modèle,
parce que leurs noms de modèles diffèrent d'un moteur à l'autre. Le classement ne conseille rien d'autre que ce qui a été mesuré ici : pas de règle devinée.
Une mesure charge le modèle et écrit une courte réponse (quelques secondes à quelques minutes selon le modèle) ; elle n'écrit rien dans les conversations."""
import json
import threading
import time
from pathlib import Path

from . import bench_moteurs
from .i18n import t as _t

FICHIER = "mesures_moteurs.json"
MAX = 200
ETAT = {"en_cours": False, "moteur": "", "modele": "", "erreur": "", "debut": 0.0}
VERROU = threading.Lock()
SERVEURS = {"colibri": "Colibri", "lmstudio": "LM Studio", "exllamav3": "ExLlamaV3"}


def nom_affiche(moteur):
    """Le nom que l'utilisateur reconnaît : pour « Serveur compatible OpenAI », le serveur choisi (Colibri, LM Studio) ou son adresse."""
    if getattr(moteur, "id", "") == "openai":
        serveur = str(getattr(moteur, "config", lambda: {})().get("serveur") or "")
        if serveur in SERVEURS:
            return SERVEURS[serveur]
        adresse = str(moteur.adresse() if hasattr(moteur, "adresse") else "")
        return _t("Serveur compatible OpenAI") + (" (" + adresse + ")" if adresse else "")
    return str(getattr(moteur, "nom", getattr(moteur, "id", "?")))


def lire(dossier):
    try:
        d = json.loads((Path(dossier) / FICHIER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [m for m in d if isinstance(m, dict)] if isinstance(d, list) else []


def _ecrire(dossier, mesures):
    p = Path(dossier) / FICHIER
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(mesures[-MAX:], ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def noter(dossier, moteur, modele, mesure, mode="rapide", date=None):
    """Garde une mesure (réussie ou non : une panne mesurée est une information). Renvoie l'entrée gardée."""
    entree = {"date": date or time.strftime("%Y-%m-%d %H:%M"), "moteur": moteur.id, "nom": nom_affiche(moteur), "modele": modele, "mode": mode, "ok": bool(mesure.get("ok")),
              "tok_s": mesure.get("tok_s"), "premier_jeton_s": mesure.get("premier_jeton_s"), "charge_s": mesure.get("charge_s"), "lecture_tok_s": mesure.get("lecture_tok_s"),
              "ram": mesure.get("ram"), "vram": mesure.get("vram"), "version": mesure.get("version", ""), "erreur": ("; ".join(mesure.get("erreurs") or []))[:200]}
    with VERROU:
        mesures = lire(dossier) + [entree]
        _ecrire(dossier, mesures)
    return entree


def classement(mesures):
    """La dernière mesure RÉUSSIE de chaque couple (moteur affiché, modèle), la plus rapide d'abord. [{..., rang, le_plus_rapide}]"""
    derniere = {}
    for m in mesures:
        if m.get("ok") and m.get("tok_s"):
            derniere[(m.get("nom"), m.get("modele"))] = m
    liste = sorted(derniere.values(), key=lambda m: -float(m["tok_s"]))
    for i, m in enumerate(liste, 1):
        m["rang"] = i
    return liste


def candidats(moteurs_, reglages):
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
        sortie.append({"moteur": mo.id, "nom": nom_affiche(mo), "modele": voulu if voulu in installes else installes[0], "modeles": installes[:60]})
    return sortie


def vue(dossier, moteurs_, reglages):
    return {"etat": dict(ETAT), "classement": classement(lire(dossier)), "candidats": candidats(moteurs_, reglages) if not ETAT["en_cours"] else [], "nombre": len(lire(dossier))}


def lancer(dossier, moteur, modele, mode="rapide", ctx=4096, memoire=None, synchrone=False, horloge=time.monotonic):
    """Mesure `moteur` avec `modele` dans un fil. ValueError si une mesure est déjà en cours, si le moteur est arrêté ou si le modèle n'est pas installé chez lui."""
    if mode not in bench_moteurs.PASSES:
        mode = "rapide"
    if not moteur.statut().get("actif"):
        raise ValueError(_t("Ce moteur ne répond pas : démarre-le d'abord (Réglages > Moteur)."))
    if modele not in (moteur.modeles().get("installes") or []):
        raise ValueError(_t("Ce modèle n'est pas installé sur ce moteur : {}").format(str(modele)[:60]))
    with VERROU:
        if ETAT["en_cours"]:
            raise ValueError(_t("Une mesure est déjà en cours : attends sa fin."))
        ETAT.update(en_cours=True, moteur=nom_affiche(moteur), modele=modele, erreur="", debut=time.time())

    def travail():
        try:
            mesure = bench_moteurs.mesurer(moteur, modele, mode, ctx, horloge, memoire)
            noter(dossier, moteur, modele, mesure, mode)
            ETAT["erreur"] = "" if mesure.get("ok") else ("; ".join(mesure.get("erreurs") or []) or _t("La mesure n'a pas abouti."))[:200]
        except Exception as e:  # noqa: BLE001  (jamais une trace dans la page)
            ETAT["erreur"] = str(e)[:200]
        finally:
            ETAT["en_cours"] = False
    if synchrone:
        travail()
    else:
        threading.Thread(target=travail, daemon=True, name="mesure-moteur").start()
    return dict(ETAT)
