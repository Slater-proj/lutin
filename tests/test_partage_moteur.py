"""Le moteur d'une machine prêtée est partagé entre son utilisateur et les autres machines : pas de panne imaginaire quand il est occupé, attente longue acceptée, charge visible ; un seul Lutin par port ; l'ancienne tâche de démarrage est retirée ; un llama-server se reconnaît à sa ligne de commande."""
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-partage-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import alimentation, machines  # noqa: E402
from lutin import ressources_chargees as rc  # noqa: E402


class Local:
    id, nom = "ollama", "Ollama"

    def __init__(self, installes):
        self.installes, self.appels = installes, 0

    def modeles(self):
        return {"actif": True, "installes": self.installes}

    def chat(self, corps, delai=60):
        self.appels += 1
        return {"message": {"role": "assistant", "content": "réponse locale"}, "done": True}


def operationnelle(modeles):
    return lambda m, modele="", *a, **kw: {"etat": "operationnel", "detail": "", "modeles": modeles}


def erreur_http(code):
    return urllib.error.HTTPError("http://x", code, "occupée", {}, None)


class PartageDuMoteur(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-partage-t-"))
        machines.DOSSIER = self.tmp
        machines.REGISTRE.update(t=0.0)
        machines.SONDES.clear()
        machines.DISTANTS.update(t=0.0, v=[], en_cours=False)
        self.addCleanup(setattr, machines, "DOSSIER", None)
        self.m = {"id": "b" * 32, "nom": "Gros PC", "adresse": "http://192.168.1.20:8777", "jeton": "t", "mac": "", "ajoutee": "x"}
        machines._ecrire_registre([self.m])

    def test_machine_occupee_429_n_est_pas_une_panne_le_local_repond(self):
        r = machines.Routage(Local(["petit:8b"]), self.m)
        with mock.patch.object(machines, "sonder", operationnelle(["petit:8b"])), mock.patch.object(machines, "requete", side_effect=erreur_http(429)):
            rep = r.chat({"model": "petit:8b", "messages": []})
        self.assertEqual(rep["message"]["content"], "réponse locale")
        self.assertEqual([k for k, v in machines.SONDES.items() if v[1]["etat"] == "injoignable"], [], "occupée n'est pas injoignable")

    def test_modele_qui_n_existe_que_la_bas_et_machine_occupee_message_clair(self):
        machines.DISTANTS.update(t=machines.time.monotonic(), v=[{"id": self.m["id"], "nom": "Gros PC", "etat": "operationnel", "modeles": ["gros:70b"]}])
        r = machines.Routage(Local(["petit:8b"]), self.m)
        with mock.patch.object(machines, "sonder", operationnelle(["gros:70b"])), mock.patch.object(machines, "requete", side_effect=erreur_http(429)):
            with self.assertRaises(ValueError) as e:
                r.chat({"model": "gros:70b", "messages": []})
        self.assertIn("répond déjà à d'autres demandes", str(e.exception))

    def test_la_demande_attend_le_moteur_longtemps_pas_30_secondes(self):
        r = machines.Routage(Local(["petit:8b"]), self.m)
        delais = []

        def requete(m, chemin, corps=None, jeton="", delai=0, ouvrir=None):
            delais.append(delai)
            raise OSError("fin du test")
        with mock.patch.object(machines, "sonder", operationnelle(["petit:8b"])), mock.patch.object(machines, "requete", requete):
            r.chat({"model": "petit:8b", "messages": []}, 600)
        self.assertEqual(delais, [600])

    def test_la_charge_du_noeud_est_dite_a_l_autre_machine(self):
        c = machines.noeud_charge(True, 2)
        self.assertEqual((c["locale_occupee"], c["distantes"]), (True, 2))
        self.assertIn("ram", c)
        with mock.patch.object(machines, "_json", lambda m, chemin, corps=None, **kw: {"id": self.m["id"], "actif": True, "modeles": ["a"], "moteur_nom": "Ollama", "charge": c}):
            r = machines.sonder(self.m, "", force=True)
        self.assertEqual(r["charge"]["distantes"], 2)


class DemarrageSansDoublon(unittest.TestCase):
    def test_installer_le_demarrage_retire_l_ancienne_tache_planifiee(self):
        class Registre:
            def __init__(self):
                self.v = {}

            def lire(self, nom):
                return self.v.get(nom, "")

            def ecrire(self, nom, valeur):
                self.v[nom] = valeur

            def supprimer(self, nom):
                self.v.pop(nom, None)
        appels = []
        alimentation.installer_demarrage(lanceur=lambda cmd, **kw: appels.append(cmd) or type("R", (), {"returncode": 0})(), systeme_actuel="windows", commande=["python", "-m", "lutin"], registre=Registre())
        self.assertTrue(any(c[:2] == ["schtasks", "/Delete"] for c in appels), "sinon deux Lutin se lanceraient à l'ouverture de session")

    def test_un_second_lutin_sur_le_meme_port_s_arrete_avant_de_lancer_quoi_que_ce_soit(self):
        occupe = socket.socket()
        occupe.bind(("127.0.0.1", 0))
        occupe.listen(1)
        port = occupe.getsockname()[1]
        avant = (sys.excepthook, threading.excepthook)
        lances = []
        try:
            with mock.patch.object(_m, "PORT", port), mock.patch.object(_m, "boucle_surveillance", lambda: lances.append("surveillance")), mock.patch.object(_m, "purger_sauvegardes", lambda: lances.append("purge")):
                with self.assertRaises(SystemExit) as e:
                    _m.principal()
        finally:
            occupe.close()
            sys.excepthook, threading.excepthook = avant
        self.assertIn("déjà pris", str(e.exception), "message clair, pas une trace")
        self.assertEqual(lances, [], "rien (surveillance, missions, tâches planifiées) n'est lancé par un second Lutin")

    def test_le_port_est_exclusif_sous_windows_et_les_redemarrages_sont_absorbes(self):
        if os.name == "nt":
            self.assertFalse(_m.ServeurLutin.allow_reuse_address, "sinon deux Lutin peuvent écouter sur le même port")
        occupe = socket.socket()
        occupe.bind(("127.0.0.1", 0))
        occupe.listen(1)
        port = occupe.getsockname()[1]
        pauses = []
        try:
            with mock.patch.object(_m, "PORT", port):
                if os.name == "nt":
                    with self.assertRaises(OSError):
                        _m.lier_le_port("127.0.0.1", essais=3, dormir=pauses.append)
                    self.assertEqual(len(pauses), 2, "quelques essais rapprochés avant de renoncer")
        finally:
            occupe.close()
        with mock.patch.object(_m, "PORT", port):
            s = _m.lier_le_port("127.0.0.1", essais=1)          # le port s'est libéré : l'ouverture réussit
            s.server_close()


class GardeFousDesTests(unittest.TestCase):
    """Un test ne doit jamais modifier la machine de développement : ni le vrai registre Windows, ni installer un vrai programme."""

    def test_le_vrai_registre_est_interdit_aux_tests(self):
        self.assertEqual(os.environ.get("LUTIN_TESTS"), "1")
        with self.assertRaises(OSError):
            alimentation.RegistreWindows().ecrire("Lutin", "x")
        with self.assertRaises(OSError):
            alimentation.RegistreWindows().supprimer("Lutin")

    def test_l_installation_reelle_d_ollama_est_interdite_aux_tests(self):
        from lutin import ollama_client
        with self.assertRaises(ollama_client.ErreurOllama):
            ollama_client.installer_windows(tempfile.mkdtemp(prefix="lutin-garde-"))


class JetonGitHub(unittest.TestCase):
    """Un jeton GITHUB_TOKEN (la CI) n'est envoyé qu'à l'API de GitHub, jamais ailleurs."""

    def test_le_jeton_ne_part_qu_vers_api_github(self):
        from lutin import moteur_llamacpp as ml
        vus = []

        class Reponse:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "jeton-secret"}), mock.patch.object(ml.urllib.request, "urlopen", lambda req, timeout=0: vus.append(req) or Reponse()):
            ml._http_json("https://api.github.com/repos/ggml-org/llama.cpp/releases")
            ml._http_json("https://huggingface.co/api/models")
        self.assertEqual(vus[0].get_header("Authorization"), "Bearer jeton-secret")
        self.assertIsNone(vus[1].get_header("Authorization"), "pas de jeton envoyé à un autre site")
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": ""}), mock.patch.object(ml.urllib.request, "urlopen", lambda req, timeout=0: vus.append(req) or Reponse()):
            ml._http_json("https://api.github.com/x")
        self.assertIsNone(vus[2].get_header("Authorization"))


