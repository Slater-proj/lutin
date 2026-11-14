"""Règles de tri des messages reçus (courriel, X…) : « si le message est comme ça, fais ça ».

Une règle par ligne, la première qui correspond gagne :

    de:*@banque.fr -> ignorer
    sujet:*facture* -> brouillon: Réponds que je regarde et que je reviens sous 48 h.
    ton:agressif -> ignorer
    texte:*rendez-vous* -> brouillon: Propose de me rappeler cette semaine.
    * -> brouillon

- critères : `de:motif`, `sujet:motif`, `texte:motif` (jokers * et ?, majuscules ignorées), `ton:agressif|passif|neutre|amical` (le ton est jugé par le modèle, seulement si une règle le demande),
  `*` (tout) ; plusieurs critères sur une ligne se combinent par « et » avec « + » : `de:*@mairie.fr + sujet:*urgent* -> brouillon` ;
- actions : `ignorer` (rien), `brouillon` (le modèle prépare une réponse que l'utilisateur valide), `auto` (le modèle répond seul) ; après « : », la consigne donnée au modèle pour cette règle ;
- sans règle qui correspond, le message est ignoré : rien n'est jamais fait par défaut.

Le texte du message n'est jamais exécuté ni interprété : il ne sert qu'à être comparé aux motifs et à être répondu."""
import re

from .i18n import t as _t

ACTIONS = ("ignorer", "brouillon", "auto")
TONES = ("agressif", "passif", "neutre", "amical")
CRITERIA = ("de", "sujet", "texte", "ton")
RE_LINE = re.compile(r"^(?P<criteres>.+?)\s*->\s*(?P<action>[a-zé]+)\s*(?::\s*(?P<consigne>.*))?$")


class RuleError(ValueError):
    pass


def parse(texte):
    """Transforme le texte des règles en liste de {criteres: [(nom, motif)], action, consigne, ligne}. Lève ErreurRegle (avec le numéro de ligne) si une ligne est mal écrite."""
    regles = []
    for numero, brut in enumerate(str(texte or "").splitlines(), 1):
        ligne = brut.strip()
        if not ligne or ligne.startswith("#"):
            continue
        m = RE_LINE.match(ligne)
        if not m:
            raise RuleError(_t("ligne {} : « {} » (attendu : critère -> action)").format(numero, ligne[:60]))
        action = m.group("action")
        if action not in ACTIONS:
            raise RuleError(_t("ligne {} : action « {} » inconnue (ignorer, brouillon ou auto)").format(numero, action))
        criteres = []
        for morceau in m.group("criteres").split("+"):
            morceau = morceau.strip()
            if morceau == "*":
                continue
            nom, _, motif = morceau.partition(":")
            nom, motif = nom.strip().lower(), motif.strip()
            if nom not in CRITERIA or not motif:
                raise RuleError(_t("ligne {} : critère « {} » inconnu (de, sujet, texte, ton ou *)").format(numero, morceau[:40]))
            if nom == "ton" and motif.lower() not in TONES:
                raise RuleError(_t("ligne {} : ton « {} » inconnu ({})").format(numero, motif, ", ".join(TONES)))
            criteres.append((nom, motif.lower()))
        regles.append({"criteres": criteres, "action": action, "consigne": (m.group("consigne") or "").strip(), "ligne": numero})
    return regles


def pattern_to_regex(motif):
    """Un motif avec jokers (* = n'importe quoi, ? = un caractère) cherché n'importe où dans le champ : « *@banque.fr » reconnaît « Banque <contact@banque.fr> »."""
    return "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in motif)


def needs_tone(regles):
    return any(nom == "ton" for r in regles for nom, _ in r["criteres"])


def choose(regles, message, juger_ton=None):
    """La première règle qui correspond au message {de, sujet, texte}, ou None. judge_tone(texte) -> un des TONS, appelé une seule fois et seulement si une règle le demande."""
    ton = []

    def le_ton():
        if not ton:
            try:
                ton.append(juger_ton(message.get("texte", "")) if juger_ton else "neutre")
            except Exception:  # noqa: BLE001  (un jugement raté ne doit pas bloquer le tri : le ton reste « neutre »)
                ton.append("neutre")
        return ton[0]

    for r in regles:
        ok = True
        for nom, motif in r["criteres"]:
            if nom == "ton":
                ok = le_ton() == motif
            else:
                ok = bool(re.search(pattern_to_regex(motif), str(message.get(nom, "")).lower()))
            if not ok:
                break
        if ok:
            return r
    return None
