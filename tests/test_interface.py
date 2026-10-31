"""La page web en français et en anglais : chaque texte est traduit, et la page se charge sans erreur dans un vrai navigateur (ignoré s'il n'y en a pas)."""
import html
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import context  # noqa: F401

RACINE = Path(__file__).resolve().parent.parent
PAGE = (RACINE / "src" / "lutin" / "web" / "index.html").read_text(encoding="utf-8")
DICO = json.loads((RACINE / "src" / "lutin" / "langues" / "interface.en.json").read_text(encoding="utf-8"))
FR = re.compile(r"[àâçéèêëîïôûùüÿœ]|\b(le|la|les|des|une|pas|pour|dans|avec|sur|ton|tes|est|du|au|aux|ce|cette|qui|que|vous|aucun|ouvre|choisis|lance|ou|et"
                r"|de|un|ajouter|chercher|nouveau|nouvelle|dossier|dossiers|travail|adresse|publique|retirer|supprimer|mettre|jour|fichier|fichiers|erreur|ouvrir|fermer|copier|lancer|arrêter|enregistrer|utiliser|démarrage)\b", re.I)
CLASSES = {"erreur", "mermaid-erreur", "texte", "travail", "travail fini", "nouveau", "supprimer", "btn-copier", "fichier", "resume", "resume|fichier", "demander", "resume|fichier|demander", "menu-ouvrir", "menu-conv", "menu-titre", "barre-disque", "legende-disque", "fichiers-joints", "carte-fichier", "tete-fichier", "nom-fichier", "/fichier/", "fichiers"}          # noms de classes CSS ou d'évènements, pas du texte
# Textes de la page identiques en français et en anglais (marques, réglages techniques, mots communs aux deux langues) : les seuls qui n'ont pas besoin de traduction
NEUTRES = {"Auto", "auto", "Conversation", "Documents", "English", "Français", "Langue / Language", "Maximum", "Mode", "Normal", "Ollama", "Skills", "Web", "min_p", "top_k", "top_p",
           "lutin modeles", "https://lutin.exemple.fr"}


def script():
    debut = PAGE.index("<script>\n(() => {")
    return PAGE[debut:PAGE.index("</script>", debut)]


def litteraux():
    """[(ligne, valeur brute, enveloppé dans T(...) ?)] pour les chaînes 'x' et "x" du script (ligne par ligne : une expression régulière ne gâte que sa ligne)."""
    sortie = []
    for numero, ligne in enumerate(script().split("\n"), 1):
        i, n = 0, len(ligne)
        while i < n:
            c = ligne[i]
            if c == "/" and ligne[i:i + 2] == "//" and (i == 0 or ligne[i - 1] in " \t;)}"):
                break
            if c in "'\"`":
                j = i + 1
                while j < n and ligne[j] != c:
                    j += 2 if ligne[j] == "\\" else 1
                if j >= n:
                    break
                sortie.append((numero, ligne[i + 1:j], ligne[:i].endswith("T(")))
                i = j + 1
            else:
                i += 1
    return sortie


def valeur(brut):
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), brut)


def normaliser(texte):
    return re.sub(r"\s+", " ", texte).strip()


def textes_html():
    """Les textes et attributs écrits directement dans la page (hors script et style)."""
    corps = re.sub(r"<script.*?</script>|<style.*?</style>", "", PAGE, flags=re.S)
    textes = [normaliser(html.unescape(t)) for t in re.findall(r">([^<>]+)<", corps)]
    attrs = [normaliser(html.unescape(a)) for a in re.findall(r'(?:title|placeholder|aria-label|alt)="([^"]+)"', corps)]
    return {t for t in textes + attrs if t}


