"""Retours d'essai sur la 0.32 : mise à jour de llama.cpp sous Windows (« Accès refusé »), Colibri géré depuis la carte « compatible OpenAI », message du premier lancement, mémoire vidéo/RAM réelles et programmes oubliés."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-correctifs-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import core as _m  # noqa: E402  (avant les autres : import circulaire sinon)
from lutin import diagnostic, engines, health  # noqa: E402
from lutin import llamacpp_engine as ml  # noqa: E402
from lutin import engine_replace, loaded_resources as rc  # noqa: E402


def dossier_avec(racine, fichiers):
    racine.mkdir(parents=True, exist_ok=True)
    for nom, contenu in fichiers.items():
        (racine / nom).write_text(contenu, encoding="utf-8")
    return racine


class RemplacerDossier(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-remplacer-"))
        self.neuf = dossier_avec(self.tmp / "bin.neuf", {"llama-server.exe": "v2"})
        self.cible = dossier_avec(self.tmp / "bin", {"llama-server.exe": "v1"})

    def test_cas_normal(self):
        ml.remplacer_dossier(self.neuf, self.cible, dormir=lambda s: self.fail("aucune attente quand tout va bien"))
        self.assertEqual((self.cible / "llama-server.exe").read_text(encoding="utf-8"), "v2")
        self.assertFalse(self.neuf.exists())

    def test_acces_refuse_passager_on_reessaie(self):
        vrai = os.replace
        essais = []

        def capricieux(a, b):
            essais.append(a)
            if len(essais) < 3:
                raise PermissionError(5, "Accès refusé")          # l'antivirus analyse les fichiers tout neufs
            return vrai(a, b)
        attentes = []
        with mock.patch.object(ml.os, "replace", capricieux):
            ml.remplacer_dossier(self.neuf, self.cible, dormir=attentes.append)
        self.assertEqual((self.cible / "llama-server.exe").read_text(encoding="utf-8"), "v2")
        self.assertEqual(len(essais), 3)
        self.assertEqual(attentes, [1, 2], "pauses croissantes entre les essais")

    def test_renommage_impossible_copie_en_dernier_recours(self):
        with mock.patch.object(ml.os, "replace", side_effect=PermissionError(5, "Accès refusé")):
            ml.remplacer_dossier(self.neuf, self.cible, dormir=lambda s: None)
        self.assertEqual((self.cible / "llama-server.exe").read_text(encoding="utf-8"), "v2")
        self.assertFalse(self.neuf.exists())

    def test_fichier_verrouille_arrete_les_processus_puis_dit_pourquoi(self):
        appels = []
        with mock.patch.object(engine_replace, "supprimer_arbre", lambda d: None), mock.patch.object(ml.shutil, "copytree", side_effect=PermissionError(5, "Accès refusé")):
            with self.assertRaises(engine_replace.ErreurRemplacement) as e:
                ml.remplacer_dossier(self.neuf, self.cible, dormir=lambda s: None, liberer=lambda: appels.append(1))
        self.assertIn("Ferme tout ce qui utilise llama.cpp", str(e.exception))
        self.assertGreaterEqual(len(appels), 1, "les programmes restés dans le dossier sont arrêtés")

    def test_pas_de_powershell_hors_windows(self):
        with mock.patch.object(engine_replace.os, "name", "posix"), mock.patch.object(engine_replace.subprocess, "run", side_effect=AssertionError("ne doit rien lancer")):
            self.assertEqual(ml.liberer_processus(self.tmp), 0)


class ModeleDuSetup(unittest.TestCase):
    """Le modèle que `coli setup` a préparé est retrouvé sans qu'on indique son dossier (lecture seule de son setup.json)."""

    def test_le_dossier_du_modele_est_lu_dans_le_setup_de_colibri(self):
        from lutin import colibri
        base = Path(tempfile.mkdtemp(prefix="lutin-setup-"))
        modele = base / "colibri-models" / "qwen36-35b"
        modele.mkdir(parents=True)
        with mock.patch.dict(os.environ, {"COLI_SETUP_HOME": str(base / "home")}):
            self.assertEqual(colibri.modele_du_setup(), "", "pas encore de setup")
            (base / "home").mkdir()
            (base / "home" / "setup.json").write_text(json.dumps({"model_dir": str(modele)}), encoding="utf-8")
            self.assertEqual(colibri.modele_du_setup(), str(modele))
            (base / "home" / "setup.json").write_text(json.dumps({"model_dir": str(base / "absent")}), encoding="utf-8")
            self.assertEqual(colibri.modele_du_setup(), "", "un dossier qui n'existe plus n'est pas proposé")
            (base / "home" / "setup.json").write_text("pas du json", encoding="utf-8")
            self.assertEqual(colibri.modele_du_setup(), "")


