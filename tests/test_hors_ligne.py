"""Mode hors ligne strict : aucune connexion vers autre chose que cette machine et les services déclarés (vérifié sur les connexions réelles)."""
import http.client
import json
import os
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-horsligne-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import horsligne, miseajour, ollama_client  # noqa: E402
from lutin import moteur as A  # noqa: E402
from lutin import securite as S  # noqa: E402
from lutin.machine import Gpu, Profil  # noqa: E402


class FauxOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        corps = json.dumps({"models": [{"name": "qwen2.5-coder:7b", "digest": "d"}]} if self.path == "/api/tags" else {"version": "0.12"}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(corps))); self.end_headers(); self.wfile.write(corps)


SERVEUR = ThreadingHTTPServer(("127.0.0.1", 0), FauxOllama)
threading.Thread(target=SERVEUR.serve_forever, daemon=True).start()
ADRESSE_OLLAMA = "http://127.0.0.1:%d" % SERVEUR.server_address[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.config = Path(self.t.name) / "config" / "config.json"
        self.config.parent.mkdir()
        self.config.write_text(json.dumps({"hors_ligne": False}), encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"LUTIN_CONFIG": str(self.config), "OLLAMA_URL": ADRESSE_OLLAMA})
        self.env.start()
        os.environ.pop("LUTIN_HORS_LIGNE", None)

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def couper(self, valeur=True):
        horsligne.definir(valeur, self.config)


class Etat(Base):
    def test_lecture_de_la_configuration_et_changement_pris_en_compte_tout_de_suite(self):
        self.assertFalse(horsligne.actif())
        self.couper(True)
        self.assertTrue(horsligne.actif())
        self.assertTrue(json.loads(self.config.read_text(encoding="utf-8"))["hors_ligne"])
        self.couper(False)
        self.assertFalse(horsligne.actif())

    def test_variable_d_environnement_force_le_mode(self):
        with mock.patch.dict(os.environ, {"LUTIN_HORS_LIGNE": "1"}):
            self.assertTrue(horsligne.actif())
        with mock.patch.dict(os.environ, {"LUTIN_HORS_LIGNE": "non"}):
            self.assertFalse(horsligne.actif())

    def test_fichier_absent_ou_abime_n_active_rien_et_ne_plante_pas(self):
        self.config.write_text("{pas du json", encoding="utf-8")
        self.assertFalse(horsligne.actif())
        self.config.unlink()
        self.assertFalse(horsligne.actif())

    def test_definir_garde_le_reste_de_la_configuration(self):
        self.config.write_text(json.dumps({"installe": True, "securite": {"niveau": "reseau"}}), encoding="utf-8")
        self.couper(True)
        d = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual((d["installe"], d["securite"]["niveau"], d["hors_ligne"]), (True, "reseau", True))

    def test_garde(self):
        horsligne.garde("https://exemple.org/x")            # mode coupé : tout passe
        self.couper(True)
        for ok in (ADRESSE_OLLAMA + "/api/tags", "http://localhost:11434/", "http://127.0.0.1/"):
            horsligne.garde(ok)
        for non in ("https://exemple.org/x", "http://192.168.1.10/", "https://registry.ollama.ai/v2/library/qwen3/manifests/8b", "http:///"):
            with self.assertRaises(horsligne.HorsLigne, msg=non):
                horsligne.garde(non)

    def test_les_services_declares_sont_autorises(self):
        self.couper(True)
        with mock.patch.dict(os.environ, {"OLLAMA_URL": "http://ollama:11434", "LUTIN_OUTIL_URL": "http://192.168.1.50:8765"}):
            horsligne.garde("http://ollama:11434/api/tags")
            horsligne.garde("http://192.168.1.50:8765/api/sante")
            with self.assertRaises(horsligne.HorsLigne):
                horsligne.garde("http://192.168.1.51:8765/")

    def test_exiger_en_ligne(self):
        horsligne.exiger_en_ligne("télécharger")
        self.couper(True)
        with self.assertRaises(horsligne.HorsLigne) as e:
            horsligne.exiger_en_ligne("télécharger un modèle")
        self.assertIn("télécharger un modèle", str(e.exception))


