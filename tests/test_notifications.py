"""Notifications : canaux Gotify / ntfy / Telegram / webhook, secrets jamais renvoyés, envoi sans suivre de redirection, erreurs lisibles ; tout avec de faux serveurs."""
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-notif-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import core as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import notifications as N  # noqa: E402

JETON_TG = "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


class Reponse:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return b"{}"


class Canaux(unittest.TestCase):
    def setUp(self):
        N.chemin().unlink(missing_ok=True)
        self.envois = []

        def ouvrir(req, timeout=0):
            self.envois.append((req.full_url, json.loads(req.data.decode("utf-8")), {k.lower(): v for k, v in req.header_items()}))
            return Reponse()
        self.ouvrir = ouvrir

    def test_gotify_envoie_titre_message_et_jeton_dans_l_en_tete(self):
        N.ajouter("Tel", "gotify", {"url": "http://192.168.1.10:8080/", "jeton": "SECRET1", "priorite": "7"})
        canal = N.lister()[0]
        N.envoyer(canal["id"], "⏰ Heure", "il est 19 h", self.ouvrir)
        url, corps, en_tetes = self.envois[0]
        self.assertEqual(url, "http://192.168.1.10:8080/message")
        self.assertEqual((corps["title"], corps["message"], corps["priority"]), ("⏰ Heure", "il est 19 h", 7))
        self.assertEqual(en_tetes["x-gotify-key"], "SECRET1")

    def test_ntfy_utilise_le_serveur_public_par_defaut_et_un_jeton_facultatif(self):
        N.ajouter("N", "ntfy", {"sujet": "mes_alertes"})
        N.envoyer(N.lister()[0]["id"], "t", "m", self.ouvrir)
        url, corps, en_tetes = self.envois[0]
        self.assertEqual((url, corps["topic"]), ("https://ntfy.sh", "mes_alertes"))
        self.assertNotIn("authorization", en_tetes)

    def test_telegram_et_webhooks(self):
        N.ajouter("T", "telegram", {"chat_id": "-100123", "jeton": JETON_TG})
        N.ajouter("D", "webhook", {"url": "https://discord.example/api/webhooks/1/abc", "format": "discord"})
        N.ajouter("S", "webhook", {"url": "https://hooks.example/x", "format": "slack"})
        N.ajouter("J", "webhook", {"url": "https://hooks.example/y"})
        for c in N.lister():
            N.envoyer(c["id"], "Titre", "Texte", self.ouvrir)
        corps = {u: c for u, c, _ in self.envois}
        self.assertIn("api.telegram.org/bot" + JETON_TG + "/sendMessage", next(u for u in corps if "telegram" in u))
        self.assertIn("Texte", corps["https://discord.example/api/webhooks/1/abc"]["content"])
        self.assertIn("Texte", corps["https://hooks.example/x"]["text"])
        self.assertEqual(corps["https://hooks.example/y"], {"title": "Titre", "message": "Texte"})

    def test_les_secrets_ne_sont_jamais_renvoyes(self):
        N.ajouter("Tel", "gotify", {"url": "http://h:8080", "jeton": "SECRET1"})
        N.ajouter("D", "webhook", {"url": "https://discord.example/api/webhooks/1/SECRET2"})
        N.ajouter("T", "telegram", {"chat_id": "1", "jeton": JETON_TG})
        texte = json.dumps(N.lister())
        for secret in ("SECRET1", "SECRET2", JETON_TG):
            self.assertNotIn(secret, texte)
        self.assertEqual(N.lister()[0]["secrets_definis"], ["jeton"])

    def test_validation_claire(self):
        for type_, params in (("gotify", {"url": "ftp://x", "jeton": "a"}), ("gotify", {"url": "http://h", "jeton": ""}), ("gotify", {"url": "http://u:p@h", "jeton": "a"}),
                              ("ntfy", {"sujet": "a b"}), ("telegram", {"chat_id": "abc", "jeton": JETON_TG}), ("telegram", {"chat_id": "1", "jeton": "pasunjeton"}),
                              ("webhook", {"url": "https://x", "format": "xml"}), ("inconnu", {})):
            with self.assertRaises(ValueError, msg=(type_, params)):
                N.ajouter("x", type_, params)
        with self.assertRaises(ValueError):
            N.ajouter("", "ntfy", {"sujet": "ok"})
        self.assertEqual(N.lister(), [])

    def test_pas_de_doublon_de_nom_et_nombre_borne(self):
        N.ajouter("Tel", "ntfy", {"sujet": "a"})
        with self.assertRaises(ValueError):
            N.ajouter("tel", "ntfy", {"sujet": "b"})
        for i in range(N.MAX_CANAUX - 1):
            N.ajouter("c%d" % i, "ntfy", {"sujet": "s%d" % i})
        with self.assertRaises(ValueError):
            N.ajouter("trop", "ntfy", {"sujet": "z"})

    def test_une_erreur_http_ou_reseau_est_lisible_et_sans_secret(self):
        N.ajouter("Tel", "gotify", {"url": "http://h:8080", "jeton": "SECRET1"})
        ident = N.lister()[0]["id"]

        def refus(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 401, "non", {}, None)

        def muet(req, timeout=0):
            raise urllib.error.URLError(OSError("connexion refusée"))
        with self.assertRaises(ValueError) as e:
            N.envoyer(ident, "t", "m", refus)
        self.assertIn("401", str(e.exception))
        with self.assertRaises(ValueError) as e:
            N.envoyer(ident, "t", "m", muet)
        self.assertIn("connexion refusée", str(e.exception))
        self.assertNotIn("SECRET1", str(e.exception))

    def test_aucune_redirection_n_est_suivie(self):
        h = N._SansRedirection()
        self.assertIsNone(h.redirect_request(mock.Mock(), None, 302, "x", {}, "http://ailleurs"))

    def test_le_message_est_borne_et_le_canal_supprimable(self):
        N.ajouter("Tel", "ntfy", {"sujet": "a"})
        ident = N.lister()[0]["id"]
        N.envoyer(ident, "t" * 500, "m" * 20000, self.ouvrir)
        corps = self.envois[0][1]
        self.assertLessEqual(len(corps["message"]), N.MESSAGE_MAX)
        self.assertLessEqual(len(corps["title"]), 120)
        N.supprimer(ident)
        self.assertEqual(N.lister(), [])
        with self.assertRaises(ValueError):
            N.supprimer(ident)
        with self.assertRaises(ValueError):
            N.envoyer(ident, "t", "m", self.ouvrir)

    def test_le_test_envoie_un_message(self):
        N.ajouter("Tel", "ntfy", {"sujet": "a"})
        self.assertEqual(N.tester(N.lister()[0]["id"], self.ouvrir), {"ok": True})
        self.assertIn("test", self.envois[0][1]["message"])

    def test_les_types_decrivent_les_champs_pour_la_page(self):
        t = {x["id"]: x for x in N.types()}
        self.assertEqual(set(t), {"gotify", "ntfy", "telegram", "webhook"})
        self.assertTrue(any(c["secret"] for c in t["gotify"]["champs"]))


if __name__ == "__main__":
    unittest.main()