class Traduction(unittest.TestCase):
    def test_tout_litteral_francais_du_script_passe_par_T(self):
        oublies = [(ligne, brut[:70]) for ligne, brut, enveloppe in litteraux()
                   if not enveloppe and FR.search(brut) and brut not in CLASSES and not brut.startswith(("/api/", "http"))]
        self.assertEqual(oublies, [], "texte français du script sans T(...) : il resterait en français dans l'interface anglaise")

    def test_chaque_T_a_sa_traduction(self):
        manquants = [(ligne, brut[:70]) for ligne, brut, enveloppe in litteraux() if enveloppe and valeur(brut) not in DICO]
        self.assertEqual(manquants, [], "T(...) sans traduction dans langues/interface.en.json")

    def test_chaque_texte_de_la_page_a_sa_traduction(self):
        # Tout texte qui contient des lettres a sa traduction, sauf la courte liste NEUTRES : la détection « ça ressemble à du français » laissait passer « Dossiers de travail », « Version de Lutin »…
        manquants = sorted(t for t in textes_html() if re.search(r"[A-Za-zÀ-ÿ]{2,}", t) and t not in {normaliser(k) for k in DICO} and t not in NEUTRES)
        self.assertEqual(manquants, [], "texte ou infobulle de la page sans traduction")

    def test_pas_de_traduction_orpheline(self):
        presents = textes_html() | {normaliser(valeur(brut)) for _, brut, _ in litteraux()}
        orphelines = [k for k in DICO if normaliser(k) not in presents]
        self.assertEqual(orphelines, [], "traduction d'un texte qui n'existe plus dans la page")

    def test_hygiene_du_dictionnaire(self):
        for fr, en in DICO.items():
            self.assertTrue(en.strip(), fr)
            self.assertEqual((len(fr) - len(fr.lstrip()), len(fr) - len(fr.rstrip())), (len(en) - len(en.lstrip()), len(en) - len(en.rstrip())), repr(fr))
            self.assertEqual(fr.count("\n"), en.count("\n"), repr(fr))

    def test_la_page_est_servie_avec_la_langue_et_le_dictionnaire(self):
        import os
        from unittest import mock
        from lutin import moteur
        with mock.patch.dict(os.environ, {"LUTIN_LANGUE": "en"}):
            page = moteur.page_web()
        self.assertIn("const LANGUE = 'en', DICO = {", page)
        self.assertIn('<html lang="en">', page)
        self.assertNotIn("__DICO__", page)
        self.assertNotIn("__LANGUE__", page)
        with mock.patch.dict(os.environ, {"LUTIN_LANGUE": "fr"}):
            page = moteur.page_web()
        self.assertIn("const LANGUE = 'fr', DICO = {};", page)
        self.assertNotIn("</script><", page.replace("</script>\n", ""), "le dictionnaire ne doit pas pouvoir fermer la balise script")


def sections(dom, *ids):
    sortie = []
    for i in ids:
        m = re.search(r'<section class="page[^"]*" id="{}".*?</section>'.format(i), dom, flags=re.S)          # la page affichée a une classe en plus : on la trouve aussi
        assert m, "section {} introuvable dans la page".format(i)                                               # avant, une section introuvable donnait un texte vide : le test passait sans rien vérifier
        sortie.append(m.group(0))
    return "".join(sortie)


