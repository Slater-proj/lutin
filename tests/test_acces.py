"""La page Accès : niveau de sécurité (qui peut le changer, ce qui est refusé), code PIN et QR, redémarrage, restauration d'une sauvegarde, dossiers de travail — côté serveur et dans un vrai navigateur."""
import html
import http.client
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-acces-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9"}.items():
    os.environ.setdefault(cle, valeur)
os.environ["LUTIN_CONFIG"] = str(_TEMP / "config" / "config.json")
for d in ("projet", "donnees", "memoire", "config"):
    (_TEMP / d).mkdir(exist_ok=True)
CONFIG = _TEMP / "config" / "config.json"
CONFIG.write_text(json.dumps({"schema": 1, "installe": True, "securite": {"niveau": "local", "port": 8777}, "emplacements": {"travail": str(_TEMP / "projet"), "travaux": [], "travail_actif": ""}}), encoding="utf-8")

from lutin import acces, sauvegarde  # noqa: E402
from lutin import moteur as A  # noqa: E402
from lutin import securite as S  # noqa: E402

SERVEUR = ThreadingHTTPServer(("127.0.0.1", 0), A.Gestionnaire)
threading.Thread(target=SERVEUR.serve_forever, daemon=True).start()
PORT = SERVEUR.server_address[1]
RACINE_TESTS = Path(__file__).resolve().parent.parent


