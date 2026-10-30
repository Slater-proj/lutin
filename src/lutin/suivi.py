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

from . import moteur as _m
from .i18n import t as _t

SECTIONS = (("objectif", "Objectif"), ("decisions", "Décisions"), ("plan", "Plan"), ("etape", "Étape en cours"), ("fait", "Fait"),
            ("ouvert", "Questions ouvertes"), ("fichiers", "Fichiers touchés"), ("demandes", "Dernières demandes"))
CLES = tuple(c for c, _ in SECTIONS)
TITRES = dict(SECTIONS)
LIGNES_MAX = {"objectif": 3, "decisions": 25, "plan": 20, "etape": 3, "fait": 15, "ouvert": 10, "fichiers": 30, "demandes": 6}
LIGNE_MAX = 240
PART_MAX = 0.10                      # part de la fenêtre de contexte que la fiche peut prendre (au-delà, elle est raccourcie)
PART_ATTENTION = 0.07                # au-delà, la page avertit
CARACTERES_PAR_JETON = 3
RE_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
MOTS_CONFIRMATION = {"oui", "ok", "okay", "yes", "go", "daccord", "dac", "ouais", "parfait", "valide", "valider", "lance", "lancez", "continue", "continuez", "allez", "vasy", "fais", "faisle", "fonce",
                     "cestbon", "onyva", "action", "proceed", "confirm", "confirme", "execute", "executez", "vas", "y", "on", "passe", "a", "laction", "le", "c", "est", "bon", "d", "accord", "do", "it",
                     "cest", "daccord", "ahead", "please", "svp", "stp", "merci", "super", "nickel", "bien", "sur", "carrement"}
_cache = {}


def dossier():
    return _m.DONNEES / "suivis"


def chemin(ident):
    if not RE_ID.match(str(ident or "")):
        raise ValueError(_t("Conversation inconnue."))
    return dossier() / (str(ident) + ".md")


def nettoyer_ligne(texte):
    return " ".join(str(texte or "").replace("#", "").split())[:LIGNE_MAX]


def normaliser_section(nom):
    base = unicodedata.normalize("NFKD", str(nom or "").lower()).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z]", "", base)
    alias = {"objectif": "objectif", "but": "objectif", "decision": "decisions", "decisions": "decisions", "plan": "plan", "etape": "etape", "etapeencours": "etape", "encours": "etape",
             "fait": "fait", "faits": "fait", "fini": "fait", "termine": "fait", "ouvert": "ouvert", "ouverts": "ouvert", "questions": "ouvert", "questionsouvertes": "ouvert", "question": "ouvert",
             "fichier": "fichiers", "fichiers": "fichiers", "fichierstouches": "fichiers", "demande": "demandes", "demandes": "demandes", "dernieresdemandes": "demandes"}
    cle = alias.get(base)
    if not cle:
        raise _m.ErreurOutil(_t("Section inconnue : « {} ». Sections : {}.").format(nom, ", ".join(CLES)))
    return cle


def vide():
    return {c: [] for c in CLES}


def borner(sections):
    """La fiche remise dans ses limites : lignes courtes, pas de doublon, nombre de lignes par section (on garde les plus récentes)."""
    sortie = vide()
    for cle in CLES:
        vues, lignes = set(), []
        for brut in sections.get(cle, []):
            ligne = nettoyer_ligne(brut)
            if ligne and ligne.lower() not in vues:
                vues.add(ligne.lower())
                lignes.append(ligne)
        sortie[cle] = lignes[-LIGNES_MAX[cle]:]
    return sortie


def serialiser(ident, sections):
    morceaux = ["# " + _t("Fiche de suivi"), "<!-- lutin-suivi conversation={} -->".format(ident), ""]
    for cle, titre in SECTIONS:
        if sections.get(cle):
            morceaux.append("## " + titre)
            morceaux += ["- " + ligne for ligne in sections[cle]]
            morceaux.append("")
    return "\n".join(morceaux)


