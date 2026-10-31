"""Les missions longues : un cahier des charges mené tour après tour, seul, jusqu'au bilan ; autonomie choisie, limites, reprise, question du modèle."""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-mission-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402
from lutin import mission  # noqa: E402

MODE, RECUES = {"v": "normal"}, []


def appel(nom, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": nom, "arguments": args}}]}


class FauxOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        corps = json.dumps({"models": [{"name": "qwen3.8:27b"}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/show":
            d = json.dumps({"capabilities": ["completion", "tools"]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(d)))
            self.end_headers()
            self.wfile.write(d)
            return
        RECUES.append(corps)
        msgs = corps.get("messages", [])
        dernier = msgs[-1] if msgs else {}
        noms = {t["function"]["name"] for t in corps.get("tools", [])}
        reponse = {"role": "assistant", "content": "Étape faite."}
        if dernier.get("role") == "user" and dernier.get("content", "").startswith("MISSION") and MODE["v"] == "normal":
            reponse = appel("ecrire", chemin="jeu.txt", contenu="version 1")
        elif dernier.get("role") == "user" and dernier.get("content", "").startswith("Continue la mission") and MODE["v"] == "normal":
            reponse = appel("mission_terminer", bilan="Jeu écrit dans jeu.txt.") if "mission_terminer" in noms else {"role": "assistant", "content": "pas d'outil de fin"}
        elif dernier.get("role") == "user" and dernier.get("content", "").startswith("Continue la mission") and MODE["v"] == "question":
            reponse = appel("mission_bloquee", question="Quel moteur utiliser ?")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        if not corps.get("stream", True):
            self.wfile.write(json.dumps({"message": reponse, "done": True}).encode("utf-8"))
            return
        self.wfile.write((json.dumps({"message": reponse, "done": True}) + "\n").encode("utf-8"))


class Mission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur = ThreadingHTTPServer(("127.0.0.1", 0), FauxOllama)
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()
        cls.vrai_ollama, _m.OLLAMA = _m.OLLAMA, "http://127.0.0.1:%d" % cls.serveur.server_address[1]
        cls.dossier = _TEMP / "travail"
        cls.dossier.mkdir()
        cls.vrai_config = _m.config_lue
        _m.config_lue = lambda: {"emplacements": {"travail": str(cls.dossier)}}

    @classmethod
    def tearDownClass(cls):
        _m.OLLAMA, _m.config_lue = cls.vrai_ollama, cls.vrai_config
        cls.serveur.shutdown()

    def setUp(self):
        MODE["v"] = "normal"
        RECUES.clear()
        _m.TOURS_ACTIFS.clear()
        _m.RACINE_TOURS.clear()
        for m in mission.lire():
            mission.action("supprimer", {"id": m["id"]})
        for f in self.dossier.glob("*"):
            f.unlink()

    def creer(self, **kw):
        return mission.creer(kw.get("nom", "Jeu"), kw.get("cahier", "Crée un petit jeu."), "principal", kw.get("duree_h", 8), kw.get("autonome", True))

    def test_une_mission_autonome_travaille_seule_puis_rend_son_bilan(self):
        m = self.creer()
        self.assertTrue(mission.un_pas())                                      # tour 1 : le plan puis le fichier, sans que personne n'accepte
        self.assertEqual((self.dossier / "jeu.txt").read_text(encoding="utf-8"), "version 1")
        self.assertEqual(mission.trouver(m["id"])["etat"], "en_cours")
        self.assertTrue(mission.un_pas())                                      # tour 2 : le modèle déclare la fin
        fin = mission.trouver(m["id"])
        self.assertEqual((fin["etat"], fin["bilan"], fin["tours"]), ("terminee", "Jeu écrit dans jeu.txt.", 2))
        self.assertGreaterEqual(fin["actions"], 2)
        self.assertFalse(mission.un_pas(), "une mission terminée ne tourne plus")
        self.assertTrue(fin["conv"])
        self.assertTrue(_m.conv_lire(fin["conv"])["titre"].startswith("🎯"))

    def test_le_modele_recoit_les_outils_de_mission_et_la_consigne_seulement_pendant_une_mission(self):
        self.creer()
        mission.un_pas()
        outils = {t["function"]["name"] for t in RECUES[0]["tools"]}
        self.assertTrue({"mission_terminer", "mission_bloquee", "suivi", "executer"} <= outils)
        self.assertIn("MISSION LONGUE", RECUES[0]["messages"][0]["content"])
        from lutin import dialogue
        self.assertNotIn("mission_terminer", {t["function"]["name"] for t in dialogue.outils_du_mode(_m.reglages())})

    def test_sans_autonomie_rien_n_est_ecrit(self):
        m = self.creer(autonome=False)
        mission.un_pas()
        self.assertFalse((self.dossier / "jeu.txt").exists())
        self.assertEqual(mission.trouver(m["id"])["etat"], "en_cours")

    def test_le_modele_pose_une_question_et_la_reponse_est_donnee_au_tour_suivant(self):
        m = self.creer()
        mission.un_pas()
        MODE["v"] = "question"
        mission.un_pas()
        x = mission.trouver(m["id"])
        self.assertEqual((x["etat"], x["question"]), ("bloquee", "Quel moteur utiliser ?"))
        self.assertFalse(mission.un_pas(), "bloquée : elle attend")
        mission.action("repondre", {"id": m["id"], "texte": "Godot"})
        self.assertEqual(mission.trouver(m["id"])["etat"], "en_cours")
        MODE["v"] = "normal"
        mission.un_pas()
        dernier = RECUES[-1]["messages"]
        self.assertTrue(any("Godot" in (x.get("content") or "") for x in dernier if x.get("role") == "user"))
        self.assertEqual(mission.trouver(m["id"])["note"], "")

    def test_pause_reprise_arret(self):
        m = self.creer()
        mission.action("pause", {"id": m["id"]})
        self.assertFalse(mission.un_pas())
        mission.action("reprendre", {"id": m["id"]})
        self.assertEqual(mission.trouver(m["id"])["etat"], "en_cours")
        mission.action("arreter", {"id": m["id"]})
        self.assertEqual(mission.trouver(m["id"])["etat"], "terminee")

    def test_trois_reponses_sans_aucune_action_demandent_de_l_aide(self):
        MODE["v"] = "muet"
        m = self.creer()
        for _ in range(mission.SANS_ACTION_MAX):
            mission.un_pas()
        x = mission.trouver(m["id"])
        self.assertEqual(x["etat"], "bloquee")
        self.assertIn("n'avance plus", x["question"])

    def test_la_duree_maximale_arrete_la_mission(self):
        m = self.creer()
        mission.modifier(m["id"], debut=0)
        mission.un_pas()
        self.assertEqual(mission.trouver(m["id"])["etat"], "terminee")

    def test_les_champs_sont_verifies(self):
        for kw in ({"nom": ""}, {"cahier": ""}, {"cahier": "x" * (mission.CAHIER_MAX + 1)}):
            with self.assertRaises(ValueError):
                self.creer(**kw)
        with self.assertRaises(ValueError):
            mission.creer("x", "y", "dossier-inconnu")
        self.assertEqual(self.creer(duree_h=500)["duree_h"], mission.DUREE_MAX_H)
        for _ in range(mission.MAX_MISSIONS - 1):
            self.creer()
        with self.assertRaises(ValueError):
            self.creer()

    def test_une_mission_est_reprise_apres_un_redemarrage(self):
        m = self.creer()
        mission.un_pas()
        avant = mission.trouver(m["id"])["conv"]
        mission.VIVANT["arrets"].clear()                                       # « redémarrage » : seul le fichier d'état reste
        mission.un_pas()
        self.assertEqual(mission.trouver(m["id"])["conv"], avant, "même conversation")
        self.assertEqual(mission.trouver(m["id"])["etat"], "terminee")


if __name__ == "__main__":
    unittest.main()
