"""Un chemin cité dans une réponse devient un lien qui ouvre le fichier DU DOSSIER DE TRAVAIL (jamais ailleurs, jamais lancé), et les avis qui revenaient à chaque réponse ne reviennent plus."""
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-ouv-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402
from lutin import ouverture as O  # noqa: E402
from lutin import dialogue  # noqa: E402


class Chemins(unittest.TestCase):
    def setUp(self):
        self.racine = Path(tempfile.mkdtemp(prefix="lutin-ouv-r-")).resolve()
        (self.racine / "tests-naomi" / "results").mkdir(parents=True)
        (self.racine / "tests-naomi" / "galerie-v11b.html").write_text("<html><img src='results/a.png'></html>", encoding="utf-8")
        (self.racine / "tests-naomi" / "results" / "a.png").write_bytes(b"\x89PNG")
        (self.racine / "README.md").write_text("# lisez-moi", encoding="utf-8")
        (self.racine / ".git").mkdir()
        (self.racine / ".git" / "config").write_text("secret", encoding="utf-8")
        (self.racine / "outil.exe").write_bytes(b"MZ")
        self.avant = _m.RACINE
        _m.RACINE = self.racine
        self.addCleanup(lambda: setattr(_m, "RACINE", self.avant))

    def test_le_meme_fichier_se_retrouve_sous_toutes_ses_ecritures(self):
        attendu = (self.racine / "tests-naomi" / "galerie-v11b.html").resolve()
        for ecrit in ("tests-naomi/galerie-v11b.html", "tests-naomi\\galerie-v11b.html", "file:///tests-naomi/galerie-v11b.html", "C:\\Users\\moi\\projet\\tests-naomi\\galerie-v11b.html",
                      "\\\\NAS\\Software\\Perso\\depot_git\\game\\assistant\\illustrateur\\tests-naomi\\galerie-v11b.html", "file:///\\NAS\\Software\\tests-naomi\\galerie-v11b.html",
                      "/home/moi/projet/tests-naomi/galerie-v11b.html", "`tests-naomi/galerie-v11b.html`", str(attendu)):
            self.assertEqual(O.resoudre(ecrit, self.racine), attendu, ecrit)
        self.assertEqual(O.resoudre("README.md", self.racine), (self.racine / "README.md").resolve())

    def test_un_nom_trop_vague_ou_inconnu_ne_devine_rien(self):
        (self.racine / "a").mkdir()
        (self.racine / "a" / "index.html").write_text("x", encoding="utf-8")
        for ecrit in ("galerie-v11b.html", "D:\\ailleurs\\index.html", "inconnu.html", "", "tests-naomi", "../x.html", "tests-naomi/../../etc/passwd"):
            self.assertIsNone(O.resoudre(ecrit, self.racine), ecrit)

    def test_rien_hors_du_dossier_ni_les_dossiers_proteges(self):
        for ecrit in ("C:\\Windows\\System32\\drivers\\etc\\hosts", "/etc/passwd", ".git/config", "projet/.git/config"):
            self.assertIsNone(O.resoudre(ecrit, self.racine), ecrit)
        with self.assertRaises(ValueError):
            O.lire(".git/config", self.racine)
        with self.assertRaises(ValueError):
            O.lire("../secret.txt", self.racine)

    def test_l_adresse_garde_les_chemins_relatifs_de_la_page_valables(self):
        p = O.resoudre("tests-naomi/galerie-v11b.html", self.racine)
        self.assertEqual(O.adresse(p, self.racine), "/ouvrir/tests-naomi/galerie-v11b.html")
        octets, mime, entetes = O.lire("tests-naomi/results/a.png", self.racine)          # l'image voisine, demandée par la page à /ouvrir/tests-naomi/results/a.png
        self.assertEqual((octets, mime), (b"\x89PNG", "image/png"))

    def test_une_page_html_s_ouvre_en_bac_a_sable_et_un_programme_se_telecharge_sans_se_lancer(self):
        octets, mime, entetes = O.lire("tests-naomi/galerie-v11b.html", self.racine)
        self.assertTrue(mime.startswith("text/html"))
        self.assertIn("sandbox", entetes["Content-Security-Policy"])
        self.assertNotIn("allow-same-origin", entetes["Content-Security-Policy"], "la page n'a aucun accès à Lutin (cookies, interface)")
        self.assertEqual(entetes["X-Content-Type-Options"], "nosniff")
        octets, mime, entetes = O.lire("outil.exe", self.racine)
        self.assertIn("attachment", entetes["Content-Disposition"])
        octets, mime, entetes = O.lire("README.md", self.racine)
        self.assertTrue(mime.startswith("text/"))


class AvisUneSeuleFois(unittest.TestCase):
    def test_la_reduction_du_contexte_n_est_pas_redite_a_chaque_reponse(self):
        dialogue.DITS["reduction"].clear()
        dits = []
        emit = dits.append
        rapport = {"raccourcis": 5, "tronques": 0, "retires": 0, "tours": 0}
        conv = {"id": "aaaa1111"}
        dialogue.annoncer_reduction(rapport, emit, {"conv": conv}, 36864)
        self.assertEqual(len(dits), 1)
        dialogue.annoncer_reduction(rapport, emit, {"conv": conv}, 36864)          # une autre réponse (nouveau contexte de tour) : la même situation
        dialogue.annoncer_reduction(dict(rapport, raccourcis=7), emit, {"conv": conv}, 36864)
        self.assertEqual(len(dits), 1, "à peine plus : pas un nouvel avis")
        dialogue.annoncer_reduction(dict(rapport, raccourcis=9, tours=5), emit, {"conv": conv}, 36864)
        self.assertEqual(len(dits), 2, "la réduction a nettement grossi : on le redit")
        dialogue.annoncer_reduction(rapport, emit, {"conv": {"id": "bbbb2222"}}, 36864)
        self.assertEqual(len(dits), 3, "une autre conversation a son propre avis")

    def test_le_nom_du_moteur_et_les_erreurs_de_memoire_video(self):
        for texte in ('{"detail":"Model X failed to load: Insufficient VRAM in split for model and cache"}', "CUDA out of memory", "not enough GPU memory", "Failed to load model"):
            self.assertTrue(dialogue.RE_MEMOIRE_VIDEO.search(texte), texte)
        self.assertFalse(dialogue.RE_MEMOIRE_VIDEO.search("Connection refused"))


if __name__ == "__main__":
    unittest.main()
