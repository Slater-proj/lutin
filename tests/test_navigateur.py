"""Des parcours réels dans un vrai Chrome (clics, fenêtres, réponses du serveur) : ce que la lecture du code ne montre pas. Ignoré s'il n'y a pas de navigateur."""
import json
import os
import re
import subprocess
import sys
import time
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
        if "#conv=" in adresse:
            p.attendre("!!document.querySelector('.conv.choisie')")          # la conversation du lien est OUVERTE (sa présence dans la liste ne suffit pas : un message envoyé trop tôt partirait dans une nouvelle conversation)
        return p

    def test_cliquer_une_conversation_ramene_sur_l_onglet_conversation(self):
        """Comme « Nouvelle conversation » : depuis un autre onglet, ouvrir une conversation existante de la liste revient sur l'onglet Conversation."""
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/#conv=a1b2c3d4" % port)
            p.evaluer("document.querySelector('.onglets button[data-p=reglages]').click(); true")
            p.attendre("document.getElementById('p-reglages').classList.contains('vue')")
            self.assertFalse(p.evaluer("document.getElementById('p-chat').classList.contains('vue')"))
            p.evaluer("document.querySelector('.conv').click(); true")
            p.attendre("document.getElementById('p-chat').classList.contains('vue')")
            self.assertFalse(p.evaluer("document.getElementById('p-reglages').classList.contains('vue')"))

    def test_la_page_sante_montre_ce_qui_est_charge_en_memoire(self):
        """La page Santé liste la mémoire utilisée, ce qui est chargé (avec un bouton Décharger quand Lutin sait le faire) et les programmes les plus gourmands, sans erreur même sans Ollama."""
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer("document.querySelector('.onglets button[data-p=sante]').click(); true")
            p.attendre("[...document.querySelectorAll('#santeCorps h2')].some(h => h.textContent.includes('chargé en mémoire'))")
            p.attendre("document.querySelectorAll('#santeCorps progress').length > 0 || document.querySelector('#santeCorps details summary')")
            self.assertEqual(p.evaluer("document.querySelectorAll('#santeCorps .erreur').length"), 0)

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
            self.assertEqual(groupes, ["Général", "Dossiers et données", "Moteur", "Conversation", "Machine et réglages avancés"])
            self.assertEqual(p.evaluer("document.querySelectorAll('#p-reglages > .cadre > h2').length"), 0, "plus de section isolée hors d'un groupe")
            p.evaluer("document.querySelector('#p-reglages details.groupe[data-g=general] > summary').click()")
            p.attendre("localStorage.getItem('lutin.groupe.general') === '0'")                       # l'évènement « toggle » arrive juste après le clic
            self.assertEqual(p.erreurs, [])

    def test_extensions_activer_un_addon_et_voir_son_panneau(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer(onglet("auto"))
            p.attendre("document.getElementById('zoneFond').textContent.includes('Nouveau travail de fond')")
            p.attendre("document.querySelectorAll('#listeAddons > .carte').length >= 4")                          # la liste des extensions se charge à part des deux sections
            self.assertEqual(p.evaluer("document.querySelectorAll('#listeAddons > .carte').length"), 4, "Telegram, ComfyUI, courriel, X : le traitement de documents n'est plus une extension, et les missions sont un mode")
            self.assertFalse(p.evaluer("!!document.getElementById('zoneMissions') || !!document.getElementById('bMission')"), "plus de section ni de bouton Mission : c'est un mode")
            self.assertEqual(p.erreurs, [])

    def test_question_fiche_ou_resume_quand_la_conversation_devient_longue(self):
        """Un message sur une conversation qui dépasse 60 % du contexte : la carte de choix apparaît, un clic répond, la conversation retient « fiche de suivi » et la réponse arrive."""
        with self.captures.serveur_demo() as (port, tmp):
            donnees = tmp / "home" / "donnees"
            reglages = json.loads((donnees / "reglages.json").read_text(encoding="utf-8"))
            reglages["num_ctx"] = 4096
            (donnees / "reglages.json").write_text(json.dumps(reglages), encoding="utf-8")
            conv = self.captures.conversation_demo("d4e5f6a7", "Longue discussion", 5)
            conv["taches"] = []
            conv["messages"] = [{"role": "user" if i % 2 == 0 else "assistant", "content": ("Le code du coffre est 4711. " if i == 0 else "") + "mot " * 220 + str(i)} for i in range(12)]
            (donnees / "conversations" / "d4e5f6a7.json").write_text(json.dumps(conv, ensure_ascii=False), encoding="utf-8")
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/#conv=d4e5f6a7" % port)
            p.attendre("document.body.textContent.includes('Longue discussion')")
            p.evaluer("(() => { const s = document.getElementById('saisie'); s.value = 'Où en est-on ?'; document.getElementById('bEnvoyer').click(); return true; })()")
            p.attendre("!!document.querySelector('.accord')")                       # la carte (le texte seul serait aussi dans le code de la page)
            self.assertIn("Cette conversation devient longue", p.evaluer("document.querySelector('.accord').textContent"))
            self.assertTrue(p.evaluer("[...document.querySelectorAll('.accord input[type=checkbox]')].every(c => c.checked)"), "« garder ce choix » est coché par défaut")
            self.assertTrue(p.evaluer(bouton("Fiche de suivi")))
            p.attendre("[...document.querySelectorAll('#fil .msg.ia')].some(m => m.textContent.includes('Réponse de démonstration.'))")
            sauve = json.loads((donnees / "conversations" / "d4e5f6a7.json").read_text(encoding="utf-8"))
            self.assertEqual(sauve.get("memoire_longue"), "fichier", "le choix est gardé pour cette conversation")
            self.assertLess(len(sauve["messages"]), 14, "en mode fiche, la conversation presque pleine est allégée du début (archivé)")
            self.assertTrue((donnees / "suivis" / "d4e5f6a7.md").is_file(), "la fiche est créée à partir du début de la conversation")
            self.assertIn("Tester la question", (donnees / "suivis" / "d4e5f6a7.md").read_text(encoding="utf-8"))
            self.assertEqual(p.erreurs, [])

    def test_le_panneau_de_chaque_addon_s_affiche_avec_ses_brouillons(self):
        """Les quatre panneaux qui ne s'activent qu'avec un vrai service (Telegram, courriel, X, ComfyUI) : leur code de page tourne sans erreur et montre ses brouillons."""
        with self.captures.serveur_demo() as (port, tmp):
            dossier = tmp / "home" / "donnees" / "addons"
            for ident, etat in (("telegram", {"code": "123456", "autorises": [{"id": 5, "nom": "Moi"}], "brouillons": [{"id": "t1", "chat_id": 9, "de": "Bob", "demande": "Tu es là ?", "texte": "Oui, je regarde.", "date": 1}]}),
                                ("mail", {"brouillons": [{"id": "m1", "de": "Alice", "adresse": "a@x.fr", "sujet": "Devis", "extrait": "Peux-tu me l'envoyer ?", "texte": "Bonjour, le devis arrive demain.", "message_id": "<1@x>", "references": "<1@x>", "date": 1}]}),
                                ("x", {"publications": [{"id": "p1", "texte": "Mon premier message", "etat": "brouillon"}, {"id": "p2", "texte": "Déjà parti", "etat": "publie"}],
                                       "reponses": [{"id": "r1", "de": "@alice", "a": "11", "extrait": "Salut", "texte": "Merci !"}]}),
                                ("comfyui", {})):
                (dossier / ident).mkdir(parents=True, exist_ok=True)
                (dossier / ident / "etat.json").write_text(json.dumps(etat), encoding="utf-8")
            (dossier / "addons.json").write_text(json.dumps({ident: {"actif": True} for ident in ("telegram", "mail", "x", "comfyui")}), encoding="utf-8")
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer(onglet("auto"))
            texte = "document.getElementById('listeAddons').textContent"
            p.attendre("%s.includes('Brouillon pour Bob') && %s.includes('Brouillon pour Alice') && %s.includes('Réponse à @alice') && %s.includes('Dossier de ComfyUI non défini')" % ((texte,) * 4))
            contenu = p.evaluer(texte)
            for attendu in ("/appairer 123456", "Devis", "✔ Publié", "Publier maintenant", "Publier la réponse"):
                self.assertIn(attendu, contenu)
            self.assertTrue(p.evaluer("[...document.querySelectorAll('#listeAddons button')].some(b => b.textContent === 'Détecter') && [...document.querySelectorAll('#listeAddons button')].some(b => b.textContent === 'Choisir le dossier…')"),
                            "ComfyUI : « Détecter » et « Choisir le dossier… » sont visibles")
            self.assertEqual(p.evaluer("[...document.querySelectorAll('#listeAddons .erreur')].filter(e => e.textContent.trim()).length"), 0, "« pas encore configuré » n'est pas une erreur : rien en rouge")
            # pas de clignotement : la liste ne change pas sous les yeux (les panneaux ne disparaissent jamais le temps d'un rafraîchissement) et n'est pas reconstruite si rien n'a changé
            p.evaluer("window.__carte = document.querySelector('#listeAddons > .carte')")
            for _ in range(36):
                self.assertTrue(p.evaluer("document.getElementById('listeAddons').textContent.includes('Dossier de ComfyUI non défini') && document.getElementById('listeAddons').textContent.includes('Brouillon pour Bob')"), "un panneau a disparu")
                time.sleep(0.3)
            self.assertTrue(p.evaluer("document.body.contains(window.__carte)"), "rien n'a changé : la liste n'a pas été reconstruite")
            brouillons = p.evaluer("[...document.querySelectorAll('#listeAddons textarea')].map(t => t.value).join(' | ')")
            for attendu in ("Oui, je regarde.", "Bonjour, le devis arrive demain.", "Mon premier message", "Merci !"):
                self.assertIn(attendu, brouillons, "les brouillons sont dans des champs modifiables")
            self.assertEqual(p.erreurs, [])

    def test_menu_de_la_conversation_addon_a_configurer_et_jauge_de_disque(self):
        """Le menu « ⋯ » d'une conversation (épingler, renommer, fiche de suivi ou résumé), une case d'addon non configuré qui ouvre sa configuration au lieu d'une erreur, et la jauge de disque des modèles."""
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.attendre("document.querySelectorAll('#conversations .conv').length >= 3")
            self.assertEqual(p.evaluer("document.querySelectorAll('#conversations .conv:first-child button').length"), 2, "deux boutons par conversation : « ⋯ » et la croix")
            self.assertEqual(p.evaluer("[...document.querySelectorAll('#conversations .conv:first-child button')].map(b => b.textContent).join(' ')"), "⋯ ✕")
            p.evaluer("document.querySelector('#conversations .conv:first-child button.menu-ouvrir').click()")
            p.attendre("!!document.querySelector('.menu-conv')")
            menu = p.evaluer("document.querySelector('.menu-conv').textContent")
            for attendu in ("Renommer", "Fiche de suivi", "Résumé automatique", "Suivre le réglage général"):
                self.assertIn(attendu, menu)
            self.assertIn("✔ Suivre le réglage général", menu, "le choix actuel est coché")
            p.evaluer("[...document.querySelectorAll('.menu-conv button')].find(b => b.textContent.includes('Résumé automatique')).click()")
            p.attendre("!document.querySelector('.menu-conv')")
            time.sleep(1.5)                                                         # la liste se recharge après le choix
            p.evaluer("document.querySelector('#conversations .conv:first-child button.menu-ouvrir').click()")
            p.attendre("!!document.querySelector('.menu-conv')")
            self.assertIn("✔ Résumé automatique", p.evaluer("document.querySelector('.menu-conv').textContent"), "le choix est retenu")
            p.evaluer("document.body.click()")
            p.attendre("!document.querySelector('.menu-conv')")
            # une case d'addon à configurer : elle ouvre la configuration, sans erreur
            p.evaluer(onglet("auto"))
            carte = "[...document.querySelectorAll('#listeAddons > .carte')].find(c => c.textContent.includes('Telegram'))"
            p.attendre("!!(" + carte + ")")
            self.assertIn("À configurer d'abord", p.evaluer("(" + carte + ").textContent"))
            p.evaluer("(" + carte + ").querySelector('input[type=checkbox]').click()")
            p.attendre("document.getElementById('modalCorps').textContent.includes('Remplis d')")
            self.assertFalse(p.evaluer("(" + carte + ").querySelector('input[type=checkbox]').checked"), "pas activé tant que ce n'est pas configuré")
            self.assertEqual(p.evaluer("document.querySelector('#listeAddons .erreur') ? document.querySelector('#listeAddons .erreur').textContent : ''"), "", "aucun message d'erreur sur la carte")
            # la jauge de disque des modèles : une vraie barre en segments avec sa légende
            p.evaluer("document.getElementById('modal').hidden = true")
            p.evaluer(onglet("modeles"))
            p.attendre("!!document.querySelector('.barre-disque')")
            self.assertEqual(p.evaluer("document.querySelectorAll('.barre-disque > i').length"), 2)
            self.assertIn("Libre", p.evaluer("document.querySelector('.legende-disque').textContent"))
            # la barre de contexte n'a plus de cadre ni de hauteur imposée
            self.assertEqual(p.evaluer("getComputedStyle(document.getElementById('jauge')).borderTopWidth"), "0px")
            self.assertEqual(p.erreurs, [])

    def test_la_liste_des_modeles_de_comfyui_est_lisible_et_reste_ouverte(self):
        """36 noms collés bout à bout étaient illisibles et la liste se refermait pendant la lecture : maintenant des lignes, groupées, avec la famille, qui restent ouvertes au rafraîchissement."""
        with self.captures.serveur_demo() as (port, tmp):
            comfy = tmp / "ComfyUI"
            (comfy / "models").mkdir(parents=True)
            (comfy / "main.py").write_text("#", encoding="utf-8")
            fichiers = {"checkpoints": ["sdxl_base.safetensors"], "diffusion_models": ["flux1-dev-fp8.safetensors", "qwen_image_fp8.safetensors", "mystere.safetensors"],
                        "loras": ["style_%02d.safetensors" % i for i in range(20)], "vae": ["ae.safetensors"], "text_encoders": ["t5xxl_fp16.safetensors", "clip_l.safetensors"]}
            for genre, noms in fichiers.items():
                (comfy / "models" / genre).mkdir()
                for n in noms:
                    (comfy / "models" / genre / n).write_bytes(b"x")
            dossier = tmp / "home" / "donnees" / "addons"
            dossier.mkdir(parents=True, exist_ok=True)
            (dossier / "addons.json").write_text(json.dumps({"comfyui": {"actif": True, "reglages": {"dossier": str(comfy)}}}), encoding="utf-8")
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer(onglet("auto"))
            resume = "[...document.querySelectorAll('#listeAddons details > summary')].find(s => s.textContent.startsWith('Modèles installés'))"
            p.attendre("!!(" + resume + ")")
            self.assertIn("(27)", p.evaluer(resume + ".textContent"), "le nombre total est dit")
            p.evaluer(resume + ".click()")
            p.attendre("!!document.querySelector('#listeAddons .liste-modeles')")
            texte = p.evaluer("document.querySelector('#listeAddons details').textContent")
            for attendu in ("Modèles d'images (1)", "Modèles de diffusion (3)", "flux1-dev-fp8", "Flux", "Qwen-Image", "famille inconnue", "Styles et personnages (LoRA) (20)"):
                self.assertIn(attendu, texte)
            self.assertNotIn(" · ", p.evaluer("document.querySelector('#listeAddons .liste-modeles').textContent"), "plus de noms collés bout à bout")
            self.assertEqual(p.evaluer("document.querySelectorAll('#listeAddons details:not(.sous) > .liste-modeles > div').length"), 4, "une ligne par modèle de génération")
            self.assertTrue(p.evaluer("[...document.querySelectorAll('#listeAddons details.sous')].every(d => !d.open)"), "les fichiers associés sont repliés")
            self.assertEqual(p.evaluer("getComputedStyle(document.querySelector('#listeAddons .liste-modeles')).overflowY"), "auto", "une longue liste défile au lieu d'allonger la page")
            p.evaluer("[...document.querySelectorAll('#listeAddons details.sous > summary')].find(s => s.textContent.includes('LoRA')).click()")
            p.attendre("document.querySelectorAll('#listeAddons details.sous[open]').length === 1")
            time.sleep(9.5)                                                                # deux rafraîchissements automatiques plus tard
            self.assertTrue(p.evaluer("document.querySelector('#listeAddons details').open"), "la liste ne se referme pas toute seule")
            self.assertEqual(p.evaluer("document.querySelectorAll('#listeAddons details.sous[open]').length"), 1, "ni le bloc des styles")
            self.assertEqual(p.erreurs, [])

    def test_cases_auto_enregistrees_file_d_attente_et_pastilles_de_travail(self):
        """La mécanique autour des conversations : les cases d'accord automatique tiennent après rechargement, un message envoyé pendant une réponse attend dans la file, l'icône « travail en cours » s'allume,
        puis la pastille verte « réponse terminée, pas lue » apparaît si on était ailleurs et s'éteint à la lecture."""
        with self.captures.serveur_demo() as (port, tmp):
            donnees = tmp / "home" / "donnees"
            adresse = "http://127.0.0.1:%d/#conv=a1b2c3d4" % port
            p = self.ouvrir(tmp, adresse)
            p.attendre("!!window.ETAT_PRET || document.getElementById('cAutoCmd') !== null")
            p.attendre("document.querySelectorAll('#fil .msg').length > 0")
            p.attendre("document.getElementById('selMode').dataset.init === '1'")
            # le modèle est tout en haut à gauche, à côté du nom ; les accords automatiques sont décochés par défaut
            self.assertTrue(p.evaluer("!!document.querySelector('aside h1 #selModele')"), "le modèle est dans l'en-tête, à côté de « Lutin »")
            self.assertFalse(p.evaluer("document.getElementById('cAuto').checked || document.getElementById('cAutoCmd').checked"), "décochés par défaut")
            self.assertEqual(p.evaluer("[...document.querySelectorAll('.options-lat label')].map(l => l.textContent.trim()).filter(x => /auto/.test(x)).join('|')"), "Fichiers auto|Commandes auto")
            # deux cases cochées à la suite : les deux sont enregistrées, pour CETTE conversation
            p.evaluer("document.getElementById('cAuto').click(); document.getElementById('cAutoCmd').click(); true")
            fichier = donnees / "options" / "a1b2c3d4.json"
            debut_attente = time.time()
            r = {}
            while time.time() - debut_attente < 10:
                if fichier.is_file():
                    r = json.loads(fichier.read_text(encoding="utf-8"))
                    if r.get("auto_ecriture") and r.get("auto_commandes"):
                        break
                time.sleep(0.3)
            self.assertTrue(r.get("auto_ecriture") and r.get("auto_commandes"), "les deux cases sont enregistrées avec la conversation : %r" % r)
            reglages = json.loads((donnees / "reglages.json").read_text(encoding="utf-8"))
            self.assertFalse(reglages.get("auto_ecriture") or reglages.get("auto_commandes"), "...et pas dans les réglages communs")
            # une autre conversation a les siennes (décochées) ; revenir à la première retrouve ses cases
            p.evaluer("document.querySelector('.conv[data-id=\"b2c3d4e5\"]').click(); true")
            p.attendre("document.querySelector('.conv.choisie') && document.querySelector('.conv.choisie').dataset.id === 'b2c3d4e5' && !document.getElementById('cAuto').checked && !document.getElementById('cAutoCmd').checked")
            p.evaluer("document.querySelector('.conv[data-id=\"a1b2c3d4\"]').click(); true")
            p.attendre("document.getElementById('cAuto').checked && document.getElementById('cAutoCmd').checked")
            # une nouvelle conversation repart décochée
            p.evaluer("document.getElementById('bNouvelle').click(); true")
            p.attendre("!document.getElementById('cAuto').checked && !document.getElementById('cAutoCmd').checked")
            p.evaluer("document.querySelector('.conv[data-id=\"a1b2c3d4\"]').click(); true")
            p.attendre("document.getElementById('cAuto').checked")
            p.evaluer("location.reload()")
            p.attendre("document.getElementById('cAutoCmd') !== null && document.querySelectorAll('#fil .msg').length > 0")
            p.attendre("document.getElementById('selMode').dataset.init === '1'")
            self.assertTrue(p.evaluer("document.getElementById('cAuto').checked && document.getElementById('cAutoCmd').checked"), "cochées après rechargement, pour cette conversation")
            self.assertTrue(p.evaluer("!document.getElementById('cAuto').disabled && !document.getElementById('cAutoCmd').disabled"), "toujours utilisables")
            # un message lent, puis un second envoyé pendant la réponse : il attend dans la file
            p.evaluer("(() => { const s = document.getElementById('saisie'); s.value = '[lent] premier'; document.getElementById('bEnvoyer').click(); return true; })()")
            p.attendre("!document.getElementById('ptTravail').hidden && !document.getElementById('ptTravail').classList.contains('fini')")        # l'icône « travail en cours »
            p.evaluer("(() => { const s = document.getElementById('saisie'); s.value = 'second'; document.getElementById('bEnvoyer').click(); return true; })()")
            p.attendre("!document.getElementById('fileAttente').hidden && document.getElementById('fileAttente').textContent.includes('second')")
            p.attendre("[...document.querySelectorAll('#fil .msg.ia')].filter(m => m.textContent.includes('Réponse de démonstration.')).length >= 2", delai=40)   # les deux réponses arrivent, dans l'ordre
            p.attendre("document.getElementById('fileAttente').hidden")
            p.attendre("document.getElementById('ptTravail').hidden")                                                                       # lu sur place : aucune pastille
            # on s'en va ailleurs pendant la réponse : pastille verte à la fin, qui s'éteint quand on revient lire
            p.evaluer("(() => { const s = document.getElementById('saisie'); s.value = '[lent] troisième'; document.getElementById('bEnvoyer').click(); return true; })()")
            p.attendre("!document.getElementById('ptTravail').hidden")
            p.evaluer(onglet("memoire"))
            p.attendre("!document.getElementById('ptTravail').hidden && document.getElementById('ptTravail').classList.contains('fini')", delai=40)
            p.evaluer(onglet("chat"))
            p.attendre("document.getElementById('ptTravail').hidden")
            self.assertEqual(p.erreurs, [])

    def test_mission_longue_est_un_mode_et_la_conversation_sert_de_compte_rendu(self):
        """Choisir le mode « Mission longue », décrire la mission dans le champ habituel : elle se lance DANS la conversation, un bandeau montre son état et la conversation se remplit toute seule. Le modèle est près du nom."""
        with self.captures.serveur_demo() as (port, tmp):
            donnees = tmp / "home" / "donnees"
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.attendre("document.getElementById('selMode').dataset.init === '1'")
            self.assertGreater(p.evaluer("document.getElementById('selModele').getBoundingClientRect().width"), 120, "la liste des modèles est assez large pour lire le nom")
            ecart = p.evaluer("(() => { const t = document.querySelector('aside h1'), s = document.getElementById('selModele').getBoundingClientRect(); const r = document.createRange(); r.selectNodeContents([...t.childNodes].find(n => n.nodeType === 3 && n.textContent.includes('Lutin'))); return s.left - r.getBoundingClientRect().right; })()")
            self.assertLess(ecart, 24, "le modèle est tout près du nom « Lutin » (écart %s px)" % ecart)
            self.assertFalse(p.evaluer("!!document.getElementById('bMission')"), "pas de bouton Mission : c'est un mode de la liste")
            self.assertTrue(p.evaluer("[...document.querySelectorAll('#selMode option')].some(o => o.value === 'mission')"), "« Mission longue » est dans la liste des modes")
            self.assertTrue(p.evaluer("document.getElementById('ligneDuree').hidden"), "la durée n'apparaît que dans ce mode")
            p.evaluer("(() => { const s = document.getElementById('selMode'); s.value = 'mission'; s.dispatchEvent(new Event('change')); return true; })()")
            p.attendre("!document.getElementById('ligneDuree').hidden && document.querySelector('#bEnvoyer .lb').textContent === 'Lancer'")
            self.assertIn("Décris la mission", p.evaluer("document.getElementById('saisie').placeholder"))
            p.evaluer("(() => { const s = document.getElementById('saisie'); s.value = 'Crée un petit jeu de pierre-feuille-ciseaux avec des tests.'; document.getElementById('bEnvoyer').click(); return true; })()")
            debut = time.time()
            missions = []
            while time.time() - debut < 15 and not missions:
                if (donnees / "missions.json").exists():
                    missions = json.loads((donnees / "missions.json").read_text(encoding="utf-8"))
                time.sleep(0.3)
            self.assertEqual(len(missions), 1, "la mission est créée")
            self.assertTrue(missions[0]["lie"] and missions[0]["conv"], "...et menée dans une conversation")
            self.assertIn("pierre-feuille-ciseaux", missions[0]["cahier"])
            self.assertEqual(p.evaluer("document.getElementById('saisie').value"), "", "le champ est vidé")
            p.attendre("!document.getElementById('bandeauMission').hidden && document.getElementById('bandeauMission').textContent.includes('Mission')", delai=30)      # le bandeau de suivi
            # la conversation se remplit toute seule : le cahier des charges, puis les réponses de Lutin
            p.attendre("document.getElementById('fil').textContent.includes('pierre-feuille-ciseaux') && document.getElementById('fil').textContent.includes('Réponse de démonstration.')", delai=40)
            fichier = donnees / "conversations" / (missions[0]["conv"] + ".json")
            self.assertTrue(fichier.is_file())
            self.assertTrue(json.loads(fichier.read_text(encoding="utf-8"))["titre"].startswith("🎯"), "la conversation porte le nom de la mission")
            self.assertEqual(p.erreurs, [])

    def test_la_fiche_de_suivi_se_voit_se_modifie_et_se_supprime_depuis_le_menu_de_chaque_conversation(self):
        """Menu « … » d'une conversation : Voir ou modifier la fiche (même si ce n'est pas la conversation ouverte), puis Supprimer la fiche."""
        with self.captures.serveur_demo() as (port, tmp):
            donnees = tmp / "home" / "donnees"
            (donnees / "suivis").mkdir(parents=True, exist_ok=True)
            fiche = donnees / "suivis" / "b2c3d4e5.md"
            fiche.write_text("## Objectif\n- Tester la fiche\n\n## Décisions\n- Le code est 4711\n", encoding="utf-8")
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)               # la conversation ouverte n'est PAS b2c3d4e5
            p.attendre("document.querySelector('#conversations .conv[data-id=\"b2c3d4e5\"] button.menu-ouvrir') !== null")
            p.evaluer("window.confirm = () => true; document.querySelector('#conversations .conv[data-id=\"b2c3d4e5\"] button.menu-ouvrir').click(); true")
            p.attendre("!!document.querySelector('.menu-conv')")
            menu = p.evaluer("document.querySelector('.menu-conv').textContent")
            self.assertIn("Voir ou modifier la fiche", menu)
            self.assertIn("Supprimer la fiche", menu)
            # consulter et modifier
            p.evaluer("[...document.querySelectorAll('.menu-conv button')].find(b => b.textContent.includes('Voir ou modifier la fiche')).click(); true")
            p.attendre("!document.getElementById('modal').hidden && !!document.querySelector('#modalCorps textarea')")
            self.assertIn("Le code est 4711", p.evaluer("document.querySelector('#modalCorps textarea').value"), "la fiche de CETTE conversation s'affiche")
            p.evaluer("(() => { const z = document.querySelector('#modalCorps textarea'); z.value = z.value + '\\n## Fait\\n- Première étape terminée\\n'; return true; })()")
            p.evaluer("[...document.querySelectorAll('#modalCorps button')].find(b => b.textContent.includes('Enregistrer la fiche')).click(); true")
            p.attendre("document.getElementById('modalCorps').textContent.includes('Fiche enregistrée')")
            self.assertIn("Première étape terminée", fiche.read_text(encoding="utf-8"), "la modification est écrite dans la fiche")
            p.evaluer("document.getElementById('modalFermer').click(); true")
            # supprimer depuis le menu
            p.evaluer("document.querySelector('#conversations .conv[data-id=\"b2c3d4e5\"] button.menu-ouvrir').click(); true")
            p.attendre("!!document.querySelector('.menu-conv')")
            p.evaluer("[...document.querySelectorAll('.menu-conv button')].find(b => b.textContent.includes('Supprimer la fiche')).click(); true")
            debut = time.time()
            while time.time() - debut < 10 and fiche.exists():
                time.sleep(0.3)
            self.assertFalse(fiche.exists(), "la fiche est supprimée")
            self.assertEqual(p.erreurs, [])

    def test_epingler_un_message_depuis_la_page(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/#conv=a1b2c3d4" % port)
            p.attendre("[...document.querySelectorAll('.actions button')].some(b => b.textContent.includes('Épingler'))")
            self.assertEqual(p.evaluer("[...document.querySelectorAll('.actions button')].filter(b => b.textContent.includes('Épingler')).length"), 2, "un bouton sur la demande et un sur la réponse")
            p.evaluer("[...document.querySelectorAll('.actions button')].find(b => b.textContent.includes('Épingler')).click()")
            p.attendre("!!document.querySelector('.msg.epingle-msg') && [...document.querySelectorAll('.actions button')].some(b => b.textContent.includes('Épinglé'))")
            sauve = json.loads((tmp / "home" / "donnees" / "conversations" / "a1b2c3d4.json").read_text(encoding="utf-8"))
            self.assertEqual([i for i, m in enumerate(sauve["messages"]) if m.get("epingle")], [0], "le premier message (la demande) est épinglé sur le disque")
            p.evaluer("[...document.querySelectorAll('.actions button')].find(b => b.textContent.includes('Épinglé')).click()")
            p.attendre("!document.querySelector('.msg.epingle-msg')")
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

    def test_recherche_par_le_sens_progression_suppression_et_ligne_dans_la_liste_des_modeles(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.attendre("document.querySelector('#pOllama').textContent.includes('Ollama prêt')")          # le premier état du serveur est arrivé : on ne fabrique le faux qu'après
            # l'état d'Ollama est fabriqué : téléchargement à 45 %, puis modèle installé
            p.evaluer("""(() => { window.__emb = {actif: true, modele: 'nomic-embed-text', installe: false, installation: {etat: 'en cours', fait: 45000000, total: 100000000, erreur: '', texte: 'pulling'}};
                const vrai = window.fetch.bind(window);
                window.fetch = async (u, o) => { const r = await vrai(u, o); if (!String(u).includes('/api/etat')) return r; const d = await r.json(); d.embeddings = window.__emb;
                  if (window.__emb.installe) { d.installes = [...d.installes, 'nomic-embed-text']; d.modeles = [...d.modeles, {id: 'nomic-embed-text', nom: 'nomic-embed-text', go: 0.3, role: 'perso', origine: 'installe', embedding: true}]; }
                  return new Response(JSON.stringify(d), {status: 200, headers: {'Content-Type': 'application/json'}}); }; })()""")
            p.evaluer(onglet("reglages"))
            p.evaluer("document.querySelector('#cSens').checked = true; document.querySelector('#cSens').dispatchEvent(new Event('change'))")
            p.attendre("document.querySelector('#aideSens').textContent.includes('45 %')", 25)
            self.assertTrue(p.evaluer("!!document.querySelector('#aideSens .barre i')"), "une barre de progression")
            self.assertIn("45 / 100", p.evaluer("document.querySelector('#aideSens').textContent"))
            p.evaluer("window.__emb.installe = true; window.__emb.installation = {etat: 'fini', fait: 100000000, total: 100000000, erreur: '', texte: ''}")
            p.attendre("[...document.querySelectorAll('#aideSens button')].some(b => b.textContent === 'Supprimer ce modèle')", 25)
            self.assertIn("Modèle de recherche installé", p.evaluer("document.querySelector('#aideSens').textContent"))
            # dans l'onglet Modèles : une puce explique à quoi il sert, et aucun « Utiliser » ni banc d'essai
            p.evaluer(onglet("modeles"))
            p.attendre("document.querySelectorAll('#listeModeles details.famille, #listeModeles .mod').length > 3")
            p.evaluer("document.querySelectorAll('#listeModeles details.famille').forEach(d => d.open = true)")
            ligne = "[...document.querySelectorAll('#listeModeles .mod')].find(m => m.textContent.includes('nomic-embed-text'))"
            p.attendre("!!(" + ligne + ")", 12)
            self.assertIn("recherche par le sens", p.evaluer(ligne + ".querySelector('.mod-nom').textContent"))
            boutons = p.evaluer("[..." + ligne + ".querySelectorAll('button')].map(b => b.textContent)")
            self.assertNotIn("Utiliser", boutons)
            self.assertNotIn("⏱", boutons)
            self.assertIn("Supprimer", boutons)
            options = p.evaluer("[...document.querySelectorAll('#selModele option')].map(o => o.value).join(',')")
            self.assertNotIn("nomic", options, "le modèle de recherche ne se choisit pas pour discuter")
            self.assertIn("qwen3:8b", options)

    def test_pastille_de_telechargement_dans_la_barre_du_haut(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer("""(() => { window.__pulls = {'qwen3:4b-q8_0': {statut: 'en cours', fait: 45000000, total: 100000000, texte: 'pulling'}};
                const vrai = window.fetch.bind(window);
                window.fetch = async (u, o) => { const r = await vrai(u, o); if (!String(u).includes('/api/etat')) return r; const d = await r.json(); d.pulls = window.__pulls;
                  return new Response(JSON.stringify(d), {status: 200, headers: {'Content-Type': 'application/json'}}); }; })()""")
            p.attendre("!document.querySelector('#bandeauTelechargements').hidden", 25)
            texte = p.evaluer("document.querySelector('#bandeauTelechargements').textContent")
            self.assertIn("qwen3:4b-q8_0", texte)
            self.assertIn("45 % (45 / 100", texte)
            self.assertTrue(p.evaluer("!!document.querySelector('#bandeauTelechargements .barre i')"), "une barre de progression, dans le bandeau bleu : la barre du haut n'est pas encombrée")
            self.assertTrue(p.evaluer("document.querySelector('#pOllama').parentElement.querySelectorAll('button.puce').length === 0"))
            p.evaluer("window.__pulls = {'qwen3:4b-q8_0': {statut: 'erreur', fait: 0, total: 0, texte: 'pas de réseau'}}")
            p.attendre("document.querySelector('#bandeauTelechargements').textContent.includes('échoué')", 25)
            self.assertIn("pas de réseau", p.evaluer("document.querySelector('#bandeauTelechargements').textContent"))
            self.assertTrue(p.evaluer("[...document.querySelectorAll('#bandeauTelechargements button')].some(b => b.textContent === 'Réessayer')"))
            hauteur = "document.querySelector('#bandeauTelechargements').offsetHeight"
            self.assertLess(p.evaluer(hauteur), 140, "le bandeau reste une bande fine, même avec une erreur")
            p.evaluer("window.__pulls = {'qwen3:4b-q8_0': {statut: 'en cours', fait: 90000000, total: 100000000, texte: 'pulling'}}")
            p.attendre("document.querySelector('#bandeauTelechargements').textContent.includes('90 %')", 25)
            self.assertLess(p.evaluer(hauteur), 140)
            p.evaluer("window.__pulls = {'qwen3:4b-q8_0': {statut: 'termine', fait: 100000000, total: 100000000, texte: 'success'}}")
            p.attendre("document.querySelector('#bandeauTelechargements').textContent.includes('installé')", 25)
            self.assertLess(p.evaluer(hauteur), 140, "« installé » ne prend pas la moitié de l'écran")
            p.evaluer("window.__pulls = {'qwen3:4b-q8_0': {statut: 'erreur', fait: 0, total: 0, texte: 'pas de réseau'}}")
            p.attendre("document.querySelector('#bandeauTelechargements').textContent.includes('échoué')", 25)
            p.evaluer("[...document.querySelectorAll('#bandeauTelechargements button')].find(b => b.textContent === 'Fermer').click()")
            self.assertNotIn("échoué", p.evaluer("document.querySelector('#bandeauTelechargements').textContent"), "fermer l'erreur la retire du bandeau")

    def test_copier_un_lien_marche_meme_sans_presse_papiers_moderne(self):
        """Page en http (adresse du réseau local) : navigator.clipboard n'existe pas, la copie passe par un champ temporaire sélectionné."""
        with self.captures.serveur_demo() as (port, tmp):
            donnees = tmp / "home" / "donnees"
            conv = self.captures.conversation_demo("e5f6a7b8", "Un lien", 5)
            conv["taches"] = []
            conv["messages"] = [{"role": "user", "content": "Donne-moi le lien"}, {"role": "assistant", "content": "Voici le lien :" + chr(10) + "```" + chr(10) + "https://exemple.org/page?a=1&b=2" + chr(10) + "```"}]
            (donnees / "conversations" / "e5f6a7b8.json").write_text(json.dumps(conv, ensure_ascii=False), encoding="utf-8")
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/#conv=e5f6a7b8" % port)
            p.attendre("!!document.querySelector('#fil .btn-copier')", 12)
            p.evaluer("""(() => { Object.defineProperty(navigator, 'clipboard', {value: undefined, configurable: true});
                window.__copie = null; document.execCommand = c => { const a = document.activeElement; window.__copie = (c === 'copy' && a && a.tagName === 'TEXTAREA') ? a.value.slice(a.selectionStart, a.selectionEnd) : null; return true; }; })()""")
            p.evaluer("document.querySelector('#fil .btn-copier').click()")
            p.attendre("window.__copie !== null", 8)
            self.assertEqual(p.evaluer("window.__copie"), "https://exemple.org/page?a=1&b=2", "le lien entier est sélectionné au moment de la copie")
            self.assertEqual(p.evaluer("document.querySelector('#fil .btn-copier').textContent"), "Copié !")
            self.assertFalse(p.evaluer("!!document.querySelector('body > textarea')"), "le champ temporaire est retiré")

    def test_point_jaune_quand_l_assistant_attend_une_action_humaine(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.attendre("document.querySelectorAll('#liste .conv, .conv').length > 0", 12)
            ident = p.evaluer("document.querySelector('.conv').dataset.id")
            p.evaluer("""(() => { window.__attente = []; const vrai = window.fetch.bind(window);
                window.fetch = async (u, o) => { const r = await vrai(u, o); if (!String(u).includes('/api/etat')) return r; const d = await r.json(); d.en_attente = window.__attente;
                  return new Response(JSON.stringify(d), {status: 200, headers: {'Content-Type': 'application/json'}}); }; })()""")
            p.evaluer("window.__attente = [%r]" % ident)
            p.attendre("!!document.querySelector('.conv .travail.wait')", 25)
            self.assertTrue(p.evaluer("document.querySelector('#ptTravail').classList.contains('wait') && !document.querySelector('#ptTravail').hidden"), "le point de l'onglet Conversation devient jaune aussi")
            self.assertIn("attend", p.evaluer("document.querySelector('.conv .travail.wait').title"))
            p.evaluer(onglet("reglages"))
            self.assertTrue(p.evaluer("document.querySelector('#ptTravail').classList.contains('wait')"), "visible depuis n'importe quel onglet")
            p.evaluer("window.__attente = []")
            p.attendre("!document.querySelector('.conv .travail.wait')", 25)
            self.assertFalse(p.evaluer("document.querySelector('#ptTravail').classList.contains('wait')"))

    def test_nom_de_modele_trop_long_coupe_le_nom_pas_les_pastilles(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer(onglet("modeles"))
            p.attendre("document.querySelectorAll('#listeModeles details.famille').length > 3")
            p.evaluer("document.querySelectorAll('#listeModeles details.famille').forEach(d => d.open = true)")
            p.attendre("document.querySelectorAll('#listeModeles .mod-nom .puce').length > 0", 12)
            p.evaluer("document.querySelectorAll('#listeModeles .mod-nom').forEach(n => { n.style.width = '230px'; n.style.maxWidth = '230px'; })")        # un nom qui ne tient pas dans la ligne
            ok = p.evaluer("""(() => { const lignes = [...document.querySelectorAll('#listeModeles .mod-nom')].filter(n => n.querySelector('.puce.ok, .puce.warn, .puce.bad'));
                if (!lignes.length) return 'aucune';
                for (const n of lignes) { const cadre = n.getBoundingClientRect(); for (const pu of n.querySelectorAll('.puce')) { const r = pu.getBoundingClientRect(); if (r.width > 0 && r.right > cadre.right + 1) return 'puce coupée : ' + pu.textContent; } }
                const coupe = lignes.some(n => { const t = n.querySelector('.mod-tete'); return t && t.scrollWidth > t.clientWidth; });
                return coupe ? 'ok' : 'rien de coupé'; })()""")
            self.assertEqual(ok, "ok", ok)

    def test_precision_des_modeles_et_comparaison_cote_a_cote(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer(onglet("modeles"))
            p.attendre("document.querySelectorAll('#listeModeles details.famille').length > 3")
            p.evaluer("document.querySelectorAll('#listeModeles details.famille').forEach(d => d.open = true)")
            # les variantes sont lues sur ollama.com : ici une réponse fabriquée
            p.evaluer("""(() => { const vrai = window.fetch.bind(window); window.fetch = (u, o) => String(u).includes('/api/variantes') ? Promise.resolve(new Response(JSON.stringify({modele: 'qwen3:8b', defaut: {id: 'qwen3:8b', go: 5.2},
                variantes: [{precision: 'q4_K_M', id: 'qwen3:8b-q4_K_M', go: 5.2, defaut: true, installe: false, niveau: 'bien', jugement: 'ok', explication: 'Le défaut.'},
                            {precision: 'q8_0', id: 'qwen3:8b-q8_0', go: 8.9, defaut: false, installe: false, niveau: 'limite', jugement: 'tient à peine', explication: 'Presque sans perte.'}]}), {status: 200, headers: {'Content-Type': 'application/json'}})) : vrai(u, o); })()""")
            p.evaluer("""(() => { const m = [...document.querySelectorAll('#listeModeles .mod')].find(m => m.querySelector('.mod-nom').textContent.includes(' qwen3:8b') || m.querySelector('.mod-nom').textContent.includes('· qwen3:8b'));
                [...m.querySelectorAll('button')].find(b => b.textContent === 'Précision').click(); })()""")
            p.attendre("!!document.querySelector('#listeModeles .mod-variantes .banc-ligne')", 8)
            texte = p.evaluer("document.querySelector('#listeModeles .mod-variantes').textContent")
            self.assertIn("q8_0", texte)
            self.assertIn("8.9", texte)
            self.assertIn("celle installée par défaut", texte)
            self.assertIn("★ actif", p.evaluer("document.querySelector('#listeModeles .mod-variantes').textContent"), "qwen3:8b est le modèle actif : sa variante par défaut (4 bits) l'est aussi")
            self.assertTrue(p.evaluer("[...document.querySelectorAll('#listeModeles .mod-variantes button')].some(b => b.textContent === 'Installer')"))
            # la comparaison : cocher un modèle installé active le bouton ; sans mesure complète, pas de tableau
            self.assertTrue(p.evaluer("document.querySelector('#bComparer').disabled"), "rien de coché")
            p.evaluer("document.querySelector('#listeModeles .mod input[type=checkbox]').click()")
            self.assertFalse(p.evaluer("document.querySelector('#bComparer').disabled"))
            # le modèle de la démonstration a une mesure complète : le tableau apparaît avec sa ligne
            self.assertIn("jetons/s", p.evaluer("document.querySelector('#tableComparaison').textContent"))
            self.assertIn("Détail des questions", p.evaluer("document.querySelector('#tableComparaison details summary').textContent"))
            self.assertIn("3/4", p.evaluer("document.querySelector('#tableComparaison').textContent"), "la légende explique ce que veut dire 3/4")

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

    def test_reglages_moteur_et_memoire_des_longues_conversations_dans_l_onglet_memoire(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.attendre("document.querySelector('#pOllama').textContent.includes('Ollama prêt')")
            p.evaluer(onglet("reglages"))
            p.attendre("document.querySelectorAll('#listeMoteurs > .moteur-liste').length === 3")
            self.assertTrue(p.evaluer("document.querySelector('#listeMoteurs > .carte input[type=radio]').checked"), "Ollama est le moteur utilisé")
            noms = p.evaluer("[...document.querySelectorAll('#listeMoteurs > .carte > .ligne:first-child b')].map(b => b.textContent.trim()).join('|')")
            self.assertEqual(noms, "Ollama|llama.cpp|Serveur compatible OpenAI")
            self.assertIn("Forces et faiblesses", p.evaluer("document.querySelector('#listeMoteurs > .carte').textContent"))
            self.assertTrue(p.evaluer("[...document.querySelectorAll('#listeMoteurs > .carte')[1].querySelectorAll('button')].some(b => b.textContent === 'Installer')"), "llama.cpp peut être installé par Lutin : le bouton est là")
            self.assertTrue(p.evaluer("!!document.querySelectorAll('#listeMoteurs > .carte')[1].querySelector('input[data-dossier]')"), "llama.cpp montre son dossier d'installation, modifiable")
            self.assertTrue(p.evaluer("!!document.querySelector('#p-memoire #selMemoire')"), "la mémoire des longues conversations est dans l'onglet Mémoire")
            self.assertFalse(p.evaluer("!!document.querySelector('#p-reglages #selMemoire')"))
            self.assertEqual(p.erreurs, [])

    def test_changer_de_moteur_cache_ce_qui_n_existe_qu_avec_ollama(self):
        with self.captures.serveur_demo() as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.attendre("document.querySelector('#pOllama').textContent.includes('Ollama prêt')")
            p.evaluer(onglet("modeles"))
            self.assertTrue(p.evaluer("getComputedStyle(document.querySelector('#p-modeles .ollama-seulement')).display !== 'none'"), "avec Ollama, l'onglet Modèles est celui d'Ollama")
            p.evaluer(onglet("reglages"))
            p.attendre("document.querySelectorAll('#listeMoteurs > .moteur-liste').length === 3")
            p.evaluer("document.querySelectorAll('#listeMoteurs > .carte input[type=radio]')[1].click()")
            p.attendre("document.body.dataset.moteur === 'llamacpp'")
            p.attendre("document.querySelector('#pOllama').textContent.includes('llama.cpp')")
            p.evaluer(onglet("modeles"))
            p.attendre("document.querySelector('#modelesMoteur').textContent.includes('Hugging Face')")
            self.assertEqual(p.evaluer("getComputedStyle(document.querySelector('#p-modeles .ollama-seulement')).display"), "none", "le banc d'essai et la comparaison restent propres à Ollama")
            self.assertTrue(p.evaluer("getComputedStyle(document.querySelector('#p-modeles .biblio')).display !== 'none'"), "mais la page des modèles (catalogue, bibliothèque, sans filtre) est la même")
            self.assertTrue(p.evaluer("getComputedStyle(document.querySelector('#modelesMoteur')).display !== 'none'"))
            self.assertIn("Hugging Face", p.evaluer("document.querySelector('#modelesMoteur').textContent"), "llama.cpp se fournit en modèles GGUF sur Hugging Face")
            p.evaluer(onglet("reglages"))
            p.evaluer("document.querySelectorAll('#listeMoteurs > .carte input[type=radio]')[0].click()")
            p.attendre("document.body.dataset.moteur === 'ollama'")
            self.assertEqual(p.erreurs, [])

    def test_la_mise_en_page_suit_la_largeur_de_l_ecran_du_telephone_au_grand_ecran(self):
        """Sur un grand écran (2K) les pages de réglages et les bulles de conversation ne s'arrêtent plus à 900 px ; sur un téléphone rien ne déborde."""
        with self.captures.serveur_demo() as (port, tmp):
            largeurs = {}
            for nom, taille in (("grand", "2560,1300"), ("telephone", "390,800")):
                p = cdp.Page(self.chrome, tmp / ("profil-" + nom), taille=taille)
                self.addCleanup(p.fermer)
                p.aller("http://127.0.0.1:%d/#conv=a1b2c3d4" % port)
                p.attendre("!!document.querySelector('.conv.choisie') || !!document.querySelector('#bNouvelle')")
                p.attendre("document.querySelectorAll('.msg .corps').length > 0")
                bulle = p.evaluer("Math.max(...[...document.querySelectorAll('.msg .corps')].map(e => e.getBoundingClientRect().width))")
                p.evaluer("document.querySelector('.onglets button[data-p=reglages]').click()")
                p.attendre("document.querySelector('#p-reglages').classList.contains('vue')")
                cadre = p.evaluer("document.querySelector('#p-reglages .cadre').getBoundingClientRect().width")
                deborde = p.evaluer("document.documentElement.scrollWidth > window.innerWidth + 1")
                largeurs[nom] = (bulle, cadre, deborde, p.evaluer("window.innerWidth"))
            self.assertGreater(largeurs["grand"][1], 1400, "les réglages utilisent la largeur d'un grand écran")
            self.assertGreater(largeurs["grand"][0], 600, "les bulles ne sont pas écrasées")
            self.assertFalse(largeurs["telephone"][2], "sur un téléphone, la page ne déborde pas sur le côté")
            self.assertLessEqual(largeurs["telephone"][1], largeurs["telephone"][3], "les réglages tiennent dans la largeur du téléphone (Chrome ne descend pas sous ~500 px en test)")

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
