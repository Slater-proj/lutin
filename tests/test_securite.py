import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401
from lutin import securite as s
from lutin.securite import Appareils, LimiteurDebit, Securite


class Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


LAN = Securite(niveau=s.RESEAU)
PROXY = Securite(niveau=s.PROXY, url_publique="https://lutin.exemple.fr", proxy_ips=["192.168.1.10", "10.0.0.0/24"])


class Ecoute(unittest.TestCase):
    def test_local_n_ecoute_jamais_ailleurs_que_sur_127(self):
        self.assertEqual(s.adresse_ecoute(Securite(), "192.168.1.5"), "127.0.0.1")
        self.assertEqual(s.adresse_ecoute(Securite(), ""), "127.0.0.1")

    def test_reseau_ecoute_sur_l_adresse_du_reseau(self):
        self.assertEqual(s.adresse_ecoute(LAN, "192.168.1.5"), "192.168.1.5")

    def test_proxy_local_reste_sur_127_proxy_distant_sur_le_reseau(self):
        self.assertEqual(s.adresse_ecoute(Securite(niveau=s.PROXY, proxy_ips=["127.0.0.1"]), "192.168.1.5"), "127.0.0.1")
        self.assertEqual(s.adresse_ecoute(PROXY, "192.168.1.5"), "192.168.1.5")


class Validation(unittest.TestCase):
    def test_configurations_correctes(self):
        self.assertEqual(Securite().valider(), [])
        self.assertEqual(LAN.valider(), [])
        self.assertEqual(PROXY.valider(), [])

    def test_proxy_exige_url_https_et_adresse_du_proxy(self):
        self.assertTrue(Securite(niveau=s.PROXY).valider())
        self.assertTrue(any("https" in p for p in Securite(niveau=s.PROXY, url_publique="http://x.fr", proxy_ips=["1.2.3.4"]).valider()))
        self.assertTrue(any("invalide" in p for p in Securite(niveau=s.PROXY, url_publique="https://x.fr", proxy_ips=["pas-une-ip"]).valider()))

    def test_niveau_ou_port_inconnu(self):
        self.assertTrue(Securite(niveau="ouvert").valider())
        self.assertTrue(Securite(port=70000).valider())


class HoteEtOrigine(unittest.TestCase):
    def test_local_refuse_un_nom_etranger_dns_rebinding(self):
        sec = Securite()
        for ok in ("127.0.0.1:8777", "localhost:8777", "LOCALHOST", "[::1]:8777"):
            self.assertTrue(s.hote_autorise(sec, ok), ok)
        for non in ("evil.com", "evil.com:8777", "192.168.1.5:8777", "", None):
            self.assertFalse(s.hote_autorise(sec, non), non)

    def test_reseau_accepte_les_adresses_privees_pas_les_publiques(self):
        self.assertTrue(s.hote_autorise(LAN, "192.168.1.5:8777", "192.168.1.5"))
        self.assertTrue(s.hote_autorise(LAN, "10.0.0.7"))
        self.assertTrue(s.hote_autorise(LAN, "monpc.local:8777"))
        self.assertFalse(s.hote_autorise(LAN, "8.8.8.8:8777"))
        self.assertFalse(s.hote_autorise(LAN, "evil.com"))

    def test_proxy_accepte_l_adresse_publique_declaree(self):
        self.assertTrue(s.hote_autorise(PROXY, "lutin.exemple.fr"))
        self.assertFalse(s.hote_autorise(PROXY, "autre.exemple.fr"))

    def test_origine(self):
        sec = Securite()
        self.assertTrue(s.origine_autorisee(sec, "", "127.0.0.1:8777"), "outil en ligne de commande : pas d'Origin")
        self.assertTrue(s.origine_autorisee(sec, "http://127.0.0.1:8777", "127.0.0.1:8777"))
        self.assertFalse(s.origine_autorisee(sec, "http://evil.com", "127.0.0.1:8777"))
        self.assertFalse(s.origine_autorisee(sec, "null", "127.0.0.1:8777"))
        self.assertFalse(s.origine_autorisee(sec, "http://localhost:8777", "127.0.0.1:8777"), "autre nom que celui de la requête")


