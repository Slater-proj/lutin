"""Le serveur fait-il respecter les trois niveaux d'accès ? (serveur réel sur 127.0.0.1, requêtes réelles, en-têtes falsifiés à la main)"""
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-secu-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import moteur as A  # noqa: E402
from lutin import securite as S  # noqa: E402

SERVEUR = ThreadingHTTPServer(("127.0.0.1", 0), A.Gestionnaire)
threading.Thread(target=SERVEUR.serve_forever, daemon=True).start()
PORT = SERVEUR.server_address[1]


def requete(methode, chemin, en_tetes=None, corps=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = {"Host": "127.0.0.1:%d" % PORT}
    h.update(en_tetes or {})
    donnees = None
    if corps is not None:
        donnees = json.dumps(corps).encode("utf-8")
        h["Content-Type"] = "application/json"
    c.request(methode, chemin, body=donnees, headers=h)
    r = c.getresponse()
    texte = r.read().decode("utf-8", "replace")
    resultat = (r.status, texte, dict((k.lower(), v) for k, v in r.getheaders()))
    c.close()
    return resultat


def json_de(texte):
    try:
        return json.loads(texte)
    except ValueError:
        return {}


class Base(unittest.TestCase):
    def setUp(self):
        self.avant = (A.SECURITE, A.APPAREILS, A.LIMITEUR_PIN, A.IP_LAN)
        A.APPAREILS = S.Appareils()
        A.LIMITEUR_PIN = S.LimiteurDebit(10, 60)

    def tearDown(self):
        A.SECURITE, A.APPAREILS, A.LIMITEUR_PIN, A.IP_LAN = self.avant

    def niveau(self, **kw):
        A.SECURITE = S.Securite(**kw)


class NiveauLocal(Base):
    def setUp(self):
        super().setUp()
        self.niveau(niveau=S.LOCAL)

    def test_la_page_contient_le_jeton_et_mermaid_est_strict(self):
        statut, page, _ = requete("GET", "/")
        self.assertEqual(statut, 200)
        self.assertIn(A.JETON, page)
        self.assertNotIn("securityLevel: 'loose'", page)
        self.assertIn("securityLevel: 'strict'", page)

    def test_les_api_en_lecture_exigent_le_jeton(self):
        self.assertEqual(requete("GET", "/api/skills")[0], 403)
        self.assertEqual(requete("GET", "/api/conversation?id=abcd1234")[0], 403)
        self.assertEqual(requete("GET", "/api/memoire", {"X-Token": "faux"})[0], 403)
        self.assertEqual(requete("GET", "/api/skills", {"X-Token": A.JETON})[0], 200)

    def test_les_api_en_ecriture_exigent_le_jeton(self):
        self.assertEqual(requete("POST", "/api/reglages", corps={"modele": "x"})[0], 403)
        self.assertEqual(requete("POST", "/api/reglages", {"X-Token": "faux"}, {"modele": "x"})[0], 403)

    def test_un_nom_d_hote_etranger_est_refuse_dns_rebinding(self):
        for chemin in ("/", "/api/skills", "/lib/highlight.min.js"):
            self.assertEqual(requete("GET", chemin, {"Host": "evil.example.com", "X-Token": A.JETON})[0], 403, chemin)
        self.assertEqual(requete("POST", "/api/reglages", {"Host": "evil.example.com", "X-Token": A.JETON}, {"mode": "technique"})[0], 403)

    def test_une_origine_etrangere_est_refusee_en_ecriture(self):
        h = {"X-Token": A.JETON}
        self.assertEqual(requete("POST", "/api/reglages", dict(h, Origin="http://evil.example.com"), {"mode": "technique"})[0], 403)
        self.assertEqual(requete("POST", "/api/reglages", dict(h, Origin="null"), {"mode": "technique"})[0], 403)
        self.assertEqual(requete("POST", "/api/reglages", dict(h, Origin="http://127.0.0.1:%d" % PORT), {"mode": "technique"})[0], 200)

    def test_appairage_inutile_en_local(self):
        statut, texte, _ = requete("POST", "/api/appairer", corps={"pin": "123456"})
        self.assertEqual(statut, 400)

    def test_le_code_pin_ne_se_demande_pas_sans_jeton(self):
        self.assertEqual(requete("POST", "/api/nouveau-pin", corps={})[0], 403)

    def test_entetes_de_securite_et_pas_de_traversee(self):
        _, _, h = requete("GET", "/")
        self.assertEqual(h.get("x-content-type-options"), "nosniff")
        self.assertEqual(h.get("referrer-policy"), "no-referrer")
        for chemin in ("/lib/C:/Windows/win.ini", "/lib/..%2f..%2fmoteur.py", "/lib/%2e%2e/moteur.py"):
            self.assertNotEqual(requete("GET", chemin)[0], 200, chemin)


class NiveauReseau(Base):
    def setUp(self):
        super().setUp()
        self.niveau(niveau=S.RESEAU)

    def test_sans_appareil_appaire_on_voit_la_page_de_connexion_pas_le_jeton(self):
        statut, page, _ = requete("GET", "/")
        self.assertEqual(statut, 200)
        self.assertIn("connexion", page)
        self.assertNotIn(A.JETON, page, "le jeton n'est jamais servi à un appareil non appairé")

    def test_api_refusee_sans_session_meme_avec_le_jeton_de_page(self):
        self.assertEqual(requete("GET", "/api/skills", {"X-Token": A.JETON})[0], 401)
        self.assertEqual(requete("POST", "/api/reglages", {"X-Token": A.JETON}, {"mode": "technique"})[0], 401)

    def test_appairage_par_pin(self):
        pin = A.APPAREILS.nouveau_pin()
        mauvais = "000000" if pin != "000000" else "111111"
        self.assertEqual(requete("POST", "/api/appairer", corps={"pin": mauvais})[0], 403)
        statut, texte, h = requete("POST", "/api/appairer", corps={"pin": pin, "nom": "Téléphone"})
        self.assertEqual(statut, 200)
        cookie = h["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertNotIn("Secure", cookie, "pas de HTTPS en réseau local simple")
        session = cookie.split(";")[0]
        statut, page, _ = requete("GET", "/", {"Cookie": session})
        self.assertIn(A.JETON, page, "appareil appairé : il reçoit la vraie page")
        self.assertEqual(requete("GET", "/api/skills", {"Cookie": session, "X-Token": A.JETON})[0], 200)
        self.assertEqual(requete("GET", "/api/skills", {"Cookie": session})[0], 403, "la session ne remplace pas le jeton de page")
        self.assertEqual(requete("POST", "/api/appairer", corps={"pin": pin})[0], 403, "un PIN ne sert qu'une fois")
        self.assertEqual(len(A.APPAREILS.liste()), 1)
        self.assertEqual(json_de(requete("POST", "/api/appareils", {"Cookie": session, "X-Token": A.JETON}, {})[1])["appareils"][0]["nom"], "Téléphone")
        requete("POST", "/api/appareils-revoquer", {"Cookie": session, "X-Token": A.JETON}, {})
        self.assertEqual(requete("GET", "/api/skills", {"Cookie": session, "X-Token": A.JETON})[0], 401, "session révoquée")

    def test_trop_d_essais_de_pin_sont_limites(self):
        A.APPAREILS.nouveau_pin()
        codes = [requete("POST", "/api/appairer", corps={"pin": "%06d" % i})[0] for i in range(12)]
        self.assertIn(429, codes)

    def test_la_console_de_la_machine_passe_sans_pin_et_obtient_un_pin(self):
        statut, texte, _ = requete("POST", "/api/nouveau-pin", {"X-Token": A.JETON_CONSOLE}, {})
        self.assertEqual(statut, 200)
        self.assertRegex(json_de(texte)["pin"], r"^\d{6}$")
        self.assertEqual(requete("GET", "/api/skills", {"X-Token": A.JETON_CONSOLE})[0], 200)

    def test_hote_public_refuse_en_reseau_local(self):
        self.assertEqual(requete("GET", "/", {"Host": "8.8.8.8"})[0], 403)
        self.assertEqual(requete("GET", "/", {"Host": "evil.example.com"})[0], 403)


class NiveauProxy(Base):
    def proxy(self, ips):
        self.niveau(niveau=S.PROXY, url_publique="https://lutin.exemple.fr", proxy_ips=ips)

    def test_identite_du_proxy_acceptee_depuis_le_proxy_declare(self):
        self.proxy(["127.0.0.1"])
        h = {"Host": "lutin.exemple.fr", "Remote-User": "alice"}
        statut, page, _ = requete("GET", "/", h)
        self.assertIn(A.JETON, page)
        self.assertEqual(requete("GET", "/api/skills", dict(h, **{"X-Token": A.JETON}))[0], 200)

    def test_en_tete_falsifie_ignore_quand_la_connexion_ne_vient_pas_du_proxy(self):
        self.proxy(["10.9.9.9"])                                  # le proxy déclaré n'est pas celui qui se connecte (ici 127.0.0.1)
        h = {"Host": "lutin.exemple.fr", "Remote-User": "admin"}
        statut, page, _ = requete("GET", "/", h)
        self.assertNotIn(A.JETON, page)
        self.assertIn("connexion", page)
        self.assertEqual(requete("GET", "/api/skills", dict(h, **{"X-Token": A.JETON}))[0], 401)

    def test_sans_identite_page_de_connexion(self):
        self.proxy(["127.0.0.1"])
        self.assertIn("connexion", requete("GET", "/", {"Host": "lutin.exemple.fr"})[1])

    def test_autre_nom_d_hote_refuse(self):
        self.proxy(["127.0.0.1"])
        self.assertEqual(requete("GET", "/", {"Host": "autre.exemple.fr", "Remote-User": "alice"})[0], 403)

    def test_le_cookie_est_secure_derriere_https(self):
        self.proxy(["10.9.9.9"])
        pin = A.APPAREILS.nouveau_pin()
        statut, _, h = requete("POST", "/api/appairer", {"Host": "lutin.exemple.fr", "Origin": "https://lutin.exemple.fr"}, {"pin": pin})
        self.assertEqual(statut, 200)
        self.assertIn("Secure", h["set-cookie"])

    def setUp(self):
        super().setUp()
        self.niveau(niveau=S.LOCAL)
        self.ancien = A.VERIFICATEUR
        self.appels = []
        A.VERIFICATEUR = lambda portee: (self.appels.append(portee), {"propositions": [{"cle": "k", "type": "maj", "modele": "m", "raison": "r"}], "erreurs": [], "catalogue": "absent"})[1]

    def tearDown(self):
        A.VERIFICATEUR = self.ancien
        super().tearDown()

    def test_les_trois_portees(self):
        for portee in ("maj", "nouveaux", "tout"):
            statut, texte, _ = requete("POST", "/api/modeles-verifier", {"X-Token": A.JETON}, {"portee": portee})
            self.assertEqual(statut, 200, portee)
            self.assertEqual(json_de(texte)["propositions"][0]["modele"], "m")
        self.assertEqual(self.appels, ["maj", "nouveaux", "tout"])
        requete("POST", "/api/modeles-verifier", {"X-Token": A.JETON}, {})
        self.assertEqual(self.appels[-1], "tout", "portée par défaut")

    def test_portee_inconnue_refusee(self):
        self.assertEqual(requete("POST", "/api/modeles-verifier", {"X-Token": A.JETON}, {"portee": "x"})[0], 400)
        self.assertEqual(self.appels, [])

    def test_exige_le_jeton_et_l_authentification(self):
        self.assertEqual(requete("POST", "/api/modeles-verifier", corps={"portee": "maj"})[0], 403)
        self.niveau(niveau=S.RESEAU)
        self.assertEqual(requete("POST", "/api/modeles-verifier", {"X-Token": A.JETON}, {"portee": "maj"})[0], 401)
        self.assertEqual(self.appels, [])

    def test_indisponible_hors_lanceur(self):
        A.VERIFICATEUR = None
        self.assertEqual(requete("POST", "/api/modeles-verifier", {"X-Token": A.JETON}, {"portee": "maj"})[0], 501)


class CommandesPortables(unittest.TestCase):
    """Les lectures sans accord et les chemins interdits, pour Windows ET pour Linux / macOS (le test tourne partout)."""

    def test_lectures_windows(self):
        lecture = A.construire_commandes_lecture(False)
        for ok in ("git status", "git diff HEAD", "dir", "dir docs", "type README.md", "where python", "echo bonjour", "python -V"):
            self.assertTrue(lecture.match(ok), ok)
        for non in ("ls", "cat fichier", "del x", "git push", "git status && del x", "type a | more", "rm -rf ."):
            self.assertFalse(lecture.match(non), non)

    def test_lectures_posix(self):
        lecture = A.construire_commandes_lecture(True)
        for ok in ("git status", "ls", "ls -la docs", "cat README.md", "pwd", "which python3", "echo bonjour"):
            self.assertTrue(lecture.match(ok), ok)
        for non in ("dir", "type x", "rm -rf .", "git push", "ls; rm x", "cat a > b", "sudo ls", "cat a | sh"):
            self.assertFalse(lecture.match(non), non)

    def test_chemins_hors_du_dossier_de_travail(self):
        windows, posix = A.construire_hors_projet(False), A.construire_hors_projet(True)
        for hors in ("type C:\\Windows\\win.ini", "dir \\\\serveur\\partage", "type ..\\secret", "git log --output=x"):
            self.assertTrue(windows.search(hors), hors)
        for hors in ("cat /etc/passwd", "ls /", "cat ~/.ssh/id_rsa", "ls ../x", "cat x=/etc/hosts", "cat 'a' '/etc/shadow'"):
            self.assertTrue(posix.search(hors), hors)
        for dedans in ("cat docs/notes.md", "ls src", "git log -3", "cat HEAD~1.txt"):
            self.assertFalse(posix.search(dedans), dedans)
        self.assertFalse(windows.search("dir /b"), "les options de dir sous Windows ne sont pas des chemins")

    def test_lecture_sure_combine_les_deux(self):
        self.assertTrue(A.commande_lecture_sure("git status") and not A.commande_lecture_sure("git status ../autre"))


if __name__ == "__main__":
    unittest.main()
