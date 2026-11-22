"""The models of an engine, the same way for every engine (ADR 0020, stage 2).

Each engine has one *model source* with the same six operations: `installed`, `recommended`, `search`, `variants`, `download`, `remove` (and `check`, the
newer versions and the new models of the servers Lutin manages, asked on demand). They answer with
the same entry whatever the engine, so that one page can show them (stage 3) and one family of routes can serve them (`/engines/{id}/models*`).
The code that knows how an engine finds and fetches its models stays where it was (`model_catalog` and the library of ollama.com for Ollama, the search
of Hugging Face in `llamacpp_engine`, `managed_models` for ExLlamaV3, LM Studio and Colibri); a source only puts it behind one shape.

An entry: `{id, name, revision, size_gb, approximate, fit, installed, in_use, summary, download, has_variants, incomplete, removable}`. `id` is the name to give to « Download »
(an Ollama tag, a repository of Hugging Face, the id of a model of Colibri); `revision` is the quantisation or the file to take with it, empty when
there is none to choose; `fit` is `{level, text}` for THIS machine; `download` is `{possible, reason}`: every entry either can be downloaded or says
why not (too big, offline, a format this engine cannot read), never a silent absence of the button. `incomplete` is a download that stopped halfway;
`removable` says whether Lutin may delete an installed model (not one it did not put there, nor the models of a server reached by its address).

Every source raises `NotChosen` for what only the engine in use can do, `ValueError` with a message for the person when its catalogue cannot be read
or when it does not do what is asked.
"""
from . import core as _m
from . import engine_capabilities as _capabilities
from . import engines as _engines
from . import model_fit as _fit
from . import offline as _offline
from .i18n import t as _t
from .managed_models import NotChosen          # one error for « not the engine in use », whoever raises it

FIT_LEVELS = {"ideal": "comfortable", "bien": "good", "limite": "tight", "trop_gros": "too_big"}
ORDERS = {"recent": "recent", "popular": "populaire"}          # the orders of a search, as the page names them -> as managed_models names them
CAPABILITIES = {"tools": "outils", "vision": "vision", "thinking": "reflexion"}          # what a model can do, as the page names it -> as the catalogue does
RECOMMENDED = 5


class Unsupported(ValueError):
    """What this engine does not do (its message says what to do instead)."""


def fit_view(fit):
    return None if not fit else {"level": FIT_LEVELS.get(fit["niveau"], fit["niveau"]), "text": fit["texte"]}


def download_state(fit, can=None, installed=False):
    """`{possible, reason}`: a model can be downloaded unless it is already here, the engine cannot take it, the network is off, or it does not fit."""
    if installed:
        return {"possible": False, "reason": _t("Déjà installé.")}
    if can is not None and not can.get("possible"):
        return {"possible": False, "reason": can.get("raison") or _t("Ce moteur ne télécharge pas de modèle.")}
    if _offline.is_active() or _engines.CONTEXT["hors_ligne"]():
        return {"possible": False, "reason": _t("Mode hors ligne : aucun téléchargement.")}
    if fit and fit.get("niveau") == "trop_gros":
        return {"possible": False, "reason": fit["texte"]}
    return {"possible": True, "reason": ""}


# The roles of the catalogue under their v1 names, and the rating from which a role is a strength of the model (as the old catalogue tab said them)
ROLES_V1 = {"polyvalent": "general", "rapide": "fast", "creatif": "creative", "code": "code", "vision": "images"}
STRONG = 7


def strengths_of(model):
    """The roles a model of the catalogue is good at, the best first: `["code", "general"]`. Empty for a model the catalogue does not rate."""
    notes = model.get("notes") or {}
    return [ROLES_V1.get(role, role) for role, note in sorted(notes.items(), key=lambda pair: (-pair[1], pair[0])) if note >= STRONG]


