"""llama.cpp en mode routeur (plusieurs modèles sans redémarrer le serveur), clé d'accès générée, couches d'experts, version épinglée, embeddings par le moteur."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401
_TEMP = Path(tempfile.mkdtemp(prefix="lutin-routeur-env-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import core as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon ; enregistre les moteurs)
from lutin import llamacpp_engine as ml  # noqa: E402
from lutin import engines, engine_updates

VRAI_POPEN = subprocess.Popen
FAUX = str(Path(__file__).resolve().parent / "fixtures" / "faux_llama_server.py")
AIDE_COMPLETE = "--models-preset --models-max --api-key --n-cpu-moe --threads --fit --mmproj"
MESSAGE = [{"role": "user", "content": "Salut"}]


def port_libre():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-routeur-"))
        self.ancien = dict(engines.CONTEXT)
        engines.CONTEXT.update(donnees=lambda: self.tmp, en_docker=lambda: False, hors_ligne=lambda: False, profil=lambda: None)
        self.m = engines.ENGINES["llamacpp"]          # l'instance enregistrée : c'est elle que regler_avance retrouve
        self.args = self.tmp / "args.jsonl"
        os.environ["LUTIN_FAUX_ARGS"] = str(self.args)
        self.addCleanup(self.fin)
        d = self.m.dossier_modeles()
        d.mkdir(parents=True)
        for nom in ("un", "deux", "nomic-embed-text"):
            (d / (nom + ".gguf")).write_bytes(b"GGUF")
        ml.regler("llamacpp", port=port_libre(), variante_installee="cpu")
        self.aide = AIDE_COMPLETE
        patchs = [mock.patch.object(self.m, "serveur_pret", lambda: Path("llama-server")), mock.patch.object(ml, "aide_serveur", lambda exe: self.aide),
                  mock.patch.object(ml.subprocess, "Popen", self.lancer_faux)]
        for p in patchs:
            p.start()
            self.addCleanup(p.stop)

    def lancer_faux(self, commande, **kw):
        self.environnements = getattr(self, "environnements", []) + [kw.get("env")]
        return VRAI_POPEN([sys.executable, FAUX] + commande[1:], **kw)

    def lancements(self):
        return [json.loads(l) for l in self.args.read_text(encoding="utf-8").splitlines()] if self.args.exists() else []

    def fin(self):
        self.m.arreter()
        os.environ.pop("LUTIN_FAUX_ARGS", None)
        engines.CONTEXT.update(self.ancien)


class Routeur(Base):
    def test_le_preset_decrit_chaque_modele_et_refuse_les_noms_dangereux(self):
        t = ml.texte_preset([("un", Path("C:/m/un.gguf"), None), ("vision", "/m/v.gguf", "/m/mm.gguf"), ("nomic-embed-text", "/m/e.gguf", None), ("mal]\nmodel = /etc/passwd", "/x.gguf", None)],
                            8192, {"fils": 8, "n_cpu_moe": 20, "ngl": 99})
        self.assertIn("[un]\nmodel = C:/m/un.gguf", t)
        self.assertIn("mmproj = /m/mm.gguf", t)
        self.assertIn("[nomic-embed-text]\nmodel = /m/e.gguf\nembeddings = true", t)
        self.assertIn("c = 8192", t)
        self.assertIn("threads = 8", t)
        self.assertIn("n-cpu-moe = 20", t)
        self.assertNotIn("passwd", t, "un nom qui tente d'ajouter une ligne est écarté")
        self.assertEqual(t.count("[*]"), 1)

    def test_le_fichier_n_est_pas_garde_en_ram_en_plus_de_la_carte(self):
        """Un modèle de 22 Go en VRAM était AUSSI gardé en entier en mémoire vive (mmap) : le PC saturait. `no-mmap` dès qu'une carte graphique sert, y compris avec `--fit`."""
        for ajuste in (False, True):
            self.assertIn("no-mmap = true", ml.texte_preset([("un", "/m/un.gguf", None)], 8192, {"fils": 8, "ngl": 99 if not ajuste else 0, "sans_mmap": True}))
        self.assertNotIn("no-mmap", ml.texte_preset([("un", "/m/un.gguf", None)], 8192, {"fils": 8, "sans_mmap": False}))

    def test_deux_modeles_se_suivent_sans_redemarrer_le_serveur(self):
        """Critère : deux modèles (deux rôles) servis l'un après l'autre par le même serveur."""
        ml.regler_avance("llamacpp", {"routeur": True})
        self.assertTrue(self.m.routeur_actif())
        r1 = self.m.chat({"model": "un", "messages": MESSAGE, "options": {"num_ctx": 4096}}, 30)
        self.assertEqual(r1["message"]["content"].split(" (")[0], "réponse de un")
        proc = ml.SERVEUR["proc"]
        r2 = self.m.chat({"model": "deux", "messages": MESSAGE, "options": {"num_ctx": 4096}}, 30)
        self.assertEqual(r2["message"]["content"].split(" (")[0], "réponse de deux")
        r3 = self.m.chat({"model": "un", "messages": MESSAGE, "options": {"num_ctx": 4096}}, 30)
        self.assertEqual(r3["message"]["content"].split(" (")[0], "réponse de un")
        self.assertIs(ml.SERVEUR["proc"], proc, "le même processus a servi les trois réponses")
        self.assertEqual(len(self.lancements()), 1, "un seul lancement du serveur")
        commande = self.lancements()[0]
        self.assertIn("--models-preset", commande)
        self.assertNotIn("-m", commande)
        self.assertEqual(commande[commande.index("--models-max") + 1], "2")
        self.assertEqual(self.m.en_memoire("un"), {"taille": 0, "vram": 0})
        self.assertEqual(self.m.en_memoire("deux"), {"taille": 0, "vram": 0})
        self.assertIsNone(self.m.en_memoire("absent"))
        self.assertIn("Routeur démarré", self.m.statut()["detail"])
        preset = (self.m.dossier() / "modeles.ini").read_text(encoding="utf-8")
        for nom in ("un", "deux", "nomic-embed-text"):
            self.assertIn("[{}]".format(nom), preset)

    def test_un_modele_telecharge_apres_coup_relance_le_routeur_une_fois(self):
        ml.regler_avance("llamacpp", {"routeur": True})
        self.m.chat({"model": "un", "messages": MESSAGE}, 30)
        (self.m.dossier_modeles() / "trois.gguf").write_bytes(b"GGUF")
        self.m.chat({"model": "trois", "messages": MESSAGE}, 30)
        self.m.chat({"model": "un", "messages": MESSAGE}, 30)
        self.assertEqual(len(self.lancements()), 2)

    def test_sans_le_mode_routeur_le_serveur_redemarre_comme_avant(self):
        self.m.chat({"model": "un", "messages": MESSAGE}, 30)
        self.m.chat({"model": "deux", "messages": MESSAGE}, 30)
        self.assertEqual(len(self.lancements()), 2)
        self.assertIn("-m", self.lancements()[0])

    def test_le_routeur_est_refuse_si_le_programme_ne_le_sait_pas(self):
        self.aide = "--api-key --threads"
        with self.assertRaises(ml.ErreurMoteur):
            ml.regler_avance("llamacpp", {"routeur": True})
        self.assertFalse(self.m.routeur_actif())

    def test_embeddings_par_le_routeur_et_refus_sans_routeur(self):
        with self.assertRaises(ml.ErreurMoteur) as e:
            self.m.vecteurs("nomic-embed-text", ["a"])
        self.assertIn("routeur", str(e.exception))
        ml.regler_avance("llamacpp", {"routeur": True})
        v = self.m.vecteurs("nomic-embed-text", ["a", "bbb"])
        self.assertEqual([x[0] for x in v], [1.0, 3.0])
        proc = ml.SERVEUR["proc"]
        self.m.chat({"model": "un", "messages": MESSAGE}, 30)
        self.assertIs(ml.SERVEUR["proc"], proc, "le modèle de recherche et celui de conversation vivent dans le même serveur")