class Points_de_sortie(Base):
    def setUp(self):
        super().setUp()
        self.couper(True)
        self.contacts = []
        reel = socket.socket.connect

        def espion(sock, adresse, *a, **k):
            self.contacts.append(adresse[0] if isinstance(adresse, tuple) else str(adresse))
            return reel(sock, adresse, *a, **k)
        self.espion = mock.patch.object(socket.socket, "connect", espion)
        self.espion.start()

    def tearDown(self):
        self.espion.stop()
        super().tearDown()

    def exterieur(self):
        return [c for c in self.contacts if c not in ("127.0.0.1", "::1", "localhost")]

    def test_telechargement_de_modele_refuse_sans_contacter_ollama(self):
        with self.assertRaises(horsligne.HorsLigne):
            ollama_client.Ollama(ADRESSE_OLLAMA).telecharger("qwen3:8b")
        self.assertEqual(self.contacts, [])
        with self.assertRaises(horsligne.HorsLigne):
            A.installer_modele("qwen3:8b")
        self.assertEqual(self.contacts, [])

    def test_telechargement_de_fichier_refuse(self):
        with self.assertRaises(horsligne.HorsLigne):
            ollama_client.telecharger_fichier("https://ollama.com/download/OllamaSetup.exe", Path(self.t.name) / "x.exe")
        self.assertEqual(self.contacts, [])

    def test_web_refuse_et_outils_web_retires(self):
        with self.assertRaises(A.ErreurOutil) as e:
            A.web_telecharger("https://exemple.org/")
        self.assertIn("hors ligne", str(e.exception))
        self.assertEqual(self.exterieur(), [])
        noms = {t["function"]["name"] for t in A.outils_du_mode(dict(A.REGLAGES_DEFAUT, web=True))}
        self.assertFalse(noms & {"web_chercher", "web_lire"})
        self.couper(False)
        noms = {t["function"]["name"] for t in A.outils_du_mode(dict(A.REGLAGES_DEFAUT, web=True))}
        self.assertTrue({"web_chercher", "web_lire"} <= noms)

    def test_verification_des_modeles_ne_sort_pas_sur_internet(self):
        machine = Profil(ram_go=32, ram_libre_go=20, gpus=[Gpu("x", "nvidia", 24)])
        cfg = {"modeles": {"choisis": {"code": "qwen2.5-coder:7b"}, "ignores": []}, "catalogue_url": "https://exemple.org/catalogue.json"}
        d = {"cache": Path(self.t.name) / "cache", "config": self.config.parent}
        r = miseajour.verifier(machine, cfg, d, ollama_client.Ollama(ADRESSE_OLLAMA), force=True)        # vrai http_get, vraie résolution : rien ne doit partir
        self.assertEqual(self.exterieur(), [], "aucune connexion vers autre chose que cette machine")
        self.assertTrue(any("hors ligne" in e for e in r["erreurs"]))
        self.assertEqual([p["type"] for p in r["propositions"]], ["nouveau"], "la comparaison avec la liste livrée reste possible")
        self.assertEqual(r["catalogue"], "absent")

    def test_http_get_refuse_directement(self):
        with self.assertRaises(horsligne.HorsLigne):
            miseajour.http_get("https://registry.ollama.ai/v2/library/qwen3/manifests/8b")
        self.assertEqual(self.contacts, [])

    def test_ce_qui_reste_local_fonctionne(self):
        self.assertTrue(ollama_client.Ollama(ADRESSE_OLLAMA).actif())
        self.assertIn("qwen2.5-coder:7b", ollama_client.Ollama(ADRESSE_OLLAMA).installes())
        self.assertEqual(set(self.exterieur()), set())


class Serveur(Base):
    def setUp(self):
        super().setUp()
        self.avant = (A.SECURITE, A.APPAREILS)
        A.SECURITE = S.Securite()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), A.Gestionnaire)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        A.SECURITE, A.APPAREILS = self.avant
        super().tearDown()

    def appel(self, methode, chemin, corps=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(methode, chemin, body=json.dumps(corps).encode() if corps is not None else None,
                  headers={"Host": "127.0.0.1:%d" % self.port, "X-Token": A.JETON, "Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read().decode("utf-8") or "{}")

    def test_bascule_par_l_api_et_visible_dans_l_etat(self):
        self.assertFalse(self.appel("GET", "/api/etat")[1]["hors_ligne"])
        self.assertEqual(self.appel("POST", "/api/hors-ligne", {"actif": True}), (200, {"hors_ligne": True}))
        self.assertTrue(self.appel("GET", "/api/etat")[1]["hors_ligne"])
        statut, d = self.appel("POST", "/api/installer-modele", {"modele": "qwen3:8b"})
        self.assertEqual(statut, 400)
        self.assertIn("hors ligne", d["erreur"])
        self.assertEqual(self.appel("POST", "/api/hors-ligne", {"actif": False}), (200, {"hors_ligne": False}))
        self.assertFalse(json.loads(self.config.read_text(encoding="utf-8"))["hors_ligne"])


if __name__ == "__main__":
    unittest.main()
