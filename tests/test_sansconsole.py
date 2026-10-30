"""Lutin sans console (icône de la zone de notification) : aucun programme lancé n'ouvre de fenêtre noire qui clignote."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401
from lutin import sansconsole

SRC = Path(__file__).resolve().parent.parent / "src"

# Un programme lancé par pythonw (donc sans console) : il lance `ping` et note les fenêtres visibles qui apparaissent pendant ce temps.
SONDE = r'''
import ctypes, json, subprocess, sys, threading, time
from ctypes import wintypes
mode, sortie = sys.argv[1], sys.argv[2]
if mode == "avec":
    sys.path.insert(0, %r)
    from lutin import sansconsole
    sansconsole.activer()
user32 = ctypes.windll.user32
Proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

def fenetres():
    classes = []
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            t = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, t, 256)
            classes.append(t.value)
        return True
    user32.EnumWindows(Proc(cb), 0)
    return classes

avant = fenetres()
fil = threading.Thread(target=lambda: subprocess.run(["ping", "-n", "4", "127.0.0.1"], capture_output=True))
fil.start()
vues = set()
debut = time.time()
while time.time() - debut < 3:
    courant = fenetres()
    vues.update(c for c in set(courant) if courant.count(c) > avant.count(c))
    time.sleep(0.05)
fil.join()
json.dump({"nouvelles": sorted(vues)}, open(sortie, "w"))
''' % str(SRC)


class Regle(unittest.TestCase):
    def test_un_programme_lance_sans_console_n_ouvre_pas_de_fenetre(self):
        self.assertEqual(sansconsole.drapeaux(0), sansconsole.CREATE_NO_WINDOW)
        self.assertEqual(sansconsole.drapeaux(0x200), 0x200 | sansconsole.CREATE_NO_WINDOW, "les autres drapeaux de l'appelant sont gardés")

    def test_un_processus_detache_ou_une_console_voulue_ne_sont_pas_touches(self):
        for voulu in (sansconsole.DETACHED_PROCESS, sansconsole.CREATE_NEW_CONSOLE, sansconsole.CREATE_NO_WINDOW):
            self.assertEqual(sansconsole.drapeaux(voulu), voulu)

    def test_popen_recoit_les_drapeaux(self):
        appels = []
        enveloppe = sansconsole.envelopper(lambda self, *a, **kw: appels.append(kw))
        enveloppe(object(), ["x"])
        enveloppe(object(), ["x"], creationflags=sansconsole.CREATE_NEW_CONSOLE)
        self.assertEqual([c["creationflags"] for c in appels], [sansconsole.CREATE_NO_WINDOW, sansconsole.CREATE_NEW_CONSOLE])

    def test_dans_un_vrai_terminal_rien_n_est_change(self):
        with mock.patch.object(sansconsole, "console_visible", return_value=True), mock.patch.object(sansconsole, "_actif", False), mock.patch.object(sansconsole.os, "name", "nt"):
            avant = subprocess.Popen.__init__
            self.assertFalse(sansconsole.activer())
            self.assertIs(subprocess.Popen.__init__, avant)

    def test_hors_windows_rien_n_est_fait(self):
        with mock.patch.object(sansconsole.os, "name", "posix"):
            self.assertFalse(sansconsole.activer(force=True))

    def test_le_paquet_l_active_au_chargement(self):
        source = (SRC / "lutin" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("sansconsole.activer()", source)


@unittest.skipUnless(sys.platform == "win32", "fenêtres Windows")
class EnVrai(unittest.TestCase):
    """Un vrai processus pythonw : sans la règle, la console d'un programme lancé s'affiche (le clignotement) ; avec la règle, aucune fenêtre."""

    def mesurer(self, mode):
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.is_file():
            self.skipTest("pas de pythonw.exe")
        tmp = Path(tempfile.mkdtemp(prefix="sansconsole-"))
        script, sortie = tmp / "sonde.py", tmp / "sortie.json"
        script.write_text(SONDE, encoding="utf-8")
        subprocess.run([str(pythonw), str(script), mode, str(sortie)], timeout=60)
        return json.loads(sortie.read_text())["nouvelles"]

    def test_avec_la_regle_aucune_fenetre_n_apparait(self):
        temoin = self.mesurer("sans")
        if not temoin:
            self.skipTest("cette session n'affiche pas de fenêtre de console (le témoin ne voit rien) : mesure impossible ici")
        self.assertEqual(self.mesurer("avec"), [], "le témoin voit {} : la règle doit les supprimer".format(temoin))


if __name__ == "__main__":
    unittest.main()
