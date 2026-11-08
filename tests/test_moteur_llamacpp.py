"""llama.cpp géré par Lutin : choix du programme, installation sûre, serveur démarré à la demande, modèles GGUF ; et le serveur externe."""
import io
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import context  # noqa: F401
from lutin import moteur_llamacpp as ml
from lutin import moteurs

VRAI_POPEN = subprocess.Popen
FAUX = str(Path(__file__).resolve().parent / "fixtures" / "faux_llama_server.py")


def asset(nom, taille=1000):
    return {"name": nom, "size": taille, "browser_download_url": "https://github.com/x/" + nom}


RELEASES = [{"tag_name": "b200", "assets": [asset("llama-b200-bin-win-cpu-x64.zip")]},          # une version récente sans la variante CUDA : on prend la précédente qui l'a
            {"tag_name": "b199", "assets": [asset(n) for n in ("llama-b199-bin-win-cuda-12.4-x64.zip", "llama-b199-bin-win-cuda-13.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip", "llama-b199-bin-win-vulkan-x64.zip",
                                                                "llama-b199-bin-win-cpu-x64.zip", "llama-b199-bin-ubuntu-x64.tar.gz", "llama-b199-bin-ubuntu-cuda-12.8-x64.tar.gz", "cudart-llama-b199-bin-ubuntu-cuda-12.8-x64.tar.gz",
                                                                "llama-b199-bin-macos-arm64.tar.gz", "llama-b199-bin-ubuntu-arm64.tar.gz")]}]


def port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-llamacpp-"))
        self.ancien = dict(moteurs.CONTEXTE)
        moteurs.CONTEXTE.update(donnees=lambda: self.tmp, en_docker=lambda: False, hors_ligne=lambda: False, profil=lambda: None)
        self.m = ml.MoteurLlamaCpp()
        self.addCleanup(self.fin)

    def fin(self):
        self.m.arreter()
        moteurs.CONTEXTE.update(self.ancien)


class Choix(Base):
    def test_variante_selon_la_machine(self):
        class G:
            def __init__(self, f, v):
                self.fabricant, self.vram_go = f, v

        class P:
            def __init__(self, *g):
                self.gpus = list(g)
        self.assertEqual(ml.variante_auto(P(G("nvidia", 24)), "windows"), "cuda")
        self.assertEqual(ml.variante_auto(P(G("amd", 16)), "linux"), "vulkan")
        self.assertEqual(ml.variante_auto(P(G("intel", 0.5)), "windows"), "cpu", "une puce graphique intégrée ne compte pas")
        self.assertEqual(ml.variante_auto(P(), "linux"), "cpu")
        self.assertEqual(ml.variante_auto(P(), "macos"), "metal")

    def test_fichiers_a_telecharger(self):
        etiquette, fichiers = ml.choisir_fichiers(RELEASES, "windows", "amd64", "cuda")
        self.assertEqual((etiquette, [f["name"] for f in fichiers]), ("b199", ["llama-b199-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"]), "CUDA 12 et ses bibliothèques, de la version qui les a")
        self.assertEqual(ml.choisir_fichiers(RELEASES, "windows", "amd64", "cpu")[0], "b200")
        self.assertEqual([f["name"] for f in ml.choisir_fichiers(RELEASES, "linux", "x86_64", "cuda")[1]], ["llama-b199-bin-ubuntu-cuda-12.8-x64.tar.gz", "cudart-llama-b199-bin-ubuntu-cuda-12.8-x64.tar.gz"])
        self.assertEqual(ml.choisir_fichiers(RELEASES, "macos", "arm64", "metal")[1][0]["name"], "llama-b199-bin-macos-arm64.tar.gz")
        self.assertIsNone(ml.choisir_fichiers(RELEASES, "windows", "arm64", "cpu"))
        self.assertIsNone(ml.choisir_fichiers([], "windows", "amd64", "cpu"))


