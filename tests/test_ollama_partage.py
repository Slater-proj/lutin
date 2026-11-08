"""Les modèles d'Ollama lus tels quels par llama.cpp : mêmes noms, mêmes octets, aucune copie, aucune suppression."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import moteur as _m  # noqa: E402,F401  (avant le dialogue : import circulaire sinon)
from lutin import dialogue  # noqa: E402  (enregistre les moteurs, et leur contexte : les tests le remplacent ensuite)
from lutin import moteur_llamacpp as ml  # noqa: E402
from lutin import moteurs, ollama_partage  # noqa: E402


def empreinte(c):
    return c * 64


def ranger(dossier, hote, chemin, couches):
    """Un modèle dans un dossier « models » d'Ollama : le manifeste, et un fichier pour chaque morceau déclaré présent."""
    manif = Path(dossier) / "manifests" / hote / chemin
    manif.parent.mkdir(parents=True, exist_ok=True)
    liste = []
    for type_, c, present in couches:
        liste.append({"mediaType": "application/vnd.ollama.image." + type_, "digest": "sha256:" + empreinte(c), "size": 5})
        if present:
            (Path(dossier) / "blobs").mkdir(parents=True, exist_ok=True)
            (Path(dossier) / "blobs" / ("sha256-" + empreinte(c))).write_bytes(b"GGUF-" + c.encode())
    manif.write_text(json.dumps({"layers": liste}), encoding="utf-8")


class Lecture(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="lutin-partage-"))
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_les_noms_sont_ceux_d_ollama(self):
        ranger(self.d, "registry.ollama.ai", "library/qwen3/8b", [("model", "a", True), ("template", "b", True)])
        ranger(self.d, "registry.ollama.ai", "huihui_ai/qwen3-abliterated/4b", [("model", "c", True)])
        lus = ollama_partage.lire(self.d)
        self.assertEqual(sorted(lus), ["huihui_ai/qwen3-abliterated:4b", "qwen3:8b"], "le modèle « sans filtre » aussi")
        self.assertEqual(lus["qwen3:8b"]["fichier"].read_bytes(), b"GGUF-a", "le morceau « modèle », pas le gabarit")
        self.assertEqual(lus["qwen3:8b"]["taille"], 6)

    def test_ce_qui_n_est_pas_utilisable_est_ignore(self):
        ranger(self.d, "registry.ollama.ai", "library/sans-fichier/1b", [("model", "d", False)])          # le morceau manque
        ranger(self.d, "exemple.org", "library/autre/1b", [("model", "e", True)])                           # hébergé ailleurs que sur le registre officiel
        ranger(self.d, "registry.ollama.ai", "library/gabarit-seul/1b", [("template", "f", True)])          # pas de morceau « modèle »
        casse = Path(self.d) / "manifests" / "registry.ollama.ai" / "library" / "casse" / "1b"
        casse.parent.mkdir(parents=True)
        casse.write_text("{pas du json", encoding="utf-8")
        self.assertEqual(ollama_partage.lire(self.d), {})
        self.assertEqual(ollama_partage.lire(self.d / "inexistant"), {})
        self.assertEqual(ollama_partage.lire(None), {})

    def test_empreinte_piegee_refusee(self):
        manif = Path(self.d) / "manifests" / "registry.ollama.ai" / "library" / "piege" / "1b"
        manif.parent.mkdir(parents=True)
        manif.write_text(json.dumps({"layers": [{"mediaType": ollama_partage.TYPE_MODELE, "digest": "sha256:../../secret", "size": 1}]}), encoding="utf-8")
        self.assertEqual(ollama_partage.lire(self.d), {}, "un chemin glissé dans l'empreinte ne sort jamais du dossier des morceaux")

    def test_projecteur_d_un_modele_qui_voit(self):
        ranger(self.d, "registry.ollama.ai", "library/gemma3/4b", [("model", "1", True), ("projector", "2", True)])
        lu = ollama_partage.lire(self.d)["gemma3:4b"]
        self.assertEqual(lu["projecteur"].read_bytes(), b"GGUF-2")


