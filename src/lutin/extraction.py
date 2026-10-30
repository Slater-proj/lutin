"""Le texte des documents (PDF, Word, LibreOffice, PowerPoint, Excel, HTML), sans dépendance et sans rien exécuter : de quoi les chercher et les lire hors ligne.

Chaque fonction renvoie une liste de « parties » (page, diapositive, feuille) : [(titre, texte)]. Les formats « à zip » (docx, odt, pptx, xlsx) sont lus par expressions régulières sur le XML (aucun analyseur XML,
donc pas de bombe d'entités). Le PDF est lu au mieux : texte des pages (flux compressés, flux d'objets, table ToUnicode des polices) ; pas de scans (images), pas de PDF chiffré.
`parties(chemin)` choisit selon l'extension et lève ErreurExtraction si le fichier est illisible ou trop gros.
"""
import base64
import html
import re
import zipfile
import zlib
from pathlib import Path

from .i18n import t as _t

FORMATS = (".pdf", ".docx", ".odt", ".ods", ".odp", ".pptx", ".xlsx", ".html", ".htm")
TAILLE_MAX = 30 * 1024 * 1024
DECOMPRESSE_MAX = 80 * 1024 * 1024


class ErreurExtraction(ValueError):
    pass


class Suspect(ErreurExtraction):
    """Un document qui se décompresse en trop de données : on arrête tout (les autres erreurs d'objet, elles, sont sautées)."""


def nettoyer(texte):
    texte = html.unescape(texte)
    texte = re.sub(r"[ \t ]+", " ", texte)
    texte = re.sub(r" ?\n ?", "\n", texte)
    return re.sub(r"\n{3,}", "\n\n", texte).strip()


