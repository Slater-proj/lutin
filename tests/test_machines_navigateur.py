"""La page Machines dans un vrai Chrome, avec une vraie machine appairée (ce même serveur, jouant le rôle de l'autre machine) : choix de qui répond, autorisations demandées puis acceptées, sans erreur JavaScript.
Ignoré s'il n'y a pas de navigateur."""
import sys
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401
import cdp
import test_machines as T
from lutin import moteur as A
from lutin import serveur as srv
from lutin import machines

RACINE = Path(__file__).resolve().parent.parent


class PageMachines(T.Base):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RACINE / "tools"))
        import captures
        try:
            cls.chrome = captures.navigateur()
        except SystemExit:
            raise unittest.SkipTest("aucun navigateur (Chrome, Chromium ou Edge) trouvé")

    def setUp(self):
        super().setUp()
        self.p_reglages.stop()          # le mode multi-machines est actif dans cette page
        self.p_reglages = mock.patch.object(srv._m, "reglages", lambda: dict(A.REGLAGES_DEFAUT, cluster=True))
        self.p_reglages.start()
        self.noeud.en_memoire = lambda nom: None          # l'état de la page interroge le moteur (ici un faux)

    def test_choix_unique_puis_demande_et_acceptation_d_un_droit(self):
        self.jumeler()
        p = cdp.Page(self.chrome, self.tmp / "profil-cdp")
        self.addCleanup(p.fermer)
        p.aller("http://127.0.0.1:%d/" % self.port)
        p.attendre("!!document.querySelector('#bNouvelle')")
        p.evaluer("window.confirm = () => true")
        p.evaluer("document.querySelector('.onglets button[data-p=\"machines\"]').click(); true")
        zone = "document.getElementById('machinesZone').textContent"
        p.attendre(zone + ".includes('Qui répond à tes messages')")
        self.assertEqual(p.evaluer("document.querySelectorAll('#machinesZone input[name=machine_choisie]').length"), 2, "cette machine + la machine appairée")
        self.assertNotIn("Revenir au moteur local", p.evaluer(zone))
        p.attendre(zone + ".includes('Ce que cette machine')")          # les autorisations de la machine appairée
        self.assertEqual(p.evaluer("[...document.querySelectorAll('#machinesZone .autorisations button')].map(b => b.textContent).join(',')"), "Demander,Demander,Demander")

        # choisir la machine appairée : un seul clic, sans bouton « répondre / revenir »
        p.evaluer("document.querySelectorAll('#machinesZone input[name=machine_choisie]')[1].click(); true")
        p.attendre("document.querySelectorAll('#machinesZone input[name=machine_choisie]')[1].checked")

        # demander l'autorisation de mener des conversations : la demande attend la réponse du propriétaire (ici le même serveur)
        p.evaluer("document.querySelector('#machinesZone .autorisations button').click(); true")
        p.attendre(zone + ".includes('Demandes d\\'autorisation')")
        self.assertIn("demande à pouvoir mener des conversations ici", p.evaluer(zone))
        self.assertFalse(machines.noeud_vue()["piloter"], "une demande n'accorde rien")
        p.attendre(zone + ".includes('demande envoyée')")
        p.evaluer("[...document.querySelectorAll('#machinesZone button')].find(b => b.textContent.trim() === 'Autoriser').click(); true")
        p.attendre("!document.getElementById('machinesZone').textContent.includes('Demandes d\\'autorisation')")
        self.assertTrue(machines.noeud_vue()["piloter"])
        self.assertEqual(p.evaluer("document.querySelectorAll('#machinesZone .autorisations button').length"), 2, "il reste deux droits à demander")
        self.assertEqual([e for e in p.erreurs if "rror" in str(e)], [], "aucune erreur JavaScript")

    def test_un_bouton_clique_ne_fige_pas_la_page(self):
        """Le bouton cliqué garde le focus : la page doit quand même se redessiner à l'état suivant (régression : il fallait cliquer une seconde fois)."""
        self.jumeler()
        p = cdp.Page(self.chrome, self.tmp / "profil-cdp2")
        self.addCleanup(p.fermer)
        p.aller("http://127.0.0.1:%d/" % self.port)
        p.attendre("!!document.querySelector('#bNouvelle')")
        p.evaluer("document.querySelector('.onglets button[data-p=\"machines\"]').click(); true")
        p.attendre("document.getElementById('machinesZone').textContent.includes('Ce que cette machine')")
        p.evaluer("document.querySelector('#machinesZone .autorisations button').focus(); true")
        machines.noeud_autoriser_extinction(True)          # l'état change côté serveur pendant que le bouton a le focus
        p.attendre("[...document.querySelectorAll('#machinesZone .autorisations .ligne')].some(l => l.textContent.includes('✅'))", 15)


if __name__ == "__main__":
    unittest.main()
