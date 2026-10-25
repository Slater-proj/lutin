import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401
from lutin import catalogue, chat_terminal, cli, client, config, installation, machine, ollama_client
from lutin.machine import Disque, Gpu, Profil

PULLS, INSTALLES = [], {}


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
            return self._json(200, {"models": [{"name": n, "digest": d} for n, d in INSTALLES.items()]})
        self._json(404, {})

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/pull":
            PULLS.append(corps["model"])
            INSTALLES[corps["model"]] = "d"
            self.send_response(200); self.end_headers()
            for e in ({"status": "pulling", "completed": 50, "total": 100}, {"status": "success"}):
                self.wfile.write((json.dumps(e) + "\n").encode()); self.wfile.flush()
            return
        self._json(404, {})


SERVEUR = ThreadingHTTPServer(("127.0.0.1", 0), Faux)
threading.Thread(target=SERVEUR.serve_forever, daemon=True).start()
os.environ["OLLAMA_URL"] = "http://127.0.0.1:%d" % SERVEUR.server_address[1]

DISQUE_LARGE = mock.Mock(free=800 * 1024 ** 3, total=1000 * 1024 ** 3, used=200 * 1024 ** 3)          # les tests ne dépendent pas de la place libre du PC qui les lance
GROS = Profil(systeme="linux", ram_go=32, ram_libre_go=20, gpus=[Gpu("RTX", "nvidia", 24)], disques=[Disque("/", 500, 1000)])


def es(reponses=None, oui=False):
    sortie, file = [], list(reponses or [])
    return installation.Es(entree=lambda q: (sortie.append(q), file.pop(0))[1], sortie=sortie.append, oui=oui), sortie