class Proxy(unittest.TestCase):
    def test_identite_acceptee_seulement_depuis_le_proxy(self):
        en_tetes = {"Remote-User": "clement"}
        self.assertEqual(s.identite_proxy(PROXY, "192.168.1.10", en_tetes), "clement")
        self.assertEqual(s.identite_proxy(PROXY, "10.0.0.42", en_tetes), "clement", "réseau déclaré")
        self.assertIsNone(s.identite_proxy(PROXY, "192.168.1.99", en_tetes), "en-tête falsifié par un autre appareil")
        self.assertIsNone(s.identite_proxy(PROXY, "8.8.8.8", en_tetes))
        self.assertIsNone(s.identite_proxy(PROXY, "pas-une-ip", en_tetes))
        self.assertIsNone(s.identite_proxy(LAN, "192.168.1.10", en_tetes), "hors niveau proxy l'en-tête n'a aucune valeur")
        self.assertIsNone(s.identite_proxy(PROXY, "192.168.1.10", {}))

    def test_acces_proxy_sans_identite_demande_une_authentification(self):
        ok, raison = s.acces(PROXY, Appareils(), "192.168.1.99", {"Remote-User": "admin"})
        self.assertFalse(ok)
        self.assertIn("authentification", raison)


class AdministrateursProxy(unittest.TestCase):
    def test_seul_un_administrateur_declare_identifie_par_le_proxy_de_confiance_configure(self):
        import os
        vrai = os.environ.get("LUTIN_ADMINS")
        try:
            os.environ.pop("LUTIN_ADMINS", None)
            self.assertFalse(s.est_admin_proxy(PROXY, "192.168.1.10", {"Remote-User": "clement"}), "personne n'est administrateur par défaut")
            os.environ["LUTIN_ADMINS"] = "Clement, marie;paul"
            self.assertEqual(s.administrateurs(), {"clement", "marie", "paul"})
            self.assertTrue(s.est_admin_proxy(PROXY, "192.168.1.10", {"Remote-User": "CLEMENT"}), "à la casse près")
            self.assertFalse(s.est_admin_proxy(PROXY, "192.168.1.10", {"Remote-User": "intrus"}))
            self.assertFalse(s.est_admin_proxy(PROXY, "192.168.1.10", {}), "sans identité")
            self.assertFalse(s.est_admin_proxy(PROXY, "203.0.113.5", {"Remote-User": "clement"}), "l'en-tête n'est cru que du proxy déclaré : n'importe qui peut l'écrire")
            self.assertFalse(s.est_admin_proxy(LAN, "192.168.1.10", {"Remote-User": "clement"}), "seulement au niveau proxy")
        finally:
            if vrai is None:
                os.environ.pop("LUTIN_ADMINS", None)
            else:
                os.environ["LUTIN_ADMINS"] = vrai


class Secrets(unittest.TestCase):
    def test_un_caractere_non_ascii_ne_fait_pas_planter_les_comparaisons(self):
        self.assertTrue(s.egal("abc", "abc"))
        self.assertFalse(s.egal("abc", "abd"))
        self.assertFalse(s.egal("é", "e"))
        self.assertTrue(s.egal("é", "é"))
        self.assertFalse(s.egal(None, "x"))
        a = Appareils(Path(tempfile.mkdtemp()) / "appareils.json")
        a.nouveau_pin()
        self.assertIsNone(a.appairer("é\u202e12", "Test"), "un code non ASCII est simplement un mauvais code")


