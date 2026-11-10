"""Tâches planifiées, tout le mécanisme : validation, échéances (semaine ou une seule fois), modification, suppression réelle (avec ou sans conversation, même en plein travail), arrêt,
exécutions notées, tâche qui ne peut pas démarrer (jamais relancée en boucle), tâche interrompue par l'arrêt de Lutin, notification. Le modèle est remplacé par un faux « tour »."""
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-plan-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402
from lutin import donnees as _d  # noqa: E402
from lutin import notifications, planifie as P  # noqa: E402

LUNDI_8H = datetime(2026, 11, 9, 8, 30)          # un lundi


def tour_qui_repond(texte="Voici le résumé."):
    def faux(conv, demande, emit, r=None, stop=None, remplacer=None, identite="", lecture_seule=False, **k):
        assert lecture_seule and identite == "planifié", "une tâche planifiée tourne toujours en lecture seule"
        conv["messages"] += [{"role": "user", "content": demande}, {"role": "assistant", "content": texte}]
        _m.conv_ecrire(conv)
    return faux


class Base(unittest.TestCase):
    def setUp(self):
        P._ecrire([])
        P.EN_COURS.clear()
        P.A_SUPPRIMER.clear()
        self.envoyes = []
        self.canal = mock.patch.object(notifications, "trouver", lambda ident: {"id": ident} if ident == "c1" else None)
        self.envoi = mock.patch.object(notifications, "envoyer", lambda canal, titre, texte: self.envoyes.append((canal, titre, texte)))
        self.canal.start()
        self.envoi.start()
        self.addCleanup(self.canal.stop)
        self.addCleanup(self.envoi.stop)

    def tache(self, **plus):
        d = dict(nom="Résumé", prompt="Résume le dépôt.", heure="08:00", jours=[0, 1, 2, 3, 4], travail="", notifier="")
        d.update(plus)
        return P.ajouter(**d)

    def lancer(self, ident, tour):
        with mock.patch.object(_m, "tour", tour):
            return P.executer(ident)


class Validation(Base):
    def test_les_champs_sont_controles(self):
        for mauvais in (dict(nom=""), dict(prompt="  "), dict(prompt="x" * 4001), dict(heure="8h"), dict(heure="25:00"), dict(jours=[]), dict(jours=[7]), dict(jours=["a"]), dict(notifier="inconnu")):
            with self.assertRaises(ValueError, msg=str(mauvais)):
                self.tache(**mauvais)
        self.assertEqual(P.lire(), [], "rien n'est enregistré à moitié")

    def test_une_tache_creee_a_ses_champs_et_un_nom_propre(self):
        t = self.tache(nom="  Résumé   du  matin ", jours=[4, 0, 0], notifier="c1")
        self.assertEqual((t["nom"], t["jours"], t["notifier"], t["actif"], t["historique"], t["date"]), ("Résumé du matin", [0, 4], "c1", True, [], ""))
        self.assertEqual(P.lire()[0]["id"], t["id"])

    def test_vingt_taches_au_plus(self):
        for i in range(P.MAX_TACHES):
            self.tache(nom="t%d" % i)
        with self.assertRaises(ValueError):
            self.tache(nom="de trop")

    def test_une_date_passee_ou_mal_ecrite_est_refusee_et_la_date_fixe_le_jour(self):
        demain = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        hier = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        for mauvaise in (hier, "demain", "2026-13-40"):
            with self.assertRaises(ValueError, msg=mauvaise):
                self.tache(date=mauvaise, jours=[])
        t = self.tache(date=demain, jours=[])
        self.assertEqual(t["jours"], [(datetime.now() + timedelta(days=1)).weekday()])


