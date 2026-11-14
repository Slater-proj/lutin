"""ExLlamaV3 côté modèles et côté carte : le catalogue (Hugging Face simulé), les quantifications, les mises à jour, la suppression, l'origine des modèles, les étapes de l'installation,
le démarrage juste après l'installation, les dossiers (mêmes lignes pour tous les moteurs) et le changement de serveur. Aucun réseau, aucun vrai processus."""
import json
import os
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-exlm-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import core as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import exllamav3 as X  # noqa: E402
from lutin import exllamav3_catalog as C  # noqa: E402
from lutin import llamacpp_engine as ml  # noqa: E402
from lutin import engines  # noqa: E402
from test_exllamav3 import SHA, Base, Faux  # noqa: E402

TAILLES = {"4.0bpw": 5_200_000_000, "6.0bpw": 6_900_000_000, "8.0bpw_H8": 8_800_000_000}


def faux_hf(depots=None, appels=None, branches=None):
    """Un faux Hugging Face : liste de dépôts, branches (« refs ») et fichiers d'une branche (« tree »)."""
    branches = branches or {"main": "m" * 40, "4.0bpw": "a" * 40, "6.0bpw": "b" * 40, "8.0bpw_H8": "c" * 40}

    def f(url, entetes=None):
        if appels is not None:
            appels.append(url)
        if url.endswith("/refs"):
            return 200, {}, json.dumps({"branches": [{"name": n, "targetCommit": c} for n, c in branches.items()]}).encode()
        if "/tree/" in url:
            rev = urllib.parse.unquote(url.rsplit("/tree/", 1)[1])
            return 200, {}, json.dumps([{"type": "file", "size": TAILLES.get(rev, 1_000_000_000), "path": "model.safetensors"}, {"type": "file", "size": 1000, "path": "config.json"}, {"type": "directory", "size": 0, "path": "x"}]).encode()
        if "/api/models?" in url:
            return 200, {}, json.dumps(depots if depots is not None else []).encode()
        return 404, {}, b""
    return f


def depot(nom, auteur="turboderp", **plus):
    return dict({"id": auteur + "/" + nom, "downloads": 1200, "likes": 30, "lastModified": "2026-11-06T11:00:00.000Z", "pipeline_tag": "text-generation", "tags": ["exl3", "base_model:quantized:Qwen/" + nom.replace("-exl3", ""), "license:apache-2.0"]}, **plus)


