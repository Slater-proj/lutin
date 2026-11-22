"""Approval rules for commands (plan step 5, item 5): what decides, before a command is run, whether Lutin refuses it, asks, or runs it without asking.

Precedence: **deny > ask > allow**. Four sources, from the strongest:

1. the hardline list (`HARDLINE`): commands that destroy or take over a machine. Never run without a question, whatever the rules and the automatic approvals say,
   and the answer to that question cannot be remembered;
2. the rules of the person (`approval_rules.json` in the data folder): `deny`, `ask` or `allow`, written from the Settings screen or by answering « always »;
3. the rules of the project (`.lutin/approvals.json` in the working folder): they can only `ask` or `deny`. A file of the working folder can be written by the model
   or come with a cloned repository: it must never be able to grant itself anything;
4. the answers « for this conversation »: kept in memory, gone when Lutin stops.

A rule names a command exactly, or a beginning followed by ` *` (`git push *`). Commands are compared after their spaces are normalised, without case on Windows.
The automatic approval of a conversation and the read-only commands recognised by `safe_commands` stay what they are: a rule only adds to them (`allow`) or
overrides them (`ask`, `deny`)."""
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from . import core as _m
from . import storage as _storage
from .i18n import t as _t

FILE = "approval_rules.json"
PROJECT_FILE = Path(".lutin") / "approvals.json"
EFFECTS = ("deny", "ask", "allow")
MAX_RULES = 200
MAX_COMMAND = 300

# What no rule and no automatic approval lets through without a question. Each entry: (pattern, what it is, said to the person).
HARDLINE = (
    (r"\brm\s+(?=(?:-\S+\s+)*-[a-z-]*r)(?=(?:-\S+\s+)*-[a-z-]*f)", "deletes folders without asking"),          # -rf, -fr, -r -f, --recursive --force
    (r"\b(?:del|erase)\b[^|&]*\s/[sq]\b", "deletes files in every sub-folder"),
    (r"\b(?:rd|rmdir)\b[^|&]*\s/s\b", "deletes a folder and everything in it"),
    (r"\bremove-item\b[^|;]*-recurse\b", "deletes a folder and everything in it"),
    (r"\bformat\s+[a-z]:", "formats a disk"),
    (r"\bmkfs(?:\.\w+)?\b", "formats a disk"),
    (r"\bdiskpart\b", "changes the partitions of a disk"),
    (r"\bdd\b[^|&]*\bof=", "writes straight to a disk or a file"),
    (r"\b(?:shutdown|reboot|halt|poweroff)\b", "stops or restarts the machine"),
    (r"\breg(?:\.exe)?\s+(?:delete|add|import)\b", "changes the Windows registry"),
    (r"\b(?:curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)\b[^|]*\|\s*(?:sh|bash|zsh|iex|invoke-expression|powershell|pwsh|python\d?)\b", "runs a program downloaded from the internet"),
    (r"\s-(?:e|ec|enc|encodedcommand)\s+[A-Za-z0-9+/=]{20,}", "runs a hidden (encoded) PowerShell command"),
    (r"\bgit\s+push\b[^|&]*(?:--force\b|--force-with-lease\b|\s-f\b)", "overwrites the history of a remote repository"),
    (r"\bgit\s+(?:reset\s+--hard|clean\s+-[a-z]*f)", "throws away work that is not committed"),
    (r"\b(?:chmod|chown)\s+-[a-z]*r[a-z]*\s", "changes the rights of a whole tree"),
    (r":\(\)\s*\{", "a fork bomb"),
    (r"\b(?:net\s+user|useradd|usermod|passwd)\b", "changes the accounts of the machine"),
    (r">\s*/dev/(?:sd|nvme|disk)", "writes straight to a disk"),
)
_HARDLINE = tuple((re.compile(pattern, re.I), reason) for pattern, reason in HARDLINE)

_LOCK = threading.Lock()
_CHAT = {}          # conversation id -> set of normalised commands allowed for this conversation


def normalise(command):
    text = " ".join(str(command or "").split())
    return text.lower() if os.name == "nt" else text


