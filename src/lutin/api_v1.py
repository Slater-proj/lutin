"""`/api/v1`: the versioned English API (docs/modernization/API_V1.md).

A second door to the same state: a route translates names at the boundary and calls the functions the French routes call. Three rules are applied here,
once, for every route:

- the right a route asks is DECLARED in the table and checked by the dispatcher before the handler runs (never inside the handler);
- an error always carries a code for programs and a message for people: {"error": {"code": "...", "message": "..."}};
- a status code means one thing (401 no session, 403 a session without the right, 404 unknown, 405 wrong method, 409 conflict with a running turn).

The request handler of `lutin.server` owns the connection and the security checks (Host, Origin, session, page token): this module asks it, it never
re-implements them. A machine leading a conversation through the relay cannot reach these routes: the relay only lets a closed list of French routes through.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import threading
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from . import core as _m
from . import engines as _engines
from . import engine_updates as _engine_updates
from . import hardware as _hardware
from . import health as _health
from . import approval_rules as _approval_rules
from . import attachments as _pieces
from . import claude_project as _claude_project
from . import github as _github
from . import i18n as _i18n
from . import images as _images
from . import machines as _machines
from . import mission as _mission
from . import model_compat as _model_compat
from . import model_fit as _model_fit
from . import offline as _offline
from . import power as _power
from . import produced_files as _produced
from . import addons as _addons
from . import mcp as _mcp
from . import mcp_catalog as _mcp_catalog
from . import notifications as _notifications
from . import scheduled_tasks as _scheduled_tasks
from . import security as _sec
from . import storage as _storage
from . import third_party_skills as _skills
from . import turn_state as _turn_state
from . import workspaces as _workspaces
from .i18n import t as _t

PREFIX = "/api/v1"
PUBLIC, SESSION, CONFIGURATOR, LOCAL, READ = "public", "session", "configurator", "local", "read"
# READ: a session is enough, the page token is not asked. Only for a GET that gives back what a browser tag fetches (an <img> sends the cookie, never a header).
RIGHTS = (PUBLIC, SESSION, CONFIGURATOR, LOCAL, READ)
WITH_BODY = ("POST", "PATCH", "PUT")
BODY_MAX = 2_000_000
DISCARD_MAX = 64 * 1024 * 1024                        # what is read and thrown away before a refusal (the bound of lutin.server for the same purpose)
ACCESS_LEVELS = {_sec.LOCAL: "local", _sec.RESEAU: "network", _sec.PROXY: "proxy"}
ROUTES = []


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class Route:
    method: str
    template: str
    right: str
    handler: object
    pattern: object
    raw: bool = False                                 # the body is a file, not JSON: the route reads `Request.raw`, bounded by `limit`
    limit: int = 0


@dataclass(frozen=True)
class Streamed:
    """What a route returns when the answer is written line by line (the turn stream): `write` is called once the checks of the route have passed."""
    write: object


@dataclass(frozen=True)
class Binary:
    """What a route returns when the answer is a file (an image): bytes and their content type."""
    data: bytes
    content_type: str
    headers: dict = field(default_factory=dict)


@dataclass
class Request:
    handler: object                                   # the HTTP request handler (lutin.server.Gestionnaire)
    params: dict = field(default_factory=dict)        # the {names} of the route template
    query: dict = field(default_factory=dict)
    body: dict = field(default_factory=dict)
    raw: bytes = b""


def route(method, template, right, raw=False, limit=0):
    """Declares a route: `@route("GET", "/conversations/{id}", SESSION)`. A {name} matches one path segment.
    `raw=True, limit=N`: the body is a file of at most N bytes (an upload), given to the handler as `Request.raw`."""
    assert right in RIGHTS and template.startswith("/")
    assert right != READ or method == "GET", "a right that skips the page token is for reading only"
    assert not raw or (method == "POST" and limit > 0)

    def register(function):
        pattern = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template) + "$")
        ROUTES.append(Route(method, template, right, function, pattern, raw, limit))
        return function
    return register


def table():
    """The contract in one list: [{method, path, right}], sorted. Compared with tests/fixtures/api_v1_routes.json by the tests."""
    return sorted(({"method": r.method, "path": PREFIX + r.template, "right": r.right} for r in ROUTES), key=lambda r: (r["path"], r["method"]))


def error(code, message):
    return {"error": {"code": code, "message": message}}


def refuse(handler, status, code, message):
    """A refusal decided before the dispatcher (host name, origin: lutin.server), in the shape of this API and with the body read."""
    discard_body(handler)
    return handler._envoyer(status, error(code, message))


def _check_right(handler, right):
    if right == PUBLIC:
        return
    if not handler._authentifie():
        raise ApiError(401, "no_session", _t("Connexion requise."))
    if right == READ:
        return
    if not handler._jeton_valide():
        raise ApiError(403, "page_token", _t("Jeton de page invalide : recharge la page."))
    if right == CONFIGURATOR and not handler._configurateur():
        raise ApiError(403, "configurator", _t("Réservé à qui peut configurer Lutin (cette machine, ou l'administration à distance si elle est ouverte)."))
    if right == LOCAL and not handler._configurateur_strict():
        raise ApiError(403, "local_only", _t("Possible seulement depuis cette machine."))


def discard_body(handler):
    """Reads and throws away a body that will not be used: answering with it unread makes the caller's connection reset, and the answer is lost.
    Bounded: beyond DISCARD_MAX (or with a length that is not a number) nothing is read, since no one may make this server read without end; the
    connection is then closed after the answer."""
    left = handler._taille_corps()
    if left > DISCARD_MAX:
        handler.close_connection = True
        return
    while left > 0:
        chunk = handler.rfile.read(min(left, 65536))
        if not chunk:
            break
        left -= len(chunk)


def _read_body(handler):
    """The JSON object of the request. Read before any refusal: a request refused with its body unread makes the caller's connection reset."""
    size = handler._taille_corps()
    if size > BODY_MAX:
        discard_body(handler)
        raise ApiError(413, "too_large", _t("Requête trop volumineuse."))
    raw = handler.rfile.read(size) if size > 0 else b""
    try:
        body = json.loads(raw or b"{}")
    except (ValueError, RecursionError):
        body = None
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_json", _t("Le corps de la requête doit être un objet JSON."))
    return body


def _read_raw(handler, limit):
    """The bytes of an upload, read before any refusal like a JSON body: over the limit, the body is thrown away (bounded) and the answer is 413."""
    size = handler._taille_corps()
    if size > limit:
        discard_body(handler)
        raise ApiError(413, "too_large", _t("Requête trop volumineuse."))
    return handler.rfile.read(size) if size > 0 else b""


def dispatch(handler, method):
    """Answers a request whose path starts with /api/v1/. The caller has already checked Host and Origin."""
    parts = urllib.parse.urlsplit(handler.path)
    path = parts.path[len(PREFIX):] or "/"
    streamed = binary = None
    try:
        matching = [(r, m) for r in ROUTES for m in [r.pattern.match(path)] if m]
        found = next(((r, m) for r, m in matching if r.method == method), None)
        raw = b""
        if found is not None and found[0].raw:
            body = {}
            raw = _read_raw(handler, found[0].limit)
        elif method in WITH_BODY:
            body = _read_body(handler)
        else:
            body = {}
            discard_body(handler)                         # a GET or a DELETE sent with a body: not used, but read
        if found is None:
            _check_right(handler, SESSION)                 # an unknown address tells nothing to a caller without a session
            if matching:
                raise ApiError(405, "method_not_allowed", _t("Méthode non permise pour cette route."))
            raise ApiError(404, "not_found", _t("Route inconnue."))
        entry, match = found
        _check_right(handler, entry.right)
        query = {k: v[-1] for k, v in urllib.parse.parse_qs(parts.query).items()}
        result = entry.handler(Request(handler, {k: urllib.parse.unquote(v) for k, v in match.groupdict().items()}, query, body, raw))
        if isinstance(result, Streamed):
            streamed = result
        elif isinstance(result, Binary):
            binary = result
        else:
            status, payload = result if isinstance(result, tuple) else (200, result)
    except ApiError as refused:
        status, payload = refused.status, error(refused.code, refused.message)
    except _offline.OfflineError as offline:                  # strict offline mode: the action needs the network
        status, payload = 409, error("offline", str(offline))
    except ValueError as invalid:                          # the functions underneath say what is wrong with a ValueError written for the user
        status, payload = 400, error("invalid_request", str(invalid))
    if binary is not None:
        return handler._envoyer(200, binary.data, binary.content_type, binary.headers)
    if streamed is not None:                               # outside the `try`: once the first line is sent, no error answer can follow it
        return streamed.write()
    return handler._envoyer(status, payload)


# ---------------------------------------------------------------------------------------------------------------- status
@route("GET", "/status", SESSION)
def status(request):
    """What the page needs to draw itself: who is asking, which engine and model answer, what is running. Deliberately small: each area has its own routes."""
    settings = _m.reglages()
    engine = _m.moteur_actuel(settings)
    state = _m.etat_moteur()
    from . import access as _access
    return {
        "version": _m.VERSION,
        "new_version": _new_version(),          # a newer Lutin announced by the launch check, for the banner (null: none, or ignored)
        "restart": {"needed": bool(_access.restart_needed()), "possible": bool(_access.can_restart())},          # a change waits for the next start
        "language": _i18n.langue(),
        "access": {"level": ACCESS_LEVELS.get(_m.SECURITE.niveau, _m.SECURITE.niveau), "can_configure": bool(request.handler._configurateur())},
        "offline": bool(_offline.is_active()),
        "engine": {"id": engine.id, "name": engine.nom, "running": bool(state["actif"])},
        "model": str(settings.get("modele") or ""),
        "installed_models": list(state["installes"]),
        "workspace": {"path": str(_m.RACINE)},
        "can_open_files": bool(request.handler._configurateur() and _produced.opening_possible()),          # « Open » asks this machine's system to open a file
        "active_turns": sorted(_m.TOURS_ACTIFS),
        "turns": _turn_state.snapshot(),          # where each running turn is: running, waiting_approval, stalled or cancelled, and in which part of the loop (turn_state.py)
        "pending_approvals": sorted({a.conv for a in _m.Attente.EN_COURS.values() if a.conv} | set(_m.CHOIX_MEMOIRE)),
    }


# -------------------------------------------------------------------------------------------------------------- settings
# The settings (defaults of new conversations, and settings of this machine) under their v1 names: {v1 name: (stored key, kind)}. A kind ending with
# "?" also accepts null, which means « automatic ». The names of engine parameters (num_ctx, top_p…) are kept: they are the engines' own names.
# tests/test_api_v1_settings.py compares this table with lutin.core.REGLAGES_DEFAUT: a setting added without a v1 name fails a test.
SETTINGS = {
    "model": ("modele", "string"), "engine": ("moteur", "string"), "machine": ("machine", "string"), "models_by_engine": ("modeles_par_moteur", "object"),
    "auxiliary_model": ("modele_annexe", "string"), "embedding_model": ("modele_embeddings", "string"),
    "mode": ("mode", "string"), "advanced": ("avance", "boolean"), "web": ("web", "boolean"), "dry_run": ("essai_a_blanc", "boolean"),
    "thinking": ("reflexion", "boolean"), "thinking_steps": ("reflexion_tours", "string"), "max_steps": ("tours_max", "integer"),
    "auto_approve_writes": ("auto_ecriture", "boolean"), "auto_approve_commands": ("auto_commandes", "boolean"),
    "num_ctx": ("num_ctx", "integer"), "num_predict": ("num_predict", "integer"), "temperature": ("temperature", "number"), "top_p": ("top_p", "number?"),
    "top_k": ("top_k", "number?"), "min_p": ("min_p", "number?"), "repeat_penalty": ("repeat_penalty", "number?"), "num_thread": ("num_thread", "integer?"),
    "keep_alive_min": ("garde_min", "integer?"),
    "resource_guard": ("garde_ressources", "boolean"), "ram_threshold_gb": ("seuil_ram_go", "number"), "disk_threshold_gb": ("seuil_disque_go", "number"),
    "data_cap_gb": ("plafond_donnees_go", "number"), "memory_budget_gb": ("budget_go", "number"), "command_ram_limit_gb": ("limite_ram_commande_go", "number"), "free_for_comfyui": ("liberer_si_comfy", "boolean"),
    "machine_advice": ("conseil_machine", "boolean"), "routing": ("routage", "boolean"), "cluster": ("cluster", "boolean?"),
    "conversation_backup": ("copie_conversations", "boolean"),
    "long_memory": ("memoire_longue", "string"), "progress_sheet_share": ("fiche_part", "integer"), "progress_sheet_scribe": ("fiche_scribe", "boolean"),
    "auto_recall": ("rappels_auto", "string"), "semantic_search": ("recherche_sens", "boolean"),
    "disabled_tools": ("outils_desactives", "strings"), "tool_command_timeout_s": ("outil_delai_commande_s", "integer"), "tool_output_max": ("outil_sortie_max", "integer"),
    "tool_read_max": ("outil_lecture_max", "integer"), "tool_search_timeout_s": ("outil_chercher_delai_s", "integer"),
    "commands_without_approval": ("commandes_sans_accord", "strings"), "extra_ignored_folders": ("dossiers_ignores_en_plus", "strings"),
}
# Settings whose value is a word: {v1 name: {stored word: v1 word}}. Tool names (disabled_tools) are what the models see: not translated (ADR 0007).
SETTING_WORDS = {
    "mode": {"polyvalent": "general", "technique": "technical", "scenario": "scenario", "recherche": "research", "discussion": "chat"},
    "thinking_steps": {"toujours": "always", "premier": "first"},
    "long_memory": {"resume": "summary", "fichier": "file", "demander": "ask"},
    "auto_recall": {"scenario": "scenario", "toujours": "always", "jamais": "never"},
}
KINDS = {"boolean": lambda v: isinstance(v, bool), "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
         "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool), "string": lambda v: isinstance(v, str),
         "strings": lambda v: isinstance(v, list) and all(isinstance(item, str) for item in v),
         "object": lambda v: isinstance(v, dict) and all(isinstance(item, str) for item in v.values())}


def _settings(stored):
    shown = {}
    for name, (key, _) in SETTINGS.items():
        value = stored.get(key)
        shown[name] = SETTING_WORDS[name].get(value, value) if name in SETTING_WORDS else value
    return shown


@route("GET", "/language", SESSION)
def language(request):
    """The language of the page and of the messages: `language` is the one in use, `choice` what was chosen (`fr`, `en`, or `auto` to follow the system)."""
    return {"language": _i18n.langue(), "choice": _i18n.langue_configuree() or "auto"}


@route("PATCH", "/language", SESSION)
def set_language(request):
    """{"language": "fr" | "en" | "auto"}. The pages read the language when they load: the caller loads the page again."""
    value = request.body.get("language")
    if value not in ("fr", "en", "auto"):
        raise ApiError(400, "invalid_request", _t("Langue inconnue (fr, en ou auto)."))
    _i18n.definir(value)
    return {"language": _i18n.langue(), "choice": _i18n.langue_configuree() or "auto"}


@route("GET", "/settings", SESSION)
def settings(request):
    return _settings(_m.reglages())


@route("PATCH", "/settings", SESSION)
def update_settings(request):
    """Changes some settings: {"temperature": 0.4, "web": false}. All or nothing: one unknown name or one value of the wrong kind and nothing is written.
    The values are then checked and bounded by the function the French route calls; the answer is every setting as it now stands."""
    body, changed = request.body, {}
    unknown = sorted(set(body) - set(SETTINGS))
    if unknown:
        raise ApiError(400, "invalid_request", _t("Réglage inconnu : {}.").format(", ".join(unknown)))
    if not body:
        return _settings(_m.reglages())
    for name, value in body.items():
        key, kind = SETTINGS[name]
        words = {v1: stored for stored, v1 in SETTING_WORDS.get(name, {}).items()}
        expected = ", ".join(words) if words else kind.rstrip("?") + (" or null" if kind.endswith("?") else "")
        if not ((value is None and kind.endswith("?")) or (value is not None and KINDS[kind.rstrip("?")](value))) or (words and value not in words):
            raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format(name, expected))
        changed[key] = words[value] if words else value
    stored = _m.enregistrer_reglages(changed)
    if changed.get("cluster") is False:
        _machines.vider_listes()                           # multi-machine mode switched off: no model and no conversation of another machine is kept
    return _settings(stored)


# ---------------------------------------------------------------------------------------------------------------- models
DOWNLOAD_STATES = {"en cours": "downloading", "termine": "done", "erreur": "failed"}


def _download(name, stored):
    return {"name": name, "state": DOWNLOAD_STATES.get(stored.get("statut"), "failed"), "done_bytes": int(stored.get("fait") or 0), "total_bytes": int(stored.get("total") or 0),
            "text": str(stored.get("texte") or ""), "restart_engine_advised": stored.get("aide") == "redemarrer"}


@route("GET", "/models", SESSION)
def models(request):
    """What the model selector needs: the models of the chosen engine, the one in use, and the downloads started since Lutin was launched."""
    state = _m.etat_moteur()
    sizes = state.get("tailles") or {}
    return {"engine": _m.moteur_actuel().id, "running": bool(state["actif"]), "current": str(_m.reglages().get("modele") or ""),
            "models": [{"name": name, "size_bytes": sizes.get(name)} for name in state["installes"]],
            "downloads": [_download(name, stored) for name, stored in sorted(_m.PULLS.items())],
            "remote": _remote_models()}


# --------------------------------------------------------------------------- paired machines (ADR 0016): other computers whose engine Lutin may use

MACHINE_STATES = {"inconnu": "unknown", "injoignable": "unreachable", "reveil_envoye": "wake_sent", "joignable": "reachable", "operationnel": "operational"}
MACHINE_STEPS = {"eteinte": "off", "reveil": "waking", "allumee": "powered_on", "lutin": "lutin_started", "synchro": "syncing", "pret": "ready",
                 "extinction": "shutting_down", "maj": "updating"}
MACHINE_RIGHTS = {"piloter": "lead", "maj": "update", "extinction": "shutdown"}


def _multi_machine():
    return _machines.cluster_actif(_m.reglages().get("cluster"))


def _remote_models():
    """The models of the paired machines that answer (probed in the last 40 s), for the model selector; empty while the multi-machine mode is off."""
    if not _multi_machine():
        return []
    return [{"machine": entry["id"], "machine_name": entry["nom"], "state": MACHINE_STATES.get(entry["etat"], "unknown"), "models": list(entry["modeles"])}
            for entry in _machines.modeles_distants()]


def _load(stored):
    if not isinstance(stored, dict):
        return None
    ram, vram = stored.get("ram"), stored.get("vram")
    return {"busy_here": bool(stored.get("locale_occupee")), "remote_turns": int(stored.get("distantes") or 0),
            "ram": {"total": ram.get("total"), "free": ram.get("libre")} if isinstance(ram, dict) else None,
            "vram": {"total": vram.get("total"), "free": vram.get("libre"), "name": vram.get("nom", "")} if isinstance(vram, dict) else None}


def _machine(stored):
    """A paired machine under its v1 names: what `machines.vue` and the last probe say, never its token."""
    allowed, shares = stored.get("agir") or {}, stored.get("droits") or {}
    return {"id": stored["id"], "name": stored.get("nom", ""), "address": stored.get("adresse", ""), "mac": stored.get("mac", ""),
            "mac_auto": bool(stored.get("mac_auto")), "added": stored.get("ajoutee", ""), "warnings": list(stored.get("avertissements") or []),
            "state": MACHINE_STATES.get(stored.get("etat"), "unknown"), "detail": stored.get("detail", ""), "step": MACHINE_STEPS.get(stored.get("etape")),
            "shutdown_in_s": stored.get("dans_s") if stored.get("etape") == "extinction" else None,          # `dans_s` is 0 in every other step
            "wake_failed": bool(stored.get("reveil_echec")), "models": list(stored.get("modeles") or []),
            "load": _load(stored.get("charge")), "version": stored.get("version", ""), "update_available": bool(stored.get("maj_disponible")),
            "allowed": {english: bool(allowed.get(french)) for french, english in MACHINE_RIGHTS.items()},
            "requested": [MACHINE_RIGHTS[right] for right in stored.get("demandes") or [] if right in MACHINE_RIGHTS],
            "shares": {"skills": bool(shares.get("skills")), "memory": bool(shares.get("memoire"))}}


