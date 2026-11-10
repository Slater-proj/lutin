"""La gestion des moteurs dans un vrai Chrome : les mêmes lignes de dossiers pour chaque moteur, la liste des serveurs qui redessine la carte, et la page Modèles d'ExLlamaV3 (mes modèles,
mises à jour, nouveautés, exploration, quantifications) avec un faux Hugging Face. Ignoré s'il n'y a pas de navigateur."""
import json
import os
import sys
import time
import unittest
from pathlib import Path

import context  # noqa: F401
import cdp

RACINE = Path(__file__).resolve().parent.parent
JETON = "document.documentElement.innerHTML.match(/TOKEN = '([0-9a-f]+)'/)[1]"
SHA = "a" * 40


def post(p, url, corps):
    return p.evaluer("(async () => (await fetch('%s', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Token': %s}, body: JSON.stringify(%s)})).json())()" % (url, JETON, json.dumps(corps)))


def installer_exllamav3_pour_de_faux(tmp):
    """Les fichiers qu'une installation d'ExLlamaV3 laisse (TabbyAPI, environnement Python, version) et un modèle téléchargé par Lutin : de quoi voir la page « installé » sans installer plusieurs Go."""
    base = tmp / "home" / "donnees" / "engines" / "exllamav3"
    (base / "tabby").mkdir(parents=True)
    (base / "tabby" / "main.py").write_text("print('tabby')\n", encoding="utf-8")
    py = base / "venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    (base / "version.json").write_text(json.dumps({"tabby": SHA, "lib": "1.6.6"}), encoding="utf-8")
    modele = base / "modeles" / "Qwen3-8B-exl3_4.0bpw"
    modele.mkdir(parents=True)
    (modele / "config.json").write_text("{}", encoding="utf-8")
    (modele / "model.safetensors").write_bytes(b"x" * 3_000_000)
    (modele / ".lutin.json").write_text(json.dumps({"depot": "turboderp/Qwen3-8B-exl3", "revision": "4.0bpw", "commit": SHA}), encoding="utf-8")


# Un faux Hugging Face côté page : les réponses des routes qui sortiraient sur internet, et la trace de ce que la page envoie
FAUX_RESEAU = """(() => {
  window.__envoyes = []; const f0 = window.fetch.bind(window);
  const rep = (corps, statut) => Promise.resolve(new Response(JSON.stringify(corps), { status: statut || 200, headers: { 'Content-Type': 'application/json' } }));
  window.fetch = (u, o) => {
    const url = String(u);
    if (o && o.method === 'POST') window.__envoyes.push([url, o.body]);
    if (url.startsWith('/api/exllamav3-catalogue')) return rep({ suite: true, modeles: [
      { id: 'turboderp/Qwen3-8B-exl3', nom: 'Qwen3-8B-exl3', auteur: 'turboderp', telechargements: 5200, aime: 40, maj: '2026-11-06', capacites: ['vision'], licence: 'apache-2.0', base: 'Qwen/Qwen3-8B', estimation_go: 5.2, adequation: { niveau: 'bien', texte: 'Convient' }, installes: ['4.0bpw'] },
      { id: 'turboderp/Enorme-400B-exl3', nom: 'Enorme-400B-exl3', auteur: 'turboderp', telechargements: 12, aime: 1, maj: '2026-11-01', capacites: [], licence: '', base: '', estimation_go: 220, adequation: { niveau: 'trop_gros', texte: 'Trop gros' }, installes: [] },
      { id: 'turboderp/Sans-taille-exl3', nom: 'Sans-taille-exl3', auteur: 'turboderp', telechargements: 3, aime: 0, maj: '2026-10-01', capacites: [], licence: '', base: '', estimation_go: null, adequation: null, installes: [] }] });
    if (url.startsWith('/api/exllamav3-quantifications')) return rep({ quantifications: [
      { revision: '4.0bpw', bpw: 4, go: 5.2, commit: 'a', adequation: { niveau: 'bien', texte: 'ok' }, installe: true },
      { revision: '6.0bpw', bpw: 6, go: 6.9, commit: 'b', adequation: { niveau: 'limite', texte: 'juste' }, installe: false }] });
    if (url === '/api/exllamav3-verifier') {
      const portee = JSON.parse(o.body).portee;
      return rep(portee === 'maj' ? { plus_recentes: [{ nom: 'Qwen3-8B-exl3_4.0bpw', depot: 'turboderp/Qwen3-8B-exl3', revision: '4.0bpw' }], erreurs: [] }
        : { propositions: [{ id: 'turboderp/Nouveau-7B-exl3', nom: 'Nouveau-7B-exl3', auteur: 'turboderp', telechargements: 9, aime: 2, maj: '2026-11-09', capacites: [], licence: '', base: '', estimation_go: 5.5, adequation: { niveau: 'ideal', texte: 'a l\\'aise' }, installes: [] }] });
    }
    if (url === '/api/exllamav3-telecharger') return rep({ tache: 'ok' });
    return f0(u, o);
  };
  return true; })()"""


