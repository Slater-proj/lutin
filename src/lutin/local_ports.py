"""Knowing at once that a local server (Ollama, ComfyUI, an engine on this machine) is not running.

On Windows, connecting to a port of this machine where nothing listens is refused only after about two seconds (the system tries again before giving
up), and the Health page asked up to six times: about fifteen seconds before it showed anything. A server that runs accepts the connection at once,
even when it is busy (the system answers for it), so a quarter of a second is enough to tell; a refusal is remembered a few seconds so the next
question gets its answer without waiting. Only the addresses of this machine are probed: a server on another machine keeps its own timeouts.
"""
import socket
import threading
import time
import urllib.error
import urllib.parse

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
PROBE_S = 0.25
REMEMBER_S = 3.0
_down = {}
_lock = threading.Lock()


def _target(url):
    parts = urllib.parse.urlsplit(str(url or ""))
    host = (parts.hostname or "").lower()
    if host not in LOCAL_HOSTS:
        return None
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None
    return ("127.0.0.1" if host == "localhost" else host), port


def down(url, now=time.monotonic, connect=socket.create_connection):
    """True when `url` is on this machine and nothing listens on its port (seen now, or in the last few seconds). False otherwise, also for an address of
    another machine: the caller then makes its request as before."""
    target = _target(url)
    if target is None:
        return False
    with _lock:
        seen = _down.get(target)
        if seen is not None and now() - seen < REMEMBER_S:
            return True
    try:
        connect(target, timeout=PROBE_S).close()
    except OSError:
        with _lock:
            _down[target] = now()
        return True
    with _lock:
        _down.pop(target, None)
    return False


def check(url):
    """Raises the error a refused connection raises (urllib.error.URLError, an OSError) when `url` is a local server that does not run."""
    if down(url):
        raise urllib.error.URLError(ConnectionRefusedError("nothing listens on {}".format(urllib.parse.urlsplit(url).netloc)))


def forget():
    """Forgets every refusal (a server was just started)."""
    with _lock:
        _down.clear()