@route("GET", "/machines", SESSION)
def paired_machines(request):
    """The paired machines and who answers. Never waits for the network: each machine comes with its last known state, and a stale one is probed
    again in the background (`unknown` until a first answer). `answering` is the machine of the setting `machine` ("" for this one)."""
    settings = _m.reglages()
    answering = str(settings.get("machine") or "")
    return {"enabled": _multi_machine(), "answering": answering,
            "machines": [_machine(stored) for stored in _machines.etats_sans_attente(settings.get("modele", ""), answering)],
            "log": _machines.journal()}


# The actions on a paired machine (ADR 0016, stage 2): the right is `configurator` for all of them, as on the old Machines tab; what this machine grants
# to the others (the node) is stage 3. Who answers by default stays the setting `machine` (`PATCH /settings`). A refusal comes before any effect: the
# functions of `lutin.machines` check the machine and the values first, and write nothing when the other machine says no or does not answer.
MACHINE_ERRORS = ((_machines.MachineInconnue, 404, "not_found"), (_machines.MachineRefus, 409, "machine_refused"),
                  (_machines.MachineInjoignable, 503, "machine_unreachable"), (_machines.MachineErreur, 502, "machine_error"))
MACHINE_ACTIONS = ("wake", "shutdown", "cancel-shutdown", "update")
MACHINE_IMPORTS = ("skills", "memory")


def _on_machine(action, *args, **kwargs):
    """Runs an action of `lutin.machines` and gives its refusal a status: 404 unknown machine, 409 the other machine said no (code refused, right not
    granted), 503 it does not answer, 502 it answered something unexpected. Any other ValueError is a value of the request: 400, as everywhere."""
    try:
        return action(*args, **kwargs)
    except ValueError as failed:
        for kind, status, code in MACHINE_ERRORS:
            if isinstance(failed, kind):
                raise ApiError(status, code, str(failed)) from None
        raise


def _paired(identifier):
    """One machine as `GET /machines` shows it."""
    settings = _m.reglages()
    found = next((stored for stored in _machines.etats_sans_attente(settings.get("modele", ""), str(settings.get("machine") or "")) if stored["id"] == identifier), None)
    if found is None:
        raise ApiError(404, "not_found", _t("Machine inconnue."))
    return _machine(found)


@route("POST", "/machines", CONFIGURATOR)
def pair_machine(request):
    """{"address": "http://192.168.1.20:8777", "code": "12345678", "name"?, "mac"?}: pairs the machine with the one-time code it shows. 201 and the
    machine (`unknown` until its first probe). Nothing is written when a field is wrong (400), the code is refused (409) or the machine does not answer (503)."""
    body = request.body
    fields = ("address", "code", "name", "mac")
    if set(body) - set(fields) or not all(isinstance(body.get(name, ""), str) for name in fields) or not body.get("address", "").strip() or not body.get("code", "").strip():
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format(", ".join(fields)))
    paired = _on_machine(_machines.ajouter, body["address"], body["code"].strip(), body.get("name", ""), body.get("mac", ""))
    return 201, _paired(paired["id"])


@route("PATCH", "/machines/{id}", CONFIGURATOR)
def update_machine(request):
    """{"mac": "00:1A:2B:3C:4D:5E"} ("" clears it): the address of the network card that wakes the machine. Answers the machine."""
    if set(request.body) != {"mac"} or not isinstance(request.body["mac"], str):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("mac"))
    _on_machine(_machines.definir_mac, request.params["id"], request.body["mac"])
    return _paired(request.params["id"])


@route("DELETE", "/machines/{id}", CONFIGURATOR)
def unpair_machine(request):
    """Forgets the machine (its token included). If it was the one answering by default, this machine answers again. Answers `GET /machines`."""
    identifier = request.params["id"]
    _on_machine(_machines.retirer, identifier)
    if str(_m.reglages().get("machine") or "") == identifier:
        _m.enregistrer_reglages({"machine": ""})
    return paired_machines(request)


@route("POST", "/machines/{id}/actions/{action}", CONFIGURATOR)
def machine_action(request):
    """`wake` sends the Wake-on-LAN packet (the machine needs its MAC address) and says what may keep it from working; `shutdown` asks the machine to
    shut down in 30 s, `cancel-shutdown` cancels that, `update` asks it to update Lutin. These three need the right the machine grants (`allowed` in
    `GET /machines`), else 409 `machine_refused`. 202: the machine goes on by itself and `GET /machines` follows it (`step`); 200 for a cancel."""
    identifier, name = request.params["id"], request.params["action"]
    if name not in MACHINE_ACTIONS:
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("action", ", ".join(MACHINE_ACTIONS)))
    if request.body:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("-"))
    if name == "wake":
        sent = _on_machine(_machines.reveiller, identifier, envoyer=_power.send_wake)          # looked up now, not when machines.py was loaded: the tests replace it
        return 202, {"mac": sent["mac"], "sent": sent["envois"], "interfaces": list(sent["cartes"]), "warnings": list(sent["avertissements"])}
    if name == "update":
        _on_machine(_machines.mettre_a_jour_distante, identifier)
        return 202, {}
    answer = _on_machine(_machines.eteindre, identifier, name == "cancel-shutdown")
    answer = answer if isinstance(answer, dict) else {}
    if name == "cancel-shutdown":
        return {"cancelled": bool(answer.get("annulee"))}
    return 202, {"shutdown_in_s": answer.get("dans_s")}


@route("POST", "/machines/{id}/rights-requests", CONFIGURATOR)
def request_machine_right(request):
    """{"right": "lead" | "update" | "shutdown"}: asks the machine to grant this right; its owner answers on it, nothing is granted by itself.
    `requested` in `GET /machines` shows it while it waits."""
    words = {english: french for french, english in MACHINE_RIGHTS.items()}
    right = request.body.get("right")
    if set(request.body) != {"right"} or not isinstance(right, str) or right not in words:
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("right", ", ".join(words)))
    _on_machine(_machines.demander_droit, request.params["id"], words[right])
    return 202, {"right": right}


@route("POST", "/machines/{id}/imports/{kind}", CONFIGURATOR)
def import_from_machine(request):
    """Adds to this machine what the other one shares (`shares` in `GET /machines`, else 409 `machine_refused`): `skills` (a skill already here is never
    overwritten, unless it came from that machine and was not changed since) or `memory` (the notes this machine does not have; the profile only when
    it is empty here). Answers the counts."""
    kind = request.params["kind"]
    if kind not in MACHINE_IMPORTS:
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("kind", ", ".join(MACHINE_IMPORTS)))
    if request.body:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("-"))
    if kind == "skills":
        counts = _on_machine(_machines.importer_skills, request.params["id"])
        return {"added": counts["ajoutes"], "updated": counts["mis_a_jour"], "already_there": counts["deja_la"]}
    counts = _on_machine(_machines.importer_memoire, request.params["id"])
    return {"notes_added": counts["notes_ajoutees"], "notes_skipped": counts["notes_ignorees"], "profile_copied": counts["profil_copie"],
            "profile_truncated": counts["profil_coupe"]}


# --------------------------------------------------------------------------- this machine as a node (ADR 0016, stage 3): what it lends to the others
# The rights are those of the old Machines tab, read in lutin.server: lending, the pairing code and revoking need `configurator`; what this machine
# grants (shares, rights, autostart), the answer to a rights request and cancelling a shutdown another machine asked for need `local`. The protocol
# between machines (/api/noeud/*) is not part of this: it changes with /node/v1 (step 3 of the plan).
NODE_SHARES = {"skills": "skills", "memoire": "memory"}
NODE_ALLOW = {"piloter": _machines.noeud_autoriser_piloter, "maj": _machines.noeud_autoriser_maj, "extinction": _machines.noeud_autoriser_extinction}


def _node():
    view = _machines.noeud_vue()
    pending = view["extinction_en_attente"]
    startup = _power.startup_state_memo()
    return {"lending": bool(view["actif"]), "id": view["id"],
            "shares": {english: bool(view["droits"].get(french)) for french, english in NODE_SHARES.items()},
            "allow": {english: bool(view.get(french)) for french, english in MACHINE_RIGHTS.items()},
            "pending_shutdown": {"in_s": pending["dans_s"], "by": pending["par"]} if pending else None,
            "requests": [{"machine": waiting.get("machine", ""), "right": MACHINE_RIGHTS[waiting["droit"]], "date": waiting.get("date", "")}
                         for waiting in view["demandes"] if waiting.get("droit") in MACHINE_RIGHTS],
            "authorized": [{"name": allowed["nom"], "date": allowed["date"]} for allowed in view["autorisees"]],
            "startup": {"installed": bool(startup.get("installe")), "possible": bool(startup.get("possible")), "limits": startup.get("limites", "")}}


@route("GET", "/node", SESSION)
def node(request):
    """This machine as a node: whether it lends its engine (`lending`), its id, what it shares with and allows to the paired machines, a shutdown one of
    them asked for (`pending_shutdown`, null when none), the rights requests waiting for an answer, the machines that may use it, and autostart."""
    return _node()


@route("PATCH", "/node", CONFIGURATOR)
def update_node(request):
    """{"lending": true | false}: lends the engine of this machine to the machines paired with it, or stops. Refused at the level « this machine only »
    (409 `local_only`): no other machine could reach it. Answers `GET /node`."""
    lending = request.body.get("lending")
    if set(request.body) != {"lending"} or not isinstance(lending, bool):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("lending"))
    try:
        _machines.noeud_activer(lending, niveau_local=_m.SECURITE.niveau == _sec.LOCAL)          # raises before writing anything
    except ValueError as refused:
        raise ApiError(409, "local_only", str(refused)) from None
    return _node()


def _flags(body, name, words):
    """The {english: bool} object `name` of a body, as {french: bool}; 400 for anything else."""
    given, french = body[name], {english: word for word, english in words.items()}
    if not isinstance(given, dict) or not given or set(given) - set(french) or not all(isinstance(value, bool) for value in given.values()):
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format(name, ", ".join(french)))
    return {french[key]: value for key, value in given.items()}


@route("PATCH", "/node/permissions", LOCAL)
def update_node_permissions(request):
    """{"shares"?: {"skills"?, "memory"?}, "allow"?: {"lead"?, "update"?, "shutdown"?}, "autostart"?: bool}: what this machine grants to the paired
    machines, from this machine only. Everything is checked before anything is written; autostart comes first, being the one step the system may
    refuse (400 with its reason, and nothing else is written). Answers `GET /node`."""
    body, fields = request.body, ("shares", "allow", "autostart")
    if not body or set(body) - set(fields):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format(", ".join(fields)))
    shares = _flags(body, "shares", NODE_SHARES) if "shares" in body else {}
    allow = _flags(body, "allow", MACHINE_RIGHTS) if "allow" in body else {}
    autostart = body.get("autostart")
    if "autostart" in body and not isinstance(autostart, bool):
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("autostart", "true, false"))
    if autostart is not None:
        (_power.install_startup if autostart else _power.remove_startup)()          # looked up now: the tests replace them
    for right, granted in allow.items():
        NODE_ALLOW[right](granted)
    for share, granted in shares.items():
        _machines.noeud_droit(share, granted)
    return _node()


@route("POST", "/node/pairing-code", CONFIGURATOR)
def node_pairing_code(request):
    """A one-time code (shown « 1234-5678 », valid `valid_seconds`) that another machine types to pair with this one (`POST /machines` there).
    409 `not_lending` while this machine does not lend its engine: the code could not be used."""
    if request.body:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("-"))
    if not _machines.noeud_actif():
        raise ApiError(409, "not_lending", _t("Cette machine ne prête pas son moteur : active d'abord le prêt."))
    code = _machines.noeud_nouveau_code()
    return 201, {"code": code["code"], "valid_seconds": code["expire_dans"]}


@route("DELETE", "/node/authorized/{name}", CONFIGURATOR)
def revoke_node_machine(request):
    """Revokes a machine that may use this one: its token stops working at once. 404 for a name no authorized machine has. Answers `GET /node`."""
    name = request.params["name"]
    if name not in [allowed["nom"] for allowed in _machines.noeud_vue()["autorisees"]]:
        raise ApiError(404, "not_found", _t("Machine inconnue."))
    _machines.noeud_revoquer(name)
    return _node()


@route("PATCH", "/node/authorized/{name}", CONFIGURATOR)
def rename_node_machine(request):
    """{"name": "PC du bureau"}: a clear name for a machine that may use this one (the one it sent is often its computer's technical name). Cleaned as
    at pairing; its token keeps working and its waiting requests follow it. 404 unknown, 409 `conflict` when another machine has that name."""
    body = request.body
    if set(body) != {"name"} or not isinstance(body["name"], str) or not _machines.nom_machine(body["name"]):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("name"))
    try:
        _machines.noeud_renommer(request.params["name"], body["name"])
    except LookupError:
        raise ApiError(404, "not_found", _t("Machine inconnue.")) from None
    except FileExistsError:
        raise ApiError(409, "conflict", _t("Une autre machine porte déjà ce nom.")) from None
    return _node()


@route("POST", "/node/requests/{machine}/{right}", LOCAL)
def answer_node_request(request):
    """{"accept": true | false}: answers the request of a paired machine for a right (`requests` in `GET /node`), from this machine only. Accepting grants
    the right (`allow`, which can be unticked at any time); refusing forgets the request. 404 when it is no longer there. Answers `GET /node`."""
    words = {english: french for french, english in MACHINE_RIGHTS.items()}
    machine, right, accept = request.params["machine"], request.params["right"], request.body.get("accept")
    if right not in words:
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("right", ", ".join(words)))
    if set(request.body) != {"accept"} or not isinstance(accept, bool):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("accept"))
    if not any(waiting.get("machine") == machine and waiting.get("droit") == words[right] for waiting in _machines.noeud_vue()["demandes"]):
        raise ApiError(404, "not_found", _t("Cette demande n'existe plus."))
    _machines.noeud_repondre_demande(machine, words[right], accept)
    return _node()


@route("POST", "/node/shutdown/cancel", LOCAL)
def cancel_node_shutdown(request):
    """Cancels a shutdown of this machine that a paired machine asked for (`pending_shutdown` in `GET /node`). `cancelled` is false when none was pending."""
    if request.body:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("-"))
    return {"cancelled": _power.cancel_shutdown(_machines.journaliser)}


# --------------------------------------------------------------------------- conversations led on another machine (ADR 0016, stages 6 and 7)
# This machine relays to the host (`/api/noeud/relais/…`, node token), which runs ITS OWN legacy routes from a closed list, with its own folders,
# approvals and models, only if it grants « lead »: the relay never reaches the host's /api/v1, so a host running an older Lutin keeps working. The
# translation is done here, at this machine's border: the answers in the shapes of the local routes, the stream through `event` (EVENTS).
# A refusal of the host keeps its sentence; its status gets a v1 code (403: the host does not grant « lead »).
RELAY_ERRORS = {400: "invalid_request", 403: "machine_refused", 404: "not_found", 409: "conflict", 413: "too_large", 429: "too_many_turns"}
RELAY_READ_MAX = 64 * 1024 * 1024
RE_CONVERSATION = re.compile(r"^[0-9a-f]{8}$")
RE_FILE_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")


def _host(identifier):
    """The paired machine that holds the conversation. 404 when unknown; 503 when it does not answer (probed once if nothing is known of it yet)."""
    stored = _machines.trouver(identifier) if _machines.RE_ID.match(identifier) else None
    if stored is None:
        raise ApiError(404, "not_found", _t("Machine inconnue."))
    if _machines.DERNIER_ETAT.get(identifier) is None:
        _machines.sonder(stored)
    if _machines.DERNIER_ETAT.get(identifier) not in ("joignable", "operationnel"):
        raise ApiError(503, "machine_unreachable", _t("La machine « {} » ne répond pas : sa conversation reviendra quand elle sera de nouveau en ligne.").format(stored["nom"]))
    return stored


def _hosted(request, key="conversation"):
    """(host, conversation id) of a route /machines/{id}/conversations/{conversation}…, both checked before anything is sent."""
    identifier = request.params[key]
    if not RE_CONVERSATION.match(identifier):
        raise ApiError(404, "not_found", _t("Conversation inconnue."))
    return _host(request.params["id"]), identifier


def _relay(host, method, path, body=None, content_type="application/json", name=""):
    """Opens the relayed request; its answer is read by the caller. Every failure becomes an ApiError before anything is written to the page."""
    try:
        return _machines.ouvrir_relais(host, method, path, body, content_type, name)
    except urllib.error.HTTPError as refused:
        try:
            detail = str(json.loads(refused.read(100_000).decode("utf-8", "replace")).get("erreur", ""))
        except (ValueError, OSError, AttributeError):
            detail = ""
        finally:
            refused.close()
        code = RELAY_ERRORS.get(refused.code)
        if code is None:
            raise ApiError(502, "machine_error", detail or _t("Cette machine a répondu une erreur ({}).").format(refused.code)) from None
        raise ApiError(refused.code, code, detail or _t("Cette machine a répondu une erreur ({}).").format(refused.code)) from None
    except (urllib.error.URLError, OSError):
        _machines.signaler_panne(host)
        raise ApiError(503, "machine_unreachable", _t("Impossible de joindre la machine « {} » : elle ne répond plus.").format(host["nom"])) from None


def _relay_json(host, method, path, body=None):
    with _relay(host, method, path, None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")) as answer:
        raw = answer.read(RELAY_READ_MAX)
    try:
        value = json.loads(raw or b"{}")
    except ValueError:
        value = None
    if not isinstance(value, dict):
        raise ApiError(502, "machine_error", _t("Réponse inattendue : ce n'est pas un Lutin qui prête son moteur."))
    return value


def _remote_conversation(host, stored):
    return dict(_conversation(stored), machine=host["id"])


@route("GET", "/machines/conversations", SESSION)
def remote_conversations(request):
    """The conversations of the paired machines that grant « lead », gathered in the background (never waits for a machine that is off); a machine that
    stopped answering has none listed. Empty while the multi-machine mode is off."""
    if not _multi_machine():
        return {"conversations": []}
    return {"conversations": [{"machine": entry["machine"], "machine_name": entry["machine_nom"], "id": entry["id"], "title": entry["titre"],
                               "updated_at": entry["maj"], "message_count": entry["messages"]} for entry in _machines.conversations_distantes()]}


@route("GET", "/machines/{id}/conversations/{conversation}", SESSION)
def remote_conversation(request):
    """One conversation of a paired machine, in the shape of GET /conversations/{id}, plus `machine`."""
    host, identifier = _hosted(request)
    return _remote_conversation(host, _relay_json(host, "GET", "/api/conversation?id=" + identifier))


def _pass_stream(handler, answer):
    """Writes the host's stream to the page, one event per line, each translated by `event`; an empty line (heartbeat) goes through. The host keeps
    running the turn if the page goes: as for a local turn, the conversation is stored at the end."""
    handler.send_response(200)
    handler.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()
    with answer:
        while True:
            try:
                line = answer.readline(1_000_000)
            except (OSError, ValueError):
                break
            if not line:
                break
            text = line.strip()
            if not text:
                out = b"\n"
            else:
                try:
                    out = (json.dumps(event(json.loads(text)), ensure_ascii=False) + "\n").encode("utf-8")
                except ValueError:
                    continue                                   # a line that is not an event is not passed on
            try:
                handler.wfile.write(out)
                handler.wfile.flush()
            except (OSError, ValueError):
                break


@route("POST", "/machines/{id}/conversations/{conversation}/turns", SESSION)
def remote_turn(request):
    """Sends a message in a conversation led on a paired machine and streams its answer, as POST /conversations/{id}/turns does: {"message"} and,
    optionally, `replace_from`, `images` and `attachments` (sent first to that machine: POST /machines/{id}/images, /attachments). The model, the
    mode and the approvals are those of that machine: nothing else is accepted. A refusal of the host comes before the stream with its sentence."""
    body = request.body
    fields = ("message", "replace_from", "images", "attachments")
    if set(body) - set(fields) or not isinstance(body.get("message"), str) or not body["message"].strip():
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format(", ".join(fields)))
    host, identifier = _hosted(request)
    payload = {"message": body["message"], "conversation": identifier}
    if "replace_from" in body:
        payload["remplacer_depuis"] = body["replace_from"]
    if "images" in body:
        payload["images"] = body["images"]
    if isinstance(body.get("attachments"), list):
        payload["pieces"] = [{"id": item.get("id"), "nom": item.get("name")} if isinstance(item, dict) else item for item in body["attachments"]]
    answer = _relay(host, "POST", "/api/chat", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return Streamed(lambda: _pass_stream(request.handler, answer))


@route("POST", "/machines/{id}/conversations/{conversation}/stop", SESSION)
def remote_stop(request):
    """The Stop button of a turn running on a paired machine. `was_running` says whether there was anything to stop."""
    if request.body:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("-"))
    host, identifier = _hosted(request)
    return {"was_running": bool(_relay_json(host, "POST", "/api/arreter", {"conversation": identifier}).get("actif"))}


