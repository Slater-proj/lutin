"""Détecter quand le modèle tourne en rond, et l'en sortir.

Deux boucles très courantes avec un petit modèle local :
- dans un même tour, il refait le MÊME appel d'outil (même outil, mêmes arguments) en espérant un autre résultat : au troisième appel identique il ne reçoit plus le résultat mais l'ordre de passer à autre
  chose, et au cinquième le tour s'arrête ;
- d'un tour à l'autre, il répète presque mot pour mot sa réponse précédente (le même plan, la même demande de confirmation) : Lutin le remarque, le dit, et à la demande suivante ordonne d'EXÉCUTER l'étape
  en cours au lieu de replanifier."""
import json
import re

from . import rappel
from .i18n import t as _t

SEUIL_APPEL = 3                    # à partir du troisième appel identique, il n'est plus exécuté
SEUIL_ABANDON = 5                  # au cinquième, le tour s'arrête
SEUIL_SIMILITUDE = 0.8             # part de mots communs au-delà de laquelle deux réponses sont « la même »
LONGUEUR_MIN = 60                  # une réponse plus courte (« Oui. ») ne compte pas
SANS_REPETITION = {"taches", "suivi", "memoriser"}          # ces outils se rappellent légitimement avec les mêmes arguments


def mots_utiles(texte):
    return set(m for m in rappel.mots(texte) if len(m) > 3)


def similitude(a, b):
    """Part de mots en commun (Jaccard) entre deux textes, de 0 à 1."""
    x, y = mots_utiles(a), mots_utiles(b)
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def empreinte(nom, args):
    try:
        return nom + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return nom + repr(args)


class Garde:
    """Compte, dans un tour, les appels d'outils identiques."""

    def __init__(self):
        self.vus = {}
        self.abandon = False

    def compter(self, nom, args):
        """Renvoie le nombre d'appels identiques déjà faits dans ce tour, celui-ci compris."""
        if nom in SANS_REPETITION:
            return 1
        cle = empreinte(nom, args)
        self.vus[cle] = self.vus.get(cle, 0) + 1
        if self.vus[cle] >= SEUIL_ABANDON:
            self.abandon = True
        return self.vus[cle]

    @staticmethod
    def message(n):
        return _t("Tu as déjà fait exactement cet appel {} fois dans cette réponse : le résultat ne changera pas. Utilise ce que tu as déjà obtenu, essaie autre chose, ou réponds à l'utilisateur.").format(n - 1)


def repete_derniere_reponse(conv):
    """La dernière réponse du modèle ressemble-t-elle presque mot pour mot à la précédente ? (la même réponse, pas seulement le même sujet)"""
    reponses = [m["content"] for m in conv.get("messages", []) if m.get("role") == "assistant" and len(re.sub(r"\s+", " ", m.get("content") or "").strip()) >= LONGUEUR_MIN]
    if len(reponses) < 2:
        return False
    return similitude(reponses[-1], reponses[-2]) >= SEUIL_SIMILITUDE


CONSIGNE = ("Tu viens de répéter ta réponse précédente. Ne refais pas le plan et ne redemande pas de confirmation : exécute l'étape en cours avec tes outils, "
            "ou dis précisément ce qui te bloque.")


def consigne():
    return _t(CONSIGNE)
