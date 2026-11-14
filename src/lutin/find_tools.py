"""Deux petits outils de lecture que les assistants de référence ont tous : retrouver des fichiers par leur NOM (comme un « glob »), et calculer sans se tromper.

Un petit modèle se trompe sur l'arithmétique et ne sait pas lister « tous les test_*.py » avec `lister` (un seul dossier à la fois) : ici c'est exact et immédiat. Aucun accord n'est demandé (rien n'est modifié)
et aucun code n'est exécuté : le calcul passe par un analyseur d'expressions qui n'accepte que des nombres, des opérateurs et quelques fonctions mathématiques."""
import ast
import fnmatch
import math
import operator
import os
import re

from . import core as _m
from .i18n import t as _t

MAX_TROUVES = 200

# ------------------------------------------------------------------------------- trouver


def outil_trouver(motif, dossier="."):
    """Les fichiers dont le NOM correspond au motif (« *.py », « test_*.py », « docs/*.md »), dans le dossier et dessous, triés du plus récent au plus ancien."""
    from .tools import chemin_sur, rel
    motif = str(motif or "").strip().replace("\\", "/")
    if not motif:
        raise _m.ErreurOutil(_t("Motif vide : donne un nom ou un motif comme « *.py » ou « test_*.json »."))
    racine = chemin_sur(dossier)
    if not racine.is_dir():
        raise _m.ErreurOutil(_t("Ce n'est pas un dossier : ") + str(dossier))
    motifs = [m.strip() for m in motif.replace(",", " ").split() if m.strip()]
    if not any(c in motif for c in "*?["):
        motifs = ["*{}*".format(m) for m in motifs]          # « univers » trouve univers.md et mon_univers.txt : un mot sans joker est un morceau de nom
    trouves, coupe = [], False
    for courant, sous, fichiers in os.walk(str(racine)):
        sous[:] = sorted(d for d in sous if d not in _m.DOSSIERS_IGNORES and not _m.ignore_chemin(os.path.join(courant, d)))
        for nom in fichiers:
            chemin = os.path.join(courant, nom)
            relatif = os.path.relpath(chemin, str(_m.RACINE)).replace("\\", "/")
            if any(fnmatch.fnmatch(nom.lower(), m.lower()) or fnmatch.fnmatch(relatif.lower(), m.lower()) for m in motifs):
                try:
                    st = os.stat(chemin)
                except OSError:
                    continue
                trouves.append((st.st_mtime, relatif, st.st_size))
        if len(trouves) >= MAX_TROUVES * 5:          # on arrête de parcourir : trop de fichiers, le motif est trop large
            coupe = True
            break
    if not trouves:
        return _t("Aucun fichier ne correspond à « {} » dans {}. Essaie un motif plus large (par exemple « *.md ») ou un autre dossier.").format(motif, rel(racine))
    trouves.sort(reverse=True)
    lignes = ["{}  ({} octets)".format(r, t) for _, r, t in trouves[:MAX_TROUVES]]
    if len(trouves) > MAX_TROUVES or coupe:
        lignes.append(_t("... (liste coupée : {} fichiers ou plus, précise le motif ou le dossier)").format(MAX_TROUVES))
    return "\n".join(lignes)


# ------------------------------------------------------------------------------- calculer
OPERATEURS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
UNAIRES = {ast.UAdd: operator.pos, ast.USub: operator.neg}
FONCTIONS = {"sqrt": math.sqrt, "abs": abs, "round": round, "min": min, "max": max, "floor": math.floor, "ceil": math.ceil, "log": math.log, "log10": math.log10, "log2": math.log2, "exp": math.exp,
             "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan, "radians": math.radians, "degrees": math.degrees, "factorial": math.factorial,
             "gcd": math.gcd, "sum": lambda *a: sum(a), "pow": pow}
CONSTANTES = {"pi": math.pi, "e": math.e, "tau": math.tau}
LIMITE_PUISSANCE = 10_000
LIMITE_CHIFFRES = 400
LIMITE_PROFONDEUR = 40


def _eval(noeud, profondeur=0):
    if profondeur > LIMITE_PROFONDEUR:
        raise ValueError(_t("expression trop imbriquée"))
    p = profondeur + 1
    if isinstance(noeud, ast.Expression):
        return _eval(noeud.body, p)
    if isinstance(noeud, ast.Constant) and isinstance(noeud.value, (int, float)) and not isinstance(noeud.value, bool):
        return noeud.value
    if isinstance(noeud, ast.Name) and noeud.id in CONSTANTES:
        return CONSTANTES[noeud.id]
    if isinstance(noeud, ast.BinOp) and type(noeud.op) in OPERATEURS:
        a, b = _eval(noeud.left, p), _eval(noeud.right, p)
        if isinstance(noeud.op, ast.Pow) and (abs(b) > LIMITE_PUISSANCE or (isinstance(a, int) and isinstance(b, int) and b > 0 and abs(a) > 1 and b * math.log10(abs(a)) > LIMITE_CHIFFRES)):
            raise ValueError(_t("puissance trop grande"))
        return OPERATEURS[type(noeud.op)](a, b)
    if isinstance(noeud, ast.UnaryOp) and type(noeud.op) in UNAIRES:
        return UNAIRES[type(noeud.op)](_eval(noeud.operand, p))
    if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name) and noeud.func.id in FONCTIONS and not noeud.keywords and len(noeud.args) <= 8:
        args = [_eval(a, p) for a in noeud.args]
        if noeud.func.id == "factorial" and (len(args) != 1 or not isinstance(args[0], int) or args[0] > 500):
            raise ValueError(_t("factorielle trop grande"))
        return FONCTIONS[noeud.func.id](*args)
    raise ValueError(_t("élément non autorisé (seuls les nombres, + - * / // % **, les parenthèses et les fonctions mathématiques courantes sont permis)"))


def _formate(valeur):
    if isinstance(valeur, float):
        if valeur != valeur or valeur in (math.inf, -math.inf):
            return str(valeur)
        if valeur == int(valeur) and abs(valeur) < 1e15:
            return str(int(valeur))
        return "{:.12g}".format(valeur)
    texte = str(valeur)
    return texte if len(texte) <= 60 else "{} ({} chiffres)".format(texte[:20] + "…" + texte[-10:], len(texte.lstrip("-")))


def outil_calculer(expression):
    """Le résultat exact d'une expression arithmétique (« 17 * 23 + 4 », « sqrt(2) * 10 », « 15% de 80 » s'écrit « 80 * 0.15 »)."""
    texte = str(expression or "").strip().replace("×", "*").replace("÷", "/").replace("^", "**")
    if not re.search(r"[A-Za-z]", texte):
        texte = re.sub(r"(?<=\d),(?=\d)", ".", texte)          # « 3,5 * 2 » : virgule décimale française (pas quand il y a un appel comme max(1,2))
    if not texte or len(texte) > 300:
        raise _m.ErreurOutil(_t("Expression vide ou trop longue (300 caractères au plus)."))
    try:
        resultat = _eval(ast.parse(texte, mode="eval"))
    except ZeroDivisionError:
        raise _m.ErreurOutil(_t("Division par zéro."))
    except (ValueError, SyntaxError, TypeError, OverflowError) as erreur:
        raise _m.ErreurOutil(_t("Calcul impossible : {}.").format(str(erreur)[:150] or _t("expression invalide")))
    return "{} = {}".format(texte, _formate(resultat))
