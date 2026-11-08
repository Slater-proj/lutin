"""Machines distantes, deuxième vague d'essais : adresse MAC reçue du nœud, réveil vérifié, démarrage automatique sans droits d'administrateur, modèles de l'autre machine dans la liste de choix, modèle qui annonce sans agir."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-distantes-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import affirmations, alimentation, machines  # noqa: E402


class FauxRegistre:
    def __init__(self, refuse=False):
        self.valeurs, self.refuse = {}, refuse

    def lire(self, nom):
        return self.valeurs.get(nom, "")

    def ecrire(self, nom, valeur):
        if self.refuse:
            raise PermissionError(5, "Accès refusé")
        self.valeurs[nom] = valeur

    def supprimer(self, nom):
        self.valeurs.pop(nom, None)


class AdresseMac(unittest.TestCase):
    def test_normalisee(self):
        self.assertEqual(alimentation.normaliser_mac("00-1a-2b-3c-4d-5e"), "00:1A:2B:3C:4D:5E")
        self.assertEqual(alimentation.normaliser_mac("001a2b3c4d5e"), "00:1A:2B:3C:4D:5E")
        for mauvaise in ("", "00:00:00:00:00:00", "01:00:5e:00:00:01", "zz:1a:2b:3c:4d:5e", "00:1a:2b"):
            self.assertEqual(alimentation.normaliser_mac(mauvaise), "", mauvaise)

    def test_cartes_windows_lues_du_json(self):
        texte = json.dumps([{"nom": "Ethernet", "description": "Intel I225-V", "mac": "00-1A-2B-3C-4D-5E", "etat": "Up", "ip": "192.168.1.20", "reveil": True},
                            {"nom": "Wi-Fi", "description": "Intel Wi-Fi 6", "mac": "AA-BB-CC-DD-EE-02", "etat": "Up", "ip": "192.168.1.21", "reveil": None},
                            {"nom": "Ancienne", "description": "x", "mac": "00-1A-2B-3C-4D-5F", "etat": "Disconnected", "ip": "", "reveil": False}])
        cartes = alimentation.analyser_cartes_windows(texte)
        self.assertEqual([c["nom"] for c in cartes], ["Ethernet", "Wi-Fi"], "une carte débranchée n'est pas retenue")
        self.assertTrue(cartes[0]["filaire"])
        self.assertFalse(cartes[1]["filaire"])
        self.assertEqual(alimentation.analyser_cartes_windows("pas du json"), [])

    def test_la_carte_retenue_est_celle_de_l_adresse_utilisee(self):
        cartes = [{"nom": "wifi", "mac": "AA:BB:CC:DD:EE:02", "ip": "192.168.1.21", "filaire": False, "reveil": None}, {"nom": "eth", "mac": "00:1A:2B:3C:4D:5E", "ip": "192.168.1.20", "filaire": True, "reveil": True}]
        self.assertEqual(alimentation.choisir_carte(cartes, "192.168.1.21")["nom"], "wifi")
        self.assertEqual(alimentation.choisir_carte(cartes, "10.0.0.1")["nom"], "eth", "sinon une carte filaire")
        self.assertIsNone(alimentation.choisir_carte([], ""))

    def test_cartes_linux_lues_dans_sys(self):
        racine = Path(tempfile.mkdtemp(prefix="lutin-sys-"))
        for nom, mac, materiel, etat in (("enp3s0", "00:1a:2b:3c:4d:5e", True, "up"), ("lo", "00:00:00:00:00:00", False, "unknown"), ("docker0", "02:42:ac:11:00:01", False, "up"), ("enp4s0", "00:1a:2b:3c:4d:5f", True, "down")):
            d = racine / nom
            d.mkdir()
            (d / "address").write_text(mac + "\n")
            (d / "operstate").write_text(etat + "\n")
            if materiel:
                (d / "device").mkdir()

        class Sortie:
            stdout = b"Settings for enp3s0:\n\tWake-on: g\n"
        cartes = alimentation.cartes_reseau(lanceur=lambda cmd, **kw: Sortie(), systeme_actuel="linux", racine_sys=str(racine), sortie_ip="2: enp3s0    inet 192.168.1.20/24 brd 192.168.1.255 scope global enp3s0\n")
        self.assertEqual([(c["nom"], c["mac"], c["ip"], c["reveil"]) for c in cartes], [("enp3s0", "00:1A:2B:3C:4D:5E", "192.168.1.20", True)])


class ReveilVerifie(unittest.TestCase):
    CARTE = {"nom": "Ethernet", "mac": "00:1A:2B:3C:4D:5E", "ip": "192.168.1.20", "filaire": True}

    def etat(self, **kw):
        return alimentation.etat_reveil("192.168.1.20", cartes=[dict(self.CARTE, **kw)], systeme_actuel="windows", demarrage_rapide=False)

    def test_tout_est_en_regle(self):
        e = self.etat(reveil=True)
        self.assertEqual((e["pret"], e["mac"], e["avertissements"]), (True, "00:1A:2B:3C:4D:5E", []))

    def test_reveil_desactive_on_avertit_avec_la_marche_a_suivre(self):
        e = self.etat(reveil=False)
        self.assertFalse(e["pret"])
        self.assertIn("Wake-on-LAN", e["avertissements"][0])
        self.assertIn("BIOS", e["avertissements"][0])

    def test_impossible_a_verifier_on_le_dit(self):
        e = self.etat(reveil=None)
        self.assertIsNone(e["pret"])
        self.assertIn("Impossible de vérifier", e["avertissements"][0])

    def test_wifi_et_demarrage_rapide(self):
        e = alimentation.etat_reveil("", cartes=[dict(self.CARTE, filaire=False, reveil=True)], systeme_actuel="windows", demarrage_rapide=True)
        self.assertFalse(e["pret"])
        texte = " ".join(e["avertissements"])
        self.assertIn("Wi-Fi", texte)
        self.assertIn("démarrage rapide", texte)

    def test_docker_et_machine_sans_carte(self):
        d = alimentation.etat_reveil("", en_docker=True)
        self.assertIsNone(d["pret"])
        self.assertIn("conteneur", d["avertissements"][0])
        self.assertIn("à la main", alimentation.etat_reveil("", cartes=[], systeme_actuel="linux")["avertissements"][0])


class DemarrageAutomatique(unittest.TestCase):
    def test_windows_sans_droits_d_administrateur_par_la_cle_run(self):
        reg = FauxRegistre()

        def lanceur(cmd, **kw):
            raise AssertionError("aucune tâche planifiée ne doit être créée (elle demande les droits d'administrateur) : {}".format(cmd))
        ancien = alimentation.subprocess.list2cmdline
        self.assertEqual(ancien(["python", "-m", "lutin"]), "python -m lutin")
        e = alimentation.installer_demarrage(lanceur=lambda cmd, **kw: type("R", (), {"returncode": 1})(), systeme_actuel="windows", commande=["C:/Python/python.exe", "-m", "lutin", "serve", "--sans-navigateur"], registre=reg)
        self.assertTrue(e["installe"])
        self.assertIn("lutin serve --sans-navigateur", reg.valeurs["Lutin"])
        self.assertEqual(lanceur.__name__, "lanceur")

    def test_retirer_efface_la_cle_et_l_ancienne_tache(self):
        reg = FauxRegistre()
        reg.valeurs["Lutin"] = "x"
        appels = []
        e = alimentation.retirer_demarrage(lanceur=lambda cmd, **kw: appels.append(cmd) or type("R", (), {"returncode": 1})(), systeme_actuel="windows", registre=reg)
        self.assertFalse(e["installe"])
        self.assertNotIn("Lutin", reg.valeurs)
        self.assertTrue(any("/Delete" in c for c in appels), "l'ancienne tâche planifiée d'une version précédente est retirée aussi")

    def test_une_ancienne_tache_planifiee_compte_comme_installee(self):
        reg = FauxRegistre()
        e = alimentation.etat_demarrage(lanceur=lambda cmd, **kw: type("R", (), {"returncode": 0})(), systeme_actuel="windows", registre=reg)
        self.assertTrue(e["installe"])

    def test_refus_de_windows_dit_clairement(self):
        with self.assertRaises(ValueError) as e:
            alimentation.installer_demarrage(systeme_actuel="windows", commande=["python"], registre=FauxRegistre(refuse=True))
        self.assertIn("refusé", str(e.exception))


class MachinesInfos(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lutin-mi-"))
        machines.DOSSIER = self.tmp
        machines.REGISTRE.update(t=0.0)
        machines.SONDES.clear()
        machines.DISTANTS.update(t=0.0, v=[], en_cours=False)
        self.addCleanup(setattr, machines, "DOSSIER", None)
        self.m = {"id": "a" * 32, "nom": "Gros PC", "adresse": "http://192.168.1.20:8777", "jeton": "t", "mac": "", "ajoutee": "x"}
        machines._ecrire_registre([self.m])

    def test_l_adresse_mac_recue_complete_celle_qui_manque_sans_ecraser_la_saisie(self):
        machines.retenir_infos(dict(self.m), {"mac": "00-1a-2b-3c-4d-5e", "reveil": {"pret": True, "avertissements": []}, "demarrage": {"installe": True, "possible": True}})
        m = machines.trouver(self.m["id"])
        self.assertEqual((m["mac"], m["mac_auto"]), ("00:1A:2B:3C:4D:5E", True))
        machines.definir_mac(self.m["id"], "AA:BB:CC:DD:EE:01")
        machines.retenir_infos(dict(m), {"mac": "00:1A:2B:3C:4D:5E"})
        self.assertEqual(machines.trouver(self.m["id"])["mac"], "AA:BB:CC:DD:EE:01", "la saisie à la main n'est jamais écrasée")

    def test_avertissements_reveil_et_demarrage(self):
        sans = dict(self.m)
        self.assertIn("Adresse MAC inconnue", " ".join(machines.avertissements(sans)))
        pas_pret = dict(self.m, mac="00:1A:2B:3C:4D:5E", reveil={"pret": False, "avertissements": ["Le Wake-on-LAN est désactivé."]}, demarrage={"installe": False, "possible": True})
        texte = " ".join(machines.avertissements(pas_pret))
        self.assertIn("Wake-on-LAN est désactivé", texte)
        self.assertIn("ne démarre pas tout seul", texte)
        docker = dict(self.m, mac="00:1A:2B:3C:4D:5E", demarrage={"docker": True, "installe": False, "possible": False})
        self.assertIn("restart: unless-stopped", " ".join(machines.avertissements(docker)))
        pret = dict(self.m, mac="00:1A:2B:3C:4D:5E", reveil={"pret": True, "avertissements": []}, demarrage={"installe": True, "possible": True})
        self.assertEqual(machines.avertissements(pret), [])

    def test_le_reveil_dit_ce_qui_risque_de_l_empecher(self):
        machines._ecrire_registre([dict(self.m, mac="00:1A:2B:3C:4D:5E", reveil={"pret": False, "avertissements": ["Wake-on-LAN désactivé."]})])
        rep = machines.reveiller(self.m["id"], envoyer=lambda mac, hote: [(hote, 9)])
        self.assertTrue(rep["ok"])
        self.assertIn("Wake-on-LAN désactivé.", rep["avertissements"])

    def test_noeud_etat_donne_mac_reveil_demarrage(self):
        class Moteur:
            id, nom = "ollama", "Ollama"
        with mock.patch.object(alimentation, "etat_reveil", lambda ip, **kw: {"mac": "00:1A:2B:3C:4D:5E", "carte": "eth", "pret": True, "avertissements": []}), \
                mock.patch.object(alimentation, "etat_demarrage", lambda: {"installe": True, "possible": True}),                 mock.patch.object(alimentation, "cartes_reseau", lambda **kw: []):
            machines.INFOS_NOEUD.clear()
            machines.CARTES.update(t=-999.0, v=None)
            e = machines.noeud_etat(Moteur(), {"actif": True, "installes": ["gros:70b"]}, "192.168.1.20")
        self.assertEqual((e["mac"], e["reveil"]["pret"], e["demarrage"]["installe"], e["modeles"]), ("00:1A:2B:3C:4D:5E", True, True, ["gros:70b"]))

    def test_modeles_distants_et_choix_d_un_modele_qui_n_existe_que_la_bas(self):
        machines.DERNIER_ETAT[self.m["id"]] = "operationnel"          # la machine répond : ses listes sont proposées
        reponses = {"etat": "operationnel", "detail": "", "modeles": ["gros:70b", "autre:32b"]}
        with mock.patch.object(machines, "sonder", lambda m, modele="", *a, **kw: reponses):
            liste = machines.modeles_distants(attente=True)
        self.assertEqual([(d["nom"], d["modeles"]) for d in liste], [("Gros PC", ["gros:70b", "autre:32b"])])
        reg = {"machine": self.m["id"], "modele": "gros:70b"}
        self.assertIsNotNone(machines.modele_distant(reg, ["petit:8b"]))
        self.assertIsNone(machines.modele_distant(reg, ["gros:70b"]), "présent ici aussi : pas un modèle distant")
        self.assertIsNone(machines.modele_distant({"machine": "", "modele": "gros:70b"}, []))
        # la machine s'éteint : sa dernière liste reste visible (grisée dans le choix)
        with mock.patch.object(machines, "sonder", lambda m, modele="", *a, **kw: {"etat": "injoignable", "detail": "", "modeles": []}):
            machines.DISTANTS["t"] = 0.0
            hors = machines.modeles_distants(attente=True)
        self.assertEqual((hors[0]["etat"], hors[0]["modeles"]), ("injoignable", ["gros:70b", "autre:32b"]))

    def test_modele_de_l_autre_machine_injoignable_erreur_claire_au_lieu_d_un_modele_introuvable(self):
        machines.DISTANTS.update(t=machines.time.monotonic(), v=[{"id": self.m["id"], "nom": "Gros PC", "etat": "operationnel", "modeles": ["gros:70b"]}])

        class Local:
            id, nom = "ollama", "Ollama"

            def modeles(self):
                return {"actif": True, "installes": ["petit:8b"]}

            def chat(self, corps, delai=60):
                raise AssertionError("le moteur local n'a pas ce modèle : il ne doit pas répondre")
        r = machines.Routage(Local(), self.m)
        with mock.patch.object(machines, "sonder", lambda m, modele="", *a, **kw: {"etat": "injoignable", "detail": "", "modeles": []}):
            with self.assertRaises(ValueError) as e:
                r.chat({"model": "gros:70b", "messages": []})
        self.assertIn("n'existe que sur la machine « Gros PC »", str(e.exception))

    def test_capacites_du_modele_distant_viennent_de_la_machine(self):
        class Local:
            id, nom = "ollama", "Ollama"

            def modeles(self):
                return {"actif": True, "installes": ["petit:8b"]}

            def capacites(self, modele):
                return {"tools"}
        r = machines.Routage(Local(), self.m)
        machines.CAPACITES_DISTANTES.clear()
        with mock.patch.object(machines, "_json", lambda m, chemin, corps=None, **kw: {"capacites": ["tools", "thinking"]}):
            self.assertEqual(r.capacites("gros:70b"), {"tools", "thinking"})
        self.assertEqual(r.capacites("petit:8b"), {"tools"}, "un modèle d'ici garde les capacités d'ici")


class InfosEnArrierePlan(unittest.TestCase):
    """L'appairage n'attend jamais PowerShell : il rend des informations vides si la lecture des cartes est lente, l'autre machine les recevra à sa prochaine sonde."""

    def test_une_lecture_lente_ne_bloque_pas_l_appairage_puis_les_infos_arrivent(self):
        import threading
        import time
        machines.INFOS_NOEUD.clear()
        machines.INFOS_EN_COURS.clear()
        libere = threading.Event()

        def lent(ip, **kw):
            libere.wait(5)
            return {"mac": "00:1A:2B:3C:4D:5E", "carte": "eth", "pret": True, "avertissements": []}
        with mock.patch.object(alimentation, "etat_reveil", lent), mock.patch.object(alimentation, "etat_demarrage", lambda: {"installe": True, "possible": True}),                 mock.patch.object(alimentation, "cartes_reseau", lambda **kw: []):
            machines.CARTES.update(t=-999.0, v=None)
            debut = time.monotonic()
            infos = machines.noeud_infos("10.0.0.1", attente=0.2)
            self.assertLess(time.monotonic() - debut, 1.5)
            self.assertEqual(infos["mac"], "", "pas encore prêt : informations vides, pas d'erreur")
            libere.set()
            for _ in range(50):
                if "10.0.0.1" in machines.INFOS_NOEUD:
                    break
                time.sleep(0.05)
            self.assertEqual(machines.noeud_infos("10.0.0.1", attente=0.2)["mac"], "00:1A:2B:3C:4D:5E")


