"""Where each piece of context goes in a request to the model (ADR 0013).

An engine keeps what it has already read: a request that starts like the previous one only costs what follows the common start. So a request has

- a prefix that stays: the system message, with nothing in it that follows the request;
- what follows the request, read once for the turn, in one pair of messages just before the last question (`turn_block`, `before_last_question`):
  the progress sheet, the extracts of the thread, the recalls drawn from the documents;
- what changes inside a turn, written at the end of the last message (`attach_tail`): the task list.

The loop (`agent._messages_de_l_etape`) assembles; this module says where things go and how much room recalls and tool results may take.
"""
import json

CHARS_PER_TOKEN = 3          # the estimate used everywhere in Lutin
RECALL_SHARE = 0.10          # of the window, for the extracts of the thread and the recalls of the documents together
THREAD_MAX = 1800            # characters of passages: the ceiling of the extracts of the thread
DOCUMENTS_MAX = 2200         # and of the recalls drawn from the documents
RECALL_MIN = 300             # below this, a recall is a title and half a sentence: none is better
RESULT_SHARE = 0.10          # of the window, for one tool result (ADR 0019, decision 5)
RESULT_WRAPPER = 120         # characters of the message around a result (role, tool name) and of the rounding of the estimate
RESULT_MIN = 600             # characters: below this, a result says nothing useful

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


def result_budget(num_ctx, ceiling):
    """Characters one tool result may take in a window of `num_ctx` tokens: about a tenth of the window, never more than `ceiling` (the limit the tools
    had before the window counted, so a large window is unchanged) nor less than RESULT_MIN. Counted on the JSON form of the text, as the estimate does:
    a tool message of this size weighs at most RESULT_SHARE of the window."""
    return max(RESULT_MIN, min(int(ceiling), int(num_ctx * RESULT_SHARE) * CHARS_PER_TOKEN - RESULT_WRAPPER))


def json_length(text):
    """The length of `text` in a request: its JSON form, escapes included, without the quotes."""
    return len(json.dumps(text, ensure_ascii=False)) - 2


def cut_middle(text, budget, header):
    """`text` unchanged when it fits `budget` characters (JSON form); otherwise `header(cut)` (`cut`: the number of characters taken out), then the
    start and the end of `text`: the end of an output often carries its conclusion (an error, a total), its start what it is. Returns (text, cut)."""
    if json_length(text) <= budget:
        return text, False
    ratio = len(text) / max(1, json_length(text))
    room = int((budget - json_length(header(len(text))) - 20) * ratio)
    while room > 0:
        head, tail = room * 3 // 5, room - room * 3 // 5
        cut = header(len(text) - room) + text[:head] + "\n[…]\n" + (text[-tail:] if tail else "")
        if json_length(cut) <= budget:
            return cut, True
        room -= max(10, room // 20)
    return header(len(text))[:budget], True


def mask_old_results(history, line):
    """`history` with the tool results of the finished turns (before the last message of the user) replaced by one line each, in one batch: the request
    changes once, at the start of the next turn, not at every answer. `line(name, args, size)` writes the line; `args` come from the call of the
    assistant that asked for the result (paired in order). Messages are copied; a short result is kept as it is."""
    last = max((i for i, m in enumerate(history) if m.get("role") == "user"), default=-1)
    out, calls = [], []
    for i, m in enumerate(history):
        if m.get("role") == "assistant":
            calls = [c.get("function") or {} for c in (m.get("tool_calls") or [])]
        elif m.get("role") == "tool" and i < last:
            call = calls.pop(0) if calls else {}
            content = str(m.get("content") or "")
            args = call.get("arguments")
            short = line(m.get("tool_name") or call.get("name") or "", args if isinstance(args, dict) else {}, len(content))
            if len(content) > len(short):
                m = dict(m, content=short)
        out.append(m)
    return out


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