def entry(ident, name=None, revision="", size_gb=None, approximate=False, fit=None, installed=False, in_use=False, summary="", can=None, has_variants=False,
          incomplete=False, removable=None, strengths=()):
    """One model, in the shape every source gives. `fit` is the verdict as the judge writes it (`{niveau, texte}`). An installed model is removable unless said.
    `strengths`: the roles it is good at, when the source rates them (the catalogue of Lutin), so that every card says it whatever the engine."""
    return {"id": ident, "name": name or ident.split("/")[-1], "revision": revision or "", "size_gb": size_gb, "approximate": bool(approximate), "fit": fit_view(fit),
            "installed": bool(installed), "in_use": bool(in_use), "summary": summary or "", "download": download_state(fit, can, installed), "has_variants": bool(has_variants),
            "incomplete": bool(incomplete), "removable": bool(installed) if removable is None else bool(removable and installed), "strengths": list(strengths)}


def _judge(engine):
    """The verdict for a size in GB on this machine, as the engine runs models: ExLlamaV3 on the card alone, the others the common way."""
    profile = _fit.profil_pret()
    if profile is None:
        return lambda gb: None
    if engine.id == _engines.EXLLAMAV3:
        from . import managed_models
        return managed_models.judge(engine.id)
    experts = _capabilities.of(engine).experts_in_ram
    return lambda gb: _fit.evaluer({"go": gb}, profile, experts_en_ram=experts) if gb else None


class ModelSource:
    """What every engine answers. A source that does not do an operation says so with a ValueError the person can read."""

    def __init__(self, engine):
        self.engine = engine

    def installed(self):
        raise NotImplementedError

    def recommended(self):
        return []

    def search(self, words="", page=1, order="recent", community=False, capability=""):
        """`order` (recent, popular) and `community` are read by the managed servers, `capability` (tools, vision, thinking) by Ollama and the catalogue."""
        return {"models": [], "more": False}

    def variants(self, ref):
        raise ValueError(_t("Ce moteur n'a pas de précision à choisir pour ses modèles."))

    def check(self, scope):
        """`scope` « updates » or « new »: `{models, errors}`. Ollama and llama.cpp have the proposals of the daily check (POST /models/check) instead."""
        raise Unsupported(_t("Ce moteur ne cherche pas ici les mises à jour de ses modèles."))

    def download(self, ref, revision=""):
        raise ValueError(_t("Ce moteur gère ses modèles lui-même : installe-les depuis le moteur."))

    def remove(self, name):
        raise ValueError(_t("Ce moteur gère ses modèles lui-même."))

    def _in_use(self):
        from . import agent
        return agent.moteur_local().id == self.engine.id

    def _require_in_use(self):
        if not self._in_use():
            raise NotChosen(_t("{} n'est pas le moteur choisi.").format(self.engine.nom))


class CatalogueSource(ModelSource):
    """Ollama and llama.cpp: the curated catalogue of Lutin (Ollama tags, which both can run), then the open library of the engine."""

    def _catalogue(self, installed):
        from . import model_compat
        profile = _fit.profil_pret()
        for model in _m._CATALOGUE["modeles"]:
            if model.get("avance"):
                continue
            verdict = model_compat.evaluate(model, self.engine, installed)
            fit = _fit.evaluer(model, profile, experts_en_ram=_capabilities.of(self.engine).experts_in_ram) if profile is not None else None
            yield model, verdict, fit

    def installed(self):
        state = self.engine.modeles()
        sizes, current = state.get("tailles") or {}, str(_m.reglages().get("modele") or "")
        judge = _judge(self.engine)
        return [entry(name, name, size_gb=round(sizes[name] / 1e9, 1) if sizes.get(name) else None, fit=judge(sizes[name] / 1e9) if sizes.get(name) else None,
                      installed=True, in_use=name == current) for name in state.get("installes", [])]

    def recommended(self):
        from . import model_compat
        profile = _fit.profil_pret()
        if profile is None:
            return []
        installed = set(self.engine.modeles().get("installes", []))
        chosen = model_compat.roles_for(profile, _m._CATALOGUE, self.engine, installed)
        seen, out = set(), []
        for role in ("polyvalent", "rapide", "creatif", "code", "vision"):
            choice = chosen.get(role)
            if choice and choice.id not in seen:
                seen.add(choice.id)
                model = choice.modele
                fit = _fit.evaluer(model, profile, experts_en_ram=_capabilities.of(self.engine).experts_in_ram)
                out.append(entry(model["id"], model["nom"], size_gb=model["go"], fit=fit, installed=model["id"] in installed, summary=model.get("phrase", ""), strengths=strengths_of(model), can=self.engine.telechargeable()))
        return sorted(out, key=lambda item: -(item["size_gb"] or 0))[:RECOMMENDED]

    def search(self, words="", page=1, order="recent", community=False, capability=""):
        words = str(words or "").strip().lower()
        installed = set(self.engine.modeles().get("installes", []))
        found = []
        if int(page) == 1:          # the catalogue is one page: what Lutin knows and recommends, before the open library
            for model, verdict, fit in self._catalogue(installed):
                if words and words not in (model["id"] + " " + model["nom"] + " " + model.get("phrase", "")).lower():
                    continue
                if capability and CAPABILITIES[capability] not in model.get("capacites", []):
                    continue
                can = {"possible": verdict["compatible"], "raison": " ".join(verdict["raisons"])} if not verdict["compatible"] else self.engine.telechargeable()
                found.append(entry(model["id"], model["nom"], size_gb=model["go"], fit=fit, installed=model["id"] in installed, summary=model.get("phrase", ""), strengths=strengths_of(model), can=can,
                                   has_variants=self.engine.id == _engines.OLLAMA))
        more = False
        offline = _offline.is_active() or _engines.CONTEXT["hors_ligne"]()
        library = None if offline else self._library(words, page, installed, order, capability)          # offline: the catalogue only, nothing asked of ollama.com or Hugging Face
        if library is not None:
            listed = {model["id"] for model in found}          # a model of the catalogue is not given again by the library
            found.extend(model for model in library["models"] if model["id"] not in listed)
            more = library["more"]
        return {"models": found, "more": more}

    def _library(self, words, page, installed, order, capability):
        return None

    def remove(self, name):
        self._require_in_use()
        from . import agent
        agent.supprimer_modele(name)


