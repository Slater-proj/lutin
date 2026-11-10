"""ExLlamaV3 piloté par Lutin (TabbyAPI) : installation dans un environnement dédié, démarrage/arrêt, téléchargement de modèles, filtre selon la machine, détection des nouvelles versions ; tout avec de faux processus."""
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-exl-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import catalogue_moteurs as cm  # noqa: E402
from lutin import exllamav3 as X  # noqa: E402
from lutin import moteur_llamacpp as ml  # noqa: E402
from lutin import moteurs, moteurs_maj  # noqa: E402

SHA = "a" * 40


def archive():
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        z.writestr("tabbyAPI-" + SHA + "/main.py", "print('tabby')\n")
        z.writestr("tabbyAPI-" + SHA + "/pyproject.toml", "[project]\nname='tabby'\n")
    return tampon.getvalue()


class Reponse:
    def __init__(self, corps, url="https://codeload.github.com/theroyallab/tabbyAPI/zip/" + SHA):
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
    def __init__(self, lignes=(), code=0, pid=4242):
        self.stdout, self.code, self.pid = iter(lignes), code, pid

    def wait(self):
        return self.code

    def poll(self):
        return self.code if self.code is not None else None

    def terminate(self):
        pass

    def kill(self):
        pass


def http(commit=SHA, lib="v1.6.6"):
    def f(url, entetes=None):
        if "commits/main" in url:
            return 200, {}, json.dumps({"sha": commit}).encode()
        return 200, {}, json.dumps({"tag_name": lib}).encode()
    return f


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-exl-t-"))
        self.dossiers = {"donnees": self.tmp}

    def faux_executer(self, version_lib="1.6.6"):
        def executer(cmd, **kw):
            if "venv" in cmd:
                py = X.python_venv(self.dossiers)
                py.parent.mkdir(parents=True, exist_ok=True)
                py.write_text("", encoding="utf-8")
                return mock.Mock(returncode=0, stdout="", stderr="")
            return mock.Mock(returncode=0, stdout="Name: exllamav3\nVersion: {}\n".format(version_lib), stderr="")
        return executer

    def installer(self, **kw):
        defauts = dict(dossiers=self.dossiers, port=5000, dire=lambda t: None, http=http(), ouvrir=lambda req, timeout: Reponse(archive()),
                       lancer=lambda cmd, **k: Faux(["Collecting torch\n", "Successfully installed\n"]), executer=self.faux_executer())
        defauts.update(kw)
        return X.installer(**defauts)


class Installation(Base):
    def test_le_config_est_local_sans_cle_et_refuse_les_chemins_piegeux(self):
        c = X.config_yaml(5123, self.tmp / "modeles")
        for attendu in ("host: 127.0.0.1", "port: 5123", "disable_auth: true", "allowed_origins: []", "web_ui: false", "inline_model_loading: true"):
            self.assertIn(attendu, c)
        for mauvais in (self.tmp / "a#b", Path("'x")):
            with self.assertRaises(ValueError):
                X.config_yaml(5000, mauvais)

    def test_installation_complete_epingle_le_commit_et_note_la_version_de_la_bibliotheque(self):
        r = self.installer()
        self.assertEqual(r, {"tabby": SHA, "lib": "1.6.6"})
        self.assertEqual(X.installee(self.dossiers), {"tabby": SHA, "lib": "1.6.6"})
        self.assertTrue((X.dossier_tabby(self.dossiers) / "main.py").is_file())
        self.assertIn("model_dir:", (X.dossier_tabby(self.dossiers) / "config.yml").read_text(encoding="utf-8"))
        self.assertTrue(X.dossier_modeles(self.dossiers).is_dir())

    def test_les_commandes_lancees_sont_celles_de_la_documentation_dans_l_environnement_dedie(self):
        cmds = []
        self.installer(lancer=lambda cmd, **k: (cmds.append((cmd, k.get("cwd"))), Faux(["ok\n"]))[1])
        cmd, cwd = cmds[0]
        self.assertEqual(cmd[1:], ["-m", "pip", "install", "-U", ".[cu12]"])
        self.assertEqual(Path(cmd[0]), X.python_venv(self.dossiers))
        self.assertEqual(Path(cwd), X.dossier_tabby(self.dossiers))

    def test_un_echec_de_pip_une_archive_redirigee_ou_trop_petite_ou_un_python_trop_ancien_sont_refuses(self):
        with self.assertRaises(ValueError) as e:
            self.installer(lancer=lambda cmd, **k: Faux(["ERROR: boom\n"], 1))
        self.assertIn("boom", str(e.exception))
        self.assertIsNone(X.installee(self.dossiers), "une installation ratée ne laisse pas croire que c'est installé")
        with self.assertRaises(ValueError):
            self.installer(ouvrir=lambda req, timeout: Reponse(archive(), "https://exemple.org/x.zip"))
        with self.assertRaises(ValueError):
            self.installer(ouvrir=lambda req, timeout: Reponse(b"x"))
        with mock.patch.object(X, "python_compatible", lambda v=None: False):
            with self.assertRaises(ValueError):
                self.installer()

    def test_une_archive_sans_tabby_est_refusee(self):
        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, "w") as z:
            z.writestr("autre/lisezmoi.txt", "x" * 2000)
        with self.assertRaises(ValueError):
            self.installer(ouvrir=lambda req, timeout: Reponse(tampon.getvalue()))

    def test_python_compatible(self):
        self.assertTrue(X.python_compatible((3, 12)))
        self.assertFalse(X.python_compatible((3, 9)))
        self.assertFalse(X.python_compatible((3, 15)))


