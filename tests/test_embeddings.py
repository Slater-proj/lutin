"""La recherche par le sens (facultative) : retrouve un passage sans mot commun, retombe sur les mots si le modèle manque, garde ses vecteurs, s'installe en arrière-plan."""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-sens-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import embeddings, rappel  # noqa: E402
from lutin import moteur as _m  # noqa: E402

# des « familles de sens » : les mots d'une même famille donnent le même vecteur, sans aucun mot commun nécessaire
FAMILLES = [("prison", "détention", "cellule", "incarcération"), ("musique", "guitare", "concert"), ("cuisine", "recette", "four")]
MODE, APPELS, PULL = {"v": "ok"}, [], []


def vecteur(texte):
    t = texte.lower()
    return [float(sum(mot in t for mot in famille)) + 0.01 for famille in FAMILLES]


class FauxOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
        if self.path == "/api/embed":
            APPELS.append(corps["input"])
            if MODE["v"] == "absent":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error": "model not found"}')
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"embeddings": [vecteur(t) for t in corps["input"]]}).encode("utf-8"))
        elif self.path == "/api/pull":
            PULL.append(corps)
            self.send_response(200)
            self.end_headers()
            for fait in (100, 400, 1000):
                self.wfile.write((json.dumps({"status": "pulling", "total": 1000, "completed": fait}) + "\n").encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b'{"status": "success"}\n')


class Sens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur = ThreadingHTTPServer(("127.0.0.1", 0), FauxOllama)
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()
        cls.vrai_ollama, _m.OLLAMA = _m.OLLAMA, "http://127.0.0.1:%d" % cls.serveur.server_address[1]
        cls.vrais_reglages = _m.reglages
        cls.sens = {"recherche_sens": True, "modele_embeddings": "nomic-embed-text"}
        _m.reglages = lambda: dict(cls.vrais_reglages(), **cls.sens)

    @classmethod
    def tearDownClass(cls):
        _m.OLLAMA, _m.reglages = cls.vrai_ollama, cls.vrais_reglages
        cls.serveur.shutdown()

    def setUp(self):
        MODE["v"] = "ok"
        APPELS.clear()
        PULL.clear()
        embeddings.ECHEC.update(jusqua=0.0, vu=False)
        self.sens["recherche_sens"] = True
        c = _m.conv_nouvelle()
        bourrage = " Voici un long développement quelconque, sans rapport avec le reste." * 12      # chaque sujet fait son propre morceau (environ 800 caractères)
        c["messages"] = [
            {"role": "user", "content": "Parle-moi de la prison de brume et de ses cellules. La détention y dure des années, personne ne quitte les lieux avant la fin de sa peine." + bourrage},
            {"role": "user", "content": "Et pour la guitare de Rémi ? Il joue un concert ce soir, c'est sa seule sortie." + bourrage},
            {"role": "user", "content": "Quelle recette pour le dîner ? Un plat au four avec des légumes." + bourrage},
        ]
        _m.conv_ecrire(c)
        self.ident = c["id"]
        rappel.FIL.clear()

    def test_un_passage_sans_mot_commun_est_retrouve_par_le_sens(self):
        passages = rappel.passages_du_fil(self.ident, "Durée d une incarcération ?", 1)
        self.assertTrue(passages and "détention" in passages[0]["m"]["texte"], passages)
        self.sens["recherche_sens"] = False                                     # sans le sens, aucun mot utile en commun avec « personne ne sort »
        sans = rappel.passages_du_fil(self.ident, "Durée d une incarcération ?", 1)
        self.assertFalse(sans and "détention" in sans[0]["m"]["texte"])

    def test_les_vecteurs_sont_gardes_sur_le_disque_et_pas_recalcules(self):
        rappel.passages_du_fil(self.ident, "détention", 1)
        premiers = sum(len(a) for a in APPELS)
        self.assertEqual(premiers, 1 + len(rappel.morceaux_du_fil(self.ident)[0]))      # la question + chaque passage, une fois
        self.assertTrue(embeddings._chemin(self.ident).exists())
        APPELS.clear()
        rappel.FIL.clear()
        rappel.passages_du_fil(self.ident, "concert", 1)
        self.assertEqual(sum(len(a) for a in APPELS), 1)                        # seule la question est vectorisée
        embeddings.supprimer(self.ident)
        self.assertFalse(embeddings._chemin(self.ident).exists())

    def test_sans_le_modele_on_retombe_sur_les_mots_sans_erreur_et_sans_insister(self):
        MODE["v"] = "absent"
        passages = rappel.passages_du_fil(self.ident, "guitare", 1)
        self.assertTrue(passages and "guitare" in passages[0]["m"]["texte"].lower())
        n = len(APPELS)
        rappel.passages_du_fil(self.ident, "guitare", 1)
        self.assertEqual(len(APPELS), n, "pas de nouvelle tentative pendant la pause")

    def test_coupee_elle_ne_contacte_pas_ollama(self):
        self.sens["recherche_sens"] = False
        rappel.passages_du_fil(self.ident, "prison", 1)
        self.assertEqual(APPELS, [])

    def test_le_budget_de_temps_borne_la_vectorisation(self):
        self.assertEqual(embeddings.similarites(self.ident, rappel.morceaux_du_fil(self.ident)[0], "prison", budget=-1).__class__, dict)
        self.assertFalse(embeddings._chemin(self.ident).exists(), "budget épuisé : rien n'a été vectorisé")

    def test_les_vecteurs_d_un_autre_modele_ne_sont_pas_utilises(self):
        rappel.passages_du_fil(self.ident, "prison", 1)
        self.sens["modele_embeddings"] = "autre-modele"
        try:
            self.assertEqual(embeddings._charger(self.ident, "autre-modele"), {})
        finally:
            self.sens["modele_embeddings"] = "nomic-embed-text"

    def test_nettoyage_des_orphelins(self):
        rappel.passages_du_fil(self.ident, "prison", 1)
        (embeddings._chemin("zzzzzzzz")).write_text("{}", encoding="utf-8")
        embeddings.nettoyer_orphelins({self.ident})
        self.assertTrue(embeddings._chemin(self.ident).exists())
        self.assertFalse(embeddings._chemin("zzzzzzzz").exists())

    def test_l_installation_telecharge_en_arriere_plan_avec_sa_progression(self):
        embeddings.INSTALLATION.update(etat="", fait=0, total=0, erreur="")
        embeddings.demarrer_installation()
        for _ in range(100):
            if embeddings.INSTALLATION["etat"] != "en cours":
                break
            time.sleep(0.05)
        self.assertEqual(embeddings.INSTALLATION["etat"], "fini", embeddings.INSTALLATION)
        self.assertEqual(embeddings.INSTALLATION["fait"], 1000)
        self.assertEqual(PULL[0]["model"], "nomic-embed-text")


if __name__ == "__main__":
    unittest.main()