class DansLlamaCpp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-llamacpp-partage-"))
        self.ollama = self.tmp / "ollama-models"
        ranger(self.ollama, "registry.ollama.ai", "library/qwen3/8b", [("model", "a", True)])
        self.ancien = dict(moteurs.CONTEXTE)
        moteurs.CONTEXTE.update(donnees=lambda: self.tmp, en_docker=lambda: False, hors_ligne=lambda: False, profil=lambda: None, profil_attendu=None, dossier_ollama=lambda: self.ollama)
        ml.CACHE_PARTAGE.clear()
        self.m = ml.MoteurLlamaCpp()
        self.addCleanup(self.fin)

    def fin(self):
        moteurs.CONTEXTE.update(self.ancien)
        ml.CACHE_PARTAGE.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_la_liste_contient_ceux_d_ollama_sans_copie(self):
        (self.m.dossier_modeles()).mkdir(parents=True)
        (self.m.dossier_modeles() / "perso.gguf").write_bytes(b"x")
        r = self.m.modeles()
        self.assertEqual(sorted(r["installes"]), ["perso", "qwen3:8b"])
        self.assertEqual(r["partages"], ["qwen3:8b"])
        self.assertEqual(self.m._fichier_modele("qwen3:8b").read_bytes(), b"GGUF-a", "le fichier d'Ollama lui-même")
        self.assertEqual(self.m._fichier_modele("perso").name, "perso.gguf")
        self.assertFalse(list(self.m.dossier_modeles().glob("*qwen3*")), "aucune copie")

    def test_llama_cpp_ne_supprime_jamais_un_modele_d_ollama(self):
        with self.assertRaises(ml.ErreurMoteur) as e:
            self.m.supprimer_modele("qwen3:8b")
        self.assertIn("appartient à Ollama", str(e.exception))
        self.assertTrue((self.ollama / "blobs" / ("sha256-" + empreinte("a"))).is_file())

    def test_sous_docker_ou_partage_coupe_ou_serveur_externe_rien_n_est_partage(self):
        moteurs.CONTEXTE["en_docker"] = lambda: True
        ml.CACHE_PARTAGE.clear()
        self.assertEqual(self.m.partages(), {})
        moteurs.CONTEXTE["en_docker"] = lambda: False
        ml.CACHE_PARTAGE.clear()
        ml.regler("llamacpp", partager_ollama=False)
        self.assertEqual(self.m.partages(), {}, "coupé par l'utilisateur")

    def test_le_projecteur_est_donne_au_serveur(self):
        ranger(self.ollama, "registry.ollama.ai", "library/gemma3/4b", [("model", "1", True), ("projector", "2", True)])
        ml.CACHE_PARTAGE.clear()
        lances = []
        exe = self.m.dossier() / "bin" / ("llama-server.exe" if __import__("os").name == "nt" else "llama-server")
        exe.parent.mkdir(parents=True)
        exe.write_text("x")
        import subprocess

        class Faux:
            def poll(self):
                return None

            def terminate(self):
                pass

            def wait(self, *a, **k):
                return 0

            def kill(self):
                pass
        vrai = subprocess.Popen
        subprocess.Popen = lambda cmd, **kw: lances.append(cmd) or Faux()
        self.addCleanup(setattr, subprocess, "Popen", vrai)
        self.m._pret = lambda: True
        vrai_aide = ml.aide_serveur
        ml.aide_serveur = lambda exe: ""          # pas de vrai llama-server ici : aucune option adaptée à la machine
        self.addCleanup(setattr, ml, "aide_serveur", vrai_aide)
        self.m.demarrer("gemma3:4b")
        self.assertIn("--mmproj", lances[0])
        self.assertTrue(lances[0][lances[0].index("--mmproj") + 1].endswith("sha256-" + empreinte("2")))
        self.assertEqual(lances[0][lances[0].index("-m") + 1].split("sha256-")[-1], empreinte("1"))


