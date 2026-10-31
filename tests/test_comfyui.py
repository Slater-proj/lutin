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
SERVICE = {"panne": False, "soumis": [], "histoire": 0, "refus": False, "interrompu": 0, "erreur_historique": False, "mode": "checkpoints", "sans_clip": False}
DIFFUSION = {"UNETLoader": ("unet_name", ["flux1-dev-fp8.safetensors", "qwen_image_fp8_e4m3fn.safetensors", "z_image_turbo_bf16.safetensors", "mystere_xl.safetensors"]),
             "CLIPLoader": ("clip_name", ["t5xxl_fp16.safetensors", "clip_l.safetensors", "qwen_2.5_vl_7b_fp8_scaled.safetensors", "qwen_3_4b.safetensors"]),
             "VAELoader": ("vae_name", ["ae.safetensors", "qwen_image_vae.safetensors"])}


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
        if SERVICE["mode"] == "diffusion":                                          # une installation sans checkpoint : seulement des modèles de diffusion (Flux, Qwen-Image, Z-Image)
            for noeud, (champ, noms) in DIFFUSION.items():
                if self.path.startswith("/object_info/" + noeud):
                    if SERVICE["sans_clip"] and noeud == "CLIPLoader":
                        return self._rep(200, {noeud: {"input": {"required": {champ: [[], {}]}}}})
                    if SERVICE.get("combo"):                                                # le nouveau format de ComfyUI : ["COMBO", {"options": [...]}]
                        return self._rep(200, {noeud: {"input": {"required": {champ: ["COMBO", {"multiselect": False, "options": noms}]}}}})
                    return self._rep(200, {noeud: {"input": {"required": {champ: [noms, {}]}}}})
            if self.path.startswith("/object_info/CheckpointLoaderSimple"):
                return self._rep(200, {"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [[], {}]}}}})
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
                return self._rep(200, {"abc": {"status": {"status_str": "error", "messages": [["execution_error", {"node_id": "3", "node_type": "KSampler", "exception_type": "torch.OutOfMemoryError", "exception_message": "out of memory"}]]}, "outputs": {}}})
            return self._rep(200, {"abc": {"status": {"status_str": "success"}, "outputs": {"9": {"images": [{"filename": "lutin_00001_.png", "subfolder": "", "type": "output"}]}}}})
        return self._rep(404, {})

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8") or "{}")
        if self.path.startswith("/interrupt"):
            SERVICE["interrompu"] += 1
            return self._rep(200, {})
        if self.path.startswith("/prompt"):
            if SERVICE["refus"]:
                return self._rep(400, {"error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation", "details": ""}, "node_errors": {"4": {"class_type": "CheckpointLoaderSimple", "errors": [{"type": "value_not_in_list", "message": "Value not in list", "details": "ckpt_name: 'x.safetensors' not in ['sdxl.safetensors']"}]}}})
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
        (_TEMP / "python_embeded").mkdir()
        (_TEMP / "python_embeded" / "python.exe").write_bytes(b"x")                 # la disposition de la version portable : ComfyUI/ et python_embeded/ côte à côte

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()

    def setUp(self):
        SERVICE.update(panne=False, soumis=[], histoire=0, refus=False, interrompu=0, erreur_historique=False, mode="checkpoints", sans_clip=False)
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
        addons.enregistrer_reglages(cu.IDENT, {"dossier": str(COMFY)})
        v = addons.verifier(cu.IDENT)
        self.assertTrue(v["ok"], v)
        self.assertEqual([e["appel"] for e in v["etapes"]], ["dossier", "lancement"])
        self.assertIn(str(COMFY), v["etapes"][0]["message"])
        d = cu.detecter()
        self.assertEqual((d["tourne"], d["version"], d["gpu"]), (True, "0.3.9", "GPU de test"))
        self.assertEqual(Path(d["dossier"]), COMFY, "le chemin de main.py est annoncé par ComfyUI : le dossier est prérempli")
        SERVICE["panne"] = True
        d = cu.detecter()
        self.assertFalse(d["tourne"])
        self.assertTrue(addons.verifier(cu.IDENT)["ok"], "ComfyUI éteint : ce n'est pas un problème, Lutin le lancera")
        addons.enregistrer_reglages(cu.IDENT, {"dossier": str(_TEMP / "projet")})
        v = addons.verifier(cu.IDENT)
        self.assertFalse(v["ok"], "un mauvais dossier est refusé avec une raison claire")
        self.assertIn("main.py", v["etapes"][0]["message"])

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
            cu.action("utiliser_dossier", {"dossier": str(_TEMP / "projet")})
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
        cu.outil_generer({"prompt": "x", "modele": "SDXL"}, self.ctx())
        self.assertEqual(SERVICE["soumis"][1]["prompt"]["4"]["inputs"]["ckpt_name"], "sdxl.safetensors", "ce que le modèle demande l'emporte (à la casse près)")
        with self.assertRaises(_m.ErreurOutil) as e:
            cu.outil_generer({"prompt": "x", "modele": "perso.safetensors"}, self.ctx())
        self.assertIn("n'est pas installé", str(e.exception))
        self.assertIn("sdxl.safetensors", str(e.exception), "le message dit quels modèles existent")
        for faux in ({"prompt": ""}, {"prompt": "x", "type": "hologramme"}, {"prompt": "x", "largeur": "beaucoup"}, {"prompt": "x", "type": "video"}):
            with self.assertRaises(_m.ErreurOutil):
                cu.outil_generer(faux, self.ctx())

    def test_l_image_creee_est_attachee_au_resultat_pour_etre_affichee_dans_la_conversation(self):
        from lutin import images
        sortie = COMFY / "output"
        sortie.mkdir(exist_ok=True)
        (sortie / "lutin_00001_.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"pixels")
        addons.enregistrer_reglages(cu.IDENT, {"dossier": str(COMFY)})
        ctx = self.ctx()
        res = cu.outil_generer({"prompt": "un phare"}, ctx)
        self.assertEqual(len(ctx.get("medias", [])), 1, res)
        octets, mime = images.lire(ctx["medias"][0])
        self.assertEqual((mime, octets[8:]), ("image/png", b"pixels"))
        self.assertIn("affichée", res)
        # un chemin qui sort du dossier de sortie n'est jamais copié
        self.assertEqual(cu._afficher(["../main.py", "../../secret.png"], self.ctx()), [])

    def test_supprimer_une_image_creee_efface_le_fichier_et_la_copie_mais_jamais_hors_de_la_sortie(self):
        from lutin import images, revue
        sortie = COMFY / "output"
        sortie.mkdir(exist_ok=True)
        (sortie / "a_supprimer.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"un")
        (COMFY / "main_intact.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"deux")
        addons.enregistrer_reglages(cu.IDENT, {"dossier": str(COMFY)})
        ctx = self.ctx()
        cu._afficher(["a_supprimer.png"], ctx)
        ident_image = ctx["medias"][0]
        self.assertEqual(ctx["medias_fichiers"][ident_image], str((sortie / "a_supprimer.png").resolve()))
        autre = images.enregistrer(b"\x89PNG\r\n\x1a\n" + b"deux")
        c = _m.conv_nouvelle()
        c["messages"] = [{"role": "tool", "tool_name": "comfy_generer", "content": "ok", "medias": [ident_image, autre],
                          "medias_fichiers": {ident_image: str(sortie / "a_supprimer.png"), autre: str(COMFY / "main_intact.png")}}]
        _m.conv_ecrire(c)
        self.assertTrue(revue.supprimer_media(c["id"], ident_image)["fichier_supprime"])
        self.assertFalse((sortie / "a_supprimer.png").exists())
        self.assertEqual(_m.conv_lire(c["id"])["messages"][0]["medias"], [autre])
        with self.assertRaises(ValueError):
            images.chemin(ident_image)
        self.assertFalse(revue.supprimer_media(c["id"], autre)["fichier_supprime"], "un fichier hors du dossier de sortie n'est jamais effacé")
        self.assertTrue((COMFY / "main_intact.png").exists())
        self.assertNotIn("medias", _m.conv_lire(c["id"])["messages"][0])
        with self.assertRaises(ValueError):
            revue.supprimer_media(c["id"], autre)

    def test_refus_essai_a_blanc_erreurs_et_arret(self):
        res = cu.outil_generer({"prompt": "x"}, self.ctx(accord=False))
        self.assertIn("Refusé", res)
        self.assertEqual(SERVICE["soumis"], [], "refusé : rien n'est envoyé")
        res = cu.outil_generer({"prompt": "x"}, self.ctx(accord=False, essai=True))
        self.assertIn("Essai à blanc", res)
        self.assertEqual(SERVICE["soumis"], [])
        SERVICE["refus"] = True
        res = cu.outil_generer({"prompt": "x"}, self.ctx())
        self.assertIn("refusé le travail", res)
        self.assertIn("Nœud 4 (CheckpointLoaderSimple)", res, "le nœud fautif est nommé")
        self.assertIn("ckpt_name: 'x.safetensors' not in ['sdxl.safetensors']", res, "avec le détail que ComfyUI donne")
        SERVICE.update(refus=False, histoire=0, erreur_historique=True)
        res = cu.outil_generer({"prompt": "x"}, self.ctx())
        self.assertIn("out of memory", res)
        self.assertIn("Nœud 3 (KSampler)", res)
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

    def test_diagnostic_du_dossier_et_choix_du_dossier_parent(self):
        self.assertEqual(cu.diagnostic_dossier(str(COMFY)), (True, ""))
        self.assertIn("non défini", cu.diagnostic_dossier("")[1])
        self.assertIn("n'existe pas", cu.diagnostic_dossier(str(_TEMP / "absent"))[1])
        self.assertIn("main.py", cu.diagnostic_dossier(str(_TEMP / "projet"))[1], "pas de main.py : on dit quoi chercher")
        (_TEMP / "sans-models").mkdir(exist_ok=True)
        (_TEMP / "sans-models" / "main.py").write_text("#", encoding="utf-8")
        self.assertIn("models", cu.diagnostic_dossier(str(_TEMP / "sans-models"))[1])
        self.assertEqual(Path(cu.normaliser_dossier(str(_TEMP))), COMFY, "le dossier parent de la version portable mène à ComfyUI/")
        self.assertEqual(Path(cu.normaliser_dossier(str(COMFY))), COMFY)
        r = cu.action("utiliser_dossier", {"dossier": str(_TEMP)})
        self.assertEqual((r["valide"], Path(r["dossier"]), r["lancement"]), (True, COMFY, True))
        self.assertEqual(Path(addons.reglages(cu.IDENT)["dossier"]), COMFY, "retenu")
        # détecter : trouvé tout seul → retenu ; introuvable → dit
        addons.enregistrer_reglages(cu.IDENT, {"dossier": ""})
        vrai = cu.trouver_dossier
        cu.trouver_dossier = lambda *a, **k: str(COMFY)
        try:
            r = cu.action("detecter", {})
            self.assertEqual((Path(addons.reglages(cu.IDENT)["dossier"]), r["introuvable"], r["valide"]), (COMFY, False, True))
            addons.enregistrer_reglages(cu.IDENT, {"dossier": ""})
            cu.trouver_dossier = lambda *a, **k: ""
            DETECTION_AVANT = dict(cu.DETECTION)
            r = cu.action("detecter", {})
            self.assertTrue(r["introuvable"])
            self.assertFalse(r["valide"])
            cu.DETECTION.update(DETECTION_AVANT)
        finally:
            cu.trouver_dossier = vrai

    def test_lutin_lance_comfyui_lui_meme_le_ferme_et_ne_touche_pas_a_celui_de_l_utilisateur(self):
        addons.enregistrer_reglages(cu.IDENT, {"dossier": str(COMFY)})
        lancements, arrets, ordre = [], [], []

        class Faux:
            def __init__(self, commande, **kw):
                lancements.append((commande, kw.get("cwd")))
                ordre.append("lancement")
                SERVICE["panne"] = False                                           # « ComfyUI démarre » : il répond maintenant
                self.fini = False

            def poll(self):
                return 1 if self.fini else None

            def terminate(self):
                arrets.append(1)
                self.fini = True

            def wait(self, delai=None):
                return 0

            def kill(self):
                self.terminate()
        vrai_popen = cu.subprocess.Popen
        cu.subprocess.Popen = Faux
        _m.liberer_vram = lambda *a, **k: ordre.append("memoire")
        self.addCleanup(setattr, cu.subprocess, "Popen", vrai_popen)
        # éteint : Lutin le lance (après avoir rendu la mémoire au modèle de langage), génère, puis le referme
        SERVICE["panne"] = True
        res = cu.outil_generer({"prompt": "un phare"}, self.ctx())
        self.assertIn("lutin_00001_.png", res)
        commande, cwd = lancements[0]
        self.assertTrue(commande[0].endswith("python.exe") and "main.py" in commande and "--disable-auto-launch" in commande and "--windows-standalone-build" in commande, commande)
        self.assertEqual((commande[commande.index("--port") + 1], Path(cwd)), (str(self.port), COMFY))
        self.assertEqual(ordre[:2], ["memoire", "lancement"], "la mémoire est rendue AVANT de lancer ComfyUI")
        self.assertEqual(len(arrets), 1, "ComfyUI lancé par Lutin est refermé après l'image")
        self.assertIsNone(cu.PROCESSUS["popen"])
        # réglage « ne pas refermer »
        addons.enregistrer_reglages(cu.IDENT, {"fermer_apres": "non"})
        SERVICE.update(panne=True, histoire=0)
        cu.outil_generer({"prompt": "x"}, self.ctx())
        self.assertEqual((len(lancements), len(arrets)), (2, 1), "lancé, mais laissé ouvert")
        cu.arreter_comfyui()
        addons.enregistrer_reglages(cu.IDENT, {"fermer_apres": "oui"})
        # déjà ouvert par l'utilisateur : ni lancé, ni refermé
        SERVICE.update(panne=False, histoire=0)
        cu.outil_generer({"prompt": "x"}, self.ctx())
        self.assertEqual((len(lancements), len(arrets)), (2, 2), "le ComfyUI de l'utilisateur n'est jamais fermé par Lutin")

    def test_lancement_impossible_ou_trop_long_donne_un_message_clair(self):
        addons.enregistrer_reglages(cu.IDENT, {"dossier": str(COMFY)})
        vrai_popen, vrai_delai = cu.subprocess.Popen, cu.DELAI_DEMARRAGE
        self.addCleanup(setattr, cu.subprocess, "Popen", vrai_popen)
        self.addCleanup(setattr, cu, "DELAI_DEMARRAGE", vrai_delai)
        SERVICE["panne"] = True

        def impossible(*a, **k):
            raise OSError("introuvable")
        cu.subprocess.Popen = impossible
        with self.assertRaises(_m.ErreurOutil) as e:
            cu.outil_generer({"prompt": "x"}, self.ctx())
        self.assertIn("Impossible de lancer", str(e.exception))

        class Mort:
            def __init__(self, *a, **k):
                pass

            def poll(self):
                return 1
        cu.subprocess.Popen = Mort
        with self.assertRaises(_m.ErreurOutil) as e:
            cu.outil_generer({"prompt": "x"}, self.ctx())
        self.assertIn("s'est arrêté au démarrage", str(e.exception))

        arrets = []

        class Muet:
            def __init__(self, *a, **k):
                pass

            def poll(self):
                return None

            def terminate(self):
                arrets.append(1)

            def wait(self, d=None):
                return 0
        cu.subprocess.Popen = Muet
        cu.DELAI_DEMARRAGE = 0.3
        with self.assertRaises(_m.ErreurOutil) as e:
            cu.outil_generer({"prompt": "x"}, self.ctx())
        self.assertIn("n'a pas répondu", str(e.exception))
        self.assertEqual(arrets, [1], "un ComfyUI qui ne répond pas est refermé")
        # pas de dossier, pas de Python : on le dit
        addons.enregistrer_reglages(cu.IDENT, {"dossier": ""})
        vrai_trouver = cu.trouver_dossier
        cu.trouver_dossier = lambda *a, **k: ""
        self.addCleanup(setattr, cu, "trouver_dossier", vrai_trouver)
        with self.assertRaises(_m.ErreurOutil) as e:
            cu.outil_generer({"prompt": "x"}, self.ctx())
        self.assertIn("ne trouve pas ComfyUI", str(e.exception))

    def test_modeles_de_diffusion_sans_checkpoint_flux_qwen_et_zimage(self):
        """Une installation sans checkpoint (ses modèles sont dans diffusion_models) : le nom du modèle décide du workflow, et l'encodeur de texte et le VAE sont choisis parmi ceux qui sont installés."""
        SERVICE["mode"] = "diffusion"
        cu.CACHE["modeles"] = (0, None)
        self.assertIn("flux1-dev-fp8.safetensors → image_flux", cu.texte_modeles(), "le modèle voit à quelle famille appartient chaque fichier")
        # Flux : UNETLoader + deux encodeurs de texte + VAE, pas de CheckpointLoader
        cu.outil_generer({"prompt": "un phare", "modele": "flux1-dev"}, self.ctx())
        wf = SERVICE["soumis"][-1]["prompt"]
        types = {n["class_type"] for n in wf.values()}
        self.assertTrue({"UNETLoader", "DualCLIPLoader", "VAELoader", "FluxGuidance", "KSampler"} <= types)
        self.assertNotIn("CheckpointLoaderSimple", types)
        self.assertEqual((wf["10"]["inputs"]["unet_name"], wf["11"]["inputs"]["clip_name1"], wf["11"]["inputs"]["clip_name2"], wf["12"]["inputs"]["vae_name"]),
                         ("flux1-dev-fp8.safetensors", "t5xxl_fp16.safetensors", "clip_l.safetensors", "ae.safetensors"))
        self.assertEqual((wf["3"]["inputs"]["steps"], wf["3"]["inputs"]["cfg"], wf["13"]["inputs"]["guidance"]), (20, 1.0, 3.5), "les réglages propres à Flux")
        # Qwen-Image
        SERVICE["histoire"] = 0
        cu.outil_generer({"prompt": "x", "modele": "qwen_image"}, self.ctx())
        wf = SERVICE["soumis"][-1]["prompt"]
        self.assertEqual((wf["11"]["inputs"]["type"], wf["11"]["inputs"]["clip_name"], wf["12"]["inputs"]["vae_name"], wf["14"]["inputs"]["shift"]),
                         ("qwen_image", "qwen_2.5_vl_7b_fp8_scaled.safetensors", "qwen_image_vae.safetensors", 3.1))
        self.assertEqual(wf["5"]["inputs"]["width"], 1328)
        # Z-Image
        SERVICE["histoire"] = 0
        cu.outil_generer({"prompt": "x", "modele": "z_image"}, self.ctx())
        wf = SERVICE["soumis"][-1]["prompt"]
        self.assertEqual((wf["11"]["inputs"]["type"], wf["11"]["inputs"]["clip_name"], wf["3"]["inputs"]["steps"]), ("lumina2", "qwen_3_4b.safetensors", 9))
        # sans modèle demandé : le premier modèle de diffusion reconnu
        SERVICE["histoire"] = 0
        cu.outil_generer({"prompt": "x"}, self.ctx())
        self.assertEqual(SERVICE["soumis"][-1]["prompt"]["10"]["inputs"]["unet_name"], "flux1-dev-fp8.safetensors")
        # famille inconnue : message clair, rien n'est envoyé
        avant = len(SERVICE["soumis"])
        with self.assertRaises(_m.ErreurOutil) as e:
            cu.outil_generer({"prompt": "x", "modele": "mystere_xl"}, self.ctx())
        self.assertIn("famille", str(e.exception))
        # un fichier manque (aucun encodeur de texte installé) : on dit lequel et où
        SERVICE["sans_clip"] = True
        cu.CACHE["modeles"] = (0, None)
        with self.assertRaises(_m.ErreurOutil) as e:
            cu.outil_generer({"prompt": "x", "modele": "flux1-dev"}, self.ctx())
        self.assertIn("encodeur de texte", str(e.exception))
        self.assertIn("text_encoders", str(e.exception))
        self.assertEqual(len(SERVICE["soumis"]), avant, "rien n'est envoyé à ComfyUI quand il manque un fichier")

    def test_nouveau_format_des_listes_de_comfyui(self):
        SERVICE["mode"], SERVICE["combo"] = "diffusion", True
        cu.CACHE["modeles"] = (0, None)
        try:
            self.assertIn("flux1-dev-fp8.safetensors", cu.lister_modeles(forcer=True)["modeles"]["diffusion_models"])
            cu.outil_generer({"prompt": "x", "modele": "flux1-dev"}, self.ctx())
            self.assertEqual(SERVICE["soumis"][-1]["prompt"]["11"]["inputs"]["clip_name1"], "t5xxl_fp16.safetensors")
        finally:
            SERVICE["combo"] = False

    def test_aucun_modele_d_image_installe(self):
        SERVICE["mode"] = "diffusion"
        for cle in DIFFUSION:
            DIFFUSION[cle] = (DIFFUSION[cle][0], [])
        cu.CACHE["modeles"] = (0, None)
        try:
            with self.assertRaises(_m.ErreurOutil) as e:
                cu.outil_generer({"prompt": "x"}, self.ctx())
            self.assertIn("aucun modèle d'image", str(e.exception))
        finally:
            DIFFUSION["UNETLoader"] = ("unet_name", ["flux1-dev-fp8.safetensors", "qwen_image_fp8_e4m3fn.safetensors", "z_image_turbo_bf16.safetensors", "mystere_xl.safetensors"])
            DIFFUSION["CLIPLoader"] = ("clip_name", ["t5xxl_fp16.safetensors", "clip_l.safetensors", "qwen_2.5_vl_7b_fp8_scaled.safetensors", "qwen_3_4b.safetensors"])
            DIFFUSION["VAELoader"] = ("vae_name", ["ae.safetensors", "qwen_image_vae.safetensors"])

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
