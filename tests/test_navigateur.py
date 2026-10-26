"""Des parcours réels dans un vrai Chrome (clics, fenêtres, réponses du serveur) : ce que la lecture du code ne montre pas. Ignoré s'il n'y a pas de navigateur."""
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

import context  # noqa: F401
import cdp

RACINE = Path(__file__).resolve().parent.parent
SRC = RACINE / "src"


def bouton(texte):
    """Expression JavaScript : clique le bouton visible qui porte ce texte (et rend vrai s'il existe)."""
    return "(() => { const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === @@ && x.offsetParent !== null); if (b) b.click(); return !!b; })()".replace("@@", json.dumps(texte))


def onglet(nom):
    return "document.querySelector('.onglets button[data-p=\"{}\"]').click()".format(nom)


class Parcours(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RACINE / "tools"))
        import captures
        cls.captures = captures
        try:
            cls.chrome = captures.navigateur()
        except SystemExit:
            raise unittest.SkipTest("aucun navigateur (Chrome, Chromium ou Edge) trouvé")

    def ouvrir(self, tmp, adresse):
        p = cdp.Page(self.chrome, tmp / "profil-cdp")
        self.addCleanup(p.fermer)
        p.aller(adresse)
        p.attendre("!!document.querySelector('#bNouvelle')")
        p.evaluer("window.confirm = () => true")                  # les fenêtres du navigateur bloqueraient le test : on répond « oui »
        return p

    def test_reprise_dit_ce_qui_ne_va_pas_puis_ce_qu_elle_a_fait(self):
        """Le bug d'origine : la reprise ne disait rien. La fenêtre montre l'erreur d'un mauvais dossier, puis le contenu trouvé, puis le résultat."""
        with self.captures.serveur_demo() as (port, tmp):
            ancien = tmp / "ancien"
            (ancien / "donnees" / "conversations").mkdir(parents=True)
            (ancien / "memoire").mkdir()
            (ancien / "donnees" / "conversations" / "aabbccdd.json").write_text(json.dumps({"id": "aabbccdd", "titre": "Reprise d'essai", "date": "2026-10-01T10:00:00", "messages": [{"role": "user", "content": "bonjour"}], "resume": ""}), encoding="utf-8")
            (ancien / "memoire" / "MEMOIRE.md").write_text("# Mémoire\n\nUne note ancienne.\n", encoding="utf-8")
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer(onglet("reglages"))
            p.attendre(bouton("Reprendre les données d'un autre assistant…"))
            p.attendre("!!document.querySelector('#modalCorps input')")
            saisie = "(texte) => { const i = document.querySelector('#modalCorps input'); i.value = texte; return true; }"
            p.evaluer("({})({})".format(saisie, json.dumps(str(tmp / "nexiste-pas"))))
            p.evaluer(bouton("Vérifier"))
            p.attendre("document.querySelector('#modalCorps .erreur') && document.querySelector('#modalCorps .erreur').textContent.length > 5")
            self.assertIn("n'existe pas", p.evaluer("document.querySelector('#modalCorps .erreur').textContent"), "l'erreur est dite dans la fenêtre")
            p.evaluer("({})({})".format(saisie, json.dumps(str(ancien))))
            p.evaluer(bouton("Vérifier"))
            p.attendre("document.querySelector('#modalCorps').textContent.includes('Conversations : 1')")
            contenu = p.evaluer("document.querySelector('#modalCorps').textContent")
            self.assertIn("Mémoire : MEMOIRE.md", contenu)
            p.evaluer(bouton("Reprendre"))
            p.attendre("document.querySelector('#modalCorps').textContent.includes('onversation')  && !document.querySelector('#modalCorps input[type=checkbox]')")
            self.assertTrue((tmp / "home" / "donnees" / "conversations" / "aabbccdd.json").is_file(), "la conversation est vraiment reprise")
            self.assertEqual(p.erreurs, [], "aucune erreur JavaScript")

    def test_dossiers_de_travail_choisir_ajouter_retirer(self):
        with self.captures.serveur_demo() as (port, tmp):
            autre = tmp / "Autre"
            autre.mkdir()
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            self.assertFalse(p.evaluer("!!document.querySelector('#selTravail')"), "plus de sélecteur de dossier dans la barre latérale")
            p.evaluer(onglet("reglages"))
            p.attendre("document.querySelector('#listeTravaux').textContent.includes('★ Projet')")
            # choisir l'autre dossier
            p.evaluer(bouton("Utiliser ce dossier"))
            p.attendre("document.querySelector('#listeTravaux').textContent.includes('★ Documents')")
            # ajouter un dossier (la boîte « chemin » est simulée)
            p.evaluer("window.prompt = (q, d) => (q.includes('Chemin') ? " + json.dumps(str(autre)) + " : 'Autre')")
            p.evaluer(bouton("Ajouter un dossier…"))
            p.attendre("document.querySelector('#listeTravaux').textContent.includes('★ Autre')")
            # retirer le dossier principal, puis tous les autres : c'est permis, Lutin retombe sur son dossier par défaut
            for nom in ("Projet", "Documents", "Autre"):
                p.attendre("[...document.querySelectorAll('#listeTravaux .conv')].some(l => l.textContent.includes(@@))".replace("@@", json.dumps(nom)))
                p.evaluer("(() => { const l = [...document.querySelectorAll('#listeTravaux .conv')].find(x => x.textContent.includes(@@)); [...l.querySelectorAll('button')].find(b => b.textContent === 'Retirer').click(); })()".replace("@@", json.dumps(nom)))
                p.attendre("![...document.querySelectorAll('#listeTravaux .conv')].some(l => l.textContent.includes(@@))".replace("@@", json.dumps(nom)))
            self.assertIn("dossier par défaut", p.evaluer("document.querySelector('#listeTravaux').textContent"))
            self.assertTrue(autre.is_dir(), "les fichiers ne sont jamais supprimés")
            self.assertEqual(p.erreurs, [])

    def test_bouton_verifier_les_mises_a_jour_dit_pourquoi_ca_ne_marche_pas(self):
        """Hors ligne strict (donc sans réseau, de façon déterministe) : le bouton répond par la vraie cause, il ne reste pas muet."""
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr", "LUTIN_HORS_LIGNE": "1"}) as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer(onglet("reglages"))
            p.attendre(bouton("Vérifier les mises à jour"))
            p.attendre("document.querySelector('#mVerifierLutin').textContent.includes('Impossible de joindre GitHub')")
            message = p.evaluer("document.querySelector('#mVerifierLutin').textContent")
            self.assertIn("hors ligne", message.lower(), "la cause réelle est montrée")
            self.assertRegex(p.evaluer("document.querySelector('#vVersionActuelle').textContent"), r"^Lutin \S+")
            self.assertFalse(p.evaluer("document.querySelector('#bVerifierLutin').disabled"), "le bouton redevient utilisable")

    def test_pin_et_qr_au_niveau_reseau(self):
        """Au niveau « réseau », le navigateur de cette machine s'appaire comme un téléphone (le PIN de la console), puis l'onglet Accès montre PIN et QR tout de suite."""
        with self.captures.serveur_demo(niveau="reseau") as (port, tmp):
            env = dict(os.environ, LUTIN_HOME=str(tmp / "home"), PYTHONPATH=str(SRC), PYTHONIOENCODING="utf-8")
            sortie = subprocess.run([sys.executable, "-B", "-m", "lutin", "pin"], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60).stdout
            pin = re.search(r"\b(\d{6})\b", sortie)
            self.assertTrue(pin, "lutin pin donne un code : " + sortie)
            p = cdp.Page(self.chrome, tmp / "profil-cdp")
            self.addCleanup(p.fermer)
            p.aller("http://127.0.0.1:%d/#pin=%s" % (port, pin.group(1)))              # la page de connexion se remplit et valide toute seule
            p.attendre("!!document.querySelector('#bNouvelle')")
            p.evaluer(onglet("acces"))
            p.attendre("/^\\d{6}$/.test(document.querySelector('#pinValeur').textContent)")
            p.attendre("!!document.querySelector('#qrPin svg')")
            self.assertFalse(p.evaluer("document.querySelector('#blocPin').hidden"))
            self.assertIn("Adresse à ouvrir", p.evaluer("document.querySelector('#adressePin').textContent"))
            self.assertEqual(p.erreurs, [])


if __name__ == "__main__":
    unittest.main()