class Parcours(unittest.TestCase):
    def setUp(self):
        PULLS.clear(); INSTALLES.clear()
        self.t = tempfile.TemporaryDirectory()
        self.d = config.dossiers({"LUTIN_HOME": self.t.name})
        self.cfg = config.charger(self.d)
        self.travail = str(Path(self.t.name) / "travail")
        # Filet de sécurité : aucun test ne doit jamais lancer un vrai script d'installation.
        self.garde = mock.patch.object(installation, "_lancer", side_effect=AssertionError("un test a tenté d'exécuter une commande système"))
        self.garde.start()

    def tearDown(self):
        self.garde.stop()
        self.t.cleanup()

    def lancer(self, e, disque=DISQUE_LARGE, **options):
        options.setdefault("travail", self.travail)
        with mock.patch.object(installation, "definir_variables_utilisateur"), mock.patch.object(installation.shutil, "disk_usage", return_value=disque):
            return installation.executer(self.cfg, self.d, e, options, profil=GROS)

    def test_mode_automatique_installe_le_polyvalent_seulement(self):
        e, sortie = es(oui=True)
        cfg = self.lancer(e)
        self.assertEqual(len(PULLS), 1)
        self.assertEqual(cfg["modeles"]["choisis"], {"polyvalent": PULLS[0]})
        self.assertTrue(cfg["installe"])
        self.assertEqual(cfg["securite"]["niveau"], "local")
        self.assertTrue(Path(self.travail).is_dir())
        self.assertTrue(config.charger(self.d)["installe"], "la configuration est enregistrée")
        texte = "\n".join(map(str, sortie))
        self.assertIn("Ta machine", texte)
        self.assertIn("lutin chat", texte)

    def test_roles_choisis_partagent_un_meme_modele_sans_doublon(self):
        e, _ = es(oui=True)
        cfg = self.lancer(e, roles=["polyvalent", "code"])
        self.assertEqual(len(PULLS), len(set(PULLS)))
        self.assertEqual(set(cfg["modeles"]["choisis"]), {"polyvalent", "code"})

    def test_sans_modeles_ne_telecharge_rien(self):
        e, _ = es(oui=True)
        cfg = self.lancer(e, sans_modeles=True, sans_ollama=True)
        self.assertEqual(PULLS, [])
        self.assertTrue(cfg["installe"])

    def test_parcours_interactif_niveau_reseau_avec_avertissement(self):
        e, sortie = es(["2", "", ""])           # niveau 2 ; modèles conseillés (Entrée) ; télécharger (Entrée = oui)
        cfg = self.lancer(e)
        self.assertEqual(cfg["securite"]["niveau"], "reseau")
        self.assertIn("code PIN", "\n".join(map(str, sortie)))
        self.assertEqual(len(PULLS), 1)

    def test_aucun_modele_si_0(self):
        e, _ = es(["1", "0"])
        self.lancer(e)
        self.assertEqual(PULLS, [])

    def test_proxy_exige_url_et_adresse_et_confirmation(self):
        with self.assertRaises(ValueError):
            self.lancer(es(oui=True)[0], niveau="proxy")
        cfg = self.lancer(es(oui=True)[0], niveau="proxy", url="https://lutin.exemple.fr", proxy_ips=["192.168.1.10"], sans_modeles=True, sans_ollama=True)
        self.assertEqual((cfg["securite"]["niveau"], cfg["securite"]["url_publique"], cfg["securite"]["proxy_ips"]), ("proxy", "https://lutin.exemple.fr", ["192.168.1.10"]))

    def test_refuser_les_risques_ramene_au_niveau_local(self):
        e, sortie = es(["3", "https://lutin.exemple.fr", "192.168.1.10", "n", "0"])
        cfg = self.lancer(e)
        self.assertEqual(cfg["securite"]["niveau"], "local")
        self.assertIn("risqué", "\n".join(map(str, sortie)))

    def test_disque_trop_petit_ne_telecharge_rien(self):
        e, sortie = es(oui=True)
        self.lancer(e, disque=mock.Mock(free=1 * 1024 ** 3, total=10 * 1024 ** 3, used=0))
        self.assertEqual(PULLS, [])
        self.assertIn("Pas assez de place", "\n".join(map(str, sortie)))

    def test_ollama_absent_et_refus_d_installer(self):
        e, sortie = es(["1", "", "n"])           # niveau 1 ; télécharger : oui (Entrée) ; installer Ollama : non
        with mock.patch.object(ollama_client.Ollama, "actif", return_value=False), mock.patch.object(ollama_client, "trouver_executable", return_value=""):
            self.lancer(e, roles=["polyvalent"])
        self.assertEqual(PULLS, [])
        self.assertIn("ollama.com/download", "\n".join(map(str, sortie)))


class FauxClient:
    def __init__(self, evenements):
        self.evenements, self.envoyes, self.recus = evenements, [], []

    def flux(self, chemin, corps):
        self.recus.append(corps)
        for e in self.evenements:
            if e == "INTERRUPTION":
                raise KeyboardInterrupt
            yield e

    def envoyer(self, chemin, corps):
        self.envoyes.append((chemin, corps))
        return {}

    def obtenir(self, chemin):
        return {"conversations": [{"id": "c1", "titre": "Un"}, {"id": "c2", "titre": "Deux"}], "reglages": {"modele": "m"}}


def terminal(evenements, saisies=()):
    sortie = []
    file = list(saisies)
    t = chat_terminal.Terminal(FauxClient(evenements), entree=lambda q: file.pop(0), sortie=sortie.append, erreur=sortie.append)
    return t, sortie


