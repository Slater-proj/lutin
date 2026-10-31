"""Écrire des PDF et des documents Word : fichiers valides, relus, accents conservés, accord demandé, sauvegarde de l'ancienne version, jamais en dehors du dossier de travail."""
import os
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.dom import minidom

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-documents-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402
from lutin import documents, extraction, revue  # noqa: E402

MARKDOWN = """# Bilan de la semaine

Un paragraphe avec du **gras**, de l'*italique* et du `code`, des accents : é è à ç œ — « guillemets » et un euro €.

## Liste

- première puce
- deuxième puce
  - sous-puce

1. un
2. deux

```
print("bonjour")
```

---

| nom | valeur |
| a | 1 |
"""


class Documents(unittest.TestCase):
    def ctx(self, accord=True):
        self.accords = []
        return {"accord": lambda t, d, df, auto=False: (self.accords.append(t), accord)[1], "essai": False, "auto_ecriture": False, "stop": None, "tour": {"id": "t", "conversation": "abcdef01", "fichiers": {}}, "conv": {"id": "abcdef01"}}

    def test_le_pdf_est_un_vrai_pdf_et_se_relit(self):
        octets = documents.pdf(MARKDOWN, "Rapport")
        self.assertTrue(octets.startswith(b"%PDF-1.4") and octets.rstrip().endswith(b"%%EOF"))
        # la table des références pointe sur de vrais objets
        debut = int(re.search(rb"startxref\n(\d+)", octets).group(1))
        self.assertEqual(octets[debut:debut + 4], b"xref")
        for n, m in enumerate(re.finditer(rb"(\d{10}) 00000 n", octets), 1):
            self.assertEqual(octets[int(m.group(1)):].split(b" ")[0], b"%d" % n)
        f = _TEMP / "essai.pdf"
        f.write_bytes(octets)
        texte = "\n".join(t for _, t in extraction.parties(str(f)))
        for attendu in ("Rapport", "Bilan de la semaine", "é è à ç œ", "première puce", "deuxième puce", "bonjour", "1 / "):
            self.assertIn(attendu, texte)

    def test_un_long_texte_fait_plusieurs_pages_sans_deborder(self):
        octets = documents.pdf("\n\n".join("Paragraphe %d : " % i + "mot " * 80 for i in range(40)))
        self.assertGreater(len(re.findall(rb"/Type /Page /Parent", octets)), 2)
        for _, taille, x, _, texte in [(0, 11, 56, 0, "x" * 5)]:
            self.assertLess(documents._largeur(texte, "F1", taille) + x, documents.PAGE[0] - documents.MARGE)
        for ligne in documents._couper("supercalifragilistic" * 12 + " fin", "F1", 11, 483):
            self.assertLessEqual(documents._largeur(ligne, "F1", 11), 483 + 1)

    def test_les_caracteres_hors_alphabet_latin_ne_cassent_pas_le_pdf(self):
        octets = documents.pdf("Emoji 😀 et idéogramme 漢字 et parenthèses (a) \\ fin")
        f = _TEMP / "exotique.pdf"
        f.write_bytes(octets)
        texte = "\n".join(t for _, t in extraction.parties(str(f)))
        self.assertIn("parenthèses (a)", texte)

    def test_le_docx_est_valide_et_se_relit(self):
        octets = documents.docx(MARKDOWN, "Rapport")
        f = _TEMP / "essai.docx"
        f.write_bytes(octets)
        with zipfile.ZipFile(f) as z:
            self.assertIsNone(z.testzip())
            for nom in z.namelist():
                minidom.parseString(z.read(nom))                                 # chaque partie est du XML bien formé
            document = z.read("word/document.xml").decode("utf-8")
        self.assertIn("<w:b/>", document)
        self.assertIn("<w:i/>", document)
        self.assertIn('w:val="Titre1"', document)
        texte = "\n".join(t for _, t in extraction.parties(str(f)))
        for attendu in ("Rapport", "Bilan de la semaine", "é è à ç œ", "première puce", "bonjour", "gras"):
            self.assertIn(attendu, texte)

    def test_les_caracteres_interdits_en_xml_sont_retires(self):
        octets = documents.docx("avant \x00\x0b\x1f après & <balise>")
        with zipfile.ZipFile(__import__("io").BytesIO(octets)) as z:
            minidom.parseString(z.read("word/document.xml"))

    def test_l_outil_demande_l_accord_ecrit_relit_et_sauvegarde(self):
        ctx = self.ctx()
        res = revue.appeler_outil("creer_document", {"chemin": "docs/bilan.pdf", "contenu": MARKDOWN, "titre": "Bilan"}, ctx)
        self.assertIn("relu", res)
        self.assertEqual(len(self.accords), 1)
        f = _m.RACINE / "docs" / "bilan.pdf"
        self.assertTrue(f.read_bytes().startswith(b"%PDF"))
        res = revue.appeler_outil("creer_document", {"chemin": "docs/bilan.pdf", "contenu": "# Version 2"}, self.ctx())
        self.assertIn("Ancienne version sauvegardée", res)
        res = revue.appeler_outil("creer_document", {"chemin": "docs/note.docx", "contenu": "Bonjour"}, self.ctx())
        self.assertTrue(zipfile.is_zipfile(_m.RACINE / "docs" / "note.docx"), res)

    def test_markdown_et_texte_sont_ecrits_tels_quels(self):
        revue.appeler_outil("creer_document", {"chemin": "docs/lisez.md", "contenu": "# Titre\n\ntexte"}, self.ctx())
        self.assertEqual((_m.RACINE / "docs" / "lisez.md").read_text(encoding="utf-8"), "# Titre\n\ntexte")

    def test_refus_format_inconnu_et_chemin_hors_du_dossier(self):
        revue.appeler_outil("creer_document", {"chemin": "docs/refuse.pdf", "contenu": "x"}, self.ctx(accord=False))
        self.assertFalse((_m.RACINE / "docs" / "refuse.pdf").exists())
        with self.assertRaises(_m.ErreurOutil):
            revue.appeler_outil("creer_document", {"chemin": "docs/x.xyz", "contenu": "x"}, self.ctx())
        with self.assertRaises(_m.ErreurOutil):
            revue.appeler_outil("creer_document", {"chemin": "../dehors.pdf", "contenu": "x"}, self.ctx())
        with self.assertRaises(_m.ErreurOutil):
            revue.appeler_outil("creer_document", {"chemin": "docs/gros.pdf", "contenu": "x" * (documents.TAILLE_MAX + 1)}, self.ctx())


if __name__ == "__main__":
    unittest.main()