class Echeances(Base):
    def test_chaque_semaine_aux_jours_choisis_une_seule_fois_par_jour(self):
        t = self.tache(jours=[0])
        t["cree"] = (LUNDI_8H - timedelta(days=3)).isoformat()
        self.assertIsNone(P.echeance(dict(t, heure="09:00"), LUNDI_8H), "pas encore l'heure")
        self.assertEqual(P.echeance(t, LUNDI_8H), LUNDI_8H.replace(hour=8, minute=0))
        self.assertIsNone(P.echeance(t, LUNDI_8H + timedelta(days=1)), "pas le bon jour")
        self.assertIsNone(P.echeance(dict(t, derniere_exec=LUNDI_8H.isoformat()), LUNDI_8H + timedelta(hours=2)), "déjà faite aujourd'hui")
        self.assertIsNone(P.echeance(dict(t, actif=False), LUNDI_8H), "en pause")
        self.assertIsNone(P.echeance(dict(t, cree=LUNDI_8H.isoformat()), LUNDI_8H), "créée après l'heure du jour : elle attend le lendemain")

    def test_une_seule_fois_a_la_date_dite_et_pas_un_autre_jour(self):
        t = {"actif": True, "heure": "08:00", "jours": [0], "date": "2026-11-09", "cree": "2026-11-01T10:00:00", "derniere_exec": ""}
        self.assertIsNotNone(P.echeance(t, LUNDI_8H))
        self.assertIsNone(P.echeance(t, LUNDI_8H + timedelta(days=7)), "le lundi suivant n'est pas la date")
        self.assertIsNone(P.echeance(t, LUNDI_8H - timedelta(days=1)))
        self.assertEqual(P.prochaine(dict(t, heure="09:00"), LUNDI_8H), "2026-11-09T09:00")
        self.assertEqual(P.prochaine(dict(t, derniere_exec="2026-11-09T08:00:00"), LUNDI_8H + timedelta(hours=1)), "", "faite : plus de prochaine fois")

    def test_la_prochaine_fois_saute_au_jour_suivant_prevu(self):
        t = {"actif": True, "heure": "08:00", "jours": [0, 2], "date": "", "cree": "2026-11-01T10:00:00", "derniere_exec": LUNDI_8H.isoformat()}
        self.assertEqual(P.prochaine(t, LUNDI_8H + timedelta(hours=1)), "2026-11-11T08:00")
        self.assertEqual(P.prochaine(dict(t, actif=False), LUNDI_8H), "")


class Modification(Base):
    def test_on_modifie_tout_et_une_heure_deja_passee_n_est_pas_rattrapee(self):
        t = self.tache(jours=[0, 1, 2, 3, 4, 5, 6])
        avant = P.lire()[0]["cree"]
        time.sleep(1.1)
        n = P.changer(t["id"], "Autre nom", "Autre demande", "09:15", [1, 3], "", "c1", "")
        self.assertEqual((n["nom"], n["prompt"], n["heure"], n["jours"], n["notifier"]), ("Autre nom", "Autre demande", "09:15", [1, 3], "c1"))
        self.assertGreater(P.lire()[0]["cree"], avant, "le moment a changé : la tâche repart de maintenant")
        garde = P.lire()[0]["cree"]
        time.sleep(1.1)
        P.changer(t["id"], "Encore", "Demande", "09:15", [1, 3], "", "", "")
        self.assertEqual(P.lire()[0]["cree"], garde, "seul le nom a changé : le moment ne bouge pas")

    def test_modifier_une_tache_en_pause_dont_le_moment_change_la_reactive(self):
        t = self.tache()
        P.modifier(t["id"], actif=False)
        P.changer(t["id"], "Résumé", "Résume.", "10:00", [0], "", "", "")
        self.assertTrue(P.lire()[0]["actif"])
        P.modifier(t["id"], actif=False)
        P.changer(t["id"], "Résumé bis", "Résume.", "10:00", [0], "", "", "")
        self.assertFalse(P.lire()[0]["actif"], "le moment n'a pas changé : la pause reste")

    def test_modifier_une_tache_inconnue_ou_avec_des_champs_faux_est_refuse(self):
        with self.assertRaises(ValueError):
            P.changer("inconnue", "n", "p", "08:00", [0], "", "", "")
        t = self.tache()
        with self.assertRaises(ValueError):
            P.changer(t["id"], "n", "p", "bientôt", [0], "", "", "")
        self.assertEqual(P.lire()[0]["heure"], "08:00")