@route("POST", "/machines/{id}/approvals/{approval}", SESSION)
def remote_approval(request):
    """Answers an approval request of a turn running on a paired machine: {"approved": true} and, optionally, `restore_auto_approval`. Remembering a
    « yes » (`remember`) is that machine's own rule to set: only `once` is accepted here."""
    body = request.body
    if set(body) - {"approved", "restore_auto_approval", "remember"} or not isinstance(body.get("approved"), bool) or body.get("remember", "once") != "once":
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("approved, restore_auto_approval, remember (once)"))
    if not RE_FILE_ID.match(request.params["approval"]):
        raise ApiError(404, "not_found", _t("Plus de demande en attente."))
    host = _host(request.params["id"])
    _relay_json(host, "POST", "/api/approuver", {"id": request.params["approval"], "ok": body["approved"], "reactiver": bool(body.get("restore_auto_approval"))})
    return {"approved": body["approved"]}


@route("POST", "/machines/{id}/conversations/{conversation}/memory-choice", SESSION)
def remote_memory_choice(request):
    """Answers the `memory_choice` event of a long conversation led on a paired machine: {"choice": "summary" | "file"}, and `remember`."""
    body = request.body
    choices = {"summary": "resume", "file": "fichier"}
    if set(body) - {"choice", "remember"} or body.get("choice") not in choices or not isinstance(body.get("remember", False), bool):
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("choice", ", ".join(choices)))
    host, identifier = _hosted(request)
    _relay_json(host, "POST", "/api/memoire-choix", {"conversation": identifier, "choix": choices[body["choice"]], "garder": body.get("remember", False)})
    return {"choice": body["choice"]}


@route("PATCH", "/machines/{id}/conversations/{conversation}", SESSION)
def update_remote_conversation(request):
    """Renames and/or pins a conversation led on a paired machine: {"title"?, "pinned"?}. Answers it, in the shape of GET /conversations/{id}."""
    body = request.body
    if not body or set(body) - {"title", "pinned"}:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("title, pinned"))
    if "title" in body and (not isinstance(body["title"], str) or not body["title"].strip()):
        raise ApiError(400, "invalid_request", _t("Le titre doit être un texte non vide."))
    if "pinned" in body and not isinstance(body["pinned"], bool):
        raise ApiError(400, "invalid_request", _t("« pinned » doit être vrai ou faux."))
    host, identifier = _hosted(request)
    if "title" in body:
        _relay_json(host, "POST", "/api/renommer", {"id": identifier, "titre": body["title"]})
    if "pinned" in body:
        _relay_json(host, "POST", "/api/epingler", {"id": identifier, "epingle": body["pinned"]})
    return _remote_conversation(host, _relay_json(host, "GET", "/api/conversation?id=" + identifier))


@route("DELETE", "/machines/{id}/conversations/{conversation}", SESSION)
def delete_remote_conversation(request):
    """Deletes a conversation led on a paired machine, there (its mission too, as there)."""
    host, identifier = _hosted(request)
    _relay_json(host, "POST", "/api/supprimer", {"id": identifier})
    return {"deleted": True}


@route("POST", "/machines/{id}/images", SESSION, raw=True, limit=_images.MAX_SIZE)
def upload_remote_image(request):
    """An image for the next message of a conversation led on a paired machine: sent to that machine, which keeps it. Answers its identifier there."""
    host = _host(request.params["id"])
    identifier = str(_relay_json_raw(host, "/api/image", request.raw, "application/octet-stream").get("id", ""))
    return 201, {"id": identifier, "url": "{}/machines/{}/images/{}".format(PREFIX, host["id"], urllib.parse.quote(identifier))}


@route("POST", "/machines/{id}/attachments", SESSION, raw=True, limit=_pieces.MAX_SIZE)
def upload_remote_attachment(request):
    """A document for the next message of a conversation led on a paired machine: its bytes as the body, its name in `X-Name` (URL-encoded); the text
    is extracted there. Answers {id, name, characters}, as POST /attachments."""
    host = _host(request.params["id"])
    answer = _relay_json_raw(host, "/api/document", request.raw, "application/octet-stream", request.handler.headers.get("X-Name") or "")
    return 201, {"id": str(answer.get("id", "")), "name": str(answer.get("nom", "")), "characters": answer.get("caracteres")}


def _relay_json_raw(host, path, data, content_type, name=""):
    with _relay(host, "POST", path, data, content_type, name) as answer:
        raw = answer.read(RELAY_READ_MAX)
    try:
        value = json.loads(raw or b"{}")
    except ValueError:
        value = None
    if not isinstance(value, dict):
        raise ApiError(502, "machine_error", _t("Réponse inattendue : ce n'est pas un Lutin qui prête son moteur."))
    return value


def _relay_file(host, path):
    with _relay(host, "GET", path) as answer:
        return answer.read(RELAY_READ_MAX), answer.headers.get("Content-Type") or "application/octet-stream"


@route("GET", "/machines/{id}/images/{image}", READ)
def remote_image(request):
    """An image sent in a conversation led on a paired machine, read from it. READ, like GET /images/{id}: a browser tag sends the cookie, not the token."""
    if not RE_FILE_ID.match(request.params["image"]):
        raise ApiError(404, "not_found", _t("Image inconnue."))
    data, content_type = _relay_file(_host(request.params["id"]), "/image/" + request.params["image"])
    if not content_type.startswith("image/"):
        raise ApiError(502, "machine_error", _t("Réponse inattendue : ce n'est pas un Lutin qui prête son moteur."))
    return Binary(data, content_type, {"Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff"})


@route("GET", "/machines/{id}/attachments/{attachment}", READ)
def remote_attachment(request):
    """A document sent in a conversation led on a paired machine, as it was sent: always a download, as GET /attachments/{id}; `?name=` names it."""
    if not RE_FILE_ID.match(request.params["attachment"]):
        raise ApiError(404, "not_found", _t("Fichier joint inconnu."))
    name = _pieces.clean_name(request.query.get("name") or "") or request.params["attachment"]
    data, _ = _relay_file(_host(request.params["id"]), "/piece/" + request.params["attachment"] + "?nom=" + urllib.parse.quote(name))
    return Binary(data, "application/octet-stream", {"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name),
                                                    "Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff"})


@route("GET", "/machines/{id}/conversations/{conversation}/files/{file}", READ)
def remote_produced_file(request):
    """A file a tool created in a conversation led on a paired machine, read from it: always a download. Opening and deleting it are done on that machine."""
    host, identifier = _hosted(request)
    if not RE_FILE_ID.match(request.params["file"]):
        raise ApiError(404, "not_found", _t("Ce fichier n'est plus dans la conversation."))
    name = _pieces.clean_name(request.query.get("name") or "") or request.params["file"]
    data, _ = _relay_file(host, "/fichier/" + identifier + "/" + request.params["file"])
    return Binary(data, "application/octet-stream", {"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name),
                                                    "Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff"})


@route("POST", "/models", SESSION)
def install_model(request):
    """Starts the download of a model: {"name": "qwen3:8b"}. Answers at once (202) with the state of the download; `GET /models` then follows it."""
    name = request.body.get("name")
    if set(request.body) - {"name"} or not isinstance(name, str):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("name"))
    return 202, _download(name, _m.installer_modele(name))


@route("DELETE", "/models/{name}", SESSION)
def delete_model(request):
    """Deletes an installed model. The model in use may be deleted: `current` is the one Lutin switched to, or the same name when there is no other."""
    _m.supprimer_modele(request.params["name"])
    return {"deleted": True, "current": str(_m.reglages().get("modele") or "")}


# ----------------------------------------------------------------------------------------------------------- machine and guide
# What the guided choice of a model needs (docs/modernization/GUIDED_SETUP.md): the machine in plain figures, the catalogue with a verdict for THIS machine, and a recommendation by use.
# The verdicts come from model_fit and model_compat, never from the page; the editorial notes of the catalogue are estimates, not measures (its own warning, given back as `disclaimer`).
FIT_LEVELS = {"ideal": "comfortable", "bien": "good", "limite": "tight", "trop_gros": "too_big"}
CAPABILITIES = {"outils": "tools", "reflexion": "thinking", "vision": "vision"}
MACHINE_CLASSES = {"sans_gpu": "no_gpu", "petite": "small", "moyenne": "medium", "grande": "large", "tres_grande": "very_large"}
RUNS_ON = {"gpu": "gpu", "partiel": "partial", "cpu": "cpu"}
# What a person says they want to do, and the roles of the catalogue that answer it, the best first.
USES = {"chat": ("polyvalent", "creatif"), "code": ("code", "polyvalent"), "documents": ("polyvalent", "vision"), "unsure": ("polyvalent", "rapide")}
ROLE_IDS = ("polyvalent", "rapide", "creatif", "code", "vision")
ROLES_V1 = {"polyvalent": "general", "rapide": "fast", "creatif": "creative", "code": "code", "vision": "images"}


def models_folder(engine_running):
    """The folder the models go to. When the engine answers it says which one it uses; when it does not, asking it would wait for its timeout (2 s, and the first launch is
    exactly that case), so the folder is the one of the configuration, then the usual place."""
    if engine_running:
        return _health.ollama_models_folder()
    from . import locations
    return Path(os.environ.get("OLLAMA_MODELS") or locations.read_models_config() or (Path.home() / ".ollama" / "models"))


def machine_profile():
    """The profile of the machine if it is known, else None: the detection (which runs programs) starts in the background and is never waited for here."""
    return _model_fit.profil_pret()


@route("GET", "/machine", SESSION)
def machine(request):
    """The machine in figures: `{"detected": false}` while the detection runs (ask again in a second or two), else its processor, memory, graphics cards and disks, and the memory Lutin
    would let a model fill (`budget_gb`)."""
    profile = machine_profile()
    if profile is None:
        return {"detected": False}
    return {
        "detected": True, "system": profile.systeme, "architecture": profile.architecture, "cpu": profile.cpu, "cores": profile.coeurs,
        "ram_gb": profile.ram_go, "ram_free_gb": profile.ram_libre_go or None,
        "gpus": [{"name": gpu.nom, "vendor": gpu.fabricant, "memory_gb": gpu.vram_go, "free_gb": gpu.libre_go or None, "integrated": _hardware.integrated_is(gpu)} for gpu in profile.gpus],
        "disks": [{"path": disk.racine, "free_gb": disk.libre_go, "total_gb": disk.total_go} for disk in profile.disques],
        "budget_gb": profile.budget_go(), "budget_set_gb": float(_m.reglages().get("budget_go") or 0) or None, "class": MACHINE_CLASSES.get(profile.classe(), profile.classe()), "summary": profile.resume(),
    }


def _catalog_entry(model, profile, engine, installed):
    fit = _model_fit.evaluer(model, profile) if profile is not None else None
    compatibility = _model_compat.evaluate(model, engine, installed)
    return {
        "id": model["id"], "name": model["nom"], "summary": model["phrase"], "size_gb": model["go"], "parameters_b": model["params_b"], "active_parameters_b": model["actifs_b"],
        "context_max": model["ctx_max"], "capabilities": [CAPABILITIES.get(item, item) for item in model.get("capacites") or []], "licence": model["licence"],
        "roles": {ROLES_V1.get(role, role): note for role, note in (model.get("notes") or {}).items()}, "advanced": bool(model.get("avance")), "warning": model.get("avertissement", ""),
        "installed": model["id"] in installed,
        "fit": None if fit is None else {"level": FIT_LEVELS.get(fit["niveau"], fit["niveau"]), "text": fit["texte"]},
        "compatibility": {"compatible": compatibility["compatible"], "reasons": compatibility["raisons"], "warnings": compatibility["avertissements"], "memory_gb": compatibility["memoire_go"]},
    }


@route("GET", "/models/catalog", SESSION)
def models_catalog(request):
    """The catalogue with, for each model, a verdict for this machine (`fit`, null until the machine is detected) and for the engine in use (`compatibility`).
    The models marked advanced are left out unless `?advanced=1`."""
    profile, engine, state = machine_profile(), _m.moteur_actuel(), _m.etat_moteur()          # the state of the engine once: it waits 2 s when the engine does not answer
    installed = set(state["installes"])
    advanced = request.query.get("advanced") == "1"
    models = [_catalog_entry(model, profile, engine, installed) for model in _m._CATALOGUE["modeles"] if advanced or not model.get("avance")]
    return {"detected": profile is not None, "disclaimer": _m._CATALOGUE.get("avertissement", ""), "models": models}


@route("GET", "/models/recommendation", SESSION)
def models_recommendation(request):
    """What to download for a use: `?use=chat|code|documents|unsure`. The model that fits this machine and this engine best, why, the other fitting choices, and what the download would cost
    in disk space. Nothing is downloaded: the page asks for a confirmation that shows these figures, then calls `POST /models`."""
    use = request.query.get("use", "unsure")
    if use not in USES:
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("use", ", ".join(USES)))
    profile = machine_profile()
    if profile is None:
        return {"detected": False, "use": use}
    engine, state = _m.moteur_actuel(), _m.etat_moteur()
    installed = set(state["installes"])
    chosen = _model_compat.roles_for(profile, _m._CATALOGUE, engine, installed)

    def described(role, choice):
        entry = _catalog_entry(choice.modele, profile, engine, installed)
        return {"role": ROLES_V1.get(role, role), "model": entry, "context_tokens": choice.num_ctx, "memory_gb": choice.memoire_go, "runs_on": RUNS_ON.get(choice.tient, choice.tient)}
    main_role = next((role for role in USES[use] if chosen.get(role)), None)
    main = chosen.get(main_role) if main_role else None
    others, seen = [], {main.id} if main else set()
    for role in ROLE_IDS:
        choice = chosen.get(role)
        if choice and choice.id not in seen:
            seen.add(choice.id)
            others.append(described(role, choice))
    to_download = [main.id] if main and main.id not in installed else []
    space = _health.disk_space(models_folder(bool(state["actif"])))
    free_gb = round(space["libre"] / _health.GB, 1) if space else None
    size_gb = round(main.modele["go"], 1) if to_download else 0.0
    return {
        "detected": True, "use": use, "recommended": described(main_role, main) if main else None, "alternatives": others,
        "download": {"models": to_download, "size_gb": size_gb, "free_gb": free_gb, "fits_on_disk": None if free_gb is None else size_gb <= free_gb},
        "engine": {"id": engine.id, "name": engine.nom, "running": bool(state["actif"])}, "offline": bool(_offline.is_active()),
    }


# --------------------------------------------------------------------------------------------------------------------- engines
# The engines (Ollama, llama.cpp, servers compatible with OpenAI…) and what can be done with each: the state, the actions that are possible (or why not), the task that runs.
# It is the machinery of the present page (lutin.engines: `actions()`, `lancer_tache`, `annuler_tache`), under English names. An action that changes the machine is not started
# without `{"confirm": true}`: a client must have shown what it does (the reason given by `actions`) and had it accepted.
ENGINE_ACTIONS = {"install": "installer", "uninstall": "desinstaller", "reinstall": "reinstaller", "start": "demarrer", "stop": "arreter", "update": "mettre_a_jour"}
NEEDS_CONFIRMATION = ("install", "uninstall", "reinstall", "update")
NEEDS_NETWORK = ("install", "reinstall", "update")
ENGINE_TASK_STATES = {"en cours": "running", "termine": "done", "erreur": "failed"}


def _task(engine_id):
    task = _engines.task(engine_id)
    if not task:
        return None
    return {"action": next((name for name, stored in ENGINE_ACTIONS.items() if stored == task.get("action")), task.get("action", "")), "state": ENGINE_TASK_STATES.get(task.get("statut"), task.get("statut", "")),
            "text": task.get("texte") or task.get("dernier", ""), "done": int(task.get("fait") or 0), "total": int(task.get("total") or 0), "error": task.get("erreur", ""),
            "result": task.get("resultat", "")}


def _settled(future, default):
    try:
        return future.result()
    except Exception:  # noqa: BLE001  (an engine that cannot be read is shown as stopped, it must not hide the others)
        return default


def _engine_view(engine, current, state, models, possible, updates=None):
    """`update` is what the daily check of engine_updates knows (null until it ran): an engine known to be up to date is not offered an update."""
    sheet = engine.vue(engine.id == current)
    actions = {name: {"possible": bool((possible.get(stored) or {}).get("possible")), "reason": (possible.get(stored) or {}).get("raison", "")} for name, stored in ENGINE_ACTIONS.items()}
    known = (updates or {}).get(engine.id)
    if known and not known.get("disponible") and actions["update"]["possible"]:
        actions["update"] = {"possible": False, "reason": _t("À jour : {} est la dernière version connue (Réinstaller la remet si besoin).").format(known.get("actuelle") or known.get("derniere"))}
    return {
        "id": engine.id, "name": engine.nom, "kind": engine.genre, "manages_models": bool(engine.gere_modeles), "current": engine.id == current, "description": sheet["description"],
        "strengths": sheet["points_forts"], "weaknesses": sheet["points_faibles"], "installed": bool(state.get("installe")), "running": bool(state.get("actif")),
        "version": state.get("version", ""), "detail": state.get("detail", ""), "models_count": len(models.get("installes") or []),
        "actions": actions,
        "update": {"current": known.get("actuelle", ""), "latest": known.get("derniere", ""), "available": bool(known.get("disponible"))} if known else None,
        "task": _task(engine.id),
    }


@route("GET", "/engines", SESSION)
def engines(request):
    """Every engine with its state, the actions it allows and its running task. The engines are read at the same time: one that does not answer must not make the others wait."""
    current = _m.moteur_actuel().id
    _engine_updates.in_background(bool(_m.reglages().get("verifier_maj", True)) and not _offline.is_active())          # once a day at most, never waited for
    updates = _engine_updates.state()
    listed = _engines.entries()
    unknown = ({"installe": False, "actif": False, "version": "", "detail": ""}, {"installes": []}, {})
    # Three questions per engine, each of which waits 2 s when the engine does not answer: all asked at the same time, so the whole list costs one wait and not three per engine.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(24, 3 * len(listed)))) as pool:
        asked = [(engine, pool.submit(engine.statut), pool.submit(engine.modeles), pool.submit(engine.actions)) for engine in listed]
        views = [_engine_view(engine, current, _settled(a, unknown[0]), _settled(b, unknown[1]), _settled(c, unknown[2]), updates) for engine, a, b, c in asked]
    return {"current": current, "engines": views}


def _known_engine(identifier):
    engine = _engines.ENGINES.get(identifier)
    if engine is None:
        raise ApiError(404, "not_found", _t("Moteur inconnu."))
    return engine


