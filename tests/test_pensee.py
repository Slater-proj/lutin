"""La réflexion d'un modèle laissée dans son texte (<think>…</think>) est rendue à part, quel que soit le découpage du flux ; un texte ordinaire n'est jamais touché."""
import random
import unittest

import context  # noqa: F401
from lutin import thinking as P


def decouper(texte, taille):
    return [texte[i:i + taille] for i in range(0, len(texte), taille)]


def lire(morceaux):
    s, sortie = P.Separateur(), []
    for m in morceaux:
        sortie += s.alimenter(m)
    sortie += s.fin()
    pensee = "".join(t for g, t in sortie if g == "pensee")
    texte = "".join(t for g, t in sortie if g == "texte")
    return pensee, texte


class Flux(unittest.TestCase):
    TEXTE = "<think>Je dois d'abord regarder le fichier.\nPuis répondre.</think>\n\nVoici la réponse : **bonjour**."

    def test_la_reflexion_et_la_reponse_sont_separees_pour_tout_decoupage(self):
        for taille in (1, 2, 3, 5, 7, 11, 1000):
            pensee, texte = lire(decouper(self.TEXTE, taille))
            self.assertEqual(pensee, "Je dois d'abord regarder le fichier.\nPuis répondre.", taille)
            self.assertEqual(texte, "Voici la réponse : **bonjour**.", taille)

    def test_un_decoupage_au_hasard_ne_change_rien(self):
        hasard = random.Random(7)
        for _ in range(200):
            morceaux, i = [], 0
            while i < len(self.TEXTE):
                n = hasard.randint(1, 9)
                morceaux.append(self.TEXTE[i:i + n])
                i += n
            self.assertEqual(lire(morceaux), ("Je dois d'abord regarder le fichier.\nPuis répondre.", "Voici la réponse : **bonjour**."))

    def test_la_casse_et_les_autres_balises_sont_reconnues(self):
        self.assertEqual(lire(["<THINK>a</Think>b"]), ("a", "b"))
        self.assertEqual(lire(["<thinking>a</thinking>b"]), ("a", "b"))
        self.assertEqual(lire(["  \n<reasoning>a</reasoning>b"]), ("a", "b"), "des espaces avant la balise ne la cachent pas")

    def test_un_texte_sans_balise_passe_tel_quel_sans_attente_inutile(self):
        s = P.Separateur()
        self.assertEqual(s.alimenter("Bonjour, "), [("texte", "Bonjour, ")])
        self.assertEqual(s.alimenter("<think> au milieu, ce n'est pas une réflexion"), [("texte", "<think> au milieu, ce n'est pas une réflexion")])
        self.assertEqual(s.fin(), [])
        self.assertEqual(lire(["def f():\n    return 1"]), ("", "def f():\n    return 1"))

    def test_un_debut_de_balise_qui_n_en_est_pas_une_est_rendu_a_la_fin(self):
        self.assertEqual(lire(["<thi"]), ("", "<thi"))
        self.assertEqual(lire(["<thi", "s is html"]), ("", "<this is html"))
        self.assertEqual(lire(["<b>gras</b>"]), ("", "<b>gras</b>"))

    def test_une_reflexion_jamais_fermee_reste_une_reflexion(self):
        self.assertEqual(lire(["<think>je réfléchis", " encore"]), ("je réfléchis encore", ""))

    def test_une_balise_fermante_coupee_en_deux_n_apparait_pas_dans_la_reflexion(self):
        self.assertEqual(lire(["<think>idée</thi", "nk>réponse"]), ("idée", "réponse"))
        self.assertEqual(lire(["<think>a < b</think>c"]), ("a < b", "c"))

    def test_la_reponse_vide_apres_la_reflexion_est_vide(self):
        self.assertEqual(lire(["<think>seulement</think>"]), ("seulement", ""))

    def test_separer_un_texte_entier_deja_enregistre(self):
        self.assertEqual(P.separer(self.TEXTE), ("Je dois d'abord regarder le fichier.\nPuis répondre.", "Voici la réponse : **bonjour**."))
        self.assertEqual(P.separer("Bonjour"), ("", "Bonjour"))
        self.assertEqual(P.separer(None), ("", ""))


if __name__ == "__main__":
    unittest.main()