def requete(methode, chemin, en_tetes=None, corps=None, brut=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = {"Host": "127.0.0.1:%d" % PORT, "X-Token": A.JETON}
    h.update(en_tetes or {})
    donnees = brut
    if corps is not None:
        donnees = json.dumps(corps).encode("utf-8")
        h["Content-Type"] = "application/json"
    c.request(methode, chemin, body=donnees, headers=h)
    r = c.getresponse()
    texte = r.read().decode("utf-8", "replace")
    c.close()
    try:
        return r.status, json.loads(texte)
    except ValueError:
        return r.status, texte


class Base(unittest.TestCase):
    def setUp(self):
        self.avant = (A.SECURITE, A.APPAREILS)
        A.SECURITE = S.Securite(niveau=S.LOCAL, port=8777)
        A.APPAREILS = S.Appareils()
        CONFIG.write_text(json.dumps({"schema": 1, "installe": True, "securite": {"niveau": "local", "port": 8777}, "emplacements": {"travail": str(_TEMP / "projet"), "travaux": [], "travail_actif": ""}}), encoding="utf-8")
        os.environ.pop("LUTIN_DOCKER", None)
        os.environ.pop("LUTIN_SUPERVISE", None)

    def tearDown(self):
        A.SECURITE, A.APPAREILS = self.avant

    def session(self):
        pin = A.APPAREILS.nouveau_pin()
        jeton = A.APPAREILS.appairer(pin, "Téléphone")
        return {"Cookie": "{}={}".format(S.NOM_COOKIE, jeton)}


class NiveauDAcces(Base):
    def test_etat(self):
        statut, e = requete("GET", "/api/acces")
        self.assertEqual(statut, 200)
        self.assertEqual((e["niveau"], e["modifiable"], e["docker"], e["redemarrage_necessaire"]), ("local", True, False, False))
        self.assertEqual(sorted(e["niveaux"]), ["local", "proxy", "reseau"])
        self.assertIn("PIN", e["avertissements"]["reseau"])
        self.assertTrue(e["adresse"].startswith("http://") and e["adresse"].endswith(":8777/"))

    def test_changer_le_niveau_enregistre_et_demande_un_redemarrage(self):
        statut, r = requete("POST", "/api/acces", corps={"niveau": "reseau"})
        self.assertEqual((statut, "comprends" in r.get("erreur", "") or "compris" in r.get("erreur", "")), (400, True), "ouvrir l'accès demande de confirmer")
        statut, r = requete("POST", "/api/acces", corps={"niveau": "reseau", "comprend": True})
        self.assertEqual((statut, r), (200, {"redemarrage_necessaire": True}))
        self.assertEqual(json.loads(CONFIG.read_text(encoding="utf-8"))["securite"]["niveau"], "reseau")
        self.assertEqual(A.SECURITE.niveau, "local", "rien ne change avant le redémarrage")
        self.assertTrue(requete("GET", "/api/acces")[1]["redemarrage_necessaire"])
        self.assertTrue(requete("GET", "/api/etat")[1]["redemarrage"]["necessaire"])
        statut, r = requete("POST", "/api/acces", corps={"niveau": "local"})
        self.assertEqual((statut, r["redemarrage_necessaire"]), (200, False), "revenir au niveau actuel annule l'attente")
        self.assertFalse(requete("GET", "/api/etat")[1]["redemarrage"]["necessaire"])

    def test_le_niveau_proxy_demande_l_adresse_et_le_proxy(self):
        statut, r = requete("POST", "/api/acces", corps={"niveau": "proxy", "comprend": True})
        self.assertEqual(statut, 400)
        self.assertIn("Sécurité", r["erreur"])
        statut, r = requete("POST", "/api/acces", corps={"niveau": "proxy", "comprend": True, "url_publique": "https://lutin.exemple.fr", "proxy_ips": ["127.0.0.1"]})
        self.assertEqual(statut, 200)
        enregistre = json.loads(CONFIG.read_text(encoding="utf-8"))["securite"]
        self.assertEqual((enregistre["url_publique"], enregistre["proxy_ips"]), ("https://lutin.exemple.fr", ["127.0.0.1"]))
        self.assertEqual(requete("POST", "/api/acces", corps={"niveau": "klingon"})[0], 400)

    def test_dans_docker_le_niveau_vient_de_la_variable(self):
        with mock.patch.dict(os.environ, {"LUTIN_DOCKER": "1"}):
            e = requete("GET", "/api/acces")[1]
            self.assertEqual((e["docker"], e["modifiable"]), (True, False))
            statut, r = requete("POST", "/api/acces", corps={"niveau": "reseau", "comprend": True})
            self.assertEqual(statut, 400)
            self.assertIn("LUTIN_NIVEAU", r["erreur"])

    def test_qui_peut_changer_le_niveau(self):
        A.SECURITE = S.Securite(niveau=S.RESEAU, port=8777)
        sur_la_machine = dict(self.session())
        self.assertTrue(requete("GET", "/api/acces", sur_la_machine)[1]["modifiable"], "le navigateur de cette machine, au niveau réseau")
        for intrus in ({"X-Forwarded-For": "192.168.1.50"}, {"Forwarded": "for=192.168.1.50"}, {"Via": "1.1 proxy"}, {"Host": "lutin.maison:8777"}, {"X-Real-IP": "10.0.0.2"}):
            statut, e = requete("GET", "/api/acces", dict(sur_la_machine, **intrus))
            if statut == 200:
                self.assertFalse(e["modifiable"], intrus)
                self.assertEqual(requete("POST", "/api/acces", dict(sur_la_machine, **intrus), {"niveau": "local"})[0], 403, intrus)
        A.SECURITE = S.Securite(niveau=S.PROXY, port=8777, url_publique="https://lutin.exemple.fr", proxy_ips=["127.0.0.1"])
        statut, e = requete("GET", "/api/acces", {"Remote-User": "moi", "Host": "lutin.exemple.fr"})
        if statut == 200:
            self.assertFalse(e["modifiable"], "derrière un proxy installé sur la machine : jamais, le proxy ne prouve rien")


class AppairageEtAppareils(Base):
    def test_pin_et_appareils(self):
        A.SECURITE = S.Securite(niveau=S.RESEAU, port=8777)
        session = self.session()
        statut, r = requete("POST", "/api/nouveau-pin", session, {})
        self.assertEqual((statut, len(r["pin"]), r["valable_s"]), (200, 6, 600))
        e = requete("GET", "/api/acces", session)[1]
        self.assertEqual([a["nom"] for a in e["appareils"]], ["Téléphone"])
        ident = e["appareils"][0]["id"]
        self.assertEqual(requete("POST", "/api/appareils-revoquer", session, {"id": ident}), (200, {"revoques": 1}))
        self.assertEqual(requete("GET", "/api/skills", session)[0], 401, "l'appareil déconnecté ne passe plus")

    def test_qr(self):
        statut, r = requete("GET", "/api/qr?d=" + "http%3A%2F%2F192.168.1.50%3A8777%2F%23pin%3D123456")
        self.assertEqual((statut, r["taille"], len(r["lignes"])), (200, 29, 29))
        self.assertTrue(all(set(ligne) <= {"0", "1"} and len(ligne) == 29 for ligne in r["lignes"]))
        self.assertEqual(requete("GET", "/api/qr?d=" + "x" * 300)[0], 400)

    def test_la_page_de_connexion_lit_le_pin_du_qr_code(self):
        A.SECURITE = S.Securite(niveau=S.RESEAU, port=8777)
        statut, page = requete("GET", "/", {"X-Token": ""})
        self.assertEqual(statut, 200)
        self.assertIn("pin=([0-9]{6})", page)
        self.assertIn("history.replaceState", page, "le code ne reste pas dans l'adresse affichée")


class CommandesDuProjet(Base):
    def test_route_des_commandes_claude(self):
        c = A.RACINE / ".claude" / "commands"
        c.mkdir(parents=True, exist_ok=True)
        (c / "bonjour.md").write_text("---\ndescription: Salue\n---\nDis bonjour à $ARGUMENTS", encoding="utf-8")
        try:
            statut, r = requete("GET", "/api/commande-claude?nom=bonjour&args=le+monde")
            self.assertEqual((statut, r), (200, {"texte": "Dis bonjour à le monde"}))
            self.assertEqual(requete("GET", "/api/commande-claude?nom=absente")[0], 400)
            self.assertEqual(requete("GET", "/api/commande-claude?nom=..%2F..%2Fx")[0], 400)
            detecte = requete("GET", "/api/projet-claude")[1]["detecte"]
            self.assertEqual([x["nom"] for x in detecte["commandes"]], ["bonjour"])
        finally:
            (c / "bonjour.md").unlink()


class Documents(Base):
    def test_rechercher_dans_un_pdf_un_document_word_et_lire_avec_citation(self):
        from test_extraction import ecrire_zip, pdf_simple
        docs = A.RACINE / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "panne.pdf").write_bytes(pdf_simple(True))
        ecrire_zip(docs / "guide.docx", {"word/document.xml": "<w:document><w:p><w:r><w:t>La sauvegarde du NAS se lance chaque nuit à trois heures.</w:t></w:r></w:p></w:document>"})
        (docs / "casse.docx").write_bytes(b"pas un zip")
        try:
            etat = requete("GET", "/api/documents")[1]
            self.assertEqual(sorted(f["nom"] for f in etat["fichiers"]), ["docs/casse.docx", "docs/guide.docx", "docs/panne.pdf"])
            self.assertEqual([e["nom"] for e in etat["erreurs"]], ["docs/casse.docx"], "un document illisible est signalé, il ne casse rien")
            statut, r = requete("GET", "/api/documents-chercher?q=" + "sauvegarde+nuit")
            self.assertEqual(statut, 200)
            self.assertEqual(r["passages"][0]["source"], "docs/guide.docx")
            statut, r = requete("GET", "/api/documents-chercher?q=" + "proc%C3%A9dure+d%C3%A9ploiement")
            self.assertEqual((r["passages"][0]["source"], r["passages"][0]["titre"]), ("docs/panne.pdf", "Page 1"), "la citation donne la page")
            self.assertEqual(requete("GET", "/api/documents-chercher?q=")[0], 400)
            self.assertEqual(requete("GET", "/api/documents-chercher?q=le+la")[0], 400)
            lu = A.outil_lire("docs/panne.pdf")
            self.assertIn("Deuxième ligne : procédure", lu)
            self.assertIn("## Page 1", lu)
            self.assertIn("Page 1", A.outil_rappeler("déploiement"))
            with self.assertRaisesRegex(A.ErreurOutil, "illisible"):
                A.outil_lire("docs/casse.docx")
            self.assertTrue(list((A.DONNEES / "cache-documents").glob("*.json")), "le texte extrait est gardé : pas de nouvelle lecture au prochain démarrage")
        finally:
            for n in ("panne.pdf", "guide.docx", "casse.docx"):
                (docs / n).unlink(missing_ok=True)