class ChatTerminal(unittest.TestCase):
    def test_reponse_outil_et_fin(self):
        t, sortie = terminal([{"type": "debut", "conversation": "c9"}, {"type": "texte", "texte": "Bon"}, {"type": "texte", "texte": "jour"}, {"type": "outil", "nom": "lire", "args": {"chemin": "a"}},
                              {"type": "resultat", "texte": "ligne 1\nligne 2"}, {"type": "fin", "conversation": {"id": "c9", "titre": "T"}}])
        t.repondre("salut")
        texte = "".join(sortie)
        self.assertIn("Bonjour", texte)
        self.assertIn("⚙ lire", texte)
        self.assertIn("ligne 1 ligne 2", texte)
        self.assertEqual(t.conversation, "c9")
        t.repondre("suite")
        self.assertEqual(t.client.recus[-1]["conversation"], "c9", "la conversation continue")

    def test_accord_accepte_et_refuse(self):
        evt = [{"type": "approbation", "id": "a1", "titre": "Écrire x", "detail": "d", "diff": "+x"}]
        t, sortie = terminal(evt, ["o"])
        t.repondre("fais")
        self.assertIn(("/api/approuver", {"id": "a1", "ok": True}), t.client.envoyes)
        t, sortie = terminal(evt, [""])
        t.repondre("fais")
        self.assertIn(("/api/approuver", {"id": "a1", "ok": False}), t.client.envoyes, "par défaut : refusé")

    def test_ctrl_c_arrete_la_reponse(self):
        t, sortie = terminal([{"type": "debut", "conversation": "c3"}, "INTERRUPTION"])
        t.repondre("long")
        self.assertIn(("/api/arreter", {"conversation": "c3"}), t.client.envoyes)
        self.assertIn("arrêté", "".join(sortie))

    def test_erreur_du_serveur_est_affichee_sans_planter(self):
        class Casse(FauxClient):
            def flux(self, chemin, corps):
                raise client.ErreurClient("Lutin ne répond pas")
                yield
        sortie = []
        t = chat_terminal.Terminal(Casse([]), entree=lambda q: "", sortie=sortie.append, erreur=sortie.append)
        t.repondre("a")
        self.assertIn("ne répond pas", "".join(sortie))

    def test_commandes(self):
        t, sortie = terminal([], ["/liste", "/reprendre 2", "/mode ecriture", "/reflexion", "/nouvelle", "/inconnue", "/quitter"])
        self.assertEqual(t.boucle(), 0)
        self.assertEqual(t.options, {"mode": "scenario", "reflexion": True})
        texte = "".join(sortie)
        self.assertIn("1. Un", texte)
        self.assertIn("Conversation reprise : Deux", texte)
        self.assertIn("Commande inconnue", texte)
        self.assertEqual(t.conversation, "", "/nouvelle remet à zéro")

    def test_ctrl_d_quitte(self):
        sortie = []
        t = chat_terminal.Terminal(FauxClient([]), entree=mock.Mock(side_effect=EOFError), sortie=sortie.append)
        self.assertEqual(t.boucle(), 0)


