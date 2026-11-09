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

SEUIL_APPEL = 3                    # à partir du troisième appel identique AVEC LE MÊME RÉSULTAT, il n'est plus exécuté
SEUIL_ABANDON = 5                  # au cinquième, le tour s'arrête
SEUIL_SIMILITUDE = 0.8             # part de mots communs au-delà de laquelle deux réponses sont « la même »
LONGUEUR_MIN = 60                  # une réponse plus courte (« Oui. ») ne compte pas
SANS_REPETITION = {"taches", "suivi", "memoriser"}          # ces outils se rappellent légitimement avec les mêmes arguments


FENETRE_REPETITION = 160           # caractères de la fin du texte qu'on cherche plus haut
REPETITIONS_MAX = 4                # la même fin déjà écrite autant de fois avant : le texte tourne en rond
LONGUEUR_REPETITION = 2500         # en dessous, on ne juge pas (une phrase répétée au début d'une réflexion n'est pas une boucle)
VERIFICATIONS_DE_SUITE = 2         # le texte doit TOURNER EN ROND à deux contrôles de suite (400 caractères d'écart) avant qu'on l'arrête : une répétition passagère dans une analyse n'est pas coupée


def texte_repete(texte):
    """Vrai si la fin du texte (réflexion ou réponse) a déjà été écrite plusieurs fois mot pour mot plus haut : le modèle est coincé dans une boucle de génération.
    Ce n'est pas un défaut de Lutin : les petits modèles, surtout en réflexion, peuvent se mettre à répéter la même phrase ; il faut les arrêter, ils ne s'en sortent pas seuls."""
    t = re.sub(r"\s+", " ", texte or "").strip()
    if len(t) < LONGUEUR_REPETITION:
        return False
    fin = t[-FENETRE_REPETITION:]
    return t[:-FENETRE_REPETITION].count(fin) >= REPETITIONS_MAX


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
    """Compte, dans un tour, les appels d'outils identiques dont le résultat est AUSSI identique : relire un fichier après l'avoir modifié, relancer des tests après une correction, n'est pas tourner en rond
    (le résultat change). Seul un appel qui redonne exactement le même résultat n'apprend plus rien au modèle."""

    def __init__(self):
        self.vus = {}              # empreinte de l'appel -> nombre d'appels qui ont redonné le résultat précédent (+ 1)
        self.dernier = {}          # empreinte de l'appel -> empreinte du dernier résultat
        self.abandon = False

    def compter(self, nom, args):
        """Renvoie le nombre d'appels identiques (même résultat) déjà faits dans ce tour, celui-ci compris."""
        if nom in SANS_REPETITION:
            return 1
        return self.vus.get(empreinte(nom, args), 0) + 1

    def refuser(self, nom, args):
        """Un appel identique refusé (au-delà du seuil) compte quand même : au cinquième, le tour s'arrête."""
        cle = empreinte(nom, args)
        self.vus[cle] = self.vus.get(cle, 0) + 1
        if self.vus[cle] >= SEUIL_ABANDON:
            self.abandon = True

    def noter_resultat(self, nom, args, resultat):
        """À appeler après l'exécution : un résultat identique au précédent compte comme une répétition, un résultat différent remet le compte à un."""
        if nom in SANS_REPETITION:
            return
        cle = empreinte(nom, args)
        signature = hash(str(resultat))
        self.vus[cle] = self.vus.get(cle, 0) + 1 if self.dernier.get(cle) == signature else 1
        self.dernier[cle] = signature
        if self.vus[cle] >= SEUIL_ABANDON:
            self.abandon = True

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
