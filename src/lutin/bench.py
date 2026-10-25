"""Banc d'essai : mesure CE qu'un modèle fait sur CETTE machine (vitesse, appel d'outils, code, français, consignes).

Onze questions courtes à réponse vérifiable automatiquement, une seule fois chacune, température 0 : c'est un **indicateur**, pas un classement scientifique.
Aucun code écrit par le modèle n'est exécuté : les questions de code demandent le résultat d'un petit programme, vérifié par comparaison.
Tout reste local (Ollama sur cette machine) ; le résultat est gardé dans le cache et peut être exporté pour proposer une note au catalogue.
"""
import json
import re
import time
from pathlib import Path

from .ollama_client import ErreurOllama

QUESTIONS_CODE = [
    ("Que valent les valeurs affichées ? Réponds seulement par la valeur.\n```python\nx = [3, 1, 2]\nx.sort()\nprint(x[0] * 10 + x[-1])\n```", "13"),
    ("Que valent les valeurs affichées ? Réponds seulement par la valeur.\n```python\nprint(sum(i * i for i in range(4)))\n```", "14"),
    ("Que valent les valeurs affichées ? Réponds seulement par la valeur.\n```python\nprint(\"abc\"[::-1].upper())\n```", "CBA"),
    ("Combien de valeurs différentes prend i dans `for i in range(2, 10, 3)` ? Réponds seulement par le nombre.", "3"),
]
OUTILS = [
    {"type": "function", "function": {"name": "lire", "description": "Lit un fichier du projet.", "parameters": {"type": "object", "properties": {"chemin": {"type": "string"}}, "required": ["chemin"]}}},
    {"type": "function", "function": {"name": "chercher", "description": "Cherche un mot dans les fichiers du projet.", "parameters": {"type": "object", "properties": {"motif": {"type": "string"}}, "required": ["motif"]}}},
]
CAS_OUTILS = [
    ("Ouvre le fichier docs/notes.md et dis-moi ce qu'il contient.", "lire", "notes.md"),
    ("Où est définie la fonction connexion dans le projet ?", "chercher", "connexion"),
    ("Bonjour, comment vas-tu ?", None, None),
]
MOTS_FR = {"le", "la", "les", "de", "des", "du", "un", "une", "et", "est", "que", "qui", "dans", "pour", "pas", "sur", "au", "aux", "ce", "cette", "il", "elle", "à", "en", "par", "se"}
MOTS_EN = {"the", "and", "is", "of", "to", "in", "that", "it", "for", "with", "this", "are"}
SURNOMS = {"vitesse": "Vitesse", "outils": "Appel d'outils", "code": "Code (lecture)", "francais": "Français", "consignes": "Consignes"}


def nettoyer(texte):
    """Réponse sans bloc de réflexion (<think>…</think>) ni espaces superflus."""
    return re.sub(r"<think>.*?</think>", "", texte or "", flags=re.S | re.I).strip()


def est_francais(texte):
    mots = re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", texte.lower())
    if len(mots) < 5:
        return False
    fr = sum(m in MOTS_FR for m in mots) / len(mots)
    en = sum(m in MOTS_EN for m in mots) / len(mots)
    return fr >= 0.12 and en < 0.05


def reponse_exacte(texte, attendu):
    """La valeur attendue figure seule (pas collée à d'autres chiffres ou lettres) dans la dernière ligne, et la réponse reste courte."""
    t = nettoyer(texte).replace("`", "").replace('"', "").replace("'", "")
    if not t or len(t) > 400:
        return False
    derniere = [ligne for ligne in t.splitlines() if ligne.strip()][-1]
    return re.search(r"(?<![\w.])" + re.escape(attendu) + r"(?![\w.])", derniere, re.I) is not None


def trois_puces(texte):
    lignes = [ligne.strip() for ligne in nettoyer(texte).splitlines() if ligne.strip()]
    puces = [ligne for ligne in lignes if ligne.startswith(("-", "•", "*"))]
    return len(puces) == 3 and len(lignes) <= 4


def json_valide(texte):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", nettoyer(texte), flags=re.I).strip()
    try:
        d = json.loads(t)
    except ValueError:
        return False
    def norm(v):
        return re.sub(r"[^a-z]", "", str(v).lower().replace("é", "e"))
    return isinstance(d, dict) and norm(d.get("ville")) == "paris" and norm(d.get("pays")) == "france"


def note_vitesse(tok_s):
    for seuil, note in ((8, 2), (15, 4), (30, 6), (60, 8)):
        if tok_s < seuil:
            return note
    return 10


def notes_depuis(r):
    """Notes de 0 à 10 par rôle d'après les résultats. Formules simples, écrites ici pour qu'on puisse les contester."""
    def part(cle):
        x = r.get(cle)
        return x["points"] / x["sur"] if x and x.get("sur") else None
    outils, code, fr, cons = part("outils"), part("code"), part("francais"), part("consignes")
    notes = {}
    if outils is not None and code is not None:
        notes["code"] = round(10 * (0.6 * code + 0.4 * outils))
    if fr is not None and cons is not None:
        notes["creatif"] = round(10 * (0.6 * fr + 0.4 * cons))
    parts = [p for p in (outils, code, fr, cons) if p is not None]
    if len(parts) == 4:
        notes["polyvalent"] = round(10 * sum(parts) / 4)
    if r.get("vitesse", {}).get("tok_s") is not None:
        n = note_vitesse(r["vitesse"]["tok_s"])
        notes["rapide"] = min(n, 4) if outils is not None and outils < 0.67 else n          # un modèle qui n'appelle pas les outils ne sert pas à Lutin
    return notes


