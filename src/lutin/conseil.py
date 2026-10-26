"""« Tester mon PC » : à partir de la vitesse mesurée du modèle actif, des conseils concrets (modèle plus léger, contexte, charge) — sans rien changer tout seul.

Les seuils sont des repères de confort de lecture, pas des mesures de qualité : en dessous de 5 mots à la seconde environ la réponse se lit plus vite qu'elle ne s'écrit.
"""
from . import selection
from .i18n import t as _t

CONFORTABLE = 25.0        # jetons par seconde : réponse plus rapide que la lecture
CORRECT = 10.0
LENT = 5.0


def qualite(tok_s):
    if tok_s >= CONFORTABLE:
        return "tres_bien"
    if tok_s >= CORRECT:
        return "bien"
    if tok_s >= LENT:
        return "lent"
    return "tres_lent"


def analyser(mesure, profil, reglages, catalogue, installes=(), charge=None):
    """[{niveau: ok | info | attention, texte}] : la vitesse mesurée en une phrase, puis ce qui peut l'améliorer.
    mesure : {tok_s, charge_s} ; charge : {taille, vram} du modèle chargé dans Ollama (ou None) ; catalogue : le catalogue de modèles (selection.choisir)."""
    tok_s = float(mesure.get("tok_s") or 0)
    modele = reglages.get("modele", "")
    q = qualite(tok_s)
    mots_par_s = tok_s * 0.75
    lignes = [{"niveau": "ok" if q in ("tres_bien", "bien") else "attention",
               "texte": _t("{} écrit environ {:.0f} jetons par seconde (≈ {:.0f} mots) : {}.").format(modele, tok_s, mots_par_s, {
                   "tres_bien": _t("très confortable, plus vite que tu ne lis"), "bien": _t("confortable"),
                   "lent": _t("lisible mais lent, une longue réponse se fait attendre"), "tres_lent": _t("trop lent pour une conversation agréable")}[q])}]
    lignes.append({"niveau": "info", "texte": _t("Une réponse de 300 mots prend environ {:.0f} secondes.").format(400 / tok_s) if tok_s > 0 else _t("Vitesse non mesurée.")})
    if mesure.get("charge_s"):
        lignes.append({"niveau": "info", "texte": _t("Chargement du modèle en mémoire : {:.0f} s (une seule fois tant qu'il reste chargé).").format(float(mesure["charge_s"]))})
    sur_carte = None
    if charge and charge.get("taille"):
        sur_carte = charge.get("vram", 0) / charge["taille"]
        if sur_carte < 0.9 and not profil.sans_gpu():
            lignes.append({"niveau": "attention", "texte": _t("Le modèle ne tient pas tout entier sur la carte graphique ({:.0f} % dessus) : le reste tourne sur le processeur, ce qui ralentit beaucoup. Ferme les programmes qui utilisent la carte (ComfyUI…), baisse la fenêtre de contexte, ou prends un modèle plus petit.").format(sur_carte * 100)})
    if profil.sans_gpu():
        lignes.append({"niveau": "info", "texte": _t("Aucune carte graphique utilisable : tout tourne sur le processeur et la RAM, c'est normal que ce soit plus lent. Les modèles « experts » (peu de paramètres actifs par mot) et les petits modèles sont les plus à l'aise.")})
    if q in ("lent", "tres_lent"):
        choix = selection.choisir(profil, catalogue).get("rapide")
        if choix and choix.id != modele:
            etat = _t("déjà installé") if choix.id in installes else _t("à installer : {} Go").format(choix.modele["go"])
            lignes.append({"niveau": "attention", "texte": _t("Le modèle rapide conseillé pour ta machine est « {} » ({}) : lui, tiendrait mieux. Onglet Modèles pour l'essayer.").format(choix.id, etat)})
        if int(reglages.get("num_ctx", 0)) > 16384:
            lignes.append({"niveau": "attention", "texte": _t("La fenêtre de contexte est grande ({} jetons) : la baisser à 16 384 (Réglages) fait démarrer les réponses plus vite et libère de la mémoire.").format(reglages["num_ctx"])})
    elif q in ("bien", "tres_bien") and reglages.get("num_thread") is None:
        lignes.append({"niveau": "info", "texte": _t("Si le PC ralentit quand tu travailles à côté, le profil « Discret » (Réglages > Charge de la machine) laisse de la place au reste, au prix d'un peu de vitesse.")})
    return lignes
