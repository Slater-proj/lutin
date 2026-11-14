"""Un modèle qui raconte avoir agi sans avoir appelé d'outil est repéré — et pas à tort."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from lutin.false_claims import affirme_sans_agir, oubli_d_ecrire, refus_a_tort  # noqa: E402

TOUS = {"ecrire", "modifier", "modifier_plusieurs", "creer_document", "executer", "web_chercher", "web_lire", "comfy_generer", "memoriser", "lire", "installer_module"}
DEMANDE = [{"role": "user", "content": "fais-le"}]


def appel(nom):
    return DEMANDE + [{"role": "tool", "tool_name": nom, "content": "ok"}]


class Affirmations(unittest.TestCase):
    def test_affirmations_sans_outil_sont_reperees(self):
        for phrase, mot in [("J'ai créé le fichier docker-compose.yml dans le dossier de travail.", "ecrire"),
                            ("Le fichier docker-compose.yml a été créé.", "ecrire"),
                            ("J'ai créé docker-compose.yml pour vous.", "ecrire"),
                            ("J'ai lancé la commande et le service tourne.", "executer"),
                            ("J'ai installé nginx sur la machine.", "executer"),
                            ("J'ai cherché sur internet : la version est la 3.2.", "web_chercher"),
                            ("J'ai généré l'image demandée.", "comfy_generer"),
                            ("J'ai mémorisé ta préférence.", "memoriser")]:
            self.assertTrue(affirme_sans_agir(phrase, DEMANDE, TOUS), phrase)

    def test_pas_de_remarque_si_l_outil_a_ete_appele(self):
        self.assertEqual(affirme_sans_agir("J'ai créé le fichier a.yml.", appel("ecrire"), TOUS), "")
        self.assertEqual(affirme_sans_agir("J'ai lancé la commande.", appel("executer"), TOUS), "")
        self.assertEqual(affirme_sans_agir("J'ai cherché sur internet.", appel("web_lire"), TOUS), "")
        self.assertEqual(affirme_sans_agir("J'ai généré l'image.", appel("comfy_generer"), TOUS), "")
        self.assertEqual(affirme_sans_agir("J'ai mémorisé cela.", appel("memoriser"), TOUS), "")

    def test_un_outil_d_une_demande_precedente_ne_compte_pas(self):
        histoire = appel("ecrire") + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "refais"}]
        self.assertTrue(affirme_sans_agir("J'ai créé le fichier b.yml.", histoire, TOUS))

    def test_pas_de_fausse_alerte(self):
        for phrase in ["Je vais créer le fichier docker-compose.yml.", "Voulez-vous que je crée le fichier ?", "J'ai ajouté une précision à ma réponse.",
                       "Voici le contenu :\n```\n# j'ai créé le fichier a.yml\n```", "Tu peux lancer la commande docker compose up.", "ok"]:
            self.assertEqual(affirme_sans_agir(phrase, DEMANDE, TOUS), "", phrase)

    def test_demande_de_creation_sans_ecriture_est_reperee(self):
        for demande in ["tu peux me créer un docker-compose pour swag avec un fournisseur ovh ?", "écris un script de sauvegarde", "Crée le fichier config.yml", "génère un README"]:
            self.assertTrue(oubli_d_ecrire(demande, appel("web_chercher"), TOUS), demande)
        self.assertEqual(oubli_d_ecrire("crée un docker-compose", appel("ecrire"), TOUS), "", "il a écrit : rien à dire")
        self.assertEqual(oubli_d_ecrire("explique-moi ce docker-compose", DEMANDE, TOUS), "", "une explication n'est pas une création")
        self.assertEqual(oubli_d_ecrire("crée un docker-compose", DEMANDE, {"lire", "lister"}), "", "pas d'outil d'écriture dans ce mode")

    def test_une_realisation_demandee_sans_le_mot_fichier_est_reperee(self):
        for demande in ["fais-moi un démineur en html", "crée un jeu de morpion", "code une calculatrice en python", "développe une page de connexion"]:
            self.assertTrue(oubli_d_ecrire(demande, DEMANDE, TOUS), demande)
        self.assertEqual(oubli_d_ecrire("c'est quoi un démineur ?", DEMANDE, TOUS), "")

    def test_un_refus_a_tort_de_creer_un_fichier_est_repere(self):
        refus = ["Je ne peux pas créer de fichier directement, mais voici le code.", "Désolé, je ne peux pas écrire sur ton disque.", "Je n'ai pas accès au système de fichiers.", "I can't create files directly, but here is the code."]
        for phrase in refus:
            self.assertTrue(refus_a_tort("fais-moi un démineur en html", phrase, DEMANDE, TOUS), phrase)
        self.assertEqual(refus_a_tort("fais-moi un démineur en html", refus[0], appel("ecrire"), TOUS), "", "il a écrit : rien à dire")
        self.assertEqual(refus_a_tort("fais-moi un démineur en html", refus[0], DEMANDE, {"lire", "lister"}), "", "pas d'outil d'écriture dans ce mode : le refus est vrai")
        self.assertEqual(refus_a_tort("explique-moi ce fichier", refus[0], DEMANDE, TOUS), "", "pas une demande de création")
        self.assertEqual(refus_a_tort("fais-moi un démineur en html", "Voici le démineur : je peux le créer si tu veux.", DEMANDE, TOUS), "")

    def test_un_outil_absent_n_est_pas_reclame(self):
        self.assertEqual(affirme_sans_agir("J'ai créé le fichier a.yml.", DEMANDE, {"lire", "lister"}), "", "mode lecture seule : le modèle n'a pas d'outil pour écrire")


if __name__ == "__main__":
    unittest.main()