def analyser(texte):
    sections, courante = vide(), None
    par_titre = {t.lower(): c for c, t in SECTIONS}
    for brut in (texte or "").splitlines():
        if brut.startswith("## "):
            courante = par_titre.get(brut[3:].strip().lower())
        elif courante and brut.startswith("- "):
            sections[courante].append(brut[2:])
    return borner(sections)


def lire(ident):
    f = chemin(ident)
    try:
        mtime = f.stat().st_mtime_ns
    except OSError:
        return vide()
    en_cache = _cache.get(str(f))
    if en_cache and en_cache[0] == mtime:
        return en_cache[1]
    try:
        sections = analyser(f.read_text(encoding="utf-8"))
    except OSError:
        return vide()
    _cache[str(f)] = (mtime, sections)
    return sections


def ecrire(ident, sections):
    f = chemin(ident)
    sections = borner(sections)
    if not any(sections.values()):
        supprimer(ident)
        return sections
    f.parent.mkdir(parents=True, exist_ok=True)
    _m.ecrire_atomique(f, serialiser(ident, sections))
    _cache.pop(str(f), None)
    return sections


def supprimer(ident):
    """Supprime la fiche (appelé quand la conversation est supprimée). Renvoie True si elle existait."""
    try:
        f = chemin(ident)
    except ValueError:
        return False
    _cache.pop(str(f), None)
    existait = f.is_file()
    f.unlink(missing_ok=True)
    return existait


def nettoyer_orphelins(ids_existants):
    """Supprime les fiches dont la conversation n'existe plus. Renvoie le nombre supprimé."""
    n = 0
    try:
        for f in dossier().glob("*.md"):
            if f.stem not in ids_existants:
                f.unlink(missing_ok=True)
                _cache.pop(str(f), None)
                n += 1
    except OSError:
        pass
    return n


def modifier(ident, section, texte, mode=""):
    """Met la fiche à jour. mode : « remplacer » (objectif, plan, étape par défaut), « ajouter » (les autres), « retirer » (enlève les lignes qui contiennent le texte). Renvoie un compte rendu court."""
    cle = normaliser_section(section)
    sections = lire(ident)
    nouvelles = [nettoyer_ligne(x) for x in re.split(r"\n+", str(texte or "")) if nettoyer_ligne(x)]
    mode = (mode or ("remplacer" if cle in ("objectif", "plan", "etape") else "ajouter")).lower()
    if mode not in ("remplacer", "ajouter", "retirer"):
        raise _m.ErreurOutil(_t("Mode inconnu : « {} » (remplacer, ajouter ou retirer).").format(mode))
    if mode == "retirer":
        cherche = nettoyer_ligne(texte).lower()
        if not cherche:
            raise _m.ErreurOutil(_t("Dis quelle ligne retirer."))
        avant = len(sections[cle])
        sections[cle] = [ligne for ligne in sections[cle] if cherche not in ligne.lower()]
        retirees = avant - len(sections[cle])
        ecrire(ident, sections)
        return _t("{} ligne(s) retirée(s) de « {} ».").format(retirees, TITRES[cle])
    if not nouvelles:
        raise _m.ErreurOutil(_t("Texte vide."))
    sections[cle] = nouvelles if mode == "remplacer" else sections[cle] + nouvelles
    ecrire(ident, sections)
    return _t("Fiche de suivi mise à jour : « {} ».").format(TITRES[cle])


def apres_tour(ident, demande, reponse, fichiers=()):
    """Mise à jour automatique à la fin d'une réponse, sans appel au modèle : la demande (et un début de réponse) rejoint « Dernières demandes », les fichiers touchés rejoignent « Fichiers touchés »."""
    sections = lire(ident)
    d, r = nettoyer_ligne(demande)[:110], nettoyer_ligne(reponse)[:110]
    if d:
        sections["demandes"].append(d + (" → " + r if r else ""))
    sections["fichiers"] += [str(f) for f in fichiers]
    ecrire(ident, sections)


