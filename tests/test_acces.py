"""La page Accès : niveau de sécurité (qui peut le changer, ce qui est refusé), code PIN et QR, redémarrage, restauration d'une sauvegarde, dossiers de travail — côté serveur et dans un vrai navigateur."""
import http.client
import io
import json
import os
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

from lutin import access, backup  # noqa: E402
from lutin import core as A  # noqa: E402
from lutin import security as S  # noqa: E402

SERVEUR = ThreadingHTTPServer(("127.0.0.1", 0), A.Handler)
threading.Thread(target=SERVEUR.serve_forever, daemon=True).start()
PORT = SERVEUR.server_address[1]
RACINE_TESTS = Path(__file__).resolve().parent.parent


def requete(methode, chemin, en_tetes=None, corps=None, brut=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = {"Host": "127.0.0.1:%d" % PORT, "X-Token": A.TOKEN}
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
        self.avant = (A.SECURITY, A.DEVICES)
        A.SECURITY = S.Security(niveau=S.LOCAL, port=8777)
        A.DEVICES = S.Devices()
        CONFIG.write_text(json.dumps({"schema": 1, "installe": True, "securite": {"niveau": "local", "port": 8777}, "emplacements": {"travail": str(_TEMP / "projet"), "travaux": [], "travail_actif": ""}}), encoding="utf-8")
        os.environ.pop("LUTIN_DOCKER", None)
        os.environ.pop("LUTIN_SUPERVISE", None)

    def tearDown(self):
        A.SECURITY, A.DEVICES = self.avant

    def session(self):
        pin = A.DEVICES.nouveau_pin()
        jeton = A.DEVICES.appairer(pin, "Téléphone")
        return {"Cookie": "{}={}".format(S.NAME_COOKIE, jeton)}


class NiveauDAcces(Base):
    def test_etat(self):
        statut, e = requete("GET", "/api/v1/access")
        self.assertEqual(statut, 200)
        self.assertEqual((e["level"], e["can_change"], e["docker"], e["restart_needed"]), ("local", True, False, False))
        self.assertEqual(sorted(x["id"] for x in e["levels"]), ["local", "network", "proxy"])
        self.assertIn("PIN", e["warnings"]["network"])
        self.assertTrue(e["address"].startswith("http://") and e["address"].endswith(":8777/"))

    def test_changer_le_niveau_enregistre_et_demande_un_redemarrage(self):
        statut, r = requete("PATCH", "/api/v1/access", corps={"level": "network"})
        message = r.get("error", {}).get("message", "")
        self.assertEqual((statut, "comprends" in message or "compris" in message), (400, True), "ouvrir l'accès demande de confirmer")
        statut, r = requete("PATCH", "/api/v1/access", corps={"level": "network", "understood": True})
        self.assertEqual((statut, r["restart_needed"], r["saved"]["level"]), (200, True, "network"))
        self.assertEqual(json.loads(CONFIG.read_text(encoding="utf-8"))["securite"]["niveau"], "reseau")
        self.assertEqual(A.SECURITY.niveau, "local", "rien ne change avant le redémarrage")
        self.assertTrue(requete("GET", "/api/v1/access")[1]["restart_needed"])
        self.assertTrue(requete("GET", "/api/v1/status")[1]["restart"]["needed"])
        statut, r = requete("PATCH", "/api/v1/access", corps={"level": "local"})
        self.assertEqual((statut, r["restart_needed"]), (200, False), "revenir au niveau actuel annule l'attente")
        self.assertFalse(requete("GET", "/api/v1/status")[1]["restart"]["needed"])

    def test_le_niveau_proxy_demande_l_adresse_et_le_proxy(self):
        statut, r = requete("PATCH", "/api/v1/access", corps={"level": "proxy", "understood": True})
        self.assertEqual(statut, 400)
        self.assertIn("Sécurité", r["error"]["message"])
        statut, r = requete("PATCH", "/api/v1/access", corps={"level": "proxy", "understood": True, "public_url": "https://lutin.exemple.fr", "proxy_ips": ["127.0.0.1"]})
        self.assertEqual(statut, 200)
        enregistre = json.loads(CONFIG.read_text(encoding="utf-8"))["securite"]
        self.assertEqual((enregistre["url_publique"], enregistre["proxy_ips"]), ("https://lutin.exemple.fr", ["127.0.0.1"]))
        self.assertEqual(requete("PATCH", "/api/v1/access", corps={"level": "klingon"})[0], 400)

    def test_dans_docker_le_niveau_vient_de_la_variable(self):
        with mock.patch.dict(os.environ, {"LUTIN_DOCKER": "1"}):
            e = requete("GET", "/api/v1/access")[1]
            self.assertEqual((e["docker"], e["can_change"]), (True, False))
            statut, r = requete("PATCH", "/api/v1/access", corps={"level": "network", "understood": True})
            self.assertEqual(statut, 409)
            self.assertIn("LUTIN_NIVEAU", r["error"]["message"])

    def test_qui_peut_changer_le_niveau(self):
        A.SECURITY = S.Security(niveau=S.RESEAU, port=8777)
        sur_la_machine = dict(self.session())
        self.assertTrue(requete("GET", "/api/v1/access", sur_la_machine)[1]["can_change"], "le navigateur de cette machine, au niveau réseau")
        for intrus in ({"X-Forwarded-For": "192.168.1.50"}, {"Forwarded": "for=192.168.1.50"}, {"Via": "1.1 proxy"}, {"Host": "lutin.maison:8777"}, {"X-Real-IP": "10.0.0.2"}):
            statut, e = requete("GET", "/api/v1/access", dict(sur_la_machine, **intrus))
            if statut == 200:
                self.assertFalse(e["can_change"], intrus)
                self.assertEqual(requete("PATCH", "/api/v1/access", dict(sur_la_machine, **intrus), {"level": "local"})[0], 403, intrus)
        A.SECURITY = S.Security(niveau=S.PROXY, port=8777, url_publique="https://lutin.exemple.fr", proxy_ips=["127.0.0.1"])
        statut, e = requete("GET", "/api/v1/access", {"Remote-User": "moi", "Host": "lutin.exemple.fr"})
        if statut == 200:
            self.assertFalse(e["can_change"], "derrière un proxy installé sur la machine : jamais, le proxy ne prouve rien")


class AppairageEtAppareils(Base):
    def test_pin_et_appareils(self):
        A.SECURITY = S.Security(niveau=S.RESEAU, port=8777)
        session = self.session()
        statut, r = requete("POST", "/api/v1/devices/pairing-code", session, {})
        self.assertEqual((statut, len(r["code"]), r["valid_seconds"]), (201, 6, 600))
        e = requete("GET", "/api/v1/devices", session)[1]
        self.assertEqual([a["name"] for a in e["devices"]], ["Téléphone"])
        ident = e["devices"][0]["id"]
        self.assertEqual(requete("DELETE", "/api/v1/devices/" + ident, session)[1]["devices"], [])
        self.assertEqual(requete("GET", "/api/v1/skills", session)[0], 401, "l'appareil déconnecté ne passe plus")

    def test_qr(self):
        A.SECURITY = S.Security(niveau=S.RESEAU, port=8777)
        statut, r = requete("POST", "/api/v1/devices/pairing-code", {"X-Token": A.CONSOLE_TOKEN}, {})          # at the level « network » even this browser pairs: the console asks
        qr = r["qr"]
        self.assertEqual((statut, len(qr["rows"])), (201, qr["size"]))
        self.assertTrue(all(set(ligne) <= {"0", "1"} and len(ligne) == qr["size"] for ligne in qr["rows"]), "the address another device opens, drawn as a QR code")

    def test_la_page_de_connexion_lit_le_pin_du_qr_code(self):
        A.SECURITY = S.Security(niveau=S.RESEAU, port=8777)
        statut, page = requete("GET", "/", {"X-Token": ""})
        self.assertEqual(statut, 200)
        self.assertIn("pin=([0-9]{6})", page)
        self.assertIn("history.replaceState", page, "le code ne reste pas dans l'adresse affichée")


class CommandesDuProjet(Base):
    def test_route_des_commandes_claude(self):
        c = A.ROOT / ".claude" / "commands"
        c.mkdir(parents=True, exist_ok=True)
        (c / "bonjour.md").write_text("---\ndescription: Salue\n---\nDis bonjour à $ARGUMENTS", encoding="utf-8")
        try:
            statut, r = requete("GET", "/api/v1/project-commands/bonjour?args=le+monde")
            self.assertEqual((statut, r), (200, {"text": "Dis bonjour à le monde"}))
            self.assertEqual(requete("GET", "/api/v1/project-commands/absente")[0], 404)
            self.assertEqual(requete("GET", "/api/v1/project-commands/..%2F..%2Fx")[0], 404)
            self.assertEqual([x["name"] for x in requete("GET", "/api/v1/project-commands")[1]["commands"]], ["bonjour"])
        finally:
            (c / "bonjour.md").unlink()


class Documents(Base):
    def test_rechercher_dans_un_pdf_un_document_word_et_lire_avec_citation(self):
        from test_extraction import ecrire_zip, pdf_simple
        docs = A.ROOT / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "panne.pdf").write_bytes(pdf_simple(True))
        ecrire_zip(docs / "guide.docx", {"word/document.xml": "<w:document><w:p><w:r><w:t>La sauvegarde du NAS se lance chaque nuit à trois heures.</w:t></w:r></w:p></w:document>"})
        (docs / "casse.docx").write_bytes(b"pas un zip")
        try:
            etat = requete("GET", "/api/v1/documents")[1]
            self.assertEqual(sorted(f["name"] for f in etat["files"]), ["docs/casse.docx", "docs/guide.docx", "docs/panne.pdf"])
            self.assertEqual([e["nom"] for e in etat["errors"]], ["docs/casse.docx"], "un document illisible est signalé, il ne casse rien")
            statut, r = requete("GET", "/api/v1/documents/search?q=" + "sauvegarde+nuit")
            self.assertEqual(statut, 200)
            self.assertEqual(r["passages"][0]["source"], "docs/guide.docx")
            statut, r = requete("GET", "/api/v1/documents/search?q=" + "proc%C3%A9dure+d%C3%A9ploiement")
            self.assertEqual((r["passages"][0]["source"], r["passages"][0]["title"]), ("docs/panne.pdf", "Page 1"), "la citation donne la page")
            self.assertEqual(requete("GET", "/api/v1/documents/search?q=")[0], 400)
            self.assertEqual(requete("GET", "/api/v1/documents/search?q=le+la")[0], 400)
            lu = A.read_tool("docs/panne.pdf")
            self.assertIn("Deuxième ligne : procédure", lu)
            self.assertIn("## Page 1", lu)
            self.assertIn("Page 1", A.recall_tool("déploiement"))
            with self.assertRaisesRegex(A.ToolError, "illisible"):
                A.read_tool("docs/casse.docx")
            self.assertTrue(list((A.DATA / "cache-documents").glob("*.json")), "le texte extrait est gardé : pas de nouvelle lecture au prochain démarrage")
        finally:
            for n in ("panne.pdf", "guide.docx", "casse.docx"):
                (docs / n).unlink(missing_ok=True)


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
        from lutin import updates
        with mock.patch.object(updates, "latest_release_detail", return_value=("99.0.0", "https://example/roue.whl", "")):
            statut, r = requete("POST", "/api/v1/lutin/check", corps={})
        self.assertEqual(statut, 200)
        self.assertEqual(r["latest"], "99.0.0")
        self.assertEqual(r["new_version"]["version"], "99.0.0")

    def test_hors_ligne_le_dit(self):
        from lutin import updates
        with mock.patch.object(updates, "latest_release_detail", return_value=(None, None, "api.github.com : timed out ; github.com : timed out")):
            statut, r = requete("POST", "/api/v1/lutin/check", corps={})
        self.assertEqual(statut, 503)
        self.assertIn("GitHub", r["error"]["message"])
        self.assertIn("timed out", r["error"]["message"], "la vraie cause est montrée, pas un message vague")