class Colibri(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-colibri-"))
        self.ancien = dict(engines.CONTEXTE)
        engines.CONTEXTE["donnees"] = lambda: self.tmp
        engines.CONTEXTE["hors_ligne"] = lambda: False
        self.mo = engines.MOTEURS["openai"]

    def tearDown(self):
        engines.CONTEXTE.clear()
        engines.CONTEXTE.update(self.ancien)

    def regler(self, **d):
        ml.regler_serveur("openai", d)

    def test_sans_choix_rien_n_est_installable_et_on_dit_comment(self):
        a = self.mo.actions()
        self.assertFalse(any(x["possible"] for x in a.values()))
        self.assertIn("Colibri", a["installer"]["raison"])

    def test_colibri_choisi_propose_installer_puis_le_reste(self):
        self.regler(serveur="colibri")
        a = self.mo.actions()
        self.assertTrue(a["installer"]["possible"])
        self.assertFalse(a["desinstaller"]["possible"] or a["demarrer"]["possible"] or a["arreter"]["possible"] or a["mettre_a_jour"]["possible"])
        self.assertEqual(self.mo.statut()["detail"], "Colibri n'est pas installé.")
        self.assertEqual(self.mo.adresse(), "http://127.0.0.1:8000/v1", "adresse locale imposée, jamais une autre")

    def test_installation_mise_a_jour_desinstallation(self):
        from lutin import colibri
        self.regler(serveur="colibri")
        vues = []

        def faux_installer(version=None, dossiers=None, dire=print, **kw):
            base = colibri.dossier_colibri(dossiers) / "v2.1.0"
            dossier_avec(base, {"coli": "#!/usr/bin/env python3"})
            (colibri.dossier_colibri(dossiers) / "actuelle.txt").write_text("2.1.0", encoding="utf-8")
            dire("✔ Somme SHA-256 vérifiée.")
            return "2.1.0", base
        with mock.patch.object(colibri, "installer", faux_installer):
            self.mo.faire("installer", lambda *a: vues.append(a[0]))
        self.assertTrue(any("Installé" in v for v in vues))
        s = self.mo.statut()
        self.assertTrue(s["installe"] and s["installe_par_lutin"])
        self.assertEqual(s["version"], "2.1.0")
        a = self.mo.actions()
        self.assertTrue(a["desinstaller"]["possible"] and a["mettre_a_jour"]["possible"] and a["reinstaller"]["possible"])
        self.assertFalse(a["installer"]["possible"])
        self.assertFalse(a["demarrer"]["possible"], "sans dossier de modèle, on ne démarre pas")
        self.assertIn("Prépare d'abord un modèle", a["demarrer"]["raison"])
        modele = _TEMP / "modele-colibri"
        modele.mkdir(exist_ok=True)
        self.regler(modele_colibri=str(modele), port_colibri=8123)
        self.assertTrue(self.mo.actions()["demarrer"]["possible"])
        lances = []
        with mock.patch.object(colibri, "demarrer", lambda m, port, **kw: lances.append((m, port))):
            self.mo.faire("demarrer", lambda *a: None)
        self.assertEqual(lances, [(str(modele), 8123)])
        self.mo.faire("desinstaller", lambda *a: None)
        self.assertIsNone(self.mo._colibri())
        self.assertTrue(self.mo.actions()["installer"]["possible"])

    def test_reglages_refuses(self):
        for d in ({"modele_colibri": "dossier/relatif"}, {"modele_colibri": str(_TEMP / "absent")}, {"port_colibri": 80}, {"port_colibri": "abc"}, {"serveur": "../x"}):
            with self.assertRaises(ml.ErreurMoteur, msg=str(d)):
                self.regler(**d)

    def test_hors_ligne_pas_de_telechargement(self):
        engines.CONTEXTE["hors_ligne"] = lambda: True
        self.regler(serveur="colibri")
        a = self.mo.actions()
        self.assertFalse(a["installer"]["possible"])
        self.assertIn("hors ligne", a["installer"]["raison"])

    def test_la_page_recoit_le_serveur_choisi_et_les_reglages_de_colibri(self):
        self.assertEqual(ml.vue_reglages("openai")["serveur"], "")
        self.regler(serveur="colibri")
        v = ml.vue_reglages("openai")
        self.assertEqual(v["serveur"], "colibri")
        self.assertEqual(v["colibri"]["port"], 8000)
        self.regler(serveur="")
        self.assertNotIn("colibri", ml.vue_reglages("openai"))


class ColibriRemplacement(unittest.TestCase):
    """Colibri passe par le même remplacement robuste que llama.cpp : « Accès refusé » passager sous Windows, on réessaie."""

    def test_l_installation_de_colibri_survit_a_un_acces_refuse_passager(self):
        from lutin import colibri
        tmp = Path(tempfile.mkdtemp(prefix="lutin-colibri-rempl-"))
        partiel, cible = dossier_avec(tmp / "v2.1.0.partiel", {"coli": "x"}), dossier_avec(tmp / "v2.1.0", {"coli": "ancien"})
        vrai, essais = os.replace, []

        def capricieux(a, b):
            essais.append(1)
            if len(essais) < 3:
                raise PermissionError(5, "Accès refusé")
            return vrai(a, b)
        with mock.patch.object(engine_replace.os, "replace", capricieux), mock.patch.object(engine_replace.time, "sleep", lambda s: None):
            engine_replace.remplacer_dossier(partiel, cible)
        self.assertEqual((cible / "coli").read_text(encoding="utf-8"), "x")
        self.assertTrue(hasattr(colibri, "remplacer_dossier"), "colibri utilise le remplacement commun")


class SeuilVideoPourTousLesMoteurs(unittest.TestCase):
    def test_ollama_et_llamacpp_repartissent_tout_seuls_pas_un_serveur_externe(self):
        for moteur, attendu in (("ollama", True), ("llamacpp", True), ("openai", False), (None, True)):
            self.assertEqual(health._repartit_seul({"moteur": moteur}), attendu, str(moteur))


class PremierLancement(unittest.TestCase):
    def test_un_autre_moteur_est_installe_on_le_propose_au_lieu_de_dire_qu_il_manque_un_moteur(self):
        r = diagnostic.premier_lancement("Serveur compatible OpenAI", False, "", {"moteur": "ollama", "nom": "Ollama", "raison": "x"}, None, [{"moteur": "ollama", "nom": "Ollama"}], "openai")
        self.assertFalse(r["pret"])
        self.assertIn("Ollama est déjà installé", r["raison"])
        self.assertNotIn("Aucun moteur n'est prêt", r["raison"])
        self.assertIsNone(r["recommande"], "rien à installer : l'un est déjà là")
        self.assertEqual(r["installes"], [{"moteur": "ollama", "nom": "Ollama"}])

    def test_rien_de_choisi_ni_d_installe(self):
        r = diagnostic.premier_lancement("Serveur compatible OpenAI", False, "", None, None, [], "openai")
        self.assertIn("Aucun moteur n'est choisi ni installé", r["raison"])
        self.assertNotIn("ne répond pas", r["raison"])

    def test_colibri_installe_mais_arrete_se_demarre_il_ne_faut_pas_dire_d_installer_ollama(self):
        r = diagnostic.premier_lancement("Serveur compatible OpenAI", False, "", None, None, [], "openai", {"nom": "Colibri", "installe": True})
        self.assertFalse(r["pret"])
        self.assertIn("Colibri est installé mais ne répond pas", r["raison"])
        self.assertNotIn("Ollama", r["raison"])
        self.assertEqual(r["gere"], {"nom": "Colibri", "installe": True})
        self.assertIsNone(r["recommande"])

    def test_serveur_gere_pas_installe_dit_de_l_installer_et_propose_l_autre_moteur_s_il_existe(self):
        r = diagnostic.premier_lancement("Serveur compatible OpenAI", False, "", None, None, [{"moteur": "ollama", "nom": "Ollama"}], "openai", {"nom": "LM Studio", "installe": False})
        self.assertIn("LM Studio n'est pas installé", r["raison"])
        self.assertIn("Ollama, déjà installé", r["raison"])

    def test_le_premier_lancement_de_la_page_reconnait_colibri_installe(self):
        import lutin.server as srv
        mo = engines.MOTEURS["openai"]
        ancien = dict(engines.CONTEXTE)
        engines.CONTEXTE["donnees"] = lambda: _TEMP / "donnees-pl"
        try:
            ml.regler_serveur("openai", {"serveur": "colibri"})
            with mock.patch.object(type(mo), "_colibri", lambda self_: ("2.1.0", _TEMP)), mock.patch.object(type(mo), "modele_colibri", lambda self_: ""):
                pl = srv.Gestionnaire._premier_lancement({"actif": False}, dict(_m.reglages(), moteur="openai"), None)
            self.assertEqual(pl["gere"], {"nom": "Colibri", "installe": True, "sans_modele": True})
            self.assertIn("aucun modèle", pl["raison"])
            with mock.patch.object(type(mo), "_colibri", lambda self_: ("2.1.0", _TEMP)), mock.patch.object(type(mo), "modele_colibri", lambda self_: str(_TEMP)):
                pl = srv.Gestionnaire._premier_lancement({"actif": False}, dict(_m.reglages(), moteur="openai"), None)
            self.assertEqual(pl["gere"], {"nom": "Colibri", "installe": True, "sans_modele": False})
            self.assertNotIn("Ollama", pl["raison"])
        finally:
            ml.regler_serveur("openai", {"serveur": ""})
            engines.CONTEXTE.clear()
            engines.CONTEXTE.update(ancien)

    def test_comportement_inchange_pour_ollama_absent(self):
        r = diagnostic.premier_lancement("Ollama", False, "Pas installé.", None, None, [], "ollama")
        self.assertIn("Aucun moteur n'est prêt", r["raison"])


class ProcessusMoteurs(unittest.TestCase):
    def test_arbre_du_routeur(self):
        proc = [{"pid": 10, "ppid": 1, "nom": "llama-server", "exe": "", "ram": 1, "vram": 0}, {"pid": 11, "ppid": 10, "nom": "llama-server", "exe": "", "ram": 1, "vram": 7 * 1024 ** 3},
                {"pid": 12, "ppid": 11, "nom": "llama-server", "exe": "", "ram": 1, "vram": 1}, {"pid": 99, "ppid": 1, "nom": "llama-server", "exe": "", "ram": 1, "vram": 5}]
        self.assertEqual(rc.descendants(proc, 10), {10, 11, 12})

    def test_instantane_windows_lu_depuis_le_json_de_powershell(self):
        texte = json.dumps([{"pid": 5, "ppid": 1, "nom": "llama-server.exe", "exe": "E:\\IA\\llama.cpp\\bin\\llama-server.exe", "ram": 100, "vram": 3000}, {"pid": 6, "ppid": 5, "nom": "ollama.exe", "exe": None, "ram": 1, "vram": None}, {"casse": 1}])
        r = rc.analyser_instantane(texte)
        self.assertEqual([x["pid"] for x in r], [5, 6])
        self.assertEqual(r[0]["nom"], "llama-server")
        self.assertIsNone(r[1]["vram"], "inconnu n'est pas zéro")
        self.assertEqual(rc.analyser_instantane(json.dumps({"pid": 7, "nom": "x.exe"}))[0]["pid"], 7, "PowerShell rend un objet seul sans liste")
        self.assertEqual(rc.analyser_instantane("pas du json"), [])

    def test_vram_du_routeur_est_celle_de_ses_fils_et_le_cache_du_fichier_n_est_pas_de_la_ram(self):
        class Proc:
            pid = 10

            def poll(self):
                return None
        go = 1024 ** 3
        instantane = [{"pid": 10, "ppid": 1, "nom": "llama-server", "exe": "", "ram": 1 * go, "vram": 0}, {"pid": 11, "ppid": 10, "nom": "llama-server", "exe": "", "ram": 18 * go, "vram": 20 * go}]
        journal = ("load_tensors: offloading 64 repeating layers to GPU\nload_tensors: offloaded 65/65 layers to GPU\nload_tensors:        CUDA0 model buffer size = 19000.00 MiB\n"
                   "load_tensors:   CPU_Mapped model buffer size =   400.00 MiB\nllama_kv_cache:      CUDA0 KV buffer size =  1000.00 MiB\n")
        ancien = dict(ml.SERVEUR)
        ml.SERVEUR.update(proc=Proc(), modele=ml.ROUTEUR, noms=("a",))
        try:
            with mock.patch.object(rc, "instantane_processus", lambda **kw: instantane), mock.patch.object(rc, "placement_llamacpp", lambda mo: (rc.analyser_journal_llamacpp(journal), "cuda")):
                c = rc.charges_llamacpp()[0]
        finally:
            ml.SERVEUR.update(ancien)
        self.assertEqual(c["vram"], 20 * go, "le routeur lui-même n'a rien : la carte est tenue par son fils")
        self.assertLess(c["ram"], 1 * go, "le modèle est sur la carte : seulement ce qui est réellement sur le processeur")
        self.assertIn("cache libérable", c["detail"])
        self.assertEqual(c["pids"], [10, 11])

    def test_journal_dernier_chargement_et_memoire_hote(self):
        j = ("load_tensors: offloading 10 repeating layers to GPU\nload_tensors: offloaded 11/11 layers to GPU\nCUDA0 model buffer size = 100.00 MiB\nCPU_Mapped model buffer size = 50.00 MiB\n"
             "load_tensors: offloading 30 repeating layers to GPU\nload_tensors: offloaded 31/31 layers to GPU\nCUDA0 model buffer size = 4000.00 MiB\nCUDA_Host model buffer size = 300.00 MiB\nCUDA0 KV buffer size = 500.00 MiB\nCPU compute buffer size = 20.00 MiB\n")
        p = rc.analyser_journal_llamacpp(j)
        self.assertEqual(p["couches"], 31)
        self.assertEqual(p["gpu"], 4000 * 1024 ** 2, "seul le dernier chargement compte")
        self.assertEqual(p["cpu"], 300 * 1024 ** 2, "la mémoire hôte est de la RAM")
        self.assertEqual(p["gpu_total"], 4500 * 1024 ** 2)
        self.assertEqual(p["cpu_total"], 320 * 1024 ** 2)

    def test_un_serveur_oublie_est_liste_et_arretable_seulement_s_il_vient_du_dossier_de_lutin(self):
        dossier = Path(tempfile.mkdtemp(prefix="lutin-llama-")).resolve()
        exe = dossier / "bin" / "llama-server.exe"
        exe.parent.mkdir()
        exe.write_text("x")
        instantane = [{"pid": 50, "ppid": 1, "nom": "llama-server", "exe": str(exe), "ram": 10, "vram": 7 * 1024 ** 3}, {"pid": 51, "ppid": 50, "nom": "llama-server", "exe": str(exe), "ram": 5, "vram": 1024},
                      {"pid": 60, "ppid": 1, "nom": "LM Studio", "exe": "C:/Autre/LM Studio.exe", "ram": 3, "vram": None}, {"pid": 70, "ppid": 1, "nom": "ollama", "exe": "", "ram": 3, "vram": 9}]
        with mock.patch.object(rc, "instantane_processus", lambda **kw: instantane), mock.patch.object(rc, "dossiers_lutin", lambda: [dossier]):
            c = rc.charges_orphelines(set())
            ids = {x["id"]: x for x in c}
            self.assertEqual(set(ids), {"processus:50", "processus:60"}, "les fils sont regroupés avec leur père ; Ollama est vu par son interface")
            self.assertEqual(ids["processus:50"]["vram"], 7 * 1024 ** 3 + 1024)
            self.assertTrue(ids["processus:50"]["dechargeable"])
            self.assertFalse(ids["processus:60"]["dechargeable"])
            self.assertIsNone(ids["processus:60"]["vram"], "inconnu n'est pas zéro")
            self.assertEqual(rc.charges_orphelines({50, 51}) and [x["id"] for x in rc.charges_orphelines({50, 51})], ["processus:60"], "ce que Lutin pilote n'est pas compté deux fois")
            arretes = []
            with mock.patch.object(rc, "arreter_processus", lambda pid, tous, **kw: arretes.append((pid, sorted(tous)))):
                self.assertIn("arrêté", rc.decharger("processus:50")["message"])
                self.assertEqual(arretes, [(50, [50, 51])])
                with self.assertRaises(ValueError):
                    rc.decharger("processus:60")          # pas à Lutin
                with self.assertRaises(ValueError):
                    rc.decharger("processus:12345")          # inconnu
                with self.assertRaises(ValueError):
                    rc.decharger("processus:abc")
        self.assertEqual(len(arretes), 1)


class SanteVideo(unittest.TestCase):
    MESURES = {"ram": {"total": 64 * 1024 ** 3, "libre": 40 * 1024 ** 3, "engagement_libre": 60 * 1024 ** 3},
               "vram": {"nom": "RTX 4090", "total": 24 * 1024 ** 3, "utilise": 7 * 1024 ** 3, "libre": 17 * 1024 ** 3}, "comfy": {}, "disques": {}, "donnees_octets": 0}

    def item(self, partiel):
        r = _m.reglages()
        return next(i for i in health.evaluer_sante(self.MESURES, r, int(19.5 * 1024 ** 3), None, partiel)["items"] if i["id"] == "vram")

    def test_ollama_modele_trop_gros_pour_la_place_libre_reste_bloquant_mais_explique(self):
        i = self.item(False)
        self.assertEqual(i["niveau"], "critique")
        self.assertIn("7.0 Go déjà pris", i["valeur"])
        self.assertIn("il manque environ 2.5 Go", i["conseil"])

    def test_llamacpp_repartit_tout_seul_ce_n_est_pas_un_blocage(self):
        i = self.item(True)
        self.assertEqual(i["niveau"], "attention")
        self.assertIn("partie sur le processeur", i["conseil"])

    def test_llamacpp_charge_sans_taille_connue_pas_de_zero_pour_cent(self):
        r = _m.reglages()
        i = next(i for i in health.evaluer_sante(self.MESURES, r, 0, {"taille": 0, "vram": 0}, True)["items"] if i["id"] == "vram")
        self.assertEqual(i["niveau"], "ok")
        self.assertNotIn("0 %", i["valeur"])


class DossierDesMoteurs(unittest.TestCase):
    """Un seul dossier pour tous les moteurs, choisi dans la page ; noms de dossiers en anglais (engines), l'ancien « moteurs » est repris."""

    def setUp(self):
        from lutin import docker_engines as md
        self.md = md
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-dossier-moteurs-"))
        self.ancien = dict(engines.CONTEXTE)
        engines.CONTEXTE.update(donnees=lambda: self.tmp, en_docker=lambda: False, hors_ligne=lambda: False)
        for k in ("LUTIN_ENGINES", "LUTIN_MOTEURS", "LUTIN_DOCKER"):
            patcher = mock.patch.dict(os.environ)
            patcher.start()
            self.addCleanup(patcher.stop)
            os.environ.pop(k, None)

    def tearDown(self):
        engines.CONTEXTE.clear()
        engines.CONTEXTE.update(self.ancien)

    def test_par_defaut_engines_en_anglais(self):
        self.assertEqual(self.md.base_moteurs(), self.tmp / "engines")

    def test_l_ancien_dossier_moteurs_est_renomme_sans_rien_perdre(self):
        (self.tmp / "moteurs" / "llamacpp").mkdir(parents=True)
        (self.tmp / "moteurs" / "llamacpp" / "version.txt").write_text("b1", encoding="utf-8")
        self.assertEqual(self.md.base_moteurs(), self.tmp / "engines")
        self.assertEqual((self.tmp / "engines" / "llamacpp" / "version.txt").read_text(encoding="utf-8"), "b1")
        self.assertFalse((self.tmp / "moteurs").exists())

    def test_renommage_impossible_l_ancien_reste_utilise(self):
        (self.tmp / "moteurs").mkdir()
        with mock.patch.object(Path, "rename", side_effect=PermissionError(5, "Accès refusé")):
            self.assertEqual(self.md.base_moteurs(), self.tmp / "moteurs")

    def test_choix_dans_la_page_et_retour_au_defaut(self):
        choisi = self.tmp / "ailleurs"
        ml.regler_dossier_moteurs(str(choisi))
        self.assertEqual(self.md.base_moteurs(), choisi)
        self.assertEqual(engines.MOTEURS["llamacpp"].dossier(), choisi / "llamacpp")
        v = ml.vue_dossier_moteurs()
        self.assertEqual((v["source"], v["personnalise"], v["actuel"]), ("reglage", True, str(choisi)))
        ml.regler_dossier_moteurs("")
        self.assertEqual(self.md.base_moteurs(), self.tmp / "engines")

    def test_refuse_un_chemin_relatif_et_tant_qu_un_moteur_y_est_installe(self):
        with self.assertRaises(ml.ErreurMoteur):
            ml.regler_dossier_moteurs("relatif/dossier")
        installe = engines.MOTEURS["llamacpp"]
        exe = installe.dossier_defaut() / "bin" / ("llama-server.exe" if os.name == "nt" else "llama-server")
        exe.parent.mkdir(parents=True)
        exe.write_text("x")
        with self.assertRaises(ml.ErreurMoteur) as e:
            ml.regler_dossier_moteurs(str(self.tmp / "autre"))
        self.assertIn("llama.cpp", str(e.exception))
        self.assertIn("désinstalle", str(e.exception))

    def test_docker_priorites_et_cause_quand_engines_n_est_pas_utilise(self):
        env = {"LUTIN_DOCKER": "1"}
        engines.CONTEXTE["en_docker"] = lambda: True
        d = self.md.detail_dossier_moteurs(env, monte=lambda p: True, ecriture=lambda p: False)
        self.assertEqual((d["source"], d["probleme"], d["dossier"]), ("donnees", "non_modifiable", self.tmp / "engines"))
        d = self.md.detail_dossier_moteurs(env, monte=lambda p: False)
        self.assertEqual((d["source"], d["probleme"]), ("donnees", "non_monte"))
        d = self.md.detail_dossier_moteurs(env, monte=lambda p: True, ecriture=lambda p: True)
        self.assertEqual((d["source"], d["dossier"]), ("montage", Path("/engines")))
        ml.regler_dossier_moteurs(str(self.tmp / "choisi"))
        d = self.md.detail_dossier_moteurs(env, monte=lambda p: True, ecriture=lambda p: True)
        self.assertEqual((d["source"], d["dossier"]), ("reglage", self.tmp / "choisi"), "le choix de la page passe avant /engines")
        d = self.md.detail_dossier_moteurs(dict(env, LUTIN_ENGINES="/vol"), monte=lambda p: True)
        self.assertEqual((d["source"], d["dossier"]), ("env", Path("/vol")), "la variable passe avant tout")
        d = self.md.detail_dossier_moteurs(dict(env, LUTIN_MOTEURS="/ancien"), monte=lambda p: True)
        self.assertEqual(d["dossier"], Path("/ancien"), "l'ancienne variable française est encore lue")

    def test_docker_le_dossier_est_choisissable_dans_la_page_sauf_si_impose_par_la_variable(self):
        engines.CONTEXTE["en_docker"] = lambda: True
        with mock.patch.dict(os.environ, {"LUTIN_DOCKER": "1", "LUTIN_ENGINES": "/vol"}):
            self.assertFalse(ml.vue_dossier_moteurs()["modifiable"])
            with self.assertRaises(ml.ErreurMoteur):
                ml.regler_dossier_moteurs(str(self.tmp / "x"))


if __name__ == "__main__":
    unittest.main()