def rendre(sections, budget_caracteres):
    """Le texte de la fiche pour le modèle, dans la limite demandée : si c'est trop long, on retire d'abord les dernières demandes, puis les fichiers, puis les plus anciennes lignes de « fait »."""
    sections = {c: list(v) for c, v in sections.items()}

    def texte():
        morceaux = []
        for cle, titre in SECTIONS:
            if sections[cle]:
                morceaux.append("{} :\n".format(titre) + "\n".join("- " + ligne for ligne in sections[cle]))
        return "\n".join(morceaux)
    for cle in ("demandes", "fichiers", "fait", "decisions", "ouvert"):
        while len(texte()) > budget_caracteres and len(sections[cle]) > (2 if cle in ("fait", "decisions") else 0):
            sections[cle].pop(0)
    return texte()[:budget_caracteres]


def budget_caracteres(num_ctx):
    return int(num_ctx * PART_MAX * CARACTERES_PAR_JETON)


def texte_pour_modele(ident, num_ctx):
    """Le bloc à donner au modèle ('' si la fiche est vide)."""
    t = rendre(lire(ident), budget_caracteres(num_ctx))
    if not t:
        return ""
    return "[Fiche de suivi] " + _t("Tenue à jour pour cette conversation : fie-toi à elle pour savoir où on en est. Elle fait foi sur l'objectif, les décisions et l'étape en cours.") + "\n" + t


def mesure(ident, num_ctx):
    """{lignes, jetons, part, niveau, avertissement} : ce que la fiche coûte à chaque réponse. niveau : ok, attention (elle prend beaucoup de place), vide."""
    sections = lire(ident)
    lignes = sum(len(v) for v in sections.values())
    if not lignes:
        return {"lignes": 0, "jetons": 0, "part": 0.0, "niveau": "vide", "avertissement": ""}
    jetons = len(rendre(sections, 10 ** 9)) // CARACTERES_PAR_JETON
    part = round(jetons / max(1, num_ctx), 3)
    niveau = "attention" if part >= PART_ATTENTION else "ok"
    avert = _t("La fiche prend {} % de la fenêtre de contexte : elle ralentit chaque réponse et laisse moins de place à la conversation. Elle est raccourcie automatiquement au-delà de {} %.").format(round(part * 100), round(PART_MAX * 100)) if niveau == "attention" else ""
    return {"lignes": lignes, "jetons": jetons, "part": part, "niveau": niveau, "avertissement": avert}


def est_confirmation(texte):
    """Vrai si le message est une simple validation (« oui », « ok vas-y », « on passe à l'action »…) : au plus 8 mots, tous des mots de validation."""
    base = unicodedata.normalize("NFKD", str(texte or "").lower()).encode("ascii", "ignore").decode()
    mots = re.findall(r"[a-z]+", base.replace("'", "").replace("’", ""))
    return 0 < len(mots) <= 8 and all(m in MOTS_CONFIRMATION for m in mots)


def directive_execution(conv, texte, ident):
    """Quand l'utilisateur valide (« oui ») et qu'il y a une étape ou une tâche à faire : une consigne qui ordonne d'EXÉCUTER, pas de replanifier ni de redemander. '' sinon."""
    if not est_confirmation(texte):
        return ""
    a_faire = [t for t in (conv.get("taches") or []) if t.get("etat") != "fait"]
    cible = ""
    if a_faire:
        cible = next((t["texte"] for t in a_faire if t.get("etat") == "en_cours"), a_faire[0]["texte"])
    else:
        try:
            etape = lire(ident)["etape"]
        except ValueError:
            etape = []
        cible = etape[0] if etape else ""
    if not cible:
        return ""
    return _t("L'utilisateur vient de VALIDER. Exécute maintenant, avec tes outils : « {} ». Ne refais pas le plan, ne redemande pas de confirmation ; fais l'étape, dis ce qui est fait, puis passe à la suivante si l'utilisateur l'a demandé.").format(cible)
