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
        p.evaluer("window.confirm = () => true")
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
                          {"role": "user", "content": "Une ancienne conversation ?"},
                          {"role": "assistant", "content": "<think>Ancienne réflexion restée dans le texte.</think>\n\nVoici l'ancienne réponse, propre."}]
        chemin.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")

    def test_la_reflexion_est_repliee_hors_de_la_bulle_et_les_messages_sont_dates(self):
        with self.captures.serveur_demo({"LUTIN_LANGUE": "fr"}) as (port, tmp):
            self.conversation_longue(tmp)
            p = self.ouvrir(tmp, "http://127.0.0.1:%d/#conv=a1b2c3d4" % port)
            p.attendre("document.querySelectorAll('#fil .msg.ia').length >= 20", delai=30)
            blocs = p.evaluer("[...document.querySelectorAll('#fil details.pensee')].map(d => [d.open, d.querySelector('summary').textContent, d.querySelector('pre').textContent, !!d.closest('.corps')])")
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