class Planification(Base):
    def setUp(self):
        super().setUp()
        from lutin import scheduled_tasks
        self.p = scheduled_tasks
        scheduled_tasks.path().unlink(missing_ok=True)

    def tearDown(self):
        self.p.path().unlink(missing_ok=True)
        super().tearDown()

    def test_ajout_validation_et_suppression(self):
        for corps in ({"name": "", "request": "x", "time": "08:00", "days": [0]}, {"name": "a", "request": "x", "time": "8h", "days": [0]},
                      {"name": "a", "request": "x", "time": "08:00", "days": []}, {"name": "a", "request": "x", "time": "08:00", "days": [9]}):
            self.assertEqual(requete("POST", "/api/v1/scheduled-tasks", corps=corps)[0], 400, corps)
        statut, t = requete("POST", "/api/v1/scheduled-tasks", corps={"name": "Matin", "request": "résume le dépôt", "time": "08:30", "days": [0, 1, 2]})
        self.assertEqual(statut, 201)
        etat = requete("GET", "/api/v1/scheduled-tasks")[1]["tasks"]
        self.assertEqual([x["name"] for x in etat], ["Matin"])
        self.assertTrue(etat[0]["next_run"])
        self.assertFalse(requete("PATCH", "/api/v1/scheduled-tasks/" + t["id"], corps={"active": False})[1]["active"])
        self.assertEqual(requete("GET", "/api/v1/scheduled-tasks")[1]["tasks"][0]["next_run"], "", "en pause : pas de prochaine exécution")
        self.assertEqual(requete("DELETE", "/api/v1/scheduled-tasks/" + t["id"])[0], 200)
        self.assertEqual(requete("DELETE", "/api/v1/scheduled-tasks/" + t["id"])[0], 404)

    def test_canaux_de_notification_par_l_api_sans_jamais_renvoyer_un_secret(self):
        from lutin import notifications
        notifications.path_of().unlink(missing_ok=True)
        statut, r = requete("POST", "/api/v1/notification-channels", corps={"name": "Tel", "type": "gotify", "params": {"url": "http://h:8080", "jeton": "SECRET1"}})
        self.assertEqual(statut, 201)
        liste = requete("GET", "/api/v1/notification-channels")[1]
        self.assertNotIn("SECRET1", json.dumps(liste))
        self.assertEqual([c["name"] for c in liste["channels"]], ["Tel"])
        self.assertEqual(requete("POST", "/api/v1/notification-channels", corps={"name": "x", "type": "inconnu", "params": {}})[0], 400)
        t = self.p.add("Matin", "x", "08:00", [0], notifier=liste["channels"][0]["id"])
        self.assertEqual(requete("PATCH", "/api/v1/scheduled-tasks/" + t["id"], corps={"notify": ""})[1]["notify"], "")
        self.assertEqual(requete("PATCH", "/api/v1/scheduled-tasks/" + t["id"], corps={"notify": "zzzz"})[0], 400)
        self.assertEqual(requete("DELETE", "/api/v1/notification-channels/" + liste["channels"][0]["id"])[0], 200)

    def test_les_notifications_se_reglent_depuis_cette_machine_seulement(self):
        A.SECURITY = S.Security(niveau=S.RESEAU, port=8777)
        statut, _ = requete("POST", "/api/v1/notification-channels", en_tetes=dict(self.session(), **{"X-Forwarded-For": "192.168.1.20"}), corps={"name": "a", "type": "ntfy", "params": {"sujet": "x"}})
        self.assertEqual(statut, 403)

    def test_gestion_reservee_a_cette_machine(self):
        A.SECURITY = S.Security(niveau=S.RESEAU, port=8777)
        statut, r = requete("POST", "/api/v1/scheduled-tasks", en_tetes=dict(self.session(), **{"X-Forwarded-For": "192.168.1.20"}), corps={"name": "a", "request": "x", "time": "08:00", "days": [0]})
        self.assertEqual(statut, 403, "un appareil appairé, ou un relais, ne planifie pas")
        self.assertEqual(self.p.read(), [])

    def test_echeance(self):
        from datetime import datetime
        t = {"actif": True, "heure": "08:30", "jours": [0, 1, 2, 3, 4], "cree": "2026-10-20T07:00:00", "derniere_exec": ""}
        lundi = lambda h, m: datetime(2026, 10, 26, h, m)  # noqa: E731
        self.assertIsNone(self.p.due(t, lundi(8, 29)), "pas avant l'heure")
        self.assertIsNotNone(self.p.due(t, lundi(8, 31)))
        self.assertIsNotNone(self.p.due(t, lundi(23, 0)), "PC allumé en retard : rattrapé le jour même")
        self.assertIsNone(self.p.due(dict(t, derniere_exec="2026-10-26T08:31:00"), lundi(9, 0)), "déjà faite aujourd'hui")
        self.assertIsNone(self.p.due(dict(t, cree="2026-10-26T09:00:00"), lundi(9, 30)), "créée après l'heure : attend demain")
        self.assertIsNone(self.p.due(t, datetime(2026, 10, 31, 9, 0)), "samedi : pas un jour choisi")
        self.assertIsNone(self.p.due(dict(t, actif=False), lundi(9, 0)))

    @staticmethod
    def faux_tour(reponse="voici", appels=None, evenements=()):
        """Un tour qui fait ce que fait le vrai : ajoute la demande, la réponse (ou rien), et écrit la conversation."""
        def tour(conv, texte, emit, r, stop, depuis, identite="", lecture_seule=False):
            if appels is not None:
                appels.append((conv["titre"], texte, lecture_seule, A.ACTIVE_TURNS.get(conv["id"]) is stop))
            conv["messages"].append({"role": "user", "content": texte})
            if reponse:
                conv["messages"].append({"role": "assistant", "content": reponse})
            A.conv_write(conv)
            for e in evenements:
                emit(e)
        return tour

    def test_execution_en_lecture_seule_dans_une_conversation_planifiee(self):
        t = self.p.add("Matin", "résume le dépôt", "08:30", [0, 1, 2, 3, 4, 5, 6])
        appels = []
        with mock.patch.object(A, "turn", side_effect=self.faux_tour(appels=appels)):
            ident = self.p.execute(t["id"])
        self.assertEqual([(a[0], a[2], a[3]) for a in appels], [("⏰ Matin", True, True)])
        self.assertTrue(appels[0][1].startswith("(Tâche planifiée « Matin » lancée le "), "la demande est datée : le modèle sait quel jour et quelle heure il est")
        self.assertTrue(appels[0][1].endswith("résume le dépôt"))
        self.assertEqual(A.ACTIVE_TURNS, {}, "la machine est libérée après la tâche")
        fait = self.p.read()[0]
        self.assertEqual((fait["derniere_conv"], fait["derniere_etat"]), (ident, "ok"))

    def test_une_tache_garde_une_seule_conversation(self):
        t = self.p.add("Heure", "donne-moi l'heure", "19:00", [0, 1, 2, 3, 4, 5, 6])
        avant = len(A.conv_list())
        with mock.patch.object(A, "turn", side_effect=self.faux_tour("il est 19 h")):
            premiere = self.p.execute(t["id"])
            seconde = self.p.execute(t["id"])
        self.assertEqual(premiere, seconde, "chaque exécution continue la même conversation")
        self.assertEqual(len(A.conv_list()), avant + 1)
        messages = A.conv_read(premiere)["messages"]
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user", "assistant"])

    def test_une_conversation_supprimee_est_recreee(self):
        t = self.p.add("Heure", "x", "19:00", [0, 1, 2, 3, 4, 5, 6])
        with mock.patch.object(A, "turn", side_effect=self.faux_tour()):
            premiere = self.p.execute(t["id"])
            A.conv_delete(premiere)
            seconde = self.p.execute(t["id"])
        self.assertNotEqual(premiere, seconde)
        self.assertEqual(A.conv_read(seconde)["titre"], "⏰ Heure")

    def test_un_moteur_muet_n_est_jamais_un_rien_fait_silencieux(self):
        t = self.p.add("Heure", "x", "19:00", [0, 1, 2, 3, 4, 5, 6])
        with mock.patch.object(A, "turn", side_effect=self.faux_tour(reponse="")):
            ident = self.p.execute(t["id"])
        self.assertEqual(self.p.read()[0]["derniere_etat"], "erreur")
        dernier = A.conv_read(ident)["messages"][-1]
        self.assertEqual(dernier["role"], "assistant")
        self.assertTrue(dernier["content"].startswith("⚠"), "le problème est écrit dans la conversation")

    def test_une_erreur_du_tour_est_ecrite_dans_la_conversation(self):
        t = self.p.add("Heure", "x", "19:00", [0, 1, 2, 3, 4, 5, 6])
        with mock.patch.object(A, "turn", side_effect=self.faux_tour(reponse="", evenements=[{"type": "erreur", "texte": "Ollama ne répond pas"}])):
            ident = self.p.execute(t["id"])
        self.assertEqual(self.p.read()[0]["derniere_etat"], "erreur")
        self.assertIn("Ollama ne répond pas", A.conv_read(ident)["messages"][-1]["content"])

    def test_le_resultat_part_sur_le_canal_associe(self):
        from lutin import notifications
        envois = []
        with mock.patch.object(notifications, "find", lambda i: {"id": i, "nom": "Tel"}), mock.patch.object(notifications, "send", lambda canal, titre, msg, ouvrir=None: envois.append((canal, titre, msg))):
            t = self.p.add("Heure", "x", "19:00", [0, 1, 2, 3, 4, 5, 6], notifier="abcd1234")
            with mock.patch.object(A, "turn", side_effect=self.faux_tour("il est 19 h")):
                self.p.execute(t["id"])
        self.assertEqual(envois, [("abcd1234", "⏰ Heure", "il est 19 h")])
        self.assertEqual(self.p.read()[0]["derniere_notif"], "ok")

    def test_une_notification_qui_echoue_est_dite_sans_casser_la_tache(self):
        from lutin import notifications
        def casse(canal, titre, msg, ouvrir=None):
            raise ValueError("« Tel » n'a pas répondu")
        with mock.patch.object(notifications, "find", lambda i: {"id": i}), mock.patch.object(notifications, "send", casse):
            t = self.p.add("Heure", "x", "19:00", [0, 1, 2, 3, 4, 5, 6], notifier="abcd1234")
            with mock.patch.object(A, "turn", side_effect=self.faux_tour("ok")):
                self.p.execute(t["id"])
        fait = self.p.read()[0]
        self.assertEqual(fait["derniere_etat"], "ok")
        self.assertIn("n'a pas répondu", fait["derniere_notif"])

    def test_un_canal_inconnu_est_refuse(self):
        with self.assertRaises(ValueError):
            self.p.add("a", "x", "08:00", [0], notifier="zzzz")

    def test_une_erreur_est_notee_et_ne_casse_pas_la_boucle(self):
        t = self.p.add("Matin", "x", "08:30", [0, 1, 2, 3, 4, 5, 6])
        with mock.patch.object(A, "turn", side_effect=RuntimeError("boum")):
            self.p.execute(t["id"])
        self.assertEqual(self.p.read()[0]["derniere_etat"], "erreur")

    def test_pas_de_demarrage_si_une_reponse_est_en_cours(self):
        from datetime import datetime, timedelta
        t = self.p.add("Matin", "x", "00:00", [0, 1, 2, 3, 4, 5, 6])
        self.p.modify(t["id"], cree=(datetime.now() - timedelta(days=2)).isoformat(timespec="seconds"))
        A.ACTIVE_TURNS["abcdef12"] = threading.Event()
        try:
            with mock.patch.object(self.p, "execute") as ex:
                self.assertIsNone(self.p.run_first_due())
                ex.assert_not_called()
        finally:
            A.ACTIVE_TURNS.pop("abcdef12", None)
        with mock.patch.object(self.p, "execute") as ex:
            self.assertEqual(self.p.run_first_due(), t["id"])
            ex.assert_called_once_with(t["id"])


