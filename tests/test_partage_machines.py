"""Partage entre machines : conversations (en jaune dans la liste), skills et mémoire importés à la demande, avec l'accord du propriétaire de la machine prêtée ; et le bug Docker des modèles téléchargés pour llama.cpp."""
import http.client
import json
import os
import tempfile
import threading
import unittest
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-partage-m-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import moteur as A  # noqa: E402
from lutin import machines, moteurs  # noqa: E402
from lutin import moteur_llamacpp as ml  # noqa: E402


def faux_blob(dossier, modele_nom="qwen3", tag="8b"):
    """Un modèle rangé comme Ollama le fait (manifeste + morceau), que Lutin lit pour llama.cpp."""
    (dossier / "blobs").mkdir(parents=True, exist_ok=True)
    return dossier


class ModelesTelechargesSousDocker(unittest.TestCase):
    """Le bug : sous Docker, `partages()` rendait toujours {} : un modèle téléchargé pour llama.cpp n'apparaissait jamais."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-docker-mod-"))
        self.avant = dict(moteurs.CONTEXTE)
        moteurs.CONTEXTE.update(donnees=lambda: self.tmp, en_docker=lambda: True, hors_ligne=lambda: False, dossier_ollama=lambda: self.tmp / "ollama-autre")
        self.addCleanup(lambda: (moteurs.CONTEXTE.clear(), moteurs.CONTEXTE.update(self.avant)))
        ml.CACHE_PARTAGE.clear()
        self.mo = ml.MoteurLlamaCpp()
        self.lib = self.tmp / "bibliotheque"

    def test_les_modeles_de_lutin_sont_listes_sous_docker_pas_ceux_d_ollama(self):
        lus = []

        def lire(dossier):
            lus.append(Path(dossier) if dossier else None)
            return {"qwen3:8b": {"fichier": Path(dossier) / "blob", "taille": 5_000_000_000, "projecteur": None}}
        with mock.patch.object(self.mo, "bibliotheque", lambda: self.lib), mock.patch("lutin.ollama_partage.lire", lire):
            communs = self.mo.partages()
        self.assertEqual(list(communs), ["qwen3:8b"])
        self.assertEqual(communs["qwen3:8b"]["origine"], "lutin")
        self.assertEqual(lus, [self.lib], "sous Docker, le dossier d'Ollama (un autre conteneur) n'est pas lu ; la bibliothèque de Lutin, si")

    def test_le_modele_telecharge_apparait_dans_la_liste_des_modeles_installes(self):
        with mock.patch.object(self.mo, "bibliotheque", lambda: self.lib), mock.patch("lutin.ollama_partage.lire", lambda d: {"granite4:3b": {"fichier": Path(d) / "b", "taille": 2_000_000_000, "projecteur": None}}):
            m = self.mo.modeles()
        self.assertIn("granite4:3b", m["installes"])
        self.assertEqual(m["tailles"]["granite4:3b"], 2_000_000_000)

    def test_hors_docker_rien_ne_change_et_un_serveur_externe_n_a_pas_de_modele_local(self):
        moteurs.CONTEXTE["en_docker"] = lambda: False
        lus = []
        with mock.patch.object(self.mo, "bibliotheque", lambda: self.lib), mock.patch("lutin.ollama_partage.lire", lambda d: lus.append(d) or {}):
            ml.CACHE_PARTAGE.clear()
            self.mo.partages()
        self.assertEqual(len(lus), 2, "hors Docker : le dossier d'Ollama ET la bibliothèque")
        with mock.patch.object(self.mo, "externe", lambda: True):
            self.assertEqual(self.mo.partages(), {})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-partage-t-"))
        machines.DOSSIER = self.tmp
        for c in (machines.REGISTRE, machines.CONVERSATIONS, machines.DISTANTS):
            c.update(t=0.0)
        machines.SONDES.clear()
        self.addCleanup(setattr, machines, "DOSSIER", None)
        self.m = {"id": "c" * 32, "nom": "Gaming PC", "adresse": "http://192.168.1.20:8777", "jeton": "t", "mac": "", "ajoutee": "x"}
        machines._ecrire_registre([self.m])


class DroitsDuNoeud(Base):
    def test_rien_n_est_partage_par_defaut_et_chaque_droit_se_donne_et_se_retire(self):
        self.assertEqual(machines.noeud_droits(), {"skills": False, "memoire": False})
        machines.noeud_droit("skills", True)
        self.assertEqual(machines.noeud_droits()["skills"], True)
        self.assertTrue(machines.noeud_vue()["droits"]["skills"])
        machines.noeud_droit("skills", False)
        self.assertFalse(machines.noeud_droits()["skills"])
        with self.assertRaises(ValueError):
            machines.noeud_droit("tout", True)

    def test_sans_droit_le_noeud_refuse(self):
        for genre in ("conversations", "skills", "skill", "memoire"):
            with self.assertRaises(PermissionError, msg=genre):
                machines.noeud_partager(genre, {"id": "0" * 8, "nom": "x.md"})
        with self.assertRaises(ValueError):
            machines.noeud_partager("autre-chose", {})

    def test_le_droit_ouvre_seulement_ce_qui_est_coche(self):
        machines.noeud_droit("memoire", True)
        with mock.patch.object(A, "lire_memoire", lambda nom: "texte " + nom):
            r = machines.noeud_partager("memoire", {})
        self.assertEqual(r["memoire"]["MEMOIRE.md"], "texte MEMOIRE.md")
        with self.assertRaises(PermissionError):
            machines.noeud_partager("skills", {})


class ImporterSkillsEtMemoire(Base):
    def faux_partage(self, reponses):
        def demander(m, genre, **corps):
            r = reponses[genre]
            return r(corps) if callable(r) else r
        return mock.patch.object(machines, "demander_partage", demander)

    def test_la_liste_distante_ne_montre_que_les_machines_qui_se_laissent_piloter(self):
        machines.DERNIER_ETAT[self.m["id"]] = "operationnel"          # la machine répond : ses listes sont proposées
        machines.SONDES[self.m["id"]] = (machines.time.monotonic(), {}, "")          # ... et vient de répondre
        reponses = {"conversations": {"conversations": [{"id": "e" * 8, "titre": "T", "maj": "m", "messages": 3}]}}
        with self.faux_partage(reponses), mock.patch.object(machines, "sonder", lambda m, modele="", *a, **kw: {"etat": "operationnel", "detail": "", "modeles": [], "agir": {"piloter": True}}):
            l = machines.conversations_distantes(attente=True)
        self.assertEqual([(c["id"], c["machine_nom"]) for c in l], [("e" * 8, "Gaming PC")])
        machines.CONVERSATIONS.update(t=0.0, v=[])
        with self.faux_partage(reponses), mock.patch.object(machines, "sonder", lambda m, modele="", *a, **kw: {"etat": "operationnel", "detail": "", "modeles": [], "agir": {"piloter": False}}):
            self.assertEqual(machines.conversations_distantes(attente=True), [])

    def test_importer_les_skills_les_deux_jeux_se_cumulent_sans_rien_ecraser(self):
        ecrits = {}
        locaux = {"local.md": "à moi", "commun.md": "version d'ici"}

        def lire(nom):
            if nom not in locaux:
                raise FileNotFoundError(nom)
            return locaux[nom]

        def ecrire(nom, texte):
            locaux[nom] = texte
            ecrits[nom] = texte
        reponses = {"skills": {"skills": [{"nom": "distant.md", "titre": "D"}, {"nom": "commun.md", "titre": "C"}]}, "skill": lambda c: {"nom": c["nom"], "texte": "version de là-bas " + c["nom"]}}
        with self.faux_partage(reponses), mock.patch.object(A, "lire_skill", lire), mock.patch.object(A, "ecrire_skill", ecrire):
            r = machines.importer_skills(self.m["id"])
        self.assertEqual(r, {"ajoutes": 1, "mis_a_jour": 0, "deja_la": 1})
        self.assertEqual(ecrits, {"distant.md": "version de là-bas distant.md"})
        self.assertEqual(locaux["commun.md"], "version d'ici", "un skill qui existe ici n'est jamais écrasé")
        # l'original a changé et la copie n'a pas bougé : mise à jour
        reponses["skill"] = lambda c: {"nom": c["nom"], "texte": "nouvelle version " + c["nom"]}
        with self.faux_partage(reponses), mock.patch.object(A, "lire_skill", lire), mock.patch.object(A, "ecrire_skill", ecrire):
            r = machines.importer_skills(self.m["id"])
        self.assertEqual((r["ajoutes"], r["mis_a_jour"], locaux["distant.md"]), (0, 1, "nouvelle version distant.md"))
        # la copie a été retouchée ici : plus de mise à jour
        locaux["distant.md"] = "retouché ici"
        reponses["skill"] = lambda c: {"nom": c["nom"], "texte": "encore une version " + c["nom"]}
        with self.faux_partage(reponses), mock.patch.object(A, "lire_skill", lire), mock.patch.object(A, "ecrire_skill", ecrire):
            machines.importer_skills(self.m["id"])
        self.assertEqual(locaux["distant.md"], "retouché ici")

    def test_importer_la_memoire_ajoute_les_notes_manquantes_sous_un_titre(self):
        stock = {"MEMOIRE.md": "- J'aime le café\n- Projet Lutin", "CONTEXTE.md": ""}
        reponses = {"memoire": {"memoire": {"MEMOIRE.md": "# Titre\n- J'aime le café\n- Je travaille sur Lutin\n- Mini PC sous Debian", "CONTEXTE.md": "Profil de là-bas"}}}
        ecrits = {}
        with self.faux_partage(reponses), mock.patch.object(A, "lire_memoire", lambda n: stock[n]), mock.patch.object(A, "ecrire_memoire", lambda n, t: ecrits.update({n: t})):
            r = machines.importer_memoire(self.m["id"])
        self.assertEqual((r["notes_ajoutees"], r["profil_copie"]), (2, True))
        self.assertIn("Depuis Gaming PC", ecrits["MEMOIRE.md"])
        self.assertIn("Mini PC sous Debian", ecrits["MEMOIRE.md"])
        self.assertEqual(ecrits["MEMOIRE.md"].count("café"), 1, "une note déjà là n'est pas dupliquée")
        self.assertEqual(ecrits["CONTEXTE.md"], "Profil de là-bas")

    def test_une_memoire_pleine_n_est_pas_rognee_et_ce_qui_est_ignore_est_dit(self):
        """Avant : (local + notes)[-59000:] jetait le DÉBUT du fichier local (ses décisions) en silence. Maintenant : on n'ajoute que ce qui tient, le local reste intact, et on dit combien de notes sont ignorées."""
        local = "# Décisions\n- DECISION-FIXE\n" + "".join("- ancienne note %04d %s\n" % (i, "x" * 50) for i in range(700))
        distantes = "\n".join("- note venue de là-bas numéro %04d %s" % (i, "y" * 60) for i in range(300))
        stock, ecrits = {"MEMOIRE.md": local, "CONTEXTE.md": ""}, {}
        with self.faux_partage({"memoire": {"memoire": {"MEMOIRE.md": distantes, "CONTEXTE.md": "c" * 70000}}}), mock.patch.object(A, "lire_memoire", lambda n: stock[n]), mock.patch.object(A, "ecrire_memoire", lambda n, t: ecrits.update({n: t})):
            r = machines.importer_memoire(self.m["id"])
        self.assertLessEqual(len(ecrits["MEMOIRE.md"]), machines.LIMITE_MEMOIRE)
        self.assertTrue(ecrits["MEMOIRE.md"].startswith("# Décisions\n- DECISION-FIXE"), "le début du fichier local est intact")
        self.assertGreater(r["notes_ignorees"], 0)
        self.assertEqual(r["notes_ajoutees"] + r["notes_ignorees"], 300)
        self.assertTrue(r["profil_coupe"])
        self.assertEqual(len(ecrits["CONTEXTE.md"]), machines.LIMITE_MEMOIRE)

    def test_le_profil_existant_n_est_pas_ecrase(self):
        stock = {"MEMOIRE.md": "", "CONTEXTE.md": "Mon profil"}
        ecrits = {}
        with self.faux_partage({"memoire": {"memoire": {"MEMOIRE.md": "", "CONTEXTE.md": "Autre profil"}}}), mock.patch.object(A, "lire_memoire", lambda n: stock[n]), mock.patch.object(A, "ecrire_memoire", lambda n, t: ecrits.update({n: t})):
            r = machines.importer_memoire(self.m["id"])
        self.assertEqual((r["notes_ajoutees"], r["profil_copie"], ecrits), (0, False, {}))

    def test_refus_du_noeud_message_clair(self):
        erreur = urllib.error.HTTPError("http://x", 403, "interdit", {}, None)
        with mock.patch.object(machines, "_json", side_effect=erreur):
            with self.assertRaises(ValueError) as e:
                machines.demander_partage(self.m, "skills")
        self.assertIn("ne partage pas cela", str(e.exception))
        with mock.patch.object(machines, "_json", side_effect=urllib.error.URLError("hors réseau")):
            with self.assertRaises(ValueError) as e:
                machines.demander_partage(self.m, "skills")
        self.assertIn("Impossible de joindre", str(e.exception))


