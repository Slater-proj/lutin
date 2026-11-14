"""« Optimiser pour cette machine » : mesurer, sur CETTE machine, combien de cœurs de processeur donnent la génération la plus rapide, puis proposer ce réglage.

Pourquoi mesurer : sur processeur, la vitesse d'écriture dépend surtout de la mémoire, pas du nombre de cœurs. Au-delà d'un certain nombre, les cœurs supplémentaires se gênent entre eux (et gênent le reste de la machine)
sans écrire plus vite ; le bon chiffre dépend du processeur (cœurs rapides et cœurs économes, hyperthreading), de la mémoire et de ce qui tourne à côté. Aucune règle valable partout : on essaie et on garde le meilleur.

Ce qui est mesuré : le débit d'écriture (jetons/s) du modèle choisi, avec chaque nombre de cœurs, deux fois. Ce qui est proposé : le plus PETIT nombre de cœurs dont le débit est à moins de 3 % du meilleur
(à vitesse égale, on laisse des cœurs au reste de la machine). Rien n'est appliqué sans ton clic."""
import json
import os
import statistics
import threading
import time

from . import bench
from . import core as _m
from .i18n import t as _t
from .ollama_client import Ollama

TOLERANCE = 0.03             # un nombre de cœurs plus petit est préféré s'il écrit à moins de 3 % du meilleur
REPETITIONS = 2
CALIBRAGE = {"en_cours": False, "etape": "", "erreur": "", "annule": False, "resultats": [], "recommande": None, "modele": "", "date": ""}


def candidats(limite=0, cpus=None):
    """Les nombres de cœurs à essayer : le tiers, la moitié, les deux tiers et la totalité de ce que le processus peut utiliser (au moins 2)."""
    base = int(limite or cpus or os.cpu_count() or 4)
    return sorted({max(2, min(base, round(base * f))) for f in (1 / 3, 1 / 2, 2 / 3, 1)})


def choisir(resultats, tolerance=TOLERANCE):
    """Le plus petit nombre de cœurs dont le débit est à moins de `tolerance` du meilleur. None s'il n'y a aucune mesure."""
    mesures = [r for r in resultats if r.get("tok_s")]
    if not mesures:
        return None
    meilleur = max(r["tok_s"] for r in mesures)
    return min(r["fils"] for r in mesures if r["tok_s"] >= meilleur * (1 - tolerance))


def chemin():
    return _m.DONNEES / "calibrage.json"


def etat():
    """Ce que la page affiche : l'avancement, ou le dernier résultat garde sur le disque."""
    if not CALIBRAGE["resultats"] and not CALIBRAGE["en_cours"] and not CALIBRAGE["erreur"]:
        garde = _m.lire_json(chemin(), {})
        if isinstance(garde, dict) and garde.get("resultats"):
            return dict(garde, en_cours=False, etape="", erreur="")
    return {k: CALIBRAGE[k] for k in ("en_cours", "etape", "erreur", "resultats", "recommande", "modele", "date")}


def mesurer_fils(ollama, modele, fils, num_ctx, repetitions=REPETITIONS):
    """Débit d'écriture moyen (jetons/s) du modèle avec `fils` cœurs, ou None si Ollama n'a rien pu mesurer."""
    banc = bench.Banc(ollama, modele, num_ctx, 300, options={"num_thread": fils})
    valeurs = []
    for _ in range(repetitions):
        v = banc.vitesse().get("tok_s")
        if v:
            valeurs.append(v)
    return round(statistics.mean(valeurs), 1) if valeurs else None


def lancer(mesure=None):
    """Démarre le calibrage en arrière-plan sur le modèle choisi dans Réglages. Un seul à la fois, et pas pendant une réponse ou un banc d'essai (les mesures se fausseraient)."""
    mesure = mesure or mesurer_fils
    r = _m.reglages()
    modele = r["modele"]
    with _m.VERROU_TOURS:
        if _m.TOURS_ACTIFS:
            raise ValueError(_t("Une réponse est en cours : la mesure serait faussée. Attends sa fin."))
        if _m.BENCH["en_cours"] or CALIBRAGE["en_cours"]:
            raise ValueError(_t("Une mesure est déjà en cours."))
        if modele not in _m.etat_ollama()["installes"]:
            raise ValueError(_t("Le modèle « {} » n'est pas installé : installe-le ou choisis-en un autre en haut à gauche.").format(modele))
        from .hardware import cpus_disponibles
        liste = candidats(cpus_disponibles())
        if len(liste) < 2:
            raise ValueError(_t("Cette machine n'a que {} cœurs : il n'y a rien à comparer.").format(cpus_disponibles()))
        CALIBRAGE.update(en_cours=True, etape=_t("démarrage"), erreur="", annule=False, resultats=[], recommande=None, modele=modele, date="")
        _m.BENCH.update(en_cours="calibrage", etape=_t("calibrage"))                  # bloque les bancs d'essai pendant ce temps

    def travail():
        ollama = Ollama(_m.OLLAMA)
        try:
            for i, fils in enumerate(liste):
                if CALIBRAGE["annule"]:
                    break
                CALIBRAGE["etape"] = _t("{} cœurs ({}/{})").format(fils, i + 1, len(liste))
                try:
                    tok_s = mesure(ollama, modele, fils, r["num_ctx"])
                except Exception as erreur:  # noqa: BLE001  (une panne d'Ollama arrête la mesure, jamais l'application)
                    CALIBRAGE["erreur"] = str(erreur)[:200]
                    break
                CALIBRAGE["resultats"].append({"fils": fils, "tok_s": tok_s})
            CALIBRAGE["recommande"] = choisir(CALIBRAGE["resultats"])
            CALIBRAGE["date"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if CALIBRAGE["resultats"] and not CALIBRAGE["annule"]:
                try:
                    chemin().write_text(json.dumps({k: CALIBRAGE[k] for k in ("resultats", "recommande", "modele", "date")}, ensure_ascii=False), encoding="utf-8")
                except OSError:
                    pass
        finally:
            CALIBRAGE.update(en_cours=False, etape="")
            _m.BENCH.update(en_cours="", etape="")
    threading.Thread(target=travail, daemon=True, name="calibrage").start()
    return {"ok": True, "essais": liste}


def annuler():
    CALIBRAGE["annule"] = True
    return {"ok": True}


def appliquer():
    """Enregistre le nombre de cœurs recommandé dans les réglages."""
    e = etat()
    if not e.get("recommande"):
        raise ValueError(_t("Aucun résultat à appliquer : lance d'abord la mesure."))
    _m.enregistrer_reglages({"num_thread": int(e["recommande"])})
    return {"ok": True, "num_thread": int(e["recommande"])}
