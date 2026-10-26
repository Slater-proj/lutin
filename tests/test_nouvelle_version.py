"""La nouvelle version de Lutin est annoncée sans rien installer : vérification espacée, silencieuse hors ligne, ignorable, vue par la page. (faux GitHub, serveur réel sur 127.0.0.1)"""
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-version-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9"}.items():
    os.environ.setdefault(cle, valeur)
os.environ["LUTIN_CONFIG"] = str(_TEMP / "config" / "config.json")
os.environ["LUTIN_VERSION_CACHE"] = str(_TEMP / "cache" / "lutin-version.json")
for d in ("projet", "donnees", "memoire", "config", "cache"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import horsligne, miseajour  # noqa: E402
from lutin import moteur as A  # noqa: E402

DOSSIERS = {"cache": str(_TEMP / "cache")}
SERVEUR = ThreadingHTTPServer(("127.0.0.1", 0), A.Gestionnaire)
threading.Thread(target=SERVEUR.serve_forever, daemon=True).start()
PORT = SERVEUR.server_address[1]


def faux_github(version, appels=None):
    def http(url, entetes=None, delai=10):
        if appels is not None:
            appels.append(url)
        corps = json.dumps({"tag_name": "v" + version, "assets": [{"name": "lutin-{}-py3-none-any.whl".format(version), "browser_download_url": "https://exemple/x.whl"}]}).encode()
        return 200, {}, corps
    return http


def requete(methode, chemin, corps=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    h = {"Host": "127.0.0.1:%d" % PORT, "X-Token": A.JETON}
    donnees = None
    if corps is not None:
        donnees = json.dumps(corps).encode("utf-8")
        h["Content-Type"] = "application/json"
    c.request(methode, chemin, body=donnees, headers=h)
    r = c.getresponse()
    texte = r.read().decode("utf-8", "replace")
    c.close()
    return r.status, json.loads(texte)


class Verification(unittest.TestCase):
    def setUp(self):
        miseajour.fichier_version(DOSSIERS).unlink(missing_ok=True)

    def test_une_version_plus_recente_est_annoncee_une_fois_par_jour(self):
        appels = []
        t = [1_700_000_000.0]
        d = miseajour.verifier_lutin(DOSSIERS, http=faux_github("0.5.0", appels), maintenant=lambda: t[0])
        self.assertEqual(d["version"], "0.5.0")
        t[0] += 3600
        miseajour.verifier_lutin(DOSSIERS, http=faux_github("0.6.0", appels), maintenant=lambda: t[0])
        self.assertEqual(len(appels), 1, "une seule requête par 24 h")
        self.assertEqual(miseajour.lire_fichier_version(miseajour.fichier_version(DOSSIERS))["version"], "0.5.0")
        t[0] += 24 * 3600
        miseajour.verifier_lutin(DOSSIERS, http=faux_github("0.6.0", appels), maintenant=lambda: t[0])
        self.assertEqual(len(appels), 2)

    def test_nouvelle_version_seulement_si_plus_recente_et_non_ignoree(self):
        chemin = miseajour.fichier_version(DOSSIERS)
        miseajour.verifier_lutin(DOSSIERS, http=faux_github("1.2.3"))
        n = miseajour.nouvelle_version(chemin, "1.2.0")
        self.assertEqual((n["version"], n["actuelle"], n["page"], n["commande"]), ("1.2.3", "1.2.0", "https://github.com/Slater-proj/lutin/releases/tag/v1.2.3", "lutin update"))
        self.assertIsNone(miseajour.nouvelle_version(chemin, "1.2.3"), "déjà à jour")
        self.assertIsNone(miseajour.nouvelle_version(chemin, "2.0.0"), "jamais de retour en arrière")
        self.assertIsNone(miseajour.nouvelle_version(chemin, "1.2.3rc4+branche"), "une candidate de la même version n'est pas « en retard »")
        miseajour.ignorer_version(chemin, "1.2.3")
        self.assertIsNone(miseajour.nouvelle_version(chemin, "1.2.0"))
        miseajour.verifier_lutin(DOSSIERS, http=faux_github("1.3.0"), force=True)
        self.assertEqual(miseajour.nouvelle_version(chemin, "1.2.0")["version"], "1.3.0", "la version suivante est annoncée de nouveau")

    def test_dans_un_conteneur_la_commande_est_celle_de_docker(self):
        with mock.patch.dict(os.environ, {"LUTIN_DOCKER": "1"}):
            self.assertEqual(miseajour.commande_mise_a_jour(), "docker compose pull && docker compose up -d")

    def test_hors_ligne_et_reseau_absent_ne_cassent_rien(self):
        def panne(url, entetes=None, delai=10):
            raise OSError("pas de réseau")

        def refuse(url, entetes=None, delai=10):
            raise horsligne.HorsLigne("hors ligne")
        for faux in (panne, refuse):
            d = miseajour.verifier_lutin(DOSSIERS, http=faux, force=True)
            self.assertNotIn("version", d)
        self.assertIsNone(miseajour.nouvelle_version(miseajour.fichier_version(DOSSIERS), "0.1.0"))
        self.assertIsNone(miseajour.nouvelle_version(_TEMP / "absent.json", "0.1.0"))


class Serveur(unittest.TestCase):
    def setUp(self):
        miseajour.fichier_version(DOSSIERS).unlink(missing_ok=True)

    def test_l_etat_annonce_la_version_et_on_peut_l_ignorer(self):
        self.assertIsNone(requete("GET", "/api/etat")[1]["nouvelle_version"])
        miseajour.verifier_lutin(DOSSIERS, http=faux_github("99.0.0"))
        n = requete("GET", "/api/etat")[1]["nouvelle_version"]
        self.assertEqual((n["version"], n["actuelle"]), ("99.0.0", A.VERSION))
        self.assertEqual(requete("POST", "/api/version-ignorer", {"version": "99.0.0"}), (200, {"ok": True}))
        self.assertIsNone(requete("GET", "/api/etat")[1]["nouvelle_version"])

    def test_la_page_contient_le_bandeau(self):
        page = A.page_web()
        self.assertIn('id="bandeauVersion"', page)
        self.assertIn("/api/version-ignorer", page)


if __name__ == "__main__":
    unittest.main()
