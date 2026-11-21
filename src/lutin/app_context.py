"""The application context (ADR 0014): what a running Lutin read from its environment, read once, in one place.

Stage 1 holds the settings only. The modules keep their names (`core.RACINE`, `core.OLLAMA`, `web.DDG_URL`…): `bind` gives each of
those modules a class whose properties read and write the current context, and keeps a copy of each value in the module's own
dictionary (the mirror). The bare names inside the module read the mirror; `mock.patch.object` reads it to know what to put back.
A write through the module (`core.OLLAMA = …`, a patch, `install`, `change`) updates the context and the mirror together; a write
that bypasses them (`global RACINE` in the module) would leave them apart, which is why `Settings` is frozen.

One context per process at a time, not a `ContextVar`: the server answers each request in a new thread, which would not inherit it.
"""
import dataclasses
import os
import sys
import threading
import types
from contextlib import contextmanager
from pathlib import Path


@dataclasses.dataclass(frozen=True)
class Settings:
    root: Path                  # LUTIN_RACINE: the working folder, the only part of the disk the assistant reads and changes
    data: Path                  # LUTIN_DONNEES
    memory: Path                # LUTIN_MEMOIRE
    ollama_url: str             # OLLAMA_URL
    tool_url: str               # LUTIN_OUTIL_URL: the optional image tool; without it its tools are not offered
    port: int                   # LUTIN_PORT
    catalogue: str | None       # LUTIN_CATALOGUE: another file of proposed models
    default_model: str          # LUTIN_MODELE
    resource_guard: bool        # LUTIN_SANS_GARDE != "1"
    auto_start: bool            # LUTIN_SANS_DEMARRAGE != "1": start Ollama when a request finds it stopped
    search_ddg_url: str         # LUTIN_RECHERCHE_URL
    search_brave_url: str       # LUTIN_BRAVE_URL
    search_tavily_url: str      # LUTIN_TAVILY_URL
    search_exa_url: str         # LUTIN_EXA_URL
    search_perplexity_url: str  # LUTIN_PERPLEXITY_URL

    @classmethod
    def from_env(cls, environ=None, cwd=None, home=None):
        env = os.environ if environ is None else environ
        data = Path(env.get("LUTIN_DONNEES") or Path(home or Path.home()) / ".lutin" / "donnees")
        return cls(
            root=Path(env.get("LUTIN_RACINE") or cwd or Path.cwd()).resolve(),
            data=data,
            memory=Path(env.get("LUTIN_MEMOIRE") or data.parent / "memoire"),
            ollama_url=env.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            tool_url=env.get("LUTIN_OUTIL_URL", "").rstrip("/"),
            port=int(env.get("LUTIN_PORT", "8777")),
            catalogue=env.get("LUTIN_CATALOGUE") or None,
            default_model=env.get("LUTIN_MODELE") or "qwen3:8b",
            resource_guard=env.get("LUTIN_SANS_GARDE") != "1",
            auto_start=env.get("LUTIN_SANS_DEMARRAGE") != "1",
            search_ddg_url=env.get("LUTIN_RECHERCHE_URL", "https://html.duckduckgo.com/html/"),
            search_brave_url=env.get("LUTIN_BRAVE_URL", "https://api.search.brave.com/res/v1/"),
            search_tavily_url=env.get("LUTIN_TAVILY_URL", "https://api.tavily.com/"),
            search_exa_url=env.get("LUTIN_EXA_URL", "https://api.exa.ai/"),
            search_perplexity_url=env.get("LUTIN_PERPLEXITY_URL", "https://api.perplexity.ai/"),
        )


class AppContext:
    def __init__(self, settings):
        self.settings = settings

    @classmethod
    def from_env(cls, environ=None, cwd=None, home=None):
        return cls(Settings.from_env(environ, cwd, home))


_LOCK = threading.RLock()
_current = None
_BOUND = {}          # module name -> {module attribute: field of Settings}


def current():
    global _current
    with _LOCK:
        if _current is None:
            _current = AppContext.from_env()
        return _current


def _refresh_mirrors():
    settings = current().settings
    for module_name, names in _BOUND.items():
        module = sys.modules.get(module_name)
        if module is not None:
            for name, field in names.items():
                module.__dict__[name] = getattr(settings, field)


def install(ctx):
    """Makes `ctx` the context of the process and returns the one it replaces (None before the first)."""
    global _current
    with _LOCK:
        previous, _current = _current, ctx
        _refresh_mirrors()
        return previous


def change(**fields):
    """The one way to change a setting while Lutin runs (the working folder, the port the launcher chose, a test's fake server)."""
    with _LOCK:
        ctx = current()
        ctx.settings = dataclasses.replace(ctx.settings, **fields)
        _refresh_mirrors()


@contextmanager
def scope(ctx):
    """Runs a block in `ctx`, then puts the previous context back."""
    previous = install(ctx)
    try:
        yield ctx
    finally:
        install(previous)          # None: the next reading builds one from the environment again


def _setting(field):
    return property(lambda module: getattr(current().settings, field), lambda module, value: change(**{field: value}))


def bind(module_name, names):
    """Makes the module attributes `names` ({attribute: field of Settings}) read and write the current context."""
    module = sys.modules[module_name]
    fields = {f.name for f in dataclasses.fields(Settings)}
    unknown = sorted(set(names.values()) - fields)
    if unknown:
        raise ValueError("not a setting: " + ", ".join(unknown))
    with _LOCK:
        _BOUND[module_name] = dict(names)
        module.__class__ = type("BoundModule", (types.ModuleType,), {name: _setting(field) for name, field in names.items()})
        _refresh_mirrors()
