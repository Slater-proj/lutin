"""The models of the three servers Lutin manages behind its OpenAI-compatible engine: ExLlamaV3, LM Studio and Colibri.

They have the same pages: the models on disk, a catalogue to explore (Hugging Face for the first two, Colibri's own list), the quantisations of one
repository, a check (newer versions of what ExLlamaV3 downloaded, or new models that fit this machine) and a download. Each answer is judged for
THIS machine (lutin.model_fit; Colibri judges for itself). Shared by the old page (lutin.server) and /api/v1: one code for both.

The answers keep the shape of the old page (French keys); /api/v1 translates them. Every function raises NotChosen when that server is not the one in
use, and ValueError (a message for the person) when the catalogue cannot be read.
"""
import concurrent.futures

from . import engines as _engines
from . import exllamav3_catalog as _exl_cat
from . import lmstudio_catalog as _lms_cat
from . import model_fit as _fit
from .i18n import t as _t

KINDS = ("exllamav3", "lmstudio", "colibri")
NAMES = {"exllamav3": "ExLlamaV3", "lmstudio": "LM Studio", "colibri": "Colibri"}


class NotChosen(ValueError):
    """The server asked for is not the one Lutin uses now."""


def engine():
    return _engines.par_id("openai")


def chosen(kind, mo=None):
    """Is `kind` the server in use? False for an unknown kind."""
    mo = mo or engine()
    flags = {"exllamav3": mo.exllamav3_choisi, "lmstudio": mo.lmstudio_choisi, "colibri": mo.colibri_choisi}
    return kind in flags and bool(flags[kind]())


def _require(kind):
    mo = engine()
    if not chosen(kind, mo):
        raise NotChosen(_t("{} n'est pas le serveur choisi.").format(NAMES.get(kind, kind)))
    return mo


def _judge():
    profile = _fit.profil_pret()
    return (lambda gb: _fit.evaluer({"go": gb}, profile)) if profile is not None else (lambda gb: None)


def _on_disk(kind, mo):
    """(models on disk, server present, models folder, catalogue search, quantisations) for `kind`."""
    if kind == "exllamav3":
        from . import exllamav3 as _exl
        return _exl.modeles(mo._dossiers()), mo._exl() is not None, str(_exl.folder_models(mo._dossiers())), _exl_cat.search, _exl_cat.quantizations
    if kind == "lmstudio":
        from . import lmstudio as _lmstudio
        present = mo._lms() is not None
        return (_lmstudio.models() if present else []), present, str(_lmstudio.models_folder()), _lms_cat.search, _lms_cat.quantizations
    from . import colibri as _colibri
    present = _colibri.installed(mo._dossiers()) is not None
    return (_colibri.installed_models(mo._dossiers(), mo.modele_colibri()) if present else []), present, str(_colibri.folder_models(mo._dossiers())), None, None


def models(kind, current_model):
    """The models on disk, each judged here and marked when in use, with the state of the server and how to start it."""
    mo = _require(kind)
    installed, present, folder, _, _ = _on_disk(kind, mo)
    judge = _judge()
    return {"modeles": [dict(x, adequation=judge(x["taille_go"]) if x.get("taille_go") else None, utilise=(x["nom"] == current_model) if kind != "colibri" else True) for x in installed],
            "installe": present, "dossier": folder, "actif": bool(mo.modeles()["actif"]) if present else False, "maj": kind == "exllamav3", "nom": NAMES[kind],
            "statut": mo.statut().get("detail", "") if present else "", "demarrer": mo.actions().get("demarrer") if present else None}


def catalog(kind, words="", order="recent", community=False, page=1):
    """{modeles, suite}: the catalogue, each model judged here and with the revisions already on disk."""
    mo = _require(kind)
    installed, _, _, search, _ = _on_disk(kind, mo)
    if kind == "colibri":
        return colibri_catalog(mo, installed, words)
    found = search(words, order, community, page)
    judge, on_disk = _judge(), {}
    for x in installed:
        on_disk.setdefault(x.get("depot", "") or x["nom"], []).append(x.get("revision") or "main")
    for m in found["modeles"]:
        m["adequation"] = judge(m["estimation_go"]) if m.get("estimation_go") else None
        m["installes"] = on_disk.get(m["id"], [])
    return found


def colibri_catalog(mo, installed, words):
    """Colibri's catalogue in the shape of the others: judged by Colibri itself (« fits » / « does not fit »), filtered by the words searched."""
    from . import colibri as _colibri
    wanted = str(words or "").lower().split()
    out = []
    for m in sorted(_colibri.catalogue(mo._dossiers()), key=lambda x: (not x["ok"], x["go"])):
        if wanted and not all(w in m["id"].lower() for w in wanted):
            continue
        verdict = {"niveau": "bien", "texte": _t("Colibri juge que ce modèle tient sur cette machine.")} if m["ok"] else {"niveau": "trop_gros", "texte": m["raison"] or _t("Ne tient pas sur cette machine.")}
        out.append({"id": m["id"], "nom": m["id"], "auteur": "colibri", "telechargements": 0, "aime": 0, "maj": "", "capacites": [], "licence": "", "base": "", "estimation_go": m["go"],
                    "adequation": verdict, "installes": ["prêt"] if any(m["id"] in x["nom"] for x in installed) else [], "direct": True})
    return {"modeles": out, "suite": False}


