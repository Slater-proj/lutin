"""The new interface under `/app/` (lutin.web_app, ADR 0002), on the real server of tests/test_api_v1.py (« network » level).

What is fixed here: nothing is served without a session, the page receives the token and a strict content security policy, only plain file names of
`web/app/assets/` can be read, and a build that does not match the sources is detected. The files are a fake build in a temporary folder: these tests
need neither Node.js nor a real build."""
import http.client
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

from lutin import web_app  # noqa: E402

A = V.A
PAGE = '<!doctype html><html lang="__LANGUAGE__"><head><meta name="lutin-token" content="__TOKEN__"><meta name="lutin-version" content="__VERSION__">' \
       '<script type="module" src="/app/assets/index-B1x_9.js"></script><link rel="stylesheet" href="/app/assets/index-C2y.css"></head><body><div id="app"></div></body></html>'


def setUpModule():
    V.setUpModule()


def get(path, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", V.PORT, timeout=20)
    connection.request("GET", path, headers=dict({"Host": "127.0.0.1:%d" % V.PORT}, **(headers or {})))
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, dict(response.getheaders()), body.decode("utf-8", "replace")


class Served(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lutin-web-app-"))
        (self.root / "assets").mkdir()
        (self.root / "index.html").write_text(PAGE, encoding="utf-8")
        (self.root / "assets" / "index-B1x_9.js").write_text("console.log('app')", encoding="utf-8")
        (self.root / "assets" / "index-C2y.css").write_text("body{margin:0}", encoding="utf-8")
        (self.root / "assets" / ".hidden.js").write_text("x", encoding="utf-8")
        (self.root / "assets" / "tool.exe").write_text("x", encoding="utf-8")
        (self.root / "assets" / "sub").mkdir()
        (self.root / "assets" / "sub" / "deep.js").write_text("x", encoding="utf-8")
        (self.root / "secret.json").write_text("{}", encoding="utf-8")
        patch = mock.patch.object(web_app, "ROOT", self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_page_receives_the_token_the_version_the_language_and_a_strict_policy(self):
        status, headers, body = get("/app/", V.OWNER)
        self.assertEqual((status, headers["Content-Type"], headers["Content-Security-Policy"]), (200, "text/html; charset=utf-8", web_app.CSP))
        self.assertIn('<meta name="lutin-token" content="{}">'.format(A.JETON), body)
        self.assertIn('<html lang="fr">', body)
        self.assertIn('<meta name="lutin-version" content="{}">'.format(A.VERSION), body)
        self.assertNotIn("__", body)
        self.assertEqual(get("/app/index.html", V.OWNER)[2], body)
        self.assertNotIn("unsafe", web_app.CSP)
        self.assertIn("default-src 'none'", web_app.CSP)

    def test_without_a_session_the_sign_in_page_is_shown_and_no_file_is_served(self):
        status, headers, body = get("/app/", V.ELSEWHERE)
        self.assertEqual((status, body), (200, get("/", V.ELSEWHERE)[2]), "the same sign-in page as the present interface")
        self.assertNotIn(A.JETON, body)
        self.assertNotIn("Content-Security-Policy", headers)
        self.assertEqual(get("/app/assets/index-B1x_9.js", V.ELSEWHERE)[0], 401)

    def test_the_built_files_are_served_with_their_type(self):
        status, headers, body = get("/app/assets/index-B1x_9.js", V.DEVICE)
        self.assertEqual((status, headers["Content-Type"], body, headers["X-Content-Type-Options"]), (200, "text/javascript; charset=utf-8", "console.log('app')", "nosniff"))
        status, headers, body = get("/app/assets/index-C2y.css", V.OWNER)
        self.assertEqual((status, headers["Content-Type"], body), (200, "text/css; charset=utf-8", "body{margin:0}"))

    def test_only_a_plain_file_name_of_the_assets_folder_can_be_read(self):
        for path in ("/app/assets/..%2Fsecret.json", "/app/assets/../secret.json", "/app/assets/%2e%2e/secret.json", "/app/assets/..\\secret.json", "/app/assets/.hidden.js",
                     "/app/assets/tool.exe", "/app/assets/sub/deep.js", "/app/assets/sub%2Fdeep.js", "/app/assets/missing.js", "/app/assets/", "/app/assets/index-B1x_9.js%00.css",
                     "/app/secret.json", "/app/build.json", "/app/anything", "/app/assets"):
            status, _, body = get(path, V.OWNER)
            self.assertEqual(status, 404, path)
            self.assertNotIn("{}", body, path)
        for name in ("", ".", "..", "a", ".js", "a..js", "../a.js", "a/b.js", "a\\b.js", "a.js ", "C:a.js"):
            self.assertIsNone(web_app.asset(name), name)
        self.assertIsNotNone(web_app.asset("index-B1x_9.js"))

    def test_a_copy_without_a_build_says_so(self):
        (self.root / "index.html").unlink()
        status, headers, body = get("/app/", V.OWNER)
        self.assertEqual((status, headers["Content-Type"]), (404, "text/html; charset=utf-8"))
        self.assertIn("npm run build", body)
        self.assertFalse(web_app.built())

    def test_values_written_into_the_page_cannot_carry_markup(self):
        self.assertEqual(web_app.page('a"><script>x</script>', "1.0.0a1+g1234", "en-US"), PAGE.replace("__TOKEN__", "ascriptxscript").replace("__VERSION__", "1.0.0a1+g1234").replace("__LANGUAGE__", "en-US"))


class Stamp(unittest.TestCase):
    """A build is recognised by the hash of the sources it was made from (ADR 0002: « a test fails if the shipped assets do not match the sources »)."""

    def sources(self, script=b"let a = 1;\n"):
        folder = Path(tempfile.mkdtemp(prefix="lutin-frontend-"))
        (folder / "src" / "lib").mkdir(parents=True)
        (folder / "package.json").write_bytes(b"{}\n")
        (folder / "src" / "main.ts").write_bytes(script)
        (folder / "src" / "lib" / "api.ts").write_bytes(b"export {};\n")
        (folder / "node_modules").mkdir()
        (folder / "node_modules" / "x.js").write_bytes(b"not a source")
        return folder

    def test_the_stamp_follows_the_sources_and_nothing_else(self):
        first = web_app.sources_stamp(self.sources())
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertEqual(web_app.sources_stamp(self.sources()), first, "same files, same stamp")
        self.assertEqual(web_app.sources_stamp(self.sources(b"let a = 1;\r\n")), first, "line endings do not count: Windows and Linux agree")
        self.assertNotEqual(web_app.sources_stamp(self.sources(b"let a = 2;\n")), first)
        renamed = self.sources()
        (renamed / "src" / "main.ts").rename(renamed / "src" / "start.ts")
        self.assertNotEqual(web_app.sources_stamp(renamed), first)

    def test_a_missing_or_broken_build_has_no_stamp(self):
        with mock.patch.object(web_app, "ROOT", Path(tempfile.mkdtemp(prefix="lutin-web-app-"))):
            self.assertEqual(web_app.build_stamp(), "")
            (web_app.ROOT / "build.json").write_text("[1]", encoding="utf-8")
            self.assertEqual(web_app.build_stamp(), "")
            (web_app.ROOT / "build.json").write_text('{"sources": "abc"}', encoding="utf-8")
            self.assertEqual(web_app.build_stamp(), "abc")

    def test_the_build_of_this_copy_was_made_from_these_sources(self):
        if not web_app.built():
            self.skipTest("no build in this copy (frontend/: npm ci, npm run build): the CI builds before it runs this test")
        self.assertEqual(web_app.build_stamp(), web_app.sources_stamp(), "the interface was changed after the build: run `npm run build` in frontend/")


if __name__ == "__main__":
    unittest.main()