class ReconnaitreUnLlamaServer(unittest.TestCase):
    def test_port_et_modele_viennent_de_la_ligne_de_commande(self):
        self.assertEqual(rc.decrire_commande('"E:/IA/llama.cpp/bin/llama-server.exe" -m "E:/IA/modeles/qwen3-27b.gguf" -c 8192 --port 8081'), "sur le port 8081, modèle qwen3-27b.gguf")
        self.assertEqual(rc.decrire_commande("llama-server --models-preset C:/x/modeles.ini --port 8080"), "sur le port 8080, modèle modeles.ini")
        self.assertEqual(rc.decrire_commande(""), "")

    def test_un_programme_sans_chemin_connu_est_reconnu_par_sa_ligne_de_commande(self):
        dossier = Path(tempfile.mkdtemp(prefix="lutin-llama-cmd-")).resolve()
        with mock.patch.object(rc, "dossiers_lutin", lambda: [dossier]):
            self.assertFalse(rc._chez_lutin("", "llama-server -m x.gguf --port 8081"))
            self.assertTrue(rc._chez_lutin("", 'llama-server --models-preset "{}/modeles.ini"'.format(str(dossier).replace("\\", "/"))))
            self.assertTrue(rc._chez_lutin(str(dossier / "bin" / "llama-server.exe"), ""))

    def test_la_ligne_de_commande_est_lue_dans_le_json_de_windows(self):
        r = rc.analyser_instantane('[{"pid": 5, "ppid": 1, "nom": "llama-server.exe", "exe": null, "cmd": "llama-server --port 8081", "ram": 10, "vram": null}]')
        self.assertEqual((r[0]["cmd"], r[0]["exe"]), ("llama-server --port 8081", ""))


if __name__ == "__main__":
    unittest.main()
