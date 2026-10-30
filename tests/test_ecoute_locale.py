"""Au niveau « réseau », le serveur est joignable AUSSI depuis sa propre machine (127.0.0.1) : sinon ni l'icône de la zone de notification, ni `lutin pin`, ni `lutin chat` ne le trouvent."""
import http.client
import os
import socket
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401

_TEMP = Path(tempfile.mkdtemp(prefix="lutin-ecoute-"))
for cle, valeur in {"LUTIN_RACINE": str(_TEMP / "projet"), "LUTIN_DONNEES": str(_TEMP / "donnees"), "LUTIN_MEMOIRE": str(_TEMP / "memoire"),
                    "LUTIN_SANS_DEMARRAGE": "1", "LUTIN_SANS_GARDE": "1", "OLLAMA_URL": "http://127.0.0.1:9"}.items():
    os.environ.setdefault(cle, valeur)
for d in ("projet", "donnees", "memoire"):
    (_TEMP / d).mkdir(exist_ok=True)

from lutin import moteur as A  # noqa: E402


def port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class EcouteLocale(unittest.TestCase):
    def setUp(self):
        self.avant = (A.PORT, A.IP_LAN)
        A.PORT = port_libre()

    def tearDown(self):
        A.PORT, A.IP_LAN = self.avant

    def test_une_adresse_du_reseau_ouvre_aussi_127_0_0_1(self):
        # 127.0.0.2 joue « l'adresse du réseau local » : une adresse de la machine qui n'est pas 127.0.0.1
        local = A.ecouter_aussi_en_local("127.0.0.2")
        self.assertIsNotNone(local)
        self.addCleanup(lambda: (local.shutdown(), local.server_close()))
        c = http.client.HTTPConnection("127.0.0.1", A.PORT, timeout=5)
        c.request("GET", "/", headers={"Host": "127.0.0.1:%d" % A.PORT})
        self.assertEqual(c.getresponse().status, 200, "joignable en local")
        c.close()

    def test_rien_a_ajouter_quand_c_est_deja_local_ou_partout(self):
        for hote in ("127.0.0.1", "localhost", "::1", "0.0.0.0", ""):
            self.assertIsNone(A.ecouter_aussi_en_local(hote), hote)

    def test_port_deja_pris_le_serveur_principal_continue(self):
        with socket.socket() as occupe:
            occupe.bind(("127.0.0.1", A.PORT))
            occupe.listen(1)
            self.assertIsNone(A.ecouter_aussi_en_local("127.0.0.2"), "pas d'exception : le serveur principal ne doit pas tomber pour ça")


class CetteMachine(unittest.TestCase):
    """Un navigateur de cette machine qui ouvre http://192.168.x.y:8777 arrive avec l'adresse réseau de la machine comme origine : c'est bien cette machine."""

    def handler(self, ip_client, host="127.0.0.1:8777", **entetes):
        h = A.Gestionnaire.__new__(A.Gestionnaire)
        h.client_address = (ip_client, 50000)
        h.headers = dict({"Host": host}, **entetes)
        return h

    def setUp(self):
        self.avant = A.IP_LAN
        A.IP_LAN = "192.168.1.131"

    def tearDown(self):
        A.IP_LAN = self.avant

    def test_la_boucle_locale_et_l_adresse_reseau_de_la_machine_sont_locales(self):
        self.assertTrue(self.handler("127.0.0.1")._local())
        self.assertTrue(self.handler("192.168.1.131")._local())

    def test_une_autre_machine_ne_l_est_pas(self):
        self.assertFalse(self.handler("192.168.1.50")._local())

    def test_sans_adresse_reseau_connue_seule_la_boucle_locale_compte(self):
        A.IP_LAN = ""
        self.assertFalse(self.handler("192.168.1.131")._local())

    def test_sur_cette_machine_avec_l_adresse_reseau_comme_nom_d_hote(self):
        self.assertTrue(self.handler("192.168.1.131", host="192.168.1.131:8777")._sur_cette_machine())
        self.assertFalse(self.handler("192.168.1.50", host="192.168.1.131:8777")._sur_cette_machine(), "un autre appareil du réseau n'est jamais « cette machine »")

    def test_derriere_un_relais_ce_n_est_plus_cette_machine(self):
        self.assertFalse(self.handler("192.168.1.131", host="192.168.1.131:8777", **{"X-Forwarded-For": "8.8.8.8"})._sur_cette_machine())


if __name__ == "__main__":
    unittest.main()
