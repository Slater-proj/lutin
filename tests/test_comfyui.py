"""L'addon ComfyUI : détection, modèles installés (API ou dossier), génération avec accord, workflow modifiable, arrêt propre, garde-fous."""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-comfy-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "LUTIN_WEB_LOCAL": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import addons, addons_comfyui as cu  # noqa: E402
from lutin import moteur as _m  # noqa: E402

COMFY = _TEMP / "ComfyUI"
SERVICE = {"panne": False, "soumis": [], "histoire": 0, "refus": False, "interrompu": 0, "erreur_historique": False}


class FauxComfy(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _rep(self, code, corps):
        d = json.dumps(corps).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def do_GET(self):
        if SERVICE["panne"]:
            return self._rep(503, {"error": "down"})
        if self.path.startswith("/system_stats"):
            return self._rep(200, {"system": {"comfyui_version": "0.3.9", "argv": [str(COMFY / "main.py")]}, "devices": [{"name": "GPU de test"}]})
        for noeud, champ, noms in (("CheckpointLoaderSimple", "ckpt_name", ["sdxl.safetensors", "sd15.safetensors"]), ("LoraLoader", "lora_name", ["style.safetensors"])):
            if self.path.startswith("/object_info/" + noeud):
                return self._rep(200, {noeud: {"input": {"required": {champ: [noms, {}]}}}})
        if self.path.startswith("/object_info/"):
            return self._rep(200, {})
        if self.path.startswith("/history/abc"):
            SERVICE["histoire"] += 1
            if SERVICE["histoire"] < 2:
                return self._rep(200, {})
            if SERVICE["erreur_historique"]:
                return self._rep(200, {"abc": {"status": {"status_str": "error", "messages": [["execution_error", {"exception_message": "out of memory"}]]}, "outputs": {}}})
            return self._rep(200, {"abc": {"status": {"status_str": "success"}, "outputs": {"9": {"images": [{"filename": "lutin_00001_.png", "subfolder": "", "type": "output"}]}}}})
        return self._rep(404, {})

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8") or "{}")
        if self.path.startswith("/interrupt"):
            SERVICE["interrompu"] += 1
            return self._rep(200, {})
        if self.path.startswith("/prompt"):
            if SERVICE["refus"]:
                return self._rep(400, {"error": {"message": "Prompt outputs failed validation"}, "node_errors": {"4": "ckpt_name inconnu"}})
            SERVICE["soumis"].append(corps)
            return self._rep(200, {"prompt_id": "abc", "number": 1, "node_errors": {}})
        return self._rep(404, {})


class FauxSiteDeModeles(BaseHTTPRequestHandler):
    """Un site qui sert des fichiers de modèles (et des pièges : page web, redirection vers un autre site, fichier tronqué, envoi lent)."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        chemin = self.path.split("?")[0]
        if chemin == "/modele.safetensors":
            corps = b"x" * 3_000_000
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)
        elif chemin == "/page.safetensors":
            corps = b"<html>connecte-toi</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)
        elif chemin == "/ailleurs.safetensors":
            self.send_response(302)
            self.send_header("Location", "http://evil.example.com/modele.safetensors")
            self.end_headers()
        elif chemin == "/tronque.safetensors":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", "2000000")
            self.end_headers()
            self.wfile.write(b"x" * 1000)
        elif chemin == "/lent.safetensors":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(50 * 1024 * 1024))
            self.end_headers()
            try:
                for _ in range(50):
                    self.wfile.write(b"x" * 1024 * 1024)
                    time.sleep(0.2)
            except OSError:
                pass
        else:
            self.send_response(404)
            self.end_headers()


class ComfyUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur = ThreadingHTTPServer(("127.0.0.1", 0), FauxComfy)
        cls.port = cls.serveur.server_address[1]
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()
        (COMFY / "models" / "checkpoints").mkdir(parents=True)
        (COMFY / "models" / "loras").mkdir()
        (COMFY / "main.py").write_text("# comfy", encoding="utf-8")
        (COMFY / "models" / "checkpoints" / "local.safetensors").write_bytes(b"x")
        (COMFY / "models" / "checkpoints" / "notes.txt").write_text("pas un modèle", encoding="utf-8")
        (COMFY / "models" / "loras" / "sous").mkdir()
        (COMFY / "models" / "loras" / "sous" / "visage.safetensors").write_bytes(b"x")

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()

    def setUp(self):
        SERVICE.update(panne=False, soumis=[], histoire=0, refus=False, interrompu=0, erreur_historique=False)
        cu.CACHE["modeles"] = (0, None)
        for f in addons.dossier_donnees().rglob("*"):
            if f.is_file():
                f.unlink()
        addons.enregistrer_reglages(cu.IDENT, {"port": str(self.port), "dossier": "", "modele": ""})
        self.vram = []
        self.vrai_vram = _m.liberer_vram
        _m.liberer_vram = lambda *a, **k: self.vram.append(1)
        self.vrai_pause = time.sleep
        cu.time.sleep = lambda s: self.vrai_pause(0.01)                          # le test n'attend pas les 2 s entre deux regards

    def tearDown(self):
        _m.liberer_vram = self.vrai_vram
        cu.time.sleep = self.vrai_pause

    def ctx(self, accord=True, **plus):
        self.accords = []
        return dict({"accord": lambda t, d, df: (self.accords.append((t, d)), accord)[1], "stop": threading.Event()}, **plus)

    def test_verification_detection_et_dossier_trouve_par_comfyui_lui_meme(self):
        v = addons.verifier(cu.IDENT)
        self.assertTrue(v["ok"], v)
        self.assertIn("0.3.9", v["etapes"][0]["message"])
        d = cu.detecter()
        self.assertEqual((d["tourne"], d["version"], d["gpu"]), (True, "0.3.9", "GPU de test"))
        self.assertEqual(Path(d["dossier"]), COMFY, "le chemin de main.py est annoncé par ComfyUI : le dossier est prérempli")
        SERVICE["panne"] = True
        d = cu.detecter()
        self.assertFalse(d["tourne"])
        self.assertFalse(addons.verifier(cu.IDENT)["ok"], "ComfyUI éteint : la vérification le dit")

    def test_modeles_par_l_api_puis_par_le_dossier(self):
        r = cu.lister_modeles()
        self.assertEqual(r["source"], "api")
        self.assertEqual(r["modeles"]["checkpoints"], ["sdxl.safetensors", "sd15.safetensors"])
        self.assertEqual(r["modeles"]["loras"], ["style.safetensors"])
        SERVICE["panne"] = True
        cu.CACHE["modeles"] = (0, None)
        self.assertEqual(cu.lister_modeles()["source"], "aucune", "ComfyUI éteint et pas de dossier réglé : rien à lister")
        self.assertIn("impossible", cu.texte_modeles())
        with self.assertRaises(addons.ErreurAddon):
            cu.action("utiliser_dossier", {"dossier": str(_TEMP)})
        cu.action("utiliser_dossier", {"dossier": str(COMFY)})
        SERVICE["panne"] = True
        r = cu.lister_modeles(forcer=True)
        self.assertEqual(r["source"], "dossier")
        self.assertEqual(r["modeles"]["checkpoints"], ["local.safetensors"], "seuls les fichiers de modèles sont listés")
        self.assertEqual(r["modeles"]["loras"], ["sous/visage.safetensors"])
        self.assertIn("dans le dossier d'installation", cu.texte_modeles())

    def test_generer_une_image_avec_accord_et_valeurs_typees(self):
        ctx = self.ctx()
        res = cu.outil_generer({"prompt": "un chat astronaute", "largeur": 1000, "hauteur": 99999, "graine": 7}, ctx)
        self.assertIn("lutin_00001_.png", res)
        self.assertIn("Graine : 7", res)
        self.assertEqual(len(self.accords), 1, "un accord est demandé")
        self.assertIn("chat astronaute", self.accords[0][1])
        self.assertEqual(self.vram, [1], "la carte graphique est libérée du modèle de langage")
        wf = SERVICE["soumis"][0]["prompt"]
        self.assertEqual((wf["5"]["inputs"]["width"], wf["5"]["inputs"]["height"]), (1000, 4096), "bornes, multiple de 8 et type nombre")
        self.assertEqual(wf["6"]["inputs"]["text"], "un chat astronaute")
        self.assertEqual((wf["3"]["inputs"]["seed"], wf["3"]["inputs"]["steps"], wf["3"]["inputs"]["cfg"]), (7, 25, 6.5))
        self.assertEqual(wf["4"]["inputs"]["ckpt_name"], "sdxl.safetensors", "sans modèle demandé : le premier installé")
        addons.enregistrer_reglages(cu.IDENT, {"modele": "sd15.safetensors"})
        SERVICE["histoire"] = 0
        cu.outil_generer({"prompt": "x", "modele": "perso.safetensors"}, self.ctx())
        self.assertEqual(SERVICE["soumis"][1]["prompt"]["4"]["inputs"]["ckpt_name"], "perso.safetensors", "ce que le modèle demande l'emporte")
        for faux in ({"prompt": ""}, {"prompt": "x", "type": "hologramme"}, {"prompt": "x", "largeur": "beaucoup"}, {"prompt": "x", "type": "video"}):
            with self.assertRaises(_m.ErreurOutil):
                cu.outil_generer(faux, self.ctx())

    def test_refus_essai_a_blanc_erreurs_et_arret(self):
        res = cu.outil_generer({"prompt": "x"}, self.ctx(accord=False))
        self.assertIn("Refusé", res)
        self.assertEqual(SERVICE["soumis"], [], "refusé : rien n'est envoyé")
        res = cu.outil_generer({"prompt": "x"}, self.ctx(accord=False, essai=True))
        self.assertIn("Essai à blanc", res)
        self.assertEqual(SERVICE["soumis"], [])
        SERVICE["refus"] = True
        self.assertIn("refusé le travail", cu.outil_generer({"prompt": "x"}, self.ctx()))
        SERVICE.update(refus=False, histoire=0, erreur_historique=True)
        self.assertIn("out of memory", cu.outil_generer({"prompt": "x"}, self.ctx()))
        SERVICE.update(histoire=-10 ** 6, erreur_historique=False)
        ctx = self.ctx()
        fil = threading.Thread(target=lambda: ctx["stop"].set() if time.sleep(0.2) is None else None)
        fil.start()
        with self.assertRaises(_m.Arret):
            cu.outil_generer({"prompt": "x"}, ctx)
        fil.join()
        self.assertEqual(SERVICE["interrompu"], 1, "le bouton Arrêter interrompt aussi le travail dans ComfyUI")

    def test_workflow_personnalise_et_marques_inconnues(self):
        wf = {"1": {"class_type": "X", "inputs": {"texte": "{prompt} en {largeur}px", "n": "{pas}", "fixe": "{rien}"}}}
        v = {"prompt": "chat", "largeur": 512, "pas": 20}
        r = cu.remplir_workflow(wf, v)
        self.assertEqual(r["1"]["inputs"], {"texte": "chat en 512px", "n": 20, "fixe": "{rien}"}, "une marque entière garde son type, une marque dans une phrase est écrite")
        self.assertEqual(cu.marques_restantes(r), {"rien"})
        f = json.loads(json.dumps(addons.flux_livre(cu.IDENT)))
        f["workflows"]["video"] = wf
        addons.appliquer_flux(cu.IDENT, f)
        with self.assertRaises(_m.ErreurOutil) as e:
            cu.outil_generer({"prompt": "x", "type": "video"}, self.ctx())
        self.assertIn("{rien}", str(e.exception), "le workflow demande une valeur que Lutin ne sait pas donner : message clair, rien n'est envoyé")
        self.assertEqual(SERVICE["soumis"], [])
        addons.restaurer_flux(cu.IDENT)

    def attendre_fin_telechargement(self):
        for _ in range(300):
            if cu.TELECHARGEMENT["etat"] != "en cours":
                return cu.TELECHARGEMENT["etat"]
            time.sleep(0.05)
        self.fail("téléchargement jamais terminé")

    def test_telecharger_un_modele_dans_le_bon_dossier_et_refuser_le_reste(self):
        site = ThreadingHTTPServer(("127.0.0.1", 0), FauxSiteDeModeles)
        threading.Thread(target=site.serve_forever, daemon=True).start()
        self.addCleanup(site.shutdown)
        base = "http://127.0.0.1:%d" % site.server_address[1]
        vrai_sleep = cu.time.sleep
        cu.time.sleep = self.vrai_pause                                              # le site lent a besoin du vrai temps
        self.addCleanup(setattr, cu.time, "sleep", vrai_sleep)
        # les noms et les sites
        self.assertEqual(cu.nom_de_fichier("https://x.org/a/b/mon%20modele.safetensors"), "mon modele.safetensors")
        self.assertEqual(cu.nom_de_fichier("https://x.org/dl", 'attachment; filename="../../evil.safetensors"'), "evil.safetensors", "jamais un chemin")
        with self.assertRaises(addons.ErreurAddon):
            cu.nom_de_fichier("https://x.org/script.exe")
        for hote, permis in (("huggingface.co", True), ("cdn-lfs.hf.co", True), ("civitai.com", True), ("evilhuggingface.co", False), ("huggingface.co.evil.com", False), ("example.com", False)):
            self.assertEqual(cu.hote_telechargement_permis(hote), permis, hote)
        # rien sans dossier d'installation
        with self.assertRaises(addons.ErreurAddon):
            cu.demarrer_telechargement(base + "/modele.safetensors", "checkpoints")
        cu.action("utiliser_dossier", {"dossier": str(COMFY)})
        for url, genre in (("ftp://huggingface.co/x.safetensors", "checkpoints"), ("https://example.com/x.safetensors", "checkpoints"), (base + "/modele.safetensors", "../etc"), ("", "checkpoints")):
            with self.assertRaises(addons.ErreurAddon):
                cu.demarrer_telechargement(url, genre)
        # un vrai téléchargement
        cu.demarrer_telechargement(base + "/modele.safetensors", "loras")
        self.assertEqual(self.attendre_fin_telechargement(), "fini", cu.TELECHARGEMENT["erreur"])
        fichier = COMFY / "models" / "loras" / "modele.safetensors"
        self.assertEqual(fichier.stat().st_size, 3_000_000)
        self.assertFalse(list((COMFY / "models" / "loras").glob("*.part")), "pas de reste de téléchargement")
        self.assertEqual(cu.TELECHARGEMENT["fait"], 3_000_000)
        self.assertIn("modele.safetensors", cu.lister_modeles(forcer=True)["modeles"].get("loras", []) + [n for n in cu._scan_dossier(COMFY).get("loras", [])])
        # rien n'est écrasé
        cu.demarrer_telechargement(base + "/modele.safetensors", "loras")
        self.assertEqual(self.attendre_fin_telechargement(), "erreur")
        self.assertIn("existe déjà", cu.TELECHARGEMENT["erreur"])
        # les pièges
        for chemin, attendu in (("/page.safetensors", "page web"), ("/ailleurs.safetensors", "refusé"), ("/tronque.safetensors", "incomplet")):
            cu.demarrer_telechargement(base + chemin, "checkpoints")
            self.assertEqual(self.attendre_fin_telechargement(), "erreur", chemin)
            self.assertIn(attendu, cu.TELECHARGEMENT["erreur"], chemin)
        self.assertEqual([p.name for p in (COMFY / "models" / "checkpoints").iterdir() if p.name != "local.safetensors" and p.name != "notes.txt"], [], "aucun fichier laissé par un téléchargement raté")
        # annulation
        cu.demarrer_telechargement(base + "/lent.safetensors", "checkpoints")
        for _ in range(100):
            if cu.TELECHARGEMENT["fait"] > 0:
                break
            time.sleep(0.05)
        cu.action("annuler_telechargement", {})
        self.assertEqual(self.attendre_fin_telechargement(), "erreur")
        self.assertIn("annulé", cu.TELECHARGEMENT["erreur"])
        self.assertFalse(list((COMFY / "models" / "checkpoints").glob("lent*")), "l'annulation efface le fichier partiel")
        fichier.unlink()
        addons.enregistrer_reglages(cu.IDENT, {"dossier": ""})

    def test_les_outils_n_existent_que_si_l_addon_est_actif(self):
        from lutin import dialogue, revue
        base = dict(_m.reglages(), web=True)

        def noms(mode):
            return {t["function"]["name"] for t in dialogue.outils_du_mode(dict(base, mode=mode))}
        comfy = {"comfy_generer", "comfy_modeles"}
        self.assertFalse(comfy & noms("polyvalent"), "addon désactivé : le modèle ne voit pas ces outils")
        with self.assertRaises(_m.ErreurOutil):
            revue.appeler_outil("comfy_generer", {"prompt": "x"}, self.ctx())
        vrai = addons.actif
        addons.actif = lambda ident: True
        try:
            self.assertTrue(comfy <= noms("polyvalent"))
            self.assertEqual(comfy & noms("recherche"), {"comfy_modeles"}, "en lecture seule, le modèle peut voir les modèles mais pas générer")
            self.assertFalse(comfy & noms("discussion"))
            self.assertIn("Modèles installés", revue.appeler_outil("comfy_modeles", {}, self.ctx()))
            self.assertIn("lutin_00001_.png", revue.appeler_outil("comfy_generer", {"prompt": "un phare"}, self.ctx()))
        finally:
            addons.actif = vrai


if __name__ == "__main__":
    unittest.main()