class ConseilPc(Base):
    def test_sans_mesure_puis_avec_mesure(self):
        from lutin import bench
        # le matériel et Ollama sont simulés : le test ne dépend pas de la machine (ni de son délai)
        from lutin import machine
        profil = machine.Profil(systeme="windows", cpu="test", coeurs=8, ram_go=16.0, ram_libre_go=10.0, gpus=[])
        ollama = {"actif": True, "installes": {}, "tailles": {}}
        with mock.patch("lutin.machine.detecter", return_value=profil), mock.patch.object(A, "etat_ollama", return_value=ollama), mock.patch.object(A, "ps_modele", return_value=None):
            self._conseil_avec_mesure(bench)

    def _conseil_avec_mesure(self, bench):
        chemin = A.chemin_bench()
        existait = chemin.exists()
        avant = chemin.read_bytes() if existait else None
        modele = A.reglages()["modele"]
        try:
            chemin.unlink(missing_ok=True)
            self.assertEqual(requete("GET", "/api/conseil"), (200, {"mesure": None, "conseil": []}))
            bench.enregistrer(chemin, {"modele": modele, "date": "2026-10-26T10:00:00", "resultats": {"vitesse": {"tok_s": 4.0, "chargement_s": 3.0}}, "notes": [], "complet": False})
            statut, r = requete("GET", "/api/conseil")
            self.assertEqual(statut, 200)
            self.assertEqual(r["mesure"]["tok_s"], 4.0)
            self.assertTrue(r["conseil"], "une vitesse très basse donne au moins un conseil")
        finally:
            if existait:
                chemin.write_bytes(avant)
            else:
                chemin.unlink(missing_ok=True)