class OllamaSource(CatalogueSource):
    def _library(self, words, page, installed, order, capability):
        from . import model_discovery
        found = model_discovery.search(words[:100], "popular" if order == "popular" else "newest", page, categorie=capability)
        judge = _judge(self.engine)
        out = []
        for item in model_discovery.evaluate_sizes(found["modeles"], lambda gb: judge(gb) or {"niveau": "", "texte": ""}):
            for size in item["tailles"]:
                tag = "{}:{}".format(item["nom"], size)
                gb = item["evaluations"][size]["go"] if size in item["evaluations"] else None
                out.append(entry(tag, tag, size_gb=gb, approximate=True, fit=item["evaluations"].get(size) if gb else None, installed=tag in installed, summary=item["description"],
                                 can=self.engine.telechargeable(), has_variants=True))
        return {"models": out, "more": bool(found["suite"])}

    def variants(self, ref):
        from . import model_variants
        found = model_variants.list_variants(ref)
        judge, installed = _judge(self.engine), set(self.engine.modeles().get("installes", []))
        return [dict(entry(v["id"], v["id"], revision=v["precision"], size_gb=v["go"], fit=judge(v["go"]), installed=v["id"] in installed, summary=model_variants.describe(v["precision"]),
                           can=self.engine.telechargeable()), default=bool(v.get("defaut"))) for v in found["variantes"]]

    def download(self, ref, revision=""):
        self._require_in_use()
        from . import agent
        return agent.installer_modele(ref)          # a precision is a tag of its own (« qwen3:8b-q4_K_M »): `ref` already names it


class LlamaCppSource(CatalogueSource):
    def _library(self, words, page, installed, order, capability):
        if not words or int(page) > 1:          # Hugging Face is searched for words; without them the catalogue above is the list
            return None
        found = self.engine.chercher_modeles(words)
        return {"models": [entry(item["id"], item["id"], summary=_t("{} téléchargements").format(item.get("telechargements", 0)), can=self.engine.telechargeable(), has_variants=True) for item in found], "more": False}

    def variants(self, ref):
        judge = _judge(self.engine)
        return [entry(ref, ref, revision=item["fichier"], size_gb=round(item["taille"] / 1e9, 1) if item["taille"] else None, fit=judge(item["taille"] / 1e9) if item["taille"] else None,
                      can=self.engine.telechargeable()) for item in self.engine.fichiers_du_depot(ref)]

    def download(self, ref, revision=""):
        self._require_in_use()
        if not revision:          # an Ollama tag of the catalogue, or a repository whose file must be chosen
            from . import agent
            if "/" in ref and ":" not in ref:
                raise ValueError(_t("Choisis une précision (un fichier) de ce dépôt."))
            return agent.installer_modele(ref)
        possible = self.engine.telechargeable()
        if not possible["possible"]:
            raise ValueError(possible["raison"])
        return _engines.launch_task(self.engine, "telecharger", lambda action, progress: self.engine.telecharger_modele(ref, revision, progress))