class Redemarrage(Base):
    def test_refuse_sans_superviseur_ni_conteneur(self):
        statut, r = requete("POST", "/api/v1/lutin/restart", corps={})
        self.assertEqual(statut, 409)
        self.assertIn("lutin", r["error"]["message"])

    def test_avec_superviseur(self):
        os.environ["LUTIN_SUPERVISE"] = "1"
        with mock.patch.object(access.threading, "Timer") as timer:
            self.assertEqual(requete("POST", "/api/v1/lutin/restart", corps={}), (200, {"restarting": True}))
            args = timer.call_args[0]
            self.assertEqual((args[0] > 0, args[1], args[2]), (True, os._exit, [access.RESTART_CODE]))
            timer.return_value.start.assert_called_once()
            A.ACTIVE_TURNS["abcd1234"] = object()
            try:
                statut, r = requete("POST", "/api/v1/lutin/restart", corps={})
                self.assertEqual(statut, 409)
                self.assertIn("réponse est en cours", r["error"]["message"])
            finally:
                A.ACTIVE_TURNS.pop("abcd1234", None)

    def test_le_superviseur_relance_sans_compter_une_panne(self):
        from lutin import cli
        codes = iter([access.RESTART_CODE] * 8 + [0])
        lancements, messages = [], []
        r = cli.supervise(lambda premiere: (lancements.append(premiere), next(codes))[1], attendre=lambda s: None, maximum=2, ecrire=messages.append)
        self.assertEqual((r, len(lancements), lancements[0], any(lancements[1:])), (0, 9, True, False), "huit redémarrages d'affilée ne sont pas des pannes : le navigateur ne se rouvre pas")
        self.assertTrue(all("Redémarrage demandé" in m for m in messages))


