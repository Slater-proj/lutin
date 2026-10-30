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


CHAMP = "document.querySelector('#modalCorps input[placeholder^=\"Chemin\"]')"


def saisir(page, selecteur, texte):
    """Écrit dans un champ (valeur donnée comme du texte JSON : aucun caractère ne casse l'expression)."""
    page.evaluer("(() => { const c = %s; c.value = %s; return true; })()" % (selecteur, json.dumps(texte)))


LISTE_CHARGEE = "document.querySelectorAll('#modalCorps div[style*=\"max-height\"] > *').length > 0"


def naviguer(page, chemin, attendu):
    """Dans le navigateur de dossiers : attend que la première liste soit affichée (sinon elle effacerait le chemin tapé), tape le chemin, l'ouvre, attend `attendu`."""
    page.attendre("!!" + CHAMP)
    page.attendre(LISTE_CHARGEE)
    saisir(page, CHAMP, chemin)
    page.evaluer(bouton("Ouvrir"))
    dernier = chemin.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    page.attendre("(%s) && (%s.value.split(String.fromCharCode(92)).join('/').endsWith(%s) || !!document.querySelector('#modalCorps .erreur').textContent)" % (attendu, CHAMP, json.dumps(dernier)))


def cliquer_dans_ligne(page, nom, bouton_texte):
    """Clique le bouton d'une ligne de la liste des dossiers de travail (celle qui contient `nom`)."""
    page.evaluer("(() => { const l = [...document.querySelectorAll('#listeTravaux .conv')].find(x => x.textContent.includes(%s)); [...l.querySelectorAll('button')].find(b => b.textContent === %s).click(); })()" % (json.dumps(nom), json.dumps(bouton_texte)))


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

    def test_dossiers_de_travail_choisir_ajouter_deplacer_retirer(self):
        with self.captures.serveur_demo() as (port, tmp):
            autre, rangement = tmp / "Autre", tmp / "Rangement"
            autre.mkdir()
            rangement.mkdir()
            (autre / "notes.txt").write_text("mes notes", encoding="utf-8")
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            self.assertFalse(p.evaluer("!!document.querySelector('#selTravail')"), "plus de sélecteur de dossier dans la barre latérale")
            p.evaluer(onglet("reglages"))
            p.attendre("document.querySelector('#listeTravaux').textContent.includes('★ Projet')")
            # choisir l'autre dossier
            p.evaluer(bouton("Utiliser ce dossier"))
            p.attendre("document.querySelector('#listeTravaux').textContent.includes('★ Documents')")
            # ajouter un dossier avec le navigateur de dossiers : on tape son chemin, on l'ouvre, on le choisit
            p.evaluer(bouton("Ajouter un dossier…"))
            naviguer(p, str(autre), "document.querySelector('#modalCorps').textContent.includes('Aucun sous-dossier')")
            p.evaluer(bouton("Ajouter ce dossier"))
            p.attendre("document.querySelector('#listeTravaux').textContent.includes('★ Autre')")
            # déplacer ses fichiers ailleurs : « Rangement » le contiendra
            cliquer_dans_ligne(p, "Autre", "Déplacer…")
            p.attendre(bouton("Déplacer les fichiers vers un autre endroit"))
            naviguer(p, str(rangement), "document.querySelector('#modalCorps').textContent.includes('Aucun sous-dossier')")
            p.evaluer(bouton("Déplacer ici"))
            p.attendre("document.querySelector('#modal').hidden")
            self.assertTrue((rangement / "Autre" / "notes.txt").is_file(), "les fichiers ont vraiment été déplacés")
            self.assertFalse(autre.exists())
            p.attendre("document.querySelector('#listeTravaux').textContent.includes('Rangement')")
            # il a été déplacé à la main : on corrige seulement son chemin
            (rangement / "Autre").rename(tmp / "Rendu")
            cliquer_dans_ligne(p, "Autre", "Déplacer…")
            p.attendre(bouton("Il a déjà été déplacé : indiquer où il est maintenant"))
            naviguer(p, str(tmp / "Rendu"), "document.querySelector('#modalCorps').textContent.includes('Aucun sous-dossier')")
            p.evaluer(bouton("C'est ici"))
            p.attendre("document.querySelector('#modal').hidden")
            p.attendre("document.querySelector('#listeTravaux').textContent.includes('Rendu')")
            # un chemin qui n'existe pas : l'erreur est dite dans la fenêtre, rien ne casse
            p.evaluer(bouton("Ajouter un dossier…"))
            naviguer(p, str(tmp / "nexiste-pas"), "document.querySelector('#modalCorps .erreur').textContent.includes(\"n'existe pas\")")
            p.evaluer(bouton("Annuler"))
            # retirer le dossier principal, puis tous les autres : c'est permis, Lutin retombe sur son dossier par défaut
            for nom in ("Projet", "Documents", "Autre"):
                p.attendre("[...document.querySelectorAll('#listeTravaux .conv')].some(l => l.textContent.includes(@@))".replace("@@", json.dumps(nom)))
                cliquer_dans_ligne(p, nom, "Retirer")
                p.attendre("!!document.querySelector('#modalCorps button.danger')")          # la fenêtre d'avertissement : on confirme
                p.evaluer("document.querySelector('#modalCorps button.danger').click()")
                p.attendre("![...document.querySelectorAll('#listeTravaux .conv')].some(l => l.textContent.includes(@@))".replace("@@", json.dumps(nom)))
            self.assertIn("dossier par défaut", p.evaluer("document.querySelector('#listeTravaux').textContent"))
            self.assertTrue((tmp / "Rendu" / "notes.txt").is_file(), "les fichiers ne sont jamais supprimés")
            self.assertEqual(p.erreurs, [])

    def test_colonne_redimensionnable_menus_groupes_et_reprise(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            largeur = lambda: p.evaluer("Math.round(document.querySelector('aside').getBoundingClientRect().width)")  # noqa: E731
            avant = largeur()
            # glisser le séparateur vertical avec une vraie souris : la colonne s'élargit, la valeur est retenue
            x = p.evaluer("Math.round(document.getElementById('sepV').getBoundingClientRect().left + 3)")
            p.commande("Input.dispatchMouseEvent", type="mousePressed", x=x, y=300, button="left", clickCount=1)
            p.commande("Input.dispatchMouseEvent", type="mouseMoved", x=x + 140, y=300, button="left")
            p.commande("Input.dispatchMouseEvent", type="mouseReleased", x=x + 140, y=300, button="left", clickCount=1)
            p.attendre("Math.round(document.querySelector('aside').getBoundingClientRect().width) > %d" % (avant + 100))
            self.assertEqual(p.evaluer("localStorage.getItem('lutin.lateral')"), str(largeur()))
            p.evaluer("document.getElementById('sepV').dispatchEvent(new MouseEvent('dblclick'))")
            p.attendre("Math.round(document.querySelector('aside').getBoundingClientRect().width) === %d" % avant)
            # séparateur horizontal : les options changent de hauteur
            haut_avant = p.evaluer("Math.round(document.querySelector('.options-lat').getBoundingClientRect().height)")
            y = p.evaluer("Math.round(document.getElementById('sepH').getBoundingClientRect().top + 3)")
            p.commande("Input.dispatchMouseEvent", type="mousePressed", x=100, y=y, button="left", clickCount=1)
            p.commande("Input.dispatchMouseEvent", type="mouseMoved", x=100, y=y - 60, button="left")
            p.commande("Input.dispatchMouseEvent", type="mouseReleased", x=100, y=y - 60, button="left", clickCount=1)
            p.attendre("Math.round(document.querySelector('.options-lat').getBoundingClientRect().height) > %d" % (haut_avant + 30))
            # les onglets : Automatisation existe et contient les tâches planifiées (plus dans Mémoire)
            self.assertEqual([p.evaluer("document.querySelectorAll('.onglets button')[%d].dataset.p" % i) for i in range(7)], ["chat", "modeles", "memoire", "auto", "reglages", "sante", "acces"])
            p.evaluer(onglet("auto"))
            p.attendre("document.querySelector('#p-auto').classList.contains('vue')")
            self.assertTrue(p.evaluer("!!document.querySelector('#p-auto #listePlanifie')"))
            self.assertFalse(p.evaluer("!!document.querySelector('#p-memoire #listePlanifie')"))
            # les réglages sont rangés en groupes repliables
            p.evaluer(onglet("reglages"))
            groupes = p.evaluer("[...document.querySelectorAll('#p-reglages details.groupe > summary')].map(s => s.textContent.trim())")
            self.assertEqual(groupes, ["Général", "Dossiers et données", "Conversation", "Machine et réglages avancés"])
            self.assertEqual(p.evaluer("document.querySelectorAll('#p-reglages > .cadre > h2').length"), 0, "plus de section isolée hors d'un groupe")
            p.evaluer("document.querySelector('#p-reglages details.groupe[data-g=general] > summary').click()")
            p.attendre("localStorage.getItem('lutin.groupe.general') === '0'")                       # l'évènement « toggle » arrive juste après le clic
            self.assertEqual(p.erreurs, [])

    def test_extensions_activer_un_addon_et_voir_son_panneau(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer(onglet("auto"))
            carte = "[...document.querySelectorAll('#listeAddons .carte')].find(c => c.textContent.includes('Travail de fond') && c.querySelector('input[type=checkbox]'))"
            p.attendre("!!(" + carte + ")")
            self.assertEqual(p.evaluer("document.querySelectorAll('#listeAddons > .carte').length"), 3, "travail de fond, Telegram, ComfyUI")
            self.assertFalse(p.evaluer("(" + carte + ").querySelector('input[type=checkbox]').checked"), "désactivé par défaut")
            self.assertNotIn("Nouveau travail de fond", p.evaluer("document.getElementById('listeAddons').textContent"))
            p.evaluer("(" + carte + ").querySelector('input[type=checkbox]').click()")
            p.attendre("document.getElementById('listeAddons').textContent.includes('Nouveau travail de fond')")
            self.assertTrue(p.evaluer("(" + carte + ").querySelector('input[type=checkbox]').checked"))
            self.assertEqual(p.erreurs, [])

    def test_reprise_proposee_une_fois_puis_plus(self):
        with self.captures.serveur_demo() as (port, tmp):
            ancien = tmp / "ancien-assistant"
            (ancien / "donnees" / "conversations").mkdir(parents=True)
            (ancien / "memoire").mkdir()
            (ancien / "donnees" / "conversations" / "aabbccdd.json").write_text(json.dumps({"id": "aabbccdd", "titre": "Vieille conversation", "date": "2026-10-01T10:00:00", "messages": [{"role": "user", "content": "salut"}], "resume": ""}), encoding="utf-8")
            (ancien / "memoire" / "MEMOIRE.md").write_text("# Mémoire\n\nUne note ancienne.\n", encoding="utf-8")
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer(onglet("reglages"))
            p.attendre(bouton("Ajouter un dossier…"))
            p.evaluer(bouton("Ajouter un dossier…"))
            naviguer(p, str(ancien), "[...document.querySelectorAll('#modalCorps .conv')].some(x => x.textContent.includes('donnees'))")
            p.evaluer(bouton("Ajouter ce dossier"))
            # Lutin dit ce qu'il a trouvé et ouvre tout de suite la reprise, déjà remplie
            p.attendre("document.querySelector('#modalCorps').textContent.includes('Conversations : 1')")
            p.evaluer(bouton("Reprendre"))
            p.attendre("!document.querySelector('#modalCorps input[type=checkbox]')")
            self.assertTrue((tmp / "home" / "donnees" / "conversations" / "aabbccdd.json").is_file())
            p.evaluer("document.getElementById('modalFermer').click()")
            # après la reprise, l'avertissement a disparu et un statut « déjà dans Lutin » le remplace
            p.attendre("document.querySelector('#listeTravaux').textContent.includes('déjà dans Lutin')")
            self.assertNotIn("pas encore dans Lutin", p.evaluer("document.querySelector('#listeTravaux').textContent"))
            p.evaluer(bouton("🔄 Actualiser"))
            p.attendre("document.querySelector('#listeTravaux').textContent.includes('déjà dans Lutin')")
            self.assertNotIn("pas encore dans Lutin", p.evaluer("document.querySelector('#listeTravaux').textContent"))
            self.assertEqual(p.erreurs, [])

    def test_liste_des_modeles_par_familles_sur_deux_lignes_et_sans_filtre_a_part(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer(onglet("modeles"))
            p.attendre("document.querySelectorAll('#listeModeles details.famille').length > 3")
            self.assertFalse(p.evaluer("!!document.querySelector('#listeModeles h2')"), "pas de section sans filtre tant que l'option n'est pas cochée")
            # la famille du modèle installé est ouverte, les autres repliées : la liste se lit d'un coup d'œil
            ouvertes = p.evaluer("[...document.querySelectorAll('#listeModeles details.famille')].filter(d => d.open).map(d => d.querySelector('summary b').textContent)")
            fermees = p.evaluer("[...document.querySelectorAll('#listeModeles details.famille')].filter(d => !d.open).length")
            self.assertIn("Qwen 3", ouvertes)
            self.assertGreater(fermees, 2)
            # tout ouvrir : chaque variante tient sur deux lignes (nom, taille, identifiant, boutons ; puis description)
            p.evaluer("document.querySelectorAll('#listeModeles details.famille').forEach(d => d.open = true)")
            hauteurs = p.evaluer("[...document.querySelectorAll('#listeModeles .mod')].map(m => m.offsetHeight)")
            self.assertTrue(hauteurs and max(hauteurs) <= 70, "une variante : deux lignes au plus ({})".format(max(hauteurs)))
            actif = p.evaluer("(() => { const m = document.querySelector('#listeModeles .mod.actif'); return m ? m.textContent : ''; })()")
            self.assertIn("8 milliards", actif)
            self.assertIn("actif", actif)
            # l'option « avancés » : une section à part, avec ses avertissements, sans attendre le prochain rafraîchissement
            nombre = p.evaluer("document.querySelectorAll('#listeModeles .mod').length")
            p.evaluer("document.querySelector('#cAvance').click()")
            p.attendre("!!document.querySelector('#listeModeles h2')", 8)
            self.assertEqual(p.evaluer("document.querySelector('#listeModeles h2').textContent"), "Modèles sans filtre")
            self.assertTrue(p.evaluer("document.querySelectorAll('#listeModeles .erreur').length >= 1"), "les avertissements sont montrés")
            p.evaluer("document.querySelectorAll('#listeModeles details.famille').forEach(d => d.open = true)")
            p.attendre("document.querySelectorAll('#listeModeles .mod').length > %d" % (nombre + 5))
            self.assertIn("Dolphin 3", p.evaluer("document.querySelector('#listeModeles').textContent"), "les modèles sans filtre du catalogue sont là")
            # replier une famille : la liste se redessine sans la rouvrir
            p.evaluer("document.querySelector('#listeModeles details.famille').open = false")
            p.evaluer("new Promise(r => setTimeout(r, 300))")
            p.evaluer("document.querySelector('#cWeb').click()")                      # un réglage qui redessine la page
            p.evaluer("new Promise(r => setTimeout(r, 1500))")
            self.assertFalse(p.evaluer("document.querySelector('#listeModeles details.famille').open"), "la famille reste repliée")
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
