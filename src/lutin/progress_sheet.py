"""La fiche de suivi : la mémoire d'une conversation très longue, tenue dans un fichier plutôt que résumée par le modèle.

Le problème d'un modèle local sur une longue conversation : la fenêtre de contexte est petite, le début est oublié (ou résumé, avec des pertes), et au « oui, on passe à l'action » le modèle ne sait plus
où il en est et replanifie. Ici, l'essentiel tient dans une fiche courte, tenue à jour, relue à chaque réponse :
objectif, décisions, plan, étape en cours, ce qui est fait, questions ouvertes, fichiers touchés, dernières demandes.

Règles de solidité :
- une fiche par conversation, dans donnees/suivis/<identifiant>.md ; elle disparaît avec la conversation, et les fiches orphelines sont nettoyées ;
- elle est BORNÉE (nombre de lignes par section, longueur des lignes, part de la fenêtre de contexte) : elle ne peut pas grossir sans fin ni ralentir chaque réponse ; la part prise est mesurée et affichée ;
- le modèle peut la mettre à jour (outil « suivi »), mais elle se remplit aussi toute seule (dernières demandes, fichiers touchés) : un petit modèle qui oublie l'outil ne la laisse pas vide ;
- elle est ajoutée AVANT la dernière question et non dans le message système : le début de la conversation reste identique d'une réponse à l'autre, donc Ollama le garde en cache et la relit plus vite."""
import re
import unicodedata

from . import core as _m
from .i18n import t as _t

SECTIONS = (("objectif", "Objectif"), ("decisions", "Décisions"), ("plan", "Plan"), ("etape", "Étape en cours"), ("fait", "Fait"),
            ("ouvert", "Questions ouvertes"), ("fichiers", "Fichiers touchés"), ("demandes", "Dernières demandes"))
KEYS = tuple(c for c, _ in SECTIONS)
TITLES = dict(SECTIONS)
MAX_LINES = {"objectif": 3, "decisions": 25, "plan": 20, "etape": 3, "fait": 15, "ouvert": 10, "fichiers": 30, "demandes": 6}
MAX_LINE = 240
KEPT_FIRST_DECISIONS = 5              # au-delà du plafond, les 5 premières décisions restent, avec les plus récentes
RENDER_ORDER = ("objectif", "etape", "ouvert", "decisions", "plan", "fait", "fichiers", "demandes")          # pour le modèle : l'essentiel d'abord, une coupe n'enlève que la fin
MAX_SHARE = 0.10                      # part de la fenêtre de contexte que la fiche peut prendre (au-delà, elle est raccourcie)
SHARE_WARNING = 0.07                # au-delà, la page avertit
CHARS_PER_TOKEN = 3
RE_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
CONFIRMATION_WORDS = {"oui", "ok", "okay", "yes", "go", "daccord", "dac", "ouais", "parfait", "valide", "valider", "lance", "lancez", "continue", "continuez", "allez", "vasy", "fais", "faisle", "fonce",
                     "cestbon", "onyva", "action", "proceed", "confirm", "confirme", "execute", "executez", "vas", "y", "on", "passe", "a", "laction", "le", "c", "est", "bon", "d", "accord", "do", "it",
                     "cest", "daccord", "ahead", "please", "svp", "stp", "merci", "super", "nickel", "bien", "sur", "carrement"}
_cache = {}


def folder():
    return _m.DONNEES / "suivis"


def path(ident):
    if not RE_ID.match(str(ident or "")):
        raise ValueError(_t("Conversation inconnue."))
    return folder() / (str(ident) + ".md")


def clean_line(texte):
    return " ".join(str(texte or "").replace("#", "").split())[:MAX_LINE]


def normalize_section(nom):
    base = unicodedata.normalize("NFKD", str(nom or "").lower()).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z]", "", base)
    alias = {"objectif": "objectif", "but": "objectif", "decision": "decisions", "decisions": "decisions", "plan": "plan", "etape": "etape", "etapeencours": "etape", "encours": "etape",
             "fait": "fait", "faits": "fait", "fini": "fait", "termine": "fait", "ouvert": "ouvert", "ouverts": "ouvert", "questions": "ouvert", "questionsouvertes": "ouvert", "question": "ouvert",
             "fichier": "fichiers", "fichiers": "fichiers", "fichierstouches": "fichiers", "demande": "demandes", "demandes": "demandes", "dernieresdemandes": "demandes"}
    cle = alias.get(base)
    if not cle:
        raise _m.ErreurOutil(_t("Section inconnue : « {} ». Sections : {}.").format(nom, ", ".join(KEYS)))
    return cle


def empty():
    return {c: [] for c in KEYS}


def clamp(sections):
    """La fiche remise dans ses limites : lignes courtes, pas de doublon, nombre de lignes par section (on garde les plus récentes)."""
    sortie = empty()
    for cle in KEYS:
        vues, lignes = set(), []
        for brut in sections.get(cle, []):
            ligne = clean_line(brut)
            if ligne and ligne.lower() not in vues:
                vues.add(ligne.lower())
                lignes.append(ligne)
        if cle == "decisions" and len(lignes) > MAX_LINES[cle]:
            lignes = lignes[:KEPT_FIRST_DECISIONS] + lignes[len(lignes) - (MAX_LINES[cle] - KEPT_FIRST_DECISIONS):]          # les premières décisions fondent le projet : gardées
        sortie[cle] = lignes[-MAX_LINES[cle]:]
    return sortie


