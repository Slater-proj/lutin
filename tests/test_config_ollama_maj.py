import copy
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401
from lutin import catalogue, config, miseajour, ollama_client
from lutin.machine import Gpu, Profil
from lutin.ollama_client import ErreurOllama, Ollama

CAT = catalogue.charger()


class Chemins(unittest.TestCase):
    def test_windows(self):
        d = config.dossiers({"APPDATA": r"C:\U\AppData\Roaming", "LOCALAPPDATA": r"C:\U\AppData\Local", "USERPROFILE": r"C:\U"}, "windows")
        self.assertEqual(d["config"], Path(r"C:\U\AppData\Roaming") / "Lutin")
        self.assertEqual(d["cache"], Path(r"C:\U\AppData\Local") / "Lutin" / "cache")
        self.assertEqual(d["memoire"].parent, d["config"], "mémoire et données avec la configuration, le cache à part")

    def test_linux_respecte_xdg(self):
        d = config.dossiers({"HOME": "/home/a", "XDG_DATA_HOME": "/d", "XDG_CONFIG_HOME": "/c", "XDG_CACHE_HOME": "/k"}, "linux")
        self.assertEqual((d["config"], d["donnees"], d["cache"]), (Path("/c/lutin"), Path("/d/lutin"), Path("/k/lutin")))
        d = config.dossiers({"HOME": "/home/a"}, "linux")
        self.assertEqual(d["donnees"], Path("/home/a/.local/share/lutin"))

    def test_macos(self):
        d = config.dossiers({"HOME": "/Users/a"}, "macos")
        self.assertIn("Application Support", str(d["donnees"]))

    def test_mode_portable(self):
        d = config.dossiers({"LUTIN_HOME": "/portable"}, "windows")
        self.assertTrue(all(str(v).replace("\\", "/").startswith("/portable") for v in d.values()))


class Configuration(unittest.TestCase):
    def test_fichier_absent_abime_ou_inattendu_donne_les_valeurs_par_defaut(self):
        with tempfile.TemporaryDirectory() as t:
            d = config.dossiers({"LUTIN_HOME": t})
            self.assertEqual(config.charger(d), config.DEFAUT)
            d["config"].mkdir(parents=True)
            for contenu in ("{pas du json", "[1,2]", "null", '"texte"'):
                (d["config"] / "config.json").write_text(contenu, encoding="utf-8")
                self.assertEqual(config.charger(d), config.DEFAUT, contenu)

    def test_aller_retour_et_copie_de_la_version_precedente(self):
        with tempfile.TemporaryDirectory() as t:
            d = config.dossiers({"LUTIN_HOME": t})
            cfg = config.charger(d)
            cfg["securite"]["niveau"] = "reseau"
            config.enregistrer(d, cfg)
            cfg["installe"] = True
            config.enregistrer(d, cfg)
            self.assertEqual(config.charger(d)["securite"]["niveau"], "reseau")
            self.assertFalse(json.loads((d["config"] / "config.json.bak").read_text(encoding="utf-8"))["installe"], "la version précédente est gardée")

    def test_migration_garde_le_connu_ignore_l_inconnu_complete_le_manquant(self):
        ancien = {"securite": {"niveau": "reseau"}, "inconnu": 1, "installe": True}
        n = config.migrer(ancien)
        self.assertEqual((n["schema"], n["securite"]["niveau"], n["securite"]["port"], n["installe"]), (config.SCHEMA, "reseau", 8777, True))
        self.assertNotIn("inconnu", n)
        self.assertNotIn("schema", ancien, "l'entrée n'est pas modifiée")

    def test_preparer_pose_la_memoire_sans_ecraser(self):
        with tempfile.TemporaryDirectory() as t:
            d = config.dossiers({"LUTIN_HOME": t})
            config.preparer(d)
            self.assertTrue((d["memoire"] / "CONTEXTE.md").is_file() and (d["memoire"] / "MEMOIRE.md").is_file())
            (d["memoire"] / "CONTEXTE.md").write_text("à moi", encoding="utf-8")
            config.preparer(d)
            self.assertEqual((d["memoire"] / "CONTEXTE.md").read_text(encoding="utf-8"), "à moi")


