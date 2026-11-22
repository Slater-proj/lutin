"""What a node reads of the computer it runs on, replaced in the tests of paired machines.

A node answers a probe or a pairing with what it reads of this computer: its network cards and their Wake-on-LAN state (PowerShell on Windows),
whether Lutin starts with the session (schtasks, the registry), its memory and graphics card (nvidia-smi). A test that pairs a server with itself
started those programs on the machine running the tests: slow (PowerShell answered in 20 s on a loaded Windows), and dependent on that machine's
cards. `quiet(test)` replaces them for the length of one test, with fixed values, and empties what the node keeps of them. The hardware profile
that sizes the models (the registry and nvidia-smi again) is the fictive machine of `hardware.profil_demo`, as in tests/test_web_app_chat.py."""
import time
from unittest import mock

from lutin import core, hardware, machines, model_fit, power

NO_WAKE = {"mac": "", "carte": "", "pret": None, "avertissements": []}
STARTUP = {"installe": True, "possible": True, "limites": ""}


def quiet(test):
    for patch in (mock.patch.object(power, "network_adapters", lambda *a, **k: []),
                  mock.patch.object(power, "wake_state", lambda *a, **k: dict(NO_WAKE)),
                  mock.patch.object(power, "startup_state", lambda *a, **k: dict(STARTUP)),
                  mock.patch.object(power, "startup_state_memo", lambda: dict(STARTUP)),
                  mock.patch.object(core, "system_memory", lambda: {"total": 32 * 1024 ** 3, "libre": 16 * 1024 ** 3}),
                  mock.patch.object(core, "video_memory", lambda: None),
                  mock.patch.dict(model_fit._state, {"profil": hardware.demo_profile(), "quand": time.time() + 3600, "en_cours": False})):
        patch.start()
        test.addCleanup(patch.stop)
    machines.NODE_INFO.clear()
    machines.CARDS.update(t=-999.0, v=None)