class Catalogue(unittest.TestCase):
    def setUp(self):
        C.CACHE.clear()

    def test_l_auteur_officiel_est_la_valeur_par_defaut_et_la_communaute_un_choix(self):
        appels = []
        C.chercher("qwen", "recent", False, 1, faux_hf([depot("Qwen3-8B-exl3")], appels))
        C.chercher("qwen", "populaire", True, 1, faux_hf([depot("Qwen3-8B-exl3")], appels))
        self.assertIn("author=turboderp", appels[0])
        self.assertIn("sort=lastModified", appels[0])
        self.assertIn("filter=exl3", appels[1])
        self.assertNotIn("author=", appels[1])
        self.assertIn("sort=downloads", appels[1])

    def test_les_depots_sont_decrits_et_ceux_qui_ne_sont_pas_exl3_ecartes(self):
        brut = [depot("Qwen3-8B-exl3"), depot("Qwen2.5-VL-7B-exl3", pipeline_tag="image-text-to-text"), {"id": "x/autre-modele", "tags": ["gguf"]}, {"id": "../mal/forme-exl3", "tags": ["exl3"]}]
        r = C.chercher("", "recent", True, 1, faux_hf(brut))
        self.assertEqual([m["nom"] for m in r["modeles"]], ["Qwen3-8B-exl3", "Qwen2.5-VL-7B-exl3"])
        m = r["modeles"][0]
        self.assertEqual((m["auteur"], m["telechargements"], m["aime"], m["maj"], m["licence"], m["base"]), ("turboderp", 1200, 30, "2026-11-06", "apache-2.0", "Qwen/Qwen3-8B"))
        self.assertEqual(m["estimation_go"], 5.2)
        self.assertEqual(r["modeles"][1]["capacites"], ["vision"])
        self.assertEqual(m["capacites"], [])

    def test_une_page_de_plus_agrandit_la_liste_et_dit_s_il_y_a_une_suite(self):
        brut = [depot("M{}-8B-exl3".format(i)) for i in range(C.PAR_PAGE + 5)]
        a = C.chercher("", "recent", False, 1, faux_hf(brut))
        self.assertEqual((len(a["modeles"]), a["suite"]), (C.PAR_PAGE, True))
        C.CACHE.clear()
        b = C.chercher("", "recent", False, 2, faux_hf(brut))
        self.assertEqual((len(b["modeles"]), b["suite"]), (C.PAR_PAGE + 5, False))

    def test_l_estimation_vient_du_nom_et_ne_se_trompe_pas_sur_les_modeles_a_experts(self):
        self.assertEqual(C.estimer_go("Qwen3-8B-exl3", 4.0), 5.2, "mesuré : 8B à 4 bits = 5,2 Go")
        self.assertGreater(C.estimer_go("Qwen3-30B-A3B-exl3", 4.0), 15, "30 milliards de poids, pas 3")
        self.assertIsNone(C.estimer_go("GLM-Flash-exl3", 4.0))
        self.assertIsNone(C.estimer_go("Qwen3-8B-exl3", 0))

    def test_les_quantifications_ont_leur_taille_exacte_et_sont_triees(self):
        q = C.quantifications("turboderp/Qwen3-8B-exl3", faux_hf())
        self.assertEqual([x["revision"] for x in q], ["4.0bpw", "6.0bpw", "8.0bpw_H8"], "« main » n'est pas une quantification")
        self.assertEqual([x["go"] for x in q], [5.2, 6.9, 8.8])
        self.assertEqual(q[0]["commit"], "a" * 40)

    def test_les_pannes_de_hugging_face_sont_dites_clairement(self):
        def panne(code):
            return lambda url, entetes=None: (code, {}, b"")

        def coupe(url, entetes=None):
            raise OSError("pas de réseau")
        for http, mot in ((panne(404), "n'existe pas"), (panne(500), "HTTP 500"), (coupe, "ne répond pas"), (lambda url, entetes=None: (200, {}, b"pas du json"), "illisible")):
            C.CACHE.clear()
            with self.assertRaises(ValueError, msg=mot) as e:
                C.quantifications("turboderp/Qwen3-8B-exl3", http)
            self.assertIn(mot, str(e.exception))
        for mauvais in ("--help", "a b/c", "solo", "../x/y"):
            with self.assertRaises(ValueError, msg=mauvais):
                C.quantifications(mauvais, faux_hf())

    def test_une_version_plus_recente_est_reperee_par_l_empreinte_de_la_branche(self):
        installes = [{"nom": "A_4.0bpw", "depot": "turboderp/A", "revision": "4.0bpw", "commit": "a" * 40},
                     {"nom": "B_6.0bpw", "depot": "turboderp/B", "revision": "6.0bpw", "commit": "z" * 40},
                     {"nom": "main", "depot": "turboderp/C", "revision": "", "commit": "m" * 40},
                     {"nom": "posé-à-la-main", "depot": "", "revision": "", "commit": ""}]
        r = C.versions_plus_recentes(installes, faux_hf())
        self.assertEqual([x["nom"] for x in r["plus_recentes"]], ["B_6.0bpw"])
        self.assertEqual(r["erreurs"], [])
        C.CACHE.clear()
        r = C.versions_plus_recentes(installes[:1], lambda url, entetes=None: (500, {}, b""))
        self.assertEqual((r["plus_recentes"], len(r["erreurs"])), ([], 1), "une panne n'est pas une mise à jour : elle est dite")