@route("POST", "/engines/{id}/actions/{action}", CONFIGURATOR)
def engine_action(request):
    """Starts an action in the background: `install`, `uninstall`, `reinstall`, `start`, `stop` or `update`. Answers 202 with the task; `GET /engines` follows it.
    What changes the machine (all but start and stop) needs `{"confirm": true}`; what needs the network is refused in strict offline mode (409 `offline`); one task at a time per engine (409 `task_running`)."""
    engine, name = _known_engine(request.params["id"]), request.params["action"]
    if name not in ENGINE_ACTIONS:
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("action", ", ".join(ENGINE_ACTIONS)))
    if set(request.body) - {"confirm"} or not isinstance(request.body.get("confirm", False), bool):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("confirm"))
    possible = engine.actions().get(ENGINE_ACTIONS[name]) or {}
    if not possible.get("possible"):
        raise ApiError(400, "action_impossible", possible.get("raison") or _t("Cette action n'est pas possible avec ce moteur."))
    if name in NEEDS_CONFIRMATION and not request.body.get("confirm"):
        raise ApiError(400, "confirmation_required", possible.get("raison") or _t("Cette action modifie cette machine : elle demande une confirmation."))
    if name in NEEDS_NETWORK and _offline.is_active():
        raise ApiError(409, "offline", _t("Mode hors ligne strict : impossible de {}. Désactive-le pour continuer (lutin offline off).").format(name))
    try:
        _engines.launch_task(engine, ENGINE_ACTIONS[name])
    except ValueError as busy:
        raise ApiError(409, "task_running", str(busy)) from None
    return 202, _task(engine.id)


@route("DELETE", "/engines/{id}/task", CONFIGURATOR)
def cancel_engine_task(request):
    """Asks the running task of this engine to stop; what was already downloaded is kept. `cancelled` says whether something was running."""
    return {"cancelled": bool(_engines.cancel_task(_known_engine(request.params["id"]).id))}


# The library of an engine that downloads GGUF files itself (llama.cpp: Hugging Face): search a model, see the quantisations of a repository (one file each, sorted by size, with a
# verdict for this machine) and download one. For the machine itself; refused offline (409 `offline`); a download needs `{"confirm": true}`.
def _library_engine(identifier):
    engine = _known_engine(identifier)
    if not hasattr(engine, "chercher_modeles"):
        raise ApiError(400, "no_library", _t("Ce moteur n'a pas de bibliothèque de modèles à parcourir."))
    return engine


@route("GET", "/engines/{id}/library", CONFIGURATOR)
def search_engine_library(request):
    """`?q=name`: the repositories that match, most downloaded first: `{"results": [{"repo", "downloads", "likes"}]}`. The words must be written (400 otherwise)."""
    engine = _library_engine(request.params["id"])
    _require_online(_t("chercher un modèle sur Hugging Face"))
    return {"results": [{"repo": item["id"], "downloads": item["telechargements"], "likes": item["likes"]} for item in engine.chercher_modeles(request.query.get("q", ""))]}


@route("GET", "/engines/{id}/library/files", CONFIGURATOR)
def engine_library_files(request):
    """`?repo=author/name`: the quantisations of a repository, smallest first: `{"files": [{"file", "size_bytes", "fit"}]}`. `fit` is the verdict for this machine
    (`{"level": comfortable | good | tight | too_big, "text"}`), null while the machine is not detected or the size is unknown."""
    engine = _library_engine(request.params["id"])
    _require_online(_t("lire les fichiers d'un dépôt Hugging Face"))
    profile = machine_profile()
    files = []
    for item in engine.fichiers_du_depot(request.query.get("repo", "")):
        fit = _model_fit.evaluer({"go": item["taille"] / 1e9}, profile) if profile is not None and item["taille"] else None
        files.append({"file": item["fichier"], "size_bytes": item["taille"], "fit": None if fit is None else {"level": FIT_LEVELS.get(fit["niveau"], fit["niveau"]), "text": fit["texte"]}})
    return {"files": files}


@route("POST", "/engines/{id}/library/download", CONFIGURATOR)
def download_from_engine_library(request):
    """{"repo", "file", "confirm": true}: downloads one file into the models folder of the engine, as a task (`GET /engines` follows it, `DELETE /engines/{id}/task` cancels it).
    Answers 202 with the task. `confirm` is always needed: it is a download of several gigabytes."""
    body = request.body
    if set(body) - {"repo", "file", "confirm"} or any(not isinstance(body.get(key), str) for key in ("repo", "file")) or not isinstance(body.get("confirm", False), bool):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("repo, file, confirm"))
    engine = _library_engine(request.params["id"])
    if not body.get("confirm"):
        raise ApiError(400, "confirmation_required", _t("Ce téléchargement peut peser plusieurs Go : confirme pour le lancer."))
    _require_online(_t("télécharger un modèle"))
    possible = engine.telechargeable()
    if not possible["possible"]:
        raise ApiError(400, "action_impossible", possible["raison"])
    repo, file = body["repo"], body["file"]
    try:
        _engines.launch_task(engine, "telecharger", lambda action, progress: engine.telecharger_modele(repo, file, progress))
    except ValueError as busy:
        raise ApiError(409, "task_running", str(busy)) from None
    return 202, _task(engine.id)


# ------------------------------------------------------------------------------------------------------------------------ setup
# The guide of the first launch (docs/modernization/GUIDED_SETUP.md): shown after the first installation on a NEW machine, never on an installation that already lives.
# « New » is proven by the absence of everything an installation leaves: the flag of this guide, conversations, a settings file, an installed model. An existing installation that
# is only stopped for a moment (its engine does not answer) therefore never sees the guide.
SETUP_FILE = "setup.json"


def _setup_path():
    return _m.DONNEES / SETUP_FILE


def _has_history():
    """Conversations or a settings file: signs of an installation that has been used. Cheap, and decided before the engine is asked."""
    return bool(_m.conv_liste()) or (_m.DONNEES / "reglages.json").is_file()


def setup_state():
    stored = _storage.lire_json(_setup_path(), {})
    if stored.get("done"):
        return {"done": True, "needed": False, "skipped": bool(stored.get("skipped"))}
    if _has_history():
        return {"done": False, "needed": False, "skipped": False}
    # Nothing proves a past use: the last proof is a model already installed (a machine where Ollama was set up before Lutin).
    return {"done": False, "needed": not _m.etat_moteur()["installes"], "skipped": False}


@route("GET", "/setup", SESSION)
def setup(request):
    """`needed`: the guide of the first launch should be shown. `done`: it was finished or skipped. An installation that already lived is never `needed`."""
    return setup_state()


@route("POST", "/setup/complete", CONFIGURATOR)
def complete_setup(request):
    """Records that the guide is over, finished or skipped (`{"skipped": true}`): it is not shown again."""
    if set(request.body) - {"skipped"} or not isinstance(request.body.get("skipped", False), bool):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("skipped"))
    _storage.ecrire_atomique(_setup_path(), json.dumps({"done": True, "skipped": bool(request.body.get("skipped"))}))
    return setup_state()


# A quick speed test, offered at the end of the first launch (a yes/no choice of the person): one short text written by the chosen model, and how fast.
SPEED = {"state": "idle", "model": "", "tokens_per_second": None, "level": None, "error": ""}
SPEED_LEVELS = ((8, "slow"), (15, "fair"), (30, "comfortable"), (60, "fast"))          # tokens per second below each bound; above the last: very_fast


def _speed_level(tokens_per_second):
    for bound, level in SPEED_LEVELS:
        if tokens_per_second < bound:
            return level
    return "very_fast"


def _measure_speed(model):
    from . import bench
    from .ollama_client import Ollama
    return bench.Banc(Ollama(_m.OLLAMA), model, 4096, 120).vitesse().get("tok_s")


@route("GET", "/speed-test", SESSION)
def speed_test(request):
    """`state`: `idle`, `running`, `done` or `failed`. `tokens_per_second` and `level` (`slow`, `fair`, `comfortable`, `fast`, `very_fast`) once it is done."""
    return dict(SPEED)


@route("POST", "/speed-test", SESSION)
def start_speed_test(request):
    """Starts the test on the model in use (Ollama only for now) and answers at once (202): `GET /speed-test` follows it. Refused while an answer is being written: the figure would be wrong."""
    model = str(_m.reglages().get("modele") or "")
    with _m.VERROU_TOURS:
        if _m.TOURS_ACTIFS or _m.BENCH["en_cours"]:
            raise ApiError(409, "busy", _t("Une réponse ou une mesure est en cours : la mesure serait faussée. Attends sa fin."))
        if SPEED["state"] == "running":
            raise ApiError(409, "busy", _t("Une mesure est déjà en cours."))
        if _m.moteur_actuel().id != _engines.OLLAMA:
            raise ApiError(409, "not_supported", _t("Le test de vitesse n'est pas encore proposé avec ce moteur."))
        if model not in _m.etat_ollama()["installes"]:
            raise ApiError(409, "model_missing", _t("Le modèle « {} » n'est pas installé : installe-le ou choisis-en un autre en haut à gauche.").format(model))
        SPEED.update(state="running", model=model, tokens_per_second=None, level=None, error="")

    def work():
        try:
            measured = _measure_speed(model)
            if measured:
                SPEED.update(state="done", tokens_per_second=measured, level=_speed_level(measured))
            else:
                SPEED.update(state="failed", error=_t("Le moteur n'a rien pu mesurer."))
        except Exception as cause:  # noqa: BLE001  (an engine that fails ends the test, never the application)
            SPEED.update(state="failed", error=str(cause)[:200])

    started = dict(SPEED)          # taken before the thread runs: a very quick test would already be done
    threading.Thread(target=work, daemon=True, name="speed-test").start()
    return 202, started


# --------------------------------------------------------------------------------------------------------- devices
# The devices that were paired with the code shown on this machine (a phone, another computer). Nothing here changes how a session is checked: the code,
# its attempts and the sessions stay in lutin.security. Only the digests of the session tokens are stored, and only their first characters are shown.
def _devices_view():
    level = ACCESS_LEVELS.get(_m.SECURITE.niveau, _m.SECURITE.niveau)
    return {"devices": [{"id": item["id"], "name": item["nom"], "paired_at": int(item["cree"]), "seen_at": int(item["vu"])} for item in _m.APPAREILS.liste()],
            "level": level, "pairing_possible": level != "local", "address": "http://{}:{}/".format(_m.IP_LAN or _m.ip_locale(), _m.SECURITE.port)}


@route("GET", "/devices", SESSION)
def devices(request):
    """The paired devices, the access level (`local`, `network`, `proxy`) and the address another device opens. `pairing_possible` is false at the level `local`:
    Lutin then listens on this machine only, and no other device can reach it."""
    return _devices_view()


@route("POST", "/devices/pairing-code", LOCAL)
def pairing_code(request):
    """A new pairing code, for the person in front of THIS machine only (right `local`: never a paired device, never a remote administrator). The code replaces
    the previous one and is valid a few minutes; it is typed on the other device, which opens `address`. `qr` draws that address."""
    view = _devices_view()
    if not view["pairing_possible"]:
        raise ApiError(409, "local_only", _t("Lutin n'écoute que sur cette machine : ouvre d'abord l'accès au réseau (Accès), puis redémarre-le."))
    from . import qr as _qr
    matrix = _qr.matrice(view["address"])
    return 201, {"code": _m.APPAREILS.nouveau_pin(), "valid_seconds": _sec.DURATION_PIN_S, "address": view["address"],
                 "qr": {"size": len(matrix), "rows": ["".join(map(str, row)) for row in matrix]}}


@route("DELETE", "/devices/{id}", CONFIGURATOR)
def revoke_device(request):
    """Ends the session of one device: it must be paired again to come back. 404 when no device has this identifier."""
    identifier = request.params["id"]
    if not re.fullmatch(r"[0-9a-f]{10}", identifier) or not _m.APPAREILS.revoquer(identifier):
        raise ApiError(404, "not_found", _t("Appareil inconnu."))
    return _devices_view()


@route("DELETE", "/devices", CONFIGURATOR)
def revoke_all_devices(request):
    """Ends the session of every paired device."""
    _m.APPAREILS.revoquer(None)
    return _devices_view()


# --------------------------------------------------------------------------------------------------------- approval rules
def _rules_view():
    return {"rules": [{"id": rule["id"], "effect": rule["effect"], "command": rule["command"], "created_at": rule.get("created", 0)} for rule in _approval_rules.user_rules()],
            "project_rules": [{"effect": rule["effect"], "command": rule["command"]} for rule in _approval_rules.project_rules(_m.RACINE)],
            "hardline": sorted({reason for _, reason in _approval_rules.HARDLINE})}


@route("GET", "/approval-rules", SESSION)
def approval_rules(request):
    """The rules that decide whether a command is refused (`deny`), asked (`ask`) or run without asking (`allow`); deny > ask > allow. `project_rules` come from
    `.lutin/approvals.json` of the working folder and can only ask or deny. `hardline` says what always needs a question, whatever the rules say."""
    return _rules_view()


@route("POST", "/approval-rules", CONFIGURATOR)
def add_approval_rule(request):
    """{"effect": "deny" | "ask" | "allow", "command": "git push *"}: a command exactly, or a beginning followed by ` *`. An `allow` for a hardline command is refused."""
    if set(request.body) - {"effect", "command"}:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("effect, command"))
    _approval_rules.add(request.body.get("effect"), request.body.get("command"))
    return 201, _rules_view()


@route("DELETE", "/approval-rules/{id}", CONFIGURATOR)
def remove_approval_rule(request):
    if not _approval_rules.remove(request.params["id"]):
        raise ApiError(404, "not_found", _t("Règle inconnue."))
    return _rules_view()


# --------------------------------------------------------------------------------------------------------- projects
# A project is a working folder: where Lutin reads and writes files for the conversations. The present page calls them « dossiers de travail ».
def _projects_view():
    state = _m.works_state()
    projects = []
    for entry in state["liste"]:
        problem = _workspaces.diagnostic(Path(entry["chemin"]))
        projects.append({"id": entry["id"], "name": entry["nom"], "path": entry["chemin"], "usable": not problem, "problem": problem or ""})
    return {"projects": projects, "current": state["actif"]}


@route("GET", "/projects", SESSION)
def projects(request):
    """The working folders and the one in use. `usable` is false, with the reason in `problem`, for a folder that cannot be used now (gone, read-only, on a disk that does not answer)."""
    return _projects_view()


@route("POST", "/projects", CONFIGURATOR)
def add_project(request):
    """{"path": "/home/me/code", "name": "optional"}: adds a folder to the list (it is not made the current one). Refused with the reason when the folder cannot be used."""
    path = request.body.get("path")
    if not isinstance(path, str) or not path.strip() or not isinstance(request.body.get("name", ""), str):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("path, name"))
    _m.add_work(path.strip(), request.body.get("name", ""))
    return 201, _projects_view()


@route("GET", "/projects/folders", CONFIGURATOR)
def browse_folders(request):
    """The sub-folders of `?path=` (never files), sorted, with the `parent` to go up. Without a path: the starting points (home, documents, drives) and an empty `parent`. Refused with the reason when the folder cannot be read. For the person at this machine only: it shows the disk."""
    listing = _m.list_folders(request.query.get("path", ""))
    return {"path": listing["chemin"], "parent": listing["parent"], "folders": [{"name": entry["nom"], "path": entry["chemin"]} for entry in listing["dossiers"]], "truncated": bool(listing.get("tronque"))}


CLAUDE_FOUND = {"contexte": "context", "regles": "rules", "skills": "skills", "commandes": "commands", "agents": "agents"}


def _claude_found(found):
    """What a folder holds on Claude's side, in English names: `context` and `rules` are file paths, the others lists of {name, description, path}."""
    view = {}
    for french, english in CLAUDE_FOUND.items():
        items = found.get(french) or []
        view[english] = [{"name": item["nom"], "description": item.get("description") or "", "path": item["chemin"]} if isinstance(item, dict) else item for item in items]
    return view


@route("GET", "/projects/claude", CONFIGURATOR)
def detect_claude_project(request):
    """What the folder `?path=` holds of a Claude project (CLAUDE.md, a `.claude/` folder): `is_claude_project`, a `summary` sentence and the `found` lists. Nothing is written."""
    path = request.query.get("path", "").strip()
    if not path:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("path"))
    folder = Path(path).expanduser()
    problem = _workspaces.diagnostic(folder)
    if problem:
        raise ApiError(400, "invalid_request", problem)
    found = _claude_project.detect(folder)
    empty = _claude_project.is_empty(found)
    return {"path": str(folder), "is_claude_project": not empty, "summary": "" if empty else _claude_project.summary(found), "found": _claude_found(found)}


CLAUDE_IMPORT_MODES = {"in_place": "ici", "copy": "copie"}


@route("POST", "/projects/import-claude", CONFIGURATOR)
def import_claude_project(request):
    """{"path", "mode": "in_place" | "copy", "to": optional folder for the copy, "name": optional}. `in_place`: Lutin works in the folder itself; `copy`: in a copy, and the original is never
    touched. The folder joins the list and becomes the current one, unless an answer is being written elsewhere (`current` then stays and `selected` is false)."""
    body = request.body
    if set(body) - {"path", "mode", "to", "name"} or not isinstance(body.get("path"), str) or not body["path"].strip() or any(not isinstance(body.get(key, ""), str) for key in ("to", "name")):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("path, mode, to, name"))
    if body.get("mode") not in CLAUDE_IMPORT_MODES:
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("mode", "in_place, copy"))
    done = _m.import_claude_project(body["path"], CLAUDE_IMPORT_MODES[body["mode"]], body.get("to", ""), body.get("name", ""))
    return dict(_projects_view(), mode=body["mode"], path=done["chemin"], summary=done["resume"], selected=bool(done["actif"]))


@route("POST", "/projects/{id}/select", SESSION)
def select_project(request):
    """Makes this folder the one the next conversations work in. Refused (409 `workspace_conflict`) while an answer is being written in another folder."""
    try:
        _m.choose_work(request.params["id"])
    except ValueError as refused:
        text = str(refused)
        if _m.TOURS_ACTIFS and "réponse" in text:
            raise ApiError(409, "workspace_conflict", text) from None
        raise
    return _projects_view()


@route("DELETE", "/projects/{id}", CONFIGURATOR)
def remove_project(request):
    """Takes the folder out of the list. Nothing in it is deleted, except with `?clean=1`: the copies of conversations that Lutin itself wrote there, never another file."""
    result = _m.remove_work(request.params["id"], request.query.get("clean") == "1")
    return dict(_projects_view(), copies_removed=result.get("copies_supprimees", 0))


# --------------------------------------------------------------------------------------------------------- scheduled tasks
# A request that Lutin carries out by itself at a time of the week (or once, on a date), in the same conversation each time.
TASK_RUN_STATES = {"": "never", "ok": "ok", "erreur": "failed", "arretee": "stopped", "en_cours": "running", "interrompue": "interrupted"}


def _scheduled_view(task):
    state = TASK_RUN_STATES.get(task.get("derniere_etat", ""), task.get("derniere_etat", ""))
    history = [{"at": item.get("date", ""), "state": TASK_RUN_STATES.get(item.get("etat", ""), item.get("etat", "")), "seconds": item.get("duree_s", 0), "error": item.get("erreur", "")}
               for item in task.get("historique") or []]
    return {"id": task["id"], "name": task["nom"], "request": task["prompt"], "time": task["heure"], "days": task.get("jours") or [], "date": task.get("date") or "",
            "project": task.get("travail") or "", "notify": task.get("notifier") or "", "active": bool(task.get("actif")), "next_run": task.get("prochaine") or "",
            "running": bool(task.get("en_cours")), "last_run_at": task.get("derniere_exec") or "", "last_state": state, "last_error": task.get("derniere_erreur") or "",
            "conversation": task.get("derniere_conv") or "", "history": history}


def _scheduled_list():
    return {"tasks": [_scheduled_view(task) for task in _scheduled_tasks.state()["taches"]]}


def _scheduled_one(identifier):
    task = next((task for task in _scheduled_tasks.state()["taches"] if task["id"] == identifier), None)
    if task is None:
        raise ApiError(404, "not_found", _t("Cette tâche planifiée n'existe plus."))
    return task


@route("GET", "/scheduled-tasks", SESSION)
def scheduled_tasks(request):
    """The scheduled tasks, with the next run, the state of the last one (`never`, `running`, `ok`, `failed`, `stopped`, `interrupted`) and the ten last runs."""
    return _scheduled_list()


