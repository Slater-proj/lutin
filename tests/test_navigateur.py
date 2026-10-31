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
            carte = "[...document.querySelectorAll('#listeAddons .carte')].find(c => c.textContent.includes('Traitement de documents') && c.querySelector('input[type=checkbox]'))"
            p.attendre("!!(" + carte + ")")
            self.assertEqual(p.evaluer("document.querySelectorAll('#listeAddons > .carte').length"), 6, "traitement de documents, missions, Telegram, ComfyUI, courriel, X")
            self.assertFalse(p.evaluer("(" + carte + ").querySelector('input[type=checkbox]').checked"), "désactivé par défaut")
            self.assertNotIn("Nouveau travail de fond", p.evaluer("document.getElementById('listeAddons').textContent"))
            p.evaluer("(" + carte + ").querySelector('input[type=checkbox]').click()")
            p.attendre("document.getElementById('listeAddons').textContent.includes('Nouveau travail de fond')")
            self.assertTrue(p.evaluer("(" + carte + ").querySelector('input[type=checkbox]').checked"))
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
            self.assertEqual(len(sauve["messages"]), 14, "en mode fiche rien n'est retiré de la conversation")
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
            (dossier / "addons.json").write_text(json.dumps({ident: {"actif": True} for ident in ("telegram", "mail", "x", "comfyui", "fond")}), encoding="utf-8")
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer(onglet("auto"))
            texte = "document.getElementById('listeAddons').textContent"
            p.attendre("%s.includes('Brouillon pour Bob') && %s.includes('Brouillon pour Alice') && %s.includes('Réponse à @alice') && %s.includes('Dossier de ComfyUI non défini')" % ((texte,) * 4))
            contenu = p.evaluer(texte)
            for attendu in ("/appairer 123456", "Devis", "✔ Publié", "Nouveau travail de fond", "Publier maintenant", "Publier la réponse"):
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