class Archives(Base):
    def test_une_archive_qui_sort_du_dossier_est_refusee(self):
        z = self.tmp / "mauvaise.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("../dehors.txt", "x")
        with self.assertRaises(ml.ErreurMoteur):
            ml.extraire(z, self.tmp / "dest")
        self.assertFalse((self.tmp / "dehors.txt").exists())
        t = self.tmp / "mauvaise.tar.gz"
        with tarfile.open(t, "w:gz") as f:
            info = tarfile.TarInfo("../../dehors2.txt")
            info.size = 1
            f.addfile(info, io.BytesIO(b"x"))
        with self.assertRaises(ml.ErreurMoteur):
            ml.extraire(t, self.tmp / "dest2")

    def test_zip_et_tar_sont_extraits(self):
        z = self.tmp / "a.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("sous/llama-server.exe" if os.name == "nt" else "sous/llama-server", "binaire")
        ml.extraire(z, self.tmp / "d1")
        self.assertIsNotNone(ml.trouver_serveur_dans(self.tmp / "d1"))


class Bibliotheques(unittest.TestCase):
    def test_une_bibliotheque_manquante_nomme_le_paquet(self):
        """Constat réel (essai S2 en CI) : llama-server ne démarre pas dans python:3.12-slim faute de libgomp.so.1."""
        log = "/tmp/x/llama-server: error while loading shared libraries: libgomp.so.1: cannot open shared object file: No such file or directory"
        aide = ml.aide_bibliotheque(log)
        self.assertIn("libgomp.so.1", aide)
        self.assertIn("apt install libgomp1", aide)
        self.assertEqual(ml.aide_bibliotheque("error while loading shared libraries: libinconnue.so.9: nope"), " Bibliothèque manquante : libinconnue.so.9.")
        self.assertEqual(ml.aide_bibliotheque("tout va bien"), "")


class Dossier(Base):
    """Où llama.cpp s'installe : à côté d'Ollama (même disque) si celui-ci a été déplacé, sinon dans le dossier de Lutin ; l'utilisateur peut choisir ailleurs."""

    def test_dossier_equivalent_a_celui_d_ollama(self):
        moteurs.CONTEXTE["dossier_ollama"] = lambda: self.tmp / "IA" / "ollama" / "models"
        self.assertEqual(self.m.dossier_propose(), self.tmp / "IA" / "ollama" / "llama.cpp")
        moteurs.CONTEXTE["dossier_ollama"] = lambda: Path.home() / ".ollama" / "models"
        self.assertIsNone(self.m.dossier_propose(), "Ollama est à son emplacement habituel : rien d'équivalent à proposer")
        moteurs.CONTEXTE["dossier_ollama"] = lambda: None
        self.assertIsNone(self.m.dossier_propose(), "dossier d'Ollama inconnu (Docker, Ollama absent)")

    def test_le_dossier_choisi_remplace_celui_de_lutin_et_se_retire(self):
        moteurs.CONTEXTE["dossier_ollama"] = lambda: self.tmp / "IA" / "ollama" / "models"
        moteurs.MOTEURS[self.m.id] = self.m
        self.addCleanup(moteurs.MOTEURS.pop, self.m.id, None)
        info = self.m.info_dossier()
        self.assertEqual((info["actuel"], info["defaut"]), (str(self.tmp / "moteurs" / "llamacpp"), str(self.tmp / "moteurs" / "llamacpp")))
        self.assertTrue(info["propose"].endswith("llama.cpp") and not info["personnalise"])
        ml.regler_dossier(self.m.id, info["propose"])
        self.assertEqual(self.m.dossier(), self.tmp / "IA" / "ollama" / "llama.cpp")
        self.assertEqual(self.m.dossier_modeles(), self.tmp / "IA" / "ollama" / "llama.cpp" / "modeles", "les modèles suivent")
        self.assertTrue(self.m.info_dossier()["personnalise"])
        ml.regler_dossier(self.m.id, "")
        self.assertEqual(self.m.dossier(), self.tmp / "moteurs" / "llamacpp", "vide : retour au dossier de Lutin")

    def test_dossier_invalide_ou_deja_installe(self):
        moteurs.MOTEURS[self.m.id] = self.m
        self.addCleanup(moteurs.MOTEURS.pop, self.m.id, None)
        with self.assertRaises(ml.ErreurMoteur):
            ml.regler_dossier(self.m.id, "dossier/relatif")
        fichier = self.tmp / "un-fichier"
        fichier.write_text("x")
        with self.assertRaises(ml.ErreurMoteur):
            ml.regler_dossier(self.m.id, str(fichier / "sous"))
        (self.m.dossier_defaut() / "bin").mkdir(parents=True)
        (self.m.dossier_defaut() / "bin" / ("llama-server.exe" if os.name == "nt" else "llama-server")).write_text("x")
        with self.assertRaises(ml.ErreurMoteur) as e:
            ml.regler_dossier(self.m.id, str(self.tmp / "ailleurs"))
        self.assertIn("désinstalle-le d'abord", str(e.exception), "rien n'est déplacé en douce")

    def test_la_page_recoit_les_infos_du_dossier_modifiables_sauf_sous_docker(self):
        moteurs.MOTEURS[self.m.id] = self.m
        self.addCleanup(moteurs.MOTEURS.pop, self.m.id, None)
        self.assertTrue(ml.vue_reglages(self.m.id)["dossier"]["modifiable"])
        moteurs.CONTEXTE["en_docker"] = lambda: True
        v = ml.vue_reglages(self.m.id)["dossier"]
        self.assertIn("actuel", v)          # le dossier est montré (le volume des moteurs)...
        self.assertFalse(v["modifiable"])          # ...mais se choisit dans le docker-compose, pas dans la page


