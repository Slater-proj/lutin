"""Télécharger un modèle de la bibliothèque d'Ollama sans Ollama, et retrouver des modèles déjà téléchargés ailleurs."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import core as _m  # noqa: E402,F401  (avant le dialogue : import circulaire sinon)
from lutin import agent  # noqa: E402,F401  (enregistre les moteurs)
from lutin import locations, engines, ollama_shared_models, ollama_registry  # noqa: E402
from lutin import llamacpp_engine as ml  # noqa: E402


def morceau(contenu):
    return contenu, "sha256:" + hashlib.sha256(contenu).hexdigest()


GGUF, EMP_GGUF = morceau(b"GGUF" + b"x" * 400)
GABARIT, EMP_GAB = morceau(b"{{ .Prompt }}")
CONF, EMP_CONF = morceau(b"{}")


def manifeste():
    return json.dumps({"config": {"mediaType": "application/vnd.docker.container.image.v1+json", "digest": EMP_CONF, "size": len(CONF)},
                       "layers": [{"mediaType": "application/vnd.ollama.image.model", "digest": EMP_GGUF, "size": len(GGUF)},
                                  {"mediaType": "application/vnd.ollama.image.template", "digest": EMP_GAB, "size": len(GABARIT)}]}).encode()


def faux_http(statut=200, corps=None):
    appels = []

    def http(url, entetes=None, delai=10):
        appels.append(url)
        return statut, {}, corps if corps is not None else manifeste()
    http.appels = appels
    return http


def faux_recuperer(contenus, abime=False):
    pris = []

    def recuperer(url, destination, progression=None, ouvrir=None, taille_min=0):
        hexa = url.rsplit("sha256:", 1)[1]
        pris.append(hexa)
        donnees = contenus["sha256:" + hexa]
        if abime:
            donnees = donnees[:-1] + b"?"
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(donnees)
        if progression:
            progression("téléchargement", len(donnees), len(donnees))
        return Path(destination)
    recuperer.pris = pris
    return recuperer


TOUS = {EMP_GGUF: GGUF, EMP_GAB: GABARIT, EMP_CONF: CONF}


class Telechargement(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="lutin-registre-"))
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_noms(self):
        self.assertEqual(ollama_registry.decomposer("qwen3:8b"), ("library", "qwen3", "8b"))
        self.assertEqual(ollama_registry.decomposer("huihui_ai/qwen3-abliterated:4b"), ("huihui_ai", "qwen3-abliterated", "4b"))
        self.assertEqual(ollama_registry.decomposer("qwen3"), ("library", "qwen3", "latest"))
        for mauvais in ("", "../x", "a b", "x/../y:1", "a/b/c:1"):
            with self.assertRaises(ollama_registry.ErreurRegistre):
                ollama_registry.decomposer(mauvais)

    def test_un_modele_est_range_comme_ollama_et_relu_sous_le_meme_nom(self):
        http = faux_http()
        suivi = []
        ollama_registry.telecharger("huihui_ai/qwen3-abliterated:4b", self.d, lambda t, f, tot: suivi.append((f, tot)), http=http, recuperer=faux_recuperer(TOUS))
        self.assertIn("/v2/huihui_ai/qwen3-abliterated/manifests/4b", http.appels[0])
        lus = ollama_shared_models.lire(self.d)
        self.assertEqual(list(lus), ["huihui_ai/qwen3-abliterated:4b"], "le même nom que dans Ollama")
        self.assertEqual(lus["huihui_ai/qwen3-abliterated:4b"]["fichier"].read_bytes(), GGUF)
        self.assertEqual(suivi[-1][0], suivi[-1][1], "la progression va jusqu'au bout")

    def test_modele_inexistant_morceau_corrompu_et_reprise(self):
        with self.assertRaises(ollama_registry.ErreurRegistre) as e:
            ollama_registry.telecharger("nexiste:pas", self.d, http=faux_http(404, b""), recuperer=faux_recuperer(TOUS))
        self.assertIn("does not exist", str(e.exception), "le message est reconnu par la page (modèle retiré de la liste)")
        with self.assertRaises(ollama_registry.ErreurRegistre) as e:
            ollama_registry.telecharger("qwen3:8b", self.d, http=faux_http(), recuperer=faux_recuperer(TOUS, abime=True))
        self.assertIn("corrompu", str(e.exception))
        self.assertEqual(ollama_shared_models.lire(self.d), {}, "rien n'est annoncé tant que le modèle n'est pas entier")
        self.assertFalse(list((self.d / "blobs").glob("sha256-*")) and any(f.stat().st_size == len(GGUF) and f.read_bytes() != GGUF for f in (self.d / "blobs").glob("sha256-*")), "le morceau abîmé est supprimé")
        deux = faux_recuperer(TOUS)
        ollama_registry.telecharger("qwen3:8b", self.d, http=faux_http(), recuperer=deux)
        un_autre = faux_recuperer(TOUS)
        ollama_registry.telecharger("qwen3:4b", self.d, http=faux_http(), recuperer=un_autre)
        self.assertEqual(un_autre.pris, [], "les morceaux déjà présents ne sont pas retéléchargés")

    def test_un_manifeste_sans_modele_ou_illisible_est_refuse(self):
        sans = json.dumps({"layers": [{"mediaType": "application/vnd.ollama.image.template", "digest": EMP_GAB, "size": 3}]}).encode()
        with self.assertRaises(ollama_registry.ErreurRegistre):
            ollama_registry.telecharger("x:1", self.d, http=faux_http(200, sans), recuperer=faux_recuperer(TOUS))
        with self.assertRaises(ollama_registry.ErreurRegistre):
            ollama_registry.telecharger("x:1", self.d, http=faux_http(200, b"pas du json"), recuperer=faux_recuperer(TOUS))

    def test_suppression_garde_les_morceaux_encore_utilises(self):
        for nom in ("qwen3:8b", "qwen3:4b"):
            ollama_registry.telecharger(nom, self.d, http=faux_http(), recuperer=faux_recuperer(TOUS))
        libere = ollama_registry.supprimer("qwen3:8b", self.d)
        self.assertEqual(libere, 0, "le même fichier sert encore au modèle 4b")
        self.assertEqual(list(ollama_shared_models.lire(self.d)), ["qwen3:4b"])
        ollama_registry.supprimer("qwen3:4b", self.d)
        self.assertEqual(list((self.d / "blobs").glob("sha256-*")), [], "plus aucun modèle : plus aucun morceau")
        self.assertEqual(ollama_registry.supprimer("absent:1", self.d), 0)


class DansLlamaCpp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-registre-llama-"))
        self.ancien = dict(engines.CONTEXTE)
        engines.CONTEXTE.update(donnees=lambda: self.tmp, en_docker=lambda: False, hors_ligne=lambda: False, profil=lambda: None, profil_attendu=None, dossier_ollama=lambda: None)
        ml.CACHE_PARTAGE.clear()
        self.m = ml.MoteurLlamaCpp()
        self.addCleanup(lambda: (engines.CONTEXTE.update(self.ancien), ml.CACHE_PARTAGE.clear(), shutil.rmtree(self.tmp, ignore_errors=True)))

    def test_telecharger_puis_lister_puis_supprimer(self):
        vrai = ollama_registry.telecharger
        ollama_registry.telecharger = lambda modele, dossier, progression=None: vrai(modele, dossier, progression, http=faux_http(), recuperer=faux_recuperer(TOUS))
        self.addCleanup(setattr, ollama_registry, "telecharger", vrai)
        self.m.telecharger_ollama("qwen3:8b", lambda *a: None)
        r = self.m.modeles()
        self.assertEqual(r["installes"], ["qwen3:8b"])
        self.assertEqual(r["partages"], [], "téléchargé par Lutin pour llama.cpp : pas « d'Ollama »")
        self.assertEqual(self.m._fichier_modele("qwen3:8b").read_bytes(), GGUF)
        self.m.supprimer_modele("qwen3:8b")
        self.assertEqual(self.m.modeles()["installes"], [])

    def test_serveur_externe_ne_telecharge_pas(self):
        ml.regler("llamacpp", "http://127.0.0.1:9999")
        with self.assertRaises(ml.ErreurMoteur):
            self.m.telecharger_ollama("qwen3:8b", lambda *a: None)


class RetrouverMesModeles(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-retrouver-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_un_ancien_dossier_sur_un_autre_disque_est_trouve(self):
        ancien = self.tmp / "E" / "IA" / "Ollama" / "models"
        manif = ancien / "manifests" / "registry.ollama.ai" / "library" / "qwen3" / "8b"
        manif.parent.mkdir(parents=True)
        manif.write_text(json.dumps({"layers": [{"mediaType": ollama_shared_models.TYPE_MODELE, "digest": EMP_GGUF, "size": len(GGUF)}]}), encoding="utf-8")
        (ancien / "blobs").mkdir()
        (ancien / "blobs" / ("sha256-" + EMP_GGUF.split(":")[1])).write_bytes(GGUF)
        vide = self.tmp / "C" / "Users" / "x" / ".ollama" / "models"
        (vide / "manifests").mkdir(parents=True)
        vrai = locations.racines_a_visiter
        locations.racines_a_visiter = lambda: [self.tmp / "E", self.tmp / "D"]
        self.addCleanup(setattr, locations, "racines_a_visiter", vrai)
        trouves = locations.chercher_dossiers_modeles(connus=[str(vide)])
        self.assertEqual([t["chemin"] for t in trouves], [str(self.tmp / "E" / "IA" / "Ollama" / "models")], "le dossier vide n'est pas proposé")
        self.assertEqual(trouves[0]["modeles"], 1)


if __name__ == "__main__":
    unittest.main()
