"""Banc comparatif de moteurs et recommandation : mesures sur de faux moteurs, règle « on garde le plus simple sous 10 % d'écart », résultat conservé et à refaire quand le matériel change."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-bancmoteurs-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import bench_moteurs as bm  # noqa: E402
from lutin import machine, moteurs  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


class Flux:
    def __init__(self, evenements):
        self.evenements = evenements

    def __enter__(self):
        return iter(self.evenements)

    def __exit__(self, *_):
        return False


class Faux:
    """Un moteur de test : répond à `tok_s` jetons par seconde (chiffres du moteur), ou échoue."""
    genre = "x"

    def __init__(self, ident, nom, tok_s=50.0, version="1.0", modeles=("m",), echec=None, installe=True, actif=True):
        self.id, self.nom, self.tok_s, self.version, self.modeles_, self.echec, self.installe, self.actif_ = ident, nom, tok_s, version, list(modeles), echec, installe, actif
        self.appels = 0

    def statut(self):
        return {"installe": self.installe, "actif": self.actif_, "version": self.version}

    def modeles(self):
        return {"actif": self.actif_, "installes": self.modeles_}

    def chat_flux(self, corps, delai=900):
        self.appels += 1
        if self.echec:
            raise RuntimeError(self.echec)
        n = 100
        return Flux([{"message": {"role": "assistant", "content": "mot "}, "done": False}, {"done": True, "eval_count": n, "eval_duration": int(n / self.tok_s * 1e9),
                                                                                         "prompt_eval_count": 40, "prompt_eval_duration": int(0.05 * 1e9)}])


class Horloge:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.5
        return self.t


class Profil:
    def __init__(self, gpu=None, integrees=False, cpu="CPU test", ram=32, gpus=()):
        self._gpu, self._integrees, self.cpu, self.ram_go, self.gpus = gpu, integrees, cpu, ram, list(gpus)

    def gpu_principal(self):
        return self._gpu

    def gpus_integrees(self):
        return [1] if self._integrees else []

    def resume(self):
        return "machine de test"


def carte(fabricant, vram, nom="Carte"):
    return machine.Gpu(nom=nom, fabricant=fabricant, vram_go=vram, source="test")


class Base(unittest.TestCase):
    def setUp(self):
        self.ancien = dict(moteurs.MOTEURS)
        self.addCleanup(lambda: (moteurs.MOTEURS.clear(), moteurs.MOTEURS.update(self.ancien)))

    def installer(self, ollama, llama):
        moteurs.MOTEURS["ollama"], moteurs.MOTEURS["llamacpp"] = ollama, llama


class Mesure(Base):
    def test_les_chiffres_du_moteur_donnent_la_vitesse(self):
        r = bm.mesurer(Faux("ollama", "Ollama", tok_s=40), "m", "rapide", horloge=Horloge(), memoire=lambda: {"ram": 1, "vram": 2})
        self.assertTrue(r["ok"])
        self.assertEqual((r["tok_s"], r["passes"], r["ram"], r["vram"]), (40.0, 3, 1, 2))
        self.assertEqual(r["lecture_tok_s"], 800)
        self.assertIsNotNone(r["charge_s"])

    def test_le_mode_approfondi_fait_plus_de_passes(self):
        f = Faux("ollama", "Ollama")
        bm.mesurer(f, "m", "approfondi", horloge=Horloge())
        self.assertEqual(f.appels, 1 + bm.PASSES["approfondi"])

    def test_une_panne_est_un_resultat_pas_une_exception(self):
        r = bm.mesurer(Faux("llamacpp", "llama.cpp", echec="le serveur ne démarre pas"), "m", horloge=Horloge())
        self.assertFalse(r["ok"])
        self.assertIn("ne démarre pas", r["erreurs"][0])
        self.assertIsNone(r["tok_s"])

    def test_sans_chiffres_du_moteur_la_vitesse_est_comptee_a_l_horloge(self):
        class SansChiffres(Faux):
            def chat_flux(self, corps, delai=900):
                return Flux([{"message": {"content": "a"}, "done": False}] * 30 + [{"done": True}])
        r = bm.mesurer(SansChiffres("openai", "X"), "m", horloge=Horloge())
        self.assertTrue(r["ok"])
        self.assertGreater(r["tok_s"], 0)


class Equivalence(unittest.TestCase):
    """Le même modèle porte un nom différent d'un moteur à l'autre : la comparaison les rapproche d'après la famille et la taille, jamais au hasard."""

    def test_le_meme_nom_gagne_toujours(self):
        self.assertEqual(bm.equivalent("qwen3:8b", ["autre", "qwen3:8b"]), "qwen3:8b")

    def test_un_fichier_gguf_un_depot_lm_studio_et_un_nom_ollama_se_retrouvent(self):
        self.assertEqual(bm.equivalent("qwen3:8b", ["Qwen3-8B-Q4_K_M", "Qwen3-14B-Q4_K_M", "llama3.1-8b"]), "Qwen3-8B-Q4_K_M")
        self.assertEqual(bm.equivalent("qwen3:8b", ["qwen/qwen3-8b", "qwen/qwen3-4b"]), "qwen/qwen3-8b")
        self.assertEqual(bm.equivalent("qwen3:8b", ["Qwen3-8B-Instruct-exl3-4.0bpw"]), "Qwen3-8B-Instruct-exl3-4.0bpw")

    def test_une_autre_taille_ou_une_autre_famille_n_est_jamais_prise(self):
        self.assertIsNone(bm.equivalent("qwen3:8b", ["Qwen3-14B-Q4_K_M", "llama3.1-8b", "qwen2.5-8b-x"][:2]))
        self.assertIsNone(bm.equivalent("qwen3-coder:30b", ["Qwen3-30B-Q4_K_M"]), "qwen3-coder n'est pas qwen3")
        self.assertIsNone(bm.equivalent("monmodele", ["monmodele-q4"]), "sans taille dans le nom on ne devine pas")
        self.assertIsNone(bm.equivalent("", []))