class Modeles(Base):
    def test_un_modele_telecharge_garde_son_origine(self):
        self.installer()
        racine = X.dossier_modeles(self.dossiers)

        def lancer(cmd, **k):
            (racine / "Qwen3-8B-exl3_4.0bpw").mkdir(parents=True)
            (racine / "Qwen3-8B-exl3_4.0bpw" / "config.json").write_text("{}", encoding="utf-8")
            (racine / "Qwen3-8B-exl3_4.0bpw" / "model.safetensors").write_bytes(b"x" * 1000)
            return Faux(["ok\n"])
        C.CACHE.clear()
        X.telecharger_modele("turboderp/Qwen3-8B-exl3", "4.0bpw", self.dossiers, lancer=lancer, http=faux_hf())
        m = X.modeles(self.dossiers)
        self.assertEqual([(x["nom"], x["depot"], x["revision"], x["commit"]) for x in m], [("Qwen3-8B-exl3_4.0bpw", "turboderp/Qwen3-8B-exl3", "4.0bpw", "a" * 40)])
        self.assertEqual(X.nom_dossier_modele("turboderp/Qwen3-8B-exl3", ""), "Qwen3-8B-exl3")

    def test_un_modele_pose_a_la_main_n_a_pas_d_origine_mais_est_liste(self):
        d = X.dossier_modeles(self.dossiers) / "maison"
        d.mkdir(parents=True)
        (d / "config.json").write_text("{}", encoding="utf-8")
        self.assertEqual([(m["nom"], m["depot"], m["commit"]) for m in X.modeles(self.dossiers)], [("maison", "", "")])

    def test_un_depot_sans_reseau_ne_fait_pas_echouer_le_telechargement(self):
        self.installer()
        racine = X.dossier_modeles(self.dossiers)

        def lancer(cmd, **k):
            (racine / "M").mkdir(parents=True)
            (racine / "M" / "config.json").write_text("{}", encoding="utf-8")
            return Faux(["ok\n"])

        def coupe(url, entetes=None):
            raise OSError("hors ligne")
        C.CACHE.clear()
        self.assertTrue(X.telecharger_modele("turboderp/M-exl3", "", self.dossiers, lancer=lancer, http=coupe))
        self.assertEqual(X.modeles(self.dossiers)[0]["commit"], "")

    def test_supprimer_n_efface_que_le_dossier_d_un_modele(self):
        racine = X.dossier_modeles(self.dossiers)
        (racine / "A").mkdir(parents=True)
        (racine / "A" / "config.json").write_text("{}", encoding="utf-8")
        (self.tmp / "intouchable").mkdir()
        for mauvais in ("", "..", "../intouchable", "a/b", "a\\b", "absent"):
            with self.assertRaises(ValueError, msg=repr(mauvais)):
                X.supprimer_modele(mauvais, self.dossiers)
        self.assertTrue((self.tmp / "intouchable").is_dir())
        self.assertTrue(X.supprimer_modele("A", self.dossiers))
        self.assertEqual(X.modeles(self.dossiers), [])

    def test_le_dossier_des_modeles_choisi_va_dans_la_configuration_de_tabby(self):
        ailleurs = self.tmp / "disque-d" / "modeles"
        d = {"donnees": self.tmp, "modeles": str(ailleurs)}
        self.assertEqual(X.dossier_modeles(d), ailleurs)
        self.assertEqual(X.dossier_modeles(self.dossiers), X.dossier(self.dossiers) / "modeles")
        self.installer(dossiers=d)
        self.assertIn(ailleurs.as_posix(), (X.dossier_tabby(d) / "config.yml").read_text(encoding="utf-8"))

    def test_l_installation_annonce_ses_etapes(self):
        textes, etapes = [], []
        self.installer(dire=textes.append, etape=lambda n, total: etapes.append((n, total)))
        self.assertEqual(etapes, [(n, X.ETAPES_INSTALLATION) for n in range(1, X.ETAPES_INSTALLATION + 1)])
        self.assertTrue(any(t.startswith("Étape 4/5") and "dépendances" in t for t in textes), textes)
        self.assertTrue(any("Successfully installed" in t for t in textes), "ce que pip dit est montré")


