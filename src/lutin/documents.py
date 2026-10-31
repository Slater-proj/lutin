"""Écrire des documents (PDF, Word) à partir d'un texte en Markdown simple, sans aucune dépendance.

Ce que le Markdown peut contenir : titres (#, ##, ###), paragraphes, listes à puces (- ou *) et numérotées (1.), blocs de code (```), séparateurs (---), tableaux (écrits tels quels, en police fixe)
et, dans Word, le gras (**x**), l'italique (*x*) et le code (`x`). Le PDF utilise les polices standard (Helvetica, Courier) : les lettres accentuées et la ponctuation courante passent ; un caractère
hors de l'alphabet latin (emoji, idéogramme) est remplacé par « ? » plutôt que de casser le fichier.

Les fichiers produits sont relus par `extraction` après l'écriture (outils.outil_document) : ce que Lutin annonce comme écrit est un document qu'il sait rouvrir."""
import re
import time
import zipfile
import zlib
from io import BytesIO
from xml.sax.saxutils import escape

PAGE = (595, 842)                # A4, en points
MARGE = 56
RE_TITRE = re.compile(r"^(#{1,3})\s+(.*)$")
RE_PUCE = re.compile(r"^(\s*)[-*•]\s+(.*)$")
RE_NUM = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
RE_SEP = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
RE_INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)")
TAILLE_MAX = 400_000

# Largeurs de la police Helvetica (millièmes d'em), caractères 32 à 126 ; les lettres accentuées ont la largeur de leur lettre de base.
_H = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015,
      667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333,
      556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
LARGEUR = {chr(32 + i): w for i, w in enumerate(_H)}
BASE = {"àáâãä": "a", "ç": "c", "èéêë": "e", "ìíîï": "i", "ñ": "n", "òóôõö": "o", "ùúûü": "u", "ýÿ": "y", "ÀÁÂÃÄ": "A", "Ç": "C", "ÈÉÊË": "E", "ÌÍÎÏ": "I", "Ñ": "N", "ÒÓÔÕÖ": "O", "ÙÚÛÜ": "U", "Ý": "Y"}
for lettres, base in BASE.items():
    for c in lettres:
        LARGEUR[c] = LARGEUR[base]
LARGEUR.update({"œ": 944, "Œ": 1000, "æ": 889, "Æ": 1000, "€": 556, "’": 222, "‘": 222, "“": 333, "”": 333, "«": 556, "»": 556, "—": 1000, "–": 556, "…": 1000, "•": 350, "°": 400, "©": 737})
SUBSTITUTIONS = str.maketrans({" ": " ", " ": " ", "→": "->", "←": "<-", "✓": "v", "✔": "v", "✗": "x", "•": "•", "−": "-", "\t": "    "})


def _largeur(texte, police, taille):
    if police == "F3":
        return len(texte) * 0.6 * taille
    total = sum(LARGEUR.get(c, 556) for c in texte) * taille / 1000
    return total * (1.07 if police == "F2" else 1.0)


