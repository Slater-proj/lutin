"""Alimentation (D8) : paquet de réveil, états « réveil envoyé → joignable → opérationnel », extinction autorisée/annulable/journalisée, démarrage automatique."""
import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-alim-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import alimentation, machines  # noqa: E402

import test_machines as tm  # noqa: E402


class Reveil(unittest.TestCase):
    def test_le_paquet_magique(self):
        p = alimentation.paquet_magique("00:1A:2b:3C:4d:5E")
        self.assertEqual(len(p), 102)
        self.assertEqual(p[:6], b"\xff" * 6)
        self.assertEqual(p[6:12], bytes.fromhex("001A2b3C4d5E"))
        self.assertEqual(p[6:12] * 16, p[6:])

    def test_adresse_mac_invalide(self):
        for mauvaise in ("", "zz:zz", "00:1A:2B:3C:4D", "00-1A-2B-3C-4D-5E-6F"):
            with self.assertRaises(ValueError):
                alimentation.paquet_magique(mauvaise)
        alimentation.paquet_magique("00-1A-2B-3C-4D-5E")

    def test_diffusion_du_reseau_de_la_machine(self):
        self.assertEqual(alimentation.diffusions("192.168.1.20"), ["255.255.255.255", "192.168.1.255"])
        self.assertEqual(alimentation.diffusions("poste.local"), ["255.255.255.255"])

    def test_envoi_udp_vers_les_deux_ports(self):
        envoyes = []

        class Faux:
            def __init__(self, *a):
                pass

            def setsockopt(self, *a):
                pass

            def sendto(self, donnees, cible):
                envoyes.append((len(donnees), cible))

            def close(self):
                pass
        r = alimentation.envoyer_reveil("00:1A:2B:3C:4D:5E", "192.168.1.20", socket_factory=Faux, locales=[])
        self.assertEqual(len(r), 6)
        self.assertIn((102, ("192.168.1.20", 9)), envoyes)
        self.assertIn((102, ("192.168.1.255", 9)), envoyes)
        self.assertIn((102, ("255.255.255.255", 7)), envoyes)

    def test_le_paquet_part_par_chaque_carte(self):
        liees, envoyes = [], []

        class Faux:
            def __init__(self, *a):
                self.source = ""

            def setsockopt(self, *a):
                pass

            def bind(self, adresse):
                self.source = adresse[0]
                liees.append(adresse[0])

            def sendto(self, donnees, cible):
                envoyes.append((self.source, cible))

            def close(self):
                pass
        alimentation.envoyer_reveil("00:1A:2B:3C:4D:5E", "192.168.1.20", socket_factory=Faux, locales=["10.8.0.2", "192.168.1.59"])
        self.assertEqual(liees, ["10.8.0.2", "192.168.1.59"])
        self.assertIn(("10.8.0.2", ("10.8.0.255", 9)), envoyes)
        self.assertIn(("192.168.1.59", ("192.168.1.255", 7)), envoyes)

    def test_un_vrai_paquet_arrive_par_udp(self):
        recepteur = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recepteur.bind(("127.0.0.1", 0))
        recepteur.settimeout(3)
        port = recepteur.getsockname()[1]
        orig = alimentation.diffusions
        with mock.patch.object(alimentation, "diffusions", lambda a="": ["127.0.0.1"]):
            alimentation.envoyer_reveil("00:1A:2B:3C:4D:5E", ports=(port,))
        donnees, _ = recepteur.recvfrom(200)
        recepteur.close()
        self.assertEqual(donnees, alimentation.paquet_magique("00:1A:2B:3C:4D:5E"))
        self.assertTrue(orig)

    def test_les_raisons_arrivent_apres_trois_minutes(self):
        self.assertEqual(alimentation.raison_echec(30), "")
        self.assertIn("BIOS", alimentation.raison_echec(alimentation.SEUIL_RAISONS_S + 1))
        self.assertIn("démarrage rapide", alimentation.raison_echec(400))