def serialize(ident, sections):
    morceaux = ["# " + _t("Fiche de suivi"), "<!-- lutin-suivi conversation={} -->".format(ident), ""]
    for cle, titre in SECTIONS:
        if sections.get(cle):
            morceaux.append("## " + titre)
            morceaux += ["- " + ligne for ligne in sections[cle]]
            morceaux.append("")
    return "\n".join(morceaux)


def parse(texte):
    sections, courante = empty(), None
    par_titre = {t.lower(): c for c, t in SECTIONS}
    for brut in (texte or "").splitlines():
        if brut.startswith("## "):
            courante = par_titre.get(brut[3:].strip().lower())
        elif courante and brut.startswith("- "):
            sections[courante].append(brut[2:])
    return clamp(sections)


def read(ident):
    f = path(ident)
    try:
        mtime = f.stat().st_mtime_ns
    except OSError:
        return empty()
    en_cache = _cache.get(str(f))
    if en_cache and en_cache[0] == mtime:
        return en_cache[1]
    try:
        sections = parse(f.read_text(encoding="utf-8"))
    except OSError:
        return empty()
    _cache[str(f)] = (mtime, sections)
    return sections


def write(ident, sections):
    f = path(ident)
    sections = clamp(sections)
    if not any(sections.values()):
        delete(ident)
        return sections
    f.parent.mkdir(parents=True, exist_ok=True)
    _m.ecrire_atomique(f, serialize(ident, sections))
    _cache.pop(str(f), None)
    return sections


def delete(ident):
    """Supprime la fiche (appelé quand la conversation est supprimée). Renvoie True si elle existait."""
    try:
        f = path(ident)
    except ValueError:
        return False
    _cache.pop(str(f), None)
    existait = f.is_file()
    f.unlink(missing_ok=True)
    return existait


def clean_orphans(ids_existants):
    """Supprime les fiches dont la conversation n'existe plus. Renvoie le nombre supprimé."""
    n = 0
    try:
        for f in folder().glob("*.md"):
            if f.stem not in ids_existants:
                f.unlink(missing_ok=True)
                _cache.pop(str(f), None)
                n += 1
    except OSError:
        pass
    return n


def modify(ident, section, texte, mode=""):
    """Met la fiche à jour. mode : « remplacer » (objectif, plan, étape par défaut), « ajouter » (les autres), « retirer » (enlève les lignes qui contiennent le texte). Renvoie un compte rendu court."""
    cle = normalize_section(section)
    sections = read(ident)
    nouvelles = [clean_line(x) for x in re.split(r"\n+", str(texte or "")) if clean_line(x)]
    mode = (mode or ("remplacer" if cle in ("objectif", "plan", "etape") else "ajouter")).lower()
    if mode not in ("remplacer", "ajouter", "retirer"):
        raise _m.ErreurOutil(_t("Mode inconnu : « {} » (remplacer, ajouter ou retirer).").format(mode))
    if mode == "retirer":
        cherche = clean_line(texte).lower()
        if not cherche:
            raise _m.ErreurOutil(_t("Dis quelle ligne retirer."))
        avant = len(sections[cle])
        sections[cle] = [ligne for ligne in sections[cle] if cherche not in ligne.lower()]
        retirees = avant - len(sections[cle])
        write(ident, sections)
        return _t("{} ligne(s) retirée(s) de « {} ».").format(retirees, TITLES[cle])
    if not nouvelles:
        raise _m.ErreurOutil(_t("Texte vide."))
    sections[cle] = nouvelles if mode == "remplacer" else sections[cle] + nouvelles
    write(ident, sections)
    return _t("Fiche de suivi mise à jour : « {} ».").format(TITLES[cle])


def after_turn(ident, demande, reponse, fichiers=()):
    """Mise à jour automatique à la fin d'une réponse, sans appel au modèle : la demande (et un début de réponse) rejoint « Dernières demandes », les fichiers touchés rejoignent « Fichiers touchés »."""
    sections = read(ident)
    d, r = clean_line(demande)[:110], clean_line(reponse)[:110]
    if d:
        sections["demandes"].append(d + (" → " + r if r else ""))
    sections["fichiers"] += [str(f) for f in fichiers]
    write(ident, sections)


