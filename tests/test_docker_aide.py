"""Docker : le diagnostic de `lutin doctor`, les profils Compose des moteurs, les volumes (recréer un conteneur ne perd ni moteurs, ni modèles, ni réglages), l'annulation d'une installation."""
import tempfile
import time
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import core as _m  # noqa: F401  (avant les autres : import circulaire sinon)
from lutin import diagnostic, docker_doctor, engines

RACINE = Path(__file__).resolve().parent.parent


class Reponse:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def injoignable(*a, **k):
    raise OSError("injoignable")


class Montages(unittest.TestCase):
    def test_points_de_montage(self):
        texte = "30 22 0:27 / /data rw,relatime - ext4 /dev/sda1 rw\n31 22 0:28 / /models rw - ext4 /dev/sdb rw\n32 22 0:1 / / rw - overlay overlay rw\n"
        self.assertEqual(docker_doctor.points_de_montage(texte), {"/data", "/models", "/"})


class Conteneur(unittest.TestCase):
    def prepare(self):
        tmp = Path(tempfile.mkdtemp(prefix="lutin-docker-"))
        (tmp / "data").mkdir()
        (tmp / "models").mkdir()
        return tmp

    def lignes(self, tmp, montages, env=None, memoire=(None, 16e9), ouvrir=injoignable):
        env = dict({"LUTIN_HOME": str(tmp / "data"), "OLLAMA_MODELS": str(tmp / "models")}, **(env or {}))
        return docker_doctor.verifier_conteneur(env, montages=montages, memoire=memoire, ouvrir=ouvrir, libre=lambda d: 50e9)

    def test_des_volumes_montes_sont_ok(self):
        tmp = self.prepare()
        lignes = self.lignes(tmp, {str(tmp / "data"), str(tmp / "models")})
        self.assertFalse([ligne for ligne in lignes if ligne[0] == "erreur"], lignes)

    def test_un_dossier_qui_n_est_pas_un_volume_est_une_erreur_claire(self):
        tmp = self.prepare()
        lignes = self.lignes(tmp, {str(tmp / "models")})
        erreurs = [t for n, t in lignes if n == "erreur"]
        self.assertEqual(len(erreurs), 1)
        self.assertIn("disparaîtront", erreurs[0])

    def test_peu_de_memoire_est_signale(self):
        tmp = self.prepare()
        lignes = self.lignes(tmp, {str(tmp / "data"), str(tmp / "models")}, memoire=(4e9, 32e9))
        self.assertTrue(any(n == "attention" and "4.0 Go" in t for n, t in lignes), lignes)

    def test_un_moteur_injoignable_est_une_erreur_qui_dit_quoi_faire(self):
        tmp = self.prepare()
        lignes = self.lignes(tmp, {str(tmp / "data"), str(tmp / "models")}, env={"LUTIN_LLAMACPP_URL": "http://llamacpp:8080/v1"})
        erreurs = [t for n, t in lignes if n == "erreur"]
        self.assertTrue(erreurs and "profil Compose" in erreurs[0], lignes)

    def test_un_moteur_qui_repond_est_ok(self):
        tmp = self.prepare()
        lignes = self.lignes(tmp, {str(tmp / "data"), str(tmp / "models")}, env={"OLLAMA_URL": "http://ollama:11434"}, ouvrir=lambda *a, **k: Reponse())
        self.assertTrue(any(n == "ok" and "http://ollama:11434" in t for n, t in lignes), lignes)


class Hote(unittest.TestCase):
    def test_sans_docker_rien_a_dire(self):
        self.assertEqual(docker_doctor.verifier_hote(qui=lambda n: None), [])

    def test_docker_arrete(self):
        class R:
            returncode, stdout = 1, b""
        lignes = docker_doctor.verifier_hote(lanceur=lambda *a, **k: R(), qui=lambda n: "docker")
        self.assertEqual(lignes[0][0], "attention")

    def test_memoire_wsl_trop_petite(self):
        reponses = {"version": b"27.0.1", "compose": b"2.29.0", "info": b"6000000000|Docker Desktop"}

        def lanceur(cmd, **k):
            class R:
                returncode = 0
                stdout = reponses[cmd[1]]
            return R()
        lignes = docker_doctor.verifier_hote(lanceur=lanceur, qui=lambda n: "docker")
        self.assertTrue(any(n == "attention" and ".wslconfig" in t for n, t in lignes), lignes)