class Banc:
    def __init__(self, ollama, modele, num_ctx=4096, delai=300):
        self.ollama, self.modele, self.num_ctx, self.delai = ollama, modele, num_ctx, delai
        self.penser = True

    def demander(self, messages, outils=None, num_predict=200):
        corps = {"model": self.modele, "messages": messages, "stream": False, "options": {"temperature": 0, "num_predict": num_predict, "num_ctx": self.num_ctx}}
        if outils:
            corps["tools"] = outils
        if self.penser:
            corps["think"] = False
        try:
            return self.ollama.json("/api/chat", corps, self.delai)
        except ErreurOllama:
            if self.penser:                    # certains modèles refusent le réglage « think » : on réessaie sans
                self.penser = False
                corps.pop("think", None)
                return self.ollama.json("/api/chat", corps, self.delai)
            raise

    def texte(self, question, num_predict=120):
        return (self.demander([{"role": "user", "content": question}], num_predict=num_predict).get("message") or {}).get("content", "")

    def vitesse(self):
        r = self.demander([{"role": "user", "content": "Écris un texte d'environ 150 mots sur la mer."}], num_predict=200)
        n, duree = r.get("eval_count") or 0, (r.get("eval_duration") or 0) / 1e9
        lu, duree_lu = r.get("prompt_eval_count") or 0, (r.get("prompt_eval_duration") or 0) / 1e9
        if n < 5 or duree <= 0:
            return {"tok_s": None, "charge_s": round((r.get("load_duration") or 0) / 1e9, 1)}
        return {"tok_s": round(n / duree, 1), "charge_s": round((r.get("load_duration") or 0) / 1e9, 1), "lecture_tok_s": round(lu / duree_lu) if lu >= 20 and duree_lu > 0 else None}

    def outils(self):
        points = 0
        for question, attendu, motif in CAS_OUTILS:
            msg = self.demander([{"role": "user", "content": question}], outils=OUTILS, num_predict=100).get("message") or {}
            appels = msg.get("tool_calls") or []
            if attendu is None:
                points += 1 if not appels and nettoyer(msg.get("content")) else 0
                continue
            if not appels:
                continue
            f = appels[0].get("function") or {}
            args = f.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            if f.get("name") == attendu and motif in json.dumps(args or {}, ensure_ascii=False):
                points += 1
        return {"points": points, "sur": len(CAS_OUTILS)}

    def code(self):
        return {"points": sum(reponse_exacte(self.texte(q, 80), a) for q, a in QUESTIONS_CODE), "sur": len(QUESTIONS_CODE)}

    def francais(self):
        a = nettoyer(self.texte("Explique en une phrase, en français, pourquoi le ciel est bleu.", 120))
        b = self.texte("Donne exactement 3 conseils pour bien dormir, chacun sur une ligne commençant par « - », sans introduction.", 120)
        return {"points": int(est_francais(a) and 5 <= len(a.split()) <= 60) + int(trois_puces(b)), "sur": 2}

    def consignes(self):
        t = self.texte("Réponds uniquement avec un objet JSON valide, sans aucun texte autour, avec les clés \"ville\" et \"pays\", pour la capitale de la France.", 80)
        return {"points": int(json_valide(t)), "sur": 1}


def executer(ollama, modele, rapide=False, progression=None, resume_machine="", num_ctx=4096, delai=300, horloge=time.time):
    """Lance le banc. `rapide` : seulement la vitesse (environ 20 secondes). Renvoie la mesure complète, jamais d'exception : une panne est notée dans `erreur`."""
    banc = Banc(ollama, modele, num_ctx, delai)
    mesure = {"modele": modele, "date": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(horloge())), "machine": resume_machine, "complet": not rapide, "resultats": {}, "notes": {}}
    etapes = [("vitesse", banc.vitesse)] + ([] if rapide else [("outils", banc.outils), ("code", banc.code), ("francais", banc.francais), ("consignes", banc.consignes)])
    for i, (nom, fonction) in enumerate(etapes):
        if progression:
            progression(SURNOMS[nom], i, len(etapes))
        try:
            mesure["resultats"][nom] = fonction()
        except (ErreurOllama, OSError) as e:
            mesure["erreur"] = "{} : {}".format(SURNOMS[nom], e)
            break
    mesure["notes"] = notes_depuis(mesure["resultats"])
    return mesure


def resume(mesure):
    r, morceaux = mesure.get("resultats", {}), []
    v = r.get("vitesse", {})
    if v.get("tok_s") is not None:
        morceaux.append("{:g} jetons/s".format(v["tok_s"]))
    if v.get("charge_s"):
        morceaux.append("chargement {:g} s".format(v["charge_s"]))
    for cle, nom in (("outils", "outils"), ("code", "code"), ("francais", "français"), ("consignes", "consignes")):
        if cle in r:
            morceaux.append("{} {}/{}".format(nom, r[cle]["points"], r[cle]["sur"]))
    return " · ".join(morceaux) or "aucune mesure"


def lire(chemin):
    try:
        d = json.loads(Path(chemin).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def enregistrer(chemin, mesure):
    chemin = Path(chemin)
    tout = lire(chemin)
    tout[mesure["modele"]] = mesure
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(".tmp")
    tmp.write_text(json.dumps(tout, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(chemin)


def exporter(mesure):
    """Bloc à coller dans une proposition de note au catalogue (sans chemin ni donnée personnelle)."""
    return json.dumps({"modele": mesure["modele"], "date": mesure["date"][:10], "machine": mesure.get("machine", ""), "resultats": mesure["resultats"], "notes": mesure["notes"],
                       "complet": mesure["complet"]}, ensure_ascii=False, indent=1)