def render(sections, budget_caracteres):
    """Le texte de la fiche pour le modèle, dans la limite demandée. L'objectif et l'étape en cours viennent d'abord ; si c'est trop long, on retire les
    plus anciennes demandes, puis les fichiers, les plus anciennes lignes de « fait », la fin du plan (les étapes lointaines), les décisions du milieu
    (la première et les plus récentes restent), le reste de « fait », enfin les questions ouvertes. Une coupe nette, en dernier recours, n'enlève que la
    fin."""
    sections = {c: list(v) for c, v in sections.items()}

    def texte():
        morceaux = []
        for cle in RENDER_ORDER:
            if sections.get(cle):
                morceaux.append("{} :\n".format(TITLES[cle]) + "\n".join("- " + ligne for ligne in sections[cle]))
        return "\n".join(morceaux)
    for cle, garder in (("demandes", 0), ("fichiers", 0), ("fait", 2), ("plan", 1), ("decisions", 2), ("fait", 0), ("ouvert", 1)):
        while len(texte()) > budget_caracteres and len(sections.get(cle) or []) > garder:
            if cle == "plan":
                sections[cle].pop()                               # la fin du plan : les étapes les plus lointaines
            elif cle == "decisions":
                sections[cle].pop(1)                              # celles du milieu : la première et les plus récentes restent
            else:
                sections[cle].pop(0)
    return texte()[:budget_caracteres]


def max_share():
    """La part de la fenêtre de contexte que la fiche peut prendre : le réglage « fiche_part » (5 à 25 %, 10 par défaut)."""
    try:
        return max(5, min(25, int(_m.reglages().get("fiche_part", 10)))) / 100
    except (TypeError, ValueError):
        return MAX_SHARE


def budget_caracteres(num_ctx):
    return int(num_ctx * max_share() * CHARS_PER_TOKEN)


def text_for_model(ident, num_ctx):
    """Le bloc à donner au modèle ('' si la fiche est vide)."""
    t = render(read(ident), budget_caracteres(num_ctx))
    if not t:
        return ""
    return "[Fiche de suivi] " + _t("Tenue à jour pour cette conversation : fie-toi à elle pour savoir où on en est. Elle fait foi sur l'objectif, les décisions et l'étape en cours.") + "\n" + t


def measure(ident, num_ctx):
    """{lignes, jetons, part, niveau, avertissement} : ce que la fiche coûte à chaque réponse. niveau : ok, attention (elle prend beaucoup de place), vide."""
    sections = read(ident)
    lignes = sum(len(v) for v in sections.values())
    if not lignes:
        return {"lignes": 0, "jetons": 0, "part": 0.0, "niveau": "vide", "avertissement": ""}
    jetons = len(render(sections, 10 ** 9)) // CHARS_PER_TOKEN
    part = round(jetons / max(1, num_ctx), 3)
    plafond = max_share()
    niveau = "attention" if part >= plafond * SHARE_WARNING / MAX_SHARE else "ok"          # l'avertissement vient aux sept dixièmes du plafond
    avert = _t("La fiche prend {} % de la fenêtre de contexte : elle ralentit chaque réponse et laisse moins de place à la conversation. Elle est raccourcie automatiquement au-delà de {} %.").format(round(part * 100), round(plafond * 100)) if niveau == "attention" else ""
    return {"lignes": lignes, "jetons": jetons, "part": part, "niveau": niveau, "avertissement": avert}


def is_confirmation(texte):
    """Vrai si le message est une simple validation (« oui », « ok vas-y », « on passe à l'action »…) : au plus 8 mots, tous des mots de validation."""
    base = unicodedata.normalize("NFKD", str(texte or "").lower()).encode("ascii", "ignore").decode()
    mots = re.findall(r"[a-z]+", base.replace("'", "").replace("’", ""))
    return 0 < len(mots) <= 8 and all(m in CONFIRMATION_WORDS for m in mots)


def execution_directive(conv, texte, ident):
    """Quand l'utilisateur valide (« oui ») et qu'il y a une étape ou une tâche à faire : une consigne qui ordonne d'EXÉCUTER, pas de replanifier ni de redemander. '' sinon."""
    if not is_confirmation(texte):
        return ""
    a_faire = [t for t in (conv.get("taches") or []) if t.get("etat") != "fait"]
    cible = ""
    if a_faire:
        cible = next((t["texte"] for t in a_faire if t.get("etat") == "en_cours"), a_faire[0]["texte"])
    else:
        try:
            etape = read(ident)["etape"]
        except ValueError:
            etape = []
        cible = etape[0] if etape else ""
    derniere = next((str(m.get("content") or "") for m in reversed(conv.get("messages") or []) if m.get("role") == "assistant" and m.get("content")), "")
    propose = "?" in derniere[-300:]                                       # ton dernier message se terminait par une proposition ou une question : c'est elle que « oui » valide
    if not cible and not propose:
        return ""
    if not cible:
        return _t("L'utilisateur vient de VALIDER. Exécute maintenant, avec tes outils, ce que tu viens de lui proposer dans ton dernier message. Ne refais pas le plan, ne redemande pas de confirmation ; fais l'action, dis ce qui est fait.")
    return _t("L'utilisateur vient de VALIDER. Exécute maintenant, avec tes outils, ce que tu viens de lui proposer dans ton dernier message. Étape en cours de la fiche, pour mémoire (elle peut être déjà faite : dans ce cas ne le répète pas, vérifie en une action puis passe à la suite) : « {} ». Ne refais pas le plan, ne redemande pas de confirmation ; fais l'action, dis ce qui est fait.").format(cible)
