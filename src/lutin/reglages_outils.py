"""Réglages des outils de base (exécuteur, lecture, recherche dans les fichiers, outils coupés) : un seul endroit, validé, appliqué sans rien redémarrer.

Les limites des outils étaient écrites en dur (4 minutes pour une commande, 9 000 caractères de sortie…). Elles se règlent maintenant dans Réglages > Outils, avec des bornes sûres.
Rien de ce qui est réglé ici n'élargit les accès : le dossier de travail, les accords demandés et les lectures « sans accord » (liste blanche stricte) gardent leurs règles.
`commandes_sans_accord` : des commandes EXACTES (ou un début suivi d'espace) que l'utilisateur dit sûres, sans chemin hors du projet ni enchaînement."""
import re

DEFAUT = {
    "outils_desactives": [],            # noms d'outils retirés au modèle (voir DESACTIVABLES)
    "outil_delai_commande_s": 240,      # temps maximal d'une commande de l'outil « executer »
    "outil_sortie_max": 9000,           # caractères gardés de la sortie d'une commande
    "outil_lecture_max": 7000,          # caractères rendus par une lecture de fichier
    "outil_chercher_delai_s": 25,       # temps maximal d'une recherche dans les fichiers
    "commandes_sans_accord": [],        # commandes sûres de plus, lancées sans accord (en plus de git status, ls…)
    "dossiers_ignores_en_plus": [],     # dossiers que les outils ne parcourent jamais, en plus de .git, node_modules…
}
BORNES = {"outil_delai_commande_s": (10, 3600), "outil_sortie_max": (2000, 60000), "outil_lecture_max": (2000, 60000), "outil_chercher_delai_s": (5, 180)}
# Les outils qu'on peut couper sans casser Lutin (ni la fiche de suivi, ni les missions, ni la mémoire, qui ont leurs propres réglages).
DESACTIVABLES = ("executer", "ecrire", "modifier", "modifier_plusieurs", "creer_document", "apercu_page", "web_chercher", "web_lire", "calculer", "symboles", "lire_plusieurs", "rappeler", "trouver", "chercher")
RE_COMMANDE = re.compile(r"^[A-Za-z0-9_./:= \-]{2,120}$")          # ni | & ; < > ` $ ( ) { } ni guillemets : pas d'enchaînement, pas de substitution
RE_DOSSIER = re.compile(r"^[A-Za-z0-9_.\- ]{1,60}$")
INTERDITS_DEBUT = ("rm", "del", "erase", "rd", "rmdir", "format", "shutdown", "reboot", "sudo", "curl", "wget", "powershell", "pwsh", "cmd", "sh", "bash", "python", "pip", "npm", "node", "docker", "ssh", "scp", "mv", "move", "cp", "copy", "chmod", "chown", "kill", "taskkill", "reg", "net")


def _borne(valeur, defaut, mini, maxi):
    try:
        return max(mini, min(maxi, int(valeur)))
    except (TypeError, ValueError):
        return defaut


def commande_valide(texte):
    """Une commande qu'on peut dire sûre sans accord : texte simple, pas d'enchaînement, pas de programme qui efface, installe, télécharge ou ouvre un shell."""
    t = str(texte or "").strip()
    if not RE_COMMANDE.match(t) or ".." in t or "--output" in t or re.search(r"[A-Za-z]:[\\/]|^[/~]|\s[/~]", t):
        return False
    return t.split()[0].lower() not in INTERDITS_DEBUT


def nettoyer(r):
    """Remet les réglages d'outils d'un dictionnaire de réglages dans leurs bornes (en place). Une valeur illisible redevient la valeur par défaut."""
    for cle, (mini, maxi) in BORNES.items():
        r[cle] = _borne(r.get(cle, DEFAUT[cle]), DEFAUT[cle], mini, maxi)
    brut = r.get("outils_desactives")
    r["outils_desactives"] = sorted({str(x) for x in (brut if isinstance(brut, list) else []) if str(x) in DESACTIVABLES})
    brut = r.get("commandes_sans_accord")
    r["commandes_sans_accord"] = sorted({str(x).strip() for x in (brut if isinstance(brut, list) else []) if commande_valide(x)})[:40]
    brut = r.get("dossiers_ignores_en_plus")
    r["dossiers_ignores_en_plus"] = sorted({str(x).strip() for x in (brut if isinstance(brut, list) else []) if RE_DOSSIER.match(str(x).strip())})[:40]
    return r


def verifier(nouveau):
    """Pour l'enregistrement : refuse avec une explication ce que `nettoyer` ignorerait en silence (une commande dangereuse, un outil inconnu)."""
    from .i18n import t as _t
    for x in nouveau.get("commandes_sans_accord") or []:
        if not commande_valide(x):
            raise ValueError(_t("« {} » ne peut pas être lancée sans accord : une commande simple seulement (pas d'enchaînement, de chemin hors du projet, ni de programme qui efface, installe ou télécharge).").format(str(x)[:60]))
    for x in nouveau.get("outils_desactives") or []:
        if str(x) not in DESACTIVABLES:
            raise ValueError(_t("Cet outil ne peut pas être coupé : {}").format(str(x)[:40]))
    for x in nouveau.get("dossiers_ignores_en_plus") or []:
        if not RE_DOSSIER.match(str(x).strip()):
            raise ValueError(_t("Nom de dossier à ignorer invalide : un nom seul, sans chemin ({}).").format(str(x)[:40]))


class Appliquees:
    """Ce qui est en vigueur dans le moteur : l'application ne refait rien tant que les réglages d'outils n'ont pas changé (un test qui règle une limite à la main n'est donc pas écrasé)."""
    derniere = None


def appliquer(r, m):
    """Pose les limites dans le module moteur (`m`), lues à chaque appel d'outil. Appelé à chaque lecture des réglages, mais ne fait quelque chose que s'ils ont changé."""
    cle = (r["outil_delai_commande_s"], r["outil_sortie_max"], r["outil_lecture_max"], r["outil_chercher_delai_s"], tuple(r["commandes_sans_accord"]), tuple(r["dossiers_ignores_en_plus"]))
    if Appliquees.derniere == cle:
        return
    Appliquees.derniere = cle
    m.DELAI_COMMANDE_S, m.SORTIE_MAX, m.LECTURE_MAX, m.CHERCHER_DELAI = cle[0], cle[1], cle[2], cle[3]
    m.DOSSIERS_IGNORES = set(m.DOSSIERS_IGNORES_BASE) | set(cle[5])
    m.COMMANDES_LECTURE = m.construire_commandes_lecture(m.os.name != "nt", cle[4])
    m.COMMANDES_SANS_ACCORD = cle[4]