class Api(Base):
    @classmethod
    def setUpClass(cls):
        from lutin import securite as S
        cls.serveur = ThreadingHTTPServer(("127.0.0.1", 0), A.Gestionnaire)
        threading.Thread(target=cls.serveur.serve_forever, daemon=True).start()
        cls.port = cls.serveur.server_address[1]
        cls.avant = A.SECURITE
        A.SECURITE = S.Securite(niveau=S.LOCAL)

    @classmethod
    def tearDownClass(cls):
        A.SECURITE = cls.avant
        cls.serveur.shutdown()

    def appel(self, methode, chemin, corps=None, en_tetes=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = dict({"Host": "127.0.0.1:%d" % self.port, "X-Token": A.JETON}, **(en_tetes or {}))
        donnees = json.dumps(corps).encode() if corps is not None else None
        if donnees:
            h["Content-Type"] = "application/json"
        c.request(methode, chemin, body=donnees, headers=h)
        r = c.getresponse()
        texte = r.read().decode("utf-8")
        c.close()
        return r.status, json.loads(texte) if texte else {}

    def test_le_noeud_ne_partage_qu_avec_un_jeton_valide_et_un_droit_coche(self):
        machines.noeud_activer(True)
        code = machines.noeud_nouveau_code()
        # un jeton de nœud réel, obtenu par l'échange du code
        jeton = machines.noeud_echanger(code["code"], "Mini PC")["jeton"]
        entetes = {"X-Noeud": jeton}
        self.assertEqual(self.appel("POST", "/api/noeud/partage", {"genre": "skills"}, {"X-Token": "faux", "X-Noeud": "faux"})[0], 401)
        self.assertEqual(self.appel("POST", "/api/noeud/partage", {"genre": "skills"}, entetes)[0], 403, "pas coché : refusé")
        machines.noeud_droit("skills", True)
        with mock.patch.object(A, "lister_skills", lambda: [("a.md", "Titre A")]):
            statut, r = self.appel("POST", "/api/noeud/partage", {"genre": "skills"}, entetes)
        self.assertEqual((statut, r["skills"]), (200, [{"nom": "a.md", "titre": "Titre A"}]))
        self.assertEqual(self.appel("POST", "/api/noeud/partage", {"genre": "conversations"}, entetes)[0], 403, "seul ce qui est coché est ouvert (piloter n'est pas coché)")
        self.assertEqual(self.appel("POST", "/api/noeud/partage", {"genre": "inconnu"}, entetes)[0], 400)

    def test_le_droit_ne_se_donne_que_depuis_cette_machine(self):
        statut, r = self.appel("POST", "/api/machines-droit", {"droit": "memoire", "actif": True})
        self.assertEqual(statut, 200)
        self.assertTrue(machines.noeud_droits()["memoire"])
        self.assertEqual(self.appel("POST", "/api/machines-droit", {"droit": "nimporte", "actif": True})[0], 400)
        self.assertTrue(self.appel("GET", "/api/machines")[1]["noeud"]["droits"]["memoire"])


if __name__ == "__main__":
    unittest.main()
