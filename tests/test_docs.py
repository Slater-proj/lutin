"""La documentation du dépôt : chaque lien et chaque image existent, et chaque page existe en anglais (X.md) et en français (X.fr.md), avec un lien vers l'autre langue."""
import re
import unittest
from pathlib import Path

import context  # noqa: F401

RACINE = Path(__file__).resolve().parent.parent
PAGES = [RACINE / "README.md", RACINE / "CONTRIBUTING.md", *[p for p in sorted((RACINE / "docs").glob("*.md")) if not p.name.endswith(".fr.md")]]
LIEN = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)|\!\[[^\]]*\]\(([^)\s]+)\)|<img[^>]+src=\"([^\"]+)\"|<a href=\"([^\"]+)\"")


def liens(chemin):
    texte = chemin.read_text(encoding="utf-8")
    texte = re.sub(r"```.*?```", "", texte, flags=re.S)          # les exemples de code ne sont pas des liens
    return [next(g for g in m.groups() if g) for m in LIEN.finditer(texte)]


class Documentation(unittest.TestCase):
    def fichiers_md(self):
        return sorted(RACINE.glob("*.md")) + sorted((RACINE / "docs").glob("*.md"))

    def test_chaque_lien_relatif_existe(self):
        casses = []
        for page in self.fichiers_md():
            for lien in liens(page):
                if lien.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                cible = (page.parent / lien.split("#")[0]).resolve()
                if not cible.exists():
                    casses.append("{} -> {}".format(page.relative_to(RACINE), lien))
        self.assertEqual(casses, [])

    def test_chaque_page_existe_dans_les_deux_langues_et_renvoie_a_l_autre(self):
        for en in PAGES:
            fr = en.with_name(en.stem + ".fr.md")
            self.assertTrue(fr.exists(), "{} n'a pas de version française".format(en.name))
            self.assertIn(fr.name, en.read_text(encoding="utf-8"), "{} ne renvoie pas vers {}".format(en.name, fr.name))
            self.assertIn(en.name, fr.read_text(encoding="utf-8"), "{} ne renvoie pas vers {}".format(fr.name, en.name))

    def test_pas_de_page_francaise_orpheline(self):
        for fr in list(RACINE.glob("*.fr.md")) + list((RACINE / "docs").glob("*.fr.md")):
            self.assertTrue(fr.with_name(fr.name.replace(".fr.md", ".md")).exists(), "{} n'a pas de version anglaise".format(fr.name))

    def test_le_readme_anglais_utilise_les_captures_anglaises(self):
        self.assertIn("assets/capture-conversation.png", (RACINE / "README.md").read_text(encoding="utf-8"))
        self.assertIn("assets/capture-conversation.fr.png", (RACINE / "README.fr.md").read_text(encoding="utf-8"))
        self.assertIn("banner.svg", (RACINE / "README.md").read_text(encoding="utf-8"))
        self.assertIn("banner.fr.svg", (RACINE / "README.fr.md").read_text(encoding="utf-8"))

    def test_le_fichier_compose_ne_depend_que_de_fichiers_qui_existent(self):
        for nom in ("docker-compose.yml", "docker-compose.gpu.yml", "docker-compose.slim.yml", "docker-compose.amd.yml", "Dockerfile", "docker/entrypoint.sh"):
            self.assertTrue((RACINE / nom).is_file(), nom)


if __name__ == "__main__":
    unittest.main()