# ----------------------------------------------------------------- formats zip
def _zip(chemin):
    if Path(chemin).stat().st_size > TAILLE_MAX:
        raise ErreurExtraction(_t("Document trop gros ({} Mo au plus).").format(TAILLE_MAX // 1024 ** 2))
    try:
        z = zipfile.ZipFile(chemin)
    except (zipfile.BadZipFile, OSError) as e:
        raise ErreurExtraction(_t("Document illisible : {}").format(e)) from e
    if sum(i.file_size for i in z.infolist()) > DECOMPRESSE_MAX:
        raise ErreurExtraction(_t("Document suspect : trop volumineux une fois décompressé."))
    return z


def _lire(z, nom):
    try:
        return z.read(nom).decode("utf-8", "replace")
    except KeyError:
        return ""


def _concat(xml, balise):
    sortie = []
    for m in re.finditer(r"<{0}(?:\s[^>]*)?>(.*?)</{0}>|(\t|\n)".format(re.escape(balise)), xml, re.S):
        sortie.append(m.group(1) if m.group(1) is not None else m.group(2))
    return "".join(sortie)


def docx(chemin):
    z = _zip(chemin)
    xml = _lire(z, "word/document.xml")
    if not xml:
        raise ErreurExtraction(_t("Ce n'est pas un document Word (.docx) lisible."))
    paragraphes = []
    for m in re.finditer(r"<w:p(?:\s[^>]*)?>(.*?)</w:p>", xml, re.S):
        texte = _concat(m.group(1), "w:t").strip()
        titre = re.search(r'<w:pStyle w:val="(?:Heading|Titre)(\d)"', m.group(1))
        if texte:
            paragraphes.append(("#" * int(titre.group(1)) + " " + texte) if titre else texte)
    return [("", nettoyer("\n\n".join(paragraphes)))]


def odt(chemin):
    z = _zip(chemin)
    xml = _lire(z, "content.xml")
    if not xml:
        raise ErreurExtraction(_t("Ce n'est pas un document LibreOffice (.odt) lisible."))
    xml = re.sub(r"<text:s\s*/>", " ", xml)
    blocs = []
    for m in re.finditer(r"<text:(h|p)(?:\s[^>]*)?>(.*?)</text:\1>", xml, re.S):
        texte = re.sub(r"<[^>]+>", "", re.sub(r"<text:(?:tab|line-break)\s*/>", " ", m.group(2))).strip()
        if texte:
            blocs.append(("# " + texte) if m.group(1) == "h" else texte)
    return [("", nettoyer("\n\n".join(blocs)))]


def pptx(chemin):
    z = _zip(chemin)
    noms = sorted((n for n in z.namelist() if re.match(r"^ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    sortie = []
    for i, n in enumerate(noms, 1):
        xml = _lire(z, n)
        paragraphes = [_concat(m.group(1), "a:t").strip() for m in re.finditer(r"<a:p(?:\s[^>]*)?>(.*?)</a:p>", xml, re.S)]
        texte = nettoyer("\n".join(p for p in paragraphes if p))
        if texte:
            sortie.append((_t("Diapositive {}").format(i), texte))
    return sortie


def xlsx(chemin):
    z = _zip(chemin)
    partages = [_concat(m.group(1), "t") for m in re.finditer(r"<si(?:\s[^>]*)?>(.*?)</si>", _lire(z, "xl/sharedStrings.xml"), re.S)]
    noms_feuilles = re.findall(r'<sheet [^>]*name="([^"]*)"', _lire(z, "xl/workbook.xml"))
    feuilles = sorted((n for n in z.namelist() if re.match(r"^xl/worksheets/sheet\d+\.xml$", n)), key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    sortie = []
    for i, n in enumerate(feuilles):
        lignes = []
        for rang in re.finditer(r"<row(?:\s[^>]*)?>(.*?)</row>", _lire(z, n), re.S):
            cases = []
            for c in re.finditer(r"<c(\s[^>]*)?>(.*?)</c>", rang.group(1), re.S):
                attrs, corps = c.group(1) or "", c.group(2)
                v = re.search(r"<v>(.*?)</v>", corps, re.S)
                if 't="s"' in attrs and v and v.group(1).strip().isdigit() and int(v.group(1)) < len(partages):
                    cases.append(partages[int(v.group(1))])
                elif 't="inlineStr"' in attrs:
                    cases.append(_concat(corps, "t"))
                elif v:
                    cases.append(v.group(1))
            if any(cases):
                lignes.append(" | ".join(cases))
        texte = nettoyer("\n".join(lignes))
        if texte:
            sortie.append((html.unescape(noms_feuilles[i]) if i < len(noms_feuilles) else _t("Feuille {}").format(i + 1), texte))
    return sortie


def page_html(chemin):
    if Path(chemin).stat().st_size > TAILLE_MAX:
        raise ErreurExtraction(_t("Document trop gros ({} Mo au plus).").format(TAILLE_MAX // 1024 ** 2))
    brut = Path(chemin).read_bytes().decode("utf-8", "replace")
    brut = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", brut, flags=re.S | re.I)
    brut = re.sub(r"<(h[1-6])\b[^>]*>(.*?)</\1>", lambda m: "\n\n# " + re.sub(r"<[^>]+>", "", m.group(2)) + "\n\n", brut, flags=re.S | re.I)
    brut = re.sub(r"</(p|div|li|tr|br|h\d)>|<br\s*/?>", "\n", brut, flags=re.I)
    return [("", nettoyer(re.sub(r"<[^>]+>", " ", brut)))]


# ----------------------------------------------------------------- PDF
RE_OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")


def _filtres(dico):
    f = dico.get("/Filter")
    if f is None:
        return []
    return [x for x in (f if isinstance(f, list) else [f])]


def _decoder_flux(dico, brut):
    """Les octets d'un flux après ses filtres ; None si un filtre n'est pas géré (images, LZW…)."""
    donnees = brut
    for f in _filtres(dico):
        try:
            if f in ("/FlateDecode", "/Fl"):
                d = zlib.decompressobj()
                donnees = d.decompress(donnees, DECOMPRESSE_MAX)
            elif f in ("/ASCII85Decode", "/A85"):
                donnees = base64.a85decode(donnees.strip(), adobe=donnees.strip().startswith(b"<~"))
            elif f in ("/ASCIIHexDecode", "/AHx"):
                donnees = bytes.fromhex(re.sub(rb"[^0-9A-Fa-f]", b"", donnees.split(b">")[0]).decode("ascii"))
            else:
                return None
        except (zlib.error, ValueError):
            return None
    return donnees


class Analyse:
    """Un petit lecteur d'objets PDF : nombres, noms, chaînes, tableaux, dictionnaires, références."""

    def __init__(self, octets):
        self.o, self.i = octets, 0

    ESPACES = b" \t\r\n\x0c\x00"
    DELIMITEURS = b"()<>[]{}/%"

    def sauter(self):
        while self.i < len(self.o):
            c = self.o[self.i:self.i + 1]
            if c in self.ESPACES:
                self.i += 1
            elif c == b"%":
                while self.i < len(self.o) and self.o[self.i:self.i + 1] not in b"\r\n":
                    self.i += 1
            else:
                break

    def valeur(self, profondeur=0):
        if profondeur > 40:
            raise ErreurExtraction("PDF trop imbriqué")
        self.sauter()
        if self.i >= len(self.o):
            raise ErreurExtraction("fin inattendue")
        c = self.o[self.i:self.i + 1]
        if c == b"/":
            return self.nom()
        if self.o.startswith(b"<<", self.i):
            self.i += 2
            d = {}
            while True:
                self.sauter()
                if self.o.startswith(b">>", self.i):
                    self.i += 2
                    return d
                cle = self.valeur(profondeur + 1)
                d[cle] = self.valeur(profondeur + 1)
        if c == b"[":
            self.i += 1
            liste = []
            while True:
                self.sauter()
                if self.o[self.i:self.i + 1] == b"]":
                    self.i += 1
                    return liste
                liste.append(self.valeur(profondeur + 1))
        if c == b"(":
            return self.chaine()
        if c == b"<":
            return self.hexa()
        m = re.compile(rb"(\d+)\s+(\d+)\s+R\b").match(self.o, self.i)
        if m:
            self.i = m.end()
            return ("ref", int(m.group(1)))
        m = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)").match(self.o, self.i)
        if m:
            self.i = m.end()
            t = m.group(0)
            return float(t) if b"." in t else int(t)
        m = re.compile(rb"[^\s()<>\[\]{}/%]+").match(self.o, self.i)
        if not m:
            raise ErreurExtraction("jeton inconnu")
        self.i = m.end()
        mot = m.group(0)
        return {b"true": True, b"false": False, b"null": None}.get(mot, mot.decode("latin-1"))

    def nom(self):
        m = re.compile(rb"/[^\s()<>\[\]{}/%]*").match(self.o, self.i)
        self.i = m.end()
        return re.sub(rb"#([0-9A-Fa-f]{2})", lambda x: bytes([int(x.group(1), 16)]), m.group(0)).decode("latin-1")

    def chaine(self):
        self.i += 1
        niveau, sortie = 1, bytearray()
        while self.i < len(self.o):
            c = self.o[self.i]
            self.i += 1
            if c == 0x5C:                                              # barre oblique inverse
                s = self.o[self.i:self.i + 1]
                self.i += 1
                if s in b"nrtbf":
                    sortie.append({b"n": 10, b"r": 13, b"t": 9, b"b": 8, b"f": 12}[s])
                elif s in b"01234567":
                    k = s
                    while len(k) < 3 and self.o[self.i:self.i + 1] in (b"0", b"1", b"2", b"3", b"4", b"5", b"6", b"7"):
                        k += self.o[self.i:self.i + 1]
                        self.i += 1
                    sortie.append(int(k, 8) & 255)
                elif s in (b"\r", b"\n"):
                    if s == b"\r" and self.o[self.i:self.i + 1] == b"\n":
                        self.i += 1
                else:
                    sortie += s
            elif c == 0x28:
                niveau += 1
                sortie.append(c)
            elif c == 0x29:
                niveau -= 1
                if niveau == 0:
                    return bytes(sortie)
                sortie.append(c)
            else:
                sortie.append(c)
        return bytes(sortie)

    def hexa(self):
        fin = self.o.index(b">", self.i)
        h = re.sub(rb"[^0-9A-Fa-f]", b"", self.o[self.i + 1:fin])
        self.i = fin + 1
        if len(h) % 2:
            h += b"0"
        return bytes.fromhex(h.decode("ascii"))


def _objets_pdf(donnees):
    """{numéro: (dictionnaire ou valeur, octets du flux décodé ou None)} pour tous les objets, y compris ceux rangés dans des flux d'objets."""
    objets = {}
    positions = [(int(m.group(1)), m.end()) for m in RE_OBJ.finditer(donnees)]
    total = 0
    for k, (num, debut) in enumerate(positions):
        fin = positions[k + 1][1] if k + 1 < len(positions) else len(donnees)
        morceau = donnees[debut:fin]
        try:
            a = Analyse(morceau)
            valeur = a.valeur()
            flux = None
            apres = morceau.find(b"stream", a.i)
            if isinstance(valeur, dict) and apres >= 0 and apres - a.i < 20:
                debut_flux = apres + 6
                if morceau[debut_flux:debut_flux + 2] == b"\r\n":
                    debut_flux += 2
                elif morceau[debut_flux:debut_flux + 1] in (b"\n", b"\r"):
                    debut_flux += 1
                fin_flux = morceau.rfind(b"endstream")
                brut = morceau[debut_flux:fin_flux if fin_flux >= debut_flux else len(morceau)]
                flux = _decoder_flux(valeur, brut.rstrip(b"\r\n") if "/FlateDecode" not in _filtres(valeur) else brut)
                if flux is not None:
                    total += len(flux)
                    if total > DECOMPRESSE_MAX:
                        raise Suspect(_t("Document suspect : trop volumineux une fois décompressé."))
            objets[num] = (valeur, flux)
        except Suspect:
            raise
        except (ValueError, IndexError):          # ErreurExtraction est une ValueError : un objet illisible est sauté, pas le document
            continue
    for num, (valeur, flux) in list(objets.items()):                      # flux d'objets : on y range d'autres objets
        if isinstance(valeur, dict) and valeur.get("/Type") == "/ObjStm" and flux:
            try:
                n, premier = int(valeur.get("/N", 0)), int(valeur.get("/First", 0))
                paires = [int(x) for x in re.findall(rb"\d+", flux[:premier])][:2 * n]
                for j in range(0, len(paires) - 1, 2):
                    debut = premier + paires[j + 1]
                    fin_o = premier + paires[j + 3] if j + 3 < len(paires) else len(flux)
                    objets.setdefault(paires[j], (Analyse(flux[debut:fin_o]).valeur(), None))
            except (ValueError, ErreurExtraction, IndexError):
                continue
    return objets


def _resoudre(objets, v):
    for _ in range(10):
        if isinstance(v, tuple) and v and v[0] == "ref":
            v = objets.get(v[1], (None, None))[0]
        else:
            break
    return v


def _cmap(flux):
    """Table code → texte d'une police (CMap ToUnicode) ; la longueur des codes (1 ou 2 octets) est déduite."""
    texte = flux.decode("latin-1")
    table, longueur = {}, 1

    def u(h):
        h = re.sub(r"\s", "", h)
        try:
            return bytes.fromhex(h if len(h) % 2 == 0 else "0" + h).decode("utf-16-be", "replace")
        except ValueError:
            return ""
    for bloc in re.findall(r"beginbfchar(.*?)endbfchar", texte, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", bloc):
            table[int(src, 16)] = u(dst)
            longueur = max(longueur, (len(src) + 1) // 2)
    for bloc in re.findall(r"beginbfrange(.*?)endbfrange", texte, re.S):
        for lo, hi, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])", bloc):
            a, b = int(lo, 16), int(hi, 16)
            longueur = max(longueur, (len(lo) + 1) // 2)
            if b - a > 70000:
                continue
            if dst.startswith("<"):
                base = u(dst[1:-1])
                for k in range(a, b + 1):
                    table[k] = (base[:-1] + chr(ord(base[-1]) + (k - a))) if base else ""
            else:
                for k, h in zip(range(a, b + 1), re.findall(r"<([0-9A-Fa-f]+)>", dst)):
                    table[k] = u(h)
    return table, longueur


class Police:
    def __init__(self, objets, ref):
        self.table, self.longueur, self.connue = {}, 1, False
        d = _resoudre(objets, ref)
        if not isinstance(d, dict):
            return
        tu = d.get("/ToUnicode")
        if isinstance(tu, tuple) and tu[1] in objets and objets[tu[1]][1]:
            self.table, self.longueur = _cmap(objets[tu[1]][1])
            self.connue = True
        elif d.get("/Subtype") == "/Type0":
            self.longueur = 2

    def decoder(self, octets):
        if self.connue:
            n = self.longueur
            return "".join(self.table.get(int.from_bytes(octets[i:i + n], "big"), "") for i in range(0, len(octets) - n + 1, n))
        if self.longueur == 2:
            return ""                                             # police à codes sur 2 octets sans table : illisible, on ne produit pas de bruit
        return octets.decode("cp1252", "replace")


def _texte_contenu(flux, polices):
    """Le texte d'un flux de contenu de page : opérateurs Tf, Tj, TJ, ', \", Td, TD, Tm, T*, ET."""
    a = Analyse(flux)
    pile, sortie, police, y_precedent = [], [], Police({}, None), None

    def montrer(v):
        if isinstance(v, bytes):
            sortie.append(police.decoder(v))

    def ligne():
        if sortie and not sortie[-1].endswith("\n"):
            sortie.append("\n")
    n = len(flux)
    while a.i < n:
        a.sauter()
        if a.i >= n:
            break
        c = flux[a.i:a.i + 1]
        try:
            if c in (b"/", b"(", b"[", b"<"):
                pile.append(a.valeur())
                continue
            m = re.compile(rb"[^\s()<>\[\]{}/%]+").match(flux, a.i)
            if not m:
                a.i += 1
                continue
            a.i = m.end()
            mot = m.group(0)
            try:
                pile.append(float(mot) if b"." in mot else int(mot))
                continue
            except ValueError:
                pass
            op = mot.decode("latin-1")
            if op == "BI":                                         # image en ligne : on saute jusqu'à EI
                fin = re.compile(rb"\sEI(?=\s|$)").search(flux, a.i)
                a.i = fin.end() if fin else n
            elif op == "Tf" and len(pile) >= 2:
                police = polices.get(pile[-2], Police({}, None))
            elif op == "Tj" and pile:
                montrer(pile[-1])
            elif op == "TJ" and pile and isinstance(pile[-1], list):
                for x in pile[-1]:
                    if isinstance(x, bytes):
                        montrer(x)
                    elif isinstance(x, (int, float)) and x < -250:
                        sortie.append(" ")
            elif op in ("'", '"') and pile:
                ligne()
                montrer(pile[-1])
            elif op in ("Td", "TD") and len(pile) >= 2:
                if abs(pile[-1]) > 0.5:
                    ligne()
            elif op == "Tm" and len(pile) >= 6:
                y = pile[-1]
                if y_precedent is not None and abs(y - y_precedent) > 1:
                    ligne()
                y_precedent = y
            elif op in ("T*", "ET"):
                ligne()
            pile.clear()
        except (ErreurExtraction, ValueError, IndexError):
            a.i += 1
    return "".join(sortie)


def pdf(chemin):
    if Path(chemin).stat().st_size > TAILLE_MAX:
        raise ErreurExtraction(_t("Document trop gros ({} Mo au plus).").format(TAILLE_MAX // 1024 ** 2))
    donnees = Path(chemin).read_bytes()
    if not donnees.startswith(b"%PDF") and b"%PDF" not in donnees[:1024]:
        raise ErreurExtraction(_t("Ce n'est pas un PDF lisible."))
    if re.search(rb"/Encrypt\s", donnees[-4096:]) or re.search(rb"/Encrypt\s*\d", donnees[-4096:]):
        raise ErreurExtraction(_t("PDF chiffré : Lutin ne peut pas le lire."))
    objets = _objets_pdf(donnees)
    # pages dans l'ordre de l'arbre ; à défaut, dans l'ordre du fichier
    pages = []

    def descendre(noeud, ressources, profondeur=0):
        d = _resoudre(objets, noeud)
        if not isinstance(d, dict) or profondeur > 30:
            return
        res = d.get("/Resources", ressources)
        if d.get("/Type") == "/Pages" or "/Kids" in d:
            for k in _resoudre(objets, d.get("/Kids")) or []:
                descendre(k, res, profondeur + 1)
        else:
            pages.append((d, res))
    racine = next((v for v, _ in objets.values() if isinstance(v, dict) and v.get("/Type") == "/Catalog"), None)
    if racine:
        descendre(racine.get("/Pages"), None)
    if not pages:
        pages = [(v, v.get("/Resources")) for num, (v, _) in sorted(objets.items()) if isinstance(v, dict) and v.get("/Type") == "/Page"]
    sortie = []
    for numero, (page, ressources) in enumerate(pages, 1):
        res = _resoudre(objets, ressources) or {}
        familles = _resoudre(objets, res.get("/Font")) or {} if isinstance(res, dict) else {}
        polices = {nom: Police(objets, ref) for nom, ref in familles.items()} if isinstance(familles, dict) else {}
        contenu = _resoudre(objets, page.get("/Contents"))
        refs = contenu if isinstance(contenu, list) else [page.get("/Contents")]
        flux = b"\n".join(objets[r[1]][1] for r in refs if isinstance(r, tuple) and r[1] in objets and objets[r[1]][1])
        texte = nettoyer(_texte_contenu(flux, polices)) if flux else ""
        if texte:
            sortie.append((_t("Page {}").format(numero), texte))
    return sortie


def parties(chemin):
    """[(titre de la partie, texte)] d'un document ; ErreurExtraction s'il est illisible."""
    ext = Path(chemin).suffix.lower()
    fonctions = {".pdf": pdf, ".docx": docx, ".odt": odt, ".ods": odt, ".odp": odt, ".pptx": pptx, ".xlsx": xlsx, ".html": page_html, ".htm": page_html}
    if ext not in fonctions:
        raise ErreurExtraction(_t("Format non géré : {}").format(ext))
    try:
        return fonctions[ext](chemin)
    except ErreurExtraction:
        raise
    except (OSError, ValueError, KeyError, zlib.error, RecursionError) as e:
        raise ErreurExtraction(_t("Document illisible : {}").format(e)) from e


def texte(chemin):
    """Tout le texte d'un document, parties séparées par leur titre en Markdown."""
    return "\n\n".join(("## {}\n\n".format(titre) if titre else "") + corps for titre, corps in parties(chemin))