def quantizations(kind, repo):
    """The quantisations of one repository, each judged here and marked when already on disk. Colibri has none: it prepares a model by its id."""
    mo = _require(kind)
    installed, _, _, _, quants = _on_disk(kind, mo)
    if quants is None:
        raise ValueError(_t("Ce serveur n'a pas de quantifications à choisir."))
    judge, on_disk = _judge(), {x.get("revision") or "main" for x in installed if x.get("depot") == repo}
    found = quants(repo)
    for x in found:
        x["adequation"] = judge(x["go"]) if x.get("go") else None
        x["installe"] = x["revision"] in on_disk
    return found


RECOMMENDED = 5          # how many models the « recommended for this machine » list holds
RECOMMENDED_CANDIDATES = 10          # how many of the most downloaded repositories are looked at (each costs a few requests for its exact sizes)
GOOD = ("ideal", "bien")          # the verdicts of lutin.model_fit that mean « runs well here »


def recommended(kind):
    """The models this machine runs well, one line each with the quantisation to take: `[{id, nom, revision, go, adequation, installe}]`, the largest first, at most `RECOMMENDED`.
    The rule, plainly: among the most downloaded repositories, keep those whose size judged here is not « too big », read their real quantisations (exact sizes), take the heaviest
    quantisation that is judged « ideal » or « good », and list the repositories by that size: of two models that run well, the larger is the more capable. Colibri judges for itself.
    Nothing is downloaded. ValueError (a message) when the catalogue cannot be read."""
    mo = _require(kind)
    installed, _, _, search, quants = _on_disk(kind, mo)
    if kind == "colibri":
        fitting = [m for m in colibri_catalog(mo, installed, "")["modeles"] if m["adequation"]["niveau"] in GOOD and not m["installes"]]
        return [{"id": m["id"], "nom": m["nom"], "revision": "", "go": m["estimation_go"], "adequation": m["adequation"], "installe": False}
                for m in sorted(fitting, key=lambda m: -(m["estimation_go"] or 0))[:RECOMMENDED]]
    judge = _judge()
    candidates = []
    for m in search("", "populaire", False, 1)["modeles"][:RECOMMENDED_CANDIDATES * 2]:
        verdict = judge(m["estimation_go"]) if m.get("estimation_go") else None
        if verdict is not None and verdict["niveau"] != "trop_gros":
            candidates.append(m)
    candidates = sorted(candidates, key=lambda m: -m["estimation_go"])[:RECOMMENDED_CANDIDATES]
    on_disk = {(x.get("depot", ""), x.get("revision") or "main") for x in installed}

    def best(m):
        try:
            found = [q for q in quants(m["id"]) if q.get("go")]
        except ValueError:
            return None          # a repository that cannot be read is left out, the others still count
        fitting = [(q, judge(q["go"])) for q in found]
        fitting = [(q, v) for q, v in fitting if v is not None and v["niveau"] in GOOD]
        if not fitting:
            return None
        q, v = max(fitting, key=lambda pair: pair[0]["go"])
        return {"id": m["id"], "nom": m["nom"], "revision": q["revision"], "go": q["go"], "adequation": v, "installe": (m["id"], q["revision"]) in on_disk}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        chosen_ones = [x for x in pool.map(best, candidates) if x]
    return sorted(chosen_ones, key=lambda x: -x["go"])[:RECOMMENDED]


def check(kind, scope):
    """`scope` « maj »: the newer versions of what ExLlamaV3 downloaded ({plus_recentes, erreurs}); otherwise new models that fit this machine
    ({propositions}, at most 8)."""
    mo = _require(kind)
    if kind == "exllamav3":
        from . import exllamav3 as _exl
        installed = _exl.modeles(mo._dossiers())
        if scope == "maj":
            return _exl_cat.newer_versions(installed)
        candidates, known = _exl_cat.search("", "recent", False, 1)["modeles"], {x.get("depot") for x in installed}
    elif kind == "lmstudio":
        from . import lmstudio as _lmstudio
        candidates, known = _lms_cat.search("", "recent", False, 1)["modeles"], {x["nom"].split("/")[-1] for x in (_lmstudio.models() if mo._lms() else [])}
    else:
        from . import colibri as _colibri
        installed = _colibri.installed_models(mo._dossiers(), mo.modele_colibri())
        candidates, known = [m for m in colibri_catalog(mo, installed, "")["modeles"] if not m["installes"]], set()
    profile, proposals = _fit.profil_pret(), []
    for m in candidates:
        verdict = m.get("adequation") or (_fit.evaluer({"go": m["estimation_go"]}, profile) if profile is not None and m.get("estimation_go") else None)
        if m["id"] in known or not verdict or verdict["niveau"] == "trop_gros":
            continue
        proposals.append(dict(m, adequation=verdict))
    return {"propositions": proposals[:8]}


def download(kind, repo, revision=""):
    """Starts the download (ExLlamaV3: a branch of a repository; LM Studio: a repository and its quantisation; Colibri: prepares a model by its
    id) as a task of the engine; GET of the engines follows it."""
    mo = _require(kind)
    if kind == "exllamav3":
        repo, revision = str(repo)[:120], str(revision or "")[:41]
        return _engines.launch_task(mo, "telecharger:" + repo + ("@" + revision if revision else ""))
    if kind == "lmstudio":
        name = str(repo) + ("@" + str(revision) if revision else "")
        return _engines.launch_task(mo, "telecharger:" + name[:121])
    return _engines.launch_task(mo, "preparer:" + str(repo)[:41])
