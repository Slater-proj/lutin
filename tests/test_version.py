"""La version affichée est celle du code installé, même quand une mise à jour a laissé les métadonnées d'une ancienne version à côté des nouvelles."""
import sys
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401
import lutin


def faux_dossier_de_paquets(versions):
    tmp = tempfile.mkdtemp(prefix="lutin-version-")
    for v in versions:
        d = Path(tmp) / "lutin-{}.dist-info".format(v)
        d.mkdir()
        (d / "METADATA").write_text("Metadata-Version: 2.1\nName: lutin\nVersion: {}\n".format(v), encoding="utf-8")
    return tmp


class VersionInstallee(unittest.TestCase):
    def avec(self, versions):
        tmp = faux_dossier_de_paquets(versions)
        sys.path.insert(0, tmp)
        self.addCleanup(sys.path.remove, tmp)

    def test_la_plus_haute_gagne_quelle_que_soit_l_ordre_des_dossiers(self):
        self.avec(["98.4.1", "98.5.1", "98.5.0"])
        self.assertEqual(lutin.version_installee(), "98.5.1", "l'ancienne 98.4.1 vient en premier dans l'ordre alphabétique : ce n'est pas elle qu'on affiche")

    def test_les_nombres_sont_compares_comme_des_nombres(self):
        self.avec(["98.9.0", "98.10.0"])
        self.assertEqual(lutin.version_installee(), "98.10.0", "10 est plus grand que 9")

    def test_numeros(self):
        self.assertEqual(lutin._numeros("0.5.2"), (0, 5, 2))
        self.assertEqual(lutin._numeros("0.5.2rc3+ma.branche"), (0, 5, 2))
        self.assertEqual(lutin._numeros("illisible"), (0, 0, 0))

    def test_la_version_du_paquet_est_celle_des_sources_ou_installee(self):
        self.assertTrue(lutin.__version__)


if __name__ == "__main__":
    unittest.main()