# --------------------------------------------------------------------------- lecture du Markdown
def blocs(markdown):
    """Liste de blocs : ("titre", niveau, texte), ("para", texte), ("puce", niveau, texte), ("num", niveau, "n. texte"), ("code", [lignes]), ("sep",), ("vide",)."""
    sortie, code, para = [], None, []

    def clore():
        if para:
            sortie.append(("para", " ".join(para)))
            para.clear()
    for ligne in str(markdown).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if ligne.strip().startswith("```"):
            clore()
            if code is None:
                code = []
            else:
                sortie.append(("code", code))
                code = None
            continue
        if code is not None:
            code.append(ligne)
            continue
        m = RE_TITRE.match(ligne.strip())
        if m:
            clore()
            sortie.append(("titre", len(m.group(1)), m.group(2).strip()))
        elif RE_SEP.match(ligne):
            clore()
            sortie.append(("sep",))
        elif RE_PUCE.match(ligne):
            clore()
            m = RE_PUCE.match(ligne)
            sortie.append(("puce", min(3, len(m.group(1).replace("\t", "  ")) // 2), m.group(2).strip()))
        elif RE_NUM.match(ligne):
            clore()
            m = RE_NUM.match(ligne)
            sortie.append(("num", min(3, len(m.group(1).replace("\t", "  ")) // 2), "{}. {}".format(m.group(2), m.group(3).strip())))
        elif ligne.lstrip().startswith("|"):
            clore()
            sortie.append(("code", [ligne.rstrip()]))                   # tableau : gardé tel quel, en police fixe
        elif not ligne.strip():
            clore()
            sortie.append(("vide",))
        else:
            para.append(ligne.strip())
    clore()
    if code is not None:
        sortie.append(("code", code))
    fusion = []
    for b in sortie:                                                   # les lignes de tableau se suivent dans un même bloc de code
        if b[0] == "code" and fusion and fusion[-1][0] == "code" and len(b[1]) == 1 and b[1][0].lstrip().startswith("|") and fusion[-1][1][-1].lstrip().startswith("|"):
            fusion[-1][1].append(b[1][0])
        else:
            fusion.append(b)
    return fusion


def sans_balises(texte):
    return re.sub(r"`([^`]+)`", r"\1", re.sub(r"\*([^*\s][^*]*)\*", r"\1", re.sub(r"\*\*([^*]+)\*\*", r"\1", texte)))


# --------------------------------------------------------------------------- PDF
def _pdf_chaine(texte):
    octets = texte.translate(SUBSTITUTIONS).encode("cp1252", "replace")
    return b"(" + octets.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def _couper(texte, police, taille, largeur):
    """Coupe un texte en lignes qui tiennent dans `largeur` (aux espaces ; un mot trop long est coupé)."""
    lignes, courante = [], ""
    for mot in texte.split(" "):
        essai = (courante + " " + mot) if courante else mot
        if _largeur(essai, police, taille) <= largeur:
            courante = essai
            continue
        if courante:
            lignes.append(courante)
        while _largeur(mot, police, taille) > largeur and len(mot) > 1:
            n = len(mot)
            while n > 1 and _largeur(mot[:n], police, taille) > largeur:
                n -= 1
            lignes.append(mot[:n])
            mot = mot[n:]
        courante = mot
    lignes.append(courante)
    return lignes


def pdf(markdown, titre=""):
    """Octets d'un PDF (A4, pages numérotées) à partir du Markdown."""
    texte_max = PAGE[0] - 2 * MARGE
    pages, courante, y = [], [], PAGE[1] - MARGE

    def saut():
        nonlocal courante, y
        pages.append(courante)
        courante, y = [], PAGE[1] - MARGE

    def ligne(police, taille, x, texte, avant=0, interligne=1.3):
        nonlocal y
        hauteur = taille * interligne
        if y - avant - hauteur < MARGE + 14:
            saut()
            avant = 0
        y -= avant + hauteur
        courante.append((police, taille, x, y + taille * 0.28, texte))

    corps = ([("titre", 0, titre)] if titre else []) + blocs(markdown)
    for b in corps:
        if b[0] == "titre":
            taille = {0: 22, 1: 18, 2: 14, 3: 12}[b[1]]
            for k, t in enumerate(_couper(sans_balises(b[2]), "F2", taille, texte_max)):
                ligne("F2", taille, MARGE, t, avant=(taille * 0.9 if k == 0 else 0), interligne=1.25)
            y -= 3
        elif b[0] == "para":
            for k, t in enumerate(_couper(sans_balises(b[1]), "F1", 11, texte_max)):
                ligne("F1", 11, MARGE, t, avant=(4 if k == 0 else 0))
        elif b[0] in ("puce", "num"):
            retrait = MARGE + 14 * b[1]
            marque = "•" if b[0] == "puce" else b[2].split(" ", 1)[0]
            reste = b[2] if b[0] == "puce" else b[2].split(" ", 1)[1] if " " in b[2] else ""
            x_texte = retrait + (14 if b[0] == "puce" else 22)
            for k, t in enumerate(_couper(sans_balises(reste), "F1", 11, texte_max - (x_texte - MARGE))):
                if k == 0:
                    ligne("F1", 11, x_texte, t, avant=2)
                    courante.insert(len(courante) - 1, ("F1", 11, retrait, y + 11 * 0.28, marque))          # la puce avant son texte (ordre de lecture)
                else:
                    ligne("F1", 11, x_texte, t)
        elif b[0] == "code":
            for k, t in enumerate(b[1] or [""]):
                for j, morceau in enumerate(_couper(t.expandtabs(4), "F3", 9, texte_max) if t.strip() else [""]):
                    ligne("F3", 9, MARGE + 6, morceau, avant=(4 if k == 0 and j == 0 else 0), interligne=1.25)
        elif b[0] == "sep":
            ligne("F1", 6, MARGE, "", avant=4)
            courante.append(("TRAIT", 0, MARGE, y + 3, ""))
        elif b[0] == "vide":
            y -= 3
    pages.append(courante)

    objets = []                                    # contenu des objets 1..n (sans « n 0 obj »)
    objets.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    nb_pages = len(pages)
    objets.append(("<< /Type /Pages /Kids [" + " ".join("%d 0 R" % (8 + 2 * i) for i in range(nb_pages)) + "] /Count %d >>" % nb_pages).encode("ascii"))
    for nom in ("Helvetica", "Helvetica-Bold", "Courier"):
        objets.append(("<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>" % nom).encode("ascii"))
    info = b"<< /Producer (Lutin) /CreationDate (D:" + time.strftime("%Y%m%d%H%M%S").encode("ascii") + b") " + (b"/Title " + _pdf_chaine(titre) + b" " if titre else b"") + b">>"
    objets.append(info)                            # objet 6
    for i, page in enumerate(pages):
        flux = [b"BT"]
        traits = []
        for police, taille, x, py, texte in page:
            if police == "TRAIT":
                traits.append(py)
                continue
            if texte:
                flux.append(b"/%s %s Tf 1 0 0 1 %.1f %.1f Tm " % (police.encode(), (b"%g" % taille), x, py) + _pdf_chaine(texte) + b" Tj")
        flux.append(b"ET")
        for py in traits:
            flux.append(b"0.6 G %d %.1f m %d %.1f l S" % (MARGE, py, PAGE[0] - MARGE, py))
        flux.append(b"BT /F1 9 Tf 1 0 0 1 %.1f 28 Tm " % (PAGE[0] / 2 - 10) + _pdf_chaine("%d / %d" % (i + 1, nb_pages)) + b" Tj ET")
        brut = zlib.compress(b"\n".join(flux))
        objets.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(brut) + brut + b"\nendstream")                                    # objet 7 + 2i
        objets.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> >>"
                       % (PAGE[0], PAGE[1], 6 + 2 * i + 1)).encode("ascii"))                                                                       # objet 8 + 2i
    sortie = BytesIO()
    sortie.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    positions = []
    for n, contenu in enumerate(objets, 1):
        positions.append(sortie.tell())
        sortie.write(b"%d 0 obj\n" % n + contenu + b"\nendobj\n")
    xref = sortie.tell()
    sortie.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objets) + 1))
    for p in positions:
        sortie.write(b"%010d 00000 n \n" % p)
    sortie.write(b"trailer\n<< /Size %d /Root 1 0 R /Info 6 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objets) + 1, xref))
    return sortie.getvalue()


# --------------------------------------------------------------------------- Word
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="%s">'
          '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="22"/><w:lang w:val="fr-FR"/></w:rPr></w:rPrDefault>'
          '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
          '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
          '<w:style w:type="paragraph" w:styleId="Titre"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="48"/></w:rPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="Titre1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="Titre2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="280" w:after="100"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="Titre3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:left="284"/></w:pPr>'
          '<w:rPr><w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:cs="Courier New"/><w:sz w:val="18"/></w:rPr></w:style></w:styles>') % W


