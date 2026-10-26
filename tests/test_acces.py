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
