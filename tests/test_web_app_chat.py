"""The Chat screen of the new interface, in a real Chrome, against a real server and the fake engine of tests/test_moteur.py.

End to end: the page loads under its content security policy without a single violation, a message is sent and the answer is written as it arrives,
an action waits for an approval given on the page, the theme changes, and nothing overflows at 360 px. Skipped without a build of the interface
(frontend/: npm ci, npm run build) or without a browser (variable CHROME to name one).
Set LUTIN_SCREENSHOTS to a folder to keep pictures of each step."""
import base64
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import test_moteur as T  # the fake engine and a server at the « this machine » level (imported as a module: its tests do not run here)

import cdp  # noqa: E402
from lutin import web_app  # noqa: E402

CHROME = next((c for c in (os.environ.get("CHROME"), shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chrome"),
                           r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") if c and Path(c).is_file()), None)
WATCH = "window.__violations = []; document.addEventListener('securitypolicyviolation', e => window.__violations.push(e.violatedDirective + ' ' + e.blockedURI));"
TEXT = "(document.querySelector('.thread') || document.body).innerText"


def js(value):
    return json.dumps(value)


class Chat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not web_app.built():
            raise unittest.SkipTest("no build of the interface in this copy (frontend/: npm ci, npm run build)")
        if not CHROME:
            raise unittest.SkipTest("no browser found (variable CHROME to name one)")
        cls.page = cdp.Page(CHROME, tempfile.mkdtemp(prefix="lutin-chrome-"), "1280,900")
        cls.addClassCleanup(cls.page.fermer)
        cls.page.commande("Page.addScriptToEvaluateOnNewDocument", source=WATCH)
        cls.page.aller(T.BASE + "/app/")
        cls.page.attendre("!!document.querySelector('#message')")

    def eventually(self, check, what, seconds=5):
        """The page shows a change at once and the server keeps it a moment later: wait for the server, do not read it on the spot."""
        end = time.time() + seconds
        while time.time() < end:
            if check():
                return
            time.sleep(0.05)
        self.fail("never true within %s s: %s" % (seconds, what))

    def picture(self, name):
        folder = os.environ.get("LUTIN_SCREENSHOTS")
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            (Path(folder) / (name + ".png")).write_bytes(base64.b64decode(self.page.commande("Page.captureScreenshot", format="png")["data"]))

    def write(self, message):
        self.page.evaluer("(() => { const box = document.querySelector('#message'); box.value = %s; box.dispatchEvent(new Event('input', {bubbles: true})); })()" % js(message))
        self.page.attendre("!document.querySelector('.composer button[type=submit]').disabled")

    def test_1_the_page_loads_under_its_policy_with_the_five_areas(self):
        p = self.page
        self.assertEqual(p.evaluer("[...document.querySelectorAll('nav a[href^=\"#/\"]')].map(a => a.getAttribute('href'))"), ["#/chat", "#/agents", "#/projects", "#/models", "#/settings"])
        self.assertEqual(p.evaluer("document.querySelector('nav a[aria-current=page]').getAttribute('href')"), "#/chat")
        self.assertEqual(p.evaluer("document.documentElement.lang"), "fr")
        self.assertIn("Que puis-je faire pour toi", p.evaluer("document.body.innerText"))
        p.evaluer("document.querySelector('.suggestions .chip').click()")
        self.assertEqual(p.evaluer("[document.querySelector('#message').value, document.activeElement.id]"), ["Explique-moi ce que contient ce dossier", "message"],
                         "a suggestion fills the field and puts the cursor in it")
        p.evaluer("(() => { const box = document.querySelector('#message'); box.value = ''; box.dispatchEvent(new Event('input', {bubbles: true})); })()")
        p.attendre("document.querySelector('header select').options.length > 0 && !document.querySelector('header select').disabled")
        self.assertIn(T.INSTALLES[0], p.evaluer("[...document.querySelector('header select').options].map(o => o.value)"))
        self.assertEqual(p.evaluer("window.__violations"), [], "the content security policy blocked something the page needs")
        self.assertEqual(p.erreurs, [])
        self.picture("1-empty")

    def test_2_a_message_is_sent_and_the_answer_is_written(self):
        p = self.page
        T.SCENARIO[:] = [[{"content": "Hello from **the fake** eng"}, {"content": "ine.\n\n- one\n- two\n\n```python\nprint('<b>hi</b>')\n```\n"}]]
        self.write("First message of the test")
        p.evaluer("document.querySelector('.composer button[type=submit]').click()")
        p.attendre(TEXT + ".includes('Hello from the fake engine.')")
        p.attendre("!!document.querySelector('.composer button[type=submit]')")          # the Stop button is gone: the turn is over
        text = p.evaluer(TEXT)
        self.assertIn("First message of the test", text)
        self.assertEqual(text.count("Hello from the fake engine."), 1, "the stored answer replaces the one that was being written")
        self.assertEqual(p.evaluer("document.querySelector('#message').value"), "")
        self.assertEqual(p.evaluer("[document.querySelector('.thread strong').innerText, document.querySelectorAll('.thread .markdown ul li').length]"), ["the fake", 2], "Markdown is drawn")
        self.assertEqual(p.evaluer("document.querySelector('.thread figure.code pre').innerText"), "print('<b>hi</b>')", "code is shown as written")
        self.assertEqual(p.evaluer("document.querySelectorAll('.thread b, .thread script').length"), 0, "an answer never becomes HTML")
        self.assertEqual(p.evaluer("document.querySelectorAll('.list .entry').length"), 1)
        self.assertEqual(p.evaluer("document.querySelector('.list .entry').getAttribute('aria-current')"), "true")
        self.assertEqual(p.erreurs, [])
        self.picture("2-answer")

    def test_3_an_action_waits_for_the_approval_given_on_the_page(self):
        p = self.page
        target = T.PROJET / "appli" / "moteur" / "code.py"
        before = target.read_text(encoding="utf-8")
        T.SCENARIO[:] = [[T.appel_outil("modifier", chemin="appli/moteur/code.py", ancien="return 1", nouveau="return 2")], [{"content": "Left as it was."}]]
        self.write("Change the file")
        p.evaluer("document.querySelector('.composer button[type=submit]').click()")
        p.attendre("!!document.querySelector('.card .button.danger')")
        self.assertIn("return 2", p.evaluer("document.querySelector('.card').innerText"))
        self.assertTrue(p.evaluer("!!document.querySelector('.composer .stop')"), "while Lutin works, the button stops the turn")
        self.picture("3-approval")
        p.evaluer("document.querySelector('.card .button.danger').click()")
        p.attendre(TEXT + ".includes('Left as it was.')")
        p.attendre("!!document.querySelector('.composer button[type=submit]')")
        self.assertEqual(target.read_text(encoding="utf-8"), before, "refused on the page: the file is untouched")
        self.assertFalse(p.evaluer("!!document.querySelector('.card')"))
        self.assertTrue(p.evaluer("[...document.querySelectorAll('.thread details summary')].some(s => s.innerText.includes('modifier'))"), "the tool call stays visible in the stored conversation")
        self.assertEqual(p.erreurs, [])

    def test_3b_the_conversation_is_renamed_and_pinned(self):
        p = self.page
        p.evaluer("document.querySelector('.rename-button').click()")
        p.attendre("document.activeElement && document.activeElement.id === 'title'")
        p.evaluer("(() => { const box = document.querySelector('#title'); box.value = 'Renamed on the page'; box.dispatchEvent(new Event('input', {bubbles: true})); box.form.requestSubmit(); })()")
        p.attendre("document.querySelector('header h1') && document.querySelector('header h1').innerText === 'Renamed on the page'")
        self.assertEqual(p.evaluer("document.querySelector('.list .entry .title').innerText"), "Renamed on the page")
        p.evaluer("document.querySelector('.pin-button').click()")
        p.attendre("document.querySelector('.pin-button').getAttribute('aria-pressed') === 'true'")
        self.assertTrue(p.evaluer("!!document.querySelector('.list .entry .tag')"), "the pin shows in the list")
        stored = [c for c in T.lire("/api/etat")["conversations"] if c["titre"] == "Renamed on the page"]
        self.assertEqual([c.get("epingle") for c in stored], [True], "renamed and pinned on the server, not only on the page")
        self.assertEqual(p.erreurs, [])

    def test_3c_a_message_is_edited_and_the_conversation_goes_on_from_it(self):
        p = self.page
        before = p.evaluer("document.querySelectorAll('.thread .mine').length")
        self.assertEqual(before, 2)
        p.evaluer("document.querySelectorAll('.thread .mine .edit')[1].click()")
        self.assertEqual(p.evaluer("[document.querySelector('#message').value, !!document.querySelector('.editing')]"), ["Change the file", True])
        T.SCENARIO[:] = [[{"content": "Answer to the edited message."}]]
        self.write("Say hello instead")
        p.evaluer("document.querySelector('.composer button[type=submit]').click()")
        p.attendre(TEXT + ".includes('Answer to the edited message.')")
        p.attendre("!!document.querySelector('.composer button[type=submit]')")
        text = p.evaluer(TEXT)
        self.assertIn("Say hello instead", text)
        self.assertNotIn("Change the file", text, "the message that was edited is replaced")
        self.assertNotIn("Left as it was.", text, "and what followed it is gone")
        self.assertIn("Hello from the fake engine.", text, "what came before is kept")
        self.assertEqual(p.evaluer("[document.querySelectorAll('.thread .mine').length, !!document.querySelector('.editing')]"), [2, False])
        self.assertEqual(p.erreurs, [])

    def test_3d_the_options_of_a_conversation_are_chosen_on_the_page_and_kept_by_the_server(self):
        p = self.page
        p.evaluer("document.querySelector('.bar .toggle').click()")
        p.attendre("!!document.querySelector('#options-panel')")
        self.assertEqual(p.evaluer("[...document.querySelectorAll('.approvals input')].map(i => i.checked)"), [False, False], "the automatic approvals start off")
        self.assertFalse(p.evaluer("!!document.querySelector('.bar .auto')"))
        p.evaluer("document.querySelectorAll('.approvals input')[1].click()")
        p.attendre("!!document.querySelector('.bar .auto')")
        self.assertIn("commandes", p.evaluer("document.querySelector('.bar .auto').innerText"), "an approval that is on stays visible while the panel is shut")
        conversation = p.evaluer("document.querySelector('.list .entry[aria-current=true]') && 'open'")
        self.assertEqual(conversation, "open")
        stored = [c for c in T.lire("/api/etat")["conversations"] if c["titre"] == "Renamed on the page"][0]["id"]
        self.eventually(lambda: T.A.options_lire(stored).get("auto_commandes") is True, "auto_commandes stored on the server, for this conversation")
        p.evaluer("(() => { const s = document.querySelector('#options-panel select'); s.value = 'mission'; s.dispatchEvent(new Event('change', {bubbles: true})); })()")
        p.attendre("document.querySelectorAll('#options-panel select').length === 2")
        self.eventually(lambda: T.A.options_lire(stored).get("mode") == "mission", "mode stored on the server")
        self.picture("3d-options")
        p.evaluer("(() => { const s = document.querySelector('#options-panel select'); s.value = 'general'; s.dispatchEvent(new Event('change', {bubbles: true})); })()")
        p.evaluer("document.querySelectorAll('.approvals input')[1].click()")
        p.attendre("!document.querySelector('.bar .auto')")
        self.assertEqual(p.erreurs, [])

    def test_3e_options_chosen_before_the_first_message_apply_to_the_conversation_it_creates(self):
        p = self.page
        p.evaluer("[...document.querySelectorAll('.list .new')].forEach(b => b.click())")
        p.attendre("!!document.querySelector('.welcome')")
        p.attendre("!!document.querySelector('.bar .toggle')")
        if not p.evaluer("!!document.querySelector('#options-panel')"):
            p.evaluer("document.querySelector('.bar .toggle').click()")
        p.attendre("!!document.querySelector('#options-panel')")
        p.evaluer("document.querySelectorAll('.approvals input')[0].click()")
        T.SCENARIO[:] = [[{"content": "Done with the option."}]]
        self.write("Message with an option chosen first")
        p.evaluer("document.querySelector('.composer button[type=submit]').click()")
        p.attendre(TEXT + ".includes('Done with the option.')")
        p.attendre("!!document.querySelector('.composer button[type=submit]')")
        created = [c for c in T.lire("/api/etat")["conversations"] if c["titre"].startswith("Message with an option")][0]["id"]
        self.eventually(lambda: T.A.options_lire(created).get("auto_ecriture") is True, "the option chosen before the conversation existed was applied to it")
        self.assertEqual(p.evaluer("document.querySelector('.bar .auto').innerText.includes('fichiers')"), True)
        p.evaluer("document.querySelectorAll('.approvals input')[0].click()")
        p.attendre("!document.querySelector('.bar .auto')")
        self.assertEqual(p.erreurs, [])

    def choose_files(self, *paths):
        """What a person does with the file dialog: the chosen files reach the input of the page, which fires its change event."""
        p = self.page
        root = p.commande("DOM.getDocument")["root"]["nodeId"]
        node = p.commande("DOM.querySelector", nodeId=root, selector="#file-input")["nodeId"]
        p.commande("DOM.setFileInputFiles", files=[str(path) for path in paths], nodeId=node)

    def test_3f_a_document_and_an_image_are_attached_sent_shown_and_kept_when_the_message_is_edited(self):
        p = self.page
        folder = Path(tempfile.mkdtemp(prefix="lutin-attach-"))
        note = folder / "note.txt"
        note.write_text("The secret word is marmalade. " * 3, encoding="utf-8")
        picture = folder / "dot.png"
        picture.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
        p.evaluer("[...document.querySelectorAll('.list .new')].forEach(b => b.click())")
        p.attendre("!!document.querySelector('.welcome')")
        self.choose_files(note, picture)
        p.attendre("document.querySelectorAll('.chips li').length === 2 && document.querySelectorAll('.chips li.busy').length === 0")
        self.assertEqual(p.evaluer("document.querySelector('.chips img').naturalWidth"), 1, "the picture is shown from the server through the session cookie alone")
        self.assertIn("note.txt", p.evaluer("document.querySelector('.chips').innerText"))
        self.picture("3f-attached")
        p.evaluer("document.querySelector('.chips .remove').click()")           # remove the first chip, the document
        p.attendre("document.querySelectorAll('.chips li').length === 1")
        self.choose_files(note)
        p.attendre("document.querySelectorAll('.chips li').length === 2 && document.querySelectorAll('.chips li.busy').length === 0")
        T.SCENARIO[:] = [[{"content": "The note says marmalade."}]]
        self.write("What does the note say?")
        p.evaluer("document.querySelector('.composer button[type=submit]').click()")
        p.attendre(TEXT + ".includes('The note says marmalade.')")
        p.attendre("!!document.querySelector('.composer button[type=submit]')")
        self.assertIn("marmalade", json.dumps(T.RECUES[-1]["messages"]), "the text of the document was given to the model")
        self.assertEqual(p.evaluer("document.querySelectorAll('.chips li').length"), 0, "what was sent is no longer attached")
        self.assertEqual(p.evaluer("document.querySelector('.thread .sent img').naturalWidth"), 1, "the image is shown in the message, read back from the server")
        self.assertIn("note.txt", p.evaluer("document.querySelector('.thread .files').innerText"))
        self.picture("3f-sent")
        edits = p.evaluer("document.querySelectorAll('.thread .mine .edit').length")
        p.evaluer("document.querySelectorAll('.thread .mine .edit')[%d].click()" % (edits - 1))
        self.assertEqual(p.evaluer("document.querySelectorAll('.chips li').length"), 2, "editing a message keeps what was sent with it")
        p.evaluer("document.querySelector('.editing .link').click()")
        self.assertEqual(p.evaluer("document.querySelectorAll('.chips li').length"), 0, "cancelling the edit drops them")
        self.assertEqual(p.erreurs, [])

    def test_4_a_refusal_of_the_server_is_shown_and_the_message_is_given_back(self):
        p = self.page
        with mock.patch.object(T.A, "TOURS_SIMULTANES", 0):
            self.write("Too many at once")
            p.evaluer("document.querySelector('.composer button[type=submit]').click()")
            p.attendre("!!document.querySelector('.dock .problem')")
        self.assertIn("réponses en cours", p.evaluer("document.querySelector('.dock .problem').innerText"))
        self.assertEqual(p.evaluer("document.querySelector('#message').value"), "Too many at once")
        self.page.evaluer("(() => { const box = document.querySelector('#message'); box.value = ''; box.dispatchEvent(new Event('input', {bubbles: true})); })()")

    def test_5_the_theme_changes_and_is_remembered(self):
        p = self.page
        colour = "getComputedStyle(document.body).backgroundColor"
        seen = {}
        for _ in range(3):
            p.evaluer("document.querySelector('nav .foot button').click()")
            seen[p.evaluer("document.documentElement.getAttribute('data-theme') || 'system'")] = p.evaluer(colour)
        self.assertEqual(sorted(seen), ["dark", "light", "system"])
        self.assertNotEqual(seen["light"], seen["dark"])
        p.evaluer("document.querySelector('nav .foot button').click()")          # light
        p.aller(T.BASE + "/app/")
        p.attendre("!!document.querySelector('#message')")
        self.assertEqual(p.evaluer("document.documentElement.getAttribute('data-theme')"), "light", "kept in this browser")
        self.picture("5-light")
        p.evaluer("document.querySelector('nav .foot button').click()")          # dark
        self.picture("5-dark")

    def test_5b_the_models_screen_lists_uses_downloads_and_deletes(self):
        p = self.page
        installed, model = list(T.INSTALLES), T.A.reglages()["modele"]
        self.addCleanup(lambda: (T.INSTALLES.__setitem__(slice(None), installed), T.A.PULLS.clear(), T.A.enregistrer_reglages({"modele": model})))
        T.INSTALLES[:] = ["qwen3.8:27b", "other:7b"]
        T.A.enregistrer_reglages({"modele": "qwen3.8:27b"})
        p.evaluer("location.hash = '#/models'")
        p.attendre("document.querySelectorAll('.models .card').length === 2")
        self.assertEqual(p.evaluer("document.querySelector('.models .card.current strong').innerText"), "qwen3.8:27b")
        self.assertIn("tourne", p.evaluer("document.querySelector('.models .engine').innerText"))
        self.picture("5b-models")
        p.evaluer("[...document.querySelectorAll('.models .card')].find(c => c.innerText.includes('other:7b')).querySelector('.button:not(.danger)').click()")
        self.eventually(lambda: T.A.reglages()["modele"] == "other:7b", "the model in use was changed on the server")
        p.attendre("document.querySelector('.models .card.current strong').innerText === 'other:7b'")
        p.evaluer("(() => { const i = document.querySelector('#model-name'); i.value = 'gemma4:12b'; i.dispatchEvent(new Event('input', {bubbles: true})); })()")
        p.attendre("!document.querySelector('.models .add .button').disabled")
        p.evaluer("document.querySelector('.models .add .button').click()")
        p.attendre("!!document.querySelector('.models .downloads .card')")
        p.attendre("document.querySelectorAll('.models .cards:not(.downloads) .card').length === 3", 20)
        self.assertEqual(p.evaluer("document.querySelector('.models .downloads .card').dataset.state"), "done")
        p.evaluer("window.confirm = () => true")
        p.evaluer("[...document.querySelectorAll('.models .card')].find(c => c.innerText.includes('gemma4:12b') && c.querySelector('.danger')).querySelector('.danger').click()")
        p.attendre("document.querySelectorAll('.models .cards:not(.downloads) .card').length === 2")
        self.eventually(lambda: "gemma4:12b" not in T.INSTALLES, "the model was deleted on the engine")
        self.assertEqual(p.erreurs, [])
        p.evaluer("location.hash = '#/chat'")

    def test_6_nothing_overflows_at_360_px_and_another_area_says_it_is_not_there_yet(self):
        p = self.page
        p.commande("Emulation.setDeviceMetricsOverride", width=360, height=740, deviceScaleFactor=1, mobile=True)
        try:
            p.aller(T.BASE + "/app/")
            p.attendre("!!document.querySelector('#message')")
            self.assertLessEqual(p.evaluer("document.documentElement.scrollWidth"), 360)
            self.assertTrue(p.evaluer("[...document.querySelectorAll('nav li a')].every(a => a.getBoundingClientRect().height >= 44)"), "navigation targets of 44 px at least")
            self.picture("6-phone")
            p.evaluer("document.querySelector('.open-list').click()")
            p.attendre("!!document.querySelector('.chat.list-open')")
            self.assertGreaterEqual(p.evaluer("document.querySelectorAll('.list .entry').length"), 1)
            self.assertLessEqual(p.evaluer("document.documentElement.scrollWidth"), 360)
            p.evaluer("location.hash = '#/models'")
            p.attendre("document.querySelector('main h1') && document.querySelector('main h1').innerText.includes('Modèles')")
            self.assertEqual(p.evaluer("document.querySelector('nav a[aria-current=page]').getAttribute('href')"), "#/models")
            self.assertEqual(p.evaluer("window.__violations"), [])
        finally:
            p.commande("Emulation.clearDeviceMetricsOverride")


if __name__ == "__main__":
    unittest.main()