# ---------------------------------------------------------------- faux Ollama
INSTALLES = {"qwen3:8b": "aaa111"}
PULLS = []


class Faux(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, o):
        d = json.dumps(o).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)

    def do_GET(self):
        if self.path == "/api/version":
            return self._json(200, {"version": "0.12.0"})
        if self.path == "/api/tags":
            return self._json(200, {"models": [{"name": n, "digest": d, "size": 5_000_000_000} for n, d in INSTALLES.items()]})
        self._json(404, {})

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/show":
            return self._json(200, {"capabilities": ["completion", "tools"]} if corps["model"] != "ancien" else {})
        if self.path == "/api/pull":
            PULLS.append(corps["model"])
            self.send_response(200); self.end_headers()
            for e in ({"status": "pulling", "completed": 10, "total": 100}, {"status": "pulling", "completed": 100, "total": 100}) + (({"error": "boom"},) if corps["model"] == "casse" else ({"status": "success"},)):
                self.wfile.write((json.dumps(e) + "\n").encode()); self.wfile.flush()
            return
        self._json(404, {})


SERVEUR = ThreadingHTTPServer(("127.0.0.1", 0), Faux)
threading.Thread(target=SERVEUR.serve_forever, daemon=True).start()
OLLAMA = Ollama("http://127.0.0.1:%d" % SERVEUR.server_address[1])


class ClientOllama(unittest.TestCase):
    def test_etat(self):
        self.assertTrue(OLLAMA.actif())
        self.assertEqual(OLLAMA.version(), "0.12.0")
        self.assertEqual(OLLAMA.installes()["qwen3:8b"]["digest"], "aaa111")
        self.assertFalse(Ollama("http://127.0.0.1:9").actif())
        with self.assertRaises(ErreurOllama):
            Ollama("http://127.0.0.1:9").installes()

    def test_capacites(self):
        self.assertEqual(OLLAMA.capacites("qwen3:8b"), ["completion", "tools"])
        self.assertIsNone(OLLAMA.capacites("ancien"), "ancienne version d'Ollama : on ne sait pas")
        self.assertIsNone(Ollama("http://127.0.0.1:9").capacites("x"))

    def test_telechargement_avec_progression_et_erreur(self):
        vu = []
        OLLAMA.telecharger("qwen3:4b", lambda t, f, tot: vu.append((t, f, tot)))
        self.assertEqual(vu[0], ("pulling", 10, 100))
        self.assertEqual(vu[-1][0], "success")
        with self.assertRaises(ErreurOllama):
            OLLAMA.telecharger("casse")

    def test_variables_selon_la_machine(self):
        gros = Profil(ram_go=32, gpus=[Gpu("x", "nvidia", 24)])
        v = ollama_client.variables_serveur(gros, "D:\\modeles")
        self.assertEqual((v["OLLAMA_FLASH_ATTENTION"], v["OLLAMA_KV_CACHE_TYPE"], v["OLLAMA_MODELS"]), ("1", "q8_0", "D:\\modeles"))
        sans = ollama_client.variables_serveur(Profil(ram_go=8))
        self.assertNotIn("OLLAMA_FLASH_ATTENTION", sans)
        self.assertNotIn("OLLAMA_MODELS", sans)

    def test_trouver_executable(self):
        self.assertEqual(ollama_client.trouver_executable("linux", {}, quelle=lambda n: "/usr/bin/ollama"), "/usr/bin/ollama")
        with tempfile.TemporaryDirectory() as t:
            exe = Path(t) / "Programs" / "Ollama" / "ollama.exe"
            exe.parent.mkdir(parents=True)
            exe.write_text("x")
            self.assertEqual(ollama_client.trouver_executable("windows", {"LOCALAPPDATA": t}, quelle=lambda n: None), str(exe))
        self.assertEqual(ollama_client.trouver_executable("windows", {"LOCALAPPDATA": "/nulle/part"}, quelle=lambda n: None), "")


class Reponse:
    def __init__(self, corps, statut=200):
        self.corps, self.status, self.headers, self.pos = corps, statut, {"Content-Length": str(len(corps))}, 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        bloc = self.corps[self.pos:] if n < 0 else self.corps[self.pos:self.pos + n]
        self.pos += len(bloc)
        return bloc