class VerifierLutin(Base):
    """Le bouton « Vérifier les mises à jour » : une requête tout de suite, puis la bannière ; hors ligne, un message clair."""

    def setUp(self):
        super().setUp()
        self.cache = Path(tempfile.mkdtemp(prefix="lutin-version-")) / "lutin-version.json"
        self.env = os.environ.get("LUTIN_VERSION_CACHE")
        os.environ["LUTIN_VERSION_CACHE"] = str(self.cache)

    def tearDown(self):
        if self.env is None:
            os.environ.pop("LUTIN_VERSION_CACHE", None)
        else:
            os.environ["LUTIN_VERSION_CACHE"] = self.env
        super().tearDown()

    def test_version_plus_recente_annoncee(self):
        from lutin import miseajour
        with mock.patch.object(miseajour, "derniere_release_detail", return_value=("99.0.0", "https://example/roue.whl", "")):
            statut, r = requete("POST", "/api/verifier-lutin", corps={})
        self.assertEqual(statut, 200)
        self.assertEqual(r["derniere"], "99.0.0")
        self.assertEqual(r["nouvelle"]["version"], "99.0.0")

    def test_hors_ligne_le_dit(self):
        from lutin import miseajour
        with mock.patch.object(miseajour, "derniere_release_detail", return_value=(None, None, "api.github.com : timed out ; github.com : timed out")):
            statut, r = requete("POST", "/api/verifier-lutin", corps={})
        self.assertEqual(statut, 503)
        self.assertIn("GitHub", r["erreur"])
        self.assertIn("timed out", r["erreur"], "la vraie cause est montrée, pas un message vague")