class Reglages(Base):
    def test_adresse_normalisee_et_cle_non_exposee(self):
        self.assertEqual(ml.normaliser_adresse("http://h:8080"), "http://h:8080/v1")
        self.assertEqual(ml.normaliser_adresse("http://h:8080/v1/"), "http://h:8080/v1")
        self.assertEqual(ml.normaliser_adresse(""), "")
        with self.assertRaises(ml.ErreurMoteur):
            ml.normaliser_adresse("ftp://x")
        ml.regler("llamacpp", adresse="http://h:8080", cle="secret")
        v = ml.vue_reglages("llamacpp")
        self.assertEqual((v["url"], v["cle_definie"]), ("http://h:8080/v1", True))
        self.assertNotIn("secret", str(v))
        self.assertTrue(self.m.externe())
        self.assertTrue(all(not a["possible"] for a in self.m.actions().values()), "avec un serveur externe, rien à installer ni démarrer")
        ml.regler("llamacpp", adresse="")
        self.assertFalse(self.m.externe())

    def test_sous_docker_llamacpp_s_installe_comme_ailleurs(self):
        moteurs.CONTEXTE["en_docker"] = lambda: True
        a = self.m.actions()
        self.assertTrue(a["installer"]["possible"])          # plus de « indique son adresse » : l'image est légère, le moteur s'installe dans le volume
        self.assertNotIn("Docker", a["installer"]["raison"])
        moteurs.CONTEXTE["hors_ligne"] = lambda: True
        with self.assertRaises(ml.ErreurMoteur):
            self.m.installer(lambda *x: None)          # hors ligne : aucun téléchargement


