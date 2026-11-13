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

from lutin import core as _m  # noqa: E402,F401
from lutin import progress_sheet  # noqa: E402

ID = "abcd1234"


class Fiche(unittest.TestCase):
    def setUp(self):
        progress_sheet.supprimer(ID)
        self.addCleanup(progress_sheet.supprimer, ID)

    def test_ecrire_lire_et_aller_retour_du_fichier(self):
        progress_sheet.modifier(ID, "objectif", "Finir la saison 1")
        progress_sheet.modifier(ID, "Décisions", "Le héros reste en prison")
        progress_sheet.modifier(ID, "decision", "Narration à la 3e personne")
        s = progress_sheet.lire(ID)
        self.assertEqual(s["objectif"], ["Finir la saison 1"])
        self.assertEqual(len(s["decisions"]), 2)
        texte = progress_sheet.chemin(ID).read_text(encoding="utf-8")
        self.assertIn("## Objectif", texte)
        self.assertEqual(progress_sheet.analyser(texte), s, "le fichier relu donne la même fiche (l'utilisateur peut le modifier à la main)")

    def test_remplacer_ajouter_retirer(self):
        progress_sheet.modifier(ID, "plan", "1. Écrire\n2. Relire")
        progress_sheet.modifier(ID, "plan", "1. Écrire\n2. Relire\n3. Publier")
        self.assertEqual(len(progress_sheet.lire(ID)["plan"]), 3, "le plan se remplace en entier")
        progress_sheet.modifier(ID, "fait", "Chapitre 1")
        progress_sheet.modifier(ID, "fait", "Chapitre 2")
        self.assertEqual(len(progress_sheet.lire(ID)["fait"]), 2, "« fait » s'ajoute")
        progress_sheet.modifier(ID, "fait", "chapitre 1", "retirer")
        self.assertEqual(progress_sheet.lire(ID)["fait"], ["Chapitre 2"])
        with self.assertRaises(_m.ErreurOutil):
            progress_sheet.modifier(ID, "nimporte", "x")
        with self.assertRaises(_m.ErreurOutil):
            progress_sheet.modifier(ID, "fait", "")
        with self.assertRaises(_m.ErreurOutil):
            progress_sheet.modifier(ID, "fait", "x", "bizarre")

    def test_la_fiche_ne_grossit_pas_sans_fin(self):
        for i in range(200):
            progress_sheet.modifier(ID, "fait", "étape numéro {} ".format(i) + "x" * 600)
        s = progress_sheet.lire(ID)
        self.assertLessEqual(len(s["fait"]), progress_sheet.LIGNES_MAX["fait"])
        self.assertTrue(all(len(ligne) <= progress_sheet.LIGNE_MAX for ligne in s["fait"]))
        self.assertIn("199", s["fait"][-1], "on garde les plus récentes")
        for i in range(100):
            progress_sheet.apres_tour(ID, "demande {} ".format(i) + "y" * 500, "réponse " + "z" * 500, ["src/f{}.py".format(i)])
        s = progress_sheet.lire(ID)
        self.assertLessEqual(len(s["demandes"]), progress_sheet.LIGNES_MAX["demandes"])
        self.assertLessEqual(len(s["fichiers"]), progress_sheet.LIGNES_MAX["fichiers"])

    def test_le_texte_donne_au_modele_respecte_la_part_du_contexte(self):
        for cle in ("decisions", "fait", "ouvert", "fichiers"):
            for i in range(30):
                progress_sheet.modifier(ID, cle, "{} ligne {} ".format(cle, i) + "mot " * 40)
        progress_sheet.modifier(ID, "objectif", "Mon objectif principal")
        progress_sheet.modifier(ID, "etape", "Étape en cours importante")
        for num_ctx in (4096, 24576):
            texte = progress_sheet.texte_pour_modele(ID, num_ctx)
            self.assertLessEqual(len(texte), progress_sheet.budget_caracteres(num_ctx) + 400)
            self.assertIn("Mon objectif principal", texte, "l'objectif survit toujours")
            self.assertIn("Étape en cours importante", texte)
            self.assertTrue(texte.startswith("[Fiche de suivi]"))

    def test_mesure_et_avertissement(self):
        self.assertEqual(progress_sheet.mesure(ID, 24576)["niveau"], "vide")
        progress_sheet.modifier(ID, "objectif", "court")
        m = progress_sheet.mesure(ID, 24576)
        self.assertEqual(m["niveau"], "ok")
        self.assertGreater(m["jetons"], 0)
        for cle in ("decisions", "fait", "ouvert", "fichiers", "plan"):
            for i in range(30):
                progress_sheet.modifier(ID, cle, "{} {} ".format(cle, i) + "mot " * 40)
        gros = progress_sheet.mesure(ID, 4096)
        self.assertEqual(gros["niveau"], "attention")
        self.assertIn("ralentit", gros["avertissement"])

    def test_identifiant_invalide_refuse(self):
        for mauvais in ("../x", "a/b", "", "a", "x" * 80):
            with self.assertRaises(ValueError):
                progress_sheet.chemin(mauvais)

    def test_orphelins_nettoyes_et_suppression(self):
        progress_sheet.modifier(ID, "objectif", "x")
        progress_sheet.modifier("zzzz9999", "objectif", "y")
        self.assertEqual(progress_sheet.nettoyer_orphelins({ID}), 1)
        self.assertTrue(progress_sheet.chemin(ID).is_file())
        self.assertFalse(progress_sheet.chemin("zzzz9999").exists())
        self.assertTrue(progress_sheet.supprimer(ID))
        self.assertFalse(progress_sheet.supprimer(ID))