class Telechargement(Base):
    def test_la_progression_suit_la_taille_du_dossier_et_dit_le_pourcentage(self):
        """Le téléchargeur de TabbyAPI réécrit une barre sur UNE ligne : rien ne s'affichait. La taille du dossier qui grossit, comparée à la taille annoncée par Hugging Face, donne le vrai avancement."""
        self.installer()
        racine = X.dossier_modeles(self.dossiers)
        dossier = racine / "Qwen3-8B-exl3_4.0bpw"

        class Lent:
            def __init__(self):
                self.code, self.pid = 0, 1

            @property
            def stdout(self):
                dossier.mkdir(parents=True)
                (dossier / "config.json").write_text("{}", encoding="utf-8")
                for i in range(1, 5):
                    (dossier / ".cache").mkdir(exist_ok=True)
                    (dossier / ".cache" / "poids.incomplete").write_bytes(b"x" * (i * 1_300_000_000 // 40))          # 32,5 Mo, 65, 97,5, 130 Mo : un fichier en cours dans le sous-dossier caché
                    time.sleep(0.12)
                    yield "ligne\n"

            def wait(self):
                return 0

            def poll(self):
                return 0

            def terminate(self):
                pass

            def kill(self):
                pass
        textes, mesures = [], []
        total_hf = 130_000_000
        faux = faux_hf(branches={"main": "m" * 40, "4.0bpw": "a" * 40})

        def http(url, entetes=None):
            if "/tree/" in url:
                import json as _json
                return 200, {}, _json.dumps([{"type": "file", "size": total_hf, "path": "model.safetensors"}]).encode()
            return faux(url, entetes)
        C.CACHE.clear()
        with mock.patch.object(X, "INTERVALLE_PROGRES_S", 0.05):
            X.telecharger_modele("turboderp/Qwen3-8B-exl3", "4.0bpw", self.dossiers, dire=textes.append, lancer=lambda cmd, **k: Lent(), http=http, progres=lambda f, t: mesures.append((f, t)))
        self.assertTrue(mesures, "la progression est remontée")
        self.assertTrue(all(t == total_hf for _, t in mesures), "le total vient de Hugging Face")
        self.assertEqual(mesures, sorted(mesures), "elle ne recule jamais")
        self.assertTrue(any("%" in t and "Go" in t for t in textes), textes)
        self.assertTrue(any("Téléchargement :" in t for t in textes))

    def test_sans_taille_connue_on_montre_ce_qui_est_recu(self):
        self.installer()
        racine = X.dossier_modeles(self.dossiers)

        class Court:
            code, pid = 0, 1
            stdout = iter([])

            def wait(self):
                time.sleep(0.2)
                return 0

            def poll(self):
                return 0

            def terminate(self):
                pass

            def kill(self):
                pass
        (racine / "M").mkdir(parents=True)
        (racine / "M" / "poids.bin").write_bytes(b"x" * 2_000_000)
        textes = []

        def panne(url, entetes=None):
            raise OSError("hors ligne")
        C.CACHE.clear()
        with mock.patch.object(X, "INTERVALLE_PROGRES_S", 0.05):
            X.telecharger_modele("turboderp/M-exl3", "", self.dossiers, dire=textes.append, lancer=lambda cmd, **k: Court(), http=panne, progres=lambda f, t: None)
        self.assertTrue(any("reçus" in t for t in textes), textes)


class SuppressionSure(Base):
    def modele(self, nom="Gros-exl3_4.0bpw", config=True):
        d = X.dossier_modeles(self.dossiers) / nom
        d.mkdir(parents=True)
        if config:
            (d / "config.json").write_text("{}", encoding="utf-8")
        (d / "model.safetensors").write_bytes(b"x" * 1000)
        return d

    def test_un_fichier_utilise_ne_laisse_pas_un_modele_a_moitie_efface(self):
        """Le défaut : la suppression effaçait fichier par fichier ; un fichier tenu par le serveur faisait échouer la fin, mais config.json était déjà parti — le modèle « disparaissait » de la liste en restant sur le disque."""
        d = self.modele()
        with mock.patch.object(X.os, "replace", side_effect=PermissionError("fichier utilisé")):
            with self.assertRaises(PermissionError):
                X.supprimer_modele(d.name, self.dossiers)
        self.assertTrue((d / "config.json").is_file() and (d / "model.safetensors").is_file(), "rien n'a été touché")
        self.assertEqual([m["nom"] for m in X.modeles(self.dossiers)], [d.name], "il est toujours dans la liste")

    def test_la_suppression_reussie_ne_laisse_aucun_dossier(self):
        d = self.modele()
        X.supprimer_modele(d.name, self.dossiers)
        self.assertEqual(list(X.dossier_modeles(self.dossiers).iterdir()), [])

    def test_les_restes_d_une_suppression_interrompue_sont_effaces_et_jamais_listes(self):
        reste = X.dossier_modeles(self.dossiers) / ".suppression-Vieux-a1b2c3"
        reste.mkdir(parents=True)
        (reste / "config.json").write_text("{}", encoding="utf-8")
        self.assertEqual(X.modeles(self.dossiers), [])
        self.assertFalse(reste.exists())

    def test_un_dossier_sans_config_mais_avec_des_poids_est_liste_comme_incomplet(self):
        d = self.modele("Abime-exl3", config=False)
        m = X.modeles(self.dossiers)
        self.assertEqual([(x["nom"], x["incomplet"]) for x in m], [(d.name, True)])
        X.supprimer_modele(d.name, self.dossiers)          # et il se supprime comme un autre
        self.assertEqual(X.modeles(self.dossiers), [])


class ContexteBorne(Base):
    def test_la_memoire_de_conversation_est_bornee_et_compressee(self):
        """« Insufficient VRAM in split for model and cache » : sans borne, TabbyAPI réserve la longueur maximale du modèle (parfois plus de 100 000 jetons) pour sa mémoire de conversation."""
        c = X.config_yaml(5000, self.tmp / "modeles", 24576)
        self.assertIn("max_seq_len: 24576", c)
        self.assertIn("cache_mode: Q8", c)
        self.assertIn("max_seq_len: %d" % X.CONTEXTE_DEFAUT, X.config_yaml(5000, self.tmp / "modeles"), "sans réglage connu : une valeur prudente, pas la longueur maximale du modèle")
        self.assertIn("max_seq_len: 2048", X.config_yaml(5000, self.tmp / "modeles", 10))
        self.assertIn("max_seq_len: 262144", X.config_yaml(5000, self.tmp / "modeles", 10 ** 9))

    def test_le_demarrage_ecrit_le_contexte_des_reglages(self):
        self.installer()
        etat = {"ok": False}

        def lancer(cmd, **k):
            etat["ok"] = True
            return Faux(code=None, pid=9)
        X.demarrer(5000, self.dossiers, lancer=lancer, repond_=lambda p: etat["ok"], dormir=lambda s: None, contexte=32768)
        self.assertIn("max_seq_len: 32768", (X.dossier_tabby(self.dossiers) / "config.yml").read_text(encoding="utf-8"))


class Carte(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-exlm-carte-"))
        self.ancien = dict(engines.CONTEXTE)
        engines.CONTEXTE["donnees"] = lambda: self.tmp
        engines.CONTEXTE["hors_ligne"] = lambda: False
        engines.CONTEXTE["en_docker"] = lambda: False
        self.mo = engines.MOTEURS["openai"]
        ml.regler_serveur("openai", {"serveur": "exllamav3"})
        self.addCleanup(self.remettre)

    def remettre(self):
        cfg = ml.lire_config()
        cfg.pop("openai", None)
        ml.ecrire_config(cfg)
        engines.CONTEXTE.clear()
        engines.CONTEXTE.update(self.ancien)

    def faux_modeles(self):
        racine = X.dossier_modeles(self.mo._dossiers())
        (racine / "A-exl3").mkdir(parents=True)
        (racine / "A-exl3" / "config.json").write_text("{}", encoding="utf-8")

    def test_l_installation_est_suivie_d_un_demarrage_et_la_barre_avance_par_etapes(self):
        suivi, progression = [], []
        with mock.patch.object(X, "installer", lambda dossiers, port, dire, annule=None, etape=None, **k: ([etape(n, 5) for n in range(1, 6)], dire("Étape 4/5 : pip"), {"tabby": SHA, "lib": "1.6.6"})[2]), \
                mock.patch.object(X, "demarrer", lambda port, dossiers=None, **k: suivi.append(("demarrer", port))):
            self.mo.faire("installer", lambda t, f, total: progression.append((t, f, total)))
        self.assertEqual(suivi, [("demarrer", 5000)])
        self.assertEqual(progression[-1][1:], (6, 6))
        self.assertIn("Installé et démarré", progression[-1][0])
        self.assertTrue(all(total == 6 for _, _, total in progression), "une barre sur 6 étapes (5 + le démarrage)")
        self.assertIn(("Étape 4/5 : pip", 4, 6), progression, "le texte de pip accompagne l'étape en cours (4 étapes faites sur 6 quand la 5e commence)")

    def test_un_demarrage_qui_echoue_ne_defait_pas_l_installation_et_est_dit(self):
        progression = []
        with mock.patch.object(X, "installer", lambda dossiers, port, dire, annule=None, etape=None, **k: {"tabby": SHA, "lib": "1.6.6"}), \
                mock.patch.object(X, "demarrer", mock.Mock(side_effect=ValueError("CUDA introuvable\nsuite du journal"))):
            self.mo.faire("installer", lambda t, f, total: progression.append((t, f, total)))        # aucune exception : l'installation a réussi
        self.assertTrue(progression[-1][0].startswith("⚠"), progression[-1])
        self.assertIn("CUDA introuvable", progression[-1][0])
        self.assertNotIn("suite du journal", progression[-1][0], "une seule ligne dans la barre")

    def test_les_dossiers_ont_les_memes_lignes_pour_chaque_serveur_gere(self):
        info = self.mo.info_dossier()
        self.assertEqual({"actuel", "installe", "modifiable", "modeles", "libre_go", "par", "personnalise"} - set(info), set())
        self.assertFalse(info["modifiable"], "l'installation se choisit pour tous les moteurs (Dossier des moteurs)")
        self.assertTrue(info["modeles"]["modifiable"] and info["actuel"].endswith("exllamav3"))
        ml.regler_serveur("openai", {"serveur": "colibri"})
        info = self.mo.info_dossier()
        self.assertEqual((info["modifiable"], info["modeles"]["modifiable"], info["par"]), (False, False, "moteurs"))
        ml.regler_serveur("openai", {"serveur": "lmstudio"})
        info = self.mo.info_dossier()
        self.assertEqual((info["par"], info["modeles"]["modifiable"]), ("programme", False))
        ml.regler_serveur("openai", {"serveur": ""})
        self.assertEqual(self.mo.info_dossier(), {}, "un serveur que Lutin ne gère pas n'a pas de dossier")
        self.assertNotIn("dossier", ml.vue_reglages("openai"))

    def test_le_dossier_des_modeles_se_choisit_et_arrete_le_serveur_qui_le_lit(self):
        ailleurs = self.tmp / "autre-disque"
        arrets = []
        with mock.patch.object(ml.MoteurOpenAI, "actif", lambda self: True), mock.patch.object(X, "arreter", lambda dossiers=None, **k: arrets.append(1)):
            ml.regler_dossier_modeles("openai", str(ailleurs))
        self.assertEqual(arrets, [1])
        self.assertEqual(self.mo._dossiers()["modeles"], str(ailleurs))
        self.assertEqual(self.mo.info_dossier()["modeles"]["actuel"], str(ailleurs))
        self.assertTrue(self.mo.info_dossier()["modeles"]["personnalise"])
        ml.regler_dossier_modeles("openai", "")
        self.assertNotIn("modeles", self.mo._dossiers())
        with self.assertRaises(ml.ErreurMoteur):
            ml.regler_dossier_modeles("openai", "pas/absolu")

    def test_choisir_un_autre_serveur_arrete_celui_qui_tourne_au_lieu_de_refuser(self):
        arrets = []
        with mock.patch.object(ml.MoteurOpenAI, "actif", lambda self: True), mock.patch.object(X, "arreter", lambda dossiers=None, **k: arrets.append("exllamav3")):
            self.assertTrue(ml.regler_serveur("openai", {"serveur": "colibri"}))
        self.assertEqual(arrets, ["exllamav3"])
        self.assertTrue(self.mo.colibri_choisi() and not self.mo.exllamav3_choisi())
        arrets.clear()
        with mock.patch.object(ml.MoteurOpenAI, "actif", lambda self: True), mock.patch.object(X, "arreter", lambda dossiers=None, **k: arrets.append("x")):
            ml.regler_serveur("openai", {"serveur": "colibri"})          # le même serveur : rien n'est arrêté
        self.assertEqual(arrets, [])

    def test_changer_de_serveur_eteint_ne_demande_rien(self):
        with mock.patch.object(ml.MoteurOpenAI, "actif", lambda self: False), mock.patch.object(X, "arreter", lambda dossiers=None, **k: self.fail("rien ne tourne")):
            ml.regler_serveur("openai", {"serveur": "lmstudio"})
        self.assertTrue(self.mo.lmstudio_choisi())

    def test_supprimer_un_modele_passe_par_le_moteur_et_dit_pourquoi_il_refuse(self):
        self.faux_modeles()
        with self.assertRaises(ml.ErreurMoteur):
            self.mo.supprimer_modele("../x")
        self.mo.supprimer_modele("A-exl3")
        self.assertEqual(X.modeles(self.mo._dossiers()), [])
        with mock.patch.object(X, "supprimer_modele", mock.Mock(side_effect=PermissionError())):
            with self.assertRaises(ml.ErreurMoteur) as e:
                self.mo.supprimer_modele("A-exl3")
        self.assertIn("arrête ExLlamaV3", str(e.exception))
        ml.regler_serveur("openai", {"serveur": "colibri"})
        with self.assertRaises(ml.ErreurMoteur):
            self.mo.supprimer_modele("A-exl3")

    def test_le_dossier_des_moteurs_compte_exllamav3_parmi_ce_qui_est_installe(self):
        with mock.patch.object(ml.MoteurExterne, "_exl", lambda self: {"tabby": SHA, "lib": "1"}):
            self.assertIn("ExLlamaV3", ml.moteurs_installes_par_lutin())
        self.assertNotIn("ExLlamaV3", ml.moteurs_installes_par_lutin())

    def test_supprimer_un_modele_tenu_par_le_serveur_l_arrete_puis_reessaie(self):
        suivi = []
        appels = {"n": 0}

        def supprimer(nom, dossiers=None):
            appels["n"] += 1
            if appels["n"] == 1:
                raise PermissionError("utilisé")
            suivi.append(("supprime", nom))
        with mock.patch.object(ml.MoteurOpenAI, "actif", lambda self: True), mock.patch.object(X, "arreter", lambda dossiers=None, **k: suivi.append("arret")), \
                mock.patch.object(X, "supprimer_modele", supprimer), mock.patch.object(ml.time, "sleep", lambda s: None):
            self.mo.supprimer_modele("A-exl3")
        self.assertEqual(suivi, ["arret", ("supprime", "A-exl3")], "arrêté une fois, puis supprimé")

    def test_si_le_fichier_reste_utilise_le_modele_reste_entier_et_l_erreur_est_dite(self):
        with mock.patch.object(ml.MoteurOpenAI, "actif", lambda self: False), mock.patch.object(X, "supprimer_modele", mock.Mock(side_effect=PermissionError())), mock.patch.object(ml.time, "sleep", lambda s: None):
            with self.assertRaises(ml.ErreurMoteur) as e:
                self.mo.supprimer_modele("A-exl3")
        self.assertIn("arrête ExLlamaV3", str(e.exception))

    def test_le_demarrage_donne_au_serveur_le_contexte_des_reglages(self):
        vus = []
        with mock.patch.object(X, "demarrer", lambda port, dossiers=None, **k: vus.append(k.get("contexte"))), mock.patch.object(ml.MoteurExterne, "_contexte", lambda self: 20480):
            self.mo.faire("demarrer", lambda *a: None)
        self.assertEqual(vus, [20480])

    def test_les_serveurs_installes_sont_dits_pour_la_liste_deroulante(self):
        with mock.patch.object(ml.MoteurExterne, "_exl", lambda self: {"tabby": SHA, "lib": "1"}), mock.patch.object(ml.MoteurExterne, "_colibri", lambda self: None), mock.patch.object(ml.MoteurExterne, "_lms", lambda self: None):
            self.assertEqual(ml.vue_reglages("openai")["serveurs_geres"], {"exllamav3": True, "colibri": False, "lmstudio": False})

    def test_la_grille_dit_que_lutin_telecharge_et_installe_exllamav3(self):
        g = self.mo.grille()
        self.assertEqual(g["telechargement"][0], "adapte")
        self.assertEqual(g["installation"][0], "non_teste")


if __name__ == "__main__":
    unittest.main()
