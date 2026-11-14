"""L'addon VoiceStudio : vérification, voix, lecture à voix haute avec accord, transcription, clonage avec déclaration d'autorisation, clé d'API, garde-fous. Contre un FAUX VoiceStudio
(l'application réelle n'est pas lancée par les tests : voir docs/TRIALS)."""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-voix-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "LUTIN_WEB_LOCAL": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import addons, addons_voicestudio as vs  # noqa: E402
from lutin import core as _m  # noqa: E402
from lutin import change_review  # noqa: E402

AUDIO = b"RIFF" + b"\x00" * 400
SERVICE = {}


class FauxVoiceStudio(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _rep(self, code, corps, type_="application/json"):
        d = corps if isinstance(corps, bytes) else json.dumps(corps).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(d)))
        self.end_headers()
        self.wfile.write(d)

    def _corps(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def _entree(self, corps=b""):
        SERVICE["appels"].append({"methode": self.command, "chemin": self.path, "corps": corps, "auth": self.headers.get("Authorization", ""), "type": self.headers.get("Content-Type", "")})
        if SERVICE.get("cle") and self.headers.get("Authorization") != "Bearer " + SERVICE["cle"]:
            self._rep(401, {"detail": "API key required"})
            return False
        return True

    def do_GET(self):
        if not self._entree():
            return
        if self.path == "/v1/audio/voices":
            voix = [{"voice_id": "p1", "id": "p1", "name": "Narrateur", "type": "profile", "language": "fr"}, {"voice_id": "p2", "id": "p2", "name": "Anna", "type": "profile", "language": "en"}]
            return self._rep(200, {"data": voix} if SERVICE.get("enveloppe") else voix)
        self._rep(404, {"detail": "nope"})

    def do_POST(self):
        corps = self._corps()
        if not self._entree(corps):
            return
        if self.path == "/v1/audio/speech":
            if SERVICE.get("erreur_deguisee"):
                return self._rep(200, {"error": {"message": "moteur non chargé"}})
            if SERVICE.get("refus"):
                return self._rep(400, {"error": {"message": "voix inconnue", "type": "invalid_request_error"}})
            return self._rep(200, AUDIO, "audio/wav")
        if self.path == "/v1/audio/transcriptions":
            return self._rep(200, {"text": SERVICE.get("texte", "bonjour tout le monde")})
        if self.path == "/profiles":
            return self._rep(200, {"id": "nouveau1", "name": "x"})
        if self.path.endswith("/attestation"):
            return self._rep(500 if SERVICE.get("attestation_en_panne") else 200, {"ok": True})
        self._rep(404, {"detail": "nope"})


class VoiceStudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serveur = ThreadingHTTPServer(("127.0.0.1", 0), FauxVoiceStudio)
        cls.port = cls.serveur.server_address[1]
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.serveur.shutdown()

    def setUp(self):
        SERVICE.clear()
        SERVICE["appels"] = []
        for f in addons.dossier_donnees().rglob("*"):
            if f.is_file():
                f.unlink()
        addons.enregistrer_reglages(vs.IDENT, {"port": str(self.port), "cle": "", "format": "wav"})
        addons.activer(vs.IDENT, True)
        self.projet = _m.RACINE
        (self.projet / "voix.wav").write_bytes(b"RIFFxxxx")

    def ctx(self, accord=True, **plus):
        self.accords = []
        return dict({"accord": lambda t, d, df, auto=False: (self.accords.append((t, d, auto)), accord)[1]}, **plus)

    # --- activation et vérification
    def test_verification_compte_les_voix_et_l_activation_exige_un_service_qui_repond(self):
        v = addons.verifier(vs.IDENT)
        self.assertTrue(v["ok"], v)
        self.assertIn("2 voix", v["etapes"][0]["message"])
        addons.activer(vs.IDENT, False)
        addons.enregistrer_reglages(vs.IDENT, {"port": "1"})
        with self.assertRaises(addons.ErreurAddon) as e:
            addons.activer(vs.IDENT, True)
        self.assertIn("ne répond pas", str(e.exception))
        self.assertFalse(addons.actif(vs.IDENT))

    def test_port_invalide(self):
        addons.enregistrer_reglages(vs.IDENT, {"port": "abc"})
        with self.assertRaises(_m.ErreurOutil):
            vs.liste_voix()

    def test_les_deux_formes_de_liste_de_voix(self):
        for enveloppe in (False, True):
            SERVICE["enveloppe"] = enveloppe
            self.assertEqual([v["nom"] for v in vs.liste_voix()], ["Narrateur", "Anna"])
        self.assertIn("Narrateur (id : p1) · fr", vs.texte_voix())

    def test_outils_inutilisables_si_l_addon_est_coupe(self):
        addons.activer(vs.IDENT, False)
        for nom in ("voix_liste", "voix_parler", "voix_transcrire", "voix_cloner"):
            with self.assertRaises(_m.ErreurOutil, msg=nom):
                change_review._appeler_outil(nom, {"texte": "x"}, self.ctx())

    # --- lire à voix haute
    def test_parler_demande_l_accord_cree_le_fichier_et_le_joint(self):
        ctx = self.ctx()
        res = change_review._appeler_outil("voix_parler", {"texte": "Bonjour à tous", "voix": "Narrateur", "vitesse": 1.5, "langue": "fr"}, ctx)
        self.assertIn("Audio créé", res)
        self.assertEqual(len(self.accords), 1)
        self.assertFalse(self.accords[0][2], "pas d'accord automatique sans la case")
        envoi = next(a for a in SERVICE["appels"] if a["chemin"] == "/v1/audio/speech")
        corps = json.loads(envoi["corps"])
        self.assertEqual((corps["input"], corps["voice"], corps["response_format"], corps["speed"], corps["language"]), ("Bonjour à tous", "Narrateur", "wav", 1.5, "fr"))
        fichier = Path(ctx["fichiers_joints"][0])
        self.assertEqual(fichier.read_bytes(), AUDIO)
        self.assertTrue(fichier.name.endswith(".wav") and "bonjour" in fichier.name)

    def test_parler_refus_rien_n_est_envoye(self):
        res = vs.outil_parler({"texte": "Salut"}, self.ctx(accord=False))
        self.assertIn("Refusé", res)
        self.assertEqual([a for a in SERVICE["appels"] if a["chemin"] == "/v1/audio/speech"], [])

    def test_parler_case_commandes_automatiques(self):
        vs.outil_parler({"texte": "Salut"}, self.ctx(auto_commandes=True))
        self.assertTrue(self.accords[0][2])

    def test_parler_garde_fous(self):
        for args in ({"texte": ""}, {"texte": "x" * 5000}, {"texte": "ok", "format": "exe"}):
            with self.assertRaises(_m.ErreurOutil, msg=str(args)[:30]):
                vs.outil_parler(args, self.ctx())
        self.assertEqual(self.accords, [])

    def test_parler_erreurs_du_service_sont_lisibles(self):
        SERVICE["refus"] = True
        with self.assertRaises(_m.ErreurOutil) as e:
            vs.outil_parler({"texte": "Salut", "voix": "inconnue"}, self.ctx())
        self.assertIn("voix inconnue", str(e.exception))
        SERVICE["refus"] = False
        SERVICE["erreur_deguisee"] = True
        with self.assertRaises(_m.ErreurOutil) as e:
            vs.outil_parler({"texte": "Salut"}, self.ctx())
        self.assertIn("moteur non chargé", str(e.exception), "une erreur en JSON n'est pas enregistrée comme un fichier audio")

    # --- clé d'API
    def test_cle_envoyee_et_jamais_affichee(self):
        SERVICE["cle"] = "secret-tres-long-1234"
        with self.assertRaises(_m.ErreurOutil) as e:
            vs.liste_voix()
        self.assertIn("clé API", str(e.exception))
        self.assertNotIn("secret-tres-long", str(e.exception))
        addons.enregistrer_reglages(vs.IDENT, {"cle": "secret-tres-long-1234"})
        self.assertEqual(len(vs.liste_voix()), 2)
        self.assertEqual(SERVICE["appels"][-1]["auth"], "Bearer secret-tres-long-1234")
        self.assertNotIn("secret-tres-long", json.dumps(addons.decrire(vs.IDENT), default=str), "la clé n'est jamais renvoyée à la page")

    # --- transcription
    def test_transcrire_envoie_le_fichier_en_multipart(self):
        res = vs.outil_transcrire({"chemin": "voix.wav", "langue": "fr"}, self.ctx())
        self.assertIn("bonjour tout le monde", res)
        envoi = next(a for a in SERVICE["appels"] if a["chemin"] == "/v1/audio/transcriptions")
        self.assertTrue(envoi["type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="file"; filename="voix.wav"', envoi["corps"])
        self.assertIn(b"RIFFxxxx", envoi["corps"])
        self.assertIn(b'name="language"\r\n\r\nfr', envoi["corps"])

    def test_transcrire_silence_et_refus_de_fichiers(self):
        SERVICE["texte"] = "  "
        self.assertIn("rien entendu", vs.outil_transcrire({"chemin": "voix.wav"}, self.ctx()))
        (self.projet / "notes.txt").write_text("x", encoding="utf-8")
        for chemin in ("notes.txt", "absent.wav", "", "../../etc/passwd.wav"):
            with self.assertRaises(_m.ErreurOutil, msg=chemin):
                vs.outil_transcrire({"chemin": chemin}, self.ctx())

    def test_transcrire_un_audio_genere_plus_tot(self):
        ctx = self.ctx()
        vs.outil_parler({"texte": "Salut"}, ctx)
        self.assertIn("bonjour", vs.outil_transcrire({"chemin": ctx["fichiers_joints"][0]}, self.ctx()))

    # --- clonage
    def test_cloner_exige_la_base_et_l_accord_meme_en_automatique(self):
        for args in ({"nom": "Moi", "chemin": "voix.wav"}, {"nom": "Moi", "chemin": "voix.wav", "base": "peut-etre"}, {"nom": "", "chemin": "voix.wav", "base": "ma_voix"}):
            with self.assertRaises(_m.ErreurOutil, msg=str(args)):
                vs.outil_cloner(args, self.ctx())
        self.assertEqual(self.accords, [])
        self.assertEqual([a for a in SERVICE["appels"] if a["chemin"] == "/profiles"], [])
        ctx = self.ctx(accord=False, auto_commandes=True, auto_ecriture=True)
        res = vs.outil_cloner({"nom": "Moi", "chemin": "voix.wav", "base": "ma_voix"}, ctx)
        self.assertIn("Refusé", res)
        self.assertFalse(self.accords[0][2], "l'accord automatique ne vaut jamais pour cloner une voix")
        self.assertIn("voix de l'utilisateur", self.accords[0][1])
        self.assertEqual([a for a in SERVICE["appels"] if a["chemin"] == "/profiles"], [])

    def test_cloner_cree_le_profil_et_transmet_la_declaration(self):
        res = vs.outil_cloner({"nom": "Ma voix", "chemin": "voix.wav", "base": "permission", "texte_reference": "Ceci est un test.", "langue": "fr"}, self.ctx())
        self.assertIn("nouveau1", res)
        self.assertIn("permission", self.accords[0][1].lower())
        envoi = next(a for a in SERVICE["appels"] if a["chemin"] == "/profiles")
        for attendu in (b'name="name"\r\n\r\nMa voix', b'name="kind"\r\n\r\nclone', b'name="ref_text"\r\n\r\nCeci est un test.', b'name="ref_audio"; filename="voix.wav"'):
            self.assertIn(attendu, envoi["corps"])
        attestation = next(a for a in SERVICE["appels"] if a["chemin"] == "/profiles/nouveau1/attestation")
        self.assertEqual(json.loads(attestation["corps"]), {"basis": "speaker_permission"})
        vs.outil_cloner({"nom": "Moi", "chemin": "voix.wav", "base": "ma_voix"}, self.ctx())
        dernier = [a for a in SERVICE["appels"] if a["chemin"].endswith("/attestation")][-1]
        self.assertEqual(json.loads(dernier["corps"]), {"basis": "own_voice"})

    def test_cloner_attestation_en_panne_est_signalee(self):
        SERVICE["attestation_en_panne"] = True
        res = vs.outil_cloner({"nom": "Moi", "chemin": "voix.wav", "base": "ma_voix"}, self.ctx())
        self.assertIn("nouveau1", res)
        self.assertIn("déclaration d'autorisation n'a pas pu", res)

    def test_cloner_enregistrement_trop_gros(self):
        gros = self.projet / "gros.wav"
        with open(gros, "wb") as f:
            f.truncate(vs.REF_MAX_OCTETS + 1)
        with self.assertRaises(_m.ErreurOutil):
            vs.outil_cloner({"nom": "Moi", "chemin": "gros.wav", "base": "ma_voix"}, self.ctx())

    def test_le_nom_du_fichier_ne_peut_pas_casser_l_envoi(self):
        (self.projet / "bi zarre'.wav").write_bytes(b"RIFFxxxx")
        vs.outil_transcrire({"chemin": "bi zarre'.wav"}, self.ctx())
        envoi = next(a for a in SERVICE["appels"] if a["chemin"] == "/v1/audio/transcriptions")
        self.assertIn(b'filename="bi_zarre_.wav"', envoi["corps"], "espaces et apostrophes remplacés : l'en-tête reste valide")


if __name__ == "__main__":
    unittest.main()
