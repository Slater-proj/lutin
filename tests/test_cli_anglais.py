"""Les commandes de Lutin ont un nom ANGLAIS officiel (lutin workspaces add, --no-models, lutin offline on…) ; les anciens noms français restent acceptés et mènent à la même commande."""
import argparse
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

import context  # noqa: F401
from lutin import cli


def lire(*argv):
    return cli.parseur().parse_args(list(argv))


def valeurs(args):
    """Les valeurs lues, sans le nom tapé de la commande (« restore » ou « restaurer ») : c'est le reste qui doit être identique."""
    return {k: v for k, v in vars(args).items() if k != "commande"}


class NomsOfficiels(unittest.TestCase):
    def test_chaque_commande_anglaise_a_son_ancien_nom_en_alias(self):
        for anglais, francais in cli.ALIAS_COMMANDES.items():
            requis = {"restore": ["f.zip"], "migrate": ["/x"], "import-project": ["/p"]}.get(anglais, [])          # ces commandes demandent un argument
            a, f = lire(anglais, *requis), lire(francais, *requis)
            self.assertEqual(cli.ALIAS_COMMANDES.get(a.commande, a.commande), francais, anglais)
            self.assertEqual(cli.ALIAS_COMMANDES.get(f.commande, f.commande), francais, francais)

    def test_les_commandes_qui_ne_changent_pas(self):
        for nom in ("setup", "serve", "update", "chat", "pin", "doctor", "bench", "colibri", "mcp", "zone"):
            self.assertEqual(lire(nom).commande, nom)

    def test_l_aide_montre_les_noms_anglais_d_abord(self):
        sortie = io.StringIO()
        with redirect_stdout(sortie), self.assertRaises(SystemExit):
            cli.parseur().parse_args(["--help"])
        texte = sortie.getvalue()
        for anglais in ("workspaces", "offline", "models", "backup", "autostart", "engine-trial", "import-project", "migrate"):
            self.assertIn(anglais, texte)
        i = texte.index("models (modeles)")
        self.assertGreater(i, 0, "l'ancien nom reste visible entre parenthèses")


class Actions(unittest.TestCase):
    def test_actions_anglaises_et_francaises_donnent_la_meme_valeur_interne(self):
        paires = [(("workspaces", "add"), ("travaux", "ajouter")), (("workspaces", "list"), ("travaux", "lister")), (("workspaces", "remove"), ("travaux", "retirer")), (("workspaces", "active"), ("travaux", "actif")),
                  (("models", "install"), ("modeles", "installer")), (("models", "update"), ("modeles", "maj")), (("devices", "revoke"), ("appareils", "revoquer")),
                  (("offline", "on"), ("hors-ligne", "oui")), (("offline", "off"), ("hors-ligne", "non")), (("offline", "status"), ("hors-ligne", "etat")),
                  (("colibri", "install"), ("colibri", "installer")), (("colibri", "start"), ("colibri", "demarrer")), (("colibri", "stop"), ("colibri", "arreter")),
                  (("autostart", "remove"), ("demarrage-auto", "retirer")), (("mcp", "allow"), ("mcp", "autoriser")), (("mcp", "refresh"), ("mcp", "actualiser"))]
        for en, fr in paires:
            self.assertEqual(lire(*en).action if en[0] != "offline" else lire(*en).etat, lire(*fr).action if fr[0] != "hors-ligne" else lire(*fr).etat, str(en))

    def test_valeur_inconnue_dit_les_choix_anglais(self):
        erreur = io.StringIO()
        with redirect_stderr(erreur), self.assertRaises(SystemExit):
            lire("workspaces", "supprimer-tout")
        self.assertIn("list,add,remove,active", erreur.getvalue())

    def test_le_niveau_network_est_le_niveau_reseau(self):
        self.assertEqual(lire("setup", "--level", "network").niveau, "reseau")
        self.assertEqual(lire("setup", "--niveau", "reseau").niveau, "reseau")
        self.assertIsNone(lire("setup").niveau)


