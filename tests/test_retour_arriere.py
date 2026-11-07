"""Mise à jour sûre et retour arrière : sauvegarde avant de changer de version, jamais bloquante ; réinstallation d'une version publiée, avec un numéro strictement contrôlé."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

from lutin import cli, miseajour  # noqa: E402


class Faux:
    """Un `subprocess.run` qui note les commandes et répond ce qu'on veut."""

    def __init__(self, pip=0, version_apres="0.21.0"):
        self.commandes = []
        self.pip = pip
        self.version_apres = version_apres

    def __call__(self, commande, **kw):
        self.commandes.append(list(commande))
        if "pip" in commande:
            return mock.Mock(returncode=self.pip, stdout="")
        return mock.Mock(returncode=0, stdout="Lutin " + self.version_apres + "\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-retour-"))
        for d in ("config", "donnees", "memoire", "cache"):
            (self.tmp / d).mkdir()
        (self.tmp / "config" / "config.json").write_text("{}", encoding="utf-8")
        (self.tmp / "donnees" / "reglages.json").write_text('{"moteur": "ollama"}', encoding="utf-8")
        self.dossiers = {d: self.tmp / d for d in ("config", "donnees", "memoire", "cache")}
        self.sorties, self.erreurs = [], []
        patchs = [mock.patch.object(cli.config, "dossiers", lambda *a, **k: self.dossiers),
                  mock.patch.object(cli, "__version__", "0.22.0")]
        for p in patchs:
            p.start()
            self.addCleanup(p.stop)

    def lancer(self, source="github:Slater-proj/lutin", faux=None, **kw):
        faux = faux or Faux()
        with mock.patch.object(cli.config, "lire_source", lambda: source), mock.patch.object(cli.subprocess, "run", faux):
            res = cli.mise_a_jour_detaillee(dire=self.sorties.append, erreur=self.erreurs.append, **kw)
        return res, faux


class SauvegardeAvant(Base):
    def test_une_sauvegarde_est_faite_avant_pip(self):
        with mock.patch.object(cli.miseajour, "derniere_release", lambda depot: ("0.23.0", "https://exemple/lutin.whl")):
            (code, avant, apres), faux = self.lancer(faux=Faux(version_apres="0.23.0"))
        self.assertEqual((code, apres), (0, "0.23.0"))
        zips = list((self.dossiers["cache"] / "avant-mise-a-jour").glob("lutin-*.zip"))
        self.assertEqual(len(zips), 1)
        self.assertTrue(zips[0].name.startswith("lutin-0.22.0-"), "le nom dit de quelle version on part")

    def test_seules_les_trois_dernieres_sont_gardees(self):
        d = self.dossiers["cache"] / "avant-mise-a-jour"
        d.mkdir()
        for i in range(5):
            f = d / "lutin-0.1.{}-20200101-00000{}.zip".format(i, i)
            f.write_bytes(b"x")
            os.utime(f, (1000 + i, 1000 + i))
        cli.sauvegarde_avant_mise_a_jour(self.sorties.append)
        restes = sorted(p.name for p in d.glob("lutin-*.zip"))
        self.assertEqual(len(restes), 3)
        self.assertNotIn("lutin-0.1.0-20200101-000000.zip", restes, "les plus anciennes partent")

    def test_une_sauvegarde_impossible_ne_bloque_pas_la_mise_a_jour(self):
        with mock.patch.object(cli.sauvegarde, "exporter", side_effect=OSError("disque plein")), \
                mock.patch.object(cli.miseajour, "derniere_release", lambda depot: ("0.23.0", "https://exemple/lutin.whl")):
            (code, avant, apres), faux = self.lancer(faux=Faux(version_apres="0.23.0"))
        self.assertEqual(code, 0)
        self.assertTrue(any("disque plein" in s for s in self.sorties), "l'utilisateur est prévenu")
        self.assertTrue(any("pip" in c for c in faux.commandes[0]))

    def test_rien_n_est_sauvegarde_quand_deja_a_jour(self):
        with mock.patch.object(cli.miseajour, "derniere_release", lambda depot: ("0.22.0", "https://exemple/lutin.whl")):
            (code, avant, apres), faux = self.lancer()
        self.assertEqual((code, apres, faux.commandes), (0, None, []))
        self.assertFalse((self.dossiers["cache"] / "avant-mise-a-jour").exists())

    def test_echec_de_pip_garde_la_version_actuelle(self):
        with mock.patch.object(cli.miseajour, "derniere_release", lambda depot: ("0.23.0", "https://exemple/lutin.whl")):
            (code, avant, apres), faux = self.lancer(faux=Faux(pip=1))
        self.assertEqual((code, apres), (1, None))
        self.assertTrue(any("reste en place" in e for e in self.erreurs))


class RetourArriere(Base):
    def test_reinstalle_la_version_demandee_depuis_la_roue_publiee(self):
        (code, avant, apres), faux = self.lancer(revenir_a="0.21.0", faux=Faux(version_apres="0.21.0"))
        self.assertEqual((code, avant, apres), (0, "0.22.0", "0.21.0"))
        pip = faux.commandes[0]
        self.assertIn("https://github.com/Slater-proj/lutin/releases/download/v0.21.0/lutin-0.21.0-py3-none-any.whl", pip)
        self.assertTrue(list((self.dossiers["cache"] / "avant-mise-a-jour").glob("*.zip")), "les données sont sauvegardées avant le retour arrière")

    def test_numero_invalide_refuse_sans_toucher_a_rien(self):
        for mauvais in ("0.21", "abc", "0.21.0; rm -rf /", "../../0.1.0", "0.21.0 --index-url http://x", ""):
            if not mauvais:
                continue
            with self.subTest(mauvais=mauvais):
                (code, _, apres), faux = self.lancer(revenir_a=mauvais)
                self.assertEqual((code, apres, faux.commandes), (1, None, []))

    def test_deja_dans_cette_version(self):
        (code, _, apres), faux = self.lancer(revenir_a="0.22.0")
        self.assertEqual((code, apres, faux.commandes), (0, None, []))

    def test_source_hors_github_refusee(self):
        (code, _, apres), faux = self.lancer(source="/chemin/vers/lutin.whl", revenir_a="0.21.0")
        self.assertEqual((code, apres, faux.commandes), (1, None, []))
        self.assertTrue(self.erreurs)

    def test_la_mise_a_jour_normale_ne_revient_jamais_en_arriere(self):
        self.assertFalse(miseajour.plus_recente("0.21.0", "0.22.0"))


if __name__ == "__main__":
    unittest.main()
