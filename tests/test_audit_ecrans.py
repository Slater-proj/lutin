"""Audit des écrans dans un vrai Chrome : chaque page et chaque rubrique, dans les deux langues et avec chaque moteur.

Ce que ce test attrape et que les tests de logique ne voient pas :
- une page VIDE parce que ses cartes sont cachées par une règle de style (l'onglet Modèles de Colibri, LM Studio et ExLlamaV3 l'était) ;
- une erreur JavaScript levée en ouvrant une rubrique ;
- un débordement horizontal (une barre de défilement sous la page) ;
- du français resté dans l'interface anglaise.
Ignoré s'il n'y a pas de navigateur."""
import json
import re
import sys
import time
import unittest
from pathlib import Path

import context  # noqa: F401
import cdp

RACINE = Path(__file__).resolve().parent.parent
PAGES = ("chat", "modeles", "memoire", "reglages", "auto", "machines", "sante", "acces")
JETON = "document.documentElement.innerHTML.match(/TOKEN = '([0-9a-f]+)'/)[1]"
MOTS_FR = re.compile(r"\b(le|la|les|des|une|dans|pour|avec|sans|est|sont|ton|tes|choisis|ajoute|ouvre|tu|vous|cette|ces|pas|ici|rien|toutes|tous|lance|clique|coche)\b", re.I)
ACCENTS = re.compile(r"[éèêàâùûôîçœ]")
# Du français voulu en anglais : noms propres, exemples, mots que l'application garde tels quels
TOLERES = ("Lutin", "Ollama", "llama.cpp", "ExLlamaV3", "Colibri", "LM Studio")

MOTEURS = {
    "ollama": [],
    "llamacpp": [("/api/reglages", {"moteur": "llamacpp"})],
    "colibri": [("/api/reglages", {"moteur": "openai"}), ("/api/moteur-regler", {"moteur": "openai", "serveur": "colibri"})],
    "lmstudio": [("/api/reglages", {"moteur": "openai"}), ("/api/moteur-regler", {"moteur": "openai", "serveur": "lmstudio"})],
    "exllamav3": [("/api/reglages", {"moteur": "openai"}), ("/api/moteur-regler", {"moteur": "openai", "serveur": "exllamav3"})],
    "autre": [("/api/reglages", {"moteur": "openai"})],
}

TEXTE_VISIBLE = """(page => { const racine = document.getElementById(page) || document.body; const w = document.createTreeWalker(racine, NodeFilter.SHOW_TEXT), sortie = [];
  while (w.nextNode()) { const n = w.currentNode, p = n.parentElement; if (!p || /^(SCRIPT|STYLE|OPTION|TEXTAREA)$/.test(p.nodeName)) continue;
    const r = p.getBoundingClientRect(); if (!r.width || !r.height) continue; const t = n.nodeValue.trim().replace(/\\s+/g, ' '); if (t.length > 1) sortie.push(t); }
  return sortie; })"""