class Cli(unittest.TestCase):
    def setUp(self):
        PULLS.clear(); INSTALLES.clear()
        self.t = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"LUTIN_HOME": self.t.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def lancer(self, *argv):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            code = cli.principal(list(argv))
        return code, sortie.getvalue()

    def test_aide_et_version(self):
        with self.assertRaises(SystemExit) as e, contextlib.redirect_stdout(io.StringIO()):
            cli.parseur().parse_args(["--version"])
        self.assertEqual(e.exception.code, 0)
        p = cli.parseur().parse_args(["setup", "--oui", "--niveau", "proxy", "--proxy-ip", "1.2.3.4", "--proxy-ip", "5.6.7.8", "--roles", "code,rapide"])
        self.assertEqual((p.niveau, p.proxy_ips, p.roles), ("proxy", ["1.2.3.4", "5.6.7.8"], "code,rapide"))
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.parseur().parse_args(["setup", "--niveau", "ouvert"])

    def test_setup_automatique_de_bout_en_bout(self):
        with mock.patch.object(machine, "detecter", return_value=GROS), mock.patch.object(installation, "definir_variables_utilisateur"),                 mock.patch.object(installation.shutil, "disk_usage", return_value=DISQUE_LARGE):
            code, sortie = self.lancer("setup", "--oui", "--travail", str(Path(self.t.name) / "w"))
        self.assertEqual(code, 0, sortie)
        d = config.dossiers()
        self.assertTrue(config.charger(d)["installe"])
        self.assertEqual(len(PULLS), 1)

    def test_setup_proxy_invalide_est_refuse_proprement(self):
        with mock.patch.object(machine, "detecter", return_value=GROS):
            code, sortie = self.lancer("setup", "--oui", "--niveau", "proxy", "--sans-modeles", "--sans-ollama", "--travail", str(Path(self.t.name) / "w"))
        self.assertEqual(code, 2)
        self.assertIn("adresse publique", sortie)
        self.assertFalse(config.charger(config.dossiers())["installe"], "rien n'est enregistré")

    def test_securite_affiche_le_niveau(self):
        code, sortie = self.lancer("securite")
        self.assertEqual(code, 0)
        self.assertIn("cette machine seulement", sortie)

    def test_modeles_recommander_et_lister(self):
        with mock.patch.object(machine, "detecter", return_value=GROS):
            code, sortie = self.lancer("modeles")
            self.assertEqual(code, 0)
            self.assertIn("Polyvalent", sortie)
            INSTALLES["qwen3:8b"] = "d"
            code, sortie = self.lancer("modeles", "lister")
        self.assertIn("installé", sortie)
        self.assertIn("qwen3:8b", sortie)

    def test_modeles_installer_et_supprimer_demandent_un_nom(self):
        self.assertEqual(self.lancer("modeles", "installer")[0], 2)
        code, sortie = self.lancer("modeles", "installer", "qwen3:4b")
        self.assertEqual((code, PULLS), (0, ["qwen3:4b"]))

    def test_modele_avance_affiche_son_avertissement(self):
        code, sortie = self.lancer("modeles", "installer", "huihui_ai/Qwen3.8-abliterated:27b")
        self.assertIn("⚠", sortie)

    def test_chat_sans_serveur_explique_quoi_faire(self):
        code, sortie = self.lancer("chat", "bonjour")
        self.assertEqual(code, 1)
        self.assertIn("lutin serve", sortie)

    def test_diagnostic(self):
        cfg = config.charger(config.dossiers())
        lignes = cli.diagnostic(cfg, {}, GROS, ollama_client.Ollama())
        textes = " | ".join(t for _, t in lignes)
        self.assertIn("Ollama 0.12.0 répond", textes)
        self.assertIn("Installation guidée : à faire", textes)
        hors = cli.diagnostic(cfg, {}, GROS, ollama_client.Ollama("http://127.0.0.1:9"))
        self.assertIn("erreur", [n for n, _ in hors])
        self.assertNotIn("conversation", textes.lower().replace("installation guidée", ""), "aucun contenu personnel")


class Console(unittest.TestCase):
    def test_fichier_console_absent_ou_abime(self):
        with tempfile.TemporaryDirectory() as t:
            c = client.ClientLocal(t)
            self.assertFalse(c.disponible())
            (Path(t) / "console.json").write_text("{pas du json", encoding="utf-8")
            self.assertFalse(c.disponible())
            with self.assertRaises(client.ErreurClient):
                c.obtenir("/api/etat")


