"""La fiche de suivi : bornée, mesurée, supprimée avec la conversation ; « oui » vaut ordre d'exécuter."""
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-suivi-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401
from lutin import suivi  # noqa: E402

ID = "abcd1234"


class Fiche(unittest.TestCase):
    def setUp(self):
        suivi.supprimer(ID)
        self.addCleanup(suivi.supprimer, ID)

    def test_ecrire_lire_et_aller_retour_du_fichier(self):
        suivi.modifier(ID, "objectif", "Finir la saison 1")
        suivi.modifier(ID, "Décisions", "Le héros reste en prison")
        suivi.modifier(ID, "decision", "Narration à la 3e personne")
        s = suivi.lire(ID)
        self.assertEqual(s["objectif"], ["Finir la saison 1"])
        self.assertEqual(len(s["decisions"]), 2)
        texte = suivi.chemin(ID).read_text(encoding="utf-8")
        self.assertIn("## Objectif", texte)
        self.assertEqual(suivi.analyser(texte), s, "le fichier relu donne la même fiche (l'utilisateur peut le modifier à la main)")

    def test_remplacer_ajouter_retirer(self):
        suivi.modifier(ID, "plan", "1. Écrire\n2. Relire")
        suivi.modifier(ID, "plan", "1. Écrire\n2. Relire\n3. Publier")
        self.assertEqual(len(suivi.lire(ID)["plan"]), 3, "le plan se remplace en entier")
        suivi.modifier(ID, "fait", "Chapitre 1")
        suivi.modifier(ID, "fait", "Chapitre 2")
        self.assertEqual(len(suivi.lire(ID)["fait"]), 2, "« fait » s'ajoute")
        suivi.modifier(ID, "fait", "chapitre 1", "retirer")
        self.assertEqual(suivi.lire(ID)["fait"], ["Chapitre 2"])
        with self.assertRaises(_m.ErreurOutil):
            suivi.modifier(ID, "nimporte", "x")
        with self.assertRaises(_m.ErreurOutil):
            suivi.modifier(ID, "fait", "")
        with self.assertRaises(_m.ErreurOutil):
            suivi.modifier(ID, "fait", "x", "bizarre")

    def test_la_fiche_ne_grossit_pas_sans_fin(self):
        for i in range(200):
            suivi.modifier(ID, "fait", "étape numéro {} ".format(i) + "x" * 600)
        s = suivi.lire(ID)
        self.assertLessEqual(len(s["fait"]), suivi.LIGNES_MAX["fait"])
        self.assertTrue(all(len(ligne) <= suivi.LIGNE_MAX for ligne in s["fait"]))
        self.assertIn("199", s["fait"][-1], "on garde les plus récentes")
        for i in range(100):
            suivi.apres_tour(ID, "demande {} ".format(i) + "y" * 500, "réponse " + "z" * 500, ["src/f{}.py".format(i)])
        s = suivi.lire(ID)
        self.assertLessEqual(len(s["demandes"]), suivi.LIGNES_MAX["demandes"])
        self.assertLessEqual(len(s["fichiers"]), suivi.LIGNES_MAX["fichiers"])

    def test_le_texte_donne_au_modele_respecte_la_part_du_contexte(self):
        for cle in ("decisions", "fait", "ouvert", "fichiers"):
            for i in range(30):
                suivi.modifier(ID, cle, "{} ligne {} ".format(cle, i) + "mot " * 40)
        suivi.modifier(ID, "objectif", "Mon objectif principal")
        suivi.modifier(ID, "etape", "Étape en cours importante")
        for num_ctx in (4096, 24576):
            texte = suivi.texte_pour_modele(ID, num_ctx)
            self.assertLessEqual(len(texte), suivi.budget_caracteres(num_ctx) + 400)
            self.assertIn("Mon objectif principal", texte, "l'objectif survit toujours")
            self.assertIn("Étape en cours importante", texte)
            self.assertTrue(texte.startswith("[Fiche de suivi]"))

    def test_mesure_et_avertissement(self):
        self.assertEqual(suivi.mesure(ID, 24576)["niveau"], "vide")
        suivi.modifier(ID, "objectif", "court")
        m = suivi.mesure(ID, 24576)
        self.assertEqual(m["niveau"], "ok")
        self.assertGreater(m["jetons"], 0)
        for cle in ("decisions", "fait", "ouvert", "fichiers", "plan"):
            for i in range(30):
                suivi.modifier(ID, cle, "{} {} ".format(cle, i) + "mot " * 40)
        gros = suivi.mesure(ID, 4096)
        self.assertEqual(gros["niveau"], "attention")
        self.assertIn("ralentit", gros["avertissement"])

    def test_identifiant_invalide_refuse(self):
        for mauvais in ("../x", "a/b", "", "a", "x" * 80):
            with self.assertRaises(ValueError):
                suivi.chemin(mauvais)

    def test_orphelins_nettoyes_et_suppression(self):
        suivi.modifier(ID, "objectif", "x")
        suivi.modifier("zzzz9999", "objectif", "y")
        self.assertEqual(suivi.nettoyer_orphelins({ID}), 1)
        self.assertTrue(suivi.chemin(ID).is_file())
        self.assertFalse(suivi.chemin("zzzz9999").exists())
        self.assertTrue(suivi.supprimer(ID))
        self.assertFalse(suivi.supprimer(ID))


class Validation(unittest.TestCase):
    def test_reconnait_les_validations(self):
        for oui in ("oui", "Oui !", "ok vas-y", "On passe à l'action", "d'accord", "go", "yes", "c'est bon, lance", "parfait, fonce"):
            self.assertTrue(suivi.est_confirmation(oui), oui)
        for non in ("non", "oui mais change le titre", "", "Explique-moi le chapitre 3", "oui je veux que tu réécrives tout le premier acte avec plus de suspense"):
            self.assertFalse(suivi.est_confirmation(non), non)

    def test_directive_seulement_s_il_y_a_quelque_chose_a_faire(self):
        conv = {"taches": [{"texte": "Écrire le chapitre 1", "etat": "fait"}, {"texte": "Écrire le chapitre 2", "etat": "en_cours"}]}
        d = suivi.directive_execution(conv, "oui", ID)
        self.assertIn("chapitre 2", d)
        self.assertIn("Ne refais pas le plan", d)
        self.assertEqual(suivi.directive_execution(conv, "explique-moi", ID), "")
        self.assertEqual(suivi.directive_execution({"taches": []}, "oui", ID), "", "rien à exécuter : pas de consigne")
        suivi.modifier(ID, "etape", "Relire l'acte 2")
        try:
            self.assertIn("Relire l'acte 2", suivi.directive_execution({}, "ok", ID), "l'étape de la fiche sert quand il n'y a pas de liste de tâches")
        finally:
            suivi.supprimer(ID)


if __name__ == "__main__":
    unittest.main()