class DossiersCommuns(unittest.TestCase):
    """Les mêmes lignes de dossiers sur la carte de chaque moteur : installation et modèles."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-dossiers-"))
        self.ancien = dict(moteurs.CONTEXTE)
        moteurs.CONTEXTE.update(donnees=lambda: self.tmp, en_docker=lambda: False, hors_ligne=lambda: False, profil=lambda: None, dossier_ollama=lambda: self.tmp / "ollama-models")
        self.addCleanup(lambda: (moteurs.CONTEXTE.update(self.ancien), shutil.rmtree(self.tmp, ignore_errors=True)))

    def test_llama_cpp_dossier_des_modeles_reglable(self):
        mo = ml.MoteurLlamaCpp()
        moteurs.MOTEURS[mo.id] = mo
        self.addCleanup(moteurs.MOTEURS.pop, mo.id, None)
        info = mo.info_dossier()
        self.assertEqual(info["modeles"]["actuel"], str(self.tmp / "engines" / "llamacpp" / "modeles"))
        ailleurs = self.tmp / "gros-disque" / "modeles"
        ml.regler_dossier_modeles(mo.id, str(ailleurs))
        self.assertEqual(mo.dossier_modeles(), ailleurs)
        self.assertTrue(mo.info_dossier()["modeles"]["personnalise"])
        ml.regler_dossier_modeles(mo.id, "")
        self.assertEqual(mo.dossier_modeles(), self.tmp / "engines" / "llamacpp" / "modeles", "vide : retour au dossier par défaut")
        with self.assertRaises(ml.ErreurMoteur):
            ml.regler_dossier_modeles(mo.id, "relatif/dossier")

    def test_ollama_montre_les_memes_lignes(self):
        mo = dialogue.MoteurOllama()
        info = mo.info_dossier()
        self.assertEqual(set(info) & {"actuel", "defaut", "libre_go", "installe", "modeles"}, {"actuel", "defaut", "libre_go", "installe", "modeles"})
        self.assertFalse(info["modeles"]["modifiable"], "les modèles d'Ollama se règlent dans l'onglet Modèles (qui sait copier ceux déjà téléchargés)")

    def test_l_installateur_d_ollama_recoit_le_dossier_choisi(self):
        from lutin import ollama_client

        class Rep:
            def __init__(self, c):
                self.c, self.status, self.headers = c, 200, {"Content-Length": str(len(c))}

            def read(self, n=-1):
                c, self.c = self.c, b""
                return c

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        lances = []
        with tempfile.TemporaryDirectory() as t:
            try:
                ollama_client.installer_windows(t, ouvrir=lambda r, timeout: Rep(b"x" * 100), lanceur_sortie=lambda c, d=0: "Valid|CN=Ollama Inc, O=Ollama", executer=lambda cmd, **k: lances.append(cmd) or type("R", (), {"returncode": 0})(), taille_min=10, dossier="E:/IA/Ollama")
            except ollama_client.ErreurOllama:
                pass          # « introuvable » après installation : sans importance ici, seule la commande lancée compte
        self.assertTrue(lances and "/DIR=E:/IA/Ollama" in lances[0] and "/SILENT" in lances[0], lances)


class ModelesRetrouves(unittest.TestCase):
    """Une mise à jour ou un redémarrage d'Ollama ne doit jamais donner l'impression que les modèles sont perdus."""

    def setUp(self):
        from unittest import mock
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-retrouves-"))
        self.models = self.tmp / "gros-disque" / "ollama-models"
        ranger(self.models, "registry.ollama.ai", "library/qwen3/8b", [("model", "a", True)])
        self.avant = (_m.DONNEES, dict(moteurs.CONTEXTE))
        _m.DONNEES = self.tmp / "donnees"
        _m.DONNEES.mkdir()
        self.addCleanup(self.fin)
        self.mock = mock

    def fin(self):
        _m.DONNEES = self.avant[0]
        moteurs.CONTEXTE.update(self.avant[1])
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_le_dernier_dossier_vu_est_retenu_et_signale_quand_ollama_ne_voit_rien(self):
        from lutin import diagnostic, emplacements
        self.assertEqual(emplacements.dossier_vu(), "")
        emplacements.retenir_dossier_vu(str(self.tmp / "inexistant"))
        self.assertEqual(emplacements.dossier_vu(), "", "un dossier sans modèles n'est pas retenu")
        emplacements.retenir_dossier_vu(str(self.models))
        self.assertEqual(emplacements.dossier_vu(), str(self.models))
        self.assertIsNone(emplacements.modeles_ailleurs(["qwen3:8b"]), "Ollama voit ses modèles : rien à dire")
        ailleurs = emplacements.modeles_ailleurs([])
        self.assertEqual(ailleurs, (str(self.models), 1))
        problemes = diagnostic.diagnostiquer(True, True, [], {}, docker=False, modeles_ailleurs=ailleurs)
        self.assertEqual([p["code"] for p in problemes], ["modeles_ailleurs"])
        self.assertIn("ne sont pas perdus", problemes[0]["texte"])
        self.assertEqual(problemes[0]["action"]["type"], "redemarrer_ollama")

    def test_ollama_relance_par_lutin_retrouve_le_dossier_habituel(self):
        from lutin import emplacements
        emplacements.retenir_dossier_vu(str(self.models))
        lances = []
        with self.mock.patch.dict("os.environ", {}, clear=False), self.mock.patch.object(_m, "chemin_ollama", lambda: "ollama"), self.mock.patch.object(_m, "etat_ollama", lambda: {"actif": bool(lances)}),                 self.mock.patch.object(emplacements, "lire_config_modeles", lambda: ""), self.mock.patch("subprocess.Popen", lambda cmd, **kw: lances.append(kw["env"]) or None), self.mock.patch("time.sleep", lambda s: None):
            __import__("os").environ.pop("OLLAMA_MODELS", None)
            _m.demarrer_ollama()
        self.assertEqual(lances[0].get("OLLAMA_MODELS"), str(self.models), "pas le dossier par défaut, vide")

    def test_la_mise_a_jour_d_ollama_garde_le_dossier_des_modeles(self):
        from lutin import emplacements, ollama_client
        mo = dialogue.MoteurOllama()
        appels = []
        possibles = {k: {"possible": True, "raison": "ok"} for k in moteurs.ACTIONS}
        with self.mock.patch.object(mo, "actions", lambda: possibles), self.mock.patch.object(_m, "arreter_ollama", lambda: appels.append("arreter")), self.mock.patch.object(_m, "demarrer_ollama", lambda: appels.append("demarrer")),                 self.mock.patch.object(ollama_client, "desinstaller_windows", lambda: appels.append("desinstaller")), self.mock.patch.object(ollama_client, "installer_windows", lambda c, p, **k: appels.append("installer")),                 self.mock.patch.object(emplacements, "dossier_modeles", lambda: self.models), self.mock.patch.object(emplacements, "definir_dossier_modeles", lambda d: appels.append("dossier:" + str(d))):
            mo.faire("mettre_a_jour", lambda *x: None)
        self.assertEqual(appels, ["arreter", "installer", "dossier:" + str(self.models), "demarrer"], "par-dessus, sans désinstaller, et le dossier des modèles est rétabli avant le redémarrage")
        self.assertEqual(emplacements.dossier_vu(), str(self.models))


class ReglagesMachine(unittest.TestCase):
    """llama.cpp est réglé d'après la machine, avec les seules options que ce programme-là connaît."""

    def profil(self, vram, coeurs=8):
        from lutin.machine import Gpu, Profil
        return Profil(systeme="windows", cpu="x", coeurs=coeurs, ram_go=32, ram_libre_go=20, gpus=[Gpu("NVIDIA GeForce RTX", "nvidia", vram)])

    def test_fils_de_calcul_et_repartition_selon_la_machine(self):
        aide = "--threads n  --fit [on|off]"
        args, ajuste = ml.reglages_machine(aide, "cuda", 2.5, self.profil(24))
        self.assertEqual((args, ajuste), (["--threads", "8"], False), "petit modèle, grosse carte : tout sur la carte")
        args, ajuste = ml.reglages_machine(aide, "cuda", 40.0, self.profil(8))
        self.assertTrue(ajuste and args[-2:] == ["--fit", "on"], "modèle trop gros pour la carte : llama.cpp répartit les couches")
        args, ajuste = ml.reglages_machine(aide, "cpu", 40.0, self.profil(8))
        self.assertEqual((args, ajuste), (["--threads", "8"], False), "sans carte utilisée, pas de répartition")

    def test_une_option_inconnue_n_est_jamais_passee(self):
        self.assertEqual(ml.reglages_machine("rien de connu", "cuda", 40.0, self.profil(8)), ([], False))
        self.assertEqual(ml.reglages_machine("--threads --fit", "cuda", 40.0, None), ([], False), "machine inconnue : rien d'inventé")


if __name__ == "__main__":
    unittest.main()