SCHEDULED_FIELDS = {"name": "nom", "request": "prompt", "time": "heure", "days": "jours", "date": "date", "project": "travail", "notify": "notifier"}


@route("POST", "/scheduled-tasks", CONFIGURATOR)
def add_scheduled_task(request):
    """{"name", "request", "time": "08:30", "days": [0..6] (Monday is 0) or "date": "2026-12-31" for a single run, "project" (optional), "notify" (optional channel)}."""
    body = request.body
    unknown = sorted(set(body) - set(SCHEDULED_FIELDS))
    if unknown:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format(", ".join(SCHEDULED_FIELDS)))
    task = _scheduled_tasks.add(body.get("name"), body.get("request"), body.get("time"), body.get("days"), body.get("project", ""), body.get("notify", ""), body.get("date", ""))
    return 201, _scheduled_view(_scheduled_one(task["id"]))


@route("PATCH", "/scheduled-tasks/{id}", CONFIGURATOR)
def change_scheduled_task(request):
    """Any of the fields of the creation, and `active` (false pauses the task). Changing the moment starts the task again from now: it does not catch up an hour that has just passed."""
    body, identifier = request.body, request.params["id"]
    unknown = sorted(set(body) - set(SCHEDULED_FIELDS) - {"active"})
    if unknown or not body:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format(", ".join(list(SCHEDULED_FIELDS) + ["active"])))
    current = _scheduled_one(identifier)
    if "active" in body and not isinstance(body["active"], bool):
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("active", "boolean"))
    if set(body) - {"active"}:
        merged = {name: body.get(name, current.get(key)) for name, key in SCHEDULED_FIELDS.items()}
        _scheduled_tasks.change(identifier, merged["name"], merged["request"], merged["time"], merged["days"], merged["project"], merged["notify"], merged["date"])
    if "active" in body:
        _scheduled_tasks.modify(identifier, actif=body["active"])
    return _scheduled_view(_scheduled_one(identifier))


@route("DELETE", "/scheduled-tasks/{id}", CONFIGURATOR)
def delete_scheduled_task(request):
    """Deletes the task for good (a task at work is stopped). `?conversation=1` also deletes the conversation it wrote in."""
    _scheduled_one(request.params["id"])
    _scheduled_tasks.remove(request.params["id"], request.query.get("conversation") == "1")
    return _scheduled_list()


@route("POST", "/scheduled-tasks/{id}/run", CONFIGURATOR)
def run_scheduled_task(request):
    """Runs the task now, in the background (202). Refused (409) while it is already at work or while the machine is busy with as many answers as it allows."""
    identifier = request.params["id"]
    _scheduled_one(identifier)
    if identifier in _scheduled_tasks.EN_COURS:
        raise ApiError(409, "busy", _t("Cette tâche travaille déjà."))
    if len(_m.TOURS_ACTIFS) >= _m.TOURS_SIMULTANES:
        raise ApiError(409, "busy", _t("Une réponse est déjà en cours : attends sa fin."))
    threading.Thread(target=lambda: _scheduled_tasks.executer(identifier), daemon=True, name="scheduled-run").start()
    return 202, {"started": True}


@route("POST", "/scheduled-tasks/{id}/stop", CONFIGURATOR)
def stop_scheduled_task(request):
    """Asks the task at work to stop (it stays scheduled for the next time). Refused with the reason when it is not at work."""
    _scheduled_one(request.params["id"])
    _scheduled_tasks.arreter(request.params["id"])
    return {"stopped": True}


# --------------------------------------------------------------------------------------------------------- notification channels
# Where Lutin sends a message when a scheduled task is done (Gotify, ntfy, Telegram, a webhook). A secret (token, webhook address) is never given back: only whether it is set.
def _channels_view():
    types = [{"id": kind["id"], "name": kind["nom"], "fields": [{"key": field["cle"], "label": field["libelle"], "required": field["obligatoire"], "secret": field["secret"]} for field in kind["champs"]]}
             for kind in _notifications.channel_types()]
    channels = [{"id": channel["id"], "name": channel["nom"], "type": channel["type"], "type_name": channel["type_nom"], "params": channel["params"], "secrets_set": channel["secrets_definis"]}
                for channel in _notifications.list_channels()]
    return {"types": types, "channels": channels}


def _channel_one(identifier):
    if _notifications.find(identifier) is None:
        raise ApiError(404, "not_found", _t("Ce canal n'existe plus."))


@route("GET", "/notification-channels", SESSION)
def notification_channels(request):
    """The channels (without their secrets: `secrets_set` names the ones that are set) and the kinds that can be added, with the fields each one asks for."""
    return _channels_view()


@route("POST", "/notification-channels", CONFIGURATOR)
def add_notification_channel(request):
    """{"name", "type": "gotify" | "ntfy" | "telegram" | "webhook", "params": {field: value}}: adds a channel. Refused (400) with what to correct. At most ten channels."""
    body = request.body
    if not isinstance(body.get("name"), str) or not isinstance(body.get("type"), str) or not isinstance(body.get("params", {}), dict):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("name, type, params"))
    _notifications.add(body["name"], body["type"], body.get("params", {}))
    return 201, _channels_view()


@route("DELETE", "/notification-channels/{id}", CONFIGURATOR)
def remove_notification_channel(request):
    """Removes the channel. A scheduled task that named it keeps working and simply stops notifying."""
    _channel_one(request.params["id"])
    _notifications.remove(request.params["id"])
    return _channels_view()


@route("POST", "/notification-channels/{id}/test", CONFIGURATOR)
def test_notification_channel(request):
    """Sends a test message through the channel. Refused (400) with the reason when the service does not answer or refuses it."""
    _channel_one(request.params["id"])
    return _notifications.test_channel(request.params["id"])


# --------------------------------------------------------------------------------------------------------- add-ons
# An add-on connects Lutin to a service (mail, Telegram, X, ComfyUI, a voice studio). Each one describes itself (its steps, the settings it asks for, the hosts it talks to):
# this is all a page needs to draw it. The value of a secret is never given back, only whether it is set. Not in v1 yet: the live panel of an add-on (the pairing code of
# Telegram, the drafts), its actions, and the editor of its calls.
def _addon_view(identifier):
    entry = _addons.decrire(identifier)
    settings = []
    for entry_field in entry["reglages"]:
        item = {"key": entry_field["cle"], "secret": bool(entry_field.get("secret")), "multiline": bool(entry_field.get("texte")), "label": entry_field.get("libelle") or "", "help": entry_field.get("aide") or "",
                "default": entry_field.get("defaut") or "", "choices": [{"value": choice[0], "label": choice[1]} for choice in entry_field["choix"]] if entry_field.get("choix") else None}
        if item["secret"]:
            item["set"] = bool(entry_field.get("defini"))
        else:
            item["value"] = entry_field.get("valeur") or ""
        settings.append(item)
    check = entry["verification"]
    return {"id": entry["id"], "name": entry["nom"], "description": entry["description"], "doc": entry["doc"], "hosts": entry["hotes"],
            "steps": [{"title": step.get("titre", ""), "text": step.get("texte", "")} for step in entry["etapes"]], "settings": settings, "missing": entry["a_configurer"],
            "active": entry["actif"], "state": entry["etat"], "stream_modified": bool(entry["flux_modifie"]),
            "check": None if not check else {"ok": bool(check["ok"]), "at": check["date"], "steps": [{"call": step["appel"], "ok": bool(step["ok"]), "message": step["message"]} for step in check["etapes"]]}}


def _addons_view():
    return {"addons": [_addon_view(identifier) for identifier in _addons.ids()], "alerts": [{"id": alert["id"], "name": alert["nom"]} for alert in _addons.alertes()]}


def _addon_one(identifier):
    if identifier not in _addons.ids():
        raise ApiError(404, "not_found", _t("Cet addon n'existe pas."))


@route("GET", "/addons", SESSION)
def addons(request):
    """The add-ons: what each does (`steps`, `hosts` it talks to), the `settings` it asks for (a secret says only whether it is `set`), what is `missing` before it can start, `active`, the last `check`, and the `alerts` (active add-ons whose last check failed)."""
    return _addons_view()


@route("PATCH", "/addons/{id}", CONFIGURATOR)
def change_addon(request):
    """{"settings": {key: value}} saves settings (an empty secret keeps the old one; an unknown key is refused), and/or {"active": true|false} starts or stops the add-on: starting runs a check first and is refused (400) with the reason when it fails."""
    body, identifier = request.body, request.params["id"]
    _addon_one(identifier)
    if set(body) - {"settings", "active"} or not body or not isinstance(body.get("settings", {}), dict) or not isinstance(body.get("active", True), bool):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("settings, active"))
    try:
        if "settings" in body:
            _addons.save_settings(identifier, body["settings"])
        if "active" in body:
            _addons.activer(identifier, body["active"])
    except _addons.ErreurAddon as refused:
        raise ApiError(400, "invalid_request", str(refused)) from None
    return _addons_view()


@route("POST", "/addons/{id}/check", CONFIGURATOR)
def check_addon(request):
    """Checks the add-on (the settings are there, then each call of its check: the add-on contacts its own hosts). Answers the check and keeps it."""
    identifier = request.params["id"]
    _addon_one(identifier)
    _addons.check(identifier)
    return _addon_view(identifier)["check"]


# The live panel of an add-on: what it holds while it runs (the pairing code and the paired phones of Telegram, the drafts of replies waiting for a yes, the posts of X) and the actions on it.
# Each add-on keeps its own French names inside; the translators below give them English ones. An add-on without a translator has no panel here (`panel` is null).
def _panel_drafts(items, keys):
    return [{new: item.get(old, default) for new, (old, default) in keys.items()} for item in items]


def _telegram_panel(raw):
    return {"listening": bool(raw["ecoute"]), "error": raw["erreur"] or "", "pairing_code": raw["code"], "third_parties": raw["tiers"] == "oui",
            "devices": [{"id": str(device["id"]), "name": device.get("nom", "")} for device in raw["autorises"]],
            "drafts": _panel_drafts(raw["brouillons"], {"id": ("id", ""), "device": ("chat_id", ""), "from": ("de", ""), "request": ("demande", ""), "text": ("texte", ""), "at": ("date", 0)})}


def _mail_panel(raw):
    return {"listening": bool(raw["ecoute"]), "error": raw["erreur"] or "", "last_check_at": raw["derniere"] or 0, "address": raw["adresse"],
            "drafts": _panel_drafts(raw["brouillons"], {"id": ("id", ""), "from": ("de", ""), "address": ("adresse", ""), "subject": ("sujet", ""), "excerpt": ("extrait", ""), "text": ("texte", ""), "at": ("date", 0)})}


X_POST_STATES = {"brouillon": "draft", "programme": "scheduled", "publie": "published"}


def _x_panel(raw):
    posts = [{"id": post["id"], "text": post.get("texte", ""), "state": X_POST_STATES.get(post.get("etat"), post.get("etat", "")), "at": post.get("date", 0), "scheduled_for": post.get("quand", 0), "detail": post.get("detail", "")}
             for post in raw["publications"]]
    return {"listening": bool(raw["ecoute"]), "error": raw["erreur"] or "", "handle": raw["pseudo"], "mentions": bool(raw["mentions"]), "published_today": raw["publies"], "daily_limit": raw["plafond"], "posts": posts,
            "replies": _panel_drafts(raw["reponses"], {"id": ("id", ""), "from": ("de", ""), "name": ("nom", ""), "to_post": ("a", ""), "excerpt": ("extrait", ""), "text": ("texte", ""), "at": ("date", 0)})}


COMFY_DOWNLOAD_STATES = {"": "idle", "en cours": "running", "fini": "done", "erreur": "failed"}
COMFY_MODEL_SOURCES = {"api": "api", "dossier": "folder", "aucune": "none"}


def _comfyui_panel(raw):
    """ComfyUI: where it is installed, the models it holds by kind (the names of ComfyUI's own model folders), what Lutin can make with them, and the download in progress."""
    models = raw["modeles"]
    download = raw["telechargement"]
    return {"running": bool(raw["tourne"]), "error": raw["erreur"] or "", "version": raw["version"], "gpu": raw["gpu"], "folder": raw["dossier"] or "", "folder_set": bool(raw["dossier_regle"]),
            "folder_valid": bool(raw["valide"]), "folder_problem": raw["raison"] or "", "can_launch": bool(raw["lancement"]),
            "models": {"source": COMFY_MODEL_SOURCES.get(models["source"], models["source"]), "by_kind": models["modeles"]}, "families": raw["familles"], "family_labels": raw["libelles_familles"],
            "workflows": raw["workflows"], "engines": {"image": raw["moteurs"]["image"], "video": raw["moteurs"]["video"], "sound": raw["moteurs"]["son"]}, "unusable_models": raw["inutilisables"],
            "download": {"state": COMFY_DOWNLOAD_STATES.get(download["etat"], "failed"), "name": download["nom"], "done_bytes": download["fait"], "total_bytes": download["total"], "error": download["erreur"]},
            "download_kinds": raw["genres"]}


ADDON_PANELS = {"telegram": _telegram_panel, "mail": _mail_panel, "x": _x_panel, "comfyui": _comfyui_panel}
# The actions that download something: they also take `confirm`, which must be true, and are refused offline.
ADDON_DOWNLOADS = {("comfyui", "download")}
# The actions of each panel: {English name: (French name, {English field: French field})}. A field that is not listed is refused.
ADDON_ACTIONS = {
    "telegram": {"forget_device": ("oublier", {"device": "chat_id"}), "new_pairing_code": ("nouveau_code", {}), "send_draft": ("envoyer", {"draft": "brouillon", "text": "texte"}), "discard_draft": ("rejeter", {"draft": "brouillon"})},
    "mail": {"send_draft": ("envoyer", {"draft": "brouillon", "text": "texte"}), "discard_draft": ("rejeter", {"draft": "brouillon"})},
    "x": {"write_posts": ("rediger", {"brief": "brief", "count": "nombre"}), "edit_post": ("modifier", {"post": "publication", "text": "texte"}), "publish_post": ("publier", {"post": "publication", "text": "texte"}),
          "schedule_post": ("programmer", {"post": "publication", "text": "texte", "at": "quand"}), "delete_post": ("supprimer", {"post": "publication"}),
          "send_reply": ("envoyer", {"draft": "brouillon", "text": "texte"}), "discard_reply": ("rejeter", {"draft": "brouillon"})},
    "comfyui": {"detect": ("detecter", {}), "refresh_models": ("modeles", {}), "use_folder": ("utiliser_dossier", {"folder": "dossier"}), "download": ("telecharger", {"url": "url", "kind": "genre"}),
                "cancel_download": ("annuler_telechargement", {})}}


def _panel_view(identifier):
    translate = ADDON_PANELS.get(identifier)
    try:
        return {"panel": translate(_addons.alive_state(identifier)) if translate else None}
    except _addons.ErreurAddon as refused:
        raise ApiError(400, "invalid_request", str(refused)) from None


@route("GET", "/addons/{id}/panel", CONFIGURATOR)
def addon_panel(request):
    """What the add-on shows while it runs, in English names, or `{"panel": null}` for an add-on that has none here. Telegram: `pairing_code`, `devices`, `drafts` of replies; mail: `drafts`; X: `posts` and `replies`. For the machine itself only: the pairing code is the key to the add-on."""
    _addon_one(request.params["id"])
    return _panel_view(request.params["id"])


@route("POST", "/addons/{id}/panel/{action}", CONFIGURATOR)
def addon_panel_action(request):
    """An action on the panel, with the fields of that action in the body (`send_draft` {draft, text}, `discard_draft` {draft}, `forget_device` {device}, `new_pairing_code`, X: `write_posts` {brief, count}, `edit_post`, `publish_post`, `schedule_post` {post, at: epoch seconds}, `delete_post`, `send_reply`, `discard_reply`). Answers the panel again; refused (400) with the reason when the add-on says no (nothing to send, service unreachable)."""
    identifier, name = request.params["id"], request.params["action"]
    _addon_one(identifier)
    known = ADDON_ACTIONS.get(identifier, {})
    if name not in known:
        raise ApiError(404, "not_found", _t("Action inconnue."))
    french_name, fields = known[name]
    body = dict(request.body)
    if (identifier, name) in ADDON_DOWNLOADS:
        confirm = body.pop("confirm", False)
        if not isinstance(confirm, bool) or set(body) - set(fields):
            raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format(", ".join(list(fields) + ["confirm"])))
        if not confirm:
            raise ApiError(400, "confirmation_required", _t("Ce téléchargement peut peser plusieurs Go : confirme pour le lancer."))
        _require_online(_t("télécharger un modèle"))
    elif set(body) - set(fields):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format(", ".join(fields) or "-"))
    try:
        _addons.action(identifier, french_name, {fields[key]: value for key, value in body.items()})
    except _addons.ErreurAddon as refused:
        raise ApiError(400, "invalid_request", str(refused)) from None
    return _panel_view(identifier)


# The flow of an add-on: the list of calls it makes to its service (addresses, methods, fields). It is a JSON document in the add-on's own format, given and taken as it is. A flow is
# checked before it is kept (same structure, only the hosts the add-on declares), the old one is kept in a history, and the one shipped with Lutin can always be put back.
def _flow_view(identifier):
    try:
        return {"flow": _addons.stream(identifier), "shipped": _addons.shipped_stream(identifier), "modified": bool(_addons.modified_stream(identifier))}
    except _addons.ErreurAddon as refused:
        raise ApiError(400, "invalid_request", str(refused)) from None


@route("GET", "/addons/{id}/flow", CONFIGURATOR)
def addon_flow(request):
    """`{"flow", "shipped", "modified"}`: the flow in force, the one shipped with Lutin, and whether the one in force is the person's own."""
    _addon_one(request.params["id"])
    return _flow_view(request.params["id"])


@route("PATCH", "/addons/{id}/flow", CONFIGURATOR)
def change_addon_flow(request):
    """{"flow": object}: keeps this flow after checking it (a flow that is badly formed or aims at a host the add-on does not declare is refused, nothing changes). Answers like GET."""
    identifier = request.params["id"]
    _addon_one(identifier)
    if set(request.body) != {"flow"} or not isinstance(request.body["flow"], dict):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("flow"))
    try:
        _addons.apply_stream(identifier, request.body["flow"])
    except _addons.ErreurAddon as refused:
        raise ApiError(400, "invalid_request", str(refused)) from None
    return _flow_view(identifier)


@route("POST", "/addons/{id}/flow/restore", CONFIGURATOR)
def restore_addon_flow(request):
    """Puts back the flow shipped with Lutin (the person's own is dropped). Answers like GET."""
    _addon_one(request.params["id"])
    _addons.restore_stream(request.params["id"])
    return _flow_view(request.params["id"])


@route("POST", "/addons/{id}/correction", CONFIGURATOR)
def propose_addon_correction(request):
    """After a failed check: asks the model for a corrected flow from the documentation of the service. Nothing is kept: `{"flow", "diff", "explanation"}`, a proposal to read and then
    send to `PATCH /addons/{id}/flow`. The proposal is checked first like any flow. Reads the documentation page, so refused offline (409)."""
    _addon_one(request.params["id"])
    _require_online(_t("chercher une correction de flux"))
    try:
        proposal = _addons.proposer_correction(request.params["id"])
    except _addons.ErreurAddon as refused:
        raise ApiError(400, "invalid_request", str(refused)) from None
    return {"flow": proposal["flux"], "diff": proposal["diff"], "explanation": proposal["explication"]}