class Restauration(Base):
    def archive(self):
        sortie = io.BytesIO()
        backup.export({"config": CONFIG.parent, "donnees": A.DATA, "memoire": A.MEMORY}, sortie)
        return sortie.getvalue()

    def test_restaurer_depuis_la_page(self):
        (A.MEMORY / "NOTE.md").write_text("avant", encoding="utf-8")
        brut = self.archive()
        (A.MEMORY / "NOTE.md").write_text("après", encoding="utf-8")
        statut, r = requete("POST", "/api/v1/backup/restore", {"Content-Type": "application/zip"}, brut=brut)
        self.assertEqual(statut, 200, r)
        self.assertTrue(r["restart_needed"])
        self.assertEqual((A.MEMORY / "NOTE.md").read_text(encoding="utf-8"), "avant")
        self.assertTrue(Path(r["kept_before"]).is_file(), "l'état d'avant est gardé")
        (A.MEMORY / "NOTE.md").unlink()

    def test_archives_refusees(self):
        mauvaise = io.BytesIO()
        with zipfile.ZipFile(mauvaise, "w") as z:
            z.writestr("manifeste.json", "{}")
            z.writestr("../evil.txt", "x")
        statut, r = requete("POST", "/api/v1/backup/restore", {"Content-Type": "application/zip"}, brut=mauvaise.getvalue())
        self.assertEqual(statut, 400)
        self.assertEqual(requete("POST", "/api/v1/backup/restore", {"Content-Type": "application/zip"}, brut=b"pas un zip")[0], 400)
        self.assertEqual(requete("POST", "/api/v1/backup/restore", {"Content-Type": "application/zip"}, brut=b"")[0], 400)
        self.assertFalse((A.MEMORY.parent / "evil.txt").exists())

    def test_une_requete_refusee_avec_un_gros_corps_recoit_quand_meme_sa_reponse(self):
        """Un refus répondu sans lire le corps réinitialisait la connexion de l'appelant (il perdait la réponse) : le serveur lit ce qui reste après avoir répondu."""
        for _ in range(15):
            self.assertEqual(requete("POST", "/api/v1/backup/restore", {"X-Token": "faux"}, brut=b"x" * 300_000)[0], 403)

    def test_restauration_reservee_a_cette_machine_et_authentifiee(self):
        self.assertEqual(requete("POST", "/api/v1/backup/restore", {"X-Token": "faux"}, brut=b"x")[0], 403)
        A.SECURITY = S.Security(niveau=S.RESEAU, port=8777)
        self.assertEqual(requete("POST", "/api/v1/backup/restore", {"X-Token": A.TOKEN}, brut=b"x")[0], 401, "pas de session")
        session = self.session()
        statut, r = requete("POST", "/api/v1/backup/restore", dict(session, **{"X-Forwarded-For": "192.168.1.50"}), brut=self.archive())
        self.assertEqual(statut, 403, "un appareil appairé ne restaure pas")


if __name__ == "__main__":
    unittest.main()
