"""Le logo de Lutin est partout, au bon format et à la bonne taille : sans fond là où un fond ferait tache, avec les tailles que Windows demande, identique dans les deux copies."""
import re
import struct
import unittest
from pathlib import Path

import context  # noqa: F401

RACINE = Path(__file__).resolve().parent.parent
WEB = RACINE / "src" / "lutin" / "web"
WINDOWS = RACINE / "installateur" / "windows"
PAGE = (WEB / "index.html").read_text(encoding="utf-8")


def entrees_ico(chemin):
    """[(largeur, hauteur, données)] d'un fichier .ico (0 = 256)."""
    brut = chemin.read_bytes()
    reserve, genre, nombre = struct.unpack("<HHH", brut[:6])
    assert (reserve, genre) == (0, 1), "ce n'est pas un .ico"
    sortie = []
    for i in range(nombre):
        largeur, hauteur, _, _, _, _, taille, decalage = struct.unpack("<BBBBHHII", brut[6 + 16 * i:22 + 16 * i])
        sortie.append((largeur or 256, hauteur or 256, brut[decalage:decalage + taille]))
    return sortie


def entete_png(donnees):
    """(largeur, hauteur, type de couleur) d'un PNG ; 6 = avec transparence."""
    assert donnees[:8] == b"\x89PNG\r\n\x1a\n", "pas un PNG"
    largeur, hauteur, _, type_couleur = struct.unpack(">IIBB", donnees[16:26])
    return largeur, hauteur, type_couleur


def taille_bmp(chemin):
    brut = chemin.read_bytes()
    assert brut[:2] == b"BM", "pas un BMP"
    largeur, hauteur = struct.unpack("<ii", brut[18:26])
    return largeur, abs(hauteur)


class LogoVectoriel(unittest.TestCase):
    def test_sans_fond_ni_halo(self):
        svg = (WEB / "logo.svg").read_text(encoding="utf-8")
        self.assertNotIn("<rect", svg, "un fond (carré) dans l'onglet du navigateur fait tache : seulement le personnage")
        self.assertNotIn("lueur", svg, "pas de halo derrière l'étincelle")

    def test_cadre_serre_autour_du_personnage(self):
        svg = (WEB / "logo.svg").read_text(encoding="utf-8")
        x, y, largeur, hauteur = (float(n) for n in re.search(r'viewBox="([^"]+)"', svg).group(1).split())
        self.assertLessEqual(largeur, 105, "le cadre est serré : le logo occupe toute la place de l'onglet")
        self.assertLessEqual(abs(largeur - hauteur), 5, "à peu près carré")
        self.assertGreater(x, 10)

    def test_les_deux_copies_sont_identiques(self):
        self.assertEqual((WEB / "logo.svg").read_text(encoding="utf-8"), (RACINE / "assets" / "logo.svg").read_text(encoding="utf-8"))

    def test_la_page_l_utilise_dans_l_onglet_et_l_en_tete(self):
        self.assertIn('rel="icon" type="image/svg+xml" href="/icone.svg"', PAGE)
        self.assertIn('<img src="/logo.svg"', PAGE)


class IconesWindows(unittest.TestCase):
    def test_les_deux_ico_ont_les_quatre_tailles_avec_transparence(self):
        for chemin in (WEB / "lutin.ico", WINDOWS / "lutin.ico"):
            entrees = entrees_ico(chemin)
            self.assertEqual(sorted((l, h) for l, h, _ in entrees), [(16, 16), (32, 32), (48, 48), (256, 256)], chemin.name)
            for largeur, hauteur, donnees in entrees:
                self.assertEqual(entete_png(donnees), (largeur, hauteur, 6), "PNG avec canal alpha : le personnage seul, sans carré")

    def test_les_deux_ico_sont_les_memes(self):
        self.assertEqual((WEB / "lutin.ico").read_bytes(), (WINDOWS / "lutin.ico").read_bytes())

    def test_images_de_l_assistant_d_installation(self):
        self.assertEqual(taille_bmp(WINDOWS / "assistant-grand.bmp"), (164, 314))
        self.assertEqual(taille_bmp(WINDOWS / "assistant-petit.bmp"), (55, 58))


class IconesDApplication(unittest.TestCase):
    def test_tailles(self):
        for n in (180, 192, 512):
            donnees = (WEB / "icones" / "icone-{}.png".format(n)).read_bytes()
            self.assertEqual(entete_png(donnees)[:2], (n, n))

    def test_le_manifeste_ne_demande_pas_de_recadrage(self):
        serveur = (RACINE / "src" / "lutin" / "serveur.py").read_text(encoding="utf-8")
        self.assertNotIn("maskable", serveur, "une icône « maskable » serait rognée : le personnage remplit déjà le carré")


class Trombone(unittest.TestCase):
    def test_le_trombone_est_un_dessin_qui_remplit_son_bouton(self):
        bouton = re.search(r'<button id="bJoindre"[^>]*>(.*?)</button>', PAGE, re.S).group(1)
        self.assertIn("<svg", bouton, "un dessin, pas le petit emoji")
        self.assertNotIn("📎", bouton)
        self.assertRegex(PAGE, r"\.saisie-ligne #bJoindre svg \{ width:2[4-9]px")


if __name__ == "__main__":
    unittest.main()