class Moteurs(unittest.TestCase):
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
        p = cdp.Page(self.chrome, tmp / "profil-moteurs", "1280,1500")
        self.addCleanup(p.fermer)
        p.aller("http://127.0.0.1:%d/" % port)
        p.attendre("!!document.querySelector('#bNouvelle')")
        p.evaluer("window.confirm = () => true")
        return p

    def moteur_exllamav3(self, p):
        post(p, "/api/reglages", {"moteur": "openai"})
        post(p, "/api/moteur-regler", {"moteur": "openai", "serveur": "exllamav3"})
        time.sleep(1.2)
        p.evaluer("location.reload()")
        p.attendre("!!document.querySelector('#bNouvelle')")
        time.sleep(2.5)

    def page_moteur(self, p):
        p.evaluer("document.querySelector('.onglets button[data-p=\"reglages\"], #menuReglages button[data-p=\"reglages\"]').click()")
        p.evaluer("document.querySelector('#sousReglages button[data-g=\"moteur\"]').click()")
        p.attendre("document.querySelectorAll('#listeMoteurs .moteur-liste').length >= 3", delai=30)

    CARTE = "[...document.querySelectorAll('#listeMoteurs .moteur-liste')].find(c => c.querySelector('b').textContent.trim() === %s)"

    def test_chaque_moteur_dit_ou_il_est_installe_et_ou_sont_ses_modeles_de_la_meme_facon(self):
        """Ollama, llama.cpp et le serveur géré (ici ExLlamaV3) : « Dossier d'installation » puis « Dossier des modèles », jamais un champ d'installation propre à un seul moteur ; le choix du dossier d'installation est dans « Dossier des moteurs »."""
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            installer_exllamav3_pour_de_faux(tmp)
            p = self.ouvrir(tmp, port)
            self.moteur_exllamav3(p)
            self.page_moteur(p)
            self.assertIn("Dossier des moteurs", p.evaluer("document.getElementById('dossierMoteurs').textContent"))
            self.assertIn("seul endroit", p.evaluer("document.getElementById('dossierMoteurs').textContent"))
            for nom in ("Ollama", "llama.cpp", "Serveur compatible OpenAI"):
                texte = p.evaluer("(%s).textContent" % (self.CARTE % json.dumps(nom)))
                self.assertIn("Dossier d'installation", texte, nom)
                self.assertIn("Dossier des modèles", texte, nom)
                self.assertLess(texte.index("Dossier d'installation"), texte.index("Dossier des modèles"), nom)
                self.assertNotIn("Utiliser le dossier proposé", texte, nom)
                self.assertEqual(p.evaluer("(%s).querySelectorAll('input[data-dossier]').length" % (self.CARTE % json.dumps(nom))), 0, nom + " : l'installation n'a plus de champ à elle")
            exl = p.evaluer("(%s).textContent" % (self.CARTE % json.dumps("Serveur compatible OpenAI")))
            self.assertIn("exllamav3", exl)
            self.assertIn("Changer de dossier", exl, "le dossier des modèles d'ExLlamaV3 se change comme celui de llama.cpp")
            self.assertEqual(p.erreurs, [])

    def test_le_dossier_des_modeles_d_exllamav3_se_change_depuis_la_carte(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            installer_exllamav3_pour_de_faux(tmp)
            p = self.ouvrir(tmp, port)
            self.moteur_exllamav3(p)
            self.page_moteur(p)
            ailleurs = str(tmp / "autre-disque")
            carte = self.CARTE % json.dumps("Serveur compatible OpenAI")
            champ = "(%s).querySelector('input[title^=\"Un chemin complet ; vide\"]')" % carte
            p.evaluer("(() => { const c = %s; c.value = %s; return true; })()" % (champ, json.dumps(ailleurs)))
            p.evaluer("[...(%s).querySelectorAll('button')].find(b => b.textContent === 'Changer de dossier').click()" % carte)
            p.attendre("(%s).textContent.includes(%s)" % (carte, json.dumps("Dossier des modèles : " + ailleurs)), delai=20)
            self.assertEqual(p.erreurs, [])

    def test_changer_de_serveur_dans_la_liste_redessine_la_carte_aussitot(self):
        """Le bug : la liste déroulante gardait le focus, la carte n'était pas redessinée et montrait toujours les boutons d'ExLlamaV3 sous « Colibri »."""
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            installer_exllamav3_pour_de_faux(tmp)
            p = self.ouvrir(tmp, port)
            self.moteur_exllamav3(p)
            self.page_moteur(p)
            carte = self.CARTE % json.dumps("Serveur compatible OpenAI")
            p.attendre("(%s).textContent.includes('Désinstaller')" % carte)
            self.assertIn("ExLlamaV3", p.evaluer("(%s).textContent" % carte))
            p.evaluer("(() => { const s = (%s).querySelector('select'); s.focus(); s.value = 'colibri'; s.dispatchEvent(new Event('change', { bubbles: true })); return document.activeElement === s; })()" % carte)
            p.attendre("!(%s).textContent.includes('Désinstaller') && (%s).textContent.includes('Colibri')" % (carte, carte), delai=20)
            texte = p.evaluer("(%s).textContent" % carte)
            self.assertNotIn("TabbyAPI", texte, "l'explication d'ExLlamaV3 a disparu")
            self.assertTrue(p.evaluer("[...(%s).querySelectorAll('button')].some(b => b.textContent === 'Installer')" % carte), "Colibri n'est pas installé : on propose de l'installer")
            self.assertEqual(p.evaluer("(%s).querySelector('select').value" % carte), "colibri")
            self.assertEqual(p.erreurs, [])

    def test_la_page_modeles_d_exllamav3_propose_les_memes_choses_qu_ollama(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            installer_exllamav3_pour_de_faux(tmp)
            p = self.ouvrir(tmp, port)
            self.moteur_exllamav3(p)
            p.evaluer(FAUX_RESEAU)
            p.evaluer("document.querySelector('.onglets button[data-p=\"modeles\"]').click()")
            zone = "document.getElementById('exllamav3Modeles')"
            p.attendre("%s.textContent.includes('Mes modèles') && %s.querySelectorAll('.mod').length >= 1" % (zone, zone), delai=30)
            texte = p.evaluer(zone + ".textContent")
            for attendu in ("Chercher les mises à jour", "Chercher de nouveaux modèles", "Mes modèles", "Qwen3-8B-exl3_4.0bpw", "turboderp/Qwen3-8B-exl3 @ 4.0bpw", "Explorer les modèles EXL3", "Un autre modèle EXL3"):
                self.assertIn(attendu, texte)
            self.assertTrue(p.evaluer("[...%s.querySelectorAll('.mod button')].some(b => b.textContent === 'Supprimer')" % zone), "supprimer un modèle")
            # explorer : un clic sur « Parcourir » liste le catalogue, les trop gros sont cachés par défaut
            p.evaluer("[...%s.querySelectorAll('button')].find(b => b.textContent === 'Parcourir').click()" % zone)
            p.attendre("%s.querySelectorAll('#exl3Explorer .carte[data-nom]').length >= 1" % zone, delai=20)
            cartes = p.evaluer("[...%s.querySelectorAll('#exl3Explorer .carte[data-nom]')].map(c => c.dataset.nom)" % zone)
            self.assertEqual(cartes, ["turboderp/Qwen3-8B-exl3", "turboderp/Sans-taille-exl3"], "le modèle trop gros pour la machine est masqué")
            self.assertIn("masqué", p.evaluer(zone + ".querySelector('#exl3Explorer').textContent"))
            self.assertIn("✔ installé : 4.0bpw", p.evaluer(zone + ".querySelector('#exl3Explorer .carte[data-nom]').textContent"))
            self.assertFalse(p.evaluer("%s.querySelector('#exl3Explorer a[href*=\"huggingface.co/turboderp/Qwen3-8B-exl3\"]') === null" % zone), "un lien vers la page du modèle")
            p.evaluer("%s.querySelector('#exl3Explorer input[type=checkbox]').click()" % zone)          # tout montrer
            p.attendre("%s.querySelectorAll('#exl3Explorer .carte[data-nom]').length === 3" % zone, delai=20)
            # une quantification : la liste, puis l'installation de celle qui manque
            p.evaluer("%s.querySelector('#exl3Explorer .carte[data-nom]').querySelector('button').click()" % zone)
            p.attendre("%s.querySelectorAll('#exl3Explorer .carte[data-nom] .mod').length === 2" % zone, delai=20)
            quants = p.evaluer("%s.querySelector('#exl3Explorer .carte[data-nom]').textContent" % zone)
            self.assertIn("6,9 Go", quants)
            self.assertIn("Limite", quants)
            p.evaluer("[...%s.querySelectorAll('#exl3Explorer .carte[data-nom] .mod button')].find(b => b.textContent === 'Installer').click()" % zone)
            p.attendre("window.__envoyes.some(e => e[0] === '/api/exllamav3-telecharger')")
            self.assertEqual(json.loads(p.evaluer("window.__envoyes.filter(e => e[0] === '/api/exllamav3-telecharger')[0][1]")), {"depot": "turboderp/Qwen3-8B-exl3", "revision": "6.0bpw"})
            self.assertEqual(p.erreurs, [])

    def test_chercher_les_mises_a_jour_et_les_nouveautes(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            installer_exllamav3_pour_de_faux(tmp)
            p = self.ouvrir(tmp, port)
            self.moteur_exllamav3(p)
            p.evaluer(FAUX_RESEAU)
            p.evaluer("document.querySelector('.onglets button[data-p=\"modeles\"]').click()")
            zone = "document.getElementById('exllamav3Modeles')"
            p.attendre("%s.querySelectorAll('.mod').length >= 1" % zone, delai=30)
            p.evaluer("[...%s.querySelectorAll('button')].find(b => b.textContent.includes('Chercher les mises à jour')).click()" % zone)
            p.attendre("%s.textContent.includes('Mise à jour : Qwen3-8B-exl3_4.0bpw')" % zone, delai=20)
            p.evaluer("[...%s.querySelectorAll('button')].find(b => b.textContent === 'Mettre à jour').click()" % zone)
            p.attendre("window.__envoyes.some(e => e[0] === '/api/exllamav3-telecharger')")
            self.assertEqual(json.loads(p.evaluer("window.__envoyes.filter(e => e[0] === '/api/exllamav3-telecharger')[0][1]")), {"depot": "turboderp/Qwen3-8B-exl3", "revision": "4.0bpw"})
            p.evaluer("[...%s.querySelectorAll('button')].find(b => b.textContent.includes('Chercher de nouveaux modèles')).click()" % zone)
            p.attendre("%s.textContent.includes('Nouveautés pour ta machine') && %s.textContent.includes('Nouveau-7B-exl3')" % (zone, zone), delai=20)
            self.assertFalse(p.evaluer("%s.textContent.includes('Mise à jour : Qwen3')" % zone), "les nouveautés remplacent les mises à jour affichées")
            self.assertEqual(p.erreurs, [])

    def test_exllamav3_pas_installe_propose_de_l_installer_sans_explorateur(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            p = self.ouvrir(tmp, port)
            self.moteur_exllamav3(p)
            p.evaluer("document.querySelector('.onglets button[data-p=\"modeles\"]').click()")
            zone = "document.getElementById('exllamav3Modeles')"
            p.attendre("%s.textContent.includes('pas encore installé')" % zone, delai=30)
            self.assertTrue(p.evaluer("[...%s.querySelectorAll('button')].some(b => b.textContent === 'Installer ExLlamaV3')" % zone))
            self.assertFalse(p.evaluer("%s.textContent.includes('Explorer les modèles')" % zone), "rien à explorer avant l'installation")
            self.assertEqual(p.erreurs, [])


if __name__ == "__main__":
    unittest.main()