class Validation(unittest.TestCase):
    def test_reconnait_les_validations(self):
        for oui in ("oui", "Oui !", "ok vas-y", "On passe à l'action", "d'accord", "go", "yes", "c'est bon, lance", "parfait, fonce"):
            self.assertTrue(progress_sheet.est_confirmation(oui), oui)
        for non in ("non", "oui mais change le titre", "", "Explique-moi le chapitre 3", "oui je veux que tu réécrives tout le premier acte avec plus de suspense"):
            self.assertFalse(progress_sheet.est_confirmation(non), non)

    def test_directive_seulement_s_il_y_a_quelque_chose_a_faire(self):
        conv = {"taches": [{"texte": "Écrire le chapitre 1", "etat": "fait"}, {"texte": "Écrire le chapitre 2", "etat": "en_cours"}]}
        d = progress_sheet.directive_execution(conv, "oui", ID)
        self.assertIn("chapitre 2", d)
        self.assertIn("Ne refais pas le plan", d)
        self.assertEqual(progress_sheet.directive_execution(conv, "explique-moi", ID), "")
        self.assertEqual(progress_sheet.directive_execution({"taches": []}, "oui", ID), "", "rien à exécuter : pas de consigne")
        progress_sheet.modifier(ID, "etape", "Relire l'acte 2")
        try:
            self.assertIn("Relire l'acte 2", progress_sheet.directive_execution({}, "ok", ID), "l'étape de la fiche sert quand il n'y a pas de liste de tâches")
        finally:
            progress_sheet.supprimer(ID)


class PartDuContexte(unittest.TestCase):
    """La part de la fenêtre de contexte que la fiche peut prendre se règle (5 à 25 %, 10 par défaut)."""

    def tearDown(self):
        _m.enregistrer_reglages({"fiche_part": 10})
        progress_sheet.supprimer(ID)

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
            progress_sheet.modifier(ID, "decisions", "Décision numéro %d : " % i + "détail " * 25)
        petit = progress_sheet.texte_pour_modele(ID, 4096)
        _m.enregistrer_reglages({"fiche_part": 25})
        grand = progress_sheet.texte_pour_modele(ID, 4096)
        self.assertGreater(len(grand), len(petit), "plus de place : plus de la fiche passe au modèle")
        self.assertLessEqual(len(grand), int(4096 * 0.25 * 3) + 400)
        m = progress_sheet.mesure(ID, 4096)
        self.assertEqual(m["niveau"], "attention", "la fiche pèse beaucoup pour un petit contexte")
        self.assertIn("25 %", m["avertissement"], "l'avertissement cite le plafond réglé")