class Planification(Base):
    def setUp(self):
        super().setUp()
        from lutin import planifie
        self.p = planifie
        planifie.chemin().unlink(missing_ok=True)

    def tearDown(self):
        self.p.chemin().unlink(missing_ok=True)
        super().tearDown()

    def test_ajout_validation_et_suppression(self):
        for corps in ({"nom": "", "prompt": "x", "heure": "08:00", "jours": [0]}, {"nom": "a", "prompt": "x", "heure": "8h", "jours": [0]},
                      {"nom": "a", "prompt": "x", "heure": "08:00", "jours": []}, {"nom": "a", "prompt": "x", "heure": "08:00", "jours": [9]}):
            self.assertEqual(requete("POST", "/api/planifie-ajouter", corps=corps)[0], 400, corps)
        statut, t = requete("POST", "/api/planifie-ajouter", corps={"nom": "Matin", "prompt": "résume le dépôt", "heure": "08:30", "jours": [0, 1, 2]})
        self.assertEqual(statut, 200)
        etat = requete("GET", "/api/planifie")[1]["taches"]
        self.assertEqual([x["nom"] for x in etat], ["Matin"])
        self.assertTrue(etat[0]["prochaine"])
        self.assertEqual(requete("POST", "/api/planifie-activer", corps={"id": t["id"], "actif": False})[1]["actif"], False)
        self.assertEqual(requete("GET", "/api/planifie")[1]["taches"][0]["prochaine"], "", "en pause : pas de prochaine exécution")
        self.assertEqual(requete("POST", "/api/planifie-supprimer", corps={"id": t["id"]})[0], 200)
        self.assertEqual(requete("POST", "/api/planifie-supprimer", corps={"id": t["id"]})[0], 400)

    def test_gestion_reservee_a_cette_machine(self):
        A.SECURITE = S.Securite(niveau=S.RESEAU, port=8777)
        statut, r = requete("POST", "/api/planifie-ajouter", en_tetes=dict(self.session(), **{"X-Forwarded-For": "192.168.1.20"}), corps={"nom": "a", "prompt": "x", "heure": "08:00", "jours": [0]})
        self.assertEqual(statut, 403, "un appareil appairé, ou un relais, ne planifie pas")
        self.assertEqual(self.p.lire(), [])

    def test_echeance(self):
        from datetime import datetime
        t = {"actif": True, "heure": "08:30", "jours": [0, 1, 2, 3, 4], "cree": "2026-10-20T07:00:00", "derniere_exec": ""}
        lundi = lambda h, m: datetime(2026, 10, 26, h, m)  # noqa: E731
        self.assertIsNone(self.p.echeance(t, lundi(8, 29)), "pas avant l'heure")
        self.assertIsNotNone(self.p.echeance(t, lundi(8, 31)))
        self.assertIsNotNone(self.p.echeance(t, lundi(23, 0)), "PC allumé en retard : rattrapé le jour même")
        self.assertIsNone(self.p.echeance(dict(t, derniere_exec="2026-10-26T08:31:00"), lundi(9, 0)), "déjà faite aujourd'hui")
        self.assertIsNone(self.p.echeance(dict(t, cree="2026-10-26T09:00:00"), lundi(9, 30)), "créée après l'heure : attend demain")
        self.assertIsNone(self.p.echeance(t, datetime(2026, 10, 31, 9, 0)), "samedi : pas un jour choisi")
        self.assertIsNone(self.p.echeance(dict(t, actif=False), lundi(9, 0)))

    def test_execution_en_lecture_seule_dans_une_conversation_planifiee(self):
        t = self.p.ajouter("Matin", "résume le dépôt", "08:30", [0, 1, 2, 3, 4, 5, 6])
        appels = []
        with mock.patch.object(A, "tour", side_effect=lambda conv, texte, emit, r, stop, depuis, identite="", lecture_seule=False: appels.append((conv["titre"], texte, lecture_seule, A.TOURS_ACTIFS.get(conv["id"]) is stop))):
            ident = self.p.executer(t["id"])
        self.assertEqual(appels, [("⏰ Matin", "résume le dépôt", True, True)])
        self.assertEqual(A.TOURS_ACTIFS, {}, "la machine est libérée après la tâche")
        fait = self.p.lire()[0]
        self.assertEqual((fait["derniere_conv"], fait["derniere_etat"]), (ident, "ok"))

    def test_une_erreur_est_notee_et_ne_casse_pas_la_boucle(self):
        t = self.p.ajouter("Matin", "x", "08:30", [0, 1, 2, 3, 4, 5, 6])
        with mock.patch.object(A, "tour", side_effect=RuntimeError("boum")):
            self.p.executer(t["id"])
        self.assertEqual(self.p.lire()[0]["derniere_etat"], "erreur")

    def test_pas_de_demarrage_si_une_reponse_est_en_cours(self):
        from datetime import datetime, timedelta
        t = self.p.ajouter("Matin", "x", "00:00", [0, 1, 2, 3, 4, 5, 6])
        self.p.modifier(t["id"], cree=(datetime.now() - timedelta(days=2)).isoformat(timespec="seconds"))
        A.TOURS_ACTIFS["abcdef12"] = threading.Event()
        try:
            with mock.patch.object(self.p, "executer") as ex:
                self.assertIsNone(self.p.un_regard())
                ex.assert_not_called()
        finally:
            A.TOURS_ACTIFS.pop("abcdef12", None)
        with mock.patch.object(self.p, "executer") as ex:
            self.assertEqual(self.p.un_regard(), t["id"])
            ex.assert_called_once_with(t["id"])


