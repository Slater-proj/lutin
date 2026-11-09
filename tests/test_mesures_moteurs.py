"""Mesures de moteurs : n'importe quel moteur actif se mesure avec son propre modèle, les résultats se gardent, se classent, et rien n'est mesuré sur un moteur arrêté."""
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-mesures-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import mesures_moteurs as MM  # noqa: E402


class Flux:
    def __init__(self, morceaux, jetons, vitesse):
        self.morceaux, self.jetons, self.vitesse = morceaux, jetons, vitesse

    def __enter__(self):
        evenements = [{"message": {"content": "mot"}} for _ in range(self.morceaux)]
        evenements.append({"done": True, "eval_count": self.jetons, "eval_duration": int(self.jetons / self.vitesse * 1e9)})          # la vitesse annoncée par le moteur
        return iter(evenements)

    def __exit__(self, *a):
        return False


class FauxMoteur:
    def __init__(self, ident="openai", nom="Serveur compatible OpenAI", actif=True, installes=("petit", "grand"), serveur="", vitesse=100):
        self.id, self.nom, self._actif, self._installes, self._serveur, self.vitesse = ident, nom, actif, list(installes), serveur, vitesse

    def statut(self):
        return {"actif": self._actif, "version": "1.2"}

    def modeles(self):
        return {"actif": self._actif, "installes": self._installes}

    def config(self):
        return {"serveur": self._serveur}

    def adresse(self):
        return "http://127.0.0.1:1234/v1"

    def chat_flux(self, corps, delai=300):
        return Flux(20, 100, self.vitesse)


class Mesures(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix="lutin-mesures-t-"))
        MM.ETAT.update(en_cours=False, erreur="")

    def test_un_serveur_openai_choisi_est_nomme_comme_l_utilisateur_le_connait(self):
        self.assertEqual(MM.nom_affiche(FauxMoteur(serveur="colibri")), "Colibri")
        self.assertEqual(MM.nom_affiche(FauxMoteur(serveur="lmstudio")), "LM Studio")
        self.assertIn("127.0.0.1:1234", MM.nom_affiche(FauxMoteur()))
        self.assertEqual(MM.nom_affiche(FauxMoteur(ident="ollama", nom="Ollama")), "Ollama")

    def test_une_mesure_est_gardee_et_classee_la_plus_rapide_d_abord(self):
        lent, vite = FauxMoteur(serveur="colibri", vitesse=40), FauxMoteur(ident="ollama", nom="Ollama", vitesse=200)
        MM.lancer(self.dossier, lent, "grand", synchrone=True)
        MM.lancer(self.dossier, vite, "petit", synchrone=True)
        c = MM.classement(MM.lire(self.dossier))
        self.assertEqual([(m["nom"], m["modele"], m["rang"]) for m in c], [("Ollama", "petit", 1), ("Colibri", "grand", 2)])
        self.assertGreater(c[0]["tok_s"], c[1]["tok_s"])
        self.assertEqual(MM.ETAT["erreur"], "")

    def test_le_classement_garde_la_derniere_mesure_reussie_de_chaque_couple(self):
        mo = FauxMoteur(ident="ollama", nom="Ollama")
        MM.noter(self.dossier, mo, "petit", {"ok": True, "tok_s": 10.0})
        MM.noter(self.dossier, mo, "petit", {"ok": True, "tok_s": 30.0})
        MM.noter(self.dossier, mo, "petit", {"ok": False, "erreurs": ["panne"]})
        c = MM.classement(MM.lire(self.dossier))
        self.assertEqual([m["tok_s"] for m in c], [30.0], "une panne ne remplace pas la dernière mesure réussie, mais reste dans l'historique")
        self.assertEqual(len(MM.lire(self.dossier)), 3)

    def test_l_historique_est_borne(self):
        mo = FauxMoteur(ident="ollama", nom="Ollama")
        for i in range(MM.MAX + 15):
            MM.noter(self.dossier, mo, "petit", {"ok": True, "tok_s": float(i + 1)})
        self.assertEqual(len(MM.lire(self.dossier)), MM.MAX)

    def test_pas_de_mesure_sur_un_moteur_arrete_ou_un_modele_absent(self):
        with self.assertRaises(ValueError):
            MM.lancer(self.dossier, FauxMoteur(actif=False), "petit", synchrone=True)
        with self.assertRaises(ValueError):
            MM.lancer(self.dossier, FauxMoteur(), "inconnu", synchrone=True)
        self.assertEqual(MM.lire(self.dossier), [], "rien n'est noté quand rien n'a été mesuré")

    def test_une_seule_mesure_a_la_fois(self):
        MM.ETAT["en_cours"] = True
        with self.assertRaises(ValueError):
            MM.lancer(self.dossier, FauxMoteur(), "petit", synchrone=True)

    def test_une_panne_de_moteur_est_un_resultat_pas_une_trace(self):
        class Casse(FauxMoteur):
            def chat_flux(self, corps, delai=300):
                raise OSError("connexion refusée")
        MM.lancer(self.dossier, Casse(), "petit", synchrone=True)
        derniere = MM.lire(self.dossier)[-1]
        self.assertFalse(derniere["ok"])
        self.assertIn("connexion refusée", derniere["erreur"])
        self.assertIn("connexion", MM.ETAT["erreur"])
        self.assertEqual(MM.classement(MM.lire(self.dossier)), [])

    def test_les_candidats_sont_les_moteurs_actifs_avec_un_modele(self):
        moteurs_ = {"a": FauxMoteur(ident="ollama", nom="Ollama", installes=("m1", "m2")), "b": FauxMoteur(ident="llamacpp", nom="llama.cpp", actif=False), "c": FauxMoteur(serveur="lmstudio", installes=())}
        c = MM.candidats(moteurs_, {"modele": "m2"})
        self.assertEqual([(x["moteur"], x["modele"]) for x in c], [("ollama", "m2")], "arrêté ou sans modèle : non proposé ; le modèle choisi est préféré s'il existe")


if __name__ == "__main__":
    unittest.main()