class Extinction(unittest.TestCase):
    def tearDown(self):
        alimentation.annuler_extinction()

    def test_extinction_apres_le_delai_et_journalisee(self):
        appels, journal = [], []
        alimentation.programmer_extinction("Petit PC", lanceur=lambda cmd, **k: appels.append(cmd), delai=0.05, systeme_actuel="linux", journaliser=journal.append)
        time.sleep(0.4)
        self.assertEqual(appels, [["systemctl", "poweroff"]])
        self.assertTrue(any("demandée par Petit PC" in j for j in journal))
        self.assertTrue(any("extinction lancée" in j for j in journal))

    def test_annuler_avant_le_delai(self):
        appels, journal = [], []
        alimentation.programmer_extinction("Petit PC", lanceur=lambda cmd, **k: appels.append(cmd), delai=0.5, systeme_actuel="windows", journaliser=journal.append)
        self.assertIsNotNone(alimentation.extinction_en_attente())
        self.assertTrue(alimentation.annuler_extinction(journal.append))
        time.sleep(0.8)
        self.assertEqual(appels, [], "rien n'a été lancé")
        self.assertIsNone(alimentation.extinction_en_attente())
        self.assertFalse(alimentation.annuler_extinction())

    def test_une_nouvelle_demande_remplace_la_precedente(self):
        appels = []
        for _ in range(2):
            alimentation.programmer_extinction("X", lanceur=lambda cmd, **k: appels.append(cmd), delai=0.1, systeme_actuel="linux")
        time.sleep(0.5)
        self.assertEqual(len(appels), 1)


class DemarrageAuto(unittest.TestCase):
    class Lanceur:
        def __init__(self, code=0):
            self.appels, self.code = [], code

        def __call__(self, cmd, **k):
            self.appels.append(cmd)

            class R:
                returncode, stdout, stderr = self.code, b"", b""
            return R()

    def test_linux_ecrit_une_unite_utilisateur(self):
        maison = Path(tempfile.mkdtemp(prefix="lutin-alim-home-"))
        lanceur = self.Lanceur()
        e = alimentation.installer_demarrage(lanceur, "linux", maison, commande=["/usr/bin/python3", "-m", "lutin", "serve"])
        unite = (maison / ".config" / "systemd" / "user" / "lutin.service").read_text(encoding="utf-8")
        self.assertIn("ExecStart=/usr/bin/python3 -m lutin serve", unite)
        self.assertIn("WantedBy=default.target", unite)
        self.assertTrue(e["installe"])
        self.assertIn(["systemctl", "--user", "enable", "lutin.service"], lanceur.appels)
        e = alimentation.retirer_demarrage(lanceur, "linux", maison)
        self.assertFalse(e["installe"])

    class Registre:
        """La clé « Run » de l'utilisateur : pas de droits d'administrateur, contrairement à une tâche planifiée à l'ouverture de session."""

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

    def test_windows_s_inscrit_a_l_ouverture_de_session_sans_tache_planifiee(self):
        lanceur, registre = self.Lanceur(code=1), self.Registre()
        e = alimentation.installer_demarrage(lanceur, "windows", commande=["C:\\Python\\python.exe", "-m", "lutin", "serve"], registre=registre)
        self.assertIn("-m lutin serve", registre.valeurs["Lutin"])
        self.assertTrue(e["installe"])
        self.assertFalse(any(c[:2] == ["schtasks", "/Create"] for c in lanceur.appels), "une tâche planifiée à l'ouverture de session demande les droits d'administrateur : Windows la refuse")

    def test_windows_refus_dit_pourquoi(self):
        with self.assertRaises(ValueError):
            alimentation.installer_demarrage(self.Lanceur(code=1), "windows", commande=["x"], registre=self.Registre(refuse=True))

    def test_les_limites_sont_dites(self):
        self.assertIn("auto-connexion", alimentation.limites("windows"))
        self.assertIn("enable-linger", alimentation.limites("linux"))

    def test_mac_non_pris_en_charge(self):
        self.assertFalse(alimentation.etat_demarrage(self.Lanceur(), "macos")["possible"])
        with self.assertRaises(ValueError):
            alimentation.installer_demarrage(self.Lanceur(), "macos")


