"""The state of the turns that are running (plan step 5, item 2).

A turn is what `agent.tour` runs for one request of one conversation. Its state used to be implicit, and spread: a conversation was « active » when its stop
event was in `core.TOURS_ACTIFS` (set by whoever launched the turn), « waiting » when an approval card or a memory question carried its id, and nothing told
a turn that loads a model from one that is frozen. The turn now says where it is, and the interface, the scheduler and the add-ons read it instead of guessing.

The turn itself keeps this record: whoever launches it (the web server, a scheduled task, a mission, an add-on) has nothing to do.
Every function is keyed by the conversation, and does nothing when no turn of that conversation is recorded: the parts of a turn can be called alone.
"""
import threading
import time
from contextlib import contextmanager

RUNNING = "running"                        # the turn works: it builds its context, the model writes, a tool runs
WAITING_APPROVAL = "waiting_approval"      # the turn waits for a person: an approval card, or the memory question
STALLED = "stalled"                        # the turn works but nothing has come out for STALL_AFTER_S: a model that loads, a long command, or something frozen
CANCELLED = "cancelled"                    # Stop was asked: the turn is winding down
STATES = (RUNNING, WAITING_APPROVAL, STALLED, CANCELLED)

CONTEXT, MODEL, TOOL = "context", "model", "tool"          # what a running turn is doing: the parts of the loop
PHASES = (CONTEXT, MODEL, TOOL)

STALL_AFTER_S = 90

_LOCK = threading.Lock()
_TURNS = {}          # conversation id -> _Turn


class _Turn:
    def __init__(self, conversation, stop, clock):
        self.conversation, self.stop, self.clock = conversation, stop, clock
        self.started = self.active = clock()
        self.phase, self.step, self.detail = CONTEXT, 0, ""
        self.waiting = []          # what the turn waits for, the newest last: a turn can only wait for one thing at a time, a list keeps the code honest if that changes

    def state(self):
        if self.stop is not None and self.stop.is_set():
            return CANCELLED
        if self.waiting:
            return WAITING_APPROVAL
        return STALLED if self.clock() - self.active >= STALL_AFTER_S else RUNNING

    def view(self):
        now = self.clock()
        return {"conversation": self.conversation, "state": self.state(), "phase": self.phase, "step": self.step, "detail": self.waiting[-1] if self.waiting else self.detail,
                "elapsed_s": round(now - self.started, 1), "idle_s": round(now - self.active, 1)}


def begin(conversation, stop=None, clock=time.monotonic):
    """Records a turn of this conversation and returns its record, to give back to `end`. A conversation runs one turn at a time: a turn recorded before
    (abandoned after Stop, see `core._rendre_la_main`) is replaced."""
    turn = _Turn(str(conversation), stop, clock)
    with _LOCK:
        _TURNS[turn.conversation] = turn
    return turn


def end(turn):
    """The turn is over. Only the turn that is recorded leaves: an abandoned turn that ends late does not erase the one that replaced it."""
    with _LOCK:
        if _TURNS.get(turn.conversation) is turn:
            del _TURNS[turn.conversation]


def _turn(conversation):
    return _TURNS.get(str(conversation))


def touch(conversation):
    """A sign of life: something was sent to the page."""
    turn = _turn(conversation)
    if turn is not None:
        turn.active = turn.clock()


def phase(conversation, name, detail="", step=None):
    """The turn enters a part of the loop: `context`, `model` or `tool` (with the name of the tool). `step` is the number of the model call, from 0."""
    if name not in PHASES:
        raise ValueError("unknown phase: {!r}".format(name))
    turn = _turn(conversation)
    if turn is None:
        return
    with _LOCK:
        turn.phase, turn.detail = name, str(detail)[:120]
        if step is not None:
            turn.step = int(step)
        turn.active = turn.clock()


@contextmanager
def waiting(conversation, detail=""):
    """For as long as the block lasts, the turn waits for a person. Time spent waiting is not time without a sign of life."""
    turn = _turn(conversation)
    if turn is None:
        yield
        return
    label = str(detail)[:120]
    with _LOCK:
        turn.waiting.append(label)
    try:
        yield
    finally:
        with _LOCK:
            if label in turn.waiting:
                turn.waiting.remove(label)
            turn.active = turn.clock()


def of(conversation):
    """The state of the turn of this conversation ({conversation, state, phase, step, detail, elapsed_s, idle_s}), or None when it runs none."""
    turn = _turn(conversation)
    return turn.view() if turn is not None else None


def snapshot():
    """The turns that run now, oldest first."""
    with _LOCK:
        turns = sorted(_TURNS.values(), key=lambda turn: turn.started)
    return [turn.view() for turn in turns]
