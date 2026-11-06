"""L'essai réel d'un moteur : ses étapes, ses refus (rien n'est téléchargé sans « oui »), son rapport. Ici avec un faux llama-server : l'essai vrai se lance avec `lutin essai-moteur`."""
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401
from lutin import essai_moteur, moteurs
from lutin import moteur_llamacpp as ml

VRAI_POPEN = subprocess.Popen
FAUX = str(Path(__file__).resolve().parent / "fixtures" / "faux_llama_server.py")


def port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Essai(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-essai-"))
        self.ancien = dict(moteurs.CONTEXTE)
        moteurs.CONTEXTE.update(donnees=lambda: self.tmp, en_docker=lambda: False, hors_ligne=lambda: False, profil=lambda: None)
        self.m = ml.MoteurLlamaCpp()
        ml.regler("llamacpp", port=port_libre(), variante_installee="cpu")
        self.sortie = []
        self.addCleanup(self.fin)

    def fin(self):
        self.m.arreter()
        moteurs.CONTEXTE.update(self.ancien)

    def lancer(self, commande, **kw):
        return VRAI_POPEN([sys.executable, FAUX] + commande[1:], **kw)

    def modele(self, nom="un"):
        d = self.m.dossier_modeles()
        d.mkdir(parents=True, exist_ok=True)
        (d / (nom + ".gguf")).write_bytes(b"GGUF")

    def essai(self, options, **kw):
        with mock.patch.object(self.m, "serveur_pret", lambda: Path("llama-server")), mock.patch.object(ml.subprocess, "Popen", self.lancer):
            return essai_moteur.executer(options, self.m, ecrire=self.sortie.append, chemin_rapport=self.tmp / "rapport.json", **kw)

    def test_un_essai_complet_reussit_et_ecrit_son_rapport(self):
        self.modele()
        r = self.essai({"modele_local": "un", "ctx": 4096})
        self.assertTrue(r["reussi"], self.sortie)
        etapes = {e["etape"]: e for e in r["etapes"]}
        self.assertTrue(all(e["ok"] for e in r["etapes"]), r["etapes"])
        self.assertIn("jetons/s", etapes["Conversation en flux"]["detail"])
        self.assertIn("20.0", etapes["Conversation en flux"]["detail"], "vitesse d'après les durées du serveur (8 jetons en 0,4 s)")
        self.assertIn("appel reçu puis réponse", etapes["Appel d'outil"]["detail"])
        self.assertEqual(json.loads((self.tmp / "rapport.json").read_text(encoding="utf-8"))["moteur"], "llamacpp")
        self.assertFalse(self.m.statut()["actif"], "le serveur est arrêté à la fin")

    def test_rien_n_est_telecharge_sans_accord(self):
        appels = []
        with mock.patch.object(self.m, "serveur_pret", lambda: None), mock.patch.object(self.m, "installer", lambda *a, **k: appels.append("installer")):
            r = essai_moteur.executer({}, self.m, ecrire=self.sortie.append, entree=lambda q: "n")
        self.assertFalse(r["reussi"])
        self.assertEqual(appels, [], "refusé : rien n'a été téléchargé")
        self.assertIn("refusée", r["etapes"][-1]["detail"])

    def test_sans_modele_l_essai_dit_quoi_faire(self):
        r = self.essai({})
        self.assertFalse(r["reussi"])
        derniere = r["etapes"][-1]
        self.assertEqual(derniere["etape"], "Modèle")
        self.assertIn("--modele unsloth/Qwen3-4B-Instruct-2507-GGUF/Qwen3-4B-Instruct-2507-Q4_K_M.gguf", derniere["detail"])

    def test_le_telechargement_d_un_modele_demande_l_accord_avec_sa_taille(self):
        questions = []

        def telecharge(repo, fichier, progression):
            self.modele("m")
            return "m"
        with mock.patch.object(self.m, "fichiers_du_depot", lambda repo, http_json=None: [{"fichier": "m.gguf", "taille": 2_500_000_000}]), mock.patch.object(self.m, "telecharger_modele", telecharge),                 mock.patch.object(self.m, "serveur_pret", lambda: Path("llama-server")), mock.patch.object(ml.subprocess, "Popen", self.lancer):
            r = essai_moteur.executer({"modele": "auteur/depot/m.gguf", "sans_outils": True}, self.m, ecrire=self.sortie.append, entree=lambda q: questions.append(q) or "oui", chemin_rapport=self.tmp / "r.json")
        self.assertTrue(r["reussi"], self.sortie)
        self.assertEqual(len(questions), 1)
        self.assertIn("2500 Mo", questions[0], "la taille est annoncée avant de télécharger")

    def test_nom_de_modele_invalide(self):
        with self.assertRaises(ValueError):
            essai_moteur.decouper_modele("juste-un-nom")
        self.assertEqual(essai_moteur.decouper_modele("a/b/c/d.gguf"), ("a/b", "c/d.gguf"))

    def test_un_serveur_qui_ne_demarre_pas_est_rapporte_avec_le_journal(self):
        self.modele()

        def casse(commande, **kw):
            return VRAI_POPEN([sys.executable, "-c", "import sys; print('erreur de bibliothèque'); sys.exit(3)"], **kw)
        with mock.patch.object(self.m, "serveur_pret", lambda: Path("llama-server")), mock.patch.object(ml.subprocess, "Popen", casse):
            r = essai_moteur.executer({"modele_local": "un"}, self.m, ecrire=self.sortie.append, chemin_rapport=self.tmp / "r.json")
        self.assertFalse(r["reussi"])
        self.assertEqual(r["etapes"][-1]["etape"], "Démarrage du serveur")
        self.assertIn("erreur de bibliothèque", r["etapes"][-1]["detail"])


if __name__ == "__main__":
    unittest.main()
