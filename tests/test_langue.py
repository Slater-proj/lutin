"""Langue française / anglaise : détection, réglage, traduction, et surtout COMPLÉTUDE (chaque texte du code a sa traduction)."""
import ast
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401
from lutin import catalogue, cli, config, i18n

SRC = Path(__file__).resolve().parent.parent / "src" / "lutin"
VARIABLE = re.compile(r"\{[^{}]*\}")


class Detection(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.config = Path(self.t.name) / "config.json"
        self.env = mock.patch.dict(os.environ, {"LUTIN_CONFIG": str(self.config)})
        self.env.start()
        os.environ.pop("LUTIN_LANGUE", None)

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def avec_systeme(self, **variables):
        env = {k: "" for k in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")}
        env.update(variables)
        return mock.patch.dict(os.environ, env)

    def test_langue_du_systeme(self):
        for valeur, attendu in (("fr_FR.UTF-8", "fr"), ("fr", "fr"), ("FR_CA", "fr"), ("en_US.UTF-8", "en"), ("de_DE", "en"), ("es_ES", "en")):
            with self.avec_systeme(LANG=valeur):
                self.assertEqual(i18n.langue_systeme(), attendu, valeur)

    def test_c_et_posix_ne_disent_rien_on_retombe_sur_le_systeme_reel_sans_planter(self):
        with self.avec_systeme(LANG="C"):
            self.assertIn(i18n.langue_systeme(), ("fr", "en"))
        with self.avec_systeme(LC_ALL="fr_FR.UTF-8", LANG="en_US"):
            self.assertEqual(i18n.langue_systeme(), "fr", "LC_ALL l'emporte sur LANG")

    def test_priorite_variable_puis_configuration_puis_systeme(self):
        with self.avec_systeme(LANG="en_US"):
            self.assertEqual(i18n.langue(), "en")
            self.config.write_text(json.dumps({"langue": "fr"}), encoding="utf-8")
            self.assertEqual(i18n.langue(), "fr", "le réglage l'emporte sur le système")
            with mock.patch.dict(os.environ, {"LUTIN_LANGUE": "en"}):
                self.assertEqual(i18n.langue(), "en", "la variable l'emporte sur le réglage")
            with mock.patch.dict(os.environ, {"LUTIN_LANGUE": "klingon"}):
                self.assertEqual(i18n.langue(), "fr", "une valeur inconnue est ignorée")

    def test_reglage_illisible_ou_invalide(self):
        with self.avec_systeme(LANG="fr_FR"):
            for contenu in ("{pas du json", '{"langue": "xx"}', '{"langue": 5}', "[]"):
                self.config.write_text(contenu, encoding="utf-8")
                self.assertEqual(i18n.langue(), "fr", contenu)

    def test_definir_et_auto(self):
        with self.avec_systeme(LANG="fr_FR"):
            self.config.write_text(json.dumps({"installe": True}), encoding="utf-8")
            self.assertEqual(i18n.definir("en"), "en")
            self.assertEqual(json.loads(self.config.read_text(encoding="utf-8")), {"installe": True, "langue": "en"}, "le reste de la configuration est gardé")
            self.assertEqual(i18n.definir("auto"), "fr", "auto : on suit le système")
            self.assertIsNone(json.loads(self.config.read_text(encoding="utf-8"))["langue"])
            with self.assertRaises(ValueError):
                i18n.definir("klingon")


class Traduction(unittest.TestCase):
    def en(self):
        return mock.patch.dict(os.environ, {"LUTIN_LANGUE": "en"})

    def test_le_francais_passe_tel_quel(self):
        self.assertEqual(i18n.t("Rien n'a été changé."), "Rien n'a été changé.")
        self.assertEqual(i18n.traduire("Lutin est déjà à jour (1.0)."), "Lutin est déjà à jour (1.0).")

    def test_traduction_exacte_et_repli_francais(self):
        with self.en():
            self.assertEqual(i18n.t("Rien n'a été changé."), "Nothing was changed.")
            self.assertEqual(i18n.t("Un texte que personne n'a traduit."), "Un texte que personne n'a traduit.", "sans traduction : le français, jamais d'erreur")

    def test_gabarit_reconnu_dans_un_message_deja_formate(self):
        with self.en():
            self.assertEqual(i18n.traduire("Lutin est déjà à jour (1.2.3)."), "Lutin is already up to date (1.2.3).")
            self.assertEqual(i18n.traduire("Mode hors ligne strict : impossible de télécharger un modèle. Désactive-le pour continuer (lutin hors-ligne non)."),
                             "Strict offline mode: unable to download a model. Turn it off to continue (lutin hors-ligne non).")
            self.assertEqual(i18n.traduire("Une phrase que personne n'a prévue (3)."), "Une phrase que personne n'a prévue (3).", "sans gabarit : inchangé")

    def test_formats_numeriques_du_gabarit_ne_cassent_pas(self):
        with self.en():
            self.assertEqual(i18n.traduire("\nÀ télécharger : 18.5 Go (qwen3.8:27b). Espace libre : 400.0 Go."), "\nTo download: 18.5 GB (qwen3.8:27b). Free space: 400.0 GB.")

    def test_un_texte_quelconque_n_est_jamais_confondu_avec_un_gabarit(self):
        with self.en():
            for texte in ("Bonjour, voici ma réponse de modèle.", "def f(x): return x", "{} libres", "Écrire", "", "x" * 5000):
                self.assertEqual(i18n.traduire(texte), texte)
            self.assertEqual(i18n.traduire(None), None)
            self.assertEqual(i18n.traduire(5), 5)

    def test_traduction_complete_des_messages_du_moteur(self):
        from lutin import moteur as A
        with self.en():
            self.assertEqual(A.traduire_json({"erreur": "Nom de modèle invalide.", "titre": "Ma conversation", "messages": [{"content": "Nom de modèle invalide."}]}),
                             {"erreur": "Invalid model name.", "titre": "Ma conversation", "messages": [{"content": "Nom de modèle invalide."}]}), "le contenu des conversations n'est jamais traduit"
            self.assertEqual(A.traduire_evenement({"type": "info", "texte": "Accord automatique : Modifier docs/a.txt"})["texte"], "Automatic approval: Modify docs/a.txt")
            self.assertEqual(A.traduire_evenement({"type": "texte", "texte": "Nom de modèle invalide."})["texte"], "Nom de modèle invalide.", "le texte du modèle n'est jamais traduit")
            sante = A.evaluer_sante({"ram": {"total": 8 * 1024 ** 3, "libre": 1 * 1024 ** 3, "engagement_libre": 3 * 1024 ** 3}}, A.reglages())
            ram = A.traduire_json(sante)["items"][0]
            self.assertEqual((ram["nom"], ram["valeur"]), ("Memory (RAM)", "1.0 GB free of 8.0 GB"))
        self.assertEqual(A.traduire_json({"erreur": "Nom de modèle invalide."}), {"erreur": "Nom de modèle invalide."}, "en français : rien ne change")


class Completude(unittest.TestCase):
    """La garantie la plus utile : on ne peut plus ajouter un texte en français sans sa traduction."""

    @classmethod
    def setUpClass(cls):
        cls.dico = json.loads((SRC / "langues" / "messages.en.json").read_text(encoding="utf-8"))

    def textes_enveloppes(self):
        sortie = []
        for f in sorted(SRC.glob("*.py")):
            arbre = ast.parse(f.read_text(encoding="utf-8"))
            for n in ast.walk(arbre):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("_t", "t") and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    sortie.append((f.name, n.lineno, n.args[0].value))
        return sortie

    def test_chaque_texte_enveloppe_a_sa_traduction(self):
        manquants = [(f, ligne, t[:70]) for f, ligne, t in self.textes_enveloppes() if t not in self.dico]
        self.assertEqual(manquants, [], "textes passés à _t(...) sans traduction dans langues/messages.en.json")
        self.assertGreater(len(self.textes_enveloppes()), 200)

    def test_les_traductions_gardent_les_variables_et_les_espaces(self):
        for fr, en in self.dico.items():
            self.assertEqual(len(VARIABLE.findall(fr)), len(VARIABLE.findall(en)), fr)
            self.assertEqual((len(fr) - len(fr.lstrip()), len(fr) - len(fr.rstrip())), (len(en) - len(en.lstrip()), len(en) - len(en.rstrip())), repr(fr))
            self.assertTrue(en.strip(), fr)

    def test_le_catalogue_est_entierement_traduit(self):
        for m in catalogue.charger()["modeles"]:
            for champ in ("nom", "phrase", "avertissement"):
                if m.get(champ):
                    self.assertIn(m[champ], self.dico, "{} : {}".format(m["id"], champ))
        for role, (titre, detail) in catalogue.LIBELLES.items():
            self.assertIn(titre, self.dico)
            self.assertIn(detail, self.dico)

    def test_les_constantes_de_niveau_module_sont_traduites(self):
        from lutin import chat_terminal, installation, moteur
        for texte in (cli.AIDE_GENERALE, chat_terminal.AIDE, installation.AVERTISSEMENT_RESEAU, installation.AVERTISSEMENT_PROXY, *moteur.TEXTES_PAGE_CONNEXION):
            self.assertIn(texte, self.dico, texte[:60])
        for _, titre, detail in installation.NIVEAUX_TEXTE.values():
            self.assertIn(titre, self.dico)
            self.assertIn(detail, self.dico)

    def test_pas_de_traduction_orpheline_ni_identique(self):
        identiques = [fr for fr, en in self.dico.items() if fr == en and fr not in ("Code", "Images")]          # deux mots qui s'écrivent pareil dans les deux langues
        self.assertEqual(identiques, [], "une « traduction » identique au français est un oubli")


class QuestionALInstallation(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"LC_ALL": "", "LC_MESSAGES": "", "LANGUAGE": "", "LANG": "fr_FR.UTF-8"})
        self.env.start()
        os.environ.pop("LUTIN_LANGUE", None)
        i18n.forcer(None)

    def tearDown(self):
        i18n.forcer(None)
        self.env.stop()

    def poser(self, reponses, options=None, cfg=None, oui=False):
        from lutin import installation
        cfg = {} if cfg is None else cfg
        sortie = []
        reponses = list(reponses)
        es = installation.Es(entree=lambda invite: (sortie.append(invite), reponses.pop(0))[1], sortie=lambda *a: None, oui=oui)
        installation.choisir_langue(es, options or {}, cfg)
        return cfg, sortie

    def test_le_choix_est_enregistre_et_applique_tout_de_suite(self):
        cfg, invites = self.poser(["2"])
        self.assertEqual(cfg["langue"], "en")
        self.assertEqual(i18n.langue(), "en", "les questions suivantes sont déjà en anglais")
        self.assertIn("[1]", invites[0], "français proposé par défaut sur un système français")

    def test_defaut_selon_le_systeme_et_reponse_vide(self):
        os.environ["LANG"] = "en_GB.UTF-8"
        cfg, invites = self.poser([""])
        self.assertEqual(cfg["langue"], "en")
        self.assertIn("[2]", invites[0])
        i18n.forcer(None)
        os.environ["LANG"] = "fr_FR.UTF-8"
        self.assertEqual(self.poser([""])[0]["langue"], "fr")

    def test_rien_n_est_demande_quand_la_langue_est_deja_fixee(self):
        self.assertEqual(self.poser([], cfg={"langue": "en"})[1], [])
        self.assertEqual(self.poser([], oui=True)[0], {}, "avec --oui : on ne demande rien et on suit le système")
        with mock.patch.dict(os.environ, {"LUTIN_LANGUE": "en"}):
            self.assertEqual(self.poser([])[0], {})
        cfg, invites = self.poser([], options={"langue": "en"})
        self.assertEqual((cfg["langue"], invites), ("en", []))
        self.assertIsNone(self.poser([], options={"langue": "auto"})[0]["langue"])


class LigneDeCommandeEnAnglais(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"LUTIN_HOME": self.t.name, "LUTIN_LANGUE": "en"})
        self.env.start()
        os.environ.pop("LUTIN_CONFIG", None)

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def lancer(self, *argv):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            try:
                code = cli.principal(list(argv))
            except SystemExit as e:
                code = e.code
        return code, sortie.getvalue()

    def test_aide_et_commandes(self):
        code, sortie = self.lancer("--help")
        self.assertEqual(code, 0)
        self.assertIn("a local AI assistant that picks the models that fit your machine", sortie)
        self.assertIn("guided installation", sortie)
        self.assertNotIn("installation guidée", sortie)
        self.assertIn("this machine only", self.lancer("securite")[1])
        self.assertIn("Strict offline mode: off.", self.lancer("hors-ligne")[1])
        self.assertIn("No workspace folder", self.lancer("travaux")[1])
        self.assertIn("No action recorded yet.", self.lancer("journal")[1])

    def test_aucun_texte_francais_dans_les_commandes_courantes(self):
        francais = re.compile(r"[àâçéèêëîïôûùüÿœ]|\b(le|la|les|des|une|pas|pour|dans|avec|sur|ton|tes|est)\b", re.I)
        for argv in (("--help",), ("securite",), ("hors-ligne",), ("travaux",), ("journal",), ("setup", "--help"), ("update", "--help"), ("bench", "--help"), ("sauvegarde", "--help")):
            sortie = self.lancer(*argv)[1]
            reste = [ligne for ligne in sortie.splitlines() if francais.search(ligne) and "« " not in ligne]
            self.assertEqual(reste, [], "texte français dans la sortie de lutin {} en anglais".format(" ".join(argv)))

    def test_la_langue_se_regle_par_la_commande(self):
        os.environ.pop("LUTIN_LANGUE")
        code, sortie = self.lancer("langue", "fr")
        self.assertEqual(code, 0, sortie)
        self.assertIn("Langue : Français", sortie)
        self.assertEqual(config.charger(config.dossiers())["langue"], "fr")
        self.assertIn("cette machine seulement", self.lancer("securite")[1])
        code, sortie = self.lancer("langue", "en")
        self.assertIn("Language: English", sortie)
        self.assertIn("this machine only", self.lancer("securite")[1])
        self.assertIn("English", self.lancer("langue")[1])
        self.assertEqual(self.lancer("langue", "klingon")[0], 2)
        os.environ["LUTIN_LANGUE"] = "fr"
        self.assertIn("LUTIN_LANGUE", self.lancer("langue", "en")[1], "la variable d'environnement l'emporte, et on le dit")


if __name__ == "__main__":
    unittest.main()
