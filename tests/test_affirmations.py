"""Un modèle qui raconte avoir agi sans avoir appelé d'outil est repéré — et pas à tort."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from lutin.affirmations import affirme_sans_agir  # noqa: E402

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

    def test_un_outil_absent_n_est_pas_reclame(self):
        self.assertEqual(affirme_sans_agir("J'ai créé le fichier a.yml.", DEMANDE, {"lire", "lister"}), "", "mode lecture seule : le modèle n'a pas d'outil pour écrire")


if __name__ == "__main__":
    unittest.main()
