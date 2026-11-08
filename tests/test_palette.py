"""La palette de commandes (Ctrl+K) dans un vrai Chrome : ouverture au clavier, recherche sans accents, navigation aux flèches, Entrée, Échap, rendu du focus, et rien d'écrit en français quand la page est en anglais."""
import json
import sys
import unittest
from pathlib import Path

import context  # noqa: F401
import cdp

RACINE = Path(__file__).resolve().parent.parent

CTRL_K = "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'k', ctrlKey: true, bubbles: true})); true"


def touche(nom):
    return "document.getElementById('palSaisie').dispatchEvent(new KeyboardEvent('keydown', {key: %s, bubbles: true})); true" % json.dumps(nom)


def taper(texte):
    return "(() => { const c = document.getElementById('palSaisie'); c.value = %s; c.dispatchEvent(new Event('input', {bubbles: true})); return true; })()" % json.dumps(texte)


TITRES = "[...document.querySelectorAll('#palListe li .pt')].map(x => x.textContent)"


class Palette(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RACINE / "tools"))
        import captures
        cls.captures = captures
        try:
            cls.chrome = captures.navigateur()
        except SystemExit:
            raise unittest.SkipTest("aucun navigateur (Chrome, Chromium ou Edge) trouvé")

    def page(self, tmp, port, ancre="#conv=a1b2c3d4"):
        p = cdp.Page(self.chrome, tmp / "profil-palette")
        self.addCleanup(p.fermer)
        p.aller("http://127.0.0.1:%d/%s" % (port, ancre))
        p.attendre("!!document.querySelector('#bNouvelle')")
        p.attendre("!!document.querySelector('.conv.choisie')")
        return p

    def test_ouvrir_chercher_choisir_au_clavier(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.page(tmp, port)
            self.assertTrue(p.evaluer("document.getElementById('palette').hidden"))
            p.evaluer(CTRL_K)
            self.assertFalse(p.evaluer("document.getElementById('palette').hidden"))
            self.assertEqual(p.evaluer("document.activeElement.id"), "palSaisie", "la saisie a le focus")
            titres = p.evaluer(TITRES)
            for attendu in ("Conversation", "Modèles", "Santé", "Réglages"):
                self.assertIn(attendu, titres)
            self.assertIn("Corriger les fautes du README", titres, "les conversations sont dans la palette")
            self.assertIn("qwen3:8b", titres, "les modèles installés aussi")
            # recherche sans accent ni majuscule : « sante » trouve « Santé »
            p.evaluer(taper("SANTE"))
            self.assertEqual(p.evaluer(TITRES)[0], "Santé")
            # Entrée ouvre l'onglet
            p.evaluer(touche("Enter"))
            self.assertTrue(p.evaluer("document.getElementById('palette').hidden"))
            p.attendre("document.getElementById('p-sante').classList.contains('vue')")

    def test_fleches_entree_sur_une_conversation_et_echap(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.page(tmp, port)
            p.evaluer("document.querySelector('.onglets button[data-p=reglages]').click(); true")
            p.attendre("document.getElementById('p-reglages').classList.contains('vue')")
            p.evaluer(CTRL_K)
            p.evaluer(taper("pip"))
            self.assertEqual(p.evaluer(TITRES), ["Expliquer une erreur de pip"])
            p.evaluer(touche("Enter"))
            p.attendre("document.getElementById('p-chat').classList.contains('vue')")      # ouvrir une conversation ramène sur l'onglet Conversation
            p.attendre("!!document.querySelector('.conv.choisie') && document.querySelector('.conv.choisie').textContent.includes('pip')")
            # flèches : la sélection bouge et reste dans la liste
            p.evaluer(CTRL_K)
            self.assertEqual(p.evaluer("document.querySelector('#palListe li[aria-selected=true]').id"), "pal0")
            p.evaluer(touche("ArrowDown"))
            self.assertEqual(p.evaluer("document.querySelector('#palListe li[aria-selected=true]').id"), "pal1")
            p.evaluer(touche("ArrowUp"))
            p.evaluer(touche("ArrowUp"))
            self.assertEqual(p.evaluer("document.querySelector('#palListe li[aria-selected=true]').id"), "pal0", "on ne sort pas par le haut")
            # Échap ferme et rend le focus ; Ctrl+K rouvre puis referme
            p.evaluer(touche("Escape"))
            self.assertTrue(p.evaluer("document.getElementById('palette').hidden"))
            p.evaluer(CTRL_K)
            p.evaluer(CTRL_K)
            self.assertTrue(p.evaluer("document.getElementById('palette').hidden"))
            self.assertEqual(p.erreurs, [])

    def test_une_recherche_sans_resultat_le_dit_et_entree_ne_fait_rien(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.page(tmp, port)
            p.evaluer(CTRL_K)
            p.evaluer(taper("zzzzqqq"))
            self.assertEqual(p.evaluer("document.querySelectorAll('#palListe li').length"), 1)
            self.assertIn("Rien ne correspond", p.evaluer("document.querySelector('#palListe li').textContent"))
            p.evaluer(touche("Enter"))
            self.assertFalse(p.evaluer("document.getElementById('palette').hidden"), "rien à ouvrir : la palette reste")
            self.assertEqual(p.erreurs, [])

    def test_le_bouton_de_l_en_tete_et_l_anglais(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "en"}) as (port, tmp):
            p = self.page(tmp, port)
            p.evaluer("document.getElementById('bPalette').click(); true")
            self.assertFalse(p.evaluer("document.getElementById('palette').hidden"))
            self.assertIn("Go to", p.evaluer("document.getElementById('palSaisie').placeholder"))
            titres = p.evaluer(TITRES)
            self.assertIn("Settings", titres)
            self.assertIn("New conversation", titres)
            groupes = p.evaluer("[...document.querySelectorAll('#palListe li .pg')].map(x => x.textContent)")
            self.assertNotIn("Onglets", groupes, "les groupes sont traduits")
            self.assertIn("Tabs", groupes)
            self.assertEqual(p.erreurs, [])


class Accueil(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RACINE / "tools"))
        import captures
        cls.captures = captures
        try:
            cls.chrome = captures.navigateur()
        except SystemExit:
            raise unittest.SkipTest("aucun navigateur (Chrome, Chromium ou Edge) trouvé")

    def test_accueil_d_une_conversation_vide(self):
        """Une conversation vide propose des départs ; une carte remplit la zone de saisie SANS rien envoyer ; l'accueil s'efface dès qu'une conversation est ouverte."""
        with self.captures.serveur_demo() as (port, tmp):
            p = cdp.Page(self.chrome, tmp / "profil-accueil")
            self.addCleanup(p.fermer)
            p.aller("http://127.0.0.1:%d/" % port)
            p.attendre("!!document.querySelector('#bNouvelle') && document.querySelectorAll('#accueil .acc-carte').length === 5")
            visible = "document.getElementById('accueil').offsetParent !== null"
            self.assertTrue(p.evaluer(visible), "rien d'ouvert : l'accueil est là")
            p.evaluer("document.querySelector('#accueil .acc-carte').click(); true")
            self.assertIn("README.md", p.evaluer("document.getElementById('saisie').value"))
            self.assertEqual(p.evaluer("document.activeElement.id"), "saisie")
            self.assertEqual(p.evaluer("document.querySelectorAll('#fil > *').length"), 0, "rien n'a été envoyé")
            # une carte « onglet » y va
            p.evaluer("[...document.querySelectorAll('#accueil .acc-carte')].find(b => b.textContent.includes('modèle') || b.textContent.includes('model')).click(); true")
            p.attendre("document.getElementById('p-modeles').classList.contains('vue')")
            # ouvrir une conversation efface l'accueil
            p.attendre("!!document.querySelector('.conv')")          # la liste des conversations se remplit après le chargement de la page
            p.evaluer("document.querySelector('.conv').click(); true")
            p.attendre("document.getElementById('p-chat').classList.contains('vue') && document.querySelectorAll('#fil > *').length > 0")
            self.assertFalse(p.evaluer(visible))
            # et « Nouvelle conversation » le ramène
            p.evaluer("document.getElementById('bNouvelle').click(); true")
            p.attendre("document.querySelectorAll('#fil > *').length === 0")
            self.assertTrue(p.evaluer(visible))
            self.assertEqual(p.erreurs, [])


class OutilsLisibles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RACINE / "tools"))
        import captures
        cls.captures = captures
        try:
            cls.chrome = captures.navigateur()
        except SystemExit:
            raise unittest.SkipTest("aucun navigateur (Chrome, Chromium ou Edge) trouvé")

    def lignes(self, langue):
        with self.captures.serveur_demo({"LUTIN_LANGUE": langue}) as (port, tmp):
            p = cdp.Page(self.chrome, tmp / "profil-outils")
            self.addCleanup(p.fermer)
            p.aller("http://127.0.0.1:%d/#conv=a1b2c3d4" % port)
            p.attendre("document.querySelectorAll('#fil .outil').length >= 4")
            res = p.evaluer("[...document.querySelectorAll('#fil .outil > div')].map(d => [d.textContent, d.title])")
            self.assertEqual(p.erreurs, [])
            return res

    def test_un_appel_d_outil_est_une_phrase_et_l_appel_exact_reste_en_infobulle(self):
        lignes = self.lignes("fr")
        self.assertEqual(lignes[0][0], "📄 Lit README.md")
        self.assertIn('"chemin":"README.md"', lignes[0][1], "l'appel exact reste visible au survol")
        self.assertTrue(any(t.startswith("✏️ Modifie README.md") for t, _ in lignes))
        self.assertFalse(any("{" in t and t.startswith("📄") for t, _ in lignes), "plus de JSON brut dans le texte affiché")

    def test_en_anglais(self):
        lignes = self.lignes("en")
        self.assertEqual(lignes[0][0], "📄 Reads README.md")