class Comparaison(Base):
    def lancer(self, o, l, **kw):
        self.installer(o, l)
        liberes = []
        r = bm.comparer("m", "rapide", Profil(), horloge=Horloge(), memoire=lambda i, m: None, liberer_autres=lambda a, m: liberes.append(list(a)), date="2026-11-07T10:00:00", **kw)
        return r, liberes

    def test_ecart_sous_dix_pour_cent_on_garde_le_plus_simple(self):
        r, liberes = self.lancer(Faux("ollama", "Ollama", 100), Faux("llamacpp", "llama.cpp", 105))
        self.assertEqual(r["recommandation"]["moteur"], "ollama")
        self.assertEqual(r["recommandation"]["source"], "banc")
        self.assertIn("plus simple", r["recommandation"]["raison"])
        self.assertEqual(liberes, [["llamacpp"], ["ollama"]], "chaque moteur est mesuré après avoir déchargé l'autre")

    def test_un_moteur_nettement_meilleur_est_recommande_avec_sa_raison(self):
        r, _ = self.lancer(Faux("ollama", "Ollama", 100), Faux("llamacpp", "llama.cpp", 130))
        rec = r["recommandation"]
        self.assertEqual(rec["moteur"], "llamacpp")
        self.assertIn("130", rec["raison"])
        self.assertIn("100", rec["raison"])
        self.assertIn("+30", rec["raison"])

    def test_un_moteur_instable_n_est_jamais_recommande(self):
        r, _ = self.lancer(Faux("ollama", "Ollama", 100), Faux("llamacpp", "llama.cpp", 300, echec="plantage"))
        self.assertEqual(r["recommandation"]["source"], "regles", "un seul moteur a réussi : pas de comparaison, on retombe sur les règles")
        self.assertEqual(r["recommandation"]["moteur"], "ollama")

    def test_un_moteur_sans_le_modele_est_ignore_avec_la_raison(self):
        r, liberes = self.lancer(Faux("ollama", "Ollama", 100), Faux("llamacpp", "llama.cpp", modeles=("autre",)))
        self.assertEqual([m["id"] for m in r["moteurs"]], ["ollama"])
        self.assertEqual([(i["id"], i["raison"]) for i in r["ignores"]], [("llamacpp", "n'a ni ce modèle ni un équivalent")])
        self.assertEqual(liberes, [], "un seul moteur : rien à décharger")

    def test_aucun_moteur_pret(self):
        r, _ = self.lancer(Faux("ollama", "Ollama", installe=False), Faux("llamacpp", "llama.cpp", actif=False, installe=False))
        self.assertEqual(r["moteurs"], [])
        self.assertEqual(len(r["ignores"]), 2)

    def test_le_texte_lisible_dit_tout(self):
        r, _ = self.lancer(Faux("ollama", "Ollama", 100), Faux("llamacpp", "llama.cpp", 130))
        t = bm.lisible(r)
        for attendu in ("Ollama", "llama.cpp", "jetons/s", "Recommandation"):
            self.assertIn(attendu, t)