class Redemarrage(Base):
    def test_refuse_sans_superviseur_ni_conteneur(self):
        statut, r = requete("POST", "/api/redemarrer", corps={})
        self.assertEqual(statut, 400)
        self.assertIn("lutin", r["erreur"])

    def test_avec_superviseur(self):
        os.environ["LUTIN_SUPERVISE"] = "1"
        with mock.patch.object(acces.threading, "Timer") as timer:
            self.assertEqual(requete("POST", "/api/redemarrer", corps={}), (200, {"ok": True}))
            args = timer.call_args[0]
            self.assertEqual((args[0] > 0, args[1], args[2]), (True, os._exit, [acces.CODE_REDEMARRAGE]))
            timer.return_value.start.assert_called_once()
            A.TOURS_ACTIFS["abcd1234"] = object()
            try:
                statut, r = requete("POST", "/api/redemarrer", corps={})
                self.assertEqual(statut, 400)
                self.assertIn("réponse est en cours", r["erreur"])
            finally:
                A.TOURS_ACTIFS.pop("abcd1234", None)

    def test_le_superviseur_relance_sans_compter_une_panne(self):
        from lutin import cli
        codes = iter([acces.CODE_REDEMARRAGE] * 8 + [0])
        lancements, messages = [], []
        r = cli.superviser(lambda premiere: (lancements.append(premiere), next(codes))[1], attendre=lambda s: None, maximum=2, ecrire=messages.append)
        self.assertEqual((r, len(lancements), lancements[0], any(lancements[1:])), (0, 9, True, False), "huit redémarrages d'affilée ne sont pas des pannes : le navigateur ne se rouvre pas")
        self.assertTrue(all("Redémarrage demandé" in m for m in messages))


