"""Pages construites par JavaScript (Reddit et autres) : Lutin lit ce que le serveur annonce sans JavaScript, dit ce qu'il ne peut pas faire, propose quoi faire, et ne cherche jamais à contourner un blocage."""
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-webjs-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import core as A  # noqa: E402,F401
from lutin import web  # noqa: E402

COQUILLE = """<!DOCTYPE html><html><head><title>reddit</title>
<meta property="og:title" content="Quel moteur pour 32 Go de RAM ? : r/LocalLLaMA">
<meta property="og:description" content="Je cherche un moteur pour un modèle à experts, des avis ?">
<meta name="description" content="Fil de discussion">
<script type="application/ld+json">{"@type": "DiscussionForumPosting", "headline": "Quel moteur ?"}</script>
<style>.x{color:red}</style></head><body><shreddit-app></shreddit-app><script>window.__INIT__={}</script></body></html>"""


class Meta(unittest.TestCase):
    def test_meta_et_donnees_structurees_sont_lues_sans_le_script(self):
        m = web.MetaPage()
        m.feed(COQUILLE)
        texte = m.texte()
        self.assertIn("Quel moteur pour 32 Go de RAM", texte)
        self.assertIn("modèle à experts", texte)
        self.assertIn("DiscussionForumPosting", texte)
        self.assertNotIn("__INIT__", texte)
        self.assertNotIn("color:red", texte)

    def test_html_casse_ne_plante_pas(self):
        m = web.MetaPage()
        m.feed("<html><meta property='og:title' content='x'><script type='application/ld+json'>{ pas fini")
        self.assertIn("x", m.texte())


class Conseil(unittest.TestCase):
    def test_conseil_general(self):
        t = web.conseil_page_javascript("https://exemple.org/page")
        self.assertIn("JavaScript", t)
        self.assertIn("trombone", t)
        self.assertNotIn("Reddit", t)

    def test_conseil_reddit_dit_la_verite_sans_promettre_de_contournement(self):
        for adresse in ("https://www.reddit.com/r/LocalLLaMA/comments/abc/x/", "https://old.reddit.com/r/x/", "https://redd.it/abc"):
            with self.subTest(adresse=adresse):
                t = web.conseil_page_javascript(adresse)
                self.assertIn("Reddit refuse", t)
                self.assertIn("je n'essaie pas de passer outre", t)
        self.assertNotIn("Reddit", web.conseil_page_javascript("https://notreddit.com/x"), "un autre domaine n'est pas Reddit")
        self.assertNotIn("Reddit", web.conseil_page_javascript("https://exemple.org/reddit.com"))


if __name__ == "__main__":
    unittest.main()