class InstallationOllama(unittest.TestCase):
    def test_refuse_http_et_les_fichiers_trop_petits(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ErreurOllama):
                ollama_client.telecharger_fichier("http://exemple.org/x.exe", Path(t) / "x.exe")
            with self.assertRaises(ErreurOllama):
                ollama_client.telecharger_fichier("https://exemple.org/x.exe", Path(t) / "x.exe", ouvrir=lambda r, timeout: Reponse(b"petit"))
            self.assertFalse((Path(t) / "x.exe").exists())

    def test_telechargement_et_reprise(self):
        with tempfile.TemporaryDirectory() as t:
            dest = Path(t) / "x.exe"
            vu = []
            ollama_client.telecharger_fichier("https://exemple.org/x.exe", dest, lambda *a: vu.append(a), lambda r, timeout: Reponse(b"a" * 100), taille_min=10)
            self.assertEqual(dest.read_bytes(), b"a" * 100)
            self.assertEqual(vu[-1], ("téléchargement", 100, 100))
            dest2 = Path(t) / "y.exe"
            (Path(t) / "y.exe.part").write_bytes(b"a" * 40)
            requetes = []

            def ouvrir(req, timeout):
                requetes.append(req.headers.get("Range"))
                return Reponse(b"b" * 60, 206)
            ollama_client.telecharger_fichier("https://exemple.org/y.exe", dest2, ouvrir=ouvrir, taille_min=10)
            self.assertEqual(requetes, ["bytes=40-"])
            self.assertEqual(dest2.read_bytes(), b"a" * 40 + b"b" * 60)

    def test_signature(self):
        ok, _ = ollama_client.verifier_signature_windows("x.exe", lambda cmd, delai=0: "Valid|CN=Ollama Inc, O=Ollama")
        self.assertTrue(ok)
        for sortie in ("Valid|CN=Pirate", "NotSigned|", "HashMismatch|CN=Ollama", ""):
            self.assertFalse(ollama_client.verifier_signature_windows("x.exe", lambda cmd, delai=0, s=sortie: s)[0], sortie)

    def test_installation_windows_annulee_si_la_signature_est_mauvaise(self):
        with tempfile.TemporaryDirectory() as t:
            lance = []
            with self.assertRaises(ErreurOllama):
                ollama_client.installer_windows(t, ouvrir=lambda r, timeout: Reponse(b"x" * 100), lanceur_sortie=lambda c, d=0: "NotSigned|", executer=lambda *a, **k: lance.append(a), taille_min=10)
            self.assertEqual(lance, [], "l'installateur n'est jamais exécuté")
            self.assertFalse((Path(t) / "OllamaSetup.exe").exists(), "et il est supprimé")


# ---------------------------------------------------------------- mises à jour
def faux_http(routes):
    appels = []

    def http(url, entetes=None, delai=10):
        appels.append((url, entetes))
        for debut, rep in routes.items():
            if url.startswith(debut):
                if isinstance(rep, Exception):
                    raise rep
                return rep
        return 404, {}, b""
    http.appels = appels
    return http