class Restauration(Base):
    def archive(self):
        sortie = io.BytesIO()
        sauvegarde.exporter({"config": CONFIG.parent, "donnees": A.DONNEES, "memoire": A.MEMOIRE}, sortie)
        return sortie.getvalue()

    def test_restaurer_depuis_la_page(self):
        (A.MEMOIRE / "NOTE.md").write_text("avant", encoding="utf-8")
        brut = self.archive()
        (A.MEMOIRE / "NOTE.md").write_text("après", encoding="utf-8")
        statut, r = requete("POST", "/api/restaurer", {"Content-Type": "application/zip"}, brut=brut)
        self.assertEqual(statut, 200, r)
        self.assertTrue(r["redemarrage_necessaire"])
        self.assertEqual((A.MEMOIRE / "NOTE.md").read_text(encoding="utf-8"), "avant")
        self.assertTrue(Path(r["secours"]).is_file(), "l'état d'avant est gardé")
        (A.MEMOIRE / "NOTE.md").unlink()

    def test_archives_refusees(self):
        mauvaise = io.BytesIO()
        with zipfile.ZipFile(mauvaise, "w") as z:
            z.writestr("manifeste.json", "{}")
            z.writestr("../evil.txt", "x")
        statut, r = requete("POST", "/api/restaurer", {"Content-Type": "application/zip"}, brut=mauvaise.getvalue())
        self.assertEqual(statut, 400)
        self.assertEqual(requete("POST", "/api/restaurer", {"Content-Type": "application/zip"}, brut=b"pas un zip")[0], 400)
        self.assertEqual(requete("POST", "/api/restaurer", {"Content-Type": "application/zip"}, brut=b"")[0], 400)
        self.assertFalse((A.MEMOIRE.parent / "evil.txt").exists())

    def test_restauration_reservee_a_cette_machine_et_authentifiee(self):
        self.assertEqual(requete("POST", "/api/restaurer", {"X-Token": "faux"}, brut=b"x")[0], 403)
        A.SECURITE = S.Securite(niveau=S.RESEAU, port=8777)
        self.assertEqual(requete("POST", "/api/restaurer", {"X-Token": A.JETON}, brut=b"x")[0], 401, "pas de session")
        session = self.session()
        statut, r = requete("POST", "/api/restaurer", dict(session, **{"X-Forwarded-For": "192.168.1.50"}), brut=self.archive())
        self.assertEqual(statut, 403, "un appareil appairé ne restaure pas")


class DansUnNavigateur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RACINE_TESTS / "tools"))
        import captures
        cls.captures = captures
        try:
            cls.chrome = captures.navigateur()
        except SystemExit:
            raise unittest.SkipTest("aucun navigateur trouvé")

    def charger(self, langue, ancre):
        with self.captures.serveur_demo({"LUTIN_LANGUE": langue}) as (port, tmp):
            r = subprocess.run([self.chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--user-data-dir=" + str(tmp / "profil"), "--virtual-time-budget=9000", "--enable-logging=stderr", "--v=0",
                                "--dump-dom", "http://127.0.0.1:%d/%s" % (port, ancre)], capture_output=True, timeout=180, encoding="utf-8", errors="replace")
        return r.stdout, [l for l in r.stderr.splitlines() if "CONSOLE" in l and ("rror" in l or "Uncaught" in l)]

    def test_page_acces_et_dossiers_de_travail(self):
        for langue, titre, bouton in (("fr", "Qui peut utiliser Lutin", "Enregistrer le niveau d'accès"), ("en", "Who can use Lutin", "Save the access level")):
            dom, erreurs = self.charger(langue, "#acces")
            self.assertEqual(erreurs, [], langue)
            texte = html.unescape(re.sub(r"<[^>]+>", " ", dom))
            self.assertIn(titre, texte)
            self.assertIn(bouton, texte)
            self.assertEqual(len(re.findall(r'name="niveauAcces"', dom)), 3, "trois niveaux proposés")
        dom, erreurs = self.charger("en", "#reglages")
        self.assertEqual(erreurs, [])
        liste = dom.split('id="listeTravaux"', 1)[1][:3000]
        self.assertIn("Project", html.unescape(re.sub(r"<[^>]+>", " ", liste)), "la liste des dossiers de travail est remplie")


if __name__ == "__main__":
    unittest.main()
