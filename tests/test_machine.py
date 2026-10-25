import unittest

import context  # noqa: F401
from lutin import machine
from lutin.machine import Disque, Gpu, Profil

NVIDIA_4090 = "NVIDIA GeForce RTX 4090, 24564, 23012\n"
NVIDIA_DEUX = "NVIDIA GeForce RTX 3060, 12288, 11000\nNVIDIA GeForce GTX 1050 Ti, 4096, 3900\n"
# Portable hybride : l'écran est sur la puce Intel, le calcul sur la NVIDIA ; AdapterRAM plafonné à 4 Go (4293918720 = 4 Go - 1 Mo) côté WMI
WIN_AMD_16GO = ('{"registre":[{"nom":"AMD Radeon RX 7800 XT","octets":[0,0,0,0,4,0,0,0]}],'
                '"wmi":[{"nom":"AMD Radeon RX 7800 XT","adapter":4293918720},{"nom":"Microsoft Basic Render Driver","adapter":0}]}')
WIN_SANS_REGISTRE = '{"registre":null,"wmi":{"nom":"Intel(R) UHD Graphics 770","adapter":1073741824}}'
MEMINFO = "MemTotal:       32768000 kB\nMemFree:         1000000 kB\nMemAvailable:   20000000 kB\n"


class Detection(unittest.TestCase):
    def test_nvidia_smi_une_carte(self):
        g = machine.analyser_nvidia_smi(NVIDIA_4090)
        self.assertEqual(len(g), 1)
        self.assertEqual((g[0].nom, g[0].fabricant, g[0].vram_go, g[0].libre_go), ("NVIDIA GeForce RTX 4090", "nvidia", 24.0, 22.5))

    def test_nvidia_smi_deux_cartes_et_nom_avec_virgule(self):
        self.assertEqual([g.vram_go for g in machine.analyser_nvidia_smi(NVIDIA_DEUX)], [12.0, 4.0])
        g = machine.analyser_nvidia_smi("NVIDIA RTX A6000, Edition, 49140, 48000")
        self.assertEqual(g[0].nom, "NVIDIA RTX A6000, Edition")

    def test_nvidia_smi_sortie_vide_ou_cassee(self):
        for texte in ("", None, "No devices were found", "a,b,c"):
            self.assertEqual(machine.analyser_nvidia_smi(texte), [])

    def test_windows_prefere_le_registre_au_champ_wmi_plafonne(self):
        g = machine.analyser_gpus_windows(WIN_AMD_16GO)
        self.assertEqual(len(g), 1, "le pilote d'affichage de base est ignoré")
        self.assertEqual((g[0].fabricant, g[0].vram_go, g[0].source), ("amd", 16.0, "registre"))

    def test_windows_sans_registre_signale_le_plafond(self):
        g = machine.analyser_gpus_windows(WIN_SANS_REGISTRE)
        self.assertEqual((g[0].fabricant, g[0].vram_go), ("intel", 1.0))
        self.assertIn("plafonné", g[0].source)

    def test_windows_sortie_illisible(self):
        for texte in ("", "pas du json", "[]", None):
            self.assertEqual(machine.analyser_gpus_windows(texte), [])

    def test_meminfo(self):
        total, dispo = machine.analyser_meminfo(MEMINFO)
        self.assertAlmostEqual(total, 31.25, places=1)
        self.assertAlmostEqual(dispo, 19.07, places=1)
        self.assertEqual(machine.analyser_meminfo(""), (0.0, 0.0))

    def test_sysfs_amd(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as t:
            carte = Path(t) / "card0" / "device"
            carte.mkdir(parents=True)
            (carte / "vendor").write_text("0x1002\n")
            (carte / "mem_info_vram_total").write_text(str(16 * 1024 ** 3))
            (Path(t) / "card0-HDMI-A-1").mkdir()          # connecteur : ignoré
            g = machine.lire_gpus_linux(t)
            self.assertEqual([(x.fabricant, x.vram_go) for x in g], [("amd", 16.0)])
            self.assertEqual(machine.lire_gpus_linux(str(Path(t) / "absent")), [])

    def test_detecter_ne_plante_jamais_meme_sans_aucune_commande(self):
        p = machine.detecter(lanceur=lambda *a, **k: "")
        self.assertIn(p.systeme, ("windows", "linux", "macos"))
        self.assertGreater(p.coeurs, 0)
        self.assertGreaterEqual(len(p.disques), 1)


def profil(vram=None, ram=32.0, fabricant="nvidia", ram_libre=20.0):
    return Profil(systeme="windows", ram_go=ram, ram_libre_go=ram_libre, gpus=[Gpu("Carte", fabricant, vram)] if vram is not None else [],
                  disques=[Disque("C:\\", 100, 500)])


class CarteDeclaree(unittest.TestCase):
    def test_formats(self):
        a = machine.analyser_gpu_declare
        self.assertEqual([(g.nom, g.fabricant, g.vram_go) for g in a("24")], [("Carte déclarée", "nvidia", 24.0)])
        self.assertEqual([(g.nom, g.fabricant, g.vram_go) for g in a("NVIDIA RTX 4090=24")], [("NVIDIA RTX 4090", "nvidia", 24.0)])
        self.assertEqual([(g.fabricant, g.vram_go) for g in a("Radeon RX 7900 XTX=20")], [("amd", 20.0)])
        self.assertEqual([(g.fabricant, g.vram_go) for g in a("Ma carte=12:intel")], [("intel", 12.0)])
        self.assertEqual([g.vram_go for g in a("Ma carte=11,5")], [11.5])

    def test_valeurs_absurdes_ignorees(self):
        for texte in ("", None, "beaucoup", "=", "0", "-4", "99999", "x=y"):
            self.assertEqual(machine.analyser_gpu_declare(texte), [], texte)

    def test_la_declaration_remplace_la_detection(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"LUTIN_GPU": "NVIDIA RTX 3060=12"}):
            p = machine.detecter(lanceur=lambda *a, **k: NVIDIA_4090 if "nvidia-smi" in str(a) else "")
        self.assertEqual([(g.nom, g.vram_go) for g in p.gpus], [("NVIDIA RTX 3060", 12.0)])
        self.assertEqual(p.classe(), "moyenne")