class Ecrans(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RACINE / "tools"))
        import captures
        cls.captures = captures
        try:
            cls.chrome = captures.navigateur()
        except SystemExit:
            raise unittest.SkipTest("aucun navigateur (Chrome, Chromium ou Edge) trouvé")

    def ouvrir(self, tmp, port, taille="1280,1500"):
        p = cdp.Page(self.chrome, tmp / "profil-audit", taille)
        self.addCleanup(p.fermer)
        p.aller("http://127.0.0.1:%d/" % port)
        p.attendre("!!document.querySelector('#bNouvelle')")
        p.evaluer("window.confirm = () => true")
        return p

    def regler(self, p, etapes):
        for url, corps in etapes:
            p.evaluer("(async () => (await fetch('%s', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Token': %s}, body: JSON.stringify(%s)})).json())()" % (url, JETON, json.dumps(corps)))

    def aller(self, p, page):
        p.evaluer("(() => { const b = document.querySelector('.onglets button[data-p=\"%s\"], #menuReglages button[data-p=\"%s\"]'); if (b) b.click(); })()" % (page, page))
        time.sleep(0.7)

    def rubriques(self, p, page):
        n = p.evaluer("document.querySelectorAll('#p-%s .sous-nav button').length" % page) or 0
        return n

    def verifier_ecran(self, p, page, contexte, minimum=40):
        textes = p.evaluer(TEXTE_VISIBLE + "('p-%s')" % page) or []
        self.assertGreater(sum(len(t) for t in textes), minimum, "%s : page vide (ses cartes sont peut-être cachées)" % contexte)
        largeur = p.evaluer("[document.documentElement.scrollWidth, window.innerWidth]")
        self.assertLessEqual(largeur[0], largeur[1] + 2, "%s : la page déborde à droite (%s)" % (contexte, largeur))
        self.assertEqual(p.erreurs, [], contexte)
        return textes

    def test_chaque_moteur_montre_ses_modeles_et_ses_reglages(self):
        """Quel que soit le moteur choisi, l'onglet Modèles et la rubrique Moteur ne sont JAMAIS vides."""
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            p = self.ouvrir(tmp, port)
            for nom, etapes in MOTEURS.items():
                self.regler(p, etapes)
                time.sleep(1.5)
                p.evaluer("location.reload()")
                p.attendre("!!document.querySelector('#bNouvelle')")
                time.sleep(2.5)                                                    # l'état du moteur arrive après le chargement de la page : c'est lui qui active ou désactive l'onglet Modèles
                if p.evaluer("document.querySelector('.onglets button[data-p=\"modeles\"]').disabled"):
                    # Moteur choisi mais pas prêt (llama.cpp ou serveur externe non installé/éteint) : l'onglet Modèles est désactivé avec sa raison, et une carte guide l'installation (premier lancement)
                    self.aller(p, "chat")
                    carte = p.evaluer("(() => { const c = document.getElementById('premierLancement'); return c.hidden ? '' : c.textContent; })()")
                    self.assertGreater(len(carte), 30, "moteur « %s » non prêt : la carte de premier lancement guide l'utilisateur" % nom)
                else:
                    self.aller(p, "modeles")
                    if nom in ("colibri", "lmstudio", "exllamav3"):
                        carte = {"colibri": "colibriModeles", "lmstudio": "lmstudioModeles", "exllamav3": "exllamav3Modeles"}[nom]
                        p.attendre("document.getElementById('%s').getBoundingClientRect().height > 30" % carte, delai=20)          # la carte se remplit à l'arrivée de l'état du serveur
                    textes = self.verifier_ecran(p, "modeles", "Modèles avec le moteur « %s »" % nom, 60)
                    if nom in ("colibri", "lmstudio", "exllamav3"):
                        self.assertTrue(any("installé" in t or "Modèles" in t for t in textes), "la carte du serveur géré est visible : " + nom)
                self.aller(p, "reglages")
                p.evaluer("document.querySelector('#sousReglages button[data-g=\"moteur\"]').click()")
                time.sleep(1.2)
                self.verifier_ecran(p, "reglages", "Réglages > Moteur avec « %s »" % nom, 100)

    def parcourir(self, langue, taille="1280,1500"):
        with self.captures.serveur_demo({"LUTIN_LANGUE": langue}) as (port, tmp):
            p = self.ouvrir(tmp, port, taille)
            suspects = {}
            for page in PAGES:
                self.aller(p, page)
                n = self.rubriques(p, page) or (6 if page == "reglages" else 0)
                for i in range(max(n, 1)):
                    if page == "reglages":
                        p.evaluer("document.querySelectorAll('#sousReglages button')[%d].click()" % i)
                    elif n:
                        p.evaluer("document.querySelectorAll('#p-%s .sous-nav button')[%d].click()" % (page, i))
                    time.sleep(0.9)
                    textes = self.verifier_ecran(p, page, "%s / page %s / rubrique %d" % (langue, page, i), 20)
                    if langue == "en":
                        for t in textes:
                            if any(m in t for m in TOLERES) and not MOTS_FR.search(t.replace("Lutin", "")):
                                continue
                            if ACCENTS.search(t) or len(MOTS_FR.findall(t)) >= 3:
                                suspects.setdefault(t[:110], "%s/%d" % (page, i))
            return suspects

    def test_toutes_les_pages_en_francais_sans_erreur(self):
        self.assertEqual(self.parcourir("fr"), {})

    def test_toutes_les_pages_en_anglais_sans_francais_ni_erreur(self):
        suspects = self.parcourir("en")
        self.assertEqual(suspects, {}, "du français resté dans l'interface anglaise")

    def test_toutes_les_pages_sur_un_telephone_sans_debordement(self):
        """Largeur d'un téléphone (400 px) : aucune page ne déborde à droite, aucune erreur."""
        self.assertEqual(self.parcourir("fr", "400,900"), {})


if __name__ == "__main__":
    unittest.main()