class Execution(Base):
    def test_une_execution_reussie_est_notee_et_notifiee_dans_la_meme_conversation(self):
        t = self.tache(notifier="c1")
        c1 = self.lancer(t["id"], tour_qui_repond("Premier résumé."))
        c2 = self.lancer(t["id"], tour_qui_repond("Deuxième résumé."))
        self.assertEqual(c1, c2, "une seule conversation « ⏰ nom » par tâche")
        n = P.lire()[0]
        self.assertEqual((n["derniere_etat"], n["derniere_erreur"], n["derniere_conv"]), ("ok", "", c1))
        self.assertEqual([h["etat"] for h in n["historique"]], ["ok", "ok"])
        self.assertTrue(all(h["date"] and h["duree_s"] >= 0 for h in n["historique"]))
        self.assertEqual(_m.conv_lire(c1)["titre"], "⏰ Résumé")
        self.assertEqual([e[2] for e in self.envoyes], ["Premier résumé.", "Deuxième résumé."])
        self.assertEqual(P.EN_COURS, {}, "rien ne reste « en cours »")

    def test_l_historique_garde_les_dix_dernieres(self):
        t = self.tache()
        for _ in range(P.HISTORIQUE_MAX + 3):
            self.lancer(t["id"], tour_qui_repond())
        self.assertEqual(len(P.lire()[0]["historique"]), P.HISTORIQUE_MAX)

    def test_un_modele_muet_ou_en_erreur_est_dit_dans_la_conversation_et_la_notification(self):
        t = self.tache(notifier="c1")

        def muet(conv, demande, emit, *a, **k):
            _m.conv_ecrire(dict(conv, messages=conv["messages"] + [{"role": "user", "content": demande}]))
        c = self.lancer(t["id"], muet)
        n = P.lire()[0]
        self.assertEqual(n["derniere_etat"], "erreur")
        self.assertIn("Aucune réponse", n["derniere_erreur"])
        dernier = _m.conv_lire(c)["messages"][-1]
        self.assertTrue(dernier["content"].startswith("⚠") and dernier["ts"], "l'explication est écrite dans la conversation, datée")
        self.assertIn("problème", self.envoyes[-1][1])

        def casse(conv, demande, emit, *a, **k):
            emit({"type": "erreur", "texte": "Ollama ne répond pas"})
        self.lancer(t["id"], casse)
        self.assertIn("Ollama ne répond pas", P.lire()[0]["derniere_erreur"])
        self.assertEqual([h["etat"] for h in P.lire()[0]["historique"]], ["erreur", "erreur"])

        def leve(conv, demande, emit, *a, **k):
            raise RuntimeError("boum")
        self.lancer(t["id"], leve)
        self.assertEqual(P.lire()[0]["derniere_etat"], "erreur")

    def test_une_tache_a_date_fixe_se_met_en_pause_apres_son_passage(self):
        demain = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        t = self.tache(date=demain, jours=[])
        self.lancer(t["id"], tour_qui_repond())
        n = P.lire()[0]
        self.assertFalse(n["actif"])
        self.assertEqual(n["derniere_etat"], "ok")
        self.assertEqual(P.prochaine(n, datetime.now()), "")

    def test_une_tache_qui_ne_peut_pas_demarrer_l_ecrit_et_n_est_pas_relancee_en_boucle(self):
        t = self.tache(notifier="c1")
        P.modifier(t["id"], cree=(LUNDI_8H - timedelta(days=3)).isoformat())
        with mock.patch.object(_m, "activer_travail", mock.Mock(side_effect=ValueError("Le dossier de travail « x » n'est plus dans la liste."))), mock.patch.object(_m, "tour", mock.Mock(side_effect=AssertionError("ne démarre pas"))):
            self.assertEqual(P.un_regard(LUNDI_8H), t["id"])
            n = P.lire()[0]
            self.assertEqual((n["derniere_etat"], len(n["historique"])), ("erreur", 1))
            self.assertIn("n'est plus dans la liste", n["derniere_erreur"])
            self.assertIn("n'est plus dans la liste", self.envoyes[-1][2])
            self.assertIsNone(P.un_regard(LUNDI_8H + timedelta(minutes=1)), "pas de nouvelle tentative toutes les 30 secondes")
            self.assertEqual(len(P.lire()[0]["historique"]), 1)

    def test_machine_occupee_la_tache_attend_sans_rien_noter(self):
        t = self.tache()
        P.modifier(t["id"], cree=(LUNDI_8H - timedelta(days=3)).isoformat())
        with mock.patch.dict(_m.TOURS_ACTIFS, {"autre": threading.Event()}), mock.patch.object(_m, "TOURS_SIMULTANES", 1), mock.patch.object(_m, "tour", mock.Mock(side_effect=AssertionError("ne démarre pas"))):
            self.assertIsNone(P.un_regard(LUNDI_8H))
            with self.assertRaises(ValueError):
                P.executer(t["id"])
        self.assertEqual((P.lire()[0]["derniere_exec"], P.lire()[0]["historique"]), ("", []))
        with mock.patch.object(_m, "tour", tour_qui_repond()):
            self.assertEqual(P.un_regard(LUNDI_8H), t["id"], "la machine est libre : elle part")

    def test_une_tache_ne_se_lance_pas_deux_fois_en_meme_temps(self):
        t = self.tache()
        libre, demarree = threading.Event(), threading.Event()

        def lent(conv, demande, emit, r=None, stop=None, *a, **k):
            demarree.set()
            libre.wait(10)
            conv["messages"] += [{"role": "assistant", "content": "ok"}]
            _m.conv_ecrire(conv)
        fil = threading.Thread(target=lambda: self.lancer(t["id"], lent))
        fil.start()
        self.assertTrue(demarree.wait(10))
        self.assertTrue(P.etat()["taches"][0]["en_cours"])
        with mock.patch.object(_m, "tour", tour_qui_repond()), self.assertRaises(ValueError) as e:
            P.executer(t["id"])
        self.assertIn("déjà", str(e.exception))
        libre.set()
        fil.join(10)
        self.assertFalse(P.etat()["taches"][0]["en_cours"])


