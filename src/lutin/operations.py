"""Operations that run inside one request (removing a model, deleting a conversation), told to the activity bar of every screen.

The downloads and installations are tasks that run in the background and say where they are; these end with their request, so only the screen that asked
saw them. Asked by the maintainer (2026-11-21): a removal of a model or of a conversation is seen wherever the person is. `track` registers the operation
while it runs (removing a 20 GB model from a network disk takes a while) and keeps how it ended a moment after, as the engine tasks do."""
import itertools
import threading
import time
from contextlib import contextmanager

KEEP_DONE_S = 8          # what ended well goes by itself
KEEP_FAILED_S = 120      # a failure stays longer: the bar keeps it until it is closed, or until this delay

_LOCK = threading.Lock()
_NEXT = itertools.count(1)
_ITEMS = {}              # id -> {id, kind, name, action, state, text, done, total, finished_at, ends}


@contextmanager
def track(kind, name, action):
    """`with track("model", "qwen3:8b", "remove"):` the operation is listed while the block runs, then « done », or « failed » with the error if it raises (the error goes on)."""
    ident = "{}:{}#{}".format(kind, name, next(_NEXT))
    with _LOCK:
        _ITEMS[ident] = {"id": ident, "kind": kind, "name": str(name), "action": action, "state": "running", "text": "", "done": 0, "total": 0, "finished_at": 0, "ends": 0}
    try:
        yield
    except BaseException as failed:
        _end(ident, "failed", str(failed) or type(failed).__name__, KEEP_FAILED_S)
        raise
    _end(ident, "done", "", KEEP_DONE_S)


def _end(ident, state, text, keep):
    now = time.time()
    with _LOCK:
        item = _ITEMS.get(ident)
        if item is not None:
            item.update(state=state, text=text, finished_at=int(now), ends=now + keep)


def items(now=None):
    """The operations running, and those that ended a moment ago, oldest first, in the shape of GET /activity."""
    now = time.time() if now is None else now
    with _LOCK:
        for ident in [ident for ident, item in _ITEMS.items() if item["ends"] and item["ends"] < now]:
            del _ITEMS[ident]
        return [{key: value for key, value in item.items() if key != "ends"} for item in _ITEMS.values()]


def forget():
    """Tests: nothing listed."""
    with _LOCK:
        _ITEMS.clear()