class ManagedSource(ModelSource):
    """ExLlamaV3, LM Studio, Colibri: `managed_models`, which already judges and fetches for each of them."""

    def _managed(self):
        from . import managed_models
        if not managed_models.chosen(self.engine.id):
            raise NotChosen(_t("{} n'est pas le moteur choisi.").format(self.engine.nom))
        return managed_models

    def installed(self):
        seen = self._managed().models(self.engine.id, _m.reglages().get("modele"))
        return [entry(item.get("depot") or item["nom"], item["nom"], revision=item.get("revision") or "", size_gb=item.get("taille_go"), fit=item.get("adequation"), installed=True,
                      in_use=bool(item.get("utilise")), incomplete=bool(item.get("incomplet")), removable=item.get("supprimable", True) is not False) for item in seen["modeles"]]

    def recommended(self):
        return [entry(item["id"], item["nom"], revision=item["revision"], size_gb=item["go"], fit=item["adequation"], installed=item["installe"], can=self._can()) for item in self._managed().recommended(self.engine.id)]

    def search(self, words="", page=1, order="recent", community=False, capability=""):
        found = self._managed().catalog(self.engine.id, str(words or "")[:100], ORDERS[order], bool(community), page)
        return {"models": [self._listed(item) for item in found["modeles"]], "more": bool(found.get("suite"))}

    def _listed(self, item):
        return entry(item["id"], item.get("nom"), size_gb=item.get("estimation_go"), approximate=True, fit=item.get("adequation"), installed=bool(item.get("installes")),
                     can=self._can(), has_variants=not item.get("direct"))

    def check(self, scope):
        """« updates »: the newer versions of what ExLlamaV3 downloaded; « new »: new models that fit this machine (at most 8). LookupError for another scope."""
        if scope not in ("updates", "new") or (scope == "updates" and self.engine.id != _engines.EXLLAMAV3):
            raise LookupError(scope)
        found = self._managed().check(self.engine.id, "maj" if scope == "updates" else "nouveaux")
        if scope == "updates":
            return {"models": [entry(item["depot"], item["nom"], revision=item.get("revision") or "", can=self._can()) for item in found.get("plus_recentes", [])],
                    "errors": [str(error) for error in found.get("erreurs", [])]}
        return {"models": [self._listed(item) for item in found.get("propositions", [])], "errors": []}

    def variants(self, ref):
        if self.engine.id == _engines.COLIBRI:
            raise ValueError(_t("Ce serveur n'a pas de quantifications à choisir."))
        return [entry(ref, revision=q["revision"], size_gb=q.get("go"), fit=q.get("adequation"), installed=bool(q.get("installe")), can=self._can()) for q in self._managed().quantizations(self.engine.id, ref)]

    def download(self, ref, revision=""):
        return self._managed().download(self.engine.id, ref, revision)

    def remove(self, name):
        if any(item["name"] == name and not item["removable"] for item in self.installed()):
            raise ValueError(_t("Lutin n'a pas mis ce modèle ici : il ne le supprime pas."))
        from . import agent
        agent.supprimer_modele(name)

    def _can(self):
        return self.engine.telechargeable() if self.engine.id == _engines.COLIBRI else {"possible": True}


class ExternalSource(ModelSource):
    """A server reached by its address: its models are its own, Lutin shows them and downloads nothing."""

    def installed(self):
        state = self.engine.modeles()
        current = str(_m.reglages().get("modele") or "")
        return [entry(name, name, installed=True, in_use=name == current, removable=False) for name in state.get("installes", [])]


def source_of(engine):
    """The model source of this engine."""
    if engine.id == _engines.OLLAMA:
        return OllamaSource(engine)
    if engine.id == _engines.LLAMACPP:
        return LlamaCppSource(engine)
    if engine.id in _engines.MANAGED_SERVERS:
        return ManagedSource(engine)
    return ExternalSource(engine)
