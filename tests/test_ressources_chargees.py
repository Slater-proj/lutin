"""Ce qui est chargé en mémoire (page Santé) : modèles d'Ollama, serveur llama.cpp, ComfyUI, programmes gourmands ; décharger chaque chose sur clic, rien d'autre."""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-ressources-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import moteur_llamacpp as ml  # noqa: E402
from lutin import moteurs, ressources_chargees as rc  # noqa: E402

APPELS = []


class FauxOutils(BaseHTTPRequestHandler):
    """Fait à la fois Ollama (/api/ps, /api/generate) et ComfyUI (/system_stats, /queue, /free)."""
    en_cours = 0

    def log_message(self, *a):
        pass

    def _json(self, o):
        d = json.dumps(o).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def do_GET(self):
        if self.path == "/api/ps":
            return self._json({"models": [{"name": "qwen3:8b", "size": 6 * 1024 ** 3, "size_vram": 5 * 1024 ** 3, "expires_at": "2026-11-07T15:42:10+01:00"},
                                          {"name": "nomic-embed-text:latest", "size": 300 * 1024 ** 2, "size_vram": 0, "expires_at": "0001-01-01T00:00:00Z"}]})
        if self.path == "/system_stats":
            return self._json({"devices": [{"name": "cuda:0", "vram_total": 12 * 1024 ** 3, "vram_free": 4 * 1024 ** 3, "torch_vram_total": 7 * 1024 ** 3, "torch_vram_free": 1 * 1024 ** 3}]})
        if self.path == "/queue":
            return self._json({"queue_running": [1] * FauxOutils.en_cours, "queue_pending": []})
        self._json({})

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        APPELS.append((self.path, corps))
        self._json({})


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = ThreadingHTTPServer(("127.0.0.1", 0), FauxOutils)
        threading.Thread(target=cls.s.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d" % cls.s.server_address[1]
        cls.ancien = _m.OLLAMA
        _m.OLLAMA = url
        os.environ["COMFY_URL"] = url

    @classmethod
    def tearDownClass(cls):
        _m.OLLAMA = cls.ancien
        os.environ.pop("COMFY_URL", None)
        cls.s.shutdown()

    def setUp(self):
        APPELS.clear()
        FauxOutils.en_cours = 0


class Charges(Base):
    def test_les_modeles_d_ollama_avec_leur_part_sur_la_carte(self):
        c = rc.charges_ollama()
        self.assertEqual([x["id"] for x in c], ["ollama:qwen3:8b", "ollama:nomic-embed-text:latest"])
        q = c[0]
        self.assertEqual((q["vram"], q["ram"]), (5 * 1024 ** 3, 1024 ** 3))
        self.assertIn("15:42", q["detail"])
        self.assertEqual(c[1]["detail"], "", "une expiration « zéro » n'est pas affichée")
        self.assertTrue(all(x["dechargeable"] for x in c))

    def test_comfyui_montre_son_cache_et_ne_se_decharge_pas_en_plein_travail(self):
        c = rc.charges_comfy()
        self.assertEqual(c[0]["vram"], 6 * 1024 ** 3)
        self.assertTrue(c[0]["dechargeable"])
        FauxOutils.en_cours = 1
        c = rc.charges_comfy()
        self.assertFalse(c[0]["dechargeable"])
        self.assertIn("génère 1", c[0]["detail"])

    def test_outils_absents_rien_a_afficher(self):
        ancien = _m.OLLAMA
        _m.OLLAMA = "http://127.0.0.1:9"
        os.environ["COMFY_URL"] = "http://127.0.0.1:9"
        try:
            self.assertEqual(rc.charges_ollama(), [])
            self.assertEqual(rc.charges_comfy(), [])
        finally:
            _m.OLLAMA = ancien
            os.environ["COMFY_URL"] = "http://127.0.0.1:%d" % self.s.server_address[1]

    def test_le_serveur_llamacpp_gere_est_liste_avec_sa_memoire(self):
        class Proc:
            pid = os.getpid()

            def poll(self):
                return None
        ancien = dict(ml.SERVEUR)
        ml.SERVEUR.update(proc=Proc(), modele="un", noms=())
        try:
            c = rc.charges_llamacpp()
            self.assertEqual(c[0]["id"], "llamacpp")
            self.assertEqual(c[0]["nom"], "un")
            self.assertGreater(c[0]["ram"] or 0, 1_000_000, "la mémoire de ce processus Python se lit")
            ml.SERVEUR.update(modele=ml.ROUTEUR, noms=("a", "b"))
            self.assertIn("2 modèles", rc.charges_llamacpp()[0]["nom"])
        finally:
            ml.SERVEUR.update(ancien)
        self.assertEqual(rc.charges_llamacpp(), [], "arrêté : rien à décharger")

    def test_etat_complet(self):
        with mock.patch.object(_m, "memoire_vive", lambda: {"total": 32 * 1024 ** 3, "libre": 10 * 1024 ** 3, "engagement_libre": 0}), \
                mock.patch.object(_m, "memoire_video", lambda: {"nom": "Carte", "total": 12 * 1024 ** 3, "utilise": 8 * 1024 ** 3, "libre": 4 * 1024 ** 3}), \
                mock.patch.object(rc, "lister_processus", lambda: [("ollama", 500), ("chrome", 900), ("chrome", 800)]):
            rc.MEMO["t"] = 0
            e = rc.etat()
        self.assertEqual(e["ram"]["total"], 32 * 1024 ** 3)
        self.assertGreaterEqual(len(e["charges"]), 3)
        self.assertEqual([g["nom"] for g in e["programmes"]], ["chrome", "ollama"])
        self.assertEqual((e["programmes"][0]["nombre"], e["programmes"][0]["octets"], e["programmes"][0]["ia"]), (2, 1700, False))
        self.assertTrue(e["programmes"][1]["ia"])


class Decharger(Base):
    def test_un_modele_d_ollama_est_decharge_avec_keep_alive_zero(self):
        r = rc.decharger("ollama:qwen3:8b")
        self.assertTrue(r["ok"])
        self.assertEqual(APPELS, [("/api/generate", {"model": "qwen3:8b", "prompt": "", "keep_alive": 0})])

    def test_comfyui_libere_ses_modeles(self):
        rc.decharger("comfyui")
        self.assertEqual(APPELS, [("/free", {"unload_models": True, "free_memory": True})])

    def test_llamacpp_s_arrete(self):
        arrete = []
        with mock.patch.object(moteurs.MOTEURS["llamacpp"], "arreter", lambda: arrete.append(1)):
            rc.decharger("llamacpp")
        self.assertEqual(arrete, [1])

    def test_les_demandes_invalides_sont_refusees_sans_rien_envoyer(self):
        for ident in ("", None, "ollama:", "ollama:a b", "ollama:x;y", "ollama:../../etc", "kill:1234", "chrome", "comfyui2"):
            with self.assertRaises(ValueError, msg=repr(ident)):
                rc.decharger(ident)
        self.assertEqual(APPELS, [])

    def test_un_outil_qui_ne_repond_pas_donne_une_erreur_claire(self):
        ancien = _m.OLLAMA
        _m.OLLAMA = "http://127.0.0.1:9"
        try:
            with self.assertRaises(ValueError) as e:
                rc.decharger("ollama:qwen3:8b")
            self.assertIn("qwen3:8b", str(e.exception))
        finally:
            _m.OLLAMA = ancien


class Programmes(unittest.TestCase):
    def test_tasklist_francais_et_anglais(self):
        fr = '"chrome.exe","1234","Console","1","412 356 Ko"\n"ollama.exe","77","Console","1","85 000 Ko"\nligne illisible\n'
        en = '"Code.exe","9","Console","1","1,024,000 K"\n'
        self.assertEqual(rc.analyser_tasklist(fr), [("chrome", 412356 * 1024), ("ollama", 85000 * 1024)])
        self.assertEqual(rc.analyser_tasklist(en), [("Code", 1024000 * 1024)])

    def test_ps_et_proc(self):
        self.assertEqual(rc.analyser_ps("  2048 /usr/bin/python3\n  100 ollama\nbof\n"), [("python3", 2048 * 1024), ("ollama", 100 * 1024)])
        proc = Path(tempfile.mkdtemp(dir=_TEMP))
        for pid, nom, rss in ((12, "llama-server", 4096), (13, "bash", 100)):
            (proc / str(pid)).mkdir()
            (proc / str(pid) / "status").write_text("Name:\t%s\nVmRSS:\t %d kB\n" % (nom, rss), encoding="utf-8")
        (proc / "self").mkdir()
        self.assertEqual(sorted(rc.lire_proc(str(proc))), [("bash", 100 * 1024), ("llama-server", 4096 * 1024)])

    def test_regroupement_et_marquage_des_outils_d_ia(self):
        g = rc.regrouper([("llama-server", 5000), ("python", 100), ("python", 200), ("firefox", 9000)], nombre=3)
        self.assertEqual([x["nom"] for x in g], ["firefox", "llama-server", "python"])
        self.assertEqual([x["ia"] for x in g], [False, True, True])
        self.assertEqual(g[2]["nombre"], 2)

    def test_la_memoire_de_ce_processus_se_lit(self):
        self.assertGreater(rc.memoire_processus(os.getpid()) or 0, 1_000_000)
        self.assertIsNone(rc.memoire_processus(2 ** 30))


class Page(Base):
    def test_les_routes_repondent(self):
        from lutin import serveur
        self.assertTrue(hasattr(serveur, "_ressources"))
        src = Path(serveur.__file__).read_text(encoding="utf-8")
        self.assertIn('"/api/ressources"', src)
        self.assertIn('"/api/decharger"', src)


if __name__ == "__main__":
    unittest.main()


class TestOuEstLeModele(unittest.TestCase):
    """Carte graphique ou mémoire vive ? Le journal de llama-server et nvidia-smi le disent."""

    def test_journal_llamacpp_sur_la_carte(self):
        j = "load_tensors: offloaded 33/33 layers to GPU\nload_tensors:        CUDA0 model buffer size =  4403.49 MiB\nload_tensors:   CPU_Mapped model buffer size =   281.81 MiB\n"
        r = rc.analyser_journal_llamacpp(j)
        self.assertEqual((r["couches_gpu"], r["couches"]), (33, 33))
        self.assertEqual(r["gpu"], int(4403.49 * 1024 ** 2))
        self.assertEqual(r["cpu"], int(281.81 * 1024 ** 2))

    def test_journal_llamacpp_sur_le_processeur(self):
        r = rc.analyser_journal_llamacpp("load_tensors: offloaded 0/33 layers to GPU\nload_tensors:   CPU_Mapped model buffer size =  4685.30 MiB\n")
        self.assertEqual(r["couches_gpu"], 0)
        self.assertEqual(r["gpu"], 0)

    def test_journal_vide(self):
        self.assertIsNone(rc.analyser_journal_llamacpp("rien d'utile"))

    def test_nvidia_smi_par_processus(self):
        r = rc.analyser_gpu_processus("1234, C:\llama\llama-server.exe, 4500\n99, python.exe, [N/A]\n")
        self.assertEqual(r[1234], ("llama-server.exe", 4500 * 1024 ** 2))
        self.assertEqual(r[99], ("python.exe", None))