# --------------------------------------------------------------------------------------------------------- MCP connectors
# A connector lends Lutin the tools of another program (started by a command) or of a server (an address). Nothing is started by adding one: the tools are asked for
# by `refresh`, and a tool is given to the model only once it is `allowed`. Starting a program is for the machine itself, hence the right `configurator` for all writes.
# The values of the environment variables and headers are secrets: they are never given back, only their names.
def _connectors_view():
    connectors = []
    for entry in _mcp.vue():
        connectors.append({"id": entry["id"], "name": entry["nom"], "kind": "http" if entry["type"] == "http" else "command", "command": entry["commande"] or [], "url": entry["url"],
                           "active": bool(entry["actif"]), "read_only": bool(entry["lecture_seule"]), "connected": bool(entry["connecte"]), "refreshed_at": entry["vu"], "error": entry["erreur"],
                           "env_names": entry["cles_env"], "header_names": entry["cles_entetes"],
                           "tools": [{"name": tool["nom"], "description": tool["description"], "read_only": bool(tool["lecture"]), "allowed": bool(tool["autorise"])} for tool in entry["outils"]]})
    return {"connectors": connectors, "tool_limit": _mcp.limit_tools()}


def _connector_one(identifier):
    if identifier not in _mcp.read()["serveurs"]:
        raise ApiError(404, "not_found", _t("Connecteur introuvable."))


def _text_map(value, field):
    if value is not None and (not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items())):
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format(field, "object"))
    return value


@route("GET", "/mcp-connectors", SESSION)
def mcp_connectors(request):
    """The connectors with their tools (`allowed` is what the model may call) and `tool_limit`: how many allowed tools the model would receive and how many are left out because there are too many."""
    return _connectors_view()


@route("POST", "/mcp-connectors", CONFIGURATOR)
def add_mcp_connector(request):
    """{"name", "command": "program arg" or ["program", "arg"], "env": {NAME: value}} for a program, or {"name", "url": "https://...", "headers": {Name: value}} for a server (one of the two, not both).
    The connector is added with no tool allowed and read-only; nothing is started."""
    body = request.body
    unknown = sorted(set(body) - {"name", "command", "url", "env", "headers"})
    if unknown or not isinstance(body.get("name"), str) or not isinstance(body.get("url", ""), str) or not isinstance(body.get("command", []), (str, list)):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("name, command, url, env, headers"))
    _mcp.add(body["name"], body.get("command"), body.get("url", ""), _text_map(body.get("env"), "env"), _text_map(body.get("headers"), "headers"))
    return 201, _connectors_view()


@route("PATCH", "/mcp-connectors/{id}", CONFIGURATOR)
def change_mcp_connector(request):
    """Any of `active`, `read_only` (booleans); `tool` + `allowed` (gives or takes back one tool: refresh the list first); `env` or `headers` REPLACE the secrets ({} removes them)."""
    body, identifier = request.body, request.params["id"]
    unknown = sorted(set(body) - {"active", "read_only", "tool", "allowed", "env", "headers"})
    if unknown or not body or ("tool" in body) != ("allowed" in body):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("active, read_only, tool + allowed, env, headers"))
    _connector_one(identifier)
    for flag in ("active", "read_only", "allowed"):
        if flag in body and not isinstance(body[flag], bool):
            raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format(flag, "boolean"))
    if "tool" in body and not isinstance(body["tool"], str):
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("tool", "string"))
    _mcp.set_value(identifier, body.get("active"), body.get("read_only"), body.get("tool"), body.get("allowed"), _text_map(body.get("env"), "env"), _text_map(body.get("headers"), "headers"))
    return _connectors_view()


@route("DELETE", "/mcp-connectors/{id}", CONFIGURATOR)
def remove_mcp_connector(request):
    """Removes the connector and closes it. The program it started is stopped; nothing else is touched."""
    _connector_one(request.params["id"])
    _mcp.remove(request.params["id"])
    return _connectors_view()


@route("POST", "/mcp-connectors/{id}/refresh", CONFIGURATOR)
def refresh_mcp_connector(request):
    """Starts the connector if needed and asks it for its tools (the ones already allowed stay allowed). Answers `{"tool_count"}`; refused (400) with the reason when it does not start or answer."""
    _connector_one(request.params["id"])
    return {"tool_count": _mcp.actualiser(request.params["id"])}


# The catalogue of connectors shipped with Lutin: known servers, each pinned to an exact version, plugged in with a few values (a folder, an address, a token). Installing one
# starts a program, hence `configurator`; if the program that runs the server is missing, Lutin downloads it first, which asks for `{"confirm": true}`.
CATALOG_FIELD_TYPES = {"dossier": "folder", "fichier": "file", "url": "url", "secret": "secret"}


def _catalog_view():
    entries = []
    for entry in _mcp_catalog.entries():
        entries.append({"id": entry["id"], "name": entry["nom"], "description": entry["description"], "category": entry["categorie"],
                        "runner": entry["execution"], "version": entry["version"], "installed": bool(entry["installe"]), "prerequisite": entry["manque"],
                        "fields": [{"key": field["cle"], "type": CATALOG_FIELD_TYPES.get(field["type"], field["type"]), "required": field["obligatoire"],
                                    "multiple": field["multiple"], "label": field["libelle"], "example": field["exemple"]} for field in entry["champs"]]})
    return {"entries": entries}


@route("GET", "/mcp-catalog", SESSION)
def mcp_catalog(request):
    """The connectors of the catalogue, in the language shown. `prerequisite` is empty when the program that runs the server is there, else the sentence that says Lutin will
    download it first; `installed` says a connector made from the entry already exists; `fields` are the values to give (`folder`, `file`, `url`, `secret`; `multiple` takes a list)."""
    return _catalog_view()


@route("POST", "/mcp-catalog/{id}/install", CONFIGURATOR)
def install_mcp_catalog_entry(request):
    """{"input": {field: value or [values]}, "confirm": true}. The values are checked first, the connector is tried at once and removed if it does not answer, and only the tools
    that declare themselves read-only are allowed. `confirm` is needed when `prerequisite` is not empty (a download). Answers `{"connector", "tool_count", "allowed_count"}`."""
    body = request.body
    if set(body) - {"input", "confirm"} or not isinstance(body.get("input", {}), dict) or not isinstance(body.get("confirm", False), bool):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("input, confirm"))
    entry = next((e for e in _mcp_catalog.entries() if e["id"] == request.params["id"]), None)
    if entry is None:
        raise ApiError(404, "not_found", _t("Connecteur du catalogue introuvable."))
    if entry["manque"] and not body.get("confirm"):
        raise ApiError(400, "confirmation_required", entry["manque"])
    done = _mcp_catalog.install(entry["id"], body.get("input") or {})
    return {"connector": done["id"], "tool_count": done["outils"], "allowed_count": done["autorises"]}


# --------------------------------------------------------------------------------------------------------- missions
# A mission is a long job given to Lutin (hours of work in a project, with all its tools), carried on turn after turn in a conversation of its own. It ends when the model says it is
# done, when it asks a question (`blocked`: it waits for an answer), or when a limit is reached. Starting one is a choice for the machine itself (`configurator`): it writes in a project.
MISSION_STATES = {"en_cours": "running", "pause": "paused", "bloquee": "blocked", "terminee": "done"}


def _mission_view(entry):
    return {"id": entry["id"], "name": entry["nom"], "brief": entry.get("cahier") or "", "project_path": entry.get("dossier") or "", "hours": entry.get("duree_h"),
            "autonomous": bool(entry.get("autonome")), "state": MISSION_STATES.get(entry.get("etat"), entry.get("etat")), "conversation": entry.get("conv") or "",
            "turns": entry.get("tours") or 0, "actions": entry.get("actions") or 0, "started_at": entry.get("debut") or 0, "ended_at": entry.get("fin") or 0,
            "report": entry.get("bilan") or "", "question": entry.get("question") or "", "message": entry.get("message") or "", "log": list(entry.get("journal") or [])}


def _missions_view():
    return {"missions": [_mission_view(entry) for entry in _mission.state()["liste"]]}


def _mission_one(identifier):
    if _mission.find(identifier) is None:
        raise ApiError(404, "not_found", _t("Cette mission n'existe plus."))


@route("GET", "/missions", SESSION)
def missions(request):
    """The missions with their state (`running`, `paused`, `blocked` = waits for an answer in `question`, `done` = ended, with its `report`), turns, actions, the last lines of `log`, and the conversation they are written in. `brief` is cut at 300 characters."""
    return _missions_view()


@route("POST", "/missions", CONFIGURATOR)
def add_mission(request):
    """{"name", "brief", "project": id of a project, "hours" (optional, 1 to 72), "autonomous" (optional, default true)}. Autonomous: writes and commands are carried out without asking, in the project, with the usual safeguards. Not autonomous: nothing is written or run, the model shows what it would do. Starts at once."""
    body = request.body
    unknown = sorted(set(body) - {"name", "brief", "project", "hours", "autonomous"})
    if unknown or not isinstance(body.get("name"), str) or not isinstance(body.get("brief"), str) or not isinstance(body.get("project"), str) \
            or not isinstance(body.get("autonomous", True), bool) or not isinstance(body.get("hours", _mission.DURATION_DEFAULT_H), int) or isinstance(body.get("hours"), bool):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("name, brief, project, hours, autonomous"))
    entry = _mission.create(body["name"], body["brief"], body["project"], body.get("hours", _mission.DURATION_DEFAULT_H), body.get("autonomous", True))
    return 201, _mission_view(_mission.summary(entry))


@route("POST", "/missions/{id}/pause", SESSION)
def pause_mission(request):
    """Pauses the mission (the turn at work stops). Resume it with `resume`."""
    _mission_one(request.params["id"])
    _mission.action("pause", {"id": request.params["id"]})
    return _missions_view()


@route("POST", "/missions/{id}/resume", SESSION)
def resume_mission(request):
    """Starts a paused mission again (the count of errors in a row starts again from zero)."""
    _mission_one(request.params["id"])
    _mission.action("reprendre", {"id": request.params["id"]})
    return _missions_view()


@route("POST", "/missions/{id}/reply", SESSION)
def reply_to_mission(request):
    """{"text"}: the answer to the question of a `blocked` mission, or one more instruction given on the way; a blocked or paused mission starts again."""
    text = request.body.get("text")
    if set(request.body) - {"text"} or not isinstance(text, str):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("text"))
    _mission_one(request.params["id"])
    _mission.action("repondre", {"id": request.params["id"], "texte": text})
    return _missions_view()


@route("POST", "/missions/{id}/stop", SESSION)
def stop_mission(request):
    """Ends the mission now. The work already done stays in the project and in the conversation."""
    _mission_one(request.params["id"])
    _mission.action("arreter", {"id": request.params["id"]})
    return _missions_view()


@route("DELETE", "/missions/{id}", CONFIGURATOR)
def delete_mission(request):
    """Removes the mission from the list (a running one is stopped). Its conversation stays in the list of conversations."""
    _mission_one(request.params["id"])
    _mission.action("supprimer", {"id": request.params["id"]})
    return _missions_view()


# --------------------------------------------------------------------------------------------------------- skills and memory
# A skill is a sheet of your own (`skills/NAME.md` in the Lutin folder): how you want something done. Only its title and its « read when… » line are given to the model; it opens the sheet when it needs it.
# The memory is two notes the model always has: the context (who you are, what you work on) and the memory (what to remember). Writing them is for the machine itself.
def _skill_entry(name, title):
    return {"name": name, "title": title, "read_when": _m.description_skill(name)}


def _skill_text(name):
    try:
        return _m.lire_skill(name)
    except FileNotFoundError:
        raise ApiError(404, "not_found", _t("Cette fiche n'existe pas.")) from None


@route("GET", "/skills", SESSION)
def skills(request):
    """The skills: `name` (the file), `title` (its first « # » line) and `read_when` (its « À lire quand… » line, empty when it has none)."""
    return {"skills": [_skill_entry(name, title) for name, title in _m.lister_skills()]}


@route("GET", "/skills/{name}", SESSION)
def skill(request):
    """One skill with its whole `text`."""
    return {"name": request.params["name"], "text": _skill_text(request.params["name"])}


@route("POST", "/skills", CONFIGURATOR)
def add_skill(request):
    """{"name": "my-notes.md", "text"}: a new skill (letters, digits, hyphens, spaces and the `.md` ending; 60 000 characters at most). Refused (409) when the name is taken: change it with PATCH."""
    body = request.body
    if set(body) != {"name", "text"} or not isinstance(body["name"], str) or not isinstance(body["text"], str):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("name, text"))
    if any(name == body["name"] for name, _title in _m.lister_skills()):
        raise ApiError(409, "exists", _t("Cette fiche existe déjà."))
    _m.ecrire_skill(body["name"], body["text"])
    return 201, skill_view(body["name"])


def skill_view(name):
    return {"name": name, "text": _skill_text(name)}


@route("PATCH", "/skills/{name}", CONFIGURATOR)
def change_skill(request):
    """{"text"}: replaces the text of the skill."""
    if set(request.body) != {"text"} or not isinstance(request.body["text"], str):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("text"))
    _skill_text(request.params["name"])
    _m.ecrire_skill(request.params["name"], request.body["text"])
    return skill_view(request.params["name"])


@route("DELETE", "/skills/{name}", CONFIGURATOR)
def delete_skill(request):
    """Deletes the skill file for good."""
    _skill_text(request.params["name"])
    _m.supprimer_skill(request.params["name"])
    return skills(request)


MEMORY_NOTES = {"context": "CONTEXTE.md", "memory": "MEMOIRE.md"}


@route("GET", "/memory", SESSION)
def memory(request):
    """The two notes the model always has: `context` and `memory`, as text."""
    return {key: _m.lire_memoire(name) for key, name in MEMORY_NOTES.items()}


@route("PATCH", "/memory", CONFIGURATOR)
def change_memory(request):
    """{"context": text} and/or {"memory": text}: replaces the note (60 000 characters at most)."""
    body = request.body
    if not body or set(body) - set(MEMORY_NOTES) or not all(isinstance(value, str) for value in body.values()):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("context, memory"))
    for key, text in body.items():
        _m.ecrire_memoire(MEMORY_NOTES[key], text)
    return memory(request)


# --------------------------------------------------------------------------------------------------------- third-party skills
# Skills published on GitHub (a folder with a SKILL.md): find them, look inside, copy one into a project, update it, remove it. A skill is text the model follows, so nothing is copied
# without `{"confirm": true}`, the card analyses it first (hidden orders, downloads, scripts) and a dangerous or unlicensed one needs its own acceptance. Nothing is ever run.
# Everything that reads GitHub is for the machine itself (`configurator`: it spends the GitHub account of the person) and is refused in strict offline mode (409 `offline`).
# The GitHub token is written and never given back.
def _require_online(verb):
    if _offline.is_active():
        raise ApiError(409, "offline", _t("Mode hors ligne strict : impossible de {}. Désactive-le pour continuer (lutin offline off).").format(verb))


def _skill_body(body, texts, flags):
    names = tuple(texts) + tuple(flags)
    if set(body) - set(names) or any(not isinstance(body.get(key, ""), str) for key in texts) or any(not isinstance(body.get(key, False), bool) for key in flags):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format(", ".join(names)))


def _skill_repo(text):
    """The repository written as « owner/name » or by its address, only when it is in the list of sources."""
    repo = "/".join(_skills.read_repo(text))
    if repo not in {source["depot"] for source in _skills.sources()}:
        raise ApiError(400, "invalid_request", _t("Ce dépôt n'est pas dans ta liste."))
    return repo


def _skill_roots():
    """{id: folder} of the projects."""
    return {entry["id"]: entry["chemin"] for entry in _m.works_state()["liste"]}


def _skill_project(identifier):
    """(id, folder) of the project to install in: the one asked for, else the current one."""
    roots = _skill_roots()
    identifier = identifier or _m.works_state()["actif"]
    if identifier not in roots:
        raise ApiError(400, "invalid_request", _t("Choisis le dossier de travail où installer le skill (Réglages > Dossiers)."))
    return identifier, roots[identifier]


def _skill_sources(listing):
    return [{"repo": source["depot"], "name": source["nom"], "default": bool(source["defaut"])} for source in listing]


def _github_view():
    view = _github.view()
    return {"configured": bool(view["configure"]), "source": {"environnement": "environment", "reglages": "settings"}.get(view["source"], "")}


def _skill_page(value, default=1):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _skill_severity(value):
    return {"aucune": "none"}.get(value, value)


def _skill_hit(skill):
    return {"repo": skill["depot"], "dir": skill["dir"], "name": skill["nom"], "sha": skill["sha"], "files": skill["fichiers"], "bytes": skill["octets"], "scripts": bool(skill["scripts"]),
            "description": skill.get("description", ""), "license": skill.get("licence", ""), "tokens": skill["jetons"]}


@route("GET", "/third-party-skills", SESSION)
def third_party_skills(request):
    """What the page needs when it opens, from this machine only (no network): the `sources` (repositories searched; `default` ones cannot be removed), the `github` account
    (`configured`, and where its token comes from: `environment` or `settings`; the token itself is never given), the `projects` a skill can go in and the `current` one, the
    `indexing` of each repository being read (`done`, `total`, `finished`, `error`) and whether strict `offline` mode is on."""
    state = _m.works_state()
    return {"sources": _skill_sources(_skills.sources()), "github": _github_view(), "projects": [{"id": entry["id"], "name": entry["nom"]} for entry in state["liste"]], "current": state["actif"],
            "indexing": {repo: {"done": item["fait"], "total": item["total"], "finished": item["fini"], "error": item["erreur"]} for repo, item in dict(_skills.INDEXING).items()},
            "offline": bool(_offline.is_active())}


@route("POST", "/third-party-skills/sources", CONFIGURATOR)
def add_skill_source(request):
    """{"repo": "owner/name" or its address}: adds a repository to search (30 at most). Nothing is read from GitHub yet. Answers `{"sources"}`."""
    _skill_body(request.body, ("repo",), ())
    return 201, {"sources": _skill_sources(_skills.ajouter_source(request.body.get("repo")))}


@route("DELETE", "/third-party-skills/sources", CONFIGURATOR)
def remove_skill_source(request):
    """`?repo=owner/name`: removes a repository that was added (the ones offered at the start stay). Answers `{"sources"}`."""
    return {"sources": _skill_sources(_skills.retirer_source(request.query.get("repo", "")))}


@route("PATCH", "/third-party-skills/github", CONFIGURATOR)
def set_github_token(request):
    """{"token": text}: keeps the GitHub token (it lifts the limit of 60 requests an hour); an empty text removes it. Answers `{"github"}` without the token."""
    _skill_body(request.body, ("token",), ())
    if "token" not in request.body:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("token"))
    _github.save(request.body["token"])
    return {"github": _github_view()}


@route("POST", "/third-party-skills/github/test", CONFIGURATOR)
def test_github_token(request):
    """What GitHub says about the account in use: `{"limit", "remaining", "resets_at", "authenticated", "account"}`."""
    _require_online(_t("essayer le compte GitHub"))
    result = _github.test_token(_skills.default_http)
    return {"limit": result["limite"], "remaining": result["restantes"], "resets_at": result["retour"], "authenticated": result["identifie"], "account": result["compte"]}


@route("GET", "/third-party-skills/search", CONFIGURATOR)
def search_third_party_skills(request):
    """`?q=words&repos=a/b,c/d&page=1` (all the sources without `repos`): the skills whose name, path or description holds every word, 20 a page, `{"skills", "total", "page", "more",
    "truncated", "described", "count"}`. Each skill: `repo`, `dir`, `name`, `sha`, `files`, `bytes`, `scripts`, `tokens` and, once read, `description` and `license`."""
    _require_online(_t("chercher des skills sur GitHub"))
    repos = [_skill_repo(item) for item in request.query.get("repos", "").split(",") if item] or [source["depot"] for source in _skills.sources()]
    found = _skills.search(request.query.get("q", "")[:200], repos, _skill_page(request.query.get("page")))
    return {"skills": [_skill_hit(skill) for skill in found["skills"]], "total": found["total"], "page": found["page"], "more": bool(found["suite"]), "truncated": bool(found["tronque"]),
            "described": found["decrits"], "count": found["nombre"]}