class MisesAJour(unittest.TestCase):
    def test_separer(self):
        self.assertEqual(miseajour.separer("qwen3:8b"), ("library", "qwen3", "8b"))
        self.assertEqual(miseajour.separer("huihui_ai/Qwen3.8-abliterated:27b"), ("huihui_ai", "Qwen3.8-abliterated", "27b"))
        self.assertEqual(miseajour.separer("llama3"), ("library", "llama3", "latest"))

    def test_digest_registre(self):
        h = faux_http({miseajour.REGISTRE: (200, {"docker-content-digest": "sha256:abc"}, b"{}")})
        self.assertEqual(miseajour.digest_registre("qwen3:8b", h), "abc")
        self.assertIn("/library/qwen3/manifests/8b", h.appels[0][0])
        self.assertIsNone(miseajour.digest_registre("x", faux_http({})))
        self.assertIsNone(miseajour.digest_registre("x", faux_http({miseajour.REGISTRE: OSError("hors ligne")})))

    def test_detecte_une_mise_a_jour(self):
        h = faux_http({miseajour.REGISTRE: (200, {"docker-content-digest": "sha256:nouveau"}, b"")})
        p = miseajour.mises_a_jour({"qwen3:8b": {"digest": "ancien"}}, h)
        self.assertEqual([x["type"] for x in p], ["maj"])
        h = faux_http({miseajour.REGISTRE: (200, {"docker-content-digest": "sha256:ancien"}, b"")})
        self.assertEqual(miseajour.mises_a_jour({"qwen3:8b": {"digest": "ancien"}}, h), [], "même empreinte : rien à proposer")

    def test_nouveaute_quand_un_modele_mieux_note_tient(self):
        machine = Profil(ram_go=32, ram_libre_go=20, gpus=[Gpu("x", "nvidia", 24)])
        p = miseajour.nouveautes(machine, CAT, {"code": "qwen2.5-coder:7b"}, {"qwen2.5-coder:7b": {}})
        self.assertEqual(len(p), 1)
        self.assertEqual((p[0]["role"], p[0]["ancien"]), ("code", "qwen2.5-coder:7b"))
        self.assertGreater(CAT and [m for m in CAT["modeles"] if m["id"] == p[0]["modele"]][0]["notes"]["code"], 7)

    def test_pas_de_proposition_si_deja_au_meilleur_ignoree_ou_inutile(self):
        machine = Profil(ram_go=32, ram_libre_go=20, gpus=[Gpu("x", "nvidia", 24)])
        meilleur = __import__("lutin.selection", fromlist=["x"]).choisir(machine, CAT)["code"].id
        self.assertEqual(miseajour.nouveautes(machine, CAT, {"code": meilleur}, {meilleur: {}}), [])
        deja = miseajour.nouveautes(machine, CAT, {"code": "qwen2.5-coder:7b"}, {"qwen2.5-coder:7b": {}})[0]["cle"]
        self.assertEqual(miseajour.nouveautes(machine, CAT, {"code": "qwen2.5-coder:7b"}, {"qwen2.5-coder:7b": {}}, ignores=[deja]), [])
        self.assertEqual(miseajour.nouveautes(machine, CAT, {"code": "qwen2.5-coder:7b"}, {}), [], "le modèle n'est plus installé : on ne propose pas de le remplacer")

    def test_modele_qui_ne_tient_plus_est_signale(self):
        petite = Profil(ram_go=16, ram_libre_go=8, gpus=[Gpu("x", "nvidia", 8)])
        p = miseajour.nouveautes(petite, CAT, {"polyvalent": "llama3.3:70b"}, {"llama3.3:70b": {}})
        self.assertTrue(p and "ne tient plus" in p[0]["raison"])

    def test_telechargement_du_catalogue(self):
        with tempfile.TemporaryDirectory() as t:
            nouveau = copy.deepcopy(CAT)
            nouveau["version"] += 1
            corps = json.dumps(nouveau).encode()
            h = faux_http({"https://ex.org/c.json": (200, {"etag": "v2"}, corps)})
            self.assertEqual(miseajour.telecharger_catalogue("https://ex.org/c.json", t, h), "maj")
            self.assertEqual(catalogue.charger(Path(t) / "catalogue.json")["version"], CAT["version"] + 1)
            h2 = faux_http({"https://ex.org/c.json": (304, {}, b"")})
            self.assertEqual(miseajour.telecharger_catalogue("https://ex.org/c.json", t, h2), "inchange")
            self.assertEqual(h2.appels[0][1].get("If-None-Match"), "v2")
            self.assertEqual(miseajour.telecharger_catalogue("", t, h), "absent")

    def test_catalogue_invalide_ou_reseau_absent_jamais_applique(self):
        with tempfile.TemporaryDirectory() as t:
            for rep in ((200, {}, b"{pas du json"), (200, {}, b'{"version":1,"modeles":[{}]}'), (500, {}, b""), (200, {}, b"x" * (miseajour.TAILLE_MAX + 1)), OSError("hors ligne")):
                self.assertEqual(miseajour.telecharger_catalogue("https://ex.org/c.json", t, faux_http({"https://ex.org/c.json": rep})), "echec")
            self.assertFalse((Path(t) / "catalogue.json").exists())

    def test_verification_complete_limitee_a_une_fois_par_jour_et_sure_hors_ligne(self):
        with tempfile.TemporaryDirectory() as t:
            d = {"cache": Path(t)}
            machine = Profil(ram_go=32, ram_libre_go=20, gpus=[Gpu("x", "nvidia", 24)])
            cfg = {"modeles": {"choisis": {"code": "qwen2.5-coder:7b"}, "ignores": []}, "catalogue_url": ""}
            INSTALLES.clear(); INSTALLES.update({"qwen2.5-coder:7b": "d1"})
            hors_ligne = faux_http({"https://": OSError("hors ligne")})
            r = miseajour.verifier(machine, cfg, d, OLLAMA, hors_ligne, maintenant=lambda: 1000.0)
            self.assertEqual([p["type"] for p in r["propositions"]], ["nouveau"], "le catalogue livré suffit même sans réseau")
            appels = len(hors_ligne.appels)
            miseajour.verifier(machine, cfg, d, OLLAMA, hors_ligne, maintenant=lambda: 2000.0)
            self.assertEqual(len(hors_ligne.appels), appels, "pas de nouvelle vérification avant 24 h")
            miseajour.verifier(machine, cfg, d, OLLAMA, hors_ligne, maintenant=lambda: 1000.0 + miseajour.INTERVALLE_S + 1)
            self.assertGreater(len(hors_ligne.appels), appels)
            self.assertEqual(len(miseajour.lire_propositions(d)["propositions"]), 1)
            INSTALLES.clear(); INSTALLES.update({"qwen3:8b": "aaa111"})

    def test_ollama_arrete_ne_leve_pas_d_exception(self):
        with tempfile.TemporaryDirectory() as t:
            r = miseajour.verifier(Profil(ram_go=8), {"modeles": {}}, {"cache": Path(t)}, Ollama("http://127.0.0.1:9"), faux_http({}), force=True)
            self.assertEqual(r["propositions"], [])
            self.assertTrue(r["erreurs"])