def hardline(command):
    """Why this command is on the hardline list, or '' when it is not. Looked for in the whole text: a dangerous part hidden after `&&` counts."""
    text = " ".join(str(command or "").split())
    for pattern, reason in _HARDLINE:
        if pattern.search(text):
            return reason
    return ""


def _path():
    return _m.DATA / FILE


def _valid(rule, effects=EFFECTS):
    return isinstance(rule, dict) and rule.get("effect") in effects and isinstance(rule.get("command"), str) and 0 < len(rule["command"]) <= MAX_COMMAND


def user_rules():
    stored = _storage.read_json(_path(), [])
    return [rule for rule in stored if _valid(rule) and rule.get("id")] if isinstance(stored, list) else []


def project_rules(root):
    """The rules of the working folder. An `allow` there is ignored: the folder cannot grant itself anything. A file that cannot be read gives no rule."""
    try:
        file = Path(root) / PROJECT_FILE
        if not file.is_file() or file.stat().st_size > 200_000:
            return []
        stored = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rules = stored.get("rules") if isinstance(stored, dict) else stored
    return [rule for rule in rules if _valid(rule, ("deny", "ask"))][:MAX_RULES] if isinstance(rules, list) else []


def matches(rule_command, command):
    """A rule names the command exactly, or its beginning followed by ` *`."""
    wanted, given = normalise(rule_command), normalise(command)
    if wanted.endswith(" *"):
        prefix = wanted[:-2]
        return given == prefix or given.startswith(prefix + " ")
    return wanted == given


def decide(command, conversation="", root=None):
    """(effect, reason): `hardline`, `deny`, `ask`, `allow`, or `none` when no rule speaks (the caller then does what it did before the rules existed)."""
    reason = hardline(command)
    if reason:
        return "hardline", reason
    found = {}
    for source, rules in (("yours", user_rules()), ("project", project_rules(root) if root else [])):
        for rule in rules:
            if matches(rule["command"], command):
                found.setdefault(rule["effect"], source)
    for effect in ("deny", "ask"):
        if effect in found:
            return effect, found[effect]
    if "allow" in found or normalise(command) in _CHAT.get(conversation, ()):
        return "allow", found.get("allow", "chat")
    return "none", ""


def add(effect, command):
    """A rule of the person. An `allow` for a command of the hardline list is refused: it would promise what the list forbids."""
    command = " ".join(str(command or "").split())
    if effect not in EFFECTS or not command or len(command) > MAX_COMMAND:
        raise ValueError(_t("Règle invalide : un effet (deny, ask, allow) et une commande de {} caractères au plus.").format(MAX_COMMAND))
    if effect == "allow" and (hardline(command) or command.strip() in ("*", "")):
        raise ValueError(_t("Cette commande fait partie de celles qui demandent toujours ton accord : aucune règle ne peut l'autoriser d'avance."))
    with _LOCK:
        rules = user_rules()
        for rule in rules:
            if rule["effect"] == effect and normalise(rule["command"]) == normalise(command):
                return rule
        if len(rules) >= MAX_RULES:
            raise ValueError(_t("Déjà {} règles : supprime-en d'abord.").format(MAX_RULES))
        rule = {"id": secrets.token_hex(4), "effect": effect, "command": command, "created": int(time.time())}
        _storage.write_atomic(_path(), json.dumps(rules + [rule], ensure_ascii=False, indent=1))
        return rule


def remove(identifier):
    with _LOCK:
        rules = user_rules()
        kept = [rule for rule in rules if rule["id"] != identifier]
        if len(kept) == len(rules):
            return False
        _storage.write_atomic(_path(), json.dumps(kept, ensure_ascii=False, indent=1))
        return True


def remember(command, scope, conversation=""):
    """Keeps the « yes » given to a command: `chat` for the rest of this conversation, `always` as a rule of the person. Nothing is kept for a hardline command."""
    if hardline(command):
        return False
    if scope == "always":
        add("allow", command)
        return True
    if scope == "chat" and conversation:
        with _LOCK:
            _CHAT.setdefault(conversation, set()).add(normalise(command))
        return True
    return False


def forget_conversation(conversation):
    with _LOCK:
        _CHAT.pop(conversation, None)