@route("GET", "/third-party-skills/repos", CONFIGURATOR)
def find_skill_repositories(request):
    """`?q=words`: repositories of skills found on GitHub by topic, most followed first (`repo`, `stars`, `description`, `updated`); with `listed=1`, the repositories the community lists
    point to, most quoted first (`repo`, `citations`). Adding one to the sources is a separate step."""
    _require_online(_t("chercher des dépôts de skills sur GitHub"))
    query = request.query.get("q", "")[:100]
    if request.query.get("listed") == "1":
        return {"repos": [{"repo": item["depot"], "citations": item["citations"]} for item in _skills.listed_repos(query)]}
    return {"repos": [{"repo": item["depot"], "stars": item["etoiles"], "description": item["description"], "updated": item["maj"]} for item in _skills.search_repos(query)]}


@route("POST", "/third-party-skills/index", CONFIGURATOR)
def index_skill_repository(request):
    """{"repo"}: reads the description of every skill of a source in the background, so that a search also looks in them (long for a large repository). Follow it in `indexing`.
    Answers `{"started": true}`, or `{"started": false}` when it is already running."""
    _skill_body(request.body, ("repo",), ())
    repo = _skill_repo(request.body.get("repo"))
    _require_online(_t("lire les descriptions des skills"))
    if not (_skills.INDEXING.get(repo) or {}).get("fini", True):
        return {"started": False}
    threading.Thread(target=lambda: _skills.indexer(repo), daemon=True, name="skills-indexing").start()
    return 202, {"started": True}


@route("GET", "/third-party-skills/card", CONFIGURATOR)
def third_party_skill_card(request):
    """`?repo=owner/name&dir=path`: all that is needed to decide, read from GitHub and analysed before anything is copied: the text of SKILL.md, the files, the licence, the weight for a small
    model (`heavy`) and the `findings` of the analysis (`severity` `danger` or `attention`; `severity` of the card is `none`, `attention` or `danger`). `installable` says the size is allowed."""
    _require_online(_t("lire la fiche d'un skill"))
    card = _skills.card(_skill_repo(request.query.get("repo", "")), request.query.get("dir", ""))
    return {"repo": card["depot"], "dir": card["dir"], "sha": card["sha"], "name": card["nom"], "description": card["description"], "license": card["licence"], "license_file": card["licence_fichier"],
            "license_repo": card["licence_depot"], "text": card["texte"], "text_truncated": card["texte_coupe"], "files": [{"path": item["chemin"], "bytes": item["octets"]} for item in card["fichiers"]],
            "file_count": card["nombre_fichiers"], "bytes": card["octets"], "scripts": card["scripts"], "tokens": card["jetons_skill"], "heavy": card["lourd"], "claude_fields": card["champs_claude"],
            "findings": [{"severity": item["gravite"], "pattern": item["motif"], "explanation": item["explication"], "file": item["fichier"], "line": item["ligne"], "excerpt": item["extrait"]}
                         for item in card["constats"]], "severity": _skill_severity(card["gravite"]), "too_big": card["trop_gros"], "analysed": card["analyses"], "installable": card["installable"]}


def _installed_skill(skill):
    view = {"project": skill["travail"], "name": skill["nom"], "folder": skill["dossier"], "repo": skill["depot"], "dir": skill["dir"], "sha": skill["sha"], "installed_at": skill["installe"],
            "license": skill["licence"], "severity": _skill_severity(skill["gravite"] or "aucune"), "tokens": skill["jetons"], "description": skill["description"]}
    if "maj" in skill:
        view.update(update=bool(skill["maj"]), gone=bool(skill["disparu"]), error=skill["erreur"])
    return view


@route("GET", "/third-party-skills/installed", SESSION)
def installed_third_party_skills(request):
    """The skills Lutin copied, in every project: `project` (its id), `name`, `folder`, `repo`, `dir`, `sha`, `installed_at`, `license`, `severity`, `tokens`, `description`. Local only."""
    return {"installed": [_installed_skill(skill) for skill in _skills.installed(_skill_roots())]}


@route("GET", "/third-party-skills/updates", CONFIGURATOR)
def third_party_skill_updates(request):
    """The same list, each skill with `update` (it changed in its repository), `gone` (it is not there any more) and `error` (why it could not be checked): one request a repository."""
    _require_online(_t("chercher des mises à jour de skills"))
    return {"installed": [_installed_skill(skill) for skill in _skills.available_updates(_skills.installed(_skill_roots()))]}


def _skill_done(done, repo, folder):
    _m.journaliser(_t("Skill tiers installé : {} ({}, {}).").format(done["nom"], repo, folder))
    return {"name": done["nom"], "folder": done["dossier"], "files": done["fichiers"], "ignored": done["ignores"]}


@route("POST", "/third-party-skills/install", CONFIGURATOR)
def install_third_party_skill(request):
    """{"repo", "dir", "project": optional id (else the current one), "confirm": true, "accept_danger", "accept_no_license"}: copies the folder into `<project>/.claude/skills/<name>/` with its
    signature; nothing is run. `confirm` is always needed. A dangerous card needs `accept_danger`, a skill without any licence needs `accept_no_license`, a name already taken by something
    Lutin did not install is refused. Answers `{"name", "folder", "files", "ignored"}`."""
    body = request.body
    _skill_body(body, ("repo", "dir", "project"), ("confirm", "accept_danger", "accept_no_license"))
    if not body.get("confirm"):
        raise ApiError(400, "confirmation_required", _t("Installer copie les fichiers de ce skill depuis GitHub dans ton dossier de travail : confirme pour continuer."))
    _require_online(_t("installer un skill"))
    repo = _skill_repo(body.get("repo"))
    _, root = _skill_project(body.get("project"))
    done = _skills.install(repo, body.get("dir", ""), root, danger_ok=bool(body.get("accept_danger")), licence_ok=bool(body.get("accept_no_license")))
    return 201, _skill_done(done, repo, body.get("dir", ""))


@route("POST", "/third-party-skills/installed/{name}/update", CONFIGURATOR)
def update_third_party_skill(request):
    """{"project": optional id (else the current one), "confirm": true, "accept_danger", "accept_no_license"}: copies the skill again from where it came, replacing the copy Lutin made.
    The same checks as an installation. Answers `{"name", "folder", "files", "ignored"}`."""
    body = request.body
    _skill_body(body, ("project",), ("confirm", "accept_danger", "accept_no_license"))
    if not body.get("confirm"):
        raise ApiError(400, "confirmation_required", _t("Mettre à jour copie de nouveau les fichiers de ce skill depuis GitHub : confirme pour continuer."))
    _require_online(_t("mettre à jour un skill"))
    project, root = _skill_project(body.get("project"))
    current = next((skill for skill in _skills.installed({project: root}) if skill["nom"] == request.params["name"]), None)
    if current is None:
        raise ApiError(404, "not_found", _t("Ce skill n'a pas été installé par Lutin."))
    done = _skills.install(current["depot"], current["dir"], root, danger_ok=bool(body.get("accept_danger")), licence_ok=bool(body.get("accept_no_license")), remplacer=True, nom=current["nom"])
    return _skill_done(done, current["depot"], current["dir"])


@route("DELETE", "/third-party-skills/installed/{name}", CONFIGURATOR)
def remove_third_party_skill(request):
    """`?project=id` (else the current one): deletes a skill Lutin installed, and only that: a folder without Lutin's signature is never touched. Answers the list of what is left."""
    project, root = _skill_project(request.query.get("project", ""))
    if not any(skill["nom"] == request.params["name"] for skill in _skills.installed({project: root})):
        raise ApiError(404, "not_found", _t("Ce skill n'a pas été installé par Lutin."))
    _skills.retirer(root, request.params["name"])
    _m.journaliser(_t("Skill tiers retiré : {}.").format(request.params["name"][:60]))
    return installed_third_party_skills(request)


# --------------------------------------------------------------------------------------------------------- conversations
def _summary(entry):
    return {"id": entry["id"], "title": entry.get("titre", ""), "updated_at": entry.get("maj", ""), "message_count": int(entry.get("messages") or 0),
            "pinned": bool(entry.get("epingle")), "origin_machine": entry.get("origine", "")}


def _conversation(stored):
    """A stored conversation under its v1 names. The messages keep their shape: it is already the chat format of the engines (role, content, tool_calls…)."""
    return {"id": stored["id"], "title": stored.get("titre", ""), "created_at": stored.get("date", ""), "updated_at": stored.get("maj", stored.get("date", "")),
            "pinned": bool(stored.get("epingle")), "summary": stored.get("resume", ""), "messages": stored.get("messages", [])}


def _read(identifier):
    try:
        return _m.conv_lire(identifier)
    except ValueError:                                     # a malformed identifier or a missing file: the same answer, in the caller's language
        raise ApiError(404, "not_found", _t("Conversation inconnue.")) from None


def _not_running(identifier):
    if identifier in _m.TOURS_ACTIFS:
        raise ApiError(409, "turn_running", _t("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la."))


@route("GET", "/conversations", SESSION)
def conversations(request):
    """Every conversation, pinned ones first, then the most recent. `?q=words` searches their titles and texts instead (accents ignored, every word
    needed, best first), each with an `extract` around what was found (ADR 0017: the full-text index of the store)."""
    query = request.query.get("q", "").strip()
    if not query:
        return {"conversations": [_summary(entry) for entry in _m.conv_liste()]}
    from . import store as _store
    if len(query) > 200:
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("q", "200"))
    listed = {entry["id"]: entry for entry in _m.conv_liste()}
    return {"query": query, "conversations": [dict(_summary(listed[found["id"]]), extract=found.get("extrait", "")) for found in _store.search(query, 50) if found["id"] in listed]}


@route("POST", "/conversations", SESSION)
def create_conversation(request):
    return 201, _conversation(_m.conv_nouvelle())


@route("GET", "/conversations/{id}", SESSION)
def conversation(request):
    return _conversation(_read(request.params["id"]))


@route("PATCH", "/conversations/{id}", SESSION)
def update_conversation(request):
    """Changes the title and/or the pin: {"title": "...", "pinned": true}. Refused while the conversation is answering (the end of the turn would write over it)."""
    identifier, body = request.params["id"], request.body
    unknown = sorted(set(body) - {"title", "pinned"})
    if unknown or not body:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("title, pinned"))
    _read(identifier)
    _not_running(identifier)
    if "title" in body:
        if not isinstance(body["title"], str) or not body["title"].strip():
            raise ApiError(400, "invalid_request", _t("Le titre doit être un texte non vide."))
        _m.conv_renommer(identifier, body["title"])
    if "pinned" in body:
        if not isinstance(body["pinned"], bool):
            raise ApiError(400, "invalid_request", _t("« pinned » doit être vrai ou faux."))
        _m.pin_conversation(identifier, body["pinned"])
    return _conversation(_read(identifier))


# The options of ONE conversation: what the page shows beside the field (mode, automatic approvals…). They override the settings of the machine for that conversation,
# except the two automatic approvals, which never come from the settings: false until the user ticks them for this conversation (storage.appliquer_options).
OPTIONS = {
    "mode": ("mode", "string"), "thinking": ("reflexion", "boolean"), "web": ("web", "boolean"), "dry_run": ("essai_a_blanc", "boolean"),
    "auto_approve_writes": ("auto_ecriture", "boolean"), "auto_approve_commands": ("auto_commandes", "boolean"),
    "num_predict": ("num_predict", "integer"), "mission_hours": ("mission_duree_h", "integer"),
}
OPTION_MODES = dict(SETTING_WORDS["mode"], mission="mission")          # « mission » is chosen conversation by conversation, never as a setting
OPTION_CHOICES = {"num_predict": _storage.LONGUEURS, "mission_hours": _storage.DUREES_MISSION}
MISSION_HOURS_DEFAULT = 8


def _options_view(identifier):
    stored = _m.options_lire(identifier)
    effective = _m.appliquer_options(_m.reglages(), identifier)
    shown = {name: effective[key] for name, (key, _) in OPTIONS.items() if key in effective}
    shown["mode"] = OPTION_MODES.get(effective["mode"], effective["mode"])
    shown["mission_hours"] = stored.get("mission_duree_h", MISSION_HOURS_DEFAULT)
    return shown


@route("GET", "/conversations/{id}/options", SESSION)
def conversation_options(request):
    identifier = request.params["id"]
    _read(identifier)
    return _options_view(identifier)


@route("PATCH", "/conversations/{id}/options", SESSION)
def update_conversation_options(request):
    """Changes some options of the conversation: {"auto_approve_commands": true, "mode": "technical"}. All or nothing; answers every option as it now stands.
    Allowed while a turn runs, as for the French route: a box ticked during an answer counts from the next tool."""
    identifier, body, changed = request.params["id"], request.body, {}
    _read(identifier)
    unknown = sorted(set(body) - set(OPTIONS))
    if unknown:
        raise ApiError(400, "invalid_request", _t("Réglage inconnu : {}.").format(", ".join(unknown)))
    words = {v1: stored for stored, v1 in OPTION_MODES.items()}
    for name, value in body.items():
        key, kind = OPTIONS[name]
        if name == "mode":
            valid, expected = value in words, ", ".join(words)
        elif name in OPTION_CHOICES:
            valid, expected = KINDS["integer"](value) and value in OPTION_CHOICES[name], ", ".join(str(choice) for choice in OPTION_CHOICES[name])
        else:
            valid, expected = KINDS[kind](value), kind
        if not valid:
            raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format(name, expected))
        changed[key] = words[value] if name == "mode" else value
    if changed:
        _m.options_ecrire(identifier, changed)
    return _options_view(identifier)


@route("DELETE", "/conversations/{id}", SESSION)
def delete_conversation(request):
    identifier = request.params["id"]
    _read(identifier)
    _not_running(identifier)
    _mission.oublier_conversation(identifier)          # its mission, if any, ends with it
    _m.conv_supprimer(identifier)
    return {"deleted": True}


@route("POST", "/conversations/{id}/stop", SESSION)
def stop_turn(request):
    """The Stop button: the model, the tools and the pending approvals of the running turn stop. `was_running` says whether there was anything to stop."""
    return {"was_running": bool(_m.arreter_conversation(request.params["id"]).get("actif"))}


# ----------------------------------------------------------------------------------------------------------------- backup
# One .zip of the data (settings, conversations, memory), and putting one back (docs/modernization/PARITY.md, item 3). Both need `configurator`:
# an archive holds every conversation and the memory (the old page let any session download it: tightened here). A restore keeps the state before
# it in a zip of its own and asks for a restart.
def _backup_folders():
    config = _m.chemin_config()
    return {"config": config.parent if config else None, "donnees": _m.DONNEES, "memoire": _m.MEMOIRE}


@route("GET", "/backup/where", SESSION)
def backup_where(request):
    """Where this Lutin keeps its data: the folders a backup takes, and the folder of the backups made before a migration or a restore."""
    folders = _backup_folders()
    return {"config": str(folders["config"] or ""), "data": str(folders["donnees"]), "memory": str(folders["memoire"]), "backups": str(Path(_m.DONNEES) / "sauvegardes")}


@route("GET", "/backup", CONFIGURATOR)
def backup_download(request):
    """The .zip of the data, to keep elsewhere (lutin restore, or POST /backup/restore, puts it back)."""
    import io
    from datetime import datetime
    from . import backup as _backup
    buffer = io.BytesIO()
    try:
        _backup.export(_backup_folders(), buffer)
    except _backup.BackupError as refused:
        raise ApiError(400, "invalid_request", str(refused)) from None
    name = "lutin-backup-{}.zip".format(datetime.now().strftime("%Y%m%d-%H%M%S"))
    return Binary(buffer.getvalue(), "application/zip", {"Content-Disposition": 'attachment; filename="{}"'.format(name)})


@route("POST", "/backup/restore", CONFIGURATOR, raw=True, limit=1024 ** 3)
def backup_restore(request):
    """The bytes of a .zip made by Lutin as the body: checked whole before anything is written, the state before it kept in donnees/import/, then
    put back. Answers {files, kept_before, version, date, restart_needed}."""
    import io
    from . import access as _access
    done = _access.restore_stream(io.BytesIO(request.raw), len(request.raw))
    return {"files": done["fichiers"], "kept_before": done["secours"], "version": done["version"], "date": done["date"], "restart_needed": bool(done.get("redemarrage_necessaire"))}


# --------------------------------------------------------------------------------------------------------- Lutin's version
# Lutin's own version (not the engines', not a paired machine's): the check made at launch at most once a day (lutin.updates, a file of the cache,
# never the network on a reading), « check now », ignoring one version, updating as `lutin update --app` does, and the restart. Nothing is installed
# without the person: the update is asked for from this machine, as on the old page.
UPDATE_STATES = {"": "idle", "en cours": "running", "erreur": "failed", "a_jour": "up_to_date", "redemarrage": "restarting", "fini": "installed"}


def _new_version():
    """{version, page, command} when the launch check found a newer version that was not ignored; None otherwise. Never the network."""
    found = _m.nouvelle_version_lutin()
    return {"version": found["version"], "page": found["page"], "command": found["commande"]} if found else None


def _version_cache():
    path = os.environ.get("LUTIN_VERSION_CACHE")
    if not path:
        raise ApiError(409, "not_available", _t("Pas de vérification de version dans ce mode de lancement."))
    return path


def _update_view():
    from . import access as _access
    from . import updates as _updates
    state = _access.update_state()
    return {"state": UPDATE_STATES.get(state["etat"], "failed"), "lines": [str(line) for line in state["lignes"]], "before": state["avant"],
            "after": state["apres"], "command": _updates.commande_mise_a_jour(), "can_update": not _access.in_docker(),
            "can_check": bool(os.environ.get("LUTIN_VERSION_CACHE")), "can_restart": _access.can_restart()}


@route("GET", "/lutin/update", SESSION)
def lutin_update_state(request):
    """Where an update of Lutin stands: `state` is idle, running, failed, up_to_date, restarting (Lutin stops and its supervisor starts it again) or
    installed (nothing restarts it: the person does), with the `lines` it wrote, the versions `before` and `after`, the `command` that does the same
    (`lutin update`, or the docker one), and what this launch allows: updating from the page (not in Docker), checking, restarting."""
    return _update_view()


@route("POST", "/lutin/update", CONFIGURATOR)
def lutin_update(request):
    """Starts the update of Lutin in the background (backup, download checked against its SHA256 sum, install, then a restart when something
    restarts Lutin); follow it with GET /lutin/update. 409 `in_docker` (the image is replaced instead), `offline`, `turn_running`, `update_running`."""
    from . import access as _access
    if _access.in_docker():
        raise ApiError(409, "in_docker", _t("Dans Docker, la mise à jour se fait en récupérant la nouvelle image : docker compose pull && docker compose up -d"))
    if _offline.is_active():
        raise ApiError(409, "offline", _t("Mode hors ligne strict : Lutin n'est pas mis à jour."))
    if _m.TOURS_ACTIFS:
        raise ApiError(409, "turn_running", _t("Une réponse est en cours : attends la fin avant de mettre à jour."))
    try:
        _access.update()
    except ValueError as refused:          # the one condition left: an update already running (or a turn that began in between)
        raise ApiError(409, "update_running", str(refused)) from None
    return _update_view()


@route("POST", "/lutin/check", SESSION)
def lutin_check(request):
    """« Check for updates »: one request to GitHub now, not waiting for the daily check. Answers {current, latest, new_version} (`new_version` as in
    GET /status: null when up to date or ignored). 409 `not_available` when this launch keeps no version cache, 503 `unreachable` with the reason."""
    path = _version_cache()
    from . import updates as _updates
    before = _updates.lire_fichier_version(path).get("date") or 0
    checked = _updates.check_lutin({"cache": str(Path(path).parent)}, force=True)
    if (checked.get("date") or 0) <= before:
        raise ApiError(503, "unreachable", _t("Impossible de joindre GitHub : {}").format(checked.get("erreur") or "?"))
    return {"current": _m.VERSION, "latest": str(_updates.lire_fichier_version(path).get("version", "")), "new_version": _new_version()}


@route("POST", "/lutin/ignored-version", SESSION)
def lutin_ignore_version(request):
    """« Ignore this version » `{version}`: no reminder for that one; the next one is announced. Answers {new_version}."""
    version = str(request.body.get("version") or "").strip()[:40]
    if not version:
        raise ApiError(400, "invalid_request", _t("Indique la version à ignorer."))
    from . import updates as _updates
    _updates.ignorer_version(_version_cache(), version)
    return {"new_version": _new_version()}