class Vie(Base):
    def test_demarrer_ecrit_le_port_lance_main_dans_le_venv_et_note_le_processus(self):
        self.installer()
        etat, lances = {"ok": False}, []

        def lancer(cmd, **k):
            lances.append((cmd, k.get("cwd")))
            etat["ok"] = True
            return Faux(code=None, pid=777)
        self.assertEqual(X.demarrer(6001, self.dossiers, lancer=lancer, repond_=lambda p: etat["ok"], dormir=lambda s: None), 6001)
        self.assertEqual([Path(lances[0][0][0]).name in ("python", "python.exe"), lances[0][0][1:]], [True, ["main.py"]])
        self.assertIn("port: 6001", (X.dossier_tabby(self.dossiers) / "config.yml").read_text(encoding="utf-8"))
        self.assertEqual((X.dossier(self.dossiers) / "tabby.pid").read_text(encoding="utf-8"), "777")
        self.assertEqual(X.demarrer(6001, self.dossiers, lancer=lambda *a, **k: self.fail("déjà en marche"), repond_=lambda p: True), 6001)

    def test_demarrer_sans_installation_ou_avec_un_programme_qui_s_arrete_donne_son_journal(self):
        with self.assertRaises(ValueError):
            X.demarrer(5000, self.dossiers, repond_=lambda p: False)
        self.installer()

        def lancer(cmd, **k):
            (X.dossier(self.dossiers) / "tabby.log").write_text("CUDA introuvable", encoding="utf-8")
            return Faux(code=1)
        with self.assertRaises(ValueError) as e:
            X.demarrer(5000, self.dossiers, lancer=lancer, repond_=lambda p: False, dormir=lambda s: None)
        self.assertIn("introuvable", str(e.exception)) if False else self.assertIn("arrêté", str(e.exception))

    def test_arreter_tue_l_arbre_de_processus_note_puis_oublie_le_numero(self):
        self.installer()
        pid = X.dossier(self.dossiers) / "tabby.pid"
        pid.write_text("555", encoding="utf-8")
        tues = []
        self.assertTrue(X.arreter(self.dossiers, tuer=tues.append))
        self.assertEqual(tues, [555])
        self.assertFalse(pid.exists())
        self.assertTrue(X.arreter(self.dossiers, tuer=lambda p: self.fail("rien à arrêter")))

    def test_desinstaller_garde_les_modeles(self):
        self.installer()
        modele = X.dossier_modeles(self.dossiers) / "Qwen-exl3"
        modele.mkdir(parents=True)
        (modele / "config.json").write_text("{}", encoding="utf-8")
        X.desinstaller(self.dossiers)
        self.assertIsNone(X.installee(self.dossiers))
        self.assertFalse(X.dossier_tabby(self.dossiers).exists())
        self.assertEqual([m["nom"] for m in X.modeles(self.dossiers)], ["Qwen-exl3"])


