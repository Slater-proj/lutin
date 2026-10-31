"""L'aperçu d'une page : capture montrée à l'utilisateur, texte affiché et erreurs de console rendus au modèle ; seulement les fichiers du projet et les adresses de cette machine."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-apercu-test-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402
from lutin import apercu, images, revue  # noqa: E402

# Un « navigateur » de théâtre : écrit une capture PNG là où on le lui demande, affiche un DOM, et se plaint dans la console.
FAUX = _TEMP / "faux_navigateur.py"
FAUX.write_text('''import sys
args = sys.argv[1:]
for a in args:
    if a.startswith("--screenshot="):
        open(a.split("=", 1)[1], "wb").write(b"\\x89PNG\\r\\n\\x1a\\n" + b"x" * 200)
        sys.stderr.write('[1:2:1031/000000.000:INFO:CONSOLE:12] "Uncaught ReferenceError: demarrer is not defined", source: file:///projet/page.html (12)\\n')
        sys.stderr.write('[1:2:1031/000000.000:INFO:CONSOLE:3] "bonjour de la page", source: file:///projet/page.html (3)\\n')
    if a == "--dump-dom":
        sys.stdout.write("<html><head><title>Ma page</title><style>p{}</style></head><body><h1>Titre visible</h1><script>var x=1</script><p>Un &eacute;l&eacute;ment</p></body></html>")
''', encoding="utf-8")


class Apercu(unittest.TestCase):
    def ctx(self, accord=True):
        self.accords = []
        return {"accord": lambda t, d, df, auto=False: (self.accords.append(t), accord)[1], "auto_commandes": False, "essai": False}

    def setUp(self):
        (_m.RACINE / "page.html").write_text("<html></html>", encoding="utf-8")
        self.vrai = apercu.navigateur
        apercu.navigateur = lambda: [sys.executable, str(FAUX)]

    def tearDown(self):
        apercu.navigateur = self.vrai

    def test_la_capture_est_montree_et_le_texte_rendu_au_modele(self):
        ctx = self.ctx()
        res = revue.appeler_outil("apercu_page", {"chemin": "page.html", "largeur": 900, "hauteur": 600}, ctx)
        self.assertEqual(len(self.accords), 1)
        self.assertIn("Titre de la page : Ma page", res)
        self.assertIn("Titre visible Un élément", res, "le texte affiché, sans script ni style")
        self.assertNotIn("var x", res)
        self.assertIn("demarrer is not defined", res)
        self.assertIn("1 erreur(s)", res)
        self.assertIn("bonjour de la page", res)
        octets, mime = images.lire(ctx["medias"][0])
        self.assertEqual(mime, "image/png")
        self.assertTrue(octets.startswith(b"\x89PNG"))

    def test_refus_et_essai_a_blanc_n_ouvrent_rien(self):
        ctx = self.ctx(accord=False)
        res = revue.appeler_outil("apercu_page", {"chemin": "page.html"}, ctx)
        self.assertIn("Refusé", res)
        self.assertNotIn("medias", ctx)

    def test_seuls_les_fichiers_du_projet_et_les_adresses_locales(self):
        for cible in ("https://example.com/", "http://192.168.1.5/x", "../dehors.html", "inexistant.html", "file:///C:/Windows/win.ini"):
            with self.assertRaises(_m.ErreurOutil, msg=cible):
                apercu.adresse(cible)
        self.assertTrue(apercu.adresse("page.html").startswith("file:///"))
        self.assertEqual(apercu.adresse("http://127.0.0.1:8000/a"), "http://127.0.0.1:8000/a")
        self.assertEqual(apercu.adresse("http://localhost/"), "http://localhost/")

    def test_sans_navigateur_le_message_est_clair(self):
        apercu.navigateur = lambda: None
        with self.assertRaises(_m.ErreurOutil) as e:
            revue.appeler_outil("apercu_page", {"chemin": "page.html"}, self.ctx())
        self.assertIn("Aucun navigateur", str(e.exception))

    def test_dimensions_invalides(self):
        with self.assertRaises(_m.ErreurOutil):
            revue.appeler_outil("apercu_page", {"chemin": "page.html", "largeur": "large"}, self.ctx())


if __name__ == "__main__":
    unittest.main()
