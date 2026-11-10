"""Le réveil d'une machine (Wake-on-LAN), de bout en bout et sans réseau : « la machine est-elle allumée ? » indépendamment de Lutin et de son pare-feu, la séquence en cinq étapes,
le délai de cinq minutes après lequel un réveil non abouti revient à « pas démarrée » avec sa raison, la synchronisation qui ne reste jamais coincée."""
import io
import json
import os
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-reveil-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"), "LUTIN_SANS_DEMARRAGE": "1"}.items():
    os.environ.setdefault(cle, valeur)
(_TEMP / "projet").mkdir(exist_ok=True)

from lutin import moteur as _m  # noqa: E402,F401  (avant les autres : import circulaire sinon)
from lutin import alimentation, machines  # noqa: E402

MAC = "00:1A:2B:3C:4D:5E"


class Voisins(unittest.TestCase):
    def test_la_table_des_voisins_est_lue_sur_windows_et_sur_linux(self):
        cas = [("Reachable 00-1A-2B-3C-4D-5E", MAC, True), ("Reachable AA-BB-CC-DD-EE-FF", MAC, False), ("Reachable 00-1A-2B-3C-4D-5E", "", True),
               ("Unreachable 00-00-00-00-00-00", MAC, False), ("Incomplete", MAC, False), ("Stale 00-1A-2B-3C-4D-5E", MAC, None), ("", MAC, None),
               ("192.168.1.59 dev eth0 lladdr 00:1a:2b:3c:4d:5e REACHABLE", MAC, True), ("192.168.1.59 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE", MAC, False),
               ("192.168.1.59 dev eth0 FAILED", MAC, False), ("192.168.1.59 dev eth0 lladdr 00:1a:2b:3c:4d:5e STALE", MAC, None), ("192.168.1.59 dev eth0 lladdr 00:1a:2b:3c:4d:5e DELAY", MAC, None)]
        for texte, mac, attendu in cas:
            self.assertEqual(alimentation.analyser_voisin(texte, mac), attendu, (texte, mac))

    def test_une_commande_absente_ne_donne_pas_de_verdict(self):
        def absente(*a, **k):
            raise FileNotFoundError("ip")
        self.assertIsNone(alimentation.voisin("192.168.1.59", MAC, lancer=absente))


class MachineAllumee(unittest.TestCase):
    def verdict(self, tcp=False, ping=False, table=None, **plus):
        return alimentation.hote_allume("192.168.1.59", MAC, 8765, delai=0.2, tcp=lambda h, p, d: tcp(p) if callable(tcp) else tcp, ping=lambda h, d: ping, table=lambda h, m: table, **plus)

    def test_la_table_des_voisins_tranche_quand_elle_sait(self):
        self.assertTrue(self.verdict(tcp=False, ping=False, table=True), "ARP confirme : allumée même si le pare-feu jette tout")
        self.assertFalse(self.verdict(tcp=True, ping=True, table=False), "une autre machine a cette adresse (ou la résolution échoue) : pas la bonne")

    def test_sans_table_une_connexion_acceptee_ou_refusee_ou_un_ping_prouvent_qu_elle_est_la(self):
        self.assertTrue(self.verdict(tcp=lambda p: p == 445))
        self.assertTrue(self.verdict(tcp=lambda p: p == 8765), "le port de Lutin est essayé aussi")
        self.assertTrue(self.verdict(tcp=False, ping=True))
        self.assertFalse(self.verdict(tcp=False, ping=False), "rien ne revient : éteinte")

    def test_un_port_refuse_compte_comme_une_reponse_et_un_silence_non(self):
        with mock.patch.object(alimentation.socket, "create_connection", side_effect=ConnectionRefusedError()):
            self.assertTrue(alimentation._tcp("192.168.1.59", 445, 0.2))
        with mock.patch.object(alimentation.socket, "create_connection", side_effect=TimeoutError()):
            self.assertFalse(alimentation._tcp("192.168.1.59", 445, 0.2))
        with mock.patch.object(alimentation.socket, "create_connection", side_effect=OSError(10065, "hôte inaccessible")):
            self.assertFalse(alimentation._tcp("192.168.1.59", 445, 0.2))
        with mock.patch.object(alimentation.socket, "create_connection", side_effect=OSError(10061, "refusé")):
            self.assertTrue(alimentation._tcp("192.168.1.59", 445, 0.2))

    def test_le_ping_windows_exige_une_vraie_reponse(self):
        def lancer(sortie, code):
            return lambda *a, **k: mock.Mock(returncode=code, stdout=sortie)
        with mock.patch.object(alimentation.os, "name", "nt"):
            self.assertFalse(alimentation._ping("192.168.1.59", 0.2, lancer("Réponse de 192.168.1.20 : Impossible de joindre l'hôte de destination.", 0)), "Windows rend 0 pour « inaccessible »")
            self.assertTrue(alimentation._ping("192.168.1.59", 0.2, lancer("Réponse de 192.168.1.59 : octets=32 temps<1ms TTL=128", 0)))


