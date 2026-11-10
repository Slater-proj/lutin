"""LM Studio piloté par Lutin sans son interface : installeur officiel (https://lmstudio.ai seulement), démon et serveur local sur 127.0.0.1, téléchargement de modèles ; tout avec de faux processus."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-lms-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import lmstudio as L  # noqa: E402
from lutin import moteur_llamacpp as ml  # noqa: E402
from lutin import moteurs  # noqa: E402


class Reponse:
    def __init__(self, corps, url="https://lmstudio.ai/install.sh"):
        self.corps, self.url = corps, url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return self.url

    def read(self, n=-1):
        return self.corps[:n] if n and n > 0 else self.corps


class Faux:
    def __init__(self, lignes=(), code=0):
        self.stdout, self.code = iter(lignes), code

    def wait(self):
        return self.code

    def poll(self):
        return self.code

    def terminate(self):
        pass

    def kill(self):
        pass


def rien(*a, **k):
    raise AssertionError("rien ne doit être lancé")


REEL_DEPENDANCES = L.preparer_dependances


class Module(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(L, "preparer_dependances", lambda dire=print, **kw: None)
        p.start()
        self.addCleanup(p.stop)

    def test_libatomic_manquante_est_installee_en_root_puis_l_installeur_continue(self):
        lances, vus = [], []
        faux = lambda cmd, **kw: (lances.append(cmd), mock.Mock(returncode=0, stdout="", stderr=""))[1]  # noqa: E731
        REEL_DEPENDANCES(vus.append, lancer=faux, present=lambda: False, trouver=lambda n: "/usr/bin/" + n if n == "apt-get" else None, root=True)
        self.assertEqual(lances, [["apt-get", "update"], ["apt-get", "install", "-y", "libatomic1"]])
        self.assertTrue(any("libatomic" in t for t in vus))

    def test_deja_presente_rien_n_est_lance(self):
        REEL_DEPENDANCES(lambda t: None, lancer=rien, present=lambda: True)

    def test_sans_droits_la_commande_exacte_est_donnee(self):
        with self.assertRaises(ValueError) as e:
            REEL_DEPENDANCES(lambda t: None, lancer=rien, present=lambda: False, trouver=lambda n: "/usr/bin/dnf" if n == "dnf" else None, root=False)
        self.assertIn("dnf install -y libatomic", str(e.exception))

    def test_l_installeur_qui_se_plaint_de_libatomic_est_explique(self):
        with mock.patch.object(L, "chemin_lms", lambda: None):
            with self.assertRaises(ValueError) as e:
                L.installer(lambda t: None, ouvrir=lambda req, timeout: Reponse(b"x"), lancer=lambda cmd, **kw: Faux(['ERROR: Missing required dependency: "libatomic" is not installed\n'], 1))
        self.assertIn("apt-get install -y libatomic1", str(e.exception))
        self.assertNotIn("code 1", str(e.exception))

    def test_l_installeur_vient_de_lmstudio_ai_seulement_et_est_lance_sans_shell(self):
        lances, vus = [], []
        with mock.patch.object(L, "chemin_lms", lambda: "/x/lms"):
            L.installer(vus.append, ouvrir=lambda req, timeout: Reponse(b"echo ok\n"), lancer=lambda cmd, **kw: (lances.append(cmd), Faux(["etape 1\n", "fini\n"]))[1])
        self.assertIn("etape 1", vus)
        self.assertEqual(len(lances), 1)
        self.assertIn(lances[0][0], ("bash", "powershell"))
        with self.assertRaises(ValueError):          # redirigé hors de lmstudio.ai
            L.installer(lambda t: None, ouvrir=lambda req, timeout: Reponse(b"x", "https://exemple.org/pirate.sh"), lancer=rien)
        with self.assertRaises(ValueError):          # vide
            L.installer(lambda t: None, ouvrir=lambda req, timeout: Reponse(b"  "), lancer=rien)
        with self.assertRaises(ValueError):          # énorme
            L.installer(lambda t: None, ouvrir=lambda req, timeout: Reponse(b"x" * (L.TAILLE_SCRIPT_MAX + 5)), lancer=rien)

    def test_un_installeur_qui_echoue_ou_ne_laisse_pas_lms_est_une_erreur_claire(self):
        with mock.patch.object(L, "chemin_lms", lambda: "/x/lms"):
            with self.assertRaises(ValueError) as e:
                L.installer(lambda t: None, ouvrir=lambda req, timeout: Reponse(b"exit 3"), lancer=lambda cmd, **kw: Faux(["boom\n"], 3))
            self.assertIn("boom", str(e.exception))
        with mock.patch.object(L, "chemin_lms", lambda: None):
            with self.assertRaises(ValueError) as e:
                L.installer(lambda t: None, ouvrir=lambda req, timeout: Reponse(b"echo"), lancer=lambda cmd, **kw: Faux([], 0))
            self.assertIn("lms", str(e.exception))

    def test_demarrer_lance_le_demon_puis_le_serveur_sur_le_port_demande(self):
        appels, etat = [], {"ok": False}

        def lancer(cmd, **kw):
            appels.append(cmd[1:])
            if cmd[1:3] == ["server", "start"]:
                etat["ok"] = True
            return mock.Mock(returncode=0, stdout="", stderr="")
        with mock.patch.object(L, "chemin_lms", lambda: "/x/lms"):
            self.assertEqual(L.demarrer(4321, lancer=lancer, repond_=lambda p: etat["ok"], dormir=lambda s: None), 4321)
            self.assertEqual(appels, [["daemon", "up"], ["server", "start", "--port", "4321"]])
            self.assertEqual(L.demarrer(4321, lancer=rien, repond_=lambda p: True), 4321, "déjà en marche : rien à lancer")

    def test_demarrer_sans_lms_ou_avec_un_demon_qui_refuse(self):
        with mock.patch.object(L, "chemin_lms", lambda: None):
            with self.assertRaises(ValueError):
                L.demarrer(1234, repond_=lambda p: False)
        with mock.patch.object(L, "chemin_lms", lambda: "/x/lms"):
            with self.assertRaises(ValueError) as e:
                L.demarrer(1234, lancer=lambda cmd, **kw: mock.Mock(returncode=1, stdout="", stderr="pas de GPU"), repond_=lambda p: False)
            self.assertIn("pas de GPU", str(e.exception))

    def test_telecharger_n_accepte_que_des_noms_simples(self):
        lances = []
        with mock.patch.object(L, "chemin_lms", lambda: "/x/lms"):
            for mauvais in ("--help", "a b", "../x", "x;y", "", "-y", "$(id)"):
                with self.assertRaises(ValueError, msg=mauvais):
                    L.telecharger(mauvais, lancer=rien)
            L.telecharger("openai/gpt-oss-20b", lancer=lambda cmd, **kw: (lances.append(cmd), Faux(["50 %\n"]))[1])
            L.telecharger("llama-3.1-8b@q4_k_m", lancer=lambda cmd, **kw: (lances.append(cmd), Faux([]))[1])
        self.assertEqual([c[1:] for c in lances], [["get", "openai/gpt-oss-20b"], ["get", "llama-3.1-8b@q4_k_m"]])

    def test_la_liste_des_modeles_se_lit_et_une_sortie_illisible_donne_une_liste_vide(self):
        sortie = json.dumps([{"type": "llm", "modelKey": "qwen/qwen3-4b", "sizeBytes": 2_500_000_000}, {"type": "embedding", "modelKey": "nomic"}, {"type": "vlm", "path": "x/y", "sizeBytes": 1_000_000_000}])
        with mock.patch.object(L, "chemin_lms", lambda: "/x/lms"):
            m = L.modeles(lancer=lambda cmd, **kw: mock.Mock(returncode=0, stdout=sortie, stderr=""))
            self.assertEqual([(x["nom"], x["taille_go"]) for x in m], [("qwen/qwen3-4b", 2.5), ("x/y", 1.0)])
            self.assertEqual(L.modeles(lancer=lambda cmd, **kw: mock.Mock(returncode=0, stdout="pas du json", stderr="")), [])


class Carte(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-lms-carte-"))
        self.ancien = dict(moteurs.CONTEXTE)
        moteurs.CONTEXTE["donnees"] = lambda: self.tmp
        moteurs.CONTEXTE["hors_ligne"] = lambda: False
        self.mo = moteurs.MOTEURS["openai"]
        ml.regler_serveur("openai", {"serveur": "lmstudio"})
        self.addCleanup(self.remettre)

    def remettre(self):
        ml.regler_serveur("openai", {"serveur": "", "port_lmstudio": 0})
        moteurs.CONTEXTE.clear()
        moteurs.CONTEXTE.update(self.ancien)

    def test_adresse_imposee_locale_et_port_regle(self):
        self.assertEqual(self.mo.adresse(), "http://127.0.0.1:1234/v1")
        ml.regler_serveur("openai", {"port_lmstudio": 4321})
        self.assertEqual(self.mo.adresse(), "http://127.0.0.1:4321/v1")
        for mauvais in (80, "abc", 70000):
            with self.assertRaises(Exception):
                ml.regler_serveur("openai", {"port_lmstudio": mauvais})

    def test_les_actions_suivent_l_etat_et_lutin_ne_desinstalle_jamais(self):
        with mock.patch.object(L, "chemin_lms", lambda: None):
            a = self.mo.actions()
            self.assertTrue(a["installer"]["possible"])
            self.assertFalse(a["demarrer"]["possible"] or a["arreter"]["possible"])
            self.assertEqual(self.mo.statut()["detail"], "LM Studio n'est pas installé.")
        with mock.patch.object(L, "chemin_lms", lambda: "/x/lms"), mock.patch.object(ml.MoteurOpenAI, "actif", lambda self_: False):
            a = self.mo.actions()
            self.assertFalse(a["installer"]["possible"])
            self.assertTrue(a["demarrer"]["possible"] and a["mettre_a_jour"]["possible"])
            self.assertFalse(a["desinstaller"]["possible"], "les modèles sont dans le dossier de LM Studio : Lutin ne le supprime pas")

    def test_les_taches_appellent_les_bonnes_commandes_et_refusent_hors_ligne(self):
        suivi = []
        with mock.patch.object(L, "installer", lambda dire, annule=None, **kw: suivi.append("installer")), mock.patch.object(L, "demarrer", lambda port, **kw: suivi.append(("demarrer", port))), \
                mock.patch.object(L, "telecharger", lambda nom, dire, annule=None, **kw: suivi.append(("telecharger", nom))), mock.patch.object(L, "arreter", lambda **kw: True):
            self.mo.faire("installer", lambda *a: None)
            self.mo.faire("demarrer", lambda *a: None)
            self.mo.faire("telecharger:openai/gpt-oss-20b", lambda *a: None)
            self.mo.faire("arreter", lambda *a: None)
        self.assertEqual(suivi, ["installer", ("demarrer", 1234), ("demarrer", 1234), ("telecharger", "openai/gpt-oss-20b")], "installé, puis démarré tout de suite ; « Démarrer » démarre")
        moteurs.CONTEXTE["hors_ligne"] = lambda: True
        with self.assertRaises(Exception):
            self.mo.faire("installer", lambda *a: None)


class Catalogue(unittest.TestCase):
    def test_le_catalogue_ne_garde_que_ce_que_lutin_sait_gerer_ou_relier(self):
        import json as _json
        from lutin import catalogue_moteurs
        ids = [m["id"] for m in _json.loads(catalogue_moteurs.FICHIER_LIVRE.read_text(encoding="utf-8"))["catalogue"]["moteurs"]]
        for retire in ("vllm", "sglang", "localai", "llama-swap"):
            self.assertNotIn(retire, ids)
        self.assertIn("lmstudio", ids)
        self.assertGreaterEqual(catalogue_moteurs.verifier(_json.loads(catalogue_moteurs.FICHIER_LIVRE.read_text(encoding="utf-8")))["version"], 4)


if __name__ == "__main__":
    unittest.main()