class Budget(unittest.TestCase):
    def test_classes(self):
        attendu = {None: "sans_gpu", 2: "sans_gpu", 6: "petite", 8: "petite", 12: "moyenne", 16: "moyenne", 24: "grande", 32: "grande", 48: "tres_grande"}
        for vram, classe in attendu.items():
            self.assertEqual(profil(vram).classe(), classe, "VRAM " + str(vram))

    def test_budget_nvidia_est_85_pour_cent(self):
        self.assertEqual(profil(24).budget_go(), 20.4)

    def test_sans_gpu_utilise_la_ram(self):
        self.assertEqual(profil(None, ram=16).budget_go(), 9.6)
        self.assertTrue(profil(None).sans_gpu())

    def test_intel_integre_n_est_pas_un_gpu_de_calcul(self):
        self.assertTrue(profil(1, fabricant="intel").sans_gpu())

    def test_apple_memoire_partagee(self):
        self.assertEqual(profil(32, ram=32, fabricant="apple").budget_go(), 24.0)

    def test_gpu_principal_prend_la_plus_grosse_memoire(self):
        p = profil(12)
        p.gpus.append(Gpu("Petite", "nvidia", 4))
        self.assertEqual(p.gpu_principal().vram_go, 12)

    def test_aller_retour_dict(self):
        p = profil(24)
        self.assertEqual(Profil.depuis_dict(p.en_dict()).gpu_principal().vram_go, 24)


if __name__ == "__main__":
    unittest.main()
