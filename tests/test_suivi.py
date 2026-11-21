"""La fiche de suivi : bornée, mesurée, supprimée avec la conversation ; « oui » vaut ordre d'exécuter."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-suivi-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import core as _m  # noqa: E402,F401
from lutin import progress_sheet  # noqa: E402

ID = "abcd1234"


class Fiche(unittest.TestCase):
    def setUp(self):
        progress_sheet.delete(ID)
        self.addCleanup(progress_sheet.delete, ID)

    def test_ecrire_lire_et_aller_retour_du_fichier(self):
        progress_sheet.modify(ID, "objectif", "Finir la saison 1")
        progress_sheet.modify(ID, "Décisions", "Le héros reste en prison")
        progress_sheet.modify(ID, "decision", "Narration à la 3e personne")
        s = progress_sheet.read(ID)
        self.assertEqual(s["objectif"], ["Finir la saison 1"])
        self.assertEqual(len(s["decisions"]), 2)
        texte = progress_sheet.path(ID).read_text(encoding="utf-8")
        self.assertIn("## Objectif", texte)
        self.assertEqual(progress_sheet.parse(texte), s, "le fichier relu donne la même fiche (l'utilisateur peut le modifier à la main)")

    def test_remplacer_ajouter_retirer(self):
        progress_sheet.modify(ID, "plan", "1. Écrire\n2. Relire")
        progress_sheet.modify(ID, "plan", "1. Écrire\n2. Relire\n3. Publier")
        self.assertEqual(len(progress_sheet.read(ID)["plan"]), 3, "le plan se remplace en entier")
        progress_sheet.modify(ID, "fait", "Chapitre 1")
        progress_sheet.modify(ID, "fait", "Chapitre 2")
        self.assertEqual(len(progress_sheet.read(ID)["fait"]), 2, "« fait » s'ajoute")
        progress_sheet.modify(ID, "fait", "chapitre 1", "retirer")
        self.assertEqual(progress_sheet.read(ID)["fait"], ["Chapitre 2"])
        with self.assertRaises(_m.ErreurOutil):
            progress_sheet.modify(ID, "nimporte", "x")
        with self.assertRaises(_m.ErreurOutil):
            progress_sheet.modify(ID, "fait", "")
        with self.assertRaises(_m.ErreurOutil):
            progress_sheet.modify(ID, "fait", "x", "bizarre")

    def test_la_fiche_ne_grossit_pas_sans_fin(self):
        for i in range(200):
            progress_sheet.modify(ID, "fait", "étape numéro {} ".format(i) + "x" * 600)
        s = progress_sheet.read(ID)
        self.assertLessEqual(len(s["fait"]), progress_sheet.MAX_LINES["fait"])
        self.assertTrue(all(len(ligne) <= progress_sheet.MAX_LINE for ligne in s["fait"]))
        self.assertIn("199", s["fait"][-1], "on garde les plus récentes")
        for i in range(100):
            progress_sheet.after_turn(ID, "demande {} ".format(i) + "y" * 500, "réponse " + "z" * 500, ["src/f{}.py".format(i)])
        s = progress_sheet.read(ID)
        self.assertLessEqual(len(s["demandes"]), progress_sheet.MAX_LINES["demandes"])
        self.assertLessEqual(len(s["fichiers"]), progress_sheet.MAX_LINES["fichiers"])

    def test_le_texte_donne_au_modele_respecte_la_part_du_contexte(self):
        for cle in ("decisions", "fait", "ouvert", "fichiers"):
            for i in range(30):
                progress_sheet.modify(ID, cle, "{} ligne {} ".format(cle, i) + "mot " * 40)
        progress_sheet.modify(ID, "objectif", "Mon objectif principal")
        progress_sheet.modify(ID, "etape", "Étape en cours importante")
        for num_ctx in (4096, 24576):
            texte = progress_sheet.text_for_model(ID, num_ctx)
            self.assertLessEqual(len(texte), progress_sheet.budget_caracteres(num_ctx) + 400)
            self.assertIn("Mon objectif principal", texte, "l'objectif survit toujours")
            self.assertIn("Étape en cours importante", texte)
            self.assertTrue(texte.startswith("[Fiche de suivi]"))

    def test_mesure_et_avertissement(self):
        self.assertEqual(progress_sheet.measure(ID, 24576)["niveau"], "vide")
        progress_sheet.modify(ID, "objectif", "court")
        m = progress_sheet.measure(ID, 24576)
        self.assertEqual(m["niveau"], "ok")
        self.assertGreater(m["jetons"], 0)
        for cle in ("decisions", "fait", "ouvert", "fichiers", "plan"):
            for i in range(30):
                progress_sheet.modify(ID, cle, "{} {} ".format(cle, i) + "mot " * 40)
        gros = progress_sheet.measure(ID, 4096)
        self.assertEqual(gros["niveau"], "attention")
        self.assertIn("ralentit", gros["avertissement"])

    def test_identifiant_invalide_refuse(self):
        for mauvais in ("../x", "a/b", "", "a", "x" * 80):
            with self.assertRaises(ValueError):
                progress_sheet.path(mauvais)

    def test_orphelins_nettoyes_et_suppression(self):
        progress_sheet.modify(ID, "objectif", "x")
        progress_sheet.modify("zzzz9999", "objectif", "y")
        self.assertEqual(progress_sheet.clean_orphans({ID}), 1)
        self.assertTrue(progress_sheet.path(ID).is_file())
        self.assertFalse(progress_sheet.path("zzzz9999").exists())
        self.assertTrue(progress_sheet.delete(ID))
        self.assertFalse(progress_sheet.delete(ID))


class Validation(unittest.TestCase):
    def test_reconnait_les_validations(self):
        for oui in ("oui", "Oui !", "ok vas-y", "On passe à l'action", "d'accord", "go", "yes", "c'est bon, lance", "parfait, fonce"):
            self.assertTrue(progress_sheet.is_confirmation(oui), oui)
        for non in ("non", "oui mais change le titre", "", "Explique-moi le chapitre 3", "oui je veux que tu réécrives tout le premier acte avec plus de suspense"):
            self.assertFalse(progress_sheet.is_confirmation(non), non)

    def test_directive_seulement_s_il_y_a_quelque_chose_a_faire(self):
        conv = {"taches": [{"texte": "Écrire le chapitre 1", "etat": "fait"}, {"texte": "Écrire le chapitre 2", "etat": "en_cours"}]}
        d = progress_sheet.execution_directive(conv, "oui", ID)
        self.assertIn("chapitre 2", d)
        self.assertIn("Ne refais pas le plan", d)
        self.assertEqual(progress_sheet.execution_directive(conv, "explique-moi", ID), "")
        self.assertEqual(progress_sheet.execution_directive({"taches": []}, "oui", ID), "", "rien à exécuter : pas de consigne")
        progress_sheet.modify(ID, "etape", "Relire l'acte 2")
        try:
            self.assertIn("Relire l'acte 2", progress_sheet.execution_directive({}, "ok", ID), "l'étape de la fiche sert quand il n'y a pas de liste de tâches")
        finally:
            progress_sheet.delete(ID)


class PartDuContexte(unittest.TestCase):
    """La part de la fenêtre de contexte que la fiche peut prendre se règle (5 à 25 %, 10 par défaut)."""

    def tearDown(self):
        _m.enregistrer_reglages({"fiche_part": 10})
        progress_sheet.delete(ID)

    def test_le_plafond_suit_le_reglage_et_reste_borne(self):
        self.assertEqual(_m.reglages()["fiche_part"], 10)
        self.assertEqual(progress_sheet.budget_caracteres(16384), int(16384 * 0.10 * 3))
        _m.enregistrer_reglages({"fiche_part": 25})
        self.assertEqual(progress_sheet.budget_caracteres(16384), int(16384 * 0.25 * 3), "25 % : la fiche peut garder plus de détails")
        _m.enregistrer_reglages({"fiche_part": 400})
        self.assertEqual(_m.reglages()["fiche_part"], 25, "borné à 25 %")
        _m.enregistrer_reglages({"fiche_part": 1})
        self.assertEqual(_m.reglages()["fiche_part"], 5, "borné à 5 %")
        _m.enregistrer_reglages({"fiche_part": "n'importe quoi"})
        self.assertEqual(_m.reglages()["fiche_part"], 10, "valeur absurde : retour à 10 %")

    def test_la_fiche_garde_plus_de_lignes_avec_un_plafond_plus_haut_et_l_avertissement_suit(self):
        for i in range(25):
            progress_sheet.modify(ID, "decisions", "Décision numéro %d : " % i + "détail " * 25)
        petit = progress_sheet.text_for_model(ID, 4096)
        _m.enregistrer_reglages({"fiche_part": 25})
        grand = progress_sheet.text_for_model(ID, 4096)
        self.assertGreater(len(grand), len(petit), "plus de place : plus de la fiche passe au modèle")
        self.assertLessEqual(len(grand), int(4096 * 0.25 * 3) + 400)
        m = progress_sheet.measure(ID, 4096)
        self.assertEqual(m["niveau"], "attention", "la fiche pèse beaucoup pour un petit contexte")
        self.assertIn("25 %", m["avertissement"], "l'avertissement cite le plafond réglé")


class Scribe(unittest.TestCase):
    """Le scribe met la fiche à jour par un appel séparé ; ses consignes sont contrôlées."""

    def setUp(self):
        from lutin import agent
        self.dialogue = agent
        progress_sheet.delete(ID)
        self.addCleanup(progress_sheet.delete, ID)
        self.vrai = agent.ollama_json
        self.addCleanup(setattr, agent, "ollama_json", self.vrai)
        self.conv = {"id": ID, "messages": [{"role": "user" if i % 2 == 0 else "assistant", "content": "message %d sur le budget" % i} for i in range(8)]}

    def avec(self, reponse):
        appels = []

        def faux(chemin, corps=None, delai=8):
            appels.append(corps)
            if isinstance(reponse, Exception):
                raise reponse
            return {"message": {"content": reponse}}
        self.dialogue.ollama_json = faux
        return appels

    def test_remplit_remplace_ajoute_sans_doublon_et_retire_les_questions_resolues(self):
        progress_sheet.modify(ID, "ouvert", "Quel budget pour la salle ?")
        progress_sheet.modify(ID, "decisions", "Budget plafonné à 500 euros")
        appels = self.avec(json_ops(objectif=["Organiser la fête"], etape=["Réserver la salle"], decisions=["budget plafonné à 500 euros", "Salle réservée au 12 mai"], fait=["Devis reçu"], resolu=["Quel budget pour la salle ?"]))
        n = self.dialogue.scribe(self.conv, {"modele": "m", "num_ctx": 8192, "temperature": 0.2})
        s = progress_sheet.read(ID)
        self.assertEqual((s["objectif"], s["etape"], s["fait"]), (["Organiser la fête"], ["Réserver la salle"], ["Devis reçu"]))
        self.assertEqual(s["decisions"], ["Budget plafonné à 500 euros", "Salle réservée au 12 mai"], "la décision déjà présente n'est pas dupliquée")
        self.assertEqual(s["ouvert"], [], "la question résolue (recopiée telle quelle) est retirée")
        self.assertGreater(n, 0)
        self.assertEqual(self.conv["scribe_a"], 8)
        self.assertEqual(appels[0]["format"], self.dialogue.SCHEMA_SCRIBE, "Ollama contraint la sortie : le scribe envoie son schéma (ADR 0019, décision 4)")
        self.assertIn("FICHE ACTUELLE", appels[0]["messages"][1]["content"])
        self.assertEqual(self.dialogue.scribe(self.conv, {"modele": "m", "num_ctx": 8192, "temperature": 0.2}), 0, "rien de nouveau depuis : aucun appel")
        self.assertEqual(len(appels), 1)

    def test_le_schema_du_scribe_suit_le_moteur_et_retombe_sur_du_json_libre(self):
        """ADR 0019, décision 4 : la réponse du scribe est contrainte par un schéma quand le moteur le sait (Ollama « format », llama.cpp par
        response_format) ; un moteur qui refuse le schéma reçoit du JSON libre au second essai, et un moteur qui ne dit rien de lui le reçoit d'emblée."""
        import urllib.error
        from unittest import mock
        from lutin import engines, openai_engine
        schema = self.dialogue.SCHEMA_SCRIBE
        self.assertEqual(set(schema["required"]), set(schema["properties"]), "chaque clé est demandée : une liste vide plutôt qu'une clé oubliée")
        self.assertTrue({"objectif", "plan", "etape", "decisions", "fait", "ouvert", "resolu"} <= set(schema["properties"]))
        refus = []

        def faux(chemin, corps=None, delai=8):
            refus.append(corps["format"])
            if isinstance(corps["format"], dict):
                raise urllib.error.HTTPError("http://x/api/chat", 400, "invalid format", {}, None)
            return {"message": {"content": json_ops(etape=["Choisir la salle"])}}
        self.dialogue.ollama_json = faux
        self.dialogue.scribe(self.conv, {"modele": "m", "num_ctx": 8192, "temperature": 0.2})
        self.assertEqual(refus, [schema, "json"], "le schéma refusé, puis du JSON libre")
        self.assertEqual(progress_sheet.read(ID)["etape"], ["Choisir la salle"], "la réponse du second essai est gardée")

        class SansAptitudes(engines.Moteur):
            id = "inconnu"

            def __init__(self):
                self.corps = []

            def chat(self, corps, delai=60):
                self.corps.append(corps)
                return {"message": {"content": "{}"}}
        moteur = SansAptitudes()
        with mock.patch.object(self.dialogue, "moteur_actuel", lambda r: moteur):
            self.dialogue._scribe_appel({"modele": "m", "num_ctx": 8192, "temperature": 0.2}, ID, "[moi] bonjour")
        self.assertEqual(moteur.corps[0]["format"], "json", "un moteur qui ne dit pas savoir contraindre sa sortie : du JSON libre")
        sortie = openai_engine.vers_openai({"model": "m", "messages": [], "format": schema, "stream": False})
        self.assertEqual(sortie["response_format"], {"type": "json_schema", "json_schema": {"name": "reponse", "schema": schema}}, "llama-server reçoit le schéma sous la forme d'OpenAI")
        self.assertEqual(openai_engine.vers_openai({"model": "m", "messages": [], "format": "json", "stream": False})["response_format"], {"type": "json_object"})

    def test_un_long_plan_ne_chasse_pas_l_etape_ni_les_premieres_decisions(self):
        """Une petite fenêtre (4 096 jetons) : le plan est raccourci par sa fin, l'étape en cours et les questions ouvertes restent ; au-delà du plafond de
        décisions, les premières (celles qui fondent le projet) restent avec les plus récentes."""
        for i in range(20):
            progress_sheet.modify(ID, "plan", "étape de plan numéro {} ".format(i) + "mot " * 50, "ajouter")
        for i in range(40):
            progress_sheet.modify(ID, "decisions", "décision {} ".format(i) + "mot " * 30)
        progress_sheet.modify(ID, "objectif", "Réécrire la facturation")
        progress_sheet.modify(ID, "etape", "Écrire les tests de la TVA")
        progress_sheet.modify(ID, "ouvert", "Quel taux pour les DOM ?")
        decisions = progress_sheet.read(ID)["decisions"]
        self.assertEqual(len(decisions), progress_sheet.MAX_LINES["decisions"])
        self.assertTrue(decisions[0].startswith("décision 0 ") and decisions[-1].startswith("décision 39 "), "les premières et les plus récentes")
        texte = progress_sheet.text_for_model(ID, 4096)
        for attendu in ("Réécrire la facturation", "Écrire les tests de la TVA", "Quel taux pour les DOM ?", "décision 0 ", "décision 39 ", "étape de plan numéro 0 "):
            self.assertIn(attendu, texte)
        self.assertNotIn("étape de plan numéro 19 ", texte, "la fin du plan part d'abord")
        self.assertLess(texte.index("Écrire les tests de la TVA"), texte.index("étape de plan numéro 0 "), "l'étape avant le plan")

    def test_une_decision_n_est_jamais_retiree_et_les_excès_sont_bornes(self):
        progress_sheet.modify(ID, "decisions", "Ne jamais toucher à la production")
        self.avec(json_ops(decisions=["décision %d" % i for i in range(30)], resolu=["Ne jamais toucher à la production"], ouvert=["x" * 5000]))
        self.dialogue.scribe(self.conv, {"modele": "m", "num_ctx": 8192, "temperature": 0.2})
        s = progress_sheet.read(ID)
        self.assertIn("Ne jamais toucher à la production", s["decisions"], "le scribe ne supprime jamais une décision")
        self.assertEqual(len(s["decisions"]), 1 + self.dialogue.SCRIBE_AJOUTS_MAX, "au plus quatre lignes ajoutées par passage")
        self.assertLessEqual(max(len(x) for x in s["ouvert"]), progress_sheet.MAX_LINE)

    def test_reponse_absurde_ou_panne_ne_cassent_rien(self):
        for reponse in ("pas du json", "[1, 2]", "null", '{"decisions": 5, "etape": {"a": 1}}', ValueError("boum"), OSError("réseau")):
            self.conv.pop("scribe_a", None)
            self.avec(reponse)
            self.dialogue.scribe(self.conv, {"modele": "m", "num_ctx": 8192, "temperature": 0.2})
        self.assertEqual(progress_sheet.read(ID)["objectif"], [])
        self.conv["messages"] = self.conv["messages"][:3]
        self.conv.pop("scribe_a", None)
        appels = self.avec("{}")
        self.assertEqual(self.dialogue.scribe(self.conv, {"modele": "m", "num_ctx": 8192, "temperature": 0.2}), 0)
        self.assertEqual(appels, [], "pas assez de nouveaux messages : pas d'appel")

    def test_retrait_demande_lit_meme_peu_de_messages_et_les_garde_si_la_fiche_echoue(self):
        """/compact en mode fiche : la fiche lit TOUT ce qui va sortir, même moins de six messages ; si elle n'y arrive pas, rien n'est retiré."""
        r = {"modele": "m", "num_ctx": 8192, "temperature": 0.2, "fiche_scribe": True}
        self.conv["messages"] = self.conv["messages"][:5]          # cinq messages jamais lus : sous le seuil du passage normal
        appels = self.avec(json_ops(decisions=["Budget fixé"]))
        self.assertEqual(self.dialogue.scribe(self.conv, r), 0, "passage normal : trop peu de messages")
        self.assertEqual(appels, [])
        self.conv["messages"] += [{"role": "user", "content": "dernière question"}, {"role": "assistant", "content": "dernière réponse"}]
        self.avec(OSError("modèle absent"))
        avant = list(self.conv["messages"])
        with self.assertRaises(ValueError):
            self.dialogue.elaguer(self.conv, r, lambda e: None, forcer=True)
        self.assertEqual(self.conv["messages"], avant, "la fiche n'a rien lu : rien n'est retiré")
        appels = self.avec(json_ops(decisions=["Budget fixé"]))
        self.assertTrue(self.dialogue.elaguer(self.conv, r, lambda e: None, forcer=True))
        self.assertIn("Budget fixé", progress_sheet.read(ID)["decisions"], "ce qui sort est passé dans la fiche")
        self.assertEqual(self.conv["messages"][-1]["content"], "dernière réponse")

    def test_beaucoup_de_messages_sont_lus_par_lots_sans_rien_sauter(self):
        self.conv["messages"] = [{"role": "user" if i % 2 == 0 else "assistant", "content": ("mot%d " % i) * 150} for i in range(30)]
        appels = self.avec(json_ops(fait=["x"]))
        self.dialogue.scribe(self.conv, {"modele": "m", "num_ctx": 8192, "temperature": 0.2}, forcer=True)
        lus = " ".join(a["messages"][1]["content"] for a in appels)
        self.assertGreater(len(appels), 1, "plusieurs lots")
        self.assertIn("mot0 ", lus)
        self.assertIn("mot29 ", lus, "le début ET la fin sont lus")
        reste = self.dialogue.messages_non_lus(self.conv)
        self.assertEqual(len(reste), 30 - self.conv["scribe_a"] if self.conv["scribe_a"] < 30 else 0)


