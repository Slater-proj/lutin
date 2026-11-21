"""Read-only commands the agent may run without asking the user (see docs/adr/0006-approval-free-commands.md).

A command is "safe" only when a validator written for its program recognises every argument. A safe command never goes through a shell:
it is either answered by Lutin itself (`echo`, and on Windows `dir` and `type`, which are cmd.exe built-ins) or started directly from an argument list.
Whatever the validators do not recognise returns None: the caller then follows the normal path (the user is asked, then the command runs in the shell).

Why not a regular expression over the command line, as before: a shell rewrites the line after the check. `type %USERPROFILE%\\x`, `echo $(...)`,
a newline followed by a second command, or `git branch -D main` all matched the former whitelist. Without a shell there is nothing left to rewrite.

This module knows nothing about Lutin's state: the caller gives the confinement function (`confine`), which says whether a path stays inside the workspace.
"""
from __future__ import annotations

import glob
import re
import shlex
import shutil
from dataclasses import dataclass

RUN, ECHO, LIST, READ = "run", "echo", "list", "read"


@dataclass(frozen=True)
class Plan:
    """How a safe command is carried out: `run` starts `argv` without a shell; `echo` returns `text`; `list` and `read` use Lutin's own tools on `paths`."""
    kind: str
    argv: tuple = ()
    text: str = ""
    paths: tuple = ()


# Refused in every approval-free command, whatever the program: control characters (for sh, a newline starts a second command),
# chaining and redirection, command substitution and variable expansion.
_NEVER = re.compile(r"[\x00-\x08\x0a-\x1f\x7f|&;<>`$]")
# `echo` is answered by Lutin: refused when a shell would have changed the text (variables, escapes, wildcards, braces, home, sub-shell, comment).
_ECHO_CMD = re.compile(r"[%^!]")
_ECHO_SH = re.compile(r"[*?\[\]{}~\\()!#]")
# A file or folder name as the simple readers accept it: letters of any alphabet, digits, and a few harmless signs. Wildcards are handled apart.
_NAME = re.compile(r"^[\w .,+@=\-\\/]+$")
_WILDCARD = re.compile(r"[*?]")
# Arguments of a command the user declared safe (Settings > Tools), and of a program that is in fact a .bat/.cmd script: nothing cmd.exe could interpret.
_SIMPLE = re.compile(r"^[A-Za-z0-9_./:=\-\\]+$")
_SHORT_OPTIONS = re.compile(r"^-[A-Za-z0-9]+$")
_LONG_OPTION = re.compile(r"^--[a-z][a-z0-9-]*(=[\w.,:+-]*)?$")
_PROGRAM_NAME = re.compile(r"^[\w.+\-]+$")
_PROGRAM_PATTERN = re.compile(r"^[\w.+\-*?]+$")          # `where` accepts wildcards itself

_OUTSIDE = re.compile(
    r"[A-Za-z]:[\\/]"                         # a drive: C:\ or D:/
    r"|^[\\/]|(?<=[=:])[\\/]"                 # an absolute path (or the root of the current drive), bare or after « = » or « : »
    r"|^~|(?<=[=:])~"                         # the home folder
    r"|(?:^|[\\/=:])\.\.(?:[\\/]|$)"          # the parent folder as a path segment (not the « a..b » of a git range)
    r"|^-[A-Za-z]{1,2}[\\/~]"                 # a path glued to a short option: -O/etc/x
)


def leaves_workspace(token):
    """True if the argument names something outside the workspace (drive, absolute path, home, parent folder, network share)."""
    return bool(_OUTSIDE.search(token))


def split(command, posix):
    """The arguments of a command line, or None if it cannot be read without guessing (unbalanced quotes).
    POSIX: the rules of sh (quotes, backslash). Windows: spaces separate, double quotes group, the backslash is a path separator and nothing else."""
    if posix:
        try:
            return shlex.split(command)
        except ValueError:
            return None
    tokens, current, quoted, started = [], "", False, False
    for char in command:
        if char == '"':
            quoted, started = not quoted, True
        elif char in " \t" and not quoted:
            if started:
                tokens.append(current)
            current, started = "", False
        else:
            current, started = current + char, True
    if quoted:
        return None
    if started:
        tokens.append(current)
    return tokens