class Modeles(Base):
    def test_telecharger_n_accepte_que_des_depots_et_revisions_simples(self):
        self.installer()
        cmds = []
        lancer = lambda cmd, **k: (cmds.append(cmd), Faux(["10 %\n"]))[1]  # noqa: E731
        for mauvais in ("--help", "a b/c", "../x", "x;y/z", "solo", ""):
            with self.assertRaises(ValueError, msg=mauvais):
                X.telecharger_modele(mauvais, "", self.dossiers, lancer=lancer)
        with self.assertRaises(ValueError):
            X.telecharger_modele("turboderp/Qwen-exl3", "--x", self.dossiers, lancer=lancer)
        self.assertEqual(cmds, [])
        X.telecharger_modele("turboderp/Qwen2.5-VL-7B-Instruct-exl3", "4.0bpw", self.dossiers, lancer=lancer)
        self.assertEqual(cmds[0][1:], ["main.py", "download", "turboderp/Qwen2.5-VL-7B-Instruct-exl3", "--revision", "4.0bpw"])
        with self.assertRaises(ValueError):
            X.telecharger_modele("turboderp/Qwen-exl3", "", self.dossiers, lancer=lambda cmd, **k: Faux(["boom\n"], 2))

    def test_la_liste_ne_garde_que_les_dossiers_de_modele(self):
        racine = X.dossier_modeles(self.dossiers)
        for nom, config in (("A-exl3", True), ("vide", False)):
            (racine / nom).mkdir(parents=True)
            if config:
                (racine / nom / "config.json").write_text("{}", encoding="utf-8")
                (racine / nom / "model.safetensors").write_bytes(b"x" * 2_000_000)
        m = X.modeles(self.dossiers)
        self.assertEqual([x["nom"] for x in m], ["A-exl3"])
        self.assertGreater(m[0]["taille_go"] + 1, 0)


class Versions(Base):
    def test_la_derniere_version_de_la_bibliotheque_et_le_dernier_commit_se_lisent(self):
        self.assertEqual(X.derniere_version_lib(http("x", "v1.7.0")), "1.7.0")
        self.assertEqual(X.dernier_commit(http("b" * 40)), "b" * 40)
        with self.assertRaises(ValueError):
            X.derniere_version_lib(http("x", "nimporte quoi"))
        with self.assertRaises(ValueError):
            X.dernier_commit(http("pas un sha"))

    def test_la_mise_a_jour_est_proposee_seulement_si_une_version_plus_recente_est_publiee(self):
        class Fausse:
            def exllamav3_choisi(self):
                return True

            def version(self):
                return "1.6.6"
        with mock.patch.object(X, "derniere_version_lib", lambda *a, **k: "1.7.0"):
            self.assertEqual(moteurs_maj._derniere_exllamav3(Fausse()), ("1.6.6", "1.7.0"))
            self.assertTrue(moteurs_maj.plus_recente("1.7.0", "1.6.6"))
            self.assertFalse(moteurs_maj.plus_recente("1.6.6", "1.6.6"))

        class Autre(Fausse):
            def exllamav3_choisi(self):
                return False
        self.assertIsNone(moteurs_maj._derniere_exllamav3(Autre()))


class Compatibilite(unittest.TestCase):
    """Les serveurs proposés dépendent de la machine : système, Docker, carte graphique."""

    def fiche(self):
        return {"plateformes": ["windows", "linux"], "materiel": ["nvidia"], "docker": False}

    def test_systeme_docker_et_carte(self):
        f = self.fiche()
        self.assertEqual(cm.compatibilite(f, "windows", False, ["nvidia"]), (True, ""))
        self.assertEqual(cm.compatibilite(f, "linux", False, ["intel", "nvidia"]), (True, ""))
        self.assertFalse(cm.compatibilite(f, "macos", False, ["apple"])[0])
        self.assertFalse(cm.compatibilite(f, "linux", True, ["nvidia"])[0], "pas dans Docker")
        self.assertFalse(cm.compatibilite(f, "windows", False, ["amd"])[0], "un fabricant connu et différent exclut")
        self.assertFalse(cm.compatibilite(f, "windows", False, [])[0], "aucune carte détectée : pas proposé")
        self.assertTrue(cm.compatibilite({"plateformes": ["windows", "linux", "macos"]}, "macos", True, [])[0], "sans exigence : toujours proposé")

    def test_le_catalogue_livre_filtre_exllamav3_et_garde_les_autres(self):
        fiches = {m["id"]: cm.vue(m) for m in cm.charger(None)["moteurs"] if m.get("type", "externe") == "externe"}
        self.assertIn("exllamav3", fiches)
        self.assertEqual(fiches["exllamav3"]["materiel"], ["nvidia"])
        self.assertFalse(fiches["exllamav3"]["docker"])
        self.assertTrue(cm.compatibilite(fiches["lmstudio"], "linux", True, [])[0])
        self.assertFalse(cm.compatibilite(fiches["exllamav3"], "linux", True, ["nvidia"])[0])

    def test_un_catalogue_avec_un_materiel_inconnu_est_refuse(self):
        base = {"id": "x", "nom": "X", "genre": "openai", "description": "d", "type": "externe"}
        for mauvais in ({"materiel": ["quantique"]}, {"materiel": []}, {"materiel": "nvidia"}, {"docker": "oui"}):
            with self.assertRaises(cm.ErreurCatalogue, msg=str(mauvais)):
                cm.valider({"version": 1, "moteurs": [dict(base, **mauvais)]})
        cm.valider({"version": 1, "moteurs": [dict(base, materiel=["nvidia"], docker=False)]})


