"""Where each piece of context goes in a request to the model (ADR 0013).

An engine keeps what it has already read: a request that starts like the previous one only costs what follows the common start. So a request has

- a prefix that stays: the system message, with nothing in it that follows the request;
- what follows the request, read once for the turn, in one pair of messages just before the last question (`turn_block`, `before_last_question`):
  the progress sheet, the extracts of the thread, the recalls drawn from the documents;
- what changes inside a turn, written at the end of the last message (`attach_tail`): the task list.

The loop (`agent._messages_de_l_etape`) assembles; this module says where things go and how much room recalls may take.
"""

CHARS_PER_TOKEN = 3          # the estimate used everywhere in Lutin
RECALL_SHARE = 0.10          # of the window, for the extracts of the thread and the recalls of the documents together
THREAD_MAX = 1800            # characters of passages: the ceiling of the extracts of the thread
DOCUMENTS_MAX = 2200         # and of the recalls drawn from the documents
RECALL_MIN = 300             # below this, a recall is a title and half a sentence: none is better

TAIL = "tail"                # private key of a message: text to write at its end once the request fits the window
KEPT = "kept"                # private key of a message: part of the block of the turn, never removed to make room
PRIVATE = (TAIL, KEPT)


def recall_budget(num_ctx):
    """Characters that recalled passages (thread and documents together) may take in a window of `num_ctx` tokens."""
    return int(num_ctx * RECALL_SHARE * CHARS_PER_TOKEN)


def thread_budget(num_ctx):
    """The thread is served first: it is this conversation's own lost detail."""
    return min(THREAD_MAX, recall_budget(num_ctx))


def documents_budget(num_ctx, thread_text=""):
    """What the thread left, 0 when it is too little to say anything."""
    left = min(DOCUMENTS_MAX, recall_budget(num_ctx) - len(thread_text or ""))
    return left if left >= RECALL_MIN else 0


def turn_block(sheet="", extracts="", recalls=""):
    """The pair of messages that carries what follows the request: [] when there is nothing. The acknowledgement keeps the roles alternating."""
    parts = [x.strip() for x in (sheet, extracts, recalls) if x and x.strip()]
    if not parts:
        return []
    return [{"role": "user", "content": "\n\n".join(parts), KEPT: True},
            {"role": "assistant", "content": "Compris, je m'appuie sur " + ("cette fiche." if sheet else "ces extraits."), KEPT: True}]


def before_last_question(history, block):
    """`history` with `block` placed just before the last message of the user: everything above it is the same from one step to the next, and from one
    question to the next up to the previous question. Unchanged when there is no question or no block."""
    last = max((i for i, m in enumerate(history) if m.get("role") == "user"), default=-1)
    if not block or last < 0:
        return history
    return history[:last] + block + history[last:]


def attach_tail(messages, text):
    """Marks the last message so that `text` is written at its end when the request is final (`merge_tail`). The message is copied: the conversation is
    never changed. The text goes on a message of the user or a tool result, never on a message of its own; with neither, nothing is attached."""
    if not text:
        return messages
    for i in reversed(range(len(messages))):
        if messages[i].get("role") in ("user", "tool"):
            return messages[:i] + [dict(messages[i], **{TAIL: text})] + messages[i + 1:]
    return messages


def merge_tail(message):
    """Writes the tail of a message at its end and removes the private keys: what the engine receives. In place, on a copy made by the caller."""
    tail = message.pop(TAIL, None)
    message.pop(KEPT, None)
    if tail:
        message["content"] = (message.get("content") or "") + tail
    return message
