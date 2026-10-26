"""Lire le texte des documents (PDF, Word, LibreOffice, PowerPoint, Excel, HTML) sans dépendance : formats construits à la main, et un vrai PDF fabriqué par Chrome."""
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock

import context  # noqa: F401
from lutin import extraction

RACINE = Path(__file__).resolve().parent.parent


def ecrire_zip(chemin, membres):
    with zipfile.ZipFile(chemin, "w") as z:
        for nom, contenu in membres.items():
            z.writestr(nom, contenu)
    return chemin


def objet(num, corps, flux=None, compresser=False):
    if flux is None:
        return "{} 0 obj\n{}\nendobj\n".format(num, corps).encode("latin-1")
    donnees = zlib.compress(flux) if compresser else flux
    entete = "{} 0 obj\n<< {} /Length {} >>\nstream\n".format(num, corps + (" /Filter /FlateDecode" if compresser else ""), len(donnees))
    return entete.encode("latin-1") + donnees + b"\nendstream\nendobj\n"


def pdf_simple(compresser=False):
    contenu = b"BT /F1 12 Tf 72 700 Td (Bonjour le monde, cr\\351ation d'un d\\351ploiement) Tj 0 -20 Td (Deuxi\\350me ligne : proc\\351dure) Tj ET"
    morceaux = [b"%PDF-1.4\n", objet(1, "<< /Type /Catalog /Pages 2 0 R >>"), objet(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
                objet(3, "<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"),
                objet(4, "", contenu, compresser), objet(5, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"), b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"]
    return b"".join(morceaux)


def pdf_avec_police_unicode_et_flux_d_objets():
    """Deux pages ; police à codes sur 2 octets avec table ToUnicode ; pages et catalogue rangés dans un flux d'objets compressé."""
    cmap = b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap 1 begincodespacerange <0000> <FFFF> endcodespacerange 3 beginbfchar <0001> <0048> <0002> <00E9> <0003> <0020> endbfchar 1 beginbfrange <0010> <0012> <0061> endbfrange endcmap end end"
    page1 = b"BT /F1 12 Tf 72 700 Td <0001000200030010001100120003> Tj ET"
    page2 = b"BT /F1 12 Tf 72 700 Td [<0001> -300 <0002>] TJ ET"
    dicts = ["<< /Type /Catalog /Pages 11 0 R >>", "<< /Type /Pages /Kids [12 0 R 13 0 R] /Count 2 >>",
             "<< /Type /Page /Parent 11 0 R /Resources << /Font << /F1 20 0 R >> >> /Contents 14 0 R >>", "<< /Type /Page /Parent 11 0 R /Resources << /Font << /F1 20 0 R >> >> /Contents 15 0 R >>"]
    numeros = [10, 11, 12, 13]
    corps, entete, position = "", "", 0
    for n, d in zip(numeros, dicts):
        entete += "{} {} ".format(n, position)
        corps += d + "\n"
        position += len(d) + 1
    flux_objets = (entete + "\n" + corps).encode("latin-1")
    morceaux = [b"%PDF-1.5\n", objet(9, "/Type /ObjStm /N 4 /First {}".format(len(entete) + 1), flux_objets, True), objet(14, "", page1, True), objet(15, "", page2, True),
                objet(20, "<< /Type /Font /Subtype /Type0 /BaseFont /Truc /ToUnicode 21 0 R >>"), objet(21, "", cmap, True), b"%%EOF\n"]
    return b"".join(morceaux)


class FormatsZip(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.d = Path(self.t.name)

    def tearDown(self):
        self.t.cleanup()

    def test_docx(self):
        xml = ('<w:document><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Procédure de déploiement</w:t></w:r></w:p>'
               '<w:p><w:r><w:t xml:space="preserve">Étape 1 : </w:t></w:r><w:r><w:tab/><w:t>sauvegarder &amp; vérifier</w:t></w:r></w:p><w:p></w:p></w:body></w:document>')
        p = ecrire_zip(self.d / "a.docx", {"word/document.xml": xml})
        self.assertEqual(extraction.parties(p), [("", "# Procédure de déploiement\n\nÉtape 1 : sauvegarder & vérifier")])

    def test_odt(self):
        xml = '<office:text><text:h text:outline-level="1">Titre du guide</text:h><text:p>Un <text:span>paragraphe</text:span> utile.<text:tab/>Fin</text:p></office:text>'
        p = ecrire_zip(self.d / "a.odt", {"content.xml": xml})
        self.assertEqual(extraction.parties(p), [("", "# Titre du guide\n\nUn paragraphe utile. Fin")])

    def test_pptx_une_partie_par_diapositive_dans_l_ordre(self):
        def diapo(texte):
            return '<p:sld><a:p><a:r><a:t>{}</a:t></a:r></a:p></p:sld>'.format(texte)
        p = ecrire_zip(self.d / "a.pptx", {"ppt/slides/slide10.xml": diapo("Dix"), "ppt/slides/slide2.xml": diapo("Deux"), "ppt/slides/slide1.xml": diapo("Un")})
        self.assertEqual([t for _, t in extraction.parties(p)], ["Un", "Deux", "Dix"])
        self.assertEqual(extraction.parties(p)[0][0], "Diapositive 1")

    def test_xlsx(self):
        partages = "<sst><si><t>Serveur</t></si><si><t>Rôle</t></si><si><t>nas-01</t></si></sst>"
        feuille = '<worksheet><sheetData><row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row><row><c t="s"><v>2</v></c><c><v>42</v></c></row></sheetData></worksheet>'
        p = ecrire_zip(self.d / "a.xlsx", {"xl/sharedStrings.xml": partages, "xl/worksheets/sheet1.xml": feuille, "xl/workbook.xml": '<workbook><sheets><sheet name="Inventaire" sheetId="1"/></sheets></workbook>'})
        self.assertEqual(extraction.parties(p), [("Inventaire", "Serveur | Rôle\nnas-01 | 42")])

    def test_html(self):
        p = self.d / "a.html"
        p.write_text("<html><head><style>x{}</style><script>alert(1)</script></head><body><h1>Guide</h1><p>Le <b>texte</b> &eacute;l&eacute;gant.</p></body></html>", encoding="utf-8")
        texte = extraction.parties(p)[0][1]
        self.assertIn("# Guide", texte)
        self.assertIn("Le texte élégant.", texte)
        self.assertNotIn("alert", texte)

    def test_refus(self):
        faux = self.d / "faux.docx"
        faux.write_bytes(b"pas un zip")
        with self.assertRaisesRegex(extraction.ErreurExtraction, "illisible"):
            extraction.parties(faux)
        vide = ecrire_zip(self.d / "vide.docx", {"autre.txt": "x"})
        with self.assertRaisesRegex(extraction.ErreurExtraction, "Word"):
            extraction.parties(vide)
        with self.assertRaisesRegex(extraction.ErreurExtraction, "Format non géré"):
            extraction.parties(self.d / "a.exe")
        with mock.patch.object(extraction, "DECOMPRESSE_MAX", 100):
            bombe = ecrire_zip(self.d / "bombe.docx", {"word/document.xml": "<w:p><w:t>" + "a" * 5000 + "</w:t></w:p>"})
            with self.assertRaisesRegex(extraction.ErreurExtraction, "suspect"):
                extraction.parties(bombe)
        with mock.patch.object(extraction, "TAILLE_MAX", 10):
            with self.assertRaisesRegex(extraction.ErreurExtraction, "trop gros"):
                extraction.parties(self.d / "bombe.docx")


class Pdf(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.d = Path(self.t.name)

    def tearDown(self):
        self.t.cleanup()

    def test_pdf_simple_avec_accents(self):
        for compresser in (False, True):
            p = self.d / "a.pdf"
            p.write_bytes(pdf_simple(compresser))
            self.assertEqual(extraction.parties(p), [("Page 1", "Bonjour le monde, création d'un déploiement\nDeuxième ligne : procédure")], compresser)

    def test_pdf_police_unicode_flux_d_objets_et_pages_dans_l_ordre(self):
        p = self.d / "b.pdf"
        p.write_bytes(pdf_avec_police_unicode_et_flux_d_objets())
        self.assertEqual(extraction.parties(p), [("Page 1", "Hé abc"), ("Page 2", "H é")])

    def test_pdf_chiffre_ou_abime(self):
        p = self.d / "c.pdf"
        p.write_bytes(pdf_simple().replace(b"trailer\n<< /Root 1 0 R >>", b"trailer\n<< /Root 1 0 R /Encrypt 9 0 R >>"))
        with self.assertRaisesRegex(extraction.ErreurExtraction, "chiffré"):
            extraction.parties(p)
        p.write_bytes(b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n2 0 obj <<")
        self.assertEqual(extraction.parties(p), [])
        p.write_bytes(b"MZ pas un pdf")
        with self.assertRaisesRegex(extraction.ErreurExtraction, "PDF"):
            extraction.parties(p)

    def test_un_vrai_pdf_fabrique_par_un_navigateur(self):
        sys.path.insert(0, str(RACINE / "tools"))
        import captures
        try:
            chrome = captures.navigateur()
        except SystemExit:
            self.skipTest("aucun navigateur")
        page = self.d / "page.html"
        page.write_text("<html><meta charset='utf-8'><body><h1>Guide de sauvegarde</h1><p>Première étape : vérifier l'espace disque du serveur.</p>"
                        "<p style='page-break-before:always'>Deuxième page : procédure de restauration, même après une panne.</p></body></html>", encoding="utf-8")
        sortie = self.d / "guide.pdf"
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--user-data-dir=" + str(self.d / "profil"), "--no-pdf-header-footer", "--print-to-pdf=" + str(sortie), page.as_uri()],
                       capture_output=True, timeout=120)
        self.assertTrue(sortie.is_file())
        pages = extraction.parties(sortie)
        ensemble = " ".join(t for _, t in pages).replace("\n", " ")
        self.assertGreaterEqual(len(pages), 2, pages)
        for attendu in ("Guide de sauvegarde", "Première étape", "espace disque", "procédure de restauration", "même après une panne"):
            self.assertIn(attendu, ensemble)
        self.assertIn("Deuxième page", pages[1][1])


if __name__ == "__main__":
    unittest.main()
