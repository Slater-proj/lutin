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
from lutin import core as A  # noqa: E402

SERVEUR = ThreadingHTTPServer(("127.0.0.1", 0), A.Handler)
threading.Thread(target=SERVEUR.serve_forever, daemon=True).start()
PORT = SERVEUR.server_address[1]


def requete(methode, chemin, corps=None, jeton=True):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = {"Host": "127.0.0.1:%d" % PORT}
    if jeton:
        h["X-Token"] = A.TOKEN
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
        i18n.force(None)
        i18n._config["mtime"] = None

    def test_reglage_par_l_api_puis_page_et_messages_dans_la_langue(self):
        statut, etat = requete("GET", "/api/v1/language")
        self.assertEqual(statut, 200)
        self.assertEqual(etat["choice"], "auto")
        self.assertIn(etat["language"], ("fr", "en"))
        self.assertEqual(requete("PATCH", "/api/v1/language", {"language": "en"}), (200, {"language": "en", "choice": "en"}))
        self.assertEqual(requete("GET", "/api/v1/status")[1]["language"], "en")
        statut, page = requete("GET", "/")
        self.assertIn('<html lang="en">', page, "the page is served in the language")
        self.assertEqual(requete("DELETE", "/api/v1/skills/x*y")[1]["error"]["message"], "Invalid skill name (letters, digits, hyphens, spaces, and .md).")
        self.assertEqual(requete("PATCH", "/api/v1/language", {"language": "fr"}), (200, {"language": "fr", "choice": "fr"}))
        self.assertIn('<html lang="fr">', requete("GET", "/")[1])
        self.assertEqual(requete("DELETE", "/api/v1/skills/x*y")[1]["error"]["message"], "Nom de skill invalide (lettres, chiffres, tirets, espaces, et .md).")

    def test_valeur_inconnue_refusee_et_jeton_exige(self):
        statut, corps = requete("PATCH", "/api/v1/language", {"language": "klingon"})
        self.assertEqual(statut, 400)
        self.assertIn("fr, en", corps["error"]["message"])
        self.assertEqual(requete("PATCH", "/api/v1/language", {"language": "en"}, jeton=False)[0], 403)
        self.assertIsNone(json.loads(Path(os.environ["LUTIN_CONFIG"]).read_text(encoding="utf-8")).get("langue") if Path(os.environ["LUTIN_CONFIG"]).exists() else None)

    def test_la_variable_d_environnement_l_emporte_sur_le_reglage(self):
        requete("PATCH", "/api/v1/language", {"language": "fr"})
        os.environ["LUTIN_LANGUE"] = "en"
        try:
            self.assertEqual(requete("GET", "/api/v1/language")[1], {"language": "en", "choice": "fr"})
        finally:
            os.environ.pop("LUTIN_LANGUE")

    def test_la_memoire_de_depart_est_dans_la_langue(self):
        os.environ["LUTIN_LANGUE"] = "en"
        try:
            dossiers = {"memoire": str(_TEMP / "memoire-en"), "donnees": str(_TEMP / "d-en"), "config": str(_TEMP / "c-en"), "cache": str(_TEMP / "ca-en")}
            config.prepare(dossiers)
            memoire = (_TEMP / "memoire-en" / "MEMOIRE.md").read_text(encoding="utf-8")
            self.assertIn("## Assistant notes", memoire)
            self.assertIn("Answer in the user's language", (_TEMP / "memoire-en" / "CONTEXTE.md").read_text(encoding="utf-8"))
            # le moteur retrouve la section des notes, quelle que soit la langue du modèle de départ
            self.assertEqual(A.notes_position(memoire), memoire.index("## Assistant notes") - 1)
            os.environ["LUTIN_LANGUE"] = "fr"
            dossiers_fr = {"memoire": str(_TEMP / "memoire-fr"), "donnees": str(_TEMP / "d-fr"), "config": str(_TEMP / "c-fr"), "cache": str(_TEMP / "ca-fr")}
            config.prepare(dossiers_fr)
            self.assertIn("## Notes de l'assistant", (_TEMP / "memoire-fr" / "MEMOIRE.md").read_text(encoding="utf-8"))
        finally:
            os.environ.pop("LUTIN_LANGUE", None)


    def test_les_resultats_d_outils_sont_dans_la_langue(self):
        """Ce que les outils renvoient (affiché dans la conversation et lu par le modèle) suit la langue : on n'a pas un modèle qui répond en anglais à des résultats en français."""
        (_TEMP / "projet" / "a.txt").write_text("un\ndeux\n", encoding="utf-8")
        os.environ["LUTIN_LANGUE"] = "en"
        try:
            with self.assertRaisesRegex(A.ToolError, "Path refused: outside the project"):
                A.safe_path("../x")
            with self.assertRaisesRegex(A.ToolError, "File not found: absent.txt"):
                A.read_tool("absent.txt")
            self.assertIn("lines 1 to 2 of 2", A.read_tool("a.txt"))
            self.assertEqual(A.search_tool("introuvable_xyz"), "No result.")
        finally:
            os.environ["LUTIN_LANGUE"] = "fr"
        with self.assertRaisesRegex(A.ToolError, "Fichier introuvable : absent.txt"):
            A.read_tool("absent.txt")
        self.assertEqual(A.search_tool("introuvable_xyz"), "Aucun résultat.")


if __name__ == "__main__":
    unittest.main()