IDENT = "ab12cd34" * 4


def machine(ident=IDENT, mac=MAC):
    return {"id": ident, "nom": "PC du salon", "adresse": "http://192.0.2.7:8765", "jeton": "x" * 20, "mac": mac, "ajoutee": "2026-11-10 10:00"}


def injoignable(*a, **k):
    raise urllib.error.URLError(TimeoutError("timed out"))          # ce que renvoie un pare-feu Windows qui jette les connexions


def repond(actif=True):
    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return lambda req, timeout=None: R(json.dumps({"id": IDENT, "actif": actif, "modeles": ["m1"], "moteur_nom": "Ollama", "droits": {}, "agir": {}}).encode())


class Sequence(unittest.TestCase):
    def setUp(self):
        for d in (machines.REVEIL, machines.ECHEC_REVEIL, machines.ALLUMEE, machines.DEPUIS_ALLUMEE, machines.REPONDU, machines.A_REPONDU, machines.SONDES, machines.SYNCHRO, machines.DERNIER_ETAT):
            d.clear()
        self.m = machine()
        machines._ecrire_registre([self.m])
        machines._REVEILS_REPRIS["fait"] = True          # pas de reprise depuis le disque, sauf dans le test qui la vérifie
        self.addCleanup(lambda: setattr(machines, "HOTE_ALLUME", None))

    def sonder(self, ouvrir=injoignable):
        machines.SONDES.clear()
        return machines.sonder(self.m, "", ouvrir=ouvrir, force=True)

    def reveil_il_y_a(self, secondes):
        machines.REVEIL[self.m["id"]] = time.monotonic() - secondes

    def test_pare_feu_qui_jette_tout_et_systeme_allume_l_etape_2_est_atteinte(self):
        """Le défaut d'origine : seule une connexion « refusée » prouvait que la machine était allumée ; un pare-feu Windows ne refuse pas, il se tait, donc on restait bloqué sur l'étape 1."""
        self.reveil_il_y_a(40)
        machines.HOTE_ALLUME = lambda hote, mac, port: False
        r = self.sonder()
        self.assertEqual((r["etat"], r["etape"]), ("reveil_envoye", "reveil"))
        self.assertIn("Réveil envoyé il y a 40", r["detail"])
        machines.HOTE_ALLUME = lambda hote, mac, port: True
        machines.ALLUMEE.clear()
        r = self.sonder()
        self.assertEqual((r["etat"], r["etape"]), ("reveil_envoye", "allumee"))
        self.assertIn("La machine est allumée", r["detail"])
        self.assertIn("Lutin n'y répond pas encore", r["detail"])

    def test_la_machine_est_testee_avec_son_adresse_son_mac_et_le_port_de_lutin_sans_exces(self):
        self.reveil_il_y_a(10)
        appels = []
        machines.HOTE_ALLUME = lambda hote, mac, port: (appels.append((hote, mac, port)), True)[1]
        self.sonder()
        self.sonder()          # deux sondes de suite : la vérification, plus coûteuse, n'est pas refaite à chaque fois
        self.assertEqual(appels, [("192.0.2.7", MAC, 8765)])

    def test_hors_reveil_la_machine_n_est_pas_testee(self):
        machines.HOTE_ALLUME = lambda *a: self.fail("pas de réveil en cours : rien à vérifier")
        r = self.sonder()
        self.assertEqual((r["etat"], r["etape"]), ("injoignable", "eteinte"))

    def test_apres_cinq_minutes_le_reveil_revient_a_pas_demarree_avec_la_raison(self):
        self.assertEqual(alimentation.ATTENTE_REVEIL_S, 300)
        machines.HOTE_ALLUME = lambda hote, mac, port: False
        self.reveil_il_y_a(alimentation.ATTENTE_REVEIL_S - 5)
        self.assertEqual(self.sonder()["etat"], "reveil_envoye", "pas encore")
        self.reveil_il_y_a(alimentation.ATTENTE_REVEIL_S + 5)
        r = self.sonder()
        self.assertEqual((r["etat"], r["etape"], r.get("reveil_echec")), ("injoignable", "eteinte", True))
        self.assertIn("Réveil non abouti", r["detail"])
        self.assertIn("5 minutes", r["detail"])
        self.assertIn("adresse IP", r["detail"], "une machine allumée sous une autre adresse est une cause fréquente")
        self.assertIn("Wake-on-LAN", r["detail"])
        self.assertNotIn(self.m["id"], machines.REVEIL, "plus de réveil en cours")
        r = self.sonder()          # la raison reste affichée, ce n'est pas un message qui disparaît
        self.assertEqual((r["etape"], r.get("reveil_echec")), ("eteinte", True))
        self.assertIn("réveil de PC du salon non abouti", " ".join(machines.journal()))

    def test_machine_allumee_sans_lutin_le_dit_autrement(self):
        machines.HOTE_ALLUME = lambda hote, mac, port: True
        self.reveil_il_y_a(alimentation.ATTENTE_REVEIL_S + 5)
        r = self.sonder()
        self.assertEqual((r["etape"], r.get("reveil_echec")), ("eteinte", True))
        self.assertIn("bien allumée", r["detail"])
        self.assertIn("Démarrer Lutin à l'ouverture de ma session", r["detail"])
        self.assertNotIn("Wake-on-LAN", r["detail"], "le réveil a marché : inutile de vérifier le BIOS")

    def test_un_nouveau_reveil_efface_l_echec_et_la_reponse_de_la_machine_aussi(self):
        self.reveil_il_y_a(alimentation.ATTENTE_REVEIL_S + 5)
        machines.HOTE_ALLUME = lambda *a: False
        self.assertTrue(self.sonder().get("reveil_echec"))
        machines.reveiller(self.m["id"], envoyer=lambda mac, hote: [(hote, 9)])
        self.assertNotIn(self.m["id"], machines.ECHEC_REVEIL)
        r = self.sonder()
        self.assertEqual((r["etat"], r.get("reveil_echec")), ("reveil_envoye", None))
        # puis elle répond : tout est remis à zéro
        r = self.sonder(repond())
        self.assertEqual(r["etat"], "operationnel")
        machines.REPONDU[self.m["id"]] -= machines.STABLE_REPONSE_S + 1          # elle répond sans interruption depuis assez longtemps
        self.sonder(repond())
        for suivi in (machines.REVEIL, machines.ECHEC_REVEIL, machines.ALLUMEE, machines.DEPUIS_ALLUMEE, machines.REPONDU, machines.A_REPONDU):
            self.assertNotIn(self.m["id"], suivi)

    def test_lutin_repond_apres_l_echec_la_machine_redevient_utilisable(self):
        self.reveil_il_y_a(alimentation.ATTENTE_REVEIL_S + 5)
        machines.HOTE_ALLUME = lambda *a: False
        self.sonder()
        r = self.sonder(repond())
        self.assertEqual((r["etat"], r.get("reveil_echec")), ("operationnel", None))
        self.assertNotIn(self.m["id"], machines.ECHEC_REVEIL)

    def test_lutin_qui_repond_puis_redemarre_ne_fait_pas_retomber_la_machine_a_eteinte(self):
        """Le défaut : à la première réponse de Lutin, tout le suivi du réveil était effacé ; si Lutin redémarrait ensuite (démarrage de session, réseau pas prêt), la séquence disparaissait et la machine
        allumée semblait éteinte — alors qu'un nouveau clic sur « Réveiller » la retrouvait aussitôt à l'étape 2."""
        machines.HOTE_ALLUME = lambda hote, mac, port: True
        self.reveil_il_y_a(60)
        r = self.sonder(repond())
        self.assertIn(r["etat"], ("operationnel", "joignable"))
        self.assertIn(self.m["id"], machines.REVEIL, "elle a répondu une fois : le réveil continue")
        r = self.sonder()          # Lutin redémarre : plus de réponse
        self.assertEqual((r["etat"], r["etape"], r.get("reveil_echec")), ("reveil_envoye", "allumee", None))
        self.assertIn("Lutin y avait répondu", r["detail"])
        self.assertIn("il redémarre", r["detail"])
        r = self.sonder(repond())          # et il revient
        self.assertEqual(r["etat"], "operationnel")

    def test_le_reveil_est_fini_quand_lutin_repond_sans_interruption(self):
        self.reveil_il_y_a(60)
        self.sonder(repond())
        machines.REPONDU[self.m["id"]] -= machines.STABLE_REPONSE_S + 1
        self.assertEqual(self.sonder(repond())["etat"], "operationnel")
        for suivi in (machines.REVEIL, machines.REPONDU, machines.A_REPONDU, machines.ALLUMEE):
            self.assertNotIn(self.m["id"], suivi)
        r = self.sonder()          # plus tard, une vraie extinction : « pas de réponse », sans faux espoir
        self.assertEqual((r["etat"], r["etape"]), ("injoignable", "eteinte"))

    def test_un_reveil_survit_au_redemarrage_de_ce_lutin(self):
        machines.HOTE_ALLUME = lambda hote, mac, port: False
        machines.reveiller(self.m["id"], envoyer=lambda mac, hote: [(hote, 9)])
        self.assertTrue((machines.dossier() / "reveils.json").is_file())
        machines.REVEIL.clear()          # CE Lutin redémarre : la mémoire est vide
        machines._REVEILS_REPRIS["fait"] = False
        r = self.sonder()
        self.assertEqual((r["etat"], r["etape"]), ("reveil_envoye", "reveil"), "la séquence reprend là où elle en était")
        # un réveil périmé n'est pas repris
        machines.REVEIL.clear()
        machines.ALLUMEE.clear()
        (machines.dossier() / "reveils.json").write_text(json.dumps({self.m["id"]: round(time.time()) - alimentation.ATTENTE_REVEIL_S - 30}), encoding="utf-8")
        machines._REVEILS_REPRIS["fait"] = False
        self.assertEqual(self.sonder()["etape"], "eteinte")

    def test_la_synchronisation_ne_reste_pas_coincee(self):
        r = self.sonder(repond())
        self.assertEqual(r["etape"], "synchro", "tout juste joignable : les listes sont en cours de relecture")
        machines.SYNCHRO[self.m["id"]]["debut"] = time.monotonic() - machines.DELAI_SYNCHRO_S - 5
        self.assertEqual(self.sonder(repond())["etape"], "pret", "une relecture qui n'aboutit pas ne bloque pas la machine en « synchronisation »")
        machines.SYNCHRO[self.m["id"]].update(modeles=True, conv=True, debut=time.monotonic())
        self.assertEqual(self.sonder(repond())["etape"], "pret")

    def test_la_sonde_est_plus_patiente_pendant_un_reveil(self):
        delais = []

        def espion(req, timeout=None):
            delais.append(timeout)
            raise urllib.error.URLError(TimeoutError())
        machines.HOTE_ALLUME = lambda *a: False
        self.sonder(espion)
        self.reveil_il_y_a(10)
        self.sonder(espion)
        self.assertEqual(delais, [machines.DELAI_SONDE_S, machines.DELAI_SONDE_REVEIL_S])
        self.assertGreater(delais[1], delais[0])


if __name__ == "__main__":
    unittest.main()
