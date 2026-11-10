"""La conversation et les tâches planifiées dans un vrai Chrome : la réflexion repliable au-dessus de la réponse (jamais dans la bulle), l'horodatage sous chaque message, la flèche « revenir en bas »
visible dès qu'on remonte (même sans réponse en cours), et le cycle de vie d'une tâche planifiée (créer, modifier, supprimer pour de bon). Ignoré s'il n'y a pas de navigateur."""
import json
import sys
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import context  # noqa: F401
import cdp

RACINE = Path(__file__).resolve().parent.parent
JETON = "document.documentElement.innerHTML.match(/TOKEN = '([0-9a-f]+)'/)[1]"


def api(p, url, corps=None):
    if corps is None:
        return p.evaluer("(async () => (await fetch('%s', {headers: {'X-Token': %s}})).json())()" % (url, JETON))
    return p.evaluer("(async () => (await fetch('%s', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Token': %s}, body: JSON.stringify(%s)})).json())()" % (url, JETON, json.dumps(corps)))


class Conversation(unittest.TestCase):
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
        p = cdp.Page(self.chrome, tmp / "profil-conv", "1100,800")
        self.addCleanup(p.fermer)
        p.aller(adresse)
        p.attendre("!!document.querySelector('#bNouvelle')")
        p.evaluer("window.confirm = () => true; window.alert = () => {}")
        return p

    def conversation_longue(self, tmp):
        """La conversation d'exemple + une longue suite de messages : une réflexion enregistrée à part, une ancienne réponse qui contient encore <think>, des messages datés."""
        chemin = tmp / "home" / "donnees" / "conversations" / "a1b2c3d4.json"
        c = json.loads(chemin.read_text(encoding="utf-8"))
        hier = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        c["messages"][0]["ts"] = hier
        c["messages"][-1]["ts"] = datetime.now().isoformat(timespec="seconds")
        for i in range(30):
            c["messages"] += [{"role": "user", "content": "Question numéro %d, assez longue pour prendre de la place dans le fil de la conversation." % i, "ts": hier},
                              {"role": "assistant", "content": "Réponse numéro %d.\n\n" % i + "Un paragraphe de réponse. " * 20, "ts": hier}]
        c["messages"] += [{"role": "user", "content": "Et la dernière ?", "ts": datetime.now().isoformat(timespec="seconds")},
                          {"role": "assistant", "content": "Voilà la dernière réponse.", "reflexion": "Je regarde le fichier puis je réponds.", "ts": datetime.now().isoformat(timespec="seconds")},
                          {"role": "user", "content": "Lis le readme puis résume-le.", "ts": datetime.now().isoformat(timespec="seconds")},
                          {"role": "assistant", "content": "Je commence par lire le fichier.", "tool_calls": [{"function": {"name": "lire", "arguments": {"chemin": "README.md"}}}], "reflexion": "Il me faut le contenu avant de résumer."},
                          {"role": "tool", "tool_name": "lire", "content": "# Mon projet\nUn assistant local."},
                          {"role": "assistant", "content": "Le readme présente un assistant local.", "ts": datetime.now().isoformat(timespec="seconds")},
                          {"role": "user", "content": "Une ancienne conversation ?"},
                          {"role": "assistant", "content": "<think>Ancienne réflexion restée dans le texte.</think>\n\nVoici l'ancienne réponse, propre."}]
        chemin.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")

    def test_la_reflexion_est_repliee_hors_de_la_bulle_et_les_messages_sont_dates(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            self.conversation_longue(tmp)
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/#conv=a1b2c3d4" % port)
            p.attendre("document.querySelectorAll('#fil .msg.ia').length >= 20", delai=30)
            blocs = p.evaluer("[...document.querySelectorAll('#fil details.pensee')].filter(d => !d.closest('details.etapes')).map(d => [d.open, d.querySelector('summary').textContent, d.querySelector('pre').textContent, !!d.closest('.corps')])")
            self.assertEqual([b[2] for b in blocs], ["Je regarde le fichier puis je réponds.", "Ancienne réflexion restée dans le texte."])
            self.assertTrue(all(not b[0] and b[1] == "Réflexion" and not b[3] for b in blocs), "repliées, titrées « Réflexion », et dans la colonne, pas dans la bulle de réponse")
            self.assertEqual(p.evaluer("[...document.querySelectorAll('#fil .corps')].filter(c => c.textContent.includes('<think>') || c.textContent.includes('Ancienne réflexion')).length"), 0)
            self.assertTrue(p.evaluer("[...document.querySelectorAll('#fil .corps')].some(c => c.textContent.includes('Voici l\\'ancienne réponse, propre.'))"))
            dates = p.evaluer("[...document.querySelectorAll('#fil .actions .horodatage')].map(s => [s.textContent, s.title])")
            self.assertGreaterEqual(len(dates), 60, "chaque message daté montre sa date à côté de ses boutons")
            self.assertTrue(any(":" in d[0] and "/" not in d[0] for d in dates), "aujourd'hui : l'heure seule")
            self.assertTrue(any("/" in d[0] for d in dates), "un autre jour : la date et l'heure")
            self.assertTrue(all(str(datetime.now().year) in d[1] for d in dates), "l'infobulle donne la date complète")
            self.assertEqual(p.evaluer("document.querySelectorAll('#fil .msg.moi:nth-last-child(n+1) .actions').length > 0"), True)
            self.assertEqual(p.erreurs, [])

    def test_le_travail_de_l_assistant_est_range_a_part_de_sa_reponse(self):
        """Réflexions, notes entre deux outils, appels d'outils et résultats : dans un bloc repliable ; la bulle ne contient que la réponse finale."""
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            self.conversation_longue(tmp)
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/#conv=a1b2c3d4" % port)
            p.attendre("document.querySelectorAll('#fil .msg.ia').length >= 20", delai=30)
            self.assertEqual(p.evaluer("document.querySelectorAll('#fil > .outil').length"), 0, "plus d'appel d'outil en vrac dans le fil")
            groupes = p.evaluer("[...document.querySelectorAll('#fil details.etapes')].map(g => [g.open, g.querySelector('summary').textContent, g.querySelectorAll('.outil').length, g.querySelectorAll('.note-etape').length, g.textContent])")
            self.assertGreaterEqual(len(groupes), 2, "le tour de la démonstration et celui du readme")
            self.assertTrue(all(not g[0] for g in groupes), "repliés : on lit d'abord la réponse")
            readme = next(g for g in groupes if "Je commence par lire le fichier." in g[4])
            self.assertEqual(readme[3], 1, "le texte écrit avant l'outil est une note de travail")
            self.assertIn("Il me faut le contenu avant de résumer.", readme[4], "la réflexion est une étape")
            self.assertIn("1 étape", readme[1])
            self.assertTrue(readme[1].startswith("⚙"))
            self.assertTrue(p.evaluer("[...document.querySelectorAll('#fil details.etapes details.pensee')].some(d => d.textContent.includes('Il me faut le contenu'))"), "la réflexion de ce tour est dans les étapes")
            bulles = p.evaluer("[...document.querySelectorAll('#fil .msg.ia .corps')].map(c => c.textContent)")
            self.assertTrue(any("Le readme présente un assistant local." in b for b in bulles))
            self.assertFalse(any("Je commence par lire le fichier." in b for b in bulles), "la note n'est pas une réponse")
            # une réponse finale par bulle : les boutons et la date n'y sont qu'une fois, sur la bonne
            dates = p.evaluer("[...document.querySelectorAll('#fil .msg.ia .horodatage')].length")
            self.assertEqual(p.evaluer("document.querySelectorAll('#fil .msg.ia .actions').length"), p.evaluer("[...document.querySelectorAll('#fil .msg.ia')].filter(m => m.querySelector('.corps')._brut).length"), "chaque bulle finale a sa barre d'actions, et seulement elles")
            self.assertGreater(dates, 30)
            p.evaluer("document.querySelector('#fil details.etapes summary').click()")
            self.assertTrue(p.evaluer("document.querySelector('#fil details.etapes').open"), "un clic déroule les étapes")
            self.assertEqual(p.erreurs, [])

    def test_en_direct_les_notes_et_les_outils_vont_dans_les_etapes_et_la_reponse_reste_seule(self):
        flux = """(() => { const f0 = window.fetch.bind(window);
          const evts = [{ type: 'debut', conversation: 'a1b2c3d4' }, { type: 'pensee', texte: 'Je dois lire le fichier.' }, { type: 'texte', texte: 'Je lis le fichier.' },
            { type: 'outil', nom: 'lire', args: { chemin: 'README.md' } }, { type: 'resultat', texte: '# Mon projet' }, { type: 'texte', texte: 'Voici ' }, { type: 'texte', texte: 'la réponse finale.' },
            { type: 'fin', conversation: { id: 'a1b2c3d4', titre: 'Démo' } }];
          window.fetch = (u, o) => { if (String(u) !== '/api/chat') return f0(u, o);
            const enc = new TextEncoder(); let i = 0;
            return Promise.resolve(new Response(new ReadableStream({ pull(c) { if (i < evts.length) { c.enqueue(enc.encode(JSON.stringify(evts[i++]) + '\\n')); return new Promise(r => setTimeout(r, 150)); } c.close(); } }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } })); };
          return true; })()"""
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/#conv=a1b2c3d4" % port)
            p.attendre("document.querySelectorAll('#fil .msg.ia').length >= 1", delai=30)
            p.evaluer(flux)
            p.evaluer("(() => { const s = document.getElementById('saisie'); s.value = 'lis le readme'; document.getElementById('bEnvoyer').click(); return true; })()")
            p.attendre("[...document.querySelectorAll('#fil .msg.ia .corps')].some(c => c.textContent.includes('Voici la réponse finale.'))", delai=30)
            p.attendre("!document.getElementById('bStop') || document.getElementById('bStop').hidden", delai=30)
            groupe = p.evaluer("(() => { const gs = [...document.querySelectorAll('#fil details.etapes')], g = gs[gs.length - 1]; return g ? [g.open, g.querySelector('summary').textContent, g.querySelectorAll('.note-etape').length, g.querySelectorAll('.outil').length, g.querySelector('.note-etape') && g.querySelector('.note-etape').textContent.trim(), g.textContent.includes('Je dois lire le fichier.'), g.textContent.includes('# Mon projet')] : null; })()")
            self.assertEqual(groupe[0], False, "le travail se replie quand la réponse est là")
            self.assertEqual(groupe[2:], [1, 1, "Je lis le fichier.", True, True], groupe)
            self.assertIn("1 étape", groupe[1])
            derniere = p.evaluer("(() => { const b = [...document.querySelectorAll('#fil .msg.ia')].filter(m => !m.hidden), x = b[b.length - 1]; return [x.querySelector('.corps').textContent.trim(), [...document.querySelectorAll('#fil .msg.ia')].filter(m => !m.hidden && !m.querySelector('.corps').textContent.trim()).length]; })()")
            self.assertEqual(derniere[0], "Voici la réponse finale.", "la bulle ne contient que la réponse, sans la note ni la réflexion")
            self.assertEqual(derniere[1], 0, "aucune bulle vide")
            self.assertEqual(p.erreurs, [])

    def test_la_fleche_pour_revenir_en_bas_apparait_des_qu_on_remonte_meme_sans_reponse_en_cours(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            self.conversation_longue(tmp)
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/#conv=a1b2c3d4" % port)
            p.attendre("document.querySelectorAll('#fil .msg.ia').length >= 20", delai=30)
            time.sleep(0.5)
            self.assertTrue(p.evaluer("document.getElementById('bBas').hidden"), "en bas de la conversation : pas de flèche")
            p.evaluer("(() => { const f = document.getElementById('fil'); f.scrollTop = 0; f.dispatchEvent(new Event('scroll')); return true; })()")
            self.assertFalse(p.evaluer("document.getElementById('bBas').hidden"), "dès qu'on remonte, même quand rien n'est en train de s'écrire")
            taille = p.evaluer("(() => { const r = document.getElementById('bBas').getBoundingClientRect(); return [r.width, r.height]; })()")
            self.assertGreaterEqual(min(taille), 44, "assez gros pour être vu et touché")
            self.assertEqual(p.evaluer("document.getElementById('bBas').classList.contains('nouveau')"), False, "elle ne pulse que pendant qu'une réponse s'écrit")
            p.evaluer("document.getElementById('bBas').click()")
            p.attendre("document.getElementById('bBas').hidden")
            self.assertLess(p.evaluer("(() => { const f = document.getElementById('fil'); return f.scrollHeight - f.scrollTop - f.clientHeight; })()"), 90)
            self.assertEqual(p.erreurs, [])

    def test_une_tache_planifiee_se_cree_se_modifie_et_se_supprime_pour_de_bon(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/" % port)
            p.evaluer("document.querySelector('.onglets button[data-p=\"auto\"], #menuReglages button[data-p=\"auto\"]').click()")
            p.attendre("!!document.getElementById('bAjouterPlanifie')")
            p.evaluer("(() => { document.getElementById('pNom').value = 'Résumé du matin'; document.getElementById('pPrompt').value = 'Résume le dépôt.'; document.getElementById('pHeure').value = '07:45'; document.getElementById('bAjouterPlanifie').click(); return true; })()")
            p.attendre("document.getElementById('listePlanifie').textContent.includes('Résumé du matin')", delai=20)
            self.assertEqual([t["heure"] for t in api(p, "/api/planifie")["taches"]], ["07:45"])
            # modifier : le formulaire se remplit, le bouton change, on peut annuler
            p.evaluer("[...document.querySelectorAll('#listePlanifie button')].find(b => b.textContent === 'Modifier').click()")
            p.attendre("document.getElementById('bAjouterPlanifie').textContent === 'Enregistrer les modifications'")
            self.assertEqual(p.evaluer("[document.getElementById('pNom').value, document.getElementById('pHeure').value, document.getElementById('bAnnulerPlanifie').hidden]"), ["Résumé du matin", "07:45", False])
            p.evaluer("(() => { document.getElementById('pNom').value = 'Résumé du soir'; document.getElementById('pHeure').value = '18:30'; document.getElementById('bAjouterPlanifie').click(); return true; })()")
            p.attendre("document.getElementById('listePlanifie').textContent.includes('Résumé du soir')", delai=20)
            taches = api(p, "/api/planifie")["taches"]
            self.assertEqual([(t["nom"], t["heure"]) for t in taches], [("Résumé du soir", "18:30")], "modifiée, pas dupliquée")
            self.assertEqual(p.evaluer("[document.getElementById('bAjouterPlanifie').textContent, document.getElementById('bAnnulerPlanifie').hidden, document.getElementById('pNom').value]"), ["Planifier", True, ""])
            # une seule fois : choisir une date grise les jours
            demain = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            p.evaluer("(() => { const d = document.getElementById('pDate'); d.value = %s; d.dispatchEvent(new Event('change')); return true; })()" % json.dumps(demain))
            self.assertTrue(p.evaluer("[...document.querySelectorAll('#pJours input')].every(c => c.disabled)"))
            p.evaluer("(() => { document.getElementById('pNom').value = 'Une fois'; document.getElementById('pPrompt').value = 'Fais-le.'; document.getElementById('bAjouterPlanifie').click(); return true; })()")
            p.attendre("document.getElementById('listePlanifie').textContent.includes('une seule fois')", delai=20)
            # supprimer : la tâche disparaît du serveur, pas seulement de la page
            p.evaluer("[...document.querySelectorAll('#listePlanifie .conv')].find(l => l.textContent.includes('Une fois')).querySelector('button:last-of-type').click()")
            p.attendre("!document.getElementById('listePlanifie').textContent.includes('Une fois')", delai=20)
            self.assertEqual([t["nom"] for t in api(p, "/api/planifie")["taches"]], ["Résumé du soir"])
            p.evaluer("[...document.querySelectorAll('#listePlanifie button')].find(b => b.textContent === 'Supprimer').click()")
            p.attendre("document.getElementById('listePlanifie').textContent.includes('Aucune tâche planifiée')", delai=20)
            self.assertEqual(api(p, "/api/planifie")["taches"], [])
            self.assertEqual(p.erreurs, [])


if __name__ == "__main__":
    unittest.main()