class Options(unittest.TestCase):
    def test_options_anglaises_et_francaises(self):
        en = lire("setup", "--yes", "--level", "proxy", "--workspace", "/w", "--models-dir", "/m", "--no-models", "--no-ollama", "--listen", "0.0.0.0", "--language", "en", "--reconfigure")
        fr = lire("setup", "--oui", "--niveau", "proxy", "--travail", "/w", "--dossier-modeles", "/m", "--sans-modeles", "--sans-ollama", "--ecoute", "0.0.0.0", "--langue", "en", "--reconfigurer")
        self.assertEqual(vars(en), vars(fr))
        self.assertTrue(en.oui and en.sans_modeles and en.sans_ollama and en.reconfigurer)
        self.assertEqual((en.travail, en.dossier_modeles, en.ecoute, en.langue), ("/w", "/m", "0.0.0.0", "en"))

    def test_serve_update_restore_et_les_autres(self):
        self.assertEqual(valeurs(lire("serve", "--no-browser", "--no-supervisor")), valeurs(lire("serve", "--sans-navigateur", "--sans-superviseur")))
        self.assertEqual(lire("update", "--models").modeles, lire("update", "--modeles").modeles)
        self.assertEqual(lire("update", "--rollback-to", "0.30.0").revenir_a, "0.30.0")
        self.assertEqual(valeurs(lire("restore", "f.zip", "--yes", "--force")), valeurs(lire("restaurer", "f.zip", "--oui", "--forcer")))
        self.assertEqual(valeurs(lire("migrate", "/x", "--all", "--overwrite", "--skills-dir", "/s", "--target", "t")), valeurs(lire("reprendre", "/x", "--tout", "--ecraser", "--dossier-skills", "/s", "--cible", "t")))
        self.assertEqual(valeurs(lire("import-project", "/p", "--copy", "--to", "/c", "--name", "n")), valeurs(lire("importer", "/p", "--copie", "--vers", "/c", "--nom", "n")))
        self.assertEqual(valeurs(lire("engine-trial", "--test-model", "--yes", "--no-tools", "--variant", "cpu", "--folder", "/d")), valeurs(lire("essai-moteur", "--modele-test", "--oui", "--sans-outils", "--variante", "cpu", "--dossier", "/d")))
        self.assertEqual(lire("bench-engines", "--mode", "deep", "--output", "o.json").mode, "approfondi")
        self.assertEqual(lire("models", "--advanced", "--engine", "llamacpp").moteur, "llamacpp")
        self.assertEqual(lire("colibri", "start", "--model", "/m").modele, "/m")
        self.assertEqual(lire("security", "--remote-admin", "on").admin_distance, "on")
        self.assertEqual(lire("bench", "--fast", "--engine", "llamacpp", "--export").exporter, True)

    def test_aucun_nom_francais_n_est_perdu(self):
        """Les anciennes options existent toujours : un script d'avant la 0.35 continue de marcher."""
        for argv in (["setup", "--sans-modeles"], ["serve", "--sans-navigateur"], ["travaux", "ajouter", "/x"], ["hors-ligne", "oui"], ["modeles", "installer", "qwen3:8b"], ["mcp", "ajouter", "n", "cmd"]):
            lire(*argv)


class Dispatch(unittest.TestCase):
    def test_le_nom_anglais_lance_la_meme_commande(self):
        appels = []
        for argv in (["workspaces", "list"], ["travaux", "lister"]):
            args = cli.parseur().parse_args(argv)
            nom = cli.ALIAS_COMMANDES.get(args.commande, args.commande)
            appels.append((nom, args.action))
        self.assertEqual(appels[0], appels[1])
        self.assertEqual(appels[0][0], "travaux")

    def test_aucune_option_en_double(self):
        """argparse refuse deux options identiques : construire le parseur suffit à le vérifier ; on vérifie aussi que l'aide de chaque commande s'affiche."""
        parseur = cli.parseur()
        sous = next(a for a in parseur._actions if isinstance(a, argparse._SubParsersAction))
        for nom, p in sous.choices.items():
            sortie = io.StringIO()
            with redirect_stdout(sortie), self.assertRaises(SystemExit):
                p.parse_args(["--help"])
            self.assertIn("usage:", sortie.getvalue(), nom)


if __name__ == "__main__":
    unittest.main()