class Installation(Base):
    def faux_telechargement(self, url, destination, progression=None, taille_min=0):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w") as z:
            z.writestr("llama-server.exe" if os.name == "nt" else "llama-server", "binaire")
        return destination

    def test_installer_puis_desinstaller_en_gardant_les_modeles(self):
        etapes = []
        with mock.patch.object(ml, "_systeme", lambda: "windows"), mock.patch("platform.machine", lambda: "AMD64"):
            self.m.installer(lambda t, f, tot: etapes.append(t), http_json=lambda url: RELEASES, telecharger=self.faux_telechargement)
        self.assertTrue(self.m.statut()["installe"])
        self.assertEqual(self.m.statut()["version"], "b200 (cpu)")
        self.assertIn("b200", self.m.version())
        self.assertFalse((self.tmp / "moteurs" / "llamacpp" / "telechargement").exists(), "les archives téléchargées sont nettoyées")
        modele = self.m.dossier_modeles() / "perso.gguf"
        modele.parent.mkdir(parents=True, exist_ok=True)
        modele.write_bytes(b"GGUF")
        self.m.desinstaller()
        self.assertIsNone(self.m.serveur_installe())
        self.assertTrue(modele.is_file(), "les modèles sont gardés")
        with self.assertRaises(ml.ErreurMoteur):
            self.m.desinstaller()

    def test_les_bibliotheques_cuda_rejoignent_le_programme_dans_son_sous_dossier(self):
        """L'archive CUDA donne llama-server dans un sous-dossier, l'archive des bibliothèques les met à la racine : elles doivent se retrouver côte à côte."""
        def telecharge(url, destination, progression=None, taille_min=0):
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(destination, "w") as z:
                if destination.name.startswith("cudart"):
                    z.writestr("cudart64_12.dll", "dll")
                else:
                    z.writestr("build/bin/llama-server.exe" if os.name == "nt" else "build/bin/llama-server", "binaire")
            return destination
        releases = [{"tag_name": "b1", "assets": [asset(n) for n in ("llama-b1-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip")]}]
        ml.regler("llamacpp", variante="cuda")
        with mock.patch.object(ml, "_systeme", lambda: "windows"), mock.patch("platform.machine", lambda: "AMD64"):
            self.m.installer(lambda *x: None, http_json=lambda url: releases, telecharger=telecharge)
        exe = self.m.serveur_installe()
        self.assertTrue((exe.parent / "cudart64_12.dll").is_file(), "la bibliothèque CUDA est à côté du programme")

    def test_empreinte_incorrecte_refusee(self):
        f = self.tmp / "x.zip"
        f.write_bytes(b"contenu")
        with self.assertRaises(ml.ErreurMoteur):
            ml.MoteurLlamaCpp._verifier_empreinte(f, {"digest": "sha256:" + "0" * 64})
        self.assertFalse(f.exists(), "un fichier corrompu est supprimé")

    def test_hors_ligne_et_github_muet(self):
        moteurs.CONTEXTE["hors_ligne"] = lambda: True
        with self.assertRaises(ml.ErreurMoteur):
            self.m.installer(lambda *x: None)
        moteurs.CONTEXTE["hors_ligne"] = lambda: False

        def muet(url):
            raise OSError("pas de réseau")
        with self.assertRaises(ml.ErreurMoteur) as e:
            self.m.installer(lambda *x: None, http_json=muet)
        self.assertIn("GitHub", str(e.exception))


class Modeles(Base):
    def test_lister_supprimer_et_chemins_surs(self):
        d = self.m.dossier_modeles()
        d.mkdir(parents=True)
        (d / "a.gguf").write_bytes(b"x" * 10)
        (d / "mmproj-b.gguf").write_bytes(b"x")
        r = self.m.modeles()
        self.assertEqual((r["installes"], r["tailles"]), (["a"], {"a": 10}), "les projecteurs d'images ne sont pas des modèles")
        with self.assertRaises(ml.ErreurMoteur):
            self.m.supprimer_modele("../../etc/passwd")
        self.m.supprimer_modele("a")
        self.assertEqual(self.m.modeles()["installes"], [])

    def test_recherche_et_fichiers_hugging_face(self):
        trouves = self.m.chercher_modeles("qwen3", http_json=lambda url: [{"id": "unsloth/Qwen3-4B-GGUF", "downloads": 5, "likes": 2}, {"id": "mauvais nom", "downloads": 1}])
        self.assertEqual([m["id"] for m in trouves], ["unsloth/Qwen3-4B-GGUF"])
        with self.assertRaises(ml.ErreurMoteur):
            self.m.chercher_modeles("   ")
        arbre = [{"type": "file", "path": "Q4_K_M.gguf", "lfs": {"size": 2_500_000_000}}, {"type": "file", "path": "Q8_0.gguf", "size": 4_000_000_000},
                 {"type": "file", "path": "mmproj-F16.gguf", "size": 5}, {"type": "file", "path": "gros-00001-of-00002.gguf", "size": 9}, {"type": "file", "path": "README.md", "size": 1}, {"type": "directory", "path": "x"}]
        self.assertEqual([f["fichier"] for f in self.m.fichiers_du_depot("unsloth/Qwen3-4B-GGUF", http_json=lambda url: arbre)], ["Q4_K_M.gguf", "Q8_0.gguf"])
        with self.assertRaises(ml.ErreurMoteur):
            self.m.fichiers_du_depot("../x")

    def test_telechargement_d_un_modele(self):
        recu = []

        def faux(url, destination, progression=None, taille_min=0):
            recu.append(url)
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            Path(destination).write_bytes(b"GGUF")
            return destination
        nom = self.m.telecharger_modele("unsloth/Qwen3-4B-GGUF", "Q4_K_M.gguf", lambda *a: None, telecharger=faux)
        self.assertEqual(nom, "Q4_K_M")
        self.assertEqual(recu, ["https://huggingface.co/unsloth/Qwen3-4B-GGUF/resolve/main/Q4_K_M.gguf"])
        self.assertEqual(self.m.modeles()["installes"], ["Q4_K_M"])
        for repo, fichier in (("../x/y", "a.gguf"), ("a/b", "../a.gguf"), ("a/b", "a.exe")):
            with self.assertRaises(ml.ErreurMoteur):
                self.m.telecharger_modele(repo, fichier, lambda *a: None, telecharger=faux)


