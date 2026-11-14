"""Détecter quand le modèle tourne en rond, et l'en sortir.

Deux boucles très courantes avec un petit modèle local :
- dans un même tour, il refait le MÊME appel d'outil (même outil, mêmes arguments) en espérant un autre résultat : au troisième appel identique il ne reçoit plus le résultat mais l'ordre de passer à autre
  chose, et au cinquième le tour s'arrête ;
- d'un tour à l'autre, il répète presque mot pour mot sa réponse précédente (le même plan, la même demande de confirmation) : Lutin le remarque, le dit, et à la demande suivante ordonne d'EXÉCUTER l'étape
  en cours au lieu de replanifier."""
import json
import re

from . import recall
from .i18n import t as _t

CALL_THRESHOLD = 3                    # à partir du troisième appel identique AVEC LE MÊME RÉSULTAT, il n'est plus exécuté
GIVE_UP_THRESHOLD = 5                  # au cinquième, le tour s'arrête
SIMILARITY_THRESHOLD = 0.8             # part de mots communs au-delà de laquelle deux réponses sont « la même »
MIN_LENGTH = 60                  # une réponse plus courte (« Oui. ») ne compte pas
MAY_REPEAT = {"taches", "suivi", "memoriser"}          # ces outils se rappellent légitimement avec les mêmes arguments


REPEAT_WINDOW = 160           # caractères de la fin du texte qu'on cherche plus haut
REPEATS_MAX = 4                # la même fin déjà écrite autant de fois avant : le texte tourne en rond
REPEAT_MIN_LENGTH = 2500         # en dessous, on ne juge pas (une phrase répétée au début d'une réflexion n'est pas une boucle)
CONSECUTIVE_CHECKS = 2         # le texte doit TOURNER EN ROND à deux contrôles de suite (400 caractères d'écart) avant qu'on l'arrête : une répétition passagère dans une analyse n'est pas coupée


def repeated_text(texte):
    """Vrai si la fin du texte (réflexion ou réponse) a déjà été écrite plusieurs fois mot pour mot plus haut : le modèle est coincé dans une boucle de génération.
    Ce n'est pas un défaut de Lutin : les petits modèles, surtout en réflexion, peuvent se mettre à répéter la même phrase ; il faut les arrêter, ils ne s'en sortent pas seuls."""
    t = re.sub(r"\s+", " ", texte or "").strip()
    if len(t) < REPEAT_MIN_LENGTH:
        return False
    fin = t[-REPEAT_WINDOW:]
    return t[:-REPEAT_WINDOW].count(fin) >= REPEATS_MAX


def useful_words(texte):
    return set(m for m in recall.mots(texte) if len(m) > 3)


def similarity(a, b):
    """Part de mots en commun (Jaccard) entre deux textes, de 0 à 1."""
    x, y = useful_words(a), useful_words(b)
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def fingerprint(nom, args):
    try:
        return nom + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return nom + repr(args)


class Guard:
    """Compte, dans un tour, les appels d'outils identiques dont le résultat est AUSSI identique : relire un fichier après l'avoir modifié, relancer des tests après une correction, n'est pas tourner en rond
    (le résultat change). Seul un appel qui redonne exactement le même résultat n'apprend plus rien au modèle."""

    def __init__(self):
        self.vus = {}              # empreinte de l'appel -> nombre d'appels qui ont redonné le résultat précédent (+ 1)
        self.dernier = {}          # empreinte de l'appel -> empreinte du dernier résultat
        self.abandon = False

    def compter(self, nom, args):
        """Renvoie le nombre d'appels identiques (même résultat) déjà faits dans ce tour, celui-ci compris."""
        if nom in MAY_REPEAT:
            return 1
        return self.vus.get(fingerprint(nom, args), 0) + 1

    def refuser(self, nom, args):
        """Un appel identique refusé (au-delà du seuil) compte quand même : au cinquième, le tour s'arrête."""
        cle = fingerprint(nom, args)
        self.vus[cle] = self.vus.get(cle, 0) + 1
        if self.vus[cle] >= GIVE_UP_THRESHOLD:
            self.abandon = True

    def noter_resultat(self, nom, args, resultat):
        """À appeler après l'exécution : un résultat identique au précédent compte comme une répétition, un résultat différent remet le compte à un."""
        if nom in MAY_REPEAT:
            return
        cle = fingerprint(nom, args)
        signature = hash(str(resultat))
        self.vus[cle] = self.vus.get(cle, 0) + 1 if self.dernier.get(cle) == signature else 1
        self.dernier[cle] = signature
        if self.vus[cle] >= GIVE_UP_THRESHOLD:
            self.abandon = True

    @staticmethod
    def message(n):
        return _t("Tu as déjà fait exactement cet appel {} fois dans cette réponse : le résultat ne changera pas. Utilise ce que tu as déjà obtenu, essaie autre chose, ou réponds à l'utilisateur.").format(n - 1)


def repeats_last_answer(conv):
    """La dernière réponse du modèle ressemble-t-elle presque mot pour mot à la précédente ? (la même réponse, pas seulement le même sujet)"""
    reponses = [m["content"] for m in conv.get("messages", []) if m.get("role") == "assistant" and len(re.sub(r"\s+", " ", m.get("content") or "").strip()) >= MIN_LENGTH]
    if len(reponses) < 2:
        return False
    return similarity(reponses[-1], reponses[-2]) >= SIMILARITY_THRESHOLD


INSTRUCTION = ("Tu viens de répéter ta réponse précédente. Ne refais pas le plan et ne redemande pas de confirmation : exécute l'étape en cours avec tes outils, "
            "ou dis précisément ce qui te bloque.")


def instruction():
    return _t(INSTRUCTION)