class DejaInstalle(unittest.TestCase):
    """Lutin déjà installé : on ne change rien. Seule une demande explicite reconfigure, et ce qui est déjà téléchargé n'est jamais retéléchargé."""

    def setUp(self):
        PULLS.clear(); INSTALLES.clear()
        self.t = tempfile.TemporaryDirectory()
        self.d = config.dossiers({"LUTIN_HOME": self.t.name})
        self.cfg = config.charger(self.d)
        self.cfg.update(installe=True)
        self.cfg["modeles"]["choisis"] = {"polyvalent": "qwen3:8b"}
        self.cfg["emplacements"]["travail"] = str(Path(self.t.name) / "w")
        config.enregistrer(self.d, self.cfg)
        self.garde = mock.patch.object(installation, "_lancer", side_effect=AssertionError("commande système interdite en test"))
        self.garde.start()

    def tearDown(self):
        self.garde.stop()
        self.t.cleanup()

    def lancer(self, e, **options):
        with mock.patch.object(installation, "definir_variables_utilisateur"), mock.patch.object(installation.shutil, "disk_usage", return_value=DISQUE_LARGE):
            return installation.executer(config.charger(self.d), self.d, e, options, profil=GROS)

    def test_ne_change_rien(self):
        INSTALLES["qwen3:8b"] = "d"
        avant = (self.d["config"] / "config.json").read_bytes()
        e, sortie = es(oui=True)
        self.lancer(e)
        texte = "\n".join(map(str, sortie))
        self.assertIn("déjà installé : rien à faire", texte)
        self.assertEqual(PULLS, [])
        self.assertEqual((self.d["config"] / "config.json").read_bytes(), avant, "le fichier de configuration n'est même pas réécrit")
        self.assertNotIn("Ta machine", texte, "aucun parcours guidé")

    def test_modele_disparu_signale_et_retelecharge_seulement_sur_demande(self):
        e, sortie = es(oui=True)                       # mode automatique : ne retélécharge pas sans qu'on le demande
        self.lancer(e)
        self.assertEqual(PULLS, [])
        self.assertIn("n'est plus installé", "\n".join(map(str, sortie)))
        e, _ = es(["o"])
        self.lancer(e)
        self.assertEqual(PULLS, ["qwen3:8b"])

    def test_ollama_arrete_ne_casse_rien(self):
        e, sortie = es(oui=True)
        with mock.patch.object(ollama_client.Ollama, "installes", side_effect=ollama_client.ErreurOllama("arrêté")):
            self.lancer(e)
        self.assertIn("rien à faire", "\n".join(map(str, sortie)))

    def test_une_option_de_changement_reconfigure(self):
        INSTALLES["qwen3:8b"] = "d"
        e, sortie = es(oui=True)
        cfg = self.lancer(e, niveau="reseau", sans_modeles=True, sans_ollama=True, travail=str(Path(self.t.name) / "autre"))
        self.assertEqual(cfg["securite"]["niveau"], "reseau")
        self.assertEqual(config.charger(self.d)["securite"]["niveau"], "reseau")

    def test_reconfigurer_ne_retelecharge_pas_ce_qui_est_deja_la(self):
        profil = GROS
        from lutin import selection
        choix = selection.choisir(profil, catalogue.charger())
        INSTALLES[choix["polyvalent"].id] = "d"
        e, sortie = es(oui=True)
        cfg = self.lancer(e, reconfigurer=True, travail=str(Path(self.t.name) / "w"))
        self.assertEqual(PULLS, [], "le modèle conseillé est déjà installé")
        self.assertEqual(cfg["modeles"]["choisis"]["polyvalent"], choix["polyvalent"].id)


class Superviseur(unittest.TestCase):
    def lancer(self, codes, maximum=5):
        journal, horloge = [], [0.0]
        suite = iter(codes)

        def lancer(premiere):
            journal.append(premiere)
            horloge[0] += 10
            return next(suite)
        sortie = []
        code = cli.superviser(lancer, attendre=lambda s: None, horloge=lambda: horloge[0], maximum=maximum, ecrire=sortie.append)
        return code, journal, sortie

    def test_arret_volontaire_pas_de_relance(self):
        for voulu in (0, 130, 3221225786):
            code, journal, _ = self.lancer([voulu])
            self.assertEqual((code, journal), (0, [True]), voulu)

    def test_panne_puis_arret_propre(self):
        code, journal, sortie = self.lancer([1, 1, 0])
        self.assertEqual(code, 0)
        self.assertEqual(journal, [True, False, False], "le navigateur ne s'ouvre qu'au premier démarrage")
        self.assertTrue(any("Relance" in s for s in sortie))

    def test_boucle_de_pannes_est_stoppee(self):
        code, journal, sortie = self.lancer([1] * 20, maximum=3)
        self.assertEqual(code, 1)
        self.assertEqual(len(journal), 4)
        self.assertIn("je n'insiste pas", sortie[-1])

    def test_pannes_espacees_ne_comptent_pas_ensemble(self):
        journal, horloge, suite = [], [0.0], iter([1, 1, 1, 1, 0])

        def lancer(premiere):
            journal.append(1)
            horloge[0] += 700          # plus de 10 minutes entre deux pannes
            return next(suite)
        self.assertEqual(cli.superviser(lancer, attendre=lambda s: None, horloge=lambda: horloge[0], maximum=1, fenetre=600, ecrire=lambda s: None), 0)
        self.assertEqual(len(journal), 5)