class PublicationsGitHub(unittest.TestCase):
    CORPS = json.dumps({"tag_name": "v1.4.2", "assets": [{"name": "lutin-1.4.2.tar.gz", "browser_download_url": "https://x/lutin-1.4.2.tar.gz"},
                                                         {"name": "lutin-1.4.2-py3-none-any.whl", "browser_download_url": "https://x/lutin-1.4.2-py3-none-any.whl"}]}).encode()

    def test_derniere_publication(self):
        h = faux_http({"https://api.github.com/repos/Slater-proj/lutin/releases/latest": (200, {}, self.CORPS)})
        self.assertEqual(miseajour.derniere_release("Slater-proj/lutin", h), ("1.4.2", "https://x/lutin-1.4.2-py3-none-any.whl"))
        self.assertIn("application/vnd.github+json", h.appels[0][1]["Accept"])

    def test_pas_de_publication_reseau_absent_ou_reponse_cassee(self):
        for rep in ((404, {}, b""), (200, {}, b"{pas du json"), (200, {}, b'{"tag_name": "v1"}'), OSError("hors ligne")):
            r = miseajour.derniere_release("a/b", faux_http({"https://api.github.com": rep}))
            self.assertTrue(r == (None, None) or r[1] is None, rep)

    def test_comparaison_de_versions(self):
        self.assertEqual(miseajour.numeros("1.2.3rc4+x"), (1, 2, 3))
        self.assertEqual(miseajour.numeros("n'importe quoi"), ())
        self.assertTrue(miseajour.plus_recente("0.10.0", "0.9.9"), "comparaison numérique, pas alphabétique")
        self.assertTrue(miseajour.plus_recente("1.0.0", "0.0.0+source"))
        self.assertTrue(miseajour.plus_recente("1.0.0", "illisible"))
        self.assertFalse(miseajour.plus_recente("1.2.3", "1.2.3"))
        self.assertFalse(miseajour.plus_recente("1.2.2", "1.2.3"), "jamais de retour en arrière")
        self.assertFalse(miseajour.plus_recente("", "1.0.0"))
        self.assertFalse(miseajour.plus_recente(None, "1.0.0"))