def _runs(texte):
    """Les morceaux d'un paragraphe : texte simple, **gras**, *italique*, `code`."""
    xml = []
    for morceau in RE_INLINE.split(texte):
        if not morceau:
            continue
        props = ""
        if morceau.startswith("**") and morceau.endswith("**") and len(morceau) > 4:
            morceau, props = morceau[2:-2], "<w:b/>"
        elif morceau.startswith("`") and morceau.endswith("`") and len(morceau) > 2:
            morceau, props = morceau[1:-1], '<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New"/><w:sz w:val="20"/>'
        elif morceau.startswith("*") and morceau.endswith("*") and len(morceau) > 2:
            morceau, props = morceau[1:-1], "<w:i/>"
        xml.append('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % ("<w:rPr>%s</w:rPr>" % props if props else "", escape(_propre(morceau))))
    return "".join(xml) or "<w:r><w:t></w:t></w:r>"


def _propre(texte):
    """Retire les caractères interdits en XML."""
    return re.sub("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]", "", texte)


def _paragraphe(texte, style="", retrait=0, suspendu=0):
    ppr = ""
    if style:
        ppr += '<w:pStyle w:val="%s"/>' % style
    if retrait:
        ppr += '<w:ind w:left="%d" w:hanging="%d"/>' % (retrait, suspendu)
    return "<w:p>%s%s</w:p>" % ("<w:pPr>%s</w:pPr>" % ppr if ppr else "", _runs(texte))


def docx(markdown, titre=""):
    """Octets d'un document Word (.docx) à partir du Markdown."""
    corps = []
    if titre:
        corps.append(_paragraphe(titre, "Titre"))
    for b in blocs(markdown):
        if b[0] == "titre":
            corps.append(_paragraphe(b[2], "Titre%d" % b[1]))
        elif b[0] == "para":
            corps.append(_paragraphe(b[1]))
        elif b[0] == "puce":
            corps.append(_paragraphe("•  " + b[2], "", 360 + 360 * b[1], 360))
        elif b[0] == "num":
            corps.append(_paragraphe(b[2], "", 360 + 360 * b[1], 360))
        elif b[0] == "code":
            corps.extend('<w:p><w:pPr><w:pStyle w:val="Code"/></w:pPr><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % escape(_propre(t)) for t in (b[1] or [""]))
        elif b[0] == "sep":
            corps.append('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="999999"/></w:pBdr></w:pPr></w:p>')
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="%s"><w:body>%s<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>') % (W, "".join(corps))
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
             '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    maintenant = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>%s</dc:title><dc:creator>Lutin</dc:creator>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created></cp:coreProperties>') % (escape(titre), maintenant)
    sortie = BytesIO()
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("docProps/core.xml", core)
    return sortie.getvalue()


FORMATS = {".pdf": pdf, ".docx": docx}