class Serveur(Base):
    def lancer_faux(self, commande, **kw):
        return VRAI_POPEN([sys.executable, FAUX] + commande[1:], **kw)

    def test_le_serveur_demarre_a_la_demande_et_redemarre_si_le_modele_change(self):
        d = self.m.dossier_modeles()
        d.mkdir(parents=True)
        (d / "un.gguf").write_bytes(b"GGUF")
        (d / "deux.gguf").write_bytes(b"GGUF")
        ml.regler("llamacpp", port=port_libre(), variante_installee="cpu")
        with mock.patch.object(self.m, "serveur_pret", lambda: Path("llama-server")), mock.patch.object(ml.subprocess, "Popen", self.lancer_faux):
            self.assertIsNone(self.m.en_memoire("un"), "pas encore démarré")
            r = self.m.chat({"model": "un", "messages": [{"role": "user", "content": "Salut"}], "options": {"num_ctx": 4096}}, 30)
            self.assertEqual(r["message"]["content"], "réponse de un (contexte 4096)")
            self.assertEqual(self.m.en_memoire("un"), {"taille": 0, "vram": 0})
            self.assertEqual(self.m.statut()["actif"], True)
            r = self.m.chat({"model": "deux", "messages": [{"role": "user", "content": "Salut"}], "options": {"num_ctx": 4096}}, 30)
            self.assertEqual(r["message"]["content"], "réponse de deux (contexte 4096)", "le modèle a changé : le serveur a redémarré")
            self.assertIsNone(self.m.en_memoire("un"))
            self.m.arreter()
            self.assertFalse(self.m.statut()["actif"])
            with self.assertRaises(ml.ErreurMoteur):
                self.m.demarrer("absent", 4096, attente=1)

    def test_sans_programme_la_demande_est_claire(self):
        with mock.patch.object(self.m, "serveur_pret", lambda: None):
            with self.assertRaises(ml.ErreurMoteur) as e:
                self.m.demarrer("x")
        self.assertIn("Installer", str(e.exception))


class Externe(Base):
    def test_serveur_externe_sans_adresse_ou_hors_ligne(self):
        m = ml.MoteurExterne()
        self.assertFalse(m.statut()["actif"])
        self.assertIn("adresse", m.statut()["detail"])
        ml.regler("openai", adresse="http://192.168.1.50:8000")
        self.assertEqual(m.adresse(), "http://192.168.1.50:8000/v1")
        moteurs.CONTEXTE["hors_ligne"] = lambda: True
        self.assertFalse(m.actif(), "hors ligne : un serveur distant n'est pas joint")
        self.assertTrue(all(not a["possible"] for a in m.actions().values()))


if __name__ == "__main__":
    unittest.main()