class ArretEtSuppression(Base):
    def en_plein_travail(self, t):
        demarree = threading.Event()

        def attend_l_arret(conv, demande, emit, r=None, stop=None, *a, **k):
            demarree.set()
            stop.wait(10)
            conv["messages"] += [{"role": "assistant", "content": "réponse partielle"}]
            _m.conv_ecrire(conv)
        fil = threading.Thread(target=lambda: self.lancer(t["id"], attend_l_arret))
        fil.start()
        self.assertTrue(demarree.wait(10))
        return fil

    def test_arreter_une_tache_en_cours_la_garde_planifiee_et_ne_previent_personne(self):
        t = self.tache(notifier="c1")
        fil = self.en_plein_travail(t)
        P.arreter(t["id"])
        fil.join(10)
        n = P.lire()[0]
        self.assertEqual((n["derniere_etat"], n["actif"], self.envoyes), ("arretee", True, []))
        self.assertEqual(n["historique"][0]["etat"], "arretee")
        with self.assertRaises(ValueError):
            P.arreter(t["id"])

    def test_supprimer_une_tache_en_cours_l_arrete_pour_de_bon(self):
        t = self.tache(notifier="c1")
        fil = self.en_plein_travail(t)
        P.supprimer(t["id"])
        fil.join(10)
        self.assertFalse(fil.is_alive(), "le tour a été arrêté")
        self.assertEqual((P.lire(), self.envoyes, P.EN_COURS), ([], [], {}), "supprimée : plus rien ne s'écrit, personne n'est prévenu")
        self.assertIsNone(P.un_regard(LUNDI_8H + timedelta(days=30)))

    def test_la_conversation_est_gardee_par_defaut_et_effacee_sur_demande(self):
        t = self.tache()
        conv = self.lancer(t["id"], tour_qui_repond())
        P.supprimer(t["id"])
        self.assertTrue(_d.conv_chemin(conv).is_file(), "la conversation reste : elle contient les résultats")
        t2 = self.tache(nom="Autre")
        conv2 = self.lancer(t2["id"], tour_qui_repond())
        P.supprimer(t2["id"], conversation=True)
        self.assertFalse(_d.conv_chemin(conv2).exists())

    def test_supprimer_avec_sa_conversation_en_plein_travail_n_en_laisse_aucune_trace(self):
        t = self.tache()
        fil = self.en_plein_travail(t)
        conv = P.lire()[0]["derniere_conv"]
        P.supprimer(t["id"], conversation=True)
        fil.join(10)
        self.assertFalse(_d.conv_chemin(conv).exists(), "la fin du tour n'a pas réécrit la conversation")
        self.assertEqual(P.A_SUPPRIMER, set())

    def test_supprimer_une_tache_inconnue_est_dit(self):
        with self.assertRaises(ValueError):
            P.supprimer("inconnue")

    def test_une_tache_interrompue_par_l_arret_de_lutin_est_dite_interrompue(self):
        t = self.tache()
        P.modifier(t["id"], derniere_etat="en_cours", derniere_conv="abc")
        self.assertEqual(P.etat()["taches"][0]["derniere_etat"], "interrompue", "affiché tout de suite")
        with mock.patch.object(P, "boucle", lambda: None):
            P.demarrer()
        n = P.lire()[0]
        self.assertEqual(n["derniere_etat"], "interrompue")
        self.assertIn("arrêté", n["derniere_erreur"])


class Notification(Base):
    def test_un_canal_supprime_entre_temps_est_dit_sans_casser_la_tache(self):
        t = self.tache(notifier="c1")

        def envoi_casse(canal, titre, texte):
            raise ValueError("Ce canal n'existe plus.")
        with mock.patch.object(notifications, "envoyer", envoi_casse):
            self.lancer(t["id"], tour_qui_repond())
        n = P.lire()[0]
        self.assertEqual(n["derniere_etat"], "ok")
        self.assertIn("n'existe plus", n["derniere_notif"])


if __name__ == "__main__":
    unittest.main()