class Portee(unittest.TestCase):
    """Boutons « chercher les mises à jour » / « chercher de nouveaux modèles » : chacun ne recalcule que sa moitié et garde l'autre."""

    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.d = {"cache": Path(self.t.name)}
        self.machine = Profil(ram_go=32, ram_libre_go=20, gpus=[Gpu("x", "nvidia", 24)])
        self.cfg = {"modeles": {"choisis": {"code": "qwen2.5-coder:7b"}, "ignores": []}, "catalogue_url": ""}
        INSTALLES.clear(); INSTALLES.update({"qwen2.5-coder:7b": "ancien"})
        self.http = faux_http({miseajour.REGISTRE: (200, {"docker-content-digest": "sha256:nouveau"}, b"")})

    def tearDown(self):
        INSTALLES.clear(); INSTALLES.update({"qwen3:8b": "aaa111"})
        self.t.cleanup()

    def test_chaque_portee_garde_l_autre_moitie(self):
        tout = miseajour.verifier(self.machine, self.cfg, self.d, OLLAMA, self.http, force=True)
        self.assertEqual(sorted(p["type"] for p in tout["propositions"]), ["maj", "nouveau"])
        INSTALLES["qwen2.5-coder:7b"] = "nouveau"                         # le modèle vient d'être mis à jour
        seulement_maj = miseajour.verifier(self.machine, self.cfg, self.d, OLLAMA, self.http, force=True, portee="maj")
        self.assertEqual([p["type"] for p in seulement_maj["propositions"]], ["nouveau"], "plus de mise à jour, mais la proposition de nouveau modèle est conservée")
        self.assertEqual(seulement_maj["portee"], "maj")
        seulement_nouveaux = miseajour.verifier(self.machine, self.cfg, self.d, OLLAMA, self.http, force=True, portee="nouveaux")
        self.assertEqual([p["type"] for p in seulement_nouveaux["propositions"]], ["nouveau"])

    def test_portee_maj_ne_touche_pas_au_catalogue_en_ligne(self):
        self.cfg["catalogue_url"] = "https://ex.org/c.json"
        miseajour.verifier(self.machine, self.cfg, self.d, OLLAMA, self.http, force=True, portee="maj")
        self.assertFalse([u for u, _ in self.http.appels if "ex.org" in u])
        r = miseajour.verifier(self.machine, self.cfg, self.d, OLLAMA, self.http, force=True, portee="nouveaux")
        self.assertTrue([u for u, _ in self.http.appels if "ex.org" in u])
        self.assertEqual(r["catalogue"], "echec", "adresse injoignable ici : signalé, copie locale utilisée")

    def test_catalogue_absent_est_signale(self):
        self.assertEqual(miseajour.verifier(self.machine, self.cfg, self.d, OLLAMA, self.http, force=True, portee="nouveaux")["catalogue"], "absent")

    def test_une_verification_manuelle_ne_decale_pas_la_verification_quotidienne(self):
        miseajour.verifier(self.machine, self.cfg, self.d, OLLAMA, self.http, force=True, portee="maj")
        self.assertFalse((self.d["cache"] / "derniere-verification.json").exists())
        miseajour.verifier(self.machine, self.cfg, self.d, OLLAMA, self.http, force=True)
        self.assertTrue((self.d["cache"] / "derniere-verification.json").exists())

    def test_portee_inconnue(self):
        with self.assertRaises(ValueError):
            miseajour.verifier(self.machine, self.cfg, self.d, OLLAMA, self.http, force=True, portee="n'importe quoi")

    def test_une_panne_garde_les_anciennes_propositions(self):
        miseajour.verifier(self.machine, self.cfg, self.d, OLLAMA, self.http, force=True)
        r = miseajour.verifier(self.machine, self.cfg, self.d, Ollama("http://127.0.0.1:9"), self.http, force=True)
        self.assertTrue(r["erreurs"])
        self.assertEqual(len(r["propositions"]), 2, "le réseau ou Ollama tombe : on n'efface pas ce qu'on savait")


if __name__ == "__main__":
    unittest.main()