class DansUnNavigateur(unittest.TestCase):
    """Un vrai serveur et un vrai Chrome : la page charge sans erreur en français comme en anglais, et l'anglais ne laisse pas de français dans les écrans fixes."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RACINE / "tools"))
        import captures
        cls.captures = captures
        try:
            cls.chrome = captures.navigateur()
        except SystemExit:
            raise unittest.SkipTest("aucun navigateur (Chrome, Chromium ou Edge) trouvé")

    def charger(self, langue, ancre, niveau="local"):
        with self.captures.serveur_demo({"LUTIN_LANGUE": langue}, niveau) as (port, tmp):
            r = subprocess.run([self.chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--user-data-dir=" + str(tmp / "profil"), "--virtual-time-budget=8000", "--enable-logging=stderr",
                                "--v=0", "--dump-dom", "http://127.0.0.1:%d/%s" % (port, ancre)], capture_output=True, timeout=180, encoding="utf-8", errors="replace")
        erreurs = [l for l in r.stderr.splitlines() if "CONSOLE" in l and ("rror" in l or "Uncaught" in l)]
        return r.stdout, erreurs

    def test_francais_sans_erreur(self):
        dom, erreurs = self.charger("fr", "#reglages")
        self.assertEqual(erreurs, [])
        self.assertIn("Fenêtre de contexte", dom)
        self.assertIn('<html lang="fr">', dom)

    def test_anglais_sans_erreur_et_sans_francais_dans_les_ecrans_fixes(self):
        dom, erreurs = self.charger("en", "#reglages")
        self.assertEqual(erreurs, [], "erreur JavaScript dans la page anglaise")
        self.assertIn('<html lang="en">', dom)
        ecrans = sections(dom, "p-modeles", "p-memoire", "p-reglages", "p-sante") + "".join(re.findall(r'<nav.*?</nav>|<header.*?</header>', dom, flags=re.S))
        ecrans = re.sub(r"<script.*?</script>|<style.*?</style>", "", ecrans, flags=re.S)
        textes = [html.unescape(t).strip() for t in re.findall(r">([^<>]+)<", ecrans)] + [html.unescape(a) for a in re.findall(r'(?:title|placeholder|aria-label)="([^"]+)"', ecrans)]
        restes = sorted({t for t in textes if t and FR.search(t) and t not in ("Français", "Langue / Language")})
        self.assertEqual(restes, [], "du français reste dans l'interface anglaise")
        self.assertIn("Context window", dom)
        self.assertNotIn("Fenêtre de contexte", sections(dom, "p-reglages"))

    def test_barre_laterale_epuree_et_reglages_complets_en_francais(self):
        dom, erreurs = self.charger("fr", "#reglages")
        self.assertEqual(erreurs, [])
        self.assertNotIn('id="selTravail"', dom, "le choix du dossier de travail est dans les réglages, plus dans la barre latérale")
        self.assertNotIn("bTravailPlus", dom, "plus de « + » dans les options")
        reglages = sections(dom, "p-reglages")
        self.assertRegex(reglages, r'Langue / Language</h2>\s*<div style="margin:6px 0"><label><select id="selLangue"', "la langue n'a qu'un cadre (celui de la liste), pas un cadre dans un cadre")
        self.assertNotRegex(reglages, r'class="carte"><label><select id="selLangue"')
        self.assertIn("Version de Lutin", reglages)
        self.assertRegex(reglages, r'id="vVersionActuelle">Lutin \S+', "la version est affichée")
        self.assertIn("Vérifier les mises à jour", reglages)
        self.assertIn("Dossiers de travail", reglages)
        self.assertIn("Ajouter un dossier", reglages)

    def test_acces_au_niveau_local_explique_au_lieu_de_montrer_un_qr_inutile(self):
        dom, erreurs = self.charger("fr", "#acces")
        self.assertEqual(erreurs, [])
        acces = sections(dom, "p-acces")
        self.assertIn('id="blocPin" hidden', acces)
        self.assertIn("choisis d'abord", acces, "dit quoi faire pour connecter un téléphone")

    def test_dossiers_de_travail_se_choisissent_dans_les_reglages(self):
        dom, erreurs = self.charger("fr", "#reglages")
        self.assertEqual(erreurs, [])
        reglages = sections(dom, "p-reglages")
        self.assertIn("Utiliser ce dossier", reglages, "le dossier non actif a son bouton")
        self.assertIn("Retirer", reglages)
        self.assertIn("★ Projet", reglages, "le dossier utilisé est marqué")

    def test_reglages_complets_en_anglais(self):
        dom, erreurs = self.charger("en", "#reglages")
        self.assertEqual(erreurs, [])
        reglages = sections(dom, "p-reglages")
        for texte in ("Lutin version", "Check for updates", "Workspace folders", "Add a folder"):
            self.assertIn(texte, reglages)
        for francais in ("Version de Lutin", "Dossiers de travail", "Ajouter un dossier", "Vérifier les mises à jour"):
            self.assertNotIn(francais, reglages, "du français dans la page anglaise")
        self.assertRegex(reglages, r'id="vVersionActuelle">Lutin \S+')


if __name__ == "__main__":
    unittest.main()