class Update(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"LUTIN_HOME": self.t.name}, clear=False)
        self.env.start()
        os.environ.pop("LUTIN_SOURCE", None)

    def tearDown(self):
        self.env.stop()
        self.t.cleanup()

    def lancer(self, *argv):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            code = cli.principal(list(argv))
        return code, sortie.getvalue()

    def test_sans_source_connue_explique_quoi_faire_sans_rien_changer(self):
        faux = mock.MagicMock()                       # le module « subprocess » vu par cli est remplacé : le vrai (partagé avec les autres threads) n'est jamais touché
        faux.run.side_effect = AssertionError("pas de pip sans source")
        with mock.patch.object(config, "lire_source", return_value=""), mock.patch.object(cli, "subprocess", faux):
            code, sortie = self.lancer("update", "--app")
        self.assertEqual(code, 0)
        self.assertIn("ne sait pas d'où", sortie)

    def test_deja_a_jour(self):
        faux = mock.MagicMock()
        faux.run.return_value = mock.Mock(returncode=0, stdout="Lutin " + cli.__version__ + "\n")
        with mock.patch.object(config, "lire_source", return_value="git+https://exemple/lutin"), mock.patch.object(cli, "subprocess", faux):
            code, sortie = self.lancer("update", "--app")
        self.assertEqual(code, 0)
        self.assertIn("déjà à jour", sortie)
        self.assertEqual(faux.run.call_args_list[0].args[0][-1], "git+https://exemple/lutin")

    def test_mise_a_jour_et_echec_de_pip(self):
        faux = mock.MagicMock()
        faux.run.return_value = mock.Mock(returncode=0, stdout="Lutin 9.9.9\n")
        with mock.patch.object(config, "lire_source", return_value="x"), mock.patch.object(cli, "subprocess", faux):
            self.assertIn("→ 9.9.9", self.lancer("update", "--app")[1])
        faux.run.return_value = mock.Mock(returncode=1, stdout="")
        with mock.patch.object(config, "lire_source", return_value="x"), mock.patch.object(cli, "subprocess", faux):
            code, sortie = self.lancer("update", "--app")
        self.assertEqual(code, 1)
        self.assertIn("a échoué", sortie)

    def test_source_lue_dans_l_environnement_ou_le_fichier(self):
        self.assertEqual(config.lire_source({"LUTIN_SOURCE": " abc "}), "abc")
        with tempfile.TemporaryDirectory() as t:
            venv = Path(t) / "venv"
            venv.mkdir()
            (Path(t) / "source.txt").write_text("depuis-fichier\n", encoding="utf-8")
            with mock.patch.object(config.sys, "prefix", str(venv)):
                self.assertEqual(config.lire_source({}), "depuis-fichier")
            (Path(t) / "source.txt").unlink()
            with mock.patch.object(config.sys, "prefix", str(venv)):
                self.assertEqual(config.lire_source({}), "", "pas de fichier : source inconnue, sans erreur")


if __name__ == "__main__":
    unittest.main()
