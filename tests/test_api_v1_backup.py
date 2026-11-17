"""`/api/v1/backup` (docs/modernization/PARITY.md, item 3) on the real server of tests/test_api_v1.py (level « network »), with its temporary folders.

A conversation is saved in the archive, changed, then the archive is restored: it comes back as it was, through the store (ADR 0017). Downloading
and restoring need the right to configure; a paired phone may only see where the data is."""
import http.client
import io
import json
import unittest
import zipfile

import test_api_v1 as V  # its temporary folders, its server and its callers (imported as a module: its tests do not run here)

A = V.A


def setUpModule():
    V.setUpModule()


def raw(method, path, data=None, who=None):
    connection = http.client.HTTPConnection("127.0.0.1", V.PORT, timeout=30)
    headers = dict({"Host": "127.0.0.1:%d" % V.PORT}, **(V.OWNER if who is None else who))
    if data is not None:
        headers["Content-Type"] = "application/zip"
    connection.request(method, path, body=data, headers=headers)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, dict(response.getheaders()), body


class Backup(unittest.TestCase):
    def test_where_the_data_is(self):
        status, answer = V.call("GET", "/api/v1/backup/where", V.DEVICE)
        self.assertEqual((status, sorted(answer)), (200, ["backups", "config", "data", "memory"]))
        self.assertEqual(answer["data"], str(A.DONNEES))

    def test_a_backup_is_downloaded_then_restored(self):
        c = A.conv_nouvelle()
        c["titre"] = "Avant la sauvegarde"
        A.conv_ecrire(c)
        self.addCleanup(lambda: A.conv_supprimer(c["id"]))
        status, headers, archive = raw("GET", "/api/v1/backup")
        self.assertEqual(status, 200, archive[:200])
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            self.assertIn("donnees/conversations/%s.json" % c["id"], z.namelist(), "the conversations of the store are in the archive")
            self.assertEqual(json.loads(z.read("donnees/conversations/%s.json" % c["id"]))["titre"], "Avant la sauvegarde")
        c["titre"] = "Changée après"
        A.conv_ecrire(c)
        status, _, body = raw("POST", "/api/v1/backup/restore", archive)
        answer = json.loads(body)
        self.assertEqual((status, answer["restart_needed"]), (200, True), answer)
        self.assertGreater(answer["files"], 0)
        self.assertEqual(A.conv_lire(c["id"])["titre"], "Avant la sauvegarde", "the conversation is back as it was in the archive")
        self.assertTrue(answer["kept_before"], "the state before the restore is kept in a zip of its own")

    def test_downloading_and_restoring_need_the_right_to_configure(self):
        self.assertEqual(raw("GET", "/api/v1/backup", who=V.DEVICE)[0], 403, "an archive holds every conversation: not for a paired phone")
        self.assertEqual(raw("POST", "/api/v1/backup/restore", b"PK", who=V.DEVICE)[0], 403)
        status, _, body = raw("POST", "/api/v1/backup/restore", b"not a zip")
        self.assertEqual((status, json.loads(body)["error"]["code"]), (400, "invalid_request"), "checked whole before anything is written")


if __name__ == "__main__":
    unittest.main()