class ClesEtReglages(Base):
    def test_des_reglages_tenus_un_instant_ne_sont_ni_lus_vides_ni_ecrases(self):
        """Sous Windows, moteurs.json se lit mal un instant quand un autre programme le tient (antivirus, une autre écriture qui le remplace).
        lire_config rendait alors {}, et l'appelant réécrivait le fichier avec son seul changement : moteurs externes et clés perdus. Il est
        relu un peu plus tard ; et une écriture qui tombe sur un fichier tenu réessaie au lieu d'échouer."""
        ml.ecrire_config({"externes": [{"id": "lmstudio", "url": "http://127.0.0.1:1234/v1"}], "llamacpp": {"cle_serveur": "secrete"}})
        vrai_lire, vrai_remplacer, refus = Path.read_text, os.replace, []

        def tenu(chemin, *a, **k):
            if chemin.name == "moteurs.json" and len(refus) < 2:
                refus.append(chemin)
                raise PermissionError(13, "Access is denied", str(chemin))
            return vrai_lire(chemin, *a, **k)
        with mock.patch.object(Path, "read_text", tenu):
            config = ml.lire_config()
        self.assertEqual(config["llamacpp"]["cle_serveur"], "secrete", "relu un instant plus tard, pas lu vide")
        remplacements = []

        def remplacer(source, cible):
            remplacements.append(cible)
            if len(remplacements) < 3:
                raise PermissionError(13, "Access is denied", str(cible))
            return vrai_remplacer(source, cible)
        with mock.patch.object(ml.os, "replace", remplacer):
            ml.ecrire_config(dict(config, nouveau=True))
        self.assertTrue(ml.lire_config()["nouveau"], "écrit au troisième essai")
        self.assertEqual([f.name for f in Path(self.tmp).iterdir() if f.name.endswith(".tmp")], [], "pas de fichier temporaire laissé")

    def test_le_serveur_gere_a_une_cle_generee_et_stable(self):
        k = self.m.cle()
        self.assertGreaterEqual(len(k), 24)
        self.assertEqual(self.m.cle(), k)
        self.m.chat({"model": "un", "messages": MESSAGE}, 30)
        commande = self.lancements()[0]
        self.assertEqual(commande[commande.index("--api-key") + 1], k)
        self.assertEqual(ml.lire_config()["llamacpp"]["cle_serveur"], k)

    def test_la_cle_ne_passe_plus_par_la_ligne_de_commande_quand_le_serveur_lit_la_variable(self):
        """Sur la ligne de commande, la clé se lisait dans la liste des processus de la machine."""
        self.aide = AIDE_COMPLETE + " (env: llama_api_key)"
        k = self.m.cle()
        self.m.chat({"model": "un", "messages": MESSAGE}, 30)
        self.assertNotIn("--api-key", self.lancements()[0])
        self.assertNotIn(k, self.lancements()[0])
        self.assertEqual(self.environnements[-1]["LLAMA_API_KEY"], k)

    def test_un_serveur_externe_garde_sa_propre_cle(self):
        ml.regler("llamacpp", adresse="http://192.168.1.50:8080", cle="secret")
        self.assertEqual(self.m.cle(), "secret")

    def test_couches_d_experts_passees_seulement_si_le_programme_les_connait(self):
        ml.regler_avance("llamacpp", {"n_cpu_moe": 12})
        self.m.chat({"model": "un", "messages": MESSAGE}, 30)
        c = self.lancements()[0]
        self.assertEqual(c[c.index("--n-cpu-moe") + 1], "12")
        self.m.arreter()
        self.aide = "--api-key"
        self.m.chat({"model": "un", "messages": MESSAGE}, 30)
        self.assertNotIn("--n-cpu-moe", self.lancements()[1])

    def test_llama_cpp_1_0_charge_aussi_sans_projeter_le_fichier_en_memoire(self):
        """llama.cpp 1.0 a retiré `--no-mmap` (remplacé par `--load-mode none`) : sans lui, un modèle sur la carte restait AUSSI en entier en mémoire vive."""
        ml.regler("llamacpp", variante_installee="cuda")
        self.aide = AIDE_COMPLETE + " -lm, --load-mode MODE"
        self.m.chat({"model": "un", "messages": MESSAGE}, 30)
        c = self.lancements()[0]
        self.assertEqual(c[c.index("--load-mode") + 1], "none")
        self.assertNotIn("--no-mmap", c)
        self.m.arreter()
        self.aide = AIDE_COMPLETE + " --no-mmap --load-mode"
        self.m.chat({"model": "un", "messages": MESSAGE}, 30)
        self.assertIn("--no-mmap", self.lancements()[1], "un serveur qui connaît encore --no-mmap le garde")
        self.assertNotIn("--load-mode", self.lancements()[1])
        self.assertIn("load-mode = none", ml.texte_preset([("un", "/m/un.gguf", None)], 8192, {"fils": 8, "ngl": 99, "chargement_direct": True}))

    def test_des_experts_imposes_ne_laissent_pas_fit_renoncer(self):
        """`--fit` renonce quand des placements de tenseurs sont déjà donnés (c'est ce que fait --n-cpu-moe) : avec les experts imposés, toutes les couches vont
        sur la carte (-ngl 99) et --fit n'est pas demandé."""
        ml.regler("llamacpp", variante_installee="cuda")
        ml.regler_avance("llamacpp", {"n_cpu_moe": 20})
        with mock.patch.object(ml, "reglages_machine", lambda *a: (["--threads", "8", "--fit", "on"], True)):
            self.m.chat({"model": "un", "messages": MESSAGE}, 30)
        c = self.lancements()[0]
        self.assertNotIn("--fit", c)
        self.assertEqual((c[c.index("--n-cpu-moe") + 1], c[c.index("-ngl") + 1], c[c.index("--threads") + 1]), ("20", "99", "8"))
        self.m.arreter()
        ml.regler_avance("llamacpp", {"n_cpu_moe": 0})
        with mock.patch.object(ml, "reglages_machine", lambda *a: (["--threads", "8", "--fit", "on"], True)):
            self.m.chat({"model": "un", "messages": MESSAGE}, 30)
        c = self.lancements()[1]
        self.assertEqual(c[c.index("--fit") + 1], "on", "sans experts imposés, --fit place lui-même les experts en mémoire vive")
        self.assertNotIn("-ngl", c)

    def test_les_valeurs_sont_controlees(self):
        for donnees in ({"modeles_max": -1}, {"modeles_max": 99}, {"modeles_max": "x"}, {"n_cpu_moe": -1}, {"n_cpu_moe": 9999}, {"n_cpu_moe": "x"}, {"version_epinglee": "latest"}, {"version_epinglee": "b12; rm"}):
            with self.assertRaises(ml.ErreurMoteur, msg=str(donnees)):
                ml.regler_avance("llamacpp", donnees)
        ml.regler_avance("llamacpp", {"modeles_max": 3, "n_cpu_moe": 5, "version_epinglee": "B6500"})
        v = ml.vue_reglages("llamacpp")["avance"]
        self.assertEqual((v["modeles_max"], v["n_cpu_moe"], v["version_epinglee"], v["routeur_possible"]), (3, 5, "b6500", True))
        ml.regler_avance("llamacpp", {"n_cpu_moe": 0, "version_epinglee": ""})
        v = ml.vue_reglages("llamacpp")["avance"]
        self.assertEqual((v["n_cpu_moe"], v["version_epinglee"]), (0, ""))
        self.assertFalse(ml.regler_avance("openai", {"routeur": True}), "ces réglages ne concernent que llama.cpp géré")