# ---- git: reading sub-commands only ----
GIT_READ = ("status", "diff", "log", "show", "branch", "ls-files")
# --output writes a file, --no-index compares any two paths of the disk, --ext-diff starts a configured program, --help opens a browser or a pager.
_GIT_REFUSED = ("--output", "--no-index", "--ext-diff", "--help")
# No « -l »: it means --list today, but « create the reflog » for a git older than 2.20, where a name after it creates a branch.
_BRANCH_FLAGS = re.compile(r"^(-[arv]+|--all|--remotes|--verbose|--list|--show-current|--no-color|--no-column|--no-abbrev|--ignore-case)$")
_BRANCH_VALUED = ("--contains", "--no-contains", "--merged", "--no-merged", "--points-at", "--sort", "--format", "--color", "--column", "--abbrev")
_BRANCH_LISTING = ("--list", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at")


def _git_branch(args):
    """`git branch` only lists: creating, renaming, moving or deleting a branch changes the repository and must be approved.
    A bare name creates a branch unless a listing option says the name is a pattern."""
    listing = False
    for arg in args:
        if arg.startswith("-"):
            name = arg.split("=", 1)[0]
            if not (_BRANCH_FLAGS.match(arg) or name in _BRANCH_VALUED):
                return False
            listing = listing or name in _BRANCH_LISTING
    return listing or all(arg.startswith("-") for arg in args)


def _git(args):
    if not args or args[0] not in GIT_READ:
        return None
    rest = args[1:]
    if any(arg.startswith(_GIT_REFUSED) or leaves_workspace(arg) for arg in rest):
        return None
    if args[0] == "branch" and not _git_branch(rest):
        return None
    return ["git"] + args


# ---- simple readers ----
def _paths(tokens, confine, root, options=_SHORT_OPTIONS, expand=True):
    """Checks the arguments of a reader (ls, cat): options are passed through, every other argument must be a name inside the workspace.
    Returns (arguments to give the program, paths found), or None. Wildcards are expanded here, since no shell will do it."""
    out, found = [], []
    for token in tokens:
        if token.startswith("-"):
            if options is None or not (options.match(token) or _LONG_OPTION.match(token)):
                return None
            out.append(token)
            continue
        if not _NAME.match(_WILDCARD.sub("", token) or ".") or leaves_workspace(token):
            return None
        matches = [token]
        if _WILDCARD.search(token):
            if not expand:
                return None
            matches = sorted(glob.glob(token, root_dir=str(root))) or [token]          # like sh: a pattern that matches nothing stays as written
        for match in matches:
            if confine(match) is None:
                return None
            out.append(match)
            found.append(match)
    return out, found


def _user_command(command, tokens, extra):
    """A command the user declared safe: exactly as written, or followed by simple arguments that stay inside the workspace."""
    for declared in extra:
        base = declared.split()
        if base and tokens[:len(base)] == base and all(_SIMPLE.match(arg) and not leaves_workspace(arg) for arg in tokens[len(base):]):
            return list(tokens)
    return None


def _echo(command, args, posix):
    if command[:4].lower() != "echo":
        return None
    if posix:
        return None if _ECHO_SH.search(command) else Plan(ECHO, text=" ".join(args))
    text = command[4:].strip()                            # cmd.exe prints the text as written, quotes included
    return None if _ECHO_CMD.search(text) else Plan(ECHO, text=text)


def plan(command, *, posix, confine, root=".", extra=(), which=shutil.which):
    """The way to carry out `command` without approval and without a shell, or None if it is not a safe read.

    `confine(path)` returns the resolved path when it stays inside the workspace (and outside Lutin's own data), None otherwise.
    `extra`: the commands the user declared safe (already validated by reglages_outils.commande_valide)."""
    command = str(command or "").strip()
    if not command or _NEVER.search(command):
        return None
    tokens = split(command, posix)
    if not tokens:
        return None
    program, args = (tokens[0] if posix else tokens[0].lower()), tokens[1:]
    argv = None
    if program == "echo":
        return _echo(command, args, posix)
    if program == "git":
        argv = _git(args)
    elif program == "python" and args == ["-V"]:
        argv = ["python", "-V"]
    elif posix:
        if program == "ls":
            checked = _paths(args, confine, root)
            argv = ["ls"] + checked[0] if checked else None
        elif program == "cat":
            checked = _paths(args, confine, root)
            argv = ["cat"] + checked[0] if checked and checked[1] else None
        elif program == "pwd":
            argv = ["pwd"] if not args else None
        elif program == "which":
            argv = ["which"] + args if args and all(a == "-a" or _PROGRAM_NAME.match(a) for a in args) else None
    else:
        if program == "dir":
            names = [a for a in args if a.lower() != "/b"]          # /b (names only) is the one option kept: Lutin's listing is already bare
            checked = _paths(names, confine, root, options=None, expand=False) if len(names) <= 1 else None
            if checked is not None:
                return Plan(LIST, paths=tuple(checked[1] or ["."]))
        elif program == "type":
            checked = _paths(args, confine, root, options=None)
            if checked and checked[1]:
                return Plan(READ, paths=tuple(checked[1]))
        elif program == "where":
            argv = ["where"] + args if args and all(_PROGRAM_PATTERN.match(a) for a in args) else None
    if argv is None:
        argv = _user_command(command, tokens, extra)
    if argv is None:
        return None
    resolved = which(argv[0]) or ""
    if resolved.lower().endswith((".bat", ".cmd")) and not all(_SIMPLE.match(arg) for arg in argv[1:]):
        return None                                       # Windows runs a script through cmd.exe, which would interpret the arguments
    return Plan(RUN, argv=tuple(argv))