class Scribe(unittest.TestCase):
    """Le scribe met la fiche à jour par un appel séparé ; ses consignes sont contrôlées."""

    def setUp(self):
        from lutin import agent
        self.dialogue = agent
        progress_sheet.supprimer(ID)
        self.addCleanup(progress_sheet.supprimer, ID)
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
        progress_sheet.modifier(ID, "ouvert", "Quel budget pour la salle ?")
        progress_sheet.modifier(ID, "decisions", "Budget plafonné à 500 euros")
        appels = self.avec(json_ops(objectif=["Organiser la fête"], etape=["Réserver la salle"], decisions=["budget plafonné à 500 euros", "Salle réservée au 12 mai"], fait=["Devis reçu"], resolu=["Quel budget pour la salle ?"]))
        n = self.dialogue.scribe(self.conv, {"modele": "m", "num_ctx": 8192, "temperature": 0.2})
        s = progress_sheet.lire(ID)
        self.assertEqual((s["objectif"], s["etape"], s["fait"]), (["Organiser la fête"], ["Réserver la salle"], ["Devis reçu"]))
        self.assertEqual(s["decisions"], ["Budget plafonné à 500 euros", "Salle réservée au 12 mai"], "la décision déjà présente n'est pas dupliquée")
        self.assertEqual(s["ouvert"], [], "la question résolue (recopiée telle quelle) est retirée")
        self.assertGreater(n, 0)
        self.assertEqual(self.conv["scribe_a"], 8)
        self.assertEqual(appels[0]["format"], "json")
        self.assertIn("FICHE ACTUELLE", appels[0]["messages"][1]["content"])
        self.assertEqual(self.dialogue.scribe(self.conv, {"modele": "m", "num_ctx": 8192, "temperature": 0.2}), 0, "rien de nouveau depuis : aucun appel")
        self.assertEqual(len(appels), 1)

    def test_une_decision_n_est_jamais_retiree_et_les_excès_sont_bornes(self):
        progress_sheet.modifier(ID, "decisions", "Ne jamais toucher à la production")
        self.avec(json_ops(decisions=["décision %d" % i for i in range(30)], resolu=["Ne jamais toucher à la production"], ouvert=["x" * 5000]))
        self.dialogue.scribe(self.conv, {"modele": "m", "num_ctx": 8192, "temperature": 0.2})
        s = progress_sheet.lire(ID)
        self.assertIn("Ne jamais toucher à la production", s["decisions"], "le scribe ne supprime jamais une décision")
        self.assertEqual(len(s["decisions"]), 1 + self.dialogue.SCRIBE_AJOUTS_MAX, "au plus quatre lignes ajoutées par passage")
        self.assertLessEqual(max(len(x) for x in s["ouvert"]), progress_sheet.LIGNE_MAX)

    def test_reponse_absurde_ou_panne_ne_cassent_rien(self):
        for reponse in ("pas du json", "[1, 2]", "null", '{"decisions": 5, "etape": {"a": 1}}', ValueError("boum"), OSError("réseau")):
            self.conv.pop("scribe_a", None)
            self.avec(reponse)
            self.dialogue.scribe(self.conv, {"modele": "m", "num_ctx": 8192, "temperature": 0.2})
        self.assertEqual(progress_sheet.lire(ID)["objectif"], [])
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
        self.assertIn("Budget fixé", progress_sheet.lire(ID)["decisions"], "ce qui sort est passé dans la fiche")
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
        self.addCleanup(lambda: __import__("lutin.recall", fromlist=["FIL"]).FIL.clear())

    def conv(self, messages):
        c = {"id": self.ident, "titre": "t", "messages": messages}
        _m.conv_ecrire(dict(c, date="2026-01-01T00:00:00.000", maj="2026-01-01T00:00:00.000", resume="", travail="principal", taches=[]))
        return c

    def test_retrouve_un_detail_ancien_et_ignore_ce_qui_est_deja_sous_les_yeux(self):
        from lutin import recall
        anciens = [{"role": "user" if i % 2 == 0 else "assistant", "content": ("Le code du coffre est 4711-ZEBRE. " if i == 0 else "") + "blabla de remplissage numéro %d " % i * 3} for i in range(14)]
        c = self.conv(anciens)
        c["messages"] = anciens + [{"role": "user", "content": "Rappelle-moi le code du coffre ZEBRE s'il te plaît ?"}]
        texte, n = recall.rappel_du_fil(c)
        self.assertEqual(n, 1)
        self.assertIn("4711-ZEBRE", texte)
        self.assertTrue(texte.startswith("[Extraits de la conversation]"))
        # le même passage encore dans les six derniers messages : il est déjà sous les yeux du modèle
        recents = [{"role": "user", "content": "Le code du coffre est 4711-ZEBRE, noté."}, {"role": "assistant", "content": "ok"}]
        c2 = self.conv(recents)
        c2["messages"] = recents + [{"role": "user", "content": "Rappelle-moi le code du coffre ZEBRE s'il te plaît ?"}]
        self.assertEqual(recall.rappel_du_fil(c2), ("", 0))

    def test_un_oui_est_complete_par_la_derniere_reponse_et_l_etape(self):
        from lutin import recall
        msgs = [{"role": "user", "content": "Le tarif du traiteur est de 35 euros par personne, c'est acté."}, {"role": "assistant", "content": "Noté."}]
        msgs += [{"role": "user" if i % 2 == 0 else "assistant", "content": "autre sujet sans rapport %d et encore des mots" % i} for i in range(10)]
        c = self.conv(msgs)
        c["messages"] = msgs + [{"role": "assistant", "content": "On passe au traiteur ?"}, {"role": "user", "content": "oui"}]
        texte, n = recall.rappel_du_fil(c, "Contacter le traiteur")
        self.assertEqual(n, 1)
        self.assertIn("35 euros", texte, "« oui » seul ne dit rien : la question précédente et l'étape en cours guident la recherche")

    def test_conversation_inconnue_ou_vide(self):
        from lutin import recall
        self.assertEqual(recall.rappel_du_fil({"id": "e9d8c7b6", "messages": [{"role": "user", "content": "une longue question sans historique ici"}]}), ("", 0))
        self.assertEqual(recall.rappel_du_fil({"id": "", "messages": []}), ("", 0))


if __name__ == "__main__":
    unittest.main()