class VersionEpinglee(Base):
    RELEASES = [{"tag_name": "b200", "assets": [{"name": "llama-b200-bin-win-cpu-x64.zip", "browser_download_url": "https://x/b200.zip"}]}, {"tag_name": "b199", "assets": [{"name": "llama-b199-bin-win-cpu-x64.zip", "browser_download_url": "https://x/b199.zip"}]}]

    def test_la_version_epinglee_est_la_seule_choisie(self):
        self.assertEqual(ml.choisir_fichiers(self.RELEASES, "windows", "amd64", "cpu")[0], "b200")
        self.assertEqual(ml.choisir_fichiers(self.RELEASES, "windows", "amd64", "cpu", "b199")[0], "b199")
        self.assertIsNone(ml.choisir_fichiers(self.RELEASES, "windows", "amd64", "cpu", "b1"))

    def test_l_installation_demande_la_version_epinglee_et_jamais_de_mise_a_jour(self):
        ml.regler_avance("llamacpp", {"version_epinglee": "b199"})
        vus = []

        def faux_json(url):
            vus.append(url)
            return self.RELEASES[1]
        with mock.patch.object(ml, "_systeme", lambda: "windows"), mock.patch("platform.machine", lambda: "AMD64"):
            with self.assertRaises(ml.ErreurMoteur):          # le téléchargement lui-même n'est pas simulé ici : seule la recherche de la version compte
                self.m.installer(lambda *a: None, http_json=faux_json, telecharger=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop")))
        self.assertEqual(vus, [ml.API_VERSION + "b199"])
        self.assertIsNone(engine_updates._latest_llamacpp(self.m, lambda url: self.RELEASES), "version épinglée : aucune mise à jour proposée")


if __name__ == "__main__":
    unittest.main()


class SansCouperUneReponse(Base):
    """Le serveur n'est JAMAIS redémarré sous une réponse en cours (la mise à jour de la fiche de suivi, avec un autre contexte, coupait la conversation)."""

    def corps(self, ctx):
        return {"model": "un", "messages": MESSAGE, "options": {"num_ctx": ctx}}

    def test_un_contexte_plus_petit_ne_redemarre_pas(self):
        self.m._assurer(self.corps(8192)); self.m._fini()
        self.m._assurer(self.corps(2048)); self.m._fini()
        self.assertEqual(len(self.lancements()), 1, "un contexte plus petit que celui du serveur convient : pas de redémarrage")

    def test_un_contexte_plus_grand_attend_la_fin_de_la_reponse_en_cours(self):
        import threading
        import time
        self.m._assurer(self.corps(4096))          # une réponse est en cours (jamais finie ici)
        fini = []

        def autre():
            self.m._assurer(self.corps(16384))
            fini.append(time.time())
            self.m._fini()
        t = threading.Thread(target=autre, daemon=True)
        t.start()
        time.sleep(1.5)
        self.assertEqual(len(self.lancements()), 1, "le serveur n'est pas redémarré sous la réponse en cours")
        self.assertFalse(fini)
        self.m._fini()          # la première réponse se termine
        t.join(30)
        self.assertEqual(len(self.lancements()), 2, "puis il redémarre avec le grand contexte")