class AvecDeuxServeurs(tm.Base):
    """Le principal réveille, voit « réveil envoyé » puis la machine répond ; il l'éteint si elle l'a autorisé."""

    def test_reveil_envoye_puis_joignable_puis_operationnel(self):
        m = self.jumeler()
        machines.definir_mac(m["id"], "00:1A:2B:3C:4D:5E")
        envois = []
        self.srv.shutdown()
        self.srv.server_close()
        machines.SONDES.clear()
        machines.reveiller(m["id"], envoyer=lambda mac, hote: envois.append((mac, hote)))
        self.assertEqual(envois, [("00:1A:2B:3C:4D:5E", "127.0.0.1")])
        mm = machines.trouver(m["id"])
        r = machines.sonder(mm, "m1", force=True)
        self.assertEqual(r["etat"], "reveil_envoye")
        self.assertIn("Réveil envoyé", r["detail"])
        # la machine démarre : son Lutin répond de nouveau
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), __import__("lutin.serveur", fromlist=["Gestionnaire"]).Gestionnaire)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.assertEqual(machines.sonder(mm, "m1", force=True)["etat"], "operationnel")
        self.assertNotIn(m["id"], machines.REVEIL, "le réveil est terminé")

    def test_apres_dix_minutes_le_reveil_n_est_plus_annonce(self):
        m = self.jumeler()
        self.srv.shutdown()
        self.srv.server_close()
        machines.REVEIL[m["id"]] = time.monotonic() - alimentation.ATTENTE_REVEIL_S - 5
        machines.SONDES.clear()
        self.assertEqual(machines.sonder(machines.trouver(m["id"]), "m1", force=True)["etat"], "injoignable")

    def test_reveiller_sans_adresse_mac_dit_quoi_faire(self):
        m = self.jumeler()
        machines.definir_mac(m["id"], "")          # l'adresse reçue du nœud a été effacée à la main
        with self.assertRaises(ValueError) as e:
            machines.reveiller(m["id"])
        self.assertIn("adresse MAC", str(e.exception))

    def test_l_extinction_est_refusee_tant_que_le_proprietaire_ne_l_a_pas_autorisee(self):
        m = self.jumeler()
        with self.assertRaises(ValueError) as e:
            machines.eteindre(m["id"])
        self.assertIn("Autoriser les machines appairées", str(e.exception))

    def test_extinction_autorisee_puis_annulee_et_journalisee(self):
        m = self.jumeler()
        machines.noeud_autoriser_extinction(True)
        appels = []
        with mock.patch.object(alimentation, "COMMANDES_EXTINCTION", {"linux": ["echo"], "windows": ["echo"], "macos": ["echo"]}), \
                mock.patch.object(alimentation.subprocess, "run", lambda cmd, **k: appels.append(cmd)):
            rep = machines.eteindre(m["id"])
            self.assertEqual(rep["dans_s"], alimentation.DELAI_EXTINCTION_S)
            self.assertIsNotNone(machines.noeud_vue()["extinction_en_attente"])
            rep = machines.eteindre(m["id"], annuler=True)
            self.assertTrue(rep["annulee"])
        self.assertEqual(appels, [])
        journal = " ".join(machines.journal())
        self.assertIn("extinction demandée", journal)
        self.assertIn("extinction annulée", journal)

    def test_sans_jeton_valide_pas_d_extinction(self):
        self.jumeler()
        machines.noeud_autoriser_extinction(True)
        statut, _ = self.http("POST", "/api/noeud/eteindre", {"annuler": False})
        self.assertEqual(statut, 401)
        self.assertIsNone(machines.noeud_vue()["extinction_en_attente"])

    def tearDown(self):
        alimentation.annuler_extinction()


if __name__ == "__main__":
    unittest.main()
