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

import json
import re
import urllib.parse
from dataclasses import dataclass, field

from . import core as _m
from . import i18n as _i18n
from . import machines as _machines
from . import mission as _mission
from . import offline as _offline
from . import security as _sec
from .i18n import t as _t

PREFIX = "/api/v1"
PUBLIC, SESSION, CONFIGURATOR, LOCAL = "public", "session", "configurator", "local"
RIGHTS = (PUBLIC, SESSION, CONFIGURATOR, LOCAL)
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


@dataclass(frozen=True)
class Streamed:
    """What a route returns when the answer is written line by line (the turn stream): `write` is called once the checks of the route have passed."""
    write: object


@dataclass
class Request:
    handler: object                                   # the HTTP request handler (lutin.server.Gestionnaire)
    params: dict = field(default_factory=dict)        # the {names} of the route template
    query: dict = field(default_factory=dict)
    body: dict = field(default_factory=dict)


def route(method, template, right):
    """Declares a route: `@route("GET", "/conversations/{id}", SESSION)`. A {name} matches one path segment."""
    assert right in RIGHTS and template.startswith("/")

    def register(function):
        pattern = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template) + "$")
        ROUTES.append(Route(method, template, right, function, pattern))
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


def dispatch(handler, method):
    """Answers a request whose path starts with /api/v1/. The caller has already checked Host and Origin."""
    parts = urllib.parse.urlsplit(handler.path)
    path = parts.path[len(PREFIX):] or "/"
    streamed = None
    try:
        if method in WITH_BODY:
            body = _read_body(handler)
        else:
            body = {}
            discard_body(handler)                         # a GET or a DELETE sent with a body: not used, but read
        matching = [(r, m) for r in ROUTES for m in [r.pattern.match(path)] if m]
        found = next(((r, m) for r, m in matching if r.method == method), None)
        if found is None:
            _check_right(handler, SESSION)                 # an unknown address tells nothing to a caller without a session
            if matching:
                raise ApiError(405, "method_not_allowed", _t("Méthode non permise pour cette route."))
            raise ApiError(404, "not_found", _t("Route inconnue."))
        entry, match = found
        _check_right(handler, entry.right)
        query = {k: v[-1] for k, v in urllib.parse.parse_qs(parts.query).items()}
        result = entry.handler(Request(handler, {k: urllib.parse.unquote(v) for k, v in match.groupdict().items()}, query, body))
        if isinstance(result, Streamed):
            streamed = result
        else:
            status, payload = result if isinstance(result, tuple) else (200, result)
    except ApiError as refused:
        status, payload = refused.status, error(refused.code, refused.message)
    except _offline.HorsLigne as offline:                  # strict offline mode: the action needs the network
        status, payload = 409, error("offline", str(offline))
    except ValueError as invalid:                          # the functions underneath say what is wrong with a ValueError written for the user
        status, payload = 400, error("invalid_request", str(invalid))
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
    return {
        "version": _m.VERSION,
        "language": _i18n.langue(),
        "access": {"level": ACCESS_LEVELS.get(_m.SECURITE.niveau, _m.SECURITE.niveau), "can_configure": bool(request.handler._configurateur())},
        "offline": bool(_offline.actif()),
        "engine": {"id": engine.id, "name": engine.nom, "running": bool(state["actif"])},
        "model": str(settings.get("modele") or ""),
        "installed_models": list(state["installes"]),
        "workspace": {"path": str(_m.RACINE)},
        "active_turns": sorted(_m.TOURS_ACTIFS),
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
    "data_cap_gb": ("plafond_donnees_go", "number"), "command_ram_limit_gb": ("limite_ram_commande_go", "number"), "free_for_comfyui": ("liberer_si_comfy", "boolean"),
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
            "downloads": [_download(name, stored) for name, stored in sorted(_m.PULLS.items())]}


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
    return {"conversations": [_summary(entry) for entry in _m.conv_liste()]}


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
        _m.epingler_conversation(identifier, body["pinned"])
    return _conversation(_read(identifier))


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
    "approbation": ("approval_request", {"id": "id", "titre": "title", "detail": "detail", "diff": "diff", "raison": "reason", "suspendu": "auto_approval_suspended"}),
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
               "workspace": "travail"}


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
    return Streamed(lambda: handler._chat(dict({TURN_FIELDS[key]: value for key, value in body.items()}, conversation=identifier)))


# ------------------------------------------------------------------------------------------------------------- approvals
@route("POST", "/approvals/{id}", SESSION)
def answer_approval(request):
    """Answers a pending action: {"approved": true}. `restore_auto_approval` re-enables the automatic approvals suspended after a web read, for this request only."""
    body = request.body
    if not isinstance(body.get("approved"), bool):
        raise ApiError(400, "invalid_request", _t("« approved » doit être vrai ou faux."))
    try:
        _m.repondre_attente(request.params["id"], body["approved"], bool(body.get("restore_auto_approval")))
    except ValueError as gone:
        raise ApiError(404, "not_found", str(gone)) from None
    return {"approved": body["approved"]}