class RechercheReglages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RACINE / "tools"))
        import captures
        cls.captures = captures
        try:
            cls.chrome = captures.navigateur()
        except SystemExit:
            raise unittest.SkipTest("aucun navigateur (Chrome, Chromium ou Edge) trouvé")

    def test_le_filtre_garde_les_groupes_qui_correspondent_et_restaure_ensuite(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = cdp.Page(self.chrome, tmp / "profil-rech")
            self.addCleanup(p.fermer)
            p.aller("http://127.0.0.1:%d/#reglages" % port)
            p.attendre("document.getElementById('p-reglages').classList.contains('vue') && document.querySelectorAll('#p-reglages details.groupe').length >= 3")
            etat = "[...document.querySelectorAll('#p-reglages details.groupe')].map(d => [d.hidden, d.open])"
            total = p.evaluer("document.querySelectorAll('#p-reglages details.groupe').length")
            # on referme tout, puis on cherche : les groupes qui correspondent sont ouverts, les autres cachés
            p.evaluer("document.querySelectorAll('#p-reglages details.groupe').forEach(d => d.open = false); true")
            p.evaluer("(() => { const c = document.getElementById('rechReglages'); c.value = 'LANGUE'; c.dispatchEvent(new Event('input', {bubbles: true})); return true; })()")
            etats = p.evaluer(etat)
            visibles = [e for e in etats if not e[0]]
            self.assertTrue(0 < len(visibles) < total, "la recherche « langue » ne garde pas tout")
            self.assertTrue(all(e[1] for e in visibles), "les groupes gardés sont ouverts")
            self.assertIn("groupe", p.evaluer("document.getElementById('rechReglagesInfo').textContent"))
            # sans résultat : tout est caché et on le dit
            p.evaluer("(() => { const c = document.getElementById('rechReglages'); c.value = 'zzzqqq'; c.dispatchEvent(new Event('input', {bubbles: true})); return true; })()")
            self.assertTrue(all(e[0] for e in p.evaluer(etat)))
            self.assertIn("Aucun réglage", p.evaluer("document.getElementById('rechReglagesInfo').textContent"))
            # champ vidé : tout est de retour (les groupes sont toujours ouverts : une rubrique à la fois les masque)
            p.evaluer("(() => { const c = document.getElementById('rechReglages'); c.value = ''; c.dispatchEvent(new Event('input', {bubbles: true})); return true; })()")
            self.assertEqual(p.evaluer(etat), [[False, True]] * total)
            self.assertEqual(p.evaluer("document.getElementById('rechReglagesInfo').textContent"), "")
            self.assertEqual(p.erreurs, [])


class RechercheWebReglages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RACINE / "tools"))
        import captures
        cls.captures = captures
        try:
            cls.chrome = captures.navigateur()
        except SystemExit:
            raise unittest.SkipTest("aucun navigateur (Chrome, Chromium ou Edge) trouvé")

    def test_moteurs_searxng_cle_brave_sans_fuite(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = cdp.Page(self.chrome, tmp / "profil-rechweb")
            self.addCleanup(p.fermer)
            p.aller("http://127.0.0.1:%d/#reglages" % port)
            p.attendre("document.getElementById('p-reglages').classList.contains('vue') && document.querySelectorAll('#rechMoteurs .ligne').length >= 2")
            moteurs = "[...document.querySelectorAll('#rechMoteurs .ligne')].map(l => l.textContent)"
            self.assertEqual([m.split('. ')[1] for m in p.evaluer(moteurs)], ["duckduckgo", "bing"])
            saisir = lambda ident, v: p.evaluer("(() => { document.getElementById(%s).value = %s; return true; })()" % (json.dumps(ident), json.dumps(v)))  # noqa: E731
            # une adresse invalide est refusée avec une phrase
            saisir("rechSearxng", "ftp://x")
            p.evaluer("document.getElementById('bRechSearxng').click(); true")
            p.attendre("document.getElementById('rechMsg').textContent.includes('invalide')")
            # une adresse valide passe en tête, avec son étoile
            saisir("rechSearxng", "127.0.0.1:8080/")
            p.evaluer("document.getElementById('bRechSearxng').click(); true")
            p.attendre("document.querySelectorAll('#rechMoteurs .ligne').length === 3")
            self.assertEqual(p.evaluer(moteurs)[0], "1. searxng ★")
            self.assertEqual(p.evaluer("document.getElementById('rechSearxng').value"), "http://127.0.0.1:8080", "l'adresse est normalisée")
            # la clé Brave : enregistrée, champ vidé, seule la fin est montrée, retirable
            saisir("rechBrave", "cle-ui-123456789")
            p.evaluer("document.getElementById('bRechBrave').click(); true")
            p.attendre("document.getElementById('rechBraveEtat').textContent.includes('6789')")
            self.assertEqual(p.evaluer("document.getElementById('rechBrave').value"), "", "le champ est vidé après l'envoi")
            self.assertNotIn("cle-ui-123456789", p.evaluer("document.getElementById('p-reglages').innerText"))
            self.assertNotIn("cle-ui-123456789", p.evaluer("document.documentElement.outerHTML"), "la clé n'est nulle part dans la page")
            self.assertEqual(p.evaluer(moteurs)[1], "2. brave ★")
            p.evaluer("document.getElementById('bRechBraveRetirer').click(); true")
            p.attendre("document.getElementById('rechBraveEtat').textContent.includes('Pas de clé')")
            self.assertEqual(p.erreurs, [])


if __name__ == "__main__":
    unittest.main()