class Recommandation(unittest.TestCase):
    def test_regles_marquees_comme_non_mesurees(self):
        cas = [(Profil(carte("nvidia", 12)), "ollama"), (Profil(carte("amd", 8)), "llamacpp"), (Profil(None, integrees=True), "ollama"), (Profil(None), "ollama")]
        for profil, attendu in cas:
            r = bm.recommander(profil)
            self.assertEqual(r["moteur"], attendu)
            self.assertEqual(r["source"], "regles")
            self.assertIn("pas encore mesuré", r["raison"])
            self.assertTrue(r["limites"])

    def test_docker_suit_les_memes_regles_car_les_moteurs_s_installent_depuis_la_page(self):
        r = bm.recommander(Profil(carte("nvidia", 24)), docker=True)
        self.assertEqual(r["moteur"], "ollama")
        self.assertNotIn("image", r["raison"])          # plus d'Ollama dans l'image : la page l'installe


    def test_sans_modele_installe_la_recommandation_est_theorique(self):
        self.assertTrue(bm.recommander(Profil(), modele_installe=False)["theorique"])
        self.assertFalse(bm.recommander(Profil(), modele_installe=True)["theorique"])

    def test_sans_profil_pas_d_exception(self):
        self.assertEqual(bm.recommander(None)["moteur"], "ollama")


class Conservation(Base):
    def resultat(self, version="1.0", cpu="CPU A"):
        self.installer(Faux("ollama", "Ollama", version=version), Faux("llamacpp", "llama.cpp", version="b100"))
        return bm.comparer("m", "rapide", Profil(cpu=cpu), horloge=Horloge(), memoire=lambda i, m: None, liberer_autres=lambda a, m: None)

    def test_enregistrer_lire_et_garder_le_dernier_par_modele(self):
        d = Path(tempfile.mkdtemp(dir=_TEMP))
        r = self.resultat()
        bm.enregistrer(d, r)
        bm.enregistrer(d, dict(r, modele="autre"))
        self.assertEqual(set(bm.lire(d)), {"m", "autre"})
        self.assertEqual(bm.lire(d)["m"]["moteurs"][0]["id"], "ollama")
        self.assertEqual(bm.lire(_TEMP / "absent"), {})

    def test_a_refaire_quand_le_materiel_ou_une_version_change(self):
        r = self.resultat()
        versions = {"ollama": "1.0", "llamacpp": "b100"}
        self.assertFalse(bm.a_refaire(r, Profil(cpu="CPU A"), versions))
        self.assertTrue(bm.a_refaire(r, Profil(cpu="CPU B"), versions), "autre processeur")
        self.assertTrue(bm.a_refaire(r, Profil(cpu="CPU A"), dict(versions, ollama="2.0")), "nouvelle version d'Ollama")
        self.assertTrue(bm.a_refaire(r, Profil(cpu="CPU A", ram=64), versions), "autre quantité de mémoire")
        self.assertTrue(bm.a_refaire(None, Profil(), versions))

    def test_le_fichier_partage_ne_contient_rien_de_personnel(self):
        r = self.resultat()
        texte = bm.exporter(r)
        d = json.loads(texte)
        self.assertNotIn("recommandation", d)
        self.assertEqual(d["modele"], "m")
        for interdit in (os.path.expanduser("~"), os.environ.get("USERNAME", "\0"), os.environ.get("COMPUTERNAME", "\0"), str(_TEMP)):
            self.assertNotIn(interdit, texte)

    def test_la_vue_signale_un_resultat_caduc_et_ne_s_en_sert_pas_pour_recommander(self):
        d = Path(tempfile.mkdtemp(dir=_TEMP))
        r = self.resultat()
        r["moteurs"][1]["tok_s"] = 500          # un résultat flatteur pour llama.cpp
        bm.enregistrer(d, r)
        self.installer(Faux("ollama", "Ollama", version="1.0"), Faux("llamacpp", "llama.cpp", version="b100"))
        v = bm.vue(d, "m", Profil(cpu="CPU A"))
        self.assertFalse(v["a_refaire"])
        self.assertEqual(v["recommandation"]["moteur"], "llamacpp")
        self.installer(Faux("ollama", "Ollama", version="9.9"), Faux("llamacpp", "llama.cpp", version="b100"))
        v = bm.vue(d, "m", Profil(cpu="CPU A"))
        self.assertTrue(v["a_refaire"])
        self.assertEqual(v["recommandation"]["source"], "regles", "un résultat périmé ne décide plus")


