"""One entry takes a seat for a turn, runs the turn and frees the seat, whoever launched it (ADR 0015).

A seat is the entry of a conversation in `core.TOURS_ACTIFS` (its stop event) and in `core.RACINE_TOURS` (the work folder of the turn). The rules are
the same for every launcher (the page, the missions, the scheduled tasks, Telegram, the automatic replies):

- one turn per conversation, and at most `core.TOURS_SIMULTANES` turns at once;
- the work folder is chosen with `core.VERROU_TOURS` held (`workspace_manager` relies on it);
- a seat is freed only by the turn that holds it: a turn abandoned after « Stop » (`core._rendre_la_main`) has lost its seat, maybe to a newer turn;
- the thread that runs a turn is marked (`core.LOCAL_TOUR.stop`), so that an abandoned turn never writes its conversation again (`storage.conv_ecrire`).

`reserve` then `Seat.run` is for a launcher that has something to do in between (the page sends the head of its stream); `run_turn` does all of it.
"""
import threading
import time

from . import core as _m

TURN_RUNNING = "turn_running"
TOO_MANY_TURNS = "too_many_turns"
WORKSPACE_CONFLICT = "workspace_conflict"


class TurnRefused(Exception):
    """No seat: `code` is one of TURN_RUNNING, TOO_MANY_TURNS, WORKSPACE_CONFLICT; `message` is the reason given by the work folder, if any."""

    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code, self.message = code, message


def active():
    """The conversations that have a turn running (a copy, safe to iterate)."""
    with _m.TURNS_LOCK:
        return dict(_m.ACTIVE_TURNS)


def full():
    """True when no seat is free: a cheap check before doing any work, the seat itself is taken by `reserve`."""
    with _m.TURNS_LOCK:
        return len(_m.ACTIVE_TURNS) >= _m.CONCURRENT_TURNS


class Seat:
    """The seat of one turn. Use it as a context manager: on exit it is freed, if it is still its own."""

    def __init__(self, conv, stop):
        self.conv, self.stop = conv, stop

    def run(self, text, emit, settings=None, replace_from=None, **options):
        """Runs the turn (`core.tour`) in this thread, marked with the stop event of the seat for the time of the turn."""
        before = getattr(_m.TURN_LOCAL, "stop", None)
        _m.TURN_LOCAL.stop = self.stop
        try:
            return _m.tour(self.conv, text, emit, settings, self.stop, replace_from, **options)
        finally:
            _m.TURN_LOCAL.stop = before          # a thread that runs several turns (a mission, an add-on) is not left marked by an abandoned one

    def release(self):
        with _m.TURNS_LOCK:
            ident = self.conv["id"]
            if _m.ACTIVE_TURNS.get(ident) is self.stop:
                _m.ACTIVE_TURNS.pop(ident, None)
                _m.TURNS_ROOT.pop(ident, None)

    @property
    def abandoned(self):
        return bool(getattr(self.stop, "abandonne", False))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False


def reserve(conv, *, work=None, wait_s=0, give_up=None, poll_s=2, also=None):
    """Takes a seat for a turn in `conv`, or raises TurnRefused.

    work: the work folder asked for (`core.activate_work`), or None to leave the folder in use as it is. wait_s: how long to wait for the conversation
    or a seat to be free, checking every `poll_s` seconds and giving up early when `give_up` (an event) is set. also(stop): called with the lock held
    once the seat is taken, for a launcher's own registry (a task at work, a running mission); if it raises, the seat is given back."""
    stop = threading.Event()
    deadline = time.monotonic() + max(0, wait_s)
    while True:
        with _m.TURNS_LOCK:
            ident = conv["id"]
            if ident in _m.ACTIVE_TURNS:
                refused = TurnRefused(TURN_RUNNING)
            elif len(_m.ACTIVE_TURNS) >= _m.CONCURRENT_TURNS:
                refused = TurnRefused(TOO_MANY_TURNS)
            else:
                if work is not None:
                    try:
                        _m.activate_work(conv, work)
                    except ValueError as erreur:
                        raise TurnRefused(WORKSPACE_CONFLICT, str(erreur)) from None
                _m.TURNS_ROOT[ident] = str(_m.ROOT)
                _m.ACTIVE_TURNS[ident] = stop
                if also is not None:
                    try:
                        also(stop)
                    except BaseException:
                        _m.ACTIVE_TURNS.pop(ident, None)
                        _m.TURNS_ROOT.pop(ident, None)
                        raise
                return Seat(conv, stop)
        if time.monotonic() >= deadline or (give_up is not None and give_up.is_set()):
            raise refused
        time.sleep(poll_s)


def run_turn(conv, text, emit, settings=None, *, work=None, wait_s=0, give_up=None, poll_s=2, also=None, replace_from=None, **options):
    """Takes a seat (see `reserve`, which may raise TurnRefused), runs the turn, frees the seat. Returns the Seat, to read `stop` and `abandoned`."""
    with reserve(conv, work=work, wait_s=wait_s, give_up=give_up, poll_s=poll_s, also=also) as seat:
        seat.run(text, emit, settings, replace_from, **options)
    return seat
