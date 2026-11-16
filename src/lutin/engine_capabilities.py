"""What an engine can do for the agent loop (plan step 5, item 7).

`engines.Moteur.grille()` says what a PERSON can do with an engine (chat, images, downloads…): it is shown on the page. This record says what the LOOP
must know to drive an engine: how tool calls reach the model, whether the start of a prompt is read again at each step, what happens when the model does
not fit in the video memory, whether the loop may start the engine itself. The loop used to ask « is it Ollama? »; each engine now declares these facts
(`Moteur.aptitudes()`), and an engine that declares nothing gets the cautious answers: nothing is assumed of it.

Two of these facts are read by the loop today: `starts_on_demand` and `spills_to_cpu`. The others are declared for the work that will use them
(plan step 6, items 2 and 5: prompt cache and slots, grammar): they say what the engine documents, not what Lutin has measured.
`tools` and `embeddings` must agree with the grid of the engine, which the conformance suite checks against a fake server (tests/test_engine_capabilities.py).
"""
from dataclasses import dataclass, fields

YES, NO, UNKNOWN = "yes", "no", "unknown"
NATIVE, TEMPLATE = "native", "template"                 # how tool calls reach the model
AUTOMATIC, ON_REQUEST = "automatic", "on_request"       # how the start of a prompt is reused

ALLOWED = {
    "tools": (NATIVE, TEMPLATE, NO, UNKNOWN),
    "grammar": (YES, NO, UNKNOWN),
    "slots": (YES, NO, UNKNOWN),
    "prompt_cache": (AUTOMATIC, ON_REQUEST, NO, UNKNOWN),
    "embeddings": (YES, NO, UNKNOWN),
    "token_counts": (YES, NO, UNKNOWN),
}


@dataclass(frozen=True)
class EngineCapabilities:
    tools: str = UNKNOWN              # « native »: the engine reads and writes tool calls itself; « template »: through the chat template of the model
    grammar: str = UNKNOWN            # the output can be constrained by a grammar or a JSON schema
    slots: str = UNKNOWN              # a conversation can keep a slot of its own, so that another conversation does not evict what the engine kept of it
    prompt_cache: str = UNKNOWN       # the unchanged start of a prompt is not read again: by itself, or when the request asks for it
    embeddings: str = UNKNOWN         # vectors for the search by meaning
    token_counts: str = UNKNOWN       # the end of an answer says how many tokens were read and written
    starts_on_demand: bool = False    # when the engine does not answer, the loop may start it and try again
    spills_to_cpu: bool = False       # a model too big for the video memory still loads, slower; otherwise loading fails and the person must choose something smaller

    def __post_init__(self):
        for name, allowed in ALLOWED.items():
            if getattr(self, name) not in allowed:
                raise ValueError("{}: {!r} is not one of {}".format(name, getattr(self, name), ", ".join(allowed)))
        for name in ("starts_on_demand", "spills_to_cpu"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError("{} is yes or no".format(name))

    def as_dict(self):
        return {field.name: getattr(self, field.name) for field in fields(self)}


CAUTIOUS = EngineCapabilities()          # an engine of which nothing is known


def of(engine):
    """The capabilities of this engine. An engine that does not declare them, or declares something else than a record, is one of which nothing is known."""
    declare = getattr(engine, "aptitudes", None)
    found = declare() if callable(declare) else None
    return found if isinstance(found, EngineCapabilities) else CAUTIOUS