@route("POST", "/lutin/restart", CONFIGURATOR)
def lutin_restart(request):
    """« Restart Lutin »: answers, then Lutin stops with the code its supervisor (`lutin`, the icon, Docker) starts again. 409 `cannot_restart` when
    nothing would start it again, `turn_running` during an answer."""
    from . import access as _access
    if not _access.can_restart():
        raise ApiError(409, "cannot_restart", _t("Lutin n'a pas été lancé par la commande « lutin » : relance-le toi-même."))
    try:
        _access.restart()
    except ValueError as refused:
        raise ApiError(409, "turn_running", str(refused)) from None
    return {"restarting": True}


# ----------------------------------------------------------------------------------------------------------------- health
# What the old Health page showed (docs/modernization/PARITY.md, item 2): the state of memory, graphics card and disk, what is loaded and what
# occupies the machine, the self-test, what the models and tools did, and what left this machine. Reading and unloading are `session`, as the old
# routes; clearing a log is `configurator`, as there.
HEALTH_LEVELS = {"ok": "ok", "attention": "warning", "alerte": "warning", "critique": "critical"}


def _health_item(item):
    return {"id": item.get("id", ""), "name": item.get("nom", ""), "level": HEALTH_LEVELS.get(item.get("niveau"), item.get("niveau", "")), "value": item.get("valeur", ""),
            "advice": item.get("conseil", "")}


def _loaded(entry):
    return {"id": entry.get("id", ""), "kind": entry.get("genre", ""), "engine": entry.get("moteur", ""), "name": entry.get("nom", ""), "vram": entry.get("vram"),
            "ram": entry.get("ram"), "size": entry.get("taille"), "detail": entry.get("detail", ""), "unloadable": bool(entry.get("dechargeable")), "closable": bool(entry.get("fermable"))}


def _resources():
    from . import loaded_resources as _loaded_resources
    state = _loaded_resources.state()
    ram, vram = state.get("ram") or {}, state.get("vram")
    return {"ram": {"total": ram.get("total"), "free": ram.get("libre"), "commit_free": ram.get("engagement_libre")},
            "vram": {"name": vram.get("nom", ""), "total": vram.get("total"), "used": vram.get("utilise"), "free": vram.get("libre")} if isinstance(vram, dict) else None,
            "loaded": [_loaded(entry) for entry in state.get("charges") or []],
            "programs": [{"name": p.get("nom", ""), "label": p.get("libelle", ""), "count": p.get("nombre", 0), "bytes": p.get("octets", 0), "ai": bool(p.get("ia"))} for p in state.get("programmes") or []]}


@route("GET", "/health", SESSION)
def health(request):
    """The state of this machine for the models (memory, graphics card, disk, each with a level and advice), what is loaded, and the programs that
    occupy the most memory."""
    state = _m.health_state()
    return {"level": HEALTH_LEVELS.get(state.get("niveau"), state.get("niveau", "")), "items": [_health_item(item) for item in state.get("items") or []], "resources": _resources()}


@route("POST", "/health/unload", SESSION)
def health_unload(request):
    """{"id": "..."} (an entry of `loaded`): unloads it (a model of Ollama, the llama.cpp server, ComfyUI). Answers the resources."""
    from . import loaded_resources as _loaded_resources
    if set(request.body) != {"id"} or not isinstance(request.body["id"], str) or not request.body["id"]:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("id"))
    done = _loaded_resources.decharger(request.body["id"])
    return {"message": done.get("message", ""), "resources": _resources()}


@route("POST", "/health/free-graphics-memory", SESSION)
def health_free_graphics_memory(request):
    """Unloads every model Lutin keeps in memory (Ollama's, the llama.cpp server, and the ExLlamaV3, Colibri or LM Studio server it manages)."""
    if request.body:
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("-"))
    done = _m.liberer_vram(tout=True)
    return {"message": done.get("message", ""), "resources": _resources()}


@route("POST", "/health/self-test", SESSION)
def health_self_test(request):
    """Checks end to end that everything works: {"deep": true} also makes the real model answer (it loads it: up to a minute)."""
    if set(request.body) - {"deep"} or not isinstance(request.body.get("deep", False), bool):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("deep"))
    done = _m.run_selftest(request.body.get("deep", False))
    return {"ok": bool(done["ok"]), "deep": bool(done["profond"]), "checks": [{"name": r["nom"], "ok": bool(r["ok"]), "important": bool(r["important"]), "detail": r["detail"],
                                                                           "seconds": r["duree"]} for r in done["resultats"]]}


@route("GET", "/health/activity", SESSION)
def health_activity(request):
    """What the models and the tools did here (names, durations, counts; never the text of a message)."""
    from . import observatory as _observatory
    events = _observatory.read(400)
    summary = _observatory.summary(events)
    return {"models": [{"model": m.get("modele", ""), "machine": m.get("machine", ""), "turns": m.get("tours", 0), "tokens": m.get("jetons", 0), "tokens_per_s": m.get("tok_s")}
                       for m in summary.get("modeles") or []],
            "tools": [{"tool": o.get("outil", ""), "calls": o.get("appels", 0), "failures": o.get("echecs", 0), "duration_ms": o.get("duree_ms", 0)} for o in summary.get("outils") or []],
            "retries": summary.get("relances") or {}, "routed": summary.get("routages") or 0}


@route("DELETE", "/health/activity", CONFIGURATOR)
def clear_health_activity(request):
    from . import observatory as _observatory
    _observatory.clear()
    return {"cleared": True}


@route("GET", "/health/outbound", SESSION)
def health_outbound(request):
    """What left this machine: the searches sent to an outside service (when, which service, the request with what was removed from it, whether it worked)."""
    from . import outbound as _outbound
    return {"entries": [{"at": e.get("quand", ""), "service": e.get("service", ""), "request": e.get("requete", ""), "removed": list(e.get("retire") or []), "ok": bool(e.get("ok"))}
                        for e in _outbound.read(60)]}


@route("DELETE", "/health/outbound", CONFIGURATOR)
def clear_health_outbound(request):
    from . import outbound as _outbound
    _outbound.clear()
    return {"cleared": True}


# ------------------------------------------------------------------------------------------- the changes of the last request
# What the last request of a conversation did to files (the tools that write: modifier, ecrire, modifier_plusieurs; not the effects of commands),
# with the differences, and the way back: every file, or one. The backups are those the tools made before writing (donnees/sauvegardes/).
CHANGE_STATES = {"créé": "created", "modifié": "modified", "supprimé": "deleted"}


def _changes(identifier):
    review = _m.turn_review(identifier)
    return {"undoable": bool(review["fichiers"]), "files": [{
        "path": entry["chemin"], "state": CHANGE_STATES.get(entry["etat"], entry["etat"]), "binary": bool(entry["binaire"]), "diff": entry["diff"],
        "added": entry["plus"], "removed": entry["moins"], "changed_since": bool(entry["modifie_depuis"])} for entry in review["fichiers"]]}


@route("GET", "/conversations/{id}/changes", SESSION)
def conversation_changes(request):
    """The files the last request changed (created, modified, deleted), each with its differences and whether someone changed it since."""
    _read(request.params["id"])
    return _changes(request.params["id"])


@route("POST", "/conversations/{id}/changes/undo", SESSION)
def undo_conversation_changes(request):
    """Puts back the files of the last request as they were before it: every one, or `{"path": "..."}` only. A file changed since by someone else is
    left as it is and said (`skipped`). The model is told in the conversation. 409 `turn_running` during an answer, `nothing_to_undo` when nothing is left."""
    identifier, body = request.params["id"], request.body
    if set(body) - {"path"} or ("path" in body and (not isinstance(body["path"], str) or not body["path"])):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format("path"))
    _read(identifier)
    _not_running(identifier)
    if not _changes(identifier)["undoable"]:
        raise ApiError(409, "nothing_to_undo", _t("Aucune modification de fichier à annuler dans cette conversation."))
    try:
        done = _m.undo_turn(identifier, body.get("path"))
    except ValueError as refused:
        raise ApiError(409, "nothing_to_undo", str(refused)) from None
    return {"restored": done["retablis"], "skipped": done["ignores"], **_changes(identifier)}


# ---------------------------------------------------------------------------------------------------------------- uploads
@route("POST", "/images", SESSION, raw=True, limit=_images.MAX_SIZE)
def upload_image(request):
    """An image for the next message: the bytes of a PNG, JPEG, GIF or WebP as the body (the type is recognised from the content, never from a header). Answers its identifier."""
    identifier = _images.save(request.raw)
    return 201, {"id": identifier, "url": "{}/images/{}".format(PREFIX, identifier)}


@route("GET", "/images/{id}", READ)
def image(request):
    """An image sent in a conversation. READ: a browser tag cannot send the page token, the session cookie is what it has."""
    try:
        data, content_type = _images.read_image(request.params["id"])
    except ValueError:
        raise ApiError(404, "not_found", _t("Image inconnue.")) from None
    return Binary(data, content_type, {"Content-Security-Policy": "default-src 'none'; sandbox"})


@route("POST", "/attachments", SESSION, raw=True, limit=_pieces.MAX_SIZE)
def upload_attachment(request):
    """A document for the next message: the bytes of the file as the body, its name in `X-Name` (URL-encoded). The text is extracted at once: a file with none is refused."""
    name = urllib.parse.unquote(request.handler.headers.get("X-Name") or "")
    identifier, shown, characters = _pieces.save(request.raw, name)
    return 201, {"id": identifier, "name": shown, "characters": characters}


@route("GET", "/attachments/{id}", READ)
def download_attachment(request):
    """A document sent in a conversation, as it was sent. READ, like the images: a link in the page carries the session cookie and not the page token.
    Always a download, never displayed (a document is not trusted to be harmless in the page's own origin); `?name=` is the name the file is saved under."""
    try:
        data = _pieces.chemin(request.params["id"]).read_bytes()
    except (ValueError, OSError):
        raise ApiError(404, "not_found", _t("Fichier joint inconnu.")) from None
    name = _pieces.clean_name(request.query.get("name") or "") or request.params["id"]
    quoted = urllib.parse.quote(name)
    return Binary(data, "application/octet-stream", {"Content-Disposition": "attachment; filename*=UTF-8''" + quoted, "Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff"})


# ------------------------------------------------------------------------------------------------- what a tool produced
# A tool result can carry the images a tool generated (`medias`: identifiers read through GET /images/{id}, `medias_fichiers`: where each is saved) and the
# files it created (`fichiers_joints`: {id, nom, taille, chemin}). The stored messages keep these names, as they keep `pieces`. Opening and deleting act on
# this machine's disk: `configurator`, as on the old page; downloading is a link, so READ.
def _produced_file(identifier, file_id):
    if not RE_FILE_ID.match(file_id):
        raise ApiError(404, "not_found", _t("Ce fichier n'est plus dans la conversation."))
    _read(identifier)
    try:
        _produced.find(identifier, file_id)
    except ValueError as missing:
        raise ApiError(404, "not_found", str(missing)) from None


@route("GET", "/conversations/{id}/files/{file}", READ)
def download_produced_file(request):
    """A file a tool created in this conversation, read from its place on the disk (only inside the allowed folders). Always a download, as the attachments."""
    identifier, file_id = request.params["id"], request.params["file"]
    _produced_file(identifier, file_id)
    try:
        data, _, name = _produced.read(identifier, file_id)
    except ValueError as missing:
        raise ApiError(404, "not_found", str(missing)) from None
    return Binary(data, "application/octet-stream", {"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name),
                                                    "Content-Security-Policy": "default-src 'none'; sandbox", "X-Content-Type-Options": "nosniff"})


@route("POST", "/conversations/{id}/files/{file}/open", CONFIGURATOR)
def open_produced_file(request):
    """Asks this machine's system to open the file with the application chosen for its type (documents and media only). 409 `cannot_open` otherwise."""
    identifier, file_id = request.params["id"], request.params["file"]
    _produced_file(identifier, file_id)
    if not _produced.opening_possible():
        raise ApiError(409, "cannot_open", _t("Ce système ne peut pas ouvrir de fichier (pas d'écran) : télécharge-le plutôt."))
    try:
        _produced.open_item(identifier, file_id)
    except ValueError as refused:
        raise ApiError(409, "cannot_open", str(refused)) from None
    return {"opened": True}


@route("DELETE", "/conversations/{id}/files/{file}", CONFIGURATOR)
def delete_produced_file(request):
    """Removes the file from the conversation and deletes it from the disk (when it is still inside the allowed folders). 409 `turn_running` during an answer."""
    identifier, file_id = request.params["id"], request.params["file"]
    _produced_file(identifier, file_id)
    _not_running(identifier)
    try:
        done = _produced.remove(identifier, file_id)
    except ValueError as refused:
        raise ApiError(409, "turn_running", str(refused)) from None
    return {"deleted": True, "file_deleted": bool(done["fichier_supprime"])}


@route("DELETE", "/conversations/{id}/media/{image}", CONFIGURATOR)
def delete_generated_image(request):
    """Removes a generated image from the conversation, deletes the copy Lutin keeps when nothing cites it any more, and the file in ComfyUI's output folder."""
    identifier, image_id = request.params["id"], request.params["image"]
    if not RE_FILE_ID.match(image_id) or not any(image_id in (message.get("medias") or []) for message in _read(identifier)["messages"]):
        raise ApiError(404, "not_found", _t("Cette image n'est plus dans la conversation."))
    _not_running(identifier)
    try:
        done = _m.delete_media(identifier, image_id)
    except ValueError as refused:
        raise ApiError(409, "turn_running", str(refused)) from None
    return {"deleted": True, "file_deleted": bool(done["fichier_supprime"])}


# ----------------------------------------------------------------------------------------------------------------- turns
# The answer stream (API_V1.md, rule 6): application/x-ndjson, one event per line, an empty line as a heartbeat. The agent emits French events; they are
# renamed here, at the boundary, field by field. A type or a field that is not in this table goes through unchanged: tests/test_api_v1_turns.py reads the
# source and fails when the agent emits one that the table does not know.
TASK_STATES = {"a_faire": "todo", "en_cours": "in_progress", "fait": "done"}
EVENTS = {
    "debut": ("start", {"conversation": "conversation_id"}),
    "texte": ("text", {"texte": "text"}),
    "pensee": ("thinking", {"texte": "text"}),
    "outil": ("tool_call", {"nom": "name", "args": "arguments"}),
    "resultat": ("tool_result", {"nom": "name", "texte": "text", "medias": "media", "medias_fichiers": "media_files", "fichiers_joints": "attached_files"}),
    "approbation": ("approval_request", {"id": "id", "titre": "title", "detail": "detail", "diff": "diff", "raison": "reason", "suspendu": "auto_approval_suspended", "retenir": "can_remember"}),
    "accord_suspendu": ("auto_approval_suspended", {"raison": "reason"}),
    "accord_retabli": ("auto_approval_restored", {}),
    "choix_memoire": ("memory_choice", {"conversation": "conversation_id"}),
    "taches": ("tasks", {"liste": "tasks"}),
    "etat": ("status", {"texte": "text"}),
    "info": ("notice", {"texte": "text"}),
    "essai": ("dry_run", {"titre": "title", "detail": "detail", "diff": "diff"}),
    "erreur": ("error", {"texte": "message"}),
    "jetons": ("tokens", {"utilise": "used", "total": "total", "reel": "measured"}),
    "vitesse": ("speed", {"ecriture": "write_tokens_per_s", "lecture": "read_tokens_per_s", "chargement": "load_s", "total": "total_s", "jetons": "tokens"}),
    "fin": ("end", {"conversation": "conversation"}),
}
TURN_FIELDS = {"message": "message", "model": "modele", "thinking": "reflexion", "replace_from": "remplacer_depuis", "images": "images", "attachments": "pieces",
               "workspace": "travail", "machine": "machine"}


def event(stored):
    """One event of the answer stream under its v1 names. Tool names and their arguments are what the model wrote: they are not translated (ADR 0007)."""
    known = EVENTS.get(stored.get("type")) if isinstance(stored, dict) else None
    if known is None:
        return stored
    name, fields = known
    if name == "error":                                    # the shape of every v1 error
        return {"type": name, "error": {"code": "turn_failed", "message": stored.get("texte", "")}}
    translated = {"type": name}
    translated.update((fields.get(key, key), value) for key, value in stored.items() if key != "type")
    if name == "end" and isinstance(stored.get("conversation"), dict):
        translated["conversation"] = {"id": stored["conversation"].get("id", ""), "title": stored["conversation"].get("titre", "")}
    if name == "tasks":
        translated["tasks"] = [{"text": task.get("texte", ""), "state": TASK_STATES.get(task.get("etat"), "todo")} for task in stored.get("liste") or [] if isinstance(task, dict)]
    return translated


@route("POST", "/conversations/{id}/turns", SESSION)
def create_turn(request):
    """Sends a message in a conversation and streams the answer: {"message": "..."} and, optionally, `model`, `thinking`, `replace_from` (the index of the
    user message to rewrite from), `images` and `attachments` (identifiers of uploaded files), `workspace`. A refusal comes before the stream, as an
    ordinary error: 400 `invalid_request`, 409 `turn_running` or `workspace_conflict`, 429 `too_many_turns`. Once the stream has begun, a failure is an
    `error` event. The turn itself is the one the French route runs (`lutin.server.Gestionnaire._chat`), mission mode included."""
    identifier, body = request.params["id"], request.body
    if set(body) - set(TURN_FIELDS) or not isinstance(body.get("message"), str):
        raise ApiError(400, "invalid_request", _t("Champs acceptés : {}.").format(", ".join(TURN_FIELDS)))
    _read(identifier)
    handler = request.handler
    handler._flux_v1 = True
    payload = {TURN_FIELDS[key]: value for key, value in body.items()}
    if isinstance(body.get("attachments"), list):          # {"id", "name"} in v1, {"id", "nom"} for the function underneath
        payload["pieces"] = [{"id": item.get("id"), "nom": item.get("name")} if isinstance(item, dict) else item for item in body["attachments"]]
    return Streamed(lambda: handler._chat(dict(payload, conversation=identifier)))


@route("POST", "/conversations/{id}/memory-choice", SESSION)
def answer_memory_choice(request):
    """Answers the `memory_choice` event of a long conversation: {"choice": "summary" | "file"}, and `remember` to make it the setting. The turn is waiting for it."""
    body = request.body
    choices = {"summary": "resume", "file": "fichier"}
    if set(body) - {"choice", "remember"} or body.get("choice") not in choices or not isinstance(body.get("remember", False), bool):
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("choice", ", ".join(choices)))
    if not _m.repondre_choix_memoire(request.params["id"], choices[body["choice"]], body.get("remember", False)):
        raise ApiError(409, "no_pending_choice", _t("Plus de question en attente pour cette conversation."))
    return {"choice": body["choice"]}


# ------------------------------------------------------------------------------------------------------------- approvals
@route("POST", "/approvals/{id}", SESSION)
def answer_approval(request):
    """Answers a pending action: {"approved": true}. `restore_auto_approval` re-enables the automatic approvals suspended after a web read, for this request only.
    `remember` (`once`, `chat`, `always`) keeps a « yes » given to a command whose request said `can_remember`: for the rest of the conversation, or as a rule
    (`always` needs the right to configure: a paired device cannot write a permanent rule)."""
    body = request.body
    if not isinstance(body.get("approved"), bool):
        raise ApiError(400, "invalid_request", _t("« approved » doit être vrai ou faux."))
    remember = body.get("remember", "once")
    if remember not in ("once", "chat", "always"):
        raise ApiError(400, "invalid_request", _t("Valeur invalide pour « {} » (attendu : {}).").format("remember", "once, chat, always"))
    if remember == "always" and not request.handler._configurateur():
        raise ApiError(403, "configurator", _t("Une règle permanente s'enregistre depuis cette machine."))
    try:
        _m.repondre_attente(request.params["id"], body["approved"], bool(body.get("restore_auto_approval")), remember)
    except ValueError as gone:
        raise ApiError(404, "not_found", str(gone)) from None
    return {"approved": body["approved"]}