class Appairage(unittest.TestCase):
    def setUp(self):
        self.h = Horloge()

    def test_pin_bon_donne_une_session_et_ne_sert_qu_une_fois(self):
        a = Appareils(horloge=self.h)
        pin = a.nouveau_pin()
        self.assertRegex(pin, r"^\d{6}$")
        jeton = a.appairer(pin, "Téléphone")
        self.assertTrue(jeton and a.valide(jeton))
        self.assertIsNone(a.appairer(pin), "PIN déjà utilisé")
        self.assertFalse(a.valide("n-importe-quoi"))
        self.assertFalse(a.valide(""))

    def test_pin_expire(self):
        a = Appareils(horloge=self.h)
        pin = a.nouveau_pin()
        self.h.t += s.DUREE_PIN_S + 1
        self.assertIsNone(a.appairer(pin))

    def test_cinq_echecs_bloquent_meme_le_bon_pin(self):
        a = Appareils(horloge=self.h)
        pin = a.nouveau_pin()
        for _ in range(s.ESSAIS_PIN):
            self.assertIsNone(a.appairer("000000" if pin != "000000" else "111111"))
        self.assertIsNone(a.appairer(pin), "le PIN est invalidé après trop d'échecs")
        a.nouveau_pin()
        self.assertIsNone(a.appairer(a.pin), "bloqué pendant la durée de blocage")
        self.h.t += s.BLOCAGE_S + 1
        pin2 = a.nouveau_pin()
        self.assertIsNotNone(a.appairer(pin2))

    def test_session_expire_et_revocation(self):
        a = Appareils(horloge=self.h)
        j1 = a.appairer(a.nouveau_pin(), "A")
        j2 = a.appairer(a.nouveau_pin(), "B")
        self.assertEqual(len(a.liste()), 2)
        self.assertEqual(a.revoquer(a.liste()[0]["id"]), 1)
        self.assertEqual(sum(a.valide(j) for j in (j1, j2)), 1)
        self.assertEqual(a.revoquer(), 1)
        self.h.t += 1
        j3 = a.appairer(a.nouveau_pin())
        self.h.t += s.DUREE_SESSION_S + 1
        self.assertFalse(a.valide(j3))

    def test_le_fichier_ne_contient_pas_les_jetons(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "appareils.json"
            a = Appareils(f, horloge=self.h)
            jeton = a.appairer(a.nouveau_pin(), "Tablette")
            self.assertNotIn(jeton, f.read_text(encoding="utf-8"))
            self.assertTrue(Appareils(f, horloge=self.h).valide(jeton), "la session survit à un redémarrage")
            f.write_text("{pas du json", encoding="utf-8")
            self.assertEqual(Appareils(f).sessions, {}, "fichier abîmé : on repart de zéro, sans planter")

    def test_acces_reseau_par_cookie(self):
        a = Appareils(horloge=self.h)
        jeton = a.appairer(a.nouveau_pin())
        self.assertEqual(s.acces(LAN, a, "192.168.1.7", {"Cookie": "{}={}; autre=1".format(s.NOM_COOKIE, jeton)}), (True, "appareil"))
        self.assertFalse(s.acces(LAN, a, "192.168.1.7", {"Cookie": s.NOM_COOKIE + "=faux"})[0])
        self.assertFalse(s.acces(LAN, a, "192.168.1.7", {})[0])
        self.assertTrue(s.acces(Securite(), a, "127.0.0.1", {})[0])

    def test_cookie_secure_seulement_en_https(self):
        self.assertIn("Secure", s.en_tete_set_cookie("x", True))
        self.assertNotIn("Secure", s.en_tete_set_cookie("x", False))
        for attendu in ("HttpOnly", "SameSite=Strict"):
            self.assertIn(attendu, s.en_tete_set_cookie("x", False))


class Debit(unittest.TestCase):
    def test_fenetre_glissante(self):
        h = Horloge()
        lim = LimiteurDebit(3, 60, h)
        self.assertEqual([lim.autoriser("ip") for _ in range(4)], [True, True, True, False])
        self.assertTrue(lim.autoriser("autre"), "par adresse")
        h.t += 61
        self.assertTrue(lim.autoriser("ip"))


if __name__ == "__main__":
    unittest.main()