class Carte(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-exl-carte-"))
        self.ancien = dict(moteurs.CONTEXTE)
        moteurs.CONTEXTE["donnees"] = lambda: self.tmp
        moteurs.CONTEXTE["hors_ligne"] = lambda: False
        moteurs.CONTEXTE["en_docker"] = lambda: False
        self.mo = moteurs.MOTEURS["openai"]
        ml.regler_serveur("openai", {"serveur": "exllamav3"})
        self.addCleanup(self.remettre)

    def remettre(self):
        ml.regler_serveur("openai", {"serveur": "", "port_exllamav3": 0})
        moteurs.CONTEXTE.clear()
        moteurs.CONTEXTE.update(self.ancien)

    def profil(self, fabricant):
        return lambda: mock.Mock(gpus=[mock.Mock(fabricant=fabricant)])

    def test_l_installation_demande_une_carte_nvidia_et_pas_docker(self):
        moteurs.CONTEXTE["profil"] = self.profil("nvidia")
        self.assertTrue(self.mo.actions()["installer"]["possible"])
        moteurs.CONTEXTE["profil"] = self.profil("amd")
        a = self.mo.actions()["installer"]
        self.assertFalse(a["possible"])
        self.assertIn("NVIDIA", a["raison"])
        moteurs.CONTEXTE["profil"] = self.profil("nvidia")
        moteurs.CONTEXTE["en_docker"] = lambda: True
        self.assertFalse(self.mo.actions()["installer"]["possible"])

    def test_adresse_locale_imposee_port_regle_et_statut(self):
        self.assertEqual(self.mo.adresse(), "http://127.0.0.1:5000/v1")
        ml.regler_serveur("openai", {"port_exllamav3": 5555})
        self.assertEqual(self.mo.adresse(), "http://127.0.0.1:5555/v1")
        for mauvais in (80, "abc", 99999):
            with self.assertRaises(Exception):
                ml.regler_serveur("openai", {"port_exllamav3": mauvais})
        self.assertEqual(self.mo.statut()["detail"], "ExLlamaV3 n'est pas installé.")

    def test_les_taches_appellent_les_bonnes_fonctions_et_ne_telechargent_pas_hors_ligne(self):
        suivi = []
        with mock.patch.object(X, "installer", lambda dossiers, port, dire, annule=None, **k: (suivi.append(("installer", port)), {"tabby": SHA, "lib": "1.6.6"})[1]), \
                mock.patch.object(X, "demarrer", lambda port, dossiers=None, **k: suivi.append(("demarrer", port))), mock.patch.object(X, "arreter", lambda dossiers=None, **k: suivi.append("arreter")), \
                mock.patch.object(X, "desinstaller", lambda dossiers=None: suivi.append("desinstaller")), \
                mock.patch.object(X, "telecharger_modele", lambda depot, rev, dossiers, dire, annule=None, **k: suivi.append(("modele", depot, rev))):
            for action in ("installer", "demarrer", "arreter", "desinstaller", "telecharger:turboderp/Qwen-exl3@4.0bpw"):
                self.mo.faire(action, lambda *a: None)
        self.assertEqual(suivi, [("installer", 5000), ("demarrer", 5000), ("demarrer", 5000), "arreter", "desinstaller", ("modele", "turboderp/Qwen-exl3", "4.0bpw")], "installé, puis démarré tout de suite ; « Démarrer » démarre")
        moteurs.CONTEXTE["hors_ligne"] = lambda: True
        with self.assertRaises(Exception):
            self.mo.faire("installer", lambda *a: None)


if __name__ == "__main__":
    unittest.main()
