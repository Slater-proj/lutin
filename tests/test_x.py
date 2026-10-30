"""L'addon X : signature OAuth 1.0a vérifiée, publication seulement sur ton clic, mentions (arriéré ignoré, brouillons, réponses seules plafonnées), plafond quotidien, secrets masqués."""
import base64
import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-x-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1",
                    "LUTIN_WEB_LOCAL": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import addons, repondeur  # noqa: E402
from lutin import addons_x as x  # noqa: E402

CLES = {"cle_api": "ck-cle-api-xxxx", "secret_api": "cs-secret-api-xxxx", "jeton": "12345-token-xxxx", "secret_jeton": "ts-secret-jeton-xxxx"}
SERVICE = {"mentions": [], "publies": [], "refus": False, "signatures_ok": [], "plan_gratuit": False}


class FauxX(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _rep(self, code, corps):
        d = json.dumps(corps).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def _signature_valide(self, methode):
        """Le serveur recalcule la signature OAuth 1.0a comme le ferait X, avec les secrets qu'il connaît."""
        entete = self.headers.get("Authorization", "")
        champs = dict(p.strip().split("=", 1) for p in entete[len("OAuth "):].split(","))
        champs = {k: urllib.parse.unquote(v.strip('"')) for k, v in champs.items()}
        recu = champs.pop("oauth_signature")
        p = urllib.parse.urlsplit(self.path)
        url = "http://127.0.0.1:%d%s" % (self.server.server_address[1], p.path)
        params = urllib.parse.parse_qsl(p.query, keep_blank_values=True) + list(champs.items())
        attendu = x_signature(methode, url, params, CLES["secret_api"], CLES["secret_jeton"])
        return recu == attendu and champs.get("oauth_consumer_key") == CLES["cle_api"] and champs.get("oauth_token") == CLES["jeton"]

    def do_GET(self):
        SERVICE["signatures_ok"].append(self._signature_valide("GET"))
        if SERVICE["refus"]:
            return self._rep(401, {"title": "Unauthorized", "detail": "Invalid token " + CLES["jeton"]})
        p = urllib.parse.urlsplit(self.path)
        if p.path == "/2/users/me":
            return self._rep(200, {"data": {"id": "1", "username": "lutin_compte", "name": "Lutin"}})
        if p.path == "/2/users/1/mentions":
            if SERVICE["plan_gratuit"]:
                return self._rep(403, {"title": "Client Forbidden", "detail": "Your plan does not allow reading"})
            q = dict(urllib.parse.parse_qsl(p.query))
            depuis = int(q.get("since_id", 0))
            visibles = [m for m in SERVICE["mentions"] if int(m["id"]) > depuis]
            if "since_id" not in q:
                visibles = SERVICE["mentions"][-int(q.get("max_results", 5)):]
            utilisateurs = [{"id": "7", "username": "alice", "name": "Alice"}, {"id": "8", "username": "troll", "name": "Troll"}, {"id": "1", "username": "lutin_compte", "name": "Lutin"}]
            plus_recent = max((int(m["id"]) for m in SERVICE["mentions"]), default=0)
            return self._rep(200, {"data": visibles, "includes": {"users": utilisateurs}, "meta": {"newest_id": str(plus_recent), "result_count": len(visibles)}})
        return self._rep(404, {})

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8") or "{}")
        SERVICE["signatures_ok"].append(self._signature_valide("POST"))
        if SERVICE["refus"]:
            return self._rep(401, {"title": "Unauthorized"})
        if self.path.startswith("/2/tweets"):
            SERVICE["publies"].append(corps)
            return self._rep(201, {"data": {"id": str(1000 + len(SERVICE["publies"])), "text": corps.get("text")}})
        return self._rep(404, {})


def x_signature(methode, url, params, cs, ts):
    enc = lambda s: urllib.parse.quote(str(s), safe="~")  # noqa: E731
    paires = sorted((enc(k), enc(v)) for k, v in params)
    base = "&".join([methode.upper(), enc(url), enc("&".join("%s=%s" % p for p in paires))])
    return base64.b64encode(hmac.new((enc(cs) + "&" + enc(ts)).encode(), base.encode(), hashlib.sha1).digest()).decode()


def mention(ident, auteur, texte):
    return {"id": str(ident), "author_id": str(auteur), "text": texte, "conversation_id": str(ident)}


class SignatureOAuth(unittest.TestCase):
    def test_vecteur_de_la_documentation(self):
        """L'exemple publié par X pour « Creating a signature » : même signature au caractère près."""
        # Les valeurs publiées dans la documentation de X (un exemple public, pas des identifiants) : coupées en deux pour que l'analyse de secrets ne les prenne pas pour de vrais.
        cle_client, nonce = "xvz1evFS4wEEPT" + "GEFPHBog", "kYjzVBB8Y0ZFabxSWbWovY3u" + "YSQ2pTgmZeNu2VS4cg"
        jeton = "370773112-GmHxMAgYyLbNEtIKZeRNFsMK" + "PR9EyMZeS9weJAEb"
        secret_client, secret_jeton = "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3Wp" + "wPAoE3Z7kBw", "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVH" + "tR2YPi5kE"
        params = [("status", "Hello Ladies + Gentlemen, a signed OAuth request!"), ("include_entities", "true"), ("oauth_consumer_key", cle_client), ("oauth_nonce", nonce),
                  ("oauth_signature_method", "HMAC-SHA1"), ("oauth_timestamp", "1318622958"), ("oauth_token", jeton), ("oauth_version", "1.0")]
        self.assertEqual(addons.signature_oauth1("POST", "https://api.twitter.com/1.1/statuses/update.json", params, secret_client, secret_jeton),
                         "hCtSmYh+iHYCEqBWrE7C7hYmtUk=")

    def test_entete(self):
        e = addons.entete_oauth1("GET", "https://api.x.com/2/users/1/mentions?since_id=5&max_results=20", {"consumer_key": "a", "consumer_secret": "b", "token": "c", "token_secret": "d"}, nonce="n", horodatage=1)
        self.assertTrue(e.startswith("OAuth "))
        self.assertIn('oauth_consumer_key="a"', e)
        self.assertIn('oauth_signature="', e)
        self.assertNotIn("since_id", e, "les paramètres de la requête signent, mais ne sont pas répétés dans l'en-tête")


class X(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur = HTTPServer(("127.0.0.1", 0), FauxX)
        port = cls.serveur.server_address[1]
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()
        livres = _TEMP / "livres" / "x"
        livres.mkdir(parents=True)
        reel = Path(addons.__file__).parent / "addons_livres" / "x"
        manifeste = json.loads((reel / "addon.json").read_text(encoding="utf-8"))
        manifeste["hotes"] = ["127.0.0.1"]
        (livres / "addon.json").write_text(json.dumps(manifeste), encoding="utf-8")
        (livres / "flux.json").write_text((reel / "flux.json").read_text(encoding="utf-8").replace("https://api.x.com", "http://127.0.0.1:%d" % port), encoding="utf-8")
        addons.DOSSIER_LIVRE = _TEMP / "livres"
        cls.vrai_reponse = staticmethod(repondeur.reponse)

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()

    def setUp(self):
        SERVICE.update(mentions=[], publies=[], refus=False, signatures_ok=[], plan_gratuit=False)
        x.VIVANT.update(erreur="", moi={})
        for f in addons.dossier_donnees().rglob("*"):
            if f.is_file():
                f.unlink()
        addons.enregistrer_reglages("x", dict(CLES, mentions="oui", regles="ton:agressif -> ignorer\nde:@troll -> ignorer\ntexte:*prix* -> brouillon: Donne le lien des tarifs.\n* -> brouillon"))
        self.demandes = []
        repondeur.reponse = self.faux_modele
        self.vrai_ton = repondeur.juger_ton
        repondeur.juger_ton = lambda t: "agressif" if "nul" in t else "neutre"

    def tearDown(self):
        repondeur.reponse = self.vrai_reponse
        repondeur.juger_ton = self.vrai_ton

    def faux_modele(self, ident, canal, cle, titre, message, consigne="", arret=None, pause=2):
        self.demandes.append({"canal": canal, "titre": titre, "message": message, "consigne": consigne})
        return "Merci pour ton message ! " + "x" * 400

    def test_verification_signature_acceptee_par_le_service_et_secrets_masques(self):
        v = addons.verifier("x")
        self.assertTrue(v["ok"], v)
        self.assertIn("lutin_compte", v["etapes"][0]["message"])
        self.assertTrue(SERVICE["signatures_ok"] and all(SERVICE["signatures_ok"]), "le service a pu recalculer la signature")
        for secret in CLES.values():
            self.assertNotIn(secret, json.dumps(addons.decrire("x")), "la page ne voit jamais les clés")
        SERVICE["refus"] = True
        v = addons.verifier("x")
        self.assertFalse(v["ok"])
        self.assertNotIn(CLES["jeton"], json.dumps(v), "le service répète le jeton : il est masqué")
        with self.assertRaises(addons.ErreurAddon):
            addons.enregistrer_reglages("x", {"mentions": "peut-etre"})

    def test_rien_n_est_publie_sans_clic_puis_publier_et_plafond(self):
        self.assertEqual(x.lire()["publications"], [])
        vrai = x.redaction
        x.redaction = lambda brief: "Un message à propos de : " + brief
        try:
            x.action("rediger", {"brief": "le lancement", "nombre": 2})
        finally:
            x.redaction = vrai
        p = x.etat()["publications"]
        self.assertEqual((len(p), p[0]["etat"]), (2, "brouillon"))
        self.assertEqual(SERVICE["publies"], [], "rédigé n'est pas publié")
        x.action("modifier", {"publication": p[0]["id"], "texte": "Texte corrigé"})
        x.action("publier", {"publication": p[0]["id"]})
        self.assertEqual(SERVICE["publies"], [{"text": "Texte corrigé"}])
        self.assertTrue(all(SERVICE["signatures_ok"]))
        with self.assertRaises(addons.ErreurAddon):
            x.action("publier", {"publication": p[0]["id"]})                        # déjà publiée : jamais deux fois
        with self.assertRaises(addons.ErreurAddon):
            x.action("publier", {"publication": "zzzz"})
        with self.assertRaises(addons.ErreurAddon):
            x.action("rediger", {"brief": ""})
        x.action("supprimer", {"publication": p[1]["id"]})
        self.assertEqual(len(x.etat()["publications"]), 1)
        e = x.lire()
        e["jours"] = {"jour": time.strftime("%Y-%m-%d"), "publies": x.PUBLICATIONS_PAR_JOUR}
        x.ecrire(e)
        with self.assertRaises(addons.ErreurAddon) as err:
            x.publier("encore un")
        self.assertIn("Plafond", str(err.exception))

    def test_programmer_publie_a_l_heure_et_une_seule_fois(self):
        e = x.lire()
        e["publications"] = [{"id": "aaaa", "texte": "Pour plus tard", "etat": "brouillon"}, {"id": "bbbb", "texte": "Brouillon jamais publié", "etat": "brouillon"}]
        x.ecrire(e)
        x.action("programmer", {"publication": "aaaa", "quand": time.time() + 3600})
        self.assertEqual(x.publier_dues(), 0, "l'heure n'est pas venue")
        self.assertEqual(x.publier_dues(time.time() + 7200), 1)
        self.assertEqual(x.publier_dues(time.time() + 9000), 0, "déjà publiée")
        self.assertEqual([p["text"] for p in SERVICE["publies"]], ["Pour plus tard"], "le brouillon non programmé n'est jamais publié")
        with self.assertRaises(addons.ErreurAddon):
            x.action("programmer", {"publication": "bbbb", "quand": "pas une date"})
        SERVICE["refus"] = True
        x.action("programmer", {"publication": "bbbb", "quand": time.time() - 5})
        SERVICE["publies"].clear()
        self.assertEqual(x.publier_dues(), 0)
        self.assertEqual(next(p for p in x.lire()["publications"] if p["id"] == "bbbb")["etat"], "erreur", "un échec est signalé, pas retenté en boucle")

    def test_mentions_arriere_ignore_regles_brouillons_et_reponses_seules(self):
        SERVICE["mentions"] = [mention(10, 7, "ancienne mention")]
        self.assertEqual(x.lire_mentions(), 0)
        self.assertEqual(self.demandes, [], "l'arriéré est ignoré")
        SERVICE["mentions"] += [mention(11, 7, "Salut, tu fais quoi ?"), mention(12, 8, "Tu es nul"), mention(13, 7, "Quel est le prix ?"), mention(14, 1, "ma propre mention")]
        self.assertEqual(x.lire_mentions(), 4)
        self.assertEqual([d["message"] for d in self.demandes], ["Message de @alice : Salut, tu fais quoi ?", "Message de @alice : Quel est le prix ?"], "le troll est ignoré, ma propre mention aussi")
        self.assertIn("Donne le lien des tarifs.", self.demandes[1]["consigne"])
        self.assertIn("280", self.demandes[0]["consigne"])
        r = x.etat()["reponses"]
        self.assertEqual((len(r), r[0]["de"], r[0]["a"]), (2, "@alice", "11"))
        self.assertLessEqual(len(r[0]["texte"]), 280, "coupé à 280 caractères")
        self.assertEqual(SERVICE["publies"], [], "brouillon : rien n'est publié sans toi")
        self.assertEqual(x.lire_mentions(), 0, "rien de nouveau : rien n'est retraité")
        x.action("envoyer", {"brouillon": r[0]["id"], "texte": "Je regarde ça !"})
        self.assertEqual(SERVICE["publies"], [{"text": "Je regarde ça !", "reply": {"in_reply_to_tweet_id": "11"}}])
        x.action("rejeter", {"brouillon": r[1]["id"]})
        self.assertEqual(x.etat()["reponses"], [])
        addons.enregistrer_reglages("x", {"regles": "* -> auto: Sois bref."})
        SERVICE["mentions"] += [mention(20 + i, 7, "question %d" % i) for i in range(x.AUTO_PAR_JOUR + 2)]
        SERVICE["publies"].clear()
        x.lire_mentions()
        self.assertEqual(len(SERVICE["publies"]), x.AUTO_PAR_JOUR, "au plus 10 réponses seules par jour")
        self.assertEqual(len(x.etat()["reponses"]), 2, "le reste attend ta validation")

    def test_lecture_desactivee_ou_refusee_par_la_formule_de_l_api(self):
        addons.enregistrer_reglages("x", {"mentions": "non"})
        SERVICE["mentions"] = [mention(1, 7, "x")]
        self.assertEqual(x.lire_mentions(), 0)
        self.assertEqual(SERVICE["signatures_ok"], [], "lecture désactivée : X n'est même pas interrogé")
        addons.enregistrer_reglages("x", {"mentions": "oui"})
        SERVICE["plan_gratuit"] = True
        x.lire_mentions()
        self.assertEqual(x.lire_mentions(), -1)
        self.assertIn("403", x.etat()["erreur"], "la formule gratuite ne lit pas les mentions : l'erreur de X est montrée")

    def test_tronquer(self):
        self.assertEqual(x.tronquer("court"), "court")
        long = ("Une phrase. " * 40).strip()
        t = x.tronquer(long)
        self.assertTrue(len(t) <= 280 and t.endswith("."), "coupé à la fin d'une phrase")
        self.assertLessEqual(len(x.tronquer("a" * 500)), 280)


if __name__ == "__main__":
    unittest.main()
