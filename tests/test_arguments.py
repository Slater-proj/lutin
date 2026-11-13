import json
import unittest

import context  # noqa: F401
from lutin import core as M
from lutin.agent import normaliser_arguments as norm


def schema(nom):
    return next(t["function"]["parameters"] for t in M.OUTILS if t["function"]["name"] == nom)


class ArgumentsDOutil(unittest.TestCase):
    def test_objet_et_texte_json(self):
        s = schema("executer")
        self.assertEqual(norm("executer", {"commande": "dir"}, s), {"commande": "dir"})
        self.assertEqual(norm("executer", '{"commande": "dir", "shell": "cmd"}', s), {"commande": "dir", "shell": "cmd"})
        self.assertEqual(norm("executer", None, s), {})
        self.assertEqual(norm("executer", "", s), {})

    def test_commande_nue_avec_egal_n_est_pas_prise_pour_cle_valeur(self):
        """Le bug : « echo a=b » devenait {"echo a": "b"} et la commande arrivait vide."""
        s = schema("executer")
        for commande in ("echo a=b", "set X=1 && echo %X%", "python -c \"print(1)\" > sortie.txt", "git config user.name=Moi", "cmd /c set A=B&echo %A%", "dir | findstr a=b"):
            self.assertEqual(norm("executer", commande, s), {"commande": commande}, commande)

    def test_cle_valeur_reconnu_seulement_si_les_cles_sont_des_parametres(self):
        s = schema("executer")
        self.assertEqual(norm("executer", "commande=dir", s), {"commande": "dir"})
        self.assertEqual(norm("executer", "commande=echo a=b", s), {"commande": "echo a=b"}, "le premier « = » seul sépare la clé")
        self.assertEqual(norm("executer", "commande=dir&shell=powershell", s), {"commande": "dir", "shell": "powershell"})
        self.assertEqual(norm("executer", "commande=dir&pirate=1", s), {"commande": "commande=dir&pirate=1"}, "clé inconnue : c'est du texte")

    def test_json_qui_est_une_chaine_ou_autre_chose_qu_un_objet(self):
        s = schema("executer")
        self.assertEqual(norm("executer", json.dumps("dir /b"), s), {"commande": "dir /b"})
        self.assertEqual(norm("executer", "42", s), {"commande": "42"})
        self.assertEqual(norm("executer", "null", s), {})
        self.assertEqual(norm("executer", ["dir"], s), {})
        self.assertEqual(norm("executer", True, s), {})

    def test_les_autres_outils_a_un_seul_argument(self):
        for nom in ("lire", "lister", "chercher", "memoriser"):
            s = schema(nom)
            requis = s.get("required") or []
            if len(requis) == 1:
                self.assertEqual(norm(nom, "valeur", s), {requis[0]: "valeur"}, nom)
        self.assertEqual(norm("memoriser", "note a=b"), {"note": "note a=b"}, "sans schéma : l'argument principal connu")
        self.assertEqual(norm("inconnu", "texte"), {}, "outil sans argument principal connu : rien d'inventé")

    def test_outil_a_plusieurs_arguments_obligatoires_ne_devine_pas(self):
        s = {"properties": {"chemin": {}, "contenu": {}}, "required": ["chemin", "contenu"]}
        self.assertEqual(norm("ecrire", "juste du texte", s), {})
        self.assertEqual(norm("ecrire", "chemin=a.txt&contenu=x", s), {"chemin": "a.txt", "contenu": "x"})

    def test_noms_voisins_rattaches_seulement_s_ils_sont_declares(self):
        s = schema("executer")
        self.assertEqual(norm("executer", {"command": "dir"}, s), {"commande": "dir"})
        self.assertEqual(norm("executer", '{"cmd": "dir", "shell": "cmd"}', s), {"commande": "dir", "shell": "cmd"})
        self.assertEqual(norm("executer", {"commande": "dir", "cmd": "autre"}, s), {"commande": "dir", "cmd": "autre"}, "ne remplace jamais un vrai paramètre")
        self.assertEqual(norm("executer", {"command": "dir"}), {"command": "dir"}, "sans schéma, rien n'est deviné")
        lire = schema("lire")
        self.assertEqual(norm("lire", {"path": "a.txt", "debut": 3}, lire), {"chemin": "a.txt", "debut": 3})


if __name__ == "__main__":
    unittest.main()
