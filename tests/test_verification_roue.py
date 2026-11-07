"""La roue de mise à jour est vérifiée contre le SHA256SUMS.txt de la publication AVANT toute installation : somme fausse, fichier absent de la liste, roue énorme ou adresse inattendue = refus, sans réseau réel."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

from lutin import cli, miseajour as m  # noqa: E402

URL = "https://github.com/Slater-proj/lutin/releases/download/v1.2.3/lutin-1.2.3-py3-none-any.whl"
CONTENU = b"contenu de la roue" * 100
SOMME = hashlib.sha256(CONTENU).hexdigest()


class Flux:
    def __init__(self, donnees):
        self.donnees, self.pos = donnees, 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        bloc = self.donnees[self.pos:self.pos + n]
        self.pos += len(bloc)
        return bloc


def http(statut, texte=""):
    return lambda url, entetes=None, delai=10: (statut, {}, texte.encode("utf-8"))


class SommesAttendues(unittest.TestCase):
    def test_lecture_du_format_sha256sum(self):
        texte = "{}  lutin-1.2.3-py3-none-any.whl\n{} *lutin-1.2.3.tar.gz\nbidule\n".format(SOMME, "a" * 64)
        self.assertEqual(m.somme_attendue(texte, "lutin-1.2.3-py3-none-any.whl"), SOMME)
        self.assertEqual(m.somme_attendue(texte, "lutin-1.2.3.tar.gz"), "a" * 64, "le mode binaire « * » est accepté")
        self.assertIsNone(m.somme_attendue(texte, "autre.whl"))
        self.assertIsNone(m.somme_attendue(texte.upper().replace(SOMME.upper(), "ZZ"), "x"))


class Telechargement(unittest.TestCase):
    def appeler(self, statut, texte, donnees=CONTENU, url=URL):
        with tempfile.TemporaryDirectory() as d:
            res = m.telecharger_roue_verifiee(url, d, http=http(statut, texte), ouvrir=lambda req, timeout=0: Flux(donnees))
            return res[1], res[0].read_bytes() if res[0].exists() else None

    def test_somme_correcte(self):
        verifie, octets = self.appeler(200, "{}  lutin-1.2.3-py3-none-any.whl\n".format(SOMME))
        self.assertTrue(verifie)
        self.assertEqual(octets, CONTENU)

    def test_somme_fausse_refusee_et_fichier_supprime(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(m.ErreurVerification) as e:
                m.telecharger_roue_verifiee(URL, d, http=http(200, "{}  lutin-1.2.3-py3-none-any.whl".format("0" * 64)), ouvrir=lambda req, timeout=0: Flux(CONTENU))
            self.assertIn("SHA-256", str(e.exception))
            self.assertEqual(list(Path(d).iterdir()), [], "la roue douteuse ne reste pas sur le disque")

    def test_fichier_absent_de_la_liste_refuse(self):
        with self.assertRaises(m.ErreurVerification):
            self.appeler(200, "{}  autre-chose.whl\n".format(SOMME))

    def test_publication_sans_sommes_signalee_mais_acceptee(self):
        verifie, octets = self.appeler(404, "")
        self.assertFalse(verifie, "ancienne publication : on le dit, on n'invente pas de vérification")
        self.assertEqual(octets, CONTENU)

    def test_autre_erreur_http_refusee(self):
        with self.assertRaises(m.ErreurVerification):
            self.appeler(500, "")

    def test_adresses_et_noms_inattendus_refuses(self):
        for url in ("http://github.com/x/lutin-1.2.3-py3-none-any.whl", "https://github.com/x/pas-lutin.whl", "https://github.com/x/lutin-1.2.3-py3-none-any.whl;rm", "https://github.com/x/../lutin-1.0.0.tar.gz"):
            with self.subTest(url=url), self.assertRaises(m.ErreurVerification):
                self.appeler(200, "", url=url)

    def test_roue_anormalement_grosse_refusee(self):
        with mock.patch.object(m, "TAILLE_ROUE_MAX", 1000), self.assertRaises(m.ErreurVerification):
            self.appeler(200, "{}  lutin-1.2.3-py3-none-any.whl".format(SOMME))

    def test_reseau_absent_est_une_oserror(self):
        def coupe(*a, **k):
            raise OSError("pas de réseau")
        with tempfile.TemporaryDirectory() as d, self.assertRaises(OSError):
            m.telecharger_roue_verifiee(URL, d, http=coupe)


class DansLaMiseAJour(unittest.TestCase):
    def test_une_somme_fausse_n_installe_rien(self):
        appels = []
        sorties, erreurs = [], []
        with mock.patch.object(cli.config, "lire_source", lambda: "github:Slater-proj/lutin"), mock.patch.object(cli, "__version__", "1.0.0"), \
                mock.patch.object(cli.miseajour, "derniere_release", lambda depot: ("1.2.3", URL)), mock.patch.object(cli, "sauvegarde_avant_mise_a_jour", lambda dire=None: None), \
                mock.patch.object(cli.miseajour, "telecharger_roue_verifiee", side_effect=m.ErreurVerification("somme fausse")), \
                mock.patch.object(cli.subprocess, "run", lambda c, **k: appels.append(c)):
            code, avant, apres = cli.mise_a_jour_detaillee(dire=sorties.append, erreur=erreurs.append)
        self.assertEqual((code, apres, appels), (1, None, []), "pip n'est jamais lancé")
        self.assertTrue(any("somme fausse" in e for e in erreurs))


if __name__ == "__main__":
    unittest.main()
