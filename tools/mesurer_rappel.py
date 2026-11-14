"""Mesure la qualité de la recherche par mots (recall.py) sur un petit corpus bilingue de référence.

    python tools/mesurer_rappel.py

Chaque question est une REFORMULATION du passage attendu (pluriels, accents, conjugaisons, synonymes proches, anglais) : c'est ce qui fait échouer une recherche trop littérale.
On affiche, pour la recherche par mots :
- rappel@1 : la bonne réponse est classée première ;
- rappel@3 : la bonne réponse est dans les trois premières ;
- MRR : moyenne de 1/rang de la bonne réponse (1 = toujours première).
Les tests exigent un minimum (tests/test_rappel_mesure.py) : une régression de la recherche se voit tout de suite."""
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lutin import core  # noqa: E402,F401  (à charger avant rappel : ils s'importent l'un l'autre)
from lutin import recall  # noqa: E402

CORPUS = {
    "sauvegarde": "# Sauvegarde\nLes sauvegardes de la base de données sont faites chaque nuit à trois heures et conservées pendant trente jours sur le NAS du salon.",
    "wol": "# Réveil à distance\nLe PC de jeu se réveille avec le Wake-on-LAN : il faut activer l'option dans le BIOS puis dans les propriétés de la carte réseau.",
    "chats": "# Les chats\nMes deux chats, Moka et Praline, mangent des croquettes sans céréales et vont chez le vétérinaire en mars pour leurs vaccins.",
    "facture": "# Facture électricité\nLa facture d'électricité de novembre s'élève à 84 euros ; le contrat heures creuses démarre à vingt-deux heures.",
    "docker": "# Docker\nLe conteneur de l'assistant redémarre automatiquement grâce à la politique restart: unless-stopped du fichier compose.",
    "voyage": "# Voyage à Lisbonne\nVol aller le 12 mai depuis Lyon, hôtel près du quartier de l'Alfama, trois nuits réservées, visite du château Saint-Georges.",
    "recette": "# Recette de la ratatouille\nCouper les courgettes, aubergines et poivrons en dés, les faire revenir séparément dans l'huile d'olive puis mijoter quarante minutes.",
    "backup_en": "# Router settings\nThe router admin page is on 192.168.1.1; the Wi-Fi password was changed in January and the guest network is disabled.",
    "guitare": "# Guitare\nJe joue une Telecaster accordée en ré standard ; les cordes sont changées tous les deux mois, calibre dix.",
    "code": "# Revue de code\nLes fonctions de plus de cinquante lignes doivent être découpées ; les tests unitaires sont obligatoires avant la fusion de la branche.",
    "vpn": "# Accès distant\nLe tunnel WireGuard relie le mini-PC au téléphone ; le port 51820 en UDP est ouvert sur la box.",
    "budget": "# Budget vacances\nLe budget total des vacances d'été est fixé à deux mille euros, dont six cents pour le logement.",
}

# (question reformulée, identifiant du passage attendu)
QUESTIONS = [
    ("à quelle heure sont sauvegardées mes bases de données ?", "sauvegarde"),
    ("combien de temps garde-t-on les backups ?", "sauvegarde"),
    ("comment réveiller mon ordinateur de jeu à distance ?", "wol"),
    ("activer le wake on lan dans le bios", "wol"),
    ("quand les chats vont-ils chez le vétérinaire ?", "chats"),
    ("que mange mon chat ?", "chats"),
    ("combien coûte l'électricité en novembre ?", "facture"),
    ("à partir de quand commencent les heures creuses ?", "facture"),
    ("comment le conteneur se relance-t-il tout seul ?", "docker"),
    ("politique de redémarrage du compose", "docker"),
    ("quel jour part l'avion pour Lisbonne ?", "voyage"),
    ("où dormir à Lisbonne ?", "voyage"),
    ("comment cuire les légumes de la ratatouille ?", "recette"),
    ("combien de temps faire mijoter ?", "recette"),
    ("what is the wifi password policy of the router?", "backup_en"),
    ("address of the router admin page", "backup_en"),
    ("quand changer les cordes de ma guitare ?", "guitare"),
    ("accordage de la Telecaster", "guitare"),
    ("quelle taille maximale pour une fonction ?", "code"),
    ("les tests sont-ils obligatoires avant de fusionner ?", "code"),
    ("quel port ouvrir pour le tunnel vpn ?", "vpn"),
    ("wireguard entre le mini pc et le téléphone", "vpn"),
    ("combien d'argent prévu pour les vacances ?", "budget"),
    ("coût du logement pendant les vacances d'été", "budget"),
]


def indexer(corpus=None):
    """Les morceaux du corpus avec leurs comptes de mots, comme rappel.morceaux_fichier les fabrique."""
    morceaux = []
    for ident, texte in (corpus or CORPUS).items():
        for m in recall.decouper(texte, ident):
            m["tf"] = collections.Counter(recall.mots(m["titre"] + " " + m["texte"]))
            m["longueur"] = sum(m["tf"].values()) or 1
            morceaux.append(m)
    df = collections.Counter()
    for m in morceaux:
        df.update(m["tf"].keys())
    return morceaux, df, (sum(m["longueur"] for m in morceaux) / len(morceaux)) or 1.0


def mesurer(corpus=None, questions=None, rang_max=3):
    """{rappel_1, rappel_3, mrr, ratees: [(question, attendu, trouve)]} pour la recherche par mots seule."""
    morceaux, df, moyenne = indexer(corpus)
    questions = questions or QUESTIONS
    premier = trois = 0
    inverse = 0.0
    ratees = []
    for question, attendu in questions:
        termes = set(recall.mots(question))
        classes = recall.noter(morceaux, df, moyenne, len(morceaux), termes, 10, 1) if termes else []
        sources = [c["m"]["source"] for c in classes]
        if sources[:1] == [attendu]:
            premier += 1
        if attendu in sources[:rang_max]:
            trois += 1
        if attendu in sources:
            inverse += 1.0 / (sources.index(attendu) + 1)
        else:
            ratees.append((question, attendu, sources[:1]))
    n = len(questions)
    return {"rappel_1": premier / n, "rappel_3": trois / n, "mrr": inverse / n, "ratees": ratees, "questions": n}


if __name__ == "__main__":
    r = mesurer()
    print("{} questions : rappel@1 {:.0%} · rappel@3 {:.0%} · MRR {:.2f}".format(r["questions"], r["rappel_1"], r["rappel_3"], r["mrr"]))
    for question, attendu, trouve in r["ratees"]:
        print("  manquée : « {} » (attendu : {}, trouvé : {})".format(question, attendu, trouve or "rien"))