class AnnonceSansAction(unittest.TestCase):
    OUTILS = {"voix_liste", "voix_parler"}

    def test_une_simple_annonce_est_relancee(self):
        for texte in ("Je vais vérifier si le profil Arnold 2 est disponible dans VoiceStudio.", "Un instant, je regarde.", "Laisse-moi chercher cela."):
            self.assertTrue(affirmations.annonce_sans_agir(texte, [], self.OUTILS), texte)

    def test_une_vraie_reponse_n_est_pas_touchee(self):
        self.assertEqual(affirmations.annonce_sans_agir("Oui, le profil Arnold 2 est disponible : je le vois dans la liste de VoiceStudio, avec la voix clonée le 3 mars et deux échantillons enregistrés.", [], self.OUTILS), "")
        self.assertEqual(affirmations.annonce_sans_agir("Voici la liste : a, b, c.", [], self.OUTILS), "")

    def test_rien_quand_il_agit_deja_ou_sans_outils(self):
        self.assertEqual(affirmations.annonce_sans_agir("Je vais vérifier.", [{"function": {"name": "voix_liste"}}], self.OUTILS), "")
        self.assertEqual(affirmations.annonce_sans_agir("Je vais vérifier.", [], set()), "")
        self.assertEqual(affirmations.annonce_sans_agir("Je vais " + "vérifier " * 60, [], self.OUTILS), "", "une longue réponse n'est pas une annonce")


if __name__ == "__main__":
    unittest.main()