def json_ops(**kw):
    import json
    return json.dumps(kw)


class RappelDuFil(unittest.TestCase):
    """Les passages anciens de la conversation en cours sont retrouvés sans que le modèle les demande."""

    def setUp(self):
        self.ident = "f1e2d3c4"
        self.addCleanup(lambda: _m.conv_chemin(self.ident).unlink(missing_ok=True))
        self.addCleanup(lambda: __import__("lutin.recall", fromlist=["FIL"]).THREAD.clear())

    def conv(self, messages):
        c = {"id": self.ident, "titre": "t", "messages": messages}
        _m.conv_ecrire(dict(c, date="2026-01-01T00:00:00.000", maj="2026-01-01T00:00:00.000", resume="", travail="principal", taches=[]))
        return c

    def test_retrouve_un_detail_ancien_et_ignore_ce_qui_est_deja_sous_les_yeux(self):
        from lutin import recall
        anciens = [{"role": "user" if i % 2 == 0 else "assistant", "content": ("Le code du coffre est 4711-ZEBRE. " if i == 0 else "") + "blabla de remplissage numéro %d " % i * 3} for i in range(14)]
        c = self.conv(anciens)
        c["messages"] = anciens + [{"role": "user", "content": "Rappelle-moi le code du coffre ZEBRE s'il te plaît ?"}]
        texte, n = recall.thread_recall(c)
        self.assertEqual(n, 1)
        self.assertIn("4711-ZEBRE", texte)
        self.assertTrue(texte.startswith("[Extraits de la conversation]"))
        # le même passage encore dans les six derniers messages : il est déjà sous les yeux du modèle
        recents = [{"role": "user", "content": "Le code du coffre est 4711-ZEBRE, noté."}, {"role": "assistant", "content": "ok"}]
        c2 = self.conv(recents)
        c2["messages"] = recents + [{"role": "user", "content": "Rappelle-moi le code du coffre ZEBRE s'il te plaît ?"}]
        self.assertEqual(recall.thread_recall(c2), ("", 0))

    def test_un_oui_est_complete_par_la_derniere_reponse_et_l_etape(self):
        from lutin import recall
        msgs = [{"role": "user", "content": "Le tarif du traiteur est de 35 euros par personne, c'est acté."}, {"role": "assistant", "content": "Noté."}]
        msgs += [{"role": "user" if i % 2 == 0 else "assistant", "content": "autre sujet sans rapport %d et encore des mots" % i} for i in range(10)]
        c = self.conv(msgs)
        c["messages"] = msgs + [{"role": "assistant", "content": "On passe au traiteur ?"}, {"role": "user", "content": "oui"}]
        texte, n = recall.thread_recall(c, "Contacter le traiteur")
        self.assertEqual(n, 1)
        self.assertIn("35 euros", texte, "« oui » seul ne dit rien : la question précédente et l'étape en cours guident la recherche")

    def test_le_rappel_sait_ce_que_la_requete_envoie_vraiment(self):
        """ADR 0018 : le rappel supposait que les six derniers messages étaient sous les yeux du modèle, et eux seuls. Sur une grande fenêtre, toute la
        conversation part au modèle : remettre un passage qu'il voit déjà prend de la place pour rien. Sur une petite, l'ajustement retire bien plus
        que le début : ce qu'il retire est cherché en premier."""
        from lutin import agent, recall
        msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": ("Le code du coffre est 4711-ZEBRE. " if i == 2 else "") + "blabla de remplissage numéro %d " % i * 40} for i in range(20)]
        c = self.conv(msgs)
        c["messages"] = msgs + [{"role": "user", "content": "Rappelle-moi le code du coffre ZEBRE s'il te plaît ?"}]
        self.assertEqual(recall.thread_recall(c)[1], 1, "sans savoir ce qui part : le message 3 sur 21 est hors des six derniers, il est remis")
        grand = dict(_m.reglages(), num_ctx=131072)
        outils = agent.outils_du_mode(grand)
        vus = agent.ce_que_voit_le_modele(c, grand, outils)
        self.assertTrue(any("4711-ZEBRE" in (m.get("content") or "") for m in vus), "sur 131 072 jetons, toute la conversation part")
        self.assertEqual(recall.thread_recall(c, "", 1800, vus), ("", 0), "le modèle le voit déjà : rien n'est remis")
        petit = dict(_m.reglages(), num_ctx=4096)
        vus = agent.ce_que_voit_le_modele(c, petit, agent.outils_du_mode(petit))
        self.assertFalse(any("4711-ZEBRE" in (m.get("content") or "") for m in vus), "sur 4 096 jetons, l'ajustement le retire")
        texte, n = recall.thread_recall(c, "", 1800, vus)
        self.assertEqual(n, 1)
        self.assertIn("4711-ZEBRE", texte)

    def test_le_rappel_cherche_d_abord_ce_que_l_ajustement_vient_de_retirer(self):
        from lutin import archive, recall
        self.addCleanup(lambda: archive.remove(self.ident))
        archive.add(self.ident, [{"role": "user", "content": "Au tout début : le code du coffre ZEBRE est 1111 (code du coffre ZEBRE : 1111). " + "début archivé " * 30}])
        msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": ("Plus tard : le coffre rouge ZEBRE, 2222. " if i == 1 else "") + "suite de la conversation %d " % i * 30} for i in range(10)]
        c = self.conv(msgs)
        c["messages"] = msgs + [{"role": "user", "content": "Quel est le code du coffre ZEBRE déjà ?"}]
        texte, n = recall.thread_recall(c, "", 1800, c["messages"][-2:])
        self.assertEqual(n, 2)
        self.assertIn("1111", recall.thread_passages(self.ident, "Quel est le code du coffre ZEBRE déjà ?", 8, 2)[0]["m"]["texte"], "le classement seul met le début archivé en premier")
        self.assertLess(texte.index("2222"), texte.index("1111"), "le message retiré de la requête passe avant le début archivé")

    def test_conversation_inconnue_ou_vide(self):
        from lutin import recall
        self.assertEqual(recall.thread_recall({"id": "e9d8c7b6", "messages": [{"role": "user", "content": "une longue question sans historique ici"}]}), ("", 0))
        self.assertEqual(recall.thread_recall({"id": "", "messages": []}), ("", 0))

    def test_une_archive_illisible_un_instant_ne_laisse_pas_un_index_incomplet_en_cache(self):
        """Sous Windows, un fichier tenu un instant par un autre programme (antivirus, indexeur) ne se lit pas. L'archive passait alors pour vide, et
        les index du rappel (le fil, la recherche dans les conversations, les résultats d'outils) gardaient cet index incomplet en cache sous la
        signature de la conversation : le début archivé restait introuvable jusqu'à la prochaine modification. Il est relu à l'appel suivant."""
        from lutin import archive, recall
        self.addCleanup(lambda: archive.remove(self.ident))
        self.addCleanup(recall.RESULTS.clear)
        archive.add(self.ident, [{"role": "user", "content": "Au tout début : le mot de passe du routeur est ORCHIDEE-42. " + "début archivé " * 30}])
        archive.add_result(self.ident, "executer", "sortie de la commande : la clé du serveur est PIVOINE-77\n" * 3)
        self.conv([{"role": "user", "content": "Bonjour, on reprend."}, {"role": "assistant", "content": "Salut."}])
        vrai = Path.read_text

        def tenue(chemin, *a, **k):
            if chemin.suffix == ".jsonl":
                raise PermissionError(13, "Access is denied", str(chemin))
            return vrai(chemin, *a, **k)
        question = "mot de passe du routeur ORCHIDEE"
        with mock.patch.object(Path, "read_text", tenue):
            self.assertEqual(recall.thread_passages(self.ident, question, 3), [], "l'archive tenue : rien ce coup-ci")
            self.assertEqual(recall.recall_passages(question, 3, seulement_conv=self.ident), [])
            self.assertEqual(recall.result_passages(self.ident, "clé serveur PIVOINE"), [])
        self.assertIn("ORCHIDEE-42", recall.thread_passages(self.ident, question, 3)[0]["m"]["texte"], "relue à l'appel suivant")
        self.assertIn("ORCHIDEE-42", recall.recall_passages(question, 3, seulement_conv=self.ident)[0]["m"]["texte"], "la recherche dans les conversations aussi")
        self.assertIn("PIVOINE-77", recall.result_passages(self.ident, "clé serveur PIVOINE")[0]["m"]["texte"], "et les résultats d'outils")

    def test_la_demande_precedente_garde_le_sujet_d_une_question_de_suite(self):
        """ADR 0019, décision 6 : « comment s'appelle-t-il déjà ? » ne dit pas de quoi l'on parle ; la demande précédente de la personne, si. Sans elle,
        un seul mot en commun (« appelle ») et rien ne revenait."""
        from lutin import recall
        msgs = [{"role": "user", "content": "Le fichier de configuration de production s'appelle reglages-prod-7.toml, garde-le en tête."}, {"role": "assistant", "content": "Noté."}]
        msgs += [{"role": "user" if i % 2 == 0 else "assistant", "content": "autre sujet sans rapport %d et encore des mots " % i * 6} for i in range(10)]
        msgs += [{"role": "user", "content": "Il faudra renommer le fichier de configuration de production."}, {"role": "assistant", "content": "D'accord, quand tu veux."}]
        c = self.conv(msgs)
        c["messages"] = msgs + [{"role": "user", "content": "Comment s'appelle-t-il exactement déjà ?"}]
        texte, n = recall.thread_recall(c)
        self.assertEqual(n, 1)
        self.assertIn("reglages-prod-7.toml", texte)

    def test_un_passage_proche_mais_faible_n_est_pas_remis(self):
        """ADR 0019, décision 6 : un passage n'est remis que s'il dépasse un seuil de score. Un mot en commun dans un long message sur autre chose
        n'apporte rien au modèle (un passage proche mais faux nuit à la réponse) ; le passage qui répond, lui, revient."""
        from lutin import recall
        msgs = [{"role": "user", "content": "Pour la cuisine, on garde les placards blancs ; au passage le jardin est grand, mais parlons des poignées, du plan de travail en chêne, de l'évier, de la hotte, du carrelage et de la lumière au-dessus de la table. "},
                {"role": "assistant", "content": "Noté pour la cuisine."}]
        msgs += [{"role": "user" if i % 2 == 0 else "assistant", "content": "sujet numéro %d sur les factures, le budget et les devis des artisans " % i * 4} for i in range(36)]          # la taille d'un fil qui déborde
        c = self.conv(msgs)
        c["messages"] = msgs + [{"role": "user", "content": "Merci, c'est clair."}, {"role": "assistant", "content": "Autre chose ?"}, {"role": "user", "content": "et le jardin ?"}]
        self.assertEqual(recall.thread_recall(c), ("", 0), "« jardin » en passant dans un message sur la cuisine : rien n'est remis")
        msgs[0] = {"role": "user", "content": "Le jardin : tondre la pelouse du jardin chaque samedi, tailler la haie du jardin en mars, arroser le potager du jardin le soir."}
        c = self.conv(msgs)
        c["messages"] = msgs + [{"role": "user", "content": "Merci, c'est clair."}, {"role": "assistant", "content": "Autre chose ?"}, {"role": "user", "content": "et le jardin ?"}]
        texte, n = recall.thread_recall(c)
        self.assertEqual(n, 1, "le passage qui parle du jardin revient")
        self.assertIn("haie", texte)

    def test_une_question_sur_l_etat_du_travail_est_laissee_a_la_fiche(self):
        """ADR 0019, décision 6 : « où en est-on ? » se répond par la fiche de suivi ; le rappel par mots-clés (fil et documents) ne cherche pas, il ne
        ramènerait que des passages qui partagent « où » ou « reste ». Une autre question, dans la même conversation, déclenche le rappel."""
        from lutin import agent, recall
        self.addCleanup(progress_sheet.delete, self.ident)
        progress_sheet.modify(self.ident, "etape", "Ouvrir le coffre ZEBRE")
        msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": ("Le code du coffre ZEBRE est 4711, où en est la serrure du coffre ? " if i == 2 else "") + "blabla de remplissage numéro %d " % i * 40} for i in range(20)]
        c = self.conv(msgs)
        r = dict(_m.reglages(), num_ctx=4096, rappel_ici=True, web=False)          # 4 096 : le début n'est plus sous les yeux du modèle
        rappels = []
        with mock.patch.object(_m, "thread_recall", lambda *a, **k: rappels.append(a) or recall.thread_recall(*a, **k)), mock.patch.object(_m, "automatic_recalls", lambda *a, **k: rappels.append(a) or ("", [])):
            c["messages"] = msgs + [{"role": "user", "content": "Où en est-on ?"}]
            p = agent._preparer_boucle(c, r, lambda e: None, {})
            self.assertEqual((p.extraits, rappels), ("", []), "la fiche répond : aucun rappel cherché")
            c["messages"] = msgs + [{"role": "user", "content": "Rappelle-moi le code du coffre ZEBRE"}]
            p = agent._preparer_boucle(c, r, lambda e: None, {})
            self.assertIn("4711", p.extraits, "une autre question : le rappel cherche")
        self.assertTrue(all(progress_sheet.is_state_question(t) for t in ("Où en est-on ?", "On en est où ?", "Fais le point", "qu'est-ce qui reste ?", "Where are we?", "état d'avancement ?")))
        self.assertFalse(any(progress_sheet.is_state_question(t) for t in ("où est le fichier config ?", "corrige l'état du bouton", "oui", "fix the status bar color",
                                                                             "Lis le README et dis-moi où sont les tests, puis fais le point sur ce qui manque dans le dossier docs de ce projet")))


if __name__ == "__main__":
    unittest.main()
