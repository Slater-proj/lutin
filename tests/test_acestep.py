"""L'addon ACE-Step : vérification, composition d'un morceau avec accord, attente de la tâche, fichier joint, clé d'API, garde-fous. Contre un FAUX ACE-Step (le vrai serveur et ses modèles
ne sont pas lancés par les tests : la forme des échanges est celle de docs/en/API.md d'ACE-Step 1.5)."""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-acestep-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "LUTIN_WEB_LOCAL": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import addons, addons_acestep as ace  # noqa: E402
from lutin import core as _m  # noqa: E402
from lutin import change_review  # noqa: E402

AUDIO = b"ID3" + b"\x01" * 400
SERVICE = {}


def enveloppe(data, code=200, error=None):
    return {"data": data, "code": code, "error": error, "timestamp": 1700000000000, "extra": None}


class FauxAceStep(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _rep(self, code, corps, type_="application/json"):
        d = corps if isinstance(corps, bytes) else json.dumps(corps).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def _entree(self, corps=b""):
        SERVICE["appels"].append({"methode": self.command, "chemin": self.path, "corps": corps, "auth": self.headers.get("Authorization", "")})
        if SERVICE.get("cle") and self.headers.get("Authorization") != "Bearer " + SERVICE["cle"]:
            self._rep(401, {"detail": "API key required"})
            return False
        return True

    def do_GET(self):
        if not self._entree():
            return
        if self.path == "/health":
            return self._rep(200, enveloppe({"status": "ok", "service": "ACE-Step API", "version": "1.0"}))
        if self.path.startswith("/v1/audio?path="):
            if SERVICE.get("erreur_deguisee"):
                return self._rep(200, {"error": "fichier effacé"})
            return self._rep(200, AUDIO, "audio/mpeg")
        self._rep(404, {"detail": "nope"})

    def do_POST(self):
        corps = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if not self._entree(corps):
            return
        if self.path == "/release_task":
            if SERVICE.get("refus"):
                return self._rep(200, enveloppe(None, code=400, error="prompt vide"))
            return self._rep(200, enveloppe({"task_id": "t-1", "status": "queued", "queue_position": 1}))
        if self.path == "/query_result":
            SERVICE["questions"] = SERVICE.get("questions", 0) + 1
            if SERVICE["questions"] <= SERVICE.get("en_cours", 0):
                return self._rep(200, enveloppe([{"task_id": "t-1", "status": 0, "result": "[]"}]))
            if SERVICE.get("echec"):
                return self._rep(200, enveloppe([{"task_id": "t-1", "status": 2, "result": json.dumps([{"status": 2, "generation_info": "CUDA out of memory"}])}]))
            fichier = SERVICE.get("fichier", "/v1/audio?path=%2Ftmp%2Fapi_audio%2Fabc.mp3")
            return self._rep(200, enveloppe([{"task_id": "t-1", "status": 1, "result": json.dumps([{"file": fichier, "status": 1, "prompt": "x"}])}]))
        self._rep(404, {"detail": "nope"})


class AceStep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur = ThreadingHTTPServer(("127.0.0.1", 0), FauxAceStep)
        cls.port = cls.serveur.server_address[1]
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()

    def setUp(self):
        SERVICE.clear()
        SERVICE["appels"] = []
        for f in addons.folder_data().rglob("*"):
            if f.is_file():
                f.unlink()
        addons.save_settings(ace.IDENT, {"port": str(self.port), "cle": "", "format": "mp3"})
        addons.activate(ace.IDENT, True)
        self.addCleanup(lambda: setattr(ace, "POLL_S", 2.0))
        ace.POLL_S = 0.01

    def ctx(self, accord=True, **plus):
        self.accords = []
        return dict({"accord": lambda t, d, df, auto=False: (self.accords.append((t, d, auto)), accord)[1]}, **plus)

    def envoyes(self, chemin):
        return [a for a in SERVICE["appels"] if a["chemin"] == chemin]

    # --- activation et vérification
    def test_la_verification_dit_que_le_serveur_repond_et_l_activation_exige_qu_il_reponde(self):
        v = addons.check(ace.IDENT)
        self.assertTrue(v["ok"], v)
        self.assertIn("répond", v["etapes"][0]["message"])
        addons.activate(ace.IDENT, False)
        addons.save_settings(ace.IDENT, {"port": "1"})
        with self.assertRaises(addons.AddonError) as e:
            addons.activate(ace.IDENT, True)
        self.assertIn("ne répond pas", str(e.exception))
        self.assertFalse(addons.actif(ace.IDENT))

    def test_port_invalide(self):
        addons.save_settings(ace.IDENT, {"port": "abc"})
        with self.assertRaises(_m.ToolError):
            ace.music_tool({"description": "jazz"}, self.ctx())

    def test_l_outil_est_inutilisable_si_l_addon_est_coupe(self):
        addons.activate(ace.IDENT, False)
        with self.assertRaises(_m.ToolError):
            change_review._call_tool("musique_generer", {"description": "jazz"}, self.ctx())

    def test_le_modele_ne_voit_l_outil_que_si_l_addon_est_actif(self):
        from lutin import agent
        reglages = dict(_m.settings(), web=True)
        addons.activate(ace.IDENT, False)
        self.assertNotIn("musique_generer", {t["function"]["name"] for t in agent.mode_tools(reglages)})
        addons.activate(ace.IDENT, True)
        self.assertIn("musique_generer", {t["function"]["name"] for t in agent.mode_tools(reglages)})

    # --- composer
    def test_composer_demande_l_accord_attend_la_tache_et_joint_le_fichier(self):
        SERVICE["en_cours"] = 2          # deux réponses « en cours » avant la bonne
        ctx = self.ctx()
        res = change_review._call_tool("musique_generer", {"description": "slow jazz piano, warm", "paroles": "[Verse]\nla la la", "duree": 45, "langue": "fr", "format": "wav"}, ctx)
        self.assertIn("Morceau créé", res)
        self.assertEqual(len(self.accords), 1)
        self.assertFalse(self.accords[0][2], "pas d'accord automatique sans la case")
        self.assertIn("slow jazz piano", self.accords[0][1])
        corps = json.loads(self.envoyes("/release_task")[0]["corps"])
        self.assertEqual((corps["prompt"], corps["lyrics"], corps["audio_duration"], corps["vocal_language"], corps["audio_format"]), ("slow jazz piano, warm", "[Verse]\nla la la", 45, "fr", "wav"))
        self.assertEqual(len(self.envoyes("/query_result")), 3, "il attend la fin de la tâche")
        self.assertEqual(json.loads(self.envoyes("/query_result")[0]["corps"]), {"task_id_list": ["t-1"]})
        fichier = Path(ctx["fichiers_joints"][0])
        self.assertEqual(fichier.read_bytes(), AUDIO)
        self.assertTrue(fichier.name.endswith(".wav") and "slow-jazz" in fichier.name)

    def test_sans_paroles_le_morceau_est_instrumental_et_la_duree_reste_dans_les_bornes(self):
        for demande, attendu in ((5, 10), (9999, 600), ("abc", 60), (None, 60), (120, 120)):
            SERVICE["appels"].clear()
            ace.music_tool({"description": "lofi", "duree": demande}, self.ctx())
            corps = json.loads(self.envoyes("/release_task")[0]["corps"])
            self.assertEqual((corps["lyrics"], corps["audio_duration"], corps["audio_format"]), ("[Instrumental]", attendu, "mp3"), repr(demande))

    def test_un_refus_n_envoie_rien(self):
        res = ace.music_tool({"description": "lofi"}, self.ctx(accord=False))
        self.assertIn("Refusé", res)
        self.assertEqual(self.envoyes("/release_task"), [])

    def test_la_case_commandes_automatiques_vaut_accord(self):
        ace.music_tool({"description": "lofi"}, self.ctx(auto_commandes=True))
        self.assertTrue(self.accords[0][2])

    def test_garde_fous_avant_tout_envoi(self):
        for args in ({"description": ""}, {"description": "x" * 5000}, {"description": "ok", "paroles": "y" * 5000}, {"description": "ok", "format": "exe"}):
            with self.assertRaises(_m.ToolError, msg=str(args)[:30]):
                ace.music_tool(args, self.ctx())
        self.assertEqual(self.accords, [])
        self.assertEqual(self.envoyes("/release_task"), [])

    # --- échecs
    def test_une_tache_qui_echoue_dit_pourquoi(self):
        SERVICE["echec"] = True
        with self.assertRaises(_m.ToolError) as e:
            ace.music_tool({"description": "lofi"}, self.ctx())
        self.assertIn("CUDA out of memory", str(e.exception))

    def test_une_demande_refusee_par_le_serveur_dit_pourquoi(self):
        SERVICE["refus"] = True
        with self.assertRaises(_m.ToolError) as e:
            ace.music_tool({"description": "lofi"}, self.ctx())
        self.assertIn("prompt vide", str(e.exception))

    def test_une_tache_trop_longue_est_abandonnee_avec_un_message(self):
        SERVICE["en_cours"] = 10 ** 6
        self.addCleanup(lambda: setattr(ace, "WAIT_MAX_S", 1800))
        ace.WAIT_MAX_S = 0.1
        with self.assertRaises(_m.ToolError) as e:
            ace.music_tool({"description": "lofi"}, self.ctx())
        self.assertIn("n'a pas fini", str(e.exception))

    def test_un_fichier_a_une_autre_adresse_est_refuse_et_rien_n_est_telecharge(self):
        SERVICE["fichier"] = "http://example.org/evil.mp3"
        with self.assertRaises(_m.ToolError) as e:
            ace.music_tool({"description": "lofi"}, self.ctx())
        self.assertIn("inattendu", str(e.exception))
        self.assertEqual([a for a in SERVICE["appels"] if a["methode"] == "GET" and "evil" in a["chemin"]], [])

    def test_une_erreur_deguisee_en_audio_n_est_pas_enregistree_comme_un_fichier(self):
        SERVICE["erreur_deguisee"] = True
        ctx = self.ctx()
        with self.assertRaises(_m.ToolError) as e:
            ace.music_tool({"description": "lofi"}, ctx)
        self.assertIn("fichier effacé", str(e.exception))
        self.assertNotIn("fichiers_joints", ctx)

    # --- clé d'API
    def test_la_cle_est_envoyee_et_jamais_affichee(self):
        SERVICE["cle"] = "secret-tres-long-1234"
        with self.assertRaises(_m.ToolError) as e:
            ace.music_tool({"description": "lofi"}, self.ctx())
        self.assertIn("clé API", str(e.exception))
        self.assertNotIn("secret-tres-long-1234", str(e.exception))
        addons.save_settings(ace.IDENT, {"port": str(self.port), "cle": "secret-tres-long-1234", "format": "mp3"})
        SERVICE["appels"].clear()
        ace.music_tool({"description": "lofi"}, self.ctx())
        self.assertTrue(all(a["auth"] == "Bearer secret-tres-long-1234" for a in SERVICE["appels"]))


if __name__ == "__main__":
    unittest.main()