class ComposeEtVolumes(unittest.TestCase):
    """Test de CI des volumes : le contenu des fichiers Compose garantit que recréer le conteneur ne perd rien."""

    def lire(self, nom):
        return (RACINE / nom).read_text(encoding="utf-8")

    def test_chaque_compose_garde_les_donnees_dans_un_volume_nomme(self):
        for nom in ("docker-compose.yml", "docker-compose.slim.yml", "docker-compose.moteurs.yml"):
            t = self.lire(nom)
            self.assertIn("lutin-data:/data", t, nom)
            self.assertRegex(t, r"(?m)^volumes:\n(?:[ \t]+.*\n)*?[ \t]+lutin-data:", nom)

    def test_les_modeles_sont_dans_un_volume_nomme(self):
        self.assertIn("lutin-models:/models", self.lire("docker-compose.yml"))
        self.assertIn("lutin-models:/root/.ollama", self.lire("docker-compose.moteurs.yml"))

    def test_les_profils_des_moteurs(self):
        t = self.lire("docker-compose.moteurs.yml")
        for profil in ("ollama", "llamacpp-cpu", "llamacpp-cuda", "llamacpp-vulkan", "llamacpp-intel"):
            self.assertIn('profiles: ["%s"]' % profil, t)
        self.assertIn("LUTIN_LLAMACPP_URL: http://llamacpp:8080/v1", t)
        self.assertEqual(t.count("aliases: [llamacpp]"), 1, "l'alias vient du bloc commun")

    def test_le_demarrage_ne_reinstalle_ni_n_efface_rien(self):
        e = self.lire("docker/entrypoint.sh")
        self.assertNotRegex(e, r"\brm\s+-rf?\b")
        self.assertIn("--reconfigure", e, "la configuration est réappliquée, pas recréée")
        self.assertIn("--no-models", e)
        self.assertIn("--no-ollama", e)


class Reglages(unittest.TestCase):
    def test_l_adresse_de_llamacpp_vient_de_l_environnement(self):
        import os
        from unittest import mock
        mo = engines.MOTEURS["llamacpp"]
        with mock.patch.dict(os.environ, {"LUTIN_LLAMACPP_URL": "http://llamacpp:8080"}):
            self.assertTrue(mo.externe())
            self.assertEqual(mo.adresse(), "http://llamacpp:8080/v1")


class PremierLancement(unittest.TestCase):
    def test_moteur_pret(self):
        self.assertTrue(diagnostic.premier_lancement("Ollama", True, "")["pret"])

    def test_aucun_moteur_dit_pourquoi_et_recommande(self):
        r = diagnostic.premier_lancement("Ollama", False, "Pas installé.", {"moteur": "ollama", "nom": "Ollama", "raison": "le plus simple"})
        self.assertFalse(r["pret"])
        self.assertIn("Ollama", r["raison"])
        self.assertIn("Pas installé.", r["raison"])
        self.assertEqual(r["recommande"]["moteur"], "ollama")


class Annulation(unittest.TestCase):
    def test_annuler_arrete_l_operation_et_garde_la_reprise(self):
        class Faux:
            id, nom = "faux", "Faux"

            def faire(self, action, progression):
                for i in range(200):
                    progression("téléchargement", i, 200)          # lève ErreurAnnule quand l'utilisateur annule
                    time.sleep(0.02)

            def statut(self):
                return {}
        engines.lancer_tache(Faux(), "installer")
        time.sleep(0.2)
        self.assertTrue(engines.annuler_tache("faux"))
        for _ in range(100):
            if engines.tache("faux")["statut"] != "en cours":
                break
            time.sleep(0.05)
        self.assertEqual(engines.tache("faux")["statut"], "annule")
        self.assertEqual(engines.tache("faux")["erreur"], "")
        self.assertFalse(engines.annuler_tache("faux"), "rien à annuler ensuite")


if __name__ == "__main__":
    unittest.main()
