"""La langue côté serveur : réglage par l'API, page servie, messages d'erreur, mémoire de départ. (serveur réel sur 127.0.0.1)"""
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-langue-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9"}.items():
    os.environ.setdefault(cle, valeur)
os.environ["LUTIN_CONFIG"] = str(_TEMP / "config" / "config.json")          # jamais la vraie configuration de l'utilisateur
for d in ("projet", "donnees", "memoire", "config"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import config, i18n  # noqa: E402
from lutin import moteur as A  # noqa: E402

SERVEUR = ThreadingHTTPServer(("127.0.0.1", 0), A.Gestionnaire)
threading.Thread(target=SERVEUR.serve_forever, daemon=True).start()
PORT = SERVEUR.server_address[1]


def requete(methode, chemin, corps=None, jeton=True):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = {"Host": "127.0.0.1:%d" % PORT}
    if jeton:
        h["X-Token"] = A.JETON
    donnees = None
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


class LangueDuServeur(unittest.TestCase):
    def setUp(self):
        os.environ.pop("LUTIN_LANGUE", None)
        Path(os.environ["LUTIN_CONFIG"]).unlink(missing_ok=True)
        i18n.forcer(None)
        i18n._config["mtime"] = None

    def test_reglage_par_l_api_puis_page_et_messages_dans_la_langue(self):
        statut, etat = requete("GET", "/api/etat")
        self.assertEqual(statut, 200)
        self.assertIsNone(etat["langue_reglage"])
        self.assertIn(etat["langue"], ("fr", "en"))
        self.assertEqual(requete("POST", "/api/langue", {"valeur": "en"}), (200, {"langue": "en"}))
        statut, etat = requete("GET", "/api/etat")
        self.assertEqual((etat["langue"], etat["langue_reglage"]), ("en", "en"))
        statut, page = requete("GET", "/")
        self.assertIn("const LANGUE = 'en', DICO = {", page)
        self.assertEqual(requete("POST", "/api/skills-supprimer", {"nom": "../x"})[1], {"erreur": "Invalid skill name (letters, digits, hyphens, spaces, and .md)."})
        self.assertEqual(requete("POST", "/api/langue", {"valeur": "fr"}), (200, {"langue": "fr"}))
        self.assertIn("const LANGUE = 'fr', DICO = {};", requete("GET", "/")[1])
        self.assertEqual(requete("POST", "/api/skills-supprimer", {"nom": "../x"})[1], {"erreur": "Nom de skill invalide (lettres, chiffres, tirets, espaces, et .md)."})

    def test_valeur_inconnue_refusee_et_jeton_exige(self):
        statut, corps = requete("POST", "/api/langue", {"valeur": "klingon"})
        self.assertEqual(statut, 400)
        self.assertIn("fr, en", corps["erreur"])
        self.assertEqual(requete("POST", "/api/langue", {"valeur": "en"}, jeton=False)[0], 403)
        self.assertIsNone(json.loads(Path(os.environ["LUTIN_CONFIG"]).read_text(encoding="utf-8")).get("langue") if Path(os.environ["LUTIN_CONFIG"]).exists() else None)

    def test_la_variable_d_environnement_l_emporte_sur_le_reglage(self):
        requete("POST", "/api/langue", {"valeur": "fr"})
        os.environ["LUTIN_LANGUE"] = "en"
        try:
            self.assertEqual(requete("GET", "/api/etat")[1]["langue"], "en")
            self.assertEqual(requete("GET", "/api/etat")[1]["langue_reglage"], "fr")
        finally:
            os.environ.pop("LUTIN_LANGUE")

    def test_la_memoire_de_depart_est_dans_la_langue(self):
        os.environ["LUTIN_LANGUE"] = "en"
        try:
            dossiers = {"memoire": str(_TEMP / "memoire-en"), "donnees": str(_TEMP / "d-en"), "config": str(_TEMP / "c-en"), "cache": str(_TEMP / "ca-en")}
            config.preparer(dossiers)
            memoire = (_TEMP / "memoire-en" / "MEMOIRE.md").read_text(encoding="utf-8")
            self.assertIn("## Assistant notes", memoire)
            self.assertIn("Answer in the user's language", (_TEMP / "memoire-en" / "CONTEXTE.md").read_text(encoding="utf-8"))
            # le moteur retrouve la section des notes, quelle que soit la langue du modèle de départ
            self.assertEqual(A.position_notes(memoire), memoire.index("## Assistant notes") - 1)
            os.environ["LUTIN_LANGUE"] = "fr"
            dossiers_fr = {"memoire": str(_TEMP / "memoire-fr"), "donnees": str(_TEMP / "d-fr"), "config": str(_TEMP / "c-fr"), "cache": str(_TEMP / "ca-fr")}
            config.preparer(dossiers_fr)
            self.assertIn("## Notes de l'assistant", (_TEMP / "memoire-fr" / "MEMOIRE.md").read_text(encoding="utf-8"))
        finally:
            os.environ.pop("LUTIN_LANGUE", None)


if __name__ == "__main__":
    unittest.main()