class Lancement(Base):
    def test_un_serveur_openai_demarre_entre_dans_la_comparaison_avec_son_propre_nom_de_modele(self):
        class Serveur(Faux):
            def adresse(self):
                return "http://127.0.0.1:1234/v1"

            def config(self):
                return {"serveur": "lmstudio"}
        self.installer(Faux("ollama", "Ollama", 100, modeles=("qwen3:8b",)), Faux("llamacpp", "llama.cpp", 100, installe=False))
        moteurs.MOTEURS["openai"] = Serveur("openai", "Serveur compatible OpenAI", 60, modeles=("qwen/qwen3-8b", "autre-70b"))
        utilises = []
        r = bm.comparer("qwen3:8b", "rapide", Profil(), horloge=Horloge(), memoire=lambda i, m: utilises.append((i, m)) or None, liberer_autres=lambda a, m: None, date="2026-11-09T10:00:00")
        self.assertEqual([(m["nom"], m["modele"]) for m in r["moteurs"]], [("Ollama", "qwen3:8b"), ("LM Studio", "qwen/qwen3-8b")])
        self.assertIn(("openai", "qwen/qwen3-8b"), utilises, "la mémoire est lue avec le nom de modèle PROPRE à ce moteur")
        self.assertEqual([i["id"] for i in r["ignores"]], ["llamacpp"])

    def test_un_serveur_openai_arrete_est_signale_pas_demarre_et_sans_adresse_il_est_absent(self):
        self.installer(Faux("ollama", "Ollama", 100), Faux("llamacpp", "llama.cpp", 100))
        arrete = Faux("openai", "Serveur compatible OpenAI", 60, actif=False)
        arrete.adresse = lambda: "http://127.0.0.1:1234/v1"
        moteurs.MOTEURS["openai"] = arrete
        raisons = {mo.id: raison for mo, raison, _ in bm.disponibles("m")}
        self.assertEqual(raisons["openai"], "pas démarré")
        sans_adresse = Faux("openai", "Serveur compatible OpenAI", 60)
        sans_adresse.adresse = lambda: ""
        moteurs.MOTEURS["openai"] = sans_adresse
        self.assertNotIn("openai", [mo.id for mo, _, _ in bm.disponibles("m")])

    def test_comparer_demande_deux_moteurs(self):
        self.installer(Faux("ollama", "Ollama", 100), Faux("llamacpp", "llama.cpp", installe=False))
        d = Path(tempfile.mkdtemp(dir=_TEMP))
        with self.assertRaises(ValueError) as e:
            bm.lancer("m", "rapide", d, Profil())
        self.assertIn("au moins deux", str(e.exception))
        v = bm.vue(d, "m", Profil())
        self.assertEqual(v["comparables"], 1)
        self.assertTrue(any(x["raison"] for x in v["disponibilite"]))
    def test_une_seule_comparaison_a_la_fois_et_resultat_conserve(self):
        self.installer(Faux("ollama", "Ollama", 100), Faux("llamacpp", "llama.cpp", 100))
        d = Path(tempfile.mkdtemp(dir=_TEMP))
        with self.assertRaises(ValueError):
            bm.lancer("", "rapide", d, Profil())
        with self.assertRaises(ValueError):
            bm.lancer("m", "bizarre", d, Profil())
        ouvert, entre = threading.Event(), threading.Event()

        def retenir(autres, modele):          # la première comparaison reste « en cours » jusqu'à ce qu'on la libère : le test ne dépend plus de la vitesse de la machine
            entre.set()
            ouvert.wait(10)
        bm.lancer("m", "rapide", d, Profil(), liberer_autres=retenir, memoire=lambda i, m: None)
        self.assertTrue(entre.wait(10))
        with self.assertRaises(ValueError):
            bm.lancer("m", "rapide", d, Profil())
        ouvert.set()
        fin = time.time() + 20
        while bm.ETAT["en_cours"] and time.time() < fin:
            time.sleep(0.05)
        self.assertFalse(bm.ETAT["en_cours"])
        self.assertEqual(bm.ETAT["erreur"], "")
        self.assertIn("m", bm.lire(d))

    def test_aucun_moteur_pret_donne_une_erreur_claire(self):
        self.installer(Faux("ollama", "Ollama", installe=False), Faux("llamacpp", "llama.cpp", installe=False))
        d = Path(tempfile.mkdtemp(dir=_TEMP))
        with self.assertRaises(ValueError) as e:          # refusé tout de suite, avec la raison de chaque moteur (avant : lancé pour rien)
            bm.lancer("m", "rapide", d, Profil())
        self.assertIn("pas installé", str(e.exception))
        self.assertFalse(bm.ETAT["en_cours"])
        self.assertEqual(bm.lire(d), {})


class Branchement(unittest.TestCase):
    def test_la_commande_existe(self):
        r = subprocess.run([sys.executable, "-m", "lutin", "bench-moteurs", "--help"], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(RACINE),
                           env=dict(os.environ, PYTHONPATH=str(RACINE / "src"), LUTIN_LANGUE="fr"), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
        self.assertIn("--mode", r.stdout)
        self.assertIn("--sortie", r.stdout)

    def test_les_routes_et_la_page(self):
        src = (RACINE / "src" / "lutin" / "serveur.py").read_text(encoding="utf-8")
        self.assertEqual(src.count('"/api/bench-moteurs"'), 2)
        page = (RACINE / "src" / "lutin" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("carteBancMoteurs", page)


if __name__ == "__main__":
    unittest.main()
