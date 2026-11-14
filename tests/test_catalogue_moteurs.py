"""Catalogue des moteurs signé : vecteurs du RFC 8032, enveloppe signée, refus de tout catalogue modifié ou mal signé, copie livrée suffisante hors ligne, ajout d'un moteur par une simple ligne."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-catmoteurs-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import core as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import engine_catalog as cm  # noqa: E402
from lutin import ed25519  # noqa: E402

# Vecteurs de test du RFC 8032 (section 7.1) : graine, clé publique, message, signature.
VECTEURS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60", "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb", "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]

# Une graine et une clé publique propres au test : jamais les vraies clés.
GRAINE_TEST = bytes(range(32))
CLE_TEST = "test"


def minimal(**plus):
    base = {"version": 1, "date": "2026-01-01", "moteurs": [{"id": "demo", "nom": "Demo", "genre": "openai", "adresse_defaut": "http://127.0.0.1:9000/v1", "description": {"fr": "Un serveur de démonstration."}}]}
    base.update(plus)
    return base


class Ed25519(unittest.TestCase):
    def test_vecteurs_rfc_8032(self):
        for graine, publique, message, signature in VECTEURS:
            graine, publique, message, signature = (bytes.fromhex(x) for x in (graine, publique, message, signature))
            self.assertEqual(ed25519.cle_publique(graine), publique)
            self.assertEqual(ed25519.signer(graine, message), signature)
            self.assertTrue(ed25519.verifier(publique, message, signature))

    def test_refus_de_tout_ce_qui_est_modifie_ou_mal_forme(self):
        graine, publique, message, signature = (bytes.fromhex(x) for x in VECTEURS[1])
        self.assertFalse(ed25519.verifier(publique, message + b"x", signature))
        self.assertFalse(ed25519.verifier(publique, message, signature[:-1] + bytes([signature[-1] ^ 1])))
        self.assertFalse(ed25519.verifier(bytes.fromhex(VECTEURS[0][1]), message, signature))          # mauvaise clé
        for mauvais in (b"", b"\x00" * 64, signature[:63], signature + b"\x00", None, "texte"):
            self.assertFalse(ed25519.verifier(publique, message, mauvais))
        self.assertFalse(ed25519.verifier(b"\xff" * 32, message, signature))
        self.assertFalse(ed25519.verifier(publique[:31], message, signature))

    def test_signature_non_canonique_refusee(self):
        """s >= L : une signature « malléable » est refusée."""
        graine, publique, message, signature = (bytes.fromhex(x) for x in VECTEURS[0])
        s = int.from_bytes(signature[32:], "little") + ed25519.L
        if s < 2 ** 256:
            self.assertFalse(ed25519.verifier(publique, message, signature[:32] + s.to_bytes(32, "little")))


class Enveloppe(unittest.TestCase):
    def setUp(self):
        self.ancien = dict(cm.CLES_PUBLIQUES)
        cm.CLES_PUBLIQUES[CLE_TEST] = ed25519.cle_publique(GRAINE_TEST).hex()

    def tearDown(self):
        cm.CLES_PUBLIQUES.clear()
        cm.CLES_PUBLIQUES.update(self.ancien)

    def test_catalogue_bien_signe_accepte(self):
        e = cm.signer(minimal(), GRAINE_TEST, CLE_TEST)
        self.assertEqual(cm.verifier(json.loads(json.dumps(e)))["moteurs"][0]["id"], "demo")

    def test_une_virgule_modifiee_est_refusee(self):
        e = cm.signer(minimal(), GRAINE_TEST, CLE_TEST)
        e["catalogue"]["moteurs"][0]["adresse_defaut"] = "http://127.0.0.1:9001/v1"
        with self.assertRaisesRegex(cm.ErreurCatalogue, "signature invalide"):
            cm.verifier(e)

    def test_cle_inconnue_signature_absente_ou_illisible(self):
        e = cm.signer(minimal(), GRAINE_TEST, CLE_TEST)
        for abime in (dict(e, cle="inconnue"), dict(e, signature="!!pas du base64!!"), dict(e, signature=""), {k: v for k, v in e.items() if k != "signature"}, {"catalogue": minimal()}, [], None):
            with self.assertRaises(cm.ErreurCatalogue):
                cm.verifier(abime)

    def test_signe_par_une_autre_cle_refuse(self):
        e = cm.signer(minimal(), bytes([7]) * 32, CLE_TEST)          # la clé nommée n'est pas celle qui a signé
        with self.assertRaisesRegex(cm.ErreurCatalogue, "signature invalide"):
            cm.verifier(e)

    def test_le_schema_est_strict_meme_bien_signe(self):
        mauvais = [minimal(moteurs=[]), minimal(extra=1), minimal(version="1"), minimal(version=True)]
        for champ, valeur in (("genre", "ollama"), ("id", "Majuscule"), ("id", "ollama"), ("adresse_defaut", "ftp://x"), ("adresse_defaut", "http://a b"), ("site", "http://pas-https.example"), ("description", ""),
                              ("description", {"en": "sans français"}), ("description", {"fr": "x" * 500}), ("nom", ""), ("inconnu", 1), ("cle_requise", "oui"), ("plateformes", ["plan9"]), ("points_forts", "texte")):
            c = minimal()
            c["moteurs"][0][champ] = valeur
            mauvais.append(c)
        c = minimal()
        c["moteurs"].append(copy.deepcopy(c["moteurs"][0]))          # identifiant en double
        mauvais.append(c)
        for catalogue in mauvais:
            with self.assertRaises(cm.ErreurCatalogue, msg=str(catalogue)[:120]):
                cm.verifier(cm.signer(catalogue, GRAINE_TEST, CLE_TEST))


class Livre(unittest.TestCase):
    def test_le_catalogue_livre_est_valide_et_signe_par_une_cle_embarquee(self):
        c = cm.lire_fichier(cm.FICHIER_LIVRE)
        self.assertGreaterEqual(len(c["moteurs"]), 5)
        self.assertEqual(len(cm.CLES_PUBLIQUES), 2)          # deux clés pour pouvoir changer de clé sans casser les installations
        for m in c["moteurs"]:
            self.assertIn("fr", m["description"])
            self.assertIn("en", m["description"], m["id"] + " : description anglaise manquante")

    def test_la_copie_livree_est_celle_de_la_source(self):
        """Une source modifiée sans re-signature ferait mentir le fichier livré : tools/signer_catalogue_moteurs.py à relancer."""
        source = json.loads((Path(__file__).resolve().parent.parent / "tools" / "moteurs.source.json").read_text(encoding="utf-8"))
        self.assertEqual(cm.lire_fichier(cm.FICHIER_LIVRE), source)

    def test_vue_dans_la_langue_courante(self):
        os.environ["LUTIN_LANGUE"] = "en"
        try:
            v = {x["id"]: x for x in cm.prereglages()}
            self.assertIn("desktop app", v["lmstudio"]["description"].lower())
            os.environ["LUTIN_LANGUE"] = "fr"
            self.assertIn("bureau", {x["id"]: x for x in cm.prereglages()}["lmstudio"]["description"])
        finally:
            os.environ.pop("LUTIN_LANGUE", None)


class Lecture(unittest.TestCase):
    def setUp(self):
        self.ancien = dict(cm.CLES_PUBLIQUES)
        cm.CLES_PUBLIQUES[CLE_TEST] = ed25519.cle_publique(GRAINE_TEST).hex()
        self.dossier = Path(tempfile.mkdtemp(dir=_TEMP))

    def tearDown(self):
        cm.CLES_PUBLIQUES.clear()
        cm.CLES_PUBLIQUES.update(self.ancien)

    def _ecrire(self, nom, enveloppe):
        f = self.dossier / nom
        f.write_text(json.dumps(enveloppe), encoding="utf-8")
        return f

    def test_hors_ligne_le_catalogue_livre_suffit(self):
        self.assertEqual(cm.charger(self.dossier / "absent.json")["version"], cm.lire_fichier(cm.FICHIER_LIVRE)["version"])
        self.assertEqual(cm.charger(None)["version"], cm.lire_fichier(cm.FICHIER_LIVRE)["version"])

    def test_le_cache_en_ligne_plus_recent_et_bien_signe_est_pris(self):
        plus_recent = cm.signer(minimal(version=99, moteurs=minimal()["moteurs"]), GRAINE_TEST, CLE_TEST)
        self.assertEqual(cm.charger(self._ecrire("c.json", plus_recent))["version"], 99)

    def test_un_cache_falsifie_ou_ancien_est_ignore(self):
        livre = cm.lire_fichier(cm.FICHIER_LIVRE)["version"]
        e = cm.signer(minimal(version=99), GRAINE_TEST, CLE_TEST)
        e["catalogue"]["version"] = 100          # modifié après signature
        self.assertEqual(cm.charger(self._ecrire("f.json", e))["version"], livre)
        self.assertEqual(cm.charger(self._ecrire("v.json", cm.signer(minimal(version=0), GRAINE_TEST, CLE_TEST)))["version"], livre)          # plus ancien
        (self.dossier / "x.json").write_text("{pas du json", encoding="utf-8")
        self.assertEqual(cm.charger(self.dossier / "x.json")["version"], livre)

    def test_telechargement_ne_garde_que_le_valide(self):
        bon = json.dumps(cm.signer(minimal(version=50), GRAINE_TEST, CLE_TEST)).encode()
        falsifie = json.loads(bon)
        falsifie["catalogue"]["moteurs"][0]["nom"] = "Pirate"
        cache = self.dossier / "dl.json"
        self.assertEqual(cm.telecharger("https://x/m.json", cache, lambda u, h: (200, {}, json.dumps(falsifie).encode())), "echec")
        self.assertFalse(cache.exists())
        self.assertEqual(cm.telecharger("https://x/m.json", cache, lambda u, h: (200, {}, b"<html>")), "echec")
        self.assertEqual(cm.telecharger("https://x/m.json", cache, lambda u, h: (404, {}, b"")), "echec")
        self.assertEqual(cm.telecharger("https://x/m.json", cache, lambda u, h: (200, {}, b"x" * (cm.TAILLE_MAX + 1))), "echec")

        def coupe(u, h):
            raise OSError("pas de réseau")
        self.assertEqual(cm.telecharger("https://x/m.json", cache, coupe), "echec")
        self.assertEqual(cm.telecharger("", cache, coupe), "absent")
        self.assertEqual(cm.telecharger("https://x/m.json", cache, lambda u, h: (200, {}, bon)), "maj")
        self.assertEqual(cm.charger(cache)["version"], 50)

    def test_un_moteur_s_ajoute_par_une_ligne_sans_toucher_au_code(self):
        """Critère de la feuille de route : le moteur apparaît dans les préréglages, avec son adresse, uniquement parce qu'il est dans le catalogue."""
        c = copy.deepcopy(minimal(version=77))
        c["moteurs"].append({"id": "nouveau-moteur", "nom": "Nouveau moteur", "genre": "openai", "adresse_defaut": "http://127.0.0.1:5555/v1", "description": {"fr": "Un autre serveur."}})
        cache = self._ecrire("n.json", cm.signer(c, GRAINE_TEST, CLE_TEST))
        vus = {x["id"]: x for x in (cm.vue(m) for m in cm.charger(cache)["moteurs"])}
        self.assertEqual(vus["nouveau-moteur"]["adresse"], "http://127.0.0.1:5555/v1")
        self.assertEqual(vus["nouveau-moteur"]["description"], "Un autre serveur.")


class Page(unittest.TestCase):
    def test_l_api_donne_les_prereglages(self):
        from lutin import server
        liste = server.Gestionnaire._prereglages()
        self.assertIn("lmstudio", [p["id"] for p in liste])
        self.assertTrue(all(p["adresse"].startswith("http") or p["experimental"] for p in liste), "seuls les expérimentaux peuvent ne pas avoir d'adresse habituelle vérifiée")


if __name__ == "__main__":
    unittest.main()
