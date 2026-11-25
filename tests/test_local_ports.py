"""lutin.local_ports: a local server that does not run is known in a quarter of a second, and the refusal is remembered a few seconds.

Hermetic: the connection is a function of the test, or a socket of this test listening on a free port of 127.0.0.1."""
import socket
import unittest
import urllib.error

import context  # noqa: F401

from lutin import local_ports


class LocalPorts(unittest.TestCase):
    def setUp(self):
        local_ports.forget()
        self.addCleanup(local_ports.forget)

    def test_a_refusal_is_known_at_once_then_remembered(self):
        tried, clock = [], [100.0]

        def refused(target, timeout):
            tried.append((target, timeout))
            raise ConnectionRefusedError()
        self.assertTrue(local_ports.down("http://localhost:11434/api/tags", now=lambda: clock[0], connect=refused))
        self.assertEqual(tried, [(("127.0.0.1", 11434), local_ports.PROBE_S)])
        clock[0] += 1
        self.assertTrue(local_ports.down("http://127.0.0.1:11434", now=lambda: clock[0], connect=refused))
        self.assertEqual(len(tried), 1, "remembered: not asked again")
        clock[0] += local_ports.REMEMBER_S
        local_ports.down("http://127.0.0.1:11434", now=lambda: clock[0], connect=refused)
        self.assertEqual(len(tried), 2, "asked again once the refusal is old")

    def test_another_machine_is_never_probed(self):
        def never(*args, **kwargs):
            raise AssertionError("probed")
        self.assertFalse(local_ports.down("http://192.168.1.20:11434", connect=never))
        self.assertFalse(local_ports.down("https://ollama.com/search", connect=never))
        self.assertFalse(local_ports.down("not an address", connect=never))

    def test_a_server_that_listens_is_up_and_check_raises_like_a_refusal_otherwise(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(16)          # a real server accepts at once; a backlog of one would be full after the first probe
        port = server.getsockname()[1]
        self.addCleanup(server.close)
        self.assertFalse(local_ports.down("http://127.0.0.1:%d/x" % port))
        local_ports.check("http://127.0.0.1:%d/x" % port)
        server.close()
        with self.assertRaises(urllib.error.URLError):
            local_ports.check("http://127.0.0.1:%d/x" % port)
        local_ports.forget()
        self.assertTrue(local_ports.down("http://127.0.0.1:%d/x" % port), "closed: nothing listens")


if __name__ == "__main__":
    unittest.main()
