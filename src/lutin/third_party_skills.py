"""Les skills tiers : trouver, examiner, installer et mettre à jour les skills publiés sur GitHub (format SKILL.md, standard ouvert agentskills.io).

Un skill est un dossier avec un `SKILL.md` (en-tête `name` et `description`, puis des consignes) et, parfois, `scripts/`, `references/`, `assets/`. Lutin sait déjà lire `.claude/skills/<nom>/SKILL.md` d'un dossier de
travail : il en liste le nom et la description, et le modèle ouvre le fichier quand le sujet arrive. Ce module ajoute ce qui manquait : une recherche, une fiche honnête, l'installation et les mises à jour.

Principes de sécurité (un skill est un TEXTE que le modèle suit, pas seulement du code) :
  - rien ne s'installe sans un clic, depuis un dépôt et un état précis affichés ; rien ne s'exécute jamais à l'installation ;
  - la fiche analyse le texte et les scripts (installation par pipe vers un shell, instructions cachées, injection de consigne, lecture de secrets…) et le dit ; un skill « dangereux » ne s'installe qu'en confirmant ;
  - une licence absente est dite et demande aussi une confirmation ; les scripts ne sont jamais lancés tout seuls (l'exécuteur de Lutin demande son accord à chaque commande) ;
  - Lutin ne retire ou ne met à jour que ce qu'il a installé lui-même (fichier `.lutin-skill.json` dans le dossier du skill) ;
  - les noms et chemins venus de GitHub sont validés (pas de `..`, pas de lien symbolique, tailles bornées).
Tout passe par `http(url, entetes) -> (statut, entetes, corps)` : testable sans réseau. Les requêtes de l'API portent le compte GitHub de l'utilisateur s'il en a donné un (voir github.py)."""
import concurrent.futures
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

from . import github, updates, claude_project
from . import storage as _donnees
from .i18n import t as _t

SOURCES_DEFAUT = (          # des dépôts publics de skills, proposés au départ ; l'utilisateur en ajoute d'autres
    ("anthropics/skills", "Anthropic (officiel)"),
    ("alirezarezvani/claude-skills", "Communauté : skills par métier"),
    ("vercel-labs/skills", "Vercel : recherche de skills"),
)
RE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
RE_NOM_SUR = re.compile(r"[^a-z0-9._-]+")
CHEMIN_SKILLS = ".claude/skills"
DOSSIERS_AGENTS = (".claude", ".agents", ".codex", ".cursor", ".opencode", ".gemini", ".github")          # là où les agents rangent leurs skills ; ordre = préférence quand le même skill est copié dans plusieurs
SIGNATURE = ".lutin-skill.json"
MAX_FICHIERS, MAX_OCTET_FICHIER, MAX_OCTETS = 200, 900_000, 8_000_000          # un skill est un dossier de texte : au-delà, ce n'est pas un skill
DUREE_CACHE = 600
TAILLE_ARBRE_MAX = 12_000_000          # l'arbre d'un dépôt de centaines de skills pèse plusieurs Mo de JSON


def http_defaut(url, entetes=None):
    return updates.http_get(url, entetes, delai=30, taille_max=TAILLE_ARBRE_MAX)

PAR_PAGE = 20
JETONS_LOURD = 3500          # au-delà, un petit modèle perd le fil : la fiche le dit
CACHE = {}
VERROU = threading.Lock()
INDEXATION = {}          # dépôt -> {fait, total, fini, erreur}


# ------------------------------------------------------------------ GitHub
def lire_depot(texte):
    """(propriétaire, dépôt) d'après « propriétaire/dépôt » ou une adresse github.com. ValueError sinon."""
    t = str(texte or "").strip().rstrip("/")
    t = re.sub(r"^(https?://)?(www\.)?github\.com/", "", t)
    t = re.sub(r"\.git$", "", t)
    morceaux = t.split("/")
    if len(morceaux) < 2 or not RE_SEGMENT.match(morceaux[0]) or not RE_SEGMENT.match(morceaux[1]) or morceaux[0].startswith(".") or morceaux[1] in (".", ".."):
        raise ValueError(_t("Écris un dépôt GitHub sous la forme « propriétaire/dépôt » (ou colle son adresse)."))
    return morceaux[0], morceaux[1]


def _lire_json(url, http):
    http = http or http_defaut
    garde = CACHE.get(url)
    if garde and time.time() - garde[0] < DUREE_CACHE:
        return garde[1]
    try:
        statut, entetes, corps = http(url, {"Accept": "application/vnd.github+json"})
    except OSError as e:
        raise ValueError(_t("GitHub ne répond pas ({}). Vérifie ta connexion.").format(str(e)[:80]))
    if github.limite_atteinte(statut, entetes):
        raise github.erreur_limite(entetes)
    if statut == 404:
        raise ValueError(_t("Dépôt introuvable sur GitHub (ou privé)."))
    if statut == 401:
        raise ValueError(_t("GitHub refuse ton jeton (expiré ou mal copié) : corrige-le dans Réglages > Outils > Compte GitHub."))
    if statut != 200:
        raise ValueError(_t("GitHub a répondu une erreur (HTTP {}). Réessaie dans quelques minutes.").format(statut))
    try:
        valeur = json.loads(corps.decode("utf-8"))
    except ValueError:
        raise ValueError(_t("Réponse illisible de GitHub."))
    CACHE[url] = (time.time(), valeur)
    return valeur


def _texte(depot, chemin, http, maxi=MAX_OCTET_FICHIER):
    http = http or http_defaut
    """Le contenu d'un fichier du dépôt (raw.githubusercontent.com, hors de la limite de l'API). None s'il est trop gros ; ValueError si illisible."""
    o, r = lire_depot(depot)
    url = "https://raw.githubusercontent.com/{}/{}/HEAD/{}".format(o, r, "/".join(urllib.parse.quote(s) for s in chemin.split("/")))
    try:
        statut, entetes, corps = http(url, {})
    except OSError as e:
        raise ValueError(_t("GitHub ne répond pas ({}). Vérifie ta connexion.").format(str(e)[:80]))
    if github.limite_atteinte(statut, entetes) or statut == 429:
        raise github.erreur_limite(entetes)
    if statut != 200:
        raise ValueError(_t("Fichier introuvable dans le dépôt : {}").format(chemin[:80]))
    return None if len(corps) > maxi else corps


def arbre(depot, http=None):
    """L'arbre complet du dépôt en UNE requête : {sha, tronque, entrees: [{path, type, sha, size, mode}]}."""
    o, r = lire_depot(depot)
    d = _lire_json("https://api.github.com/repos/{}/{}/git/trees/HEAD?recursive=1".format(o, r), http)
    return {"sha": str(d.get("sha", "")), "tronque": bool(d.get("truncated")), "entrees": [e for e in d.get("tree", []) if isinstance(e, dict)]}


def chercher_depots(q, http=None):
    """Des dépôts de skills sur GitHub (recherche par sujet), les plus suivis d'abord : [{depot, etoiles, description, maj}]."""
    q = " ".join(str(q or "").split())[:60]
    requete = (q + " " if q else "") + "(topic:agent-skills OR topic:claude-skills OR topic:claude-code-skills)"
    d = _lire_json("https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": requete, "sort": "stars", "order": "desc", "per_page": "20"}), http)
    return [{"depot": e.get("full_name", ""), "etoiles": int(e.get("stargazers_count") or 0), "description": str(e.get("description") or "")[:200], "maj": str(e.get("pushed_at") or "")[:10]}
            for e in d.get("items", []) if RE_SEGMENT.match(str(e.get("full_name", "")).split("/")[0] or "")]


LISTES_COMMUNAUTAIRES = ("VoltAgent/awesome-agent-skills", "travisvn/awesome-claude-skills")          # des listes de liens vers des dépôts de skills
RE_LIEN_DEPOT = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9][A-Za-z0-9_.-]{0,38})/([A-Za-z0-9_][A-Za-z0-9_.-]{0,99})(?=[/)#\s\"'>\]]|$)")
RE_LIEN_ANNUAIRE = re.compile(r"https?://officialskills\.sh/([A-Za-z0-9][A-Za-z0-9_.-]{0,38})/([A-Za-z0-9_][A-Za-z0-9_.-]{0,99})/")
NON_DEPOTS = {"orgs", "topics", "features", "sponsors", "marketplace", "settings", "apps", "about", "pricing", "search", "login", "collections", "trending", "explore"}


def depots_recenses(q="", http=None):
    """Les dépôts GitHub cités par les listes communautaires de skills (liens trouvés dans leur README), les plus cités d'abord : [{depot, citations}]. Filtrés par le mot cherché ; les listes elles-mêmes sont écartées."""
    comptes = {}
    for liste in LISTES_COMMUNAUTAIRES:
        try:
            texte = (_texte(liste, "README.md", http, 4_000_000) or b"").decode("utf-8", "replace")
        except ValueError:
            continue          # une liste qui ne se lit pas n'empêche pas les autres
        for o, r in RE_LIEN_DEPOT.findall(texte) + RE_LIEN_ANNUAIRE.findall(texte):
            r = re.sub(r"\.git$", "", r)
            if o.lower() in NON_DEPOTS or o.startswith(".") or r in ("blob", "tree", "issues", "pull", "releases", "wiki", "actions") or "{}/{}".format(o, r) in LISTES_COMMUNAUTAIRES:
                continue
            comptes["{}/{}".format(o, r)] = comptes.get("{}/{}".format(o, r), 0) + 1
    mots = [m for m in str(q or "").lower().split() if m]
    sortie = [{"depot": d, "citations": n} for d, n in comptes.items() if all(m in d.lower() for m in mots)]
    if not sortie and not comptes:
        raise ValueError(_t("Les listes communautaires de skills ne se lisent pas pour l'instant. Réessaie dans quelques minutes."))
    return sorted(sortie, key=lambda x: (-x["citations"], x["depot"]))[:120]


# ------------------------------------------------------------------ le contenu d'un dépôt
def _dossier_cache(dossiers=None):
    from . import core as _m
    return (dossiers or {}).get("donnees", _m.DONNEES) / "cache" / "skills_tiers"


def skills_du_depot(depot, http=None):
    """Les skills d'un dépôt d'après son arbre : [{dir, nom, sha, fichiers, octets, scripts}]. Les dossiers cachés (.gemini, .github…) sont ignorés : ce sont des copies ou des outils, pas des skills."""
    a = arbre(depot, http)
    entrees = a["entrees"]
    dossiers_sha = {e["path"]: e.get("sha", "") for e in entrees if e.get("type") == "tree"}
    sortie, cache = [], {}
    for e in entrees:
        if e.get("type") != "blob" or not (e["path"] == "SKILL.md" or e["path"].endswith("/SKILL.md")):
            continue
        dossier = e["path"].rsplit("/", 1)[0] if "/" in e["path"] else ""
        segments = [x for x in dossier.split("/") if x]
        if "node_modules" in segments:
            continue
        if any(x.startswith(".") for x in segments):          # dossier caché : seulement ceux des agents (« .claude/skills/x »), et jamais en double d'un skill déjà vu ailleurs
            if segments[0] not in DOSSIERS_AGENTS or len(segments) < 3 or segments[1] != "skills":
                continue
            cache[dossier] = segments[-1]
            continue
        prefixe = dossier + "/" if dossier else ""
        fichiers = [x for x in entrees if x.get("type") == "blob" and x["path"].startswith(prefixe) and not any(seg.startswith(".") for seg in x["path"][len(prefixe):].split("/"))]
        sortie.append({"dir": dossier, "nom": dossier.rsplit("/", 1)[-1] if dossier else depot.split("/")[1], "sha": dossiers_sha.get(dossier, a["sha"]), "fichiers": len(fichiers),
                       "octets": sum(int(x.get("size") or 0) for x in fichiers), "scripts": any(x["path"][len(prefixe):].startswith("scripts/") for x in fichiers)})
    deja = {s["nom"] for s in sortie}
    for dossier in sorted(cache, key=lambda d: (DOSSIERS_AGENTS.index(d.split("/")[0]), d)):
        if cache[dossier] in deja:
            continue          # la même fiche est déjà dans le dépôt (ou dans un dossier d'agent préféré) : une copie de plus n'est pas un autre skill
        deja.add(cache[dossier])
        prefixe = dossier + "/"
        fichiers = [x for x in entrees if x.get("type") == "blob" and x["path"].startswith(prefixe)]
        sortie.append({"dir": dossier, "nom": cache[dossier], "sha": dossiers_sha.get(dossier, a["sha"]), "fichiers": len(fichiers), "octets": sum(int(x.get("size") or 0) for x in fichiers),
                       "scripts": any(x["path"][len(prefixe):].startswith("scripts/") for x in fichiers)})
    return sorted(sortie, key=lambda s: s["dir"]), a["tronque"]


def _entete_skill(texte):
    f = claude_project.frontmatter(texte[:6000])
    return {"nom": str(f.get("name") or ""), "description": " ".join(str(f.get("description") or "").split())[:400], "licence": str(f.get("license") or "")[:120]}


def _fichier_index(depot, dossiers=None):
    o, r = lire_depot(depot)
    return _dossier_cache(dossiers) / "{}__{}.json".format(o, r)


def _index_lu(depot, dossiers=None):
    d = _donnees.lire_json(_fichier_index(depot, dossiers), {})
    return d if isinstance(d, dict) else {}


def descriptions(depot, skills, http=None, dossiers=None, travailleurs=6):
    """Complète `skills` avec leur description et licence (lues dans leur SKILL.md, gardées sur disque tant que le skill ne change pas). Rend les skills enrichis ; un fichier illisible n'arrête rien."""
    index = _index_lu(depot, dossiers)
    deja = index.get("skills", {})
    a_lire = [s for s in skills if deja.get(s["dir"], {}).get("sha") != s["sha"]]

    def lire(s):
        try:
            texte = _texte(depot, (s["dir"] + "/" if s["dir"] else "") + "SKILL.md", http)
            return s, _entete_skill((texte or b"").decode("utf-8", "replace"))
        except ValueError as e:
            return s, {"_erreur": str(e)}
    if a_lire:
        with concurrent.futures.ThreadPoolExecutor(max_workers=travailleurs) as pool:
            resultats = list(pool.map(lire, a_lire))
        limite = next((r["_erreur"] for _, r in resultats if r.get("_erreur") and "GitHub limite" in r["_erreur"]), "")
        for s, r in resultats:
            if "_erreur" not in r:
                deja[s["dir"]] = dict(r, sha=s["sha"])
        try:
            _fichier_index(depot, dossiers).parent.mkdir(parents=True, exist_ok=True)
            _donnees.ecrire_atomique(_fichier_index(depot, dossiers), json.dumps({"skills": deja}, ensure_ascii=False))
        except OSError:
            pass
        if limite:
            raise ValueError(limite)
    return [dict(s, **{k: v for k, v in deja.get(s["dir"], {}).items() if k != "sha"}) for s in skills]


def _correspond(s, mots):
    texte = (s["dir"] + " " + s.get("nom", "") + " " + s.get("description", "")).lower()
    return all(m in texte for m in mots)


def chercher(q, depots, page=1, http=None, dossiers=None):
    """Les skills qui correspondent, sur les dépôts choisis : {skills, total, page, suite, tronque, decrits}. La recherche porte sur le nom, le chemin et la description (celle des skills déjà lus ou indexés) ;
    la page demandée est complétée avec ses descriptions. ValueError (limite de GitHub, dépôt introuvable…) si un dépôt ne se lit pas."""
    mots = [m for m in re.split(r"\s+", str(q or "").lower().strip()) if m]
    page = max(1, int(page or 1))
    tous, tronque = [], False
    for depot in depots:
        liste, t = skills_du_depot(depot, http)
        tronque = tronque or t
        deja = _index_lu(depot, dossiers).get("skills", {})
        for s in liste:
            info = {k: v for k, v in deja.get(s["dir"], {}).items() if k != "sha"} if deja.get(s["dir"], {}).get("sha") == s["sha"] else {}
            tous.append(dict(s, depot=depot, **info))
    trouves = [s for s in tous if _correspond(s, mots)] if mots else tous
    trouves.sort(key=lambda s: (s["depot"], s["dir"]))
    morceau = trouves[(page - 1) * PAR_PAGE: page * PAR_PAGE]
    for depot in sorted({s["depot"] for s in morceau}):
        groupe = [s for s in morceau if s["depot"] == depot and "description" not in s]
        if groupe:
            enrichis = {e["dir"]: e for e in descriptions(depot, groupe, http, dossiers)}
            morceau = [dict(enrichis.get(s["dir"], s)) if s["depot"] == depot else s for s in morceau]
    for s in morceau:
        s["jetons"] = _jetons_octets(s["octets"])
    return {"skills": morceau, "total": len(trouves), "page": page, "suite": page * PAR_PAGE < len(trouves), "tronque": tronque, "decrits": sum(1 for s in tous if "description" in s), "nombre": len(tous)}


def indexer(depot, http=None, dossiers=None):
    """Lit les descriptions de TOUS les skills d'un dépôt (pour que la recherche porte aussi sur elles). Long pour un gros dépôt (un fichier par skill) : à lancer dans un fil ; l'avancement est dans INDEXATION."""
    etat = INDEXATION[depot] = {"fait": 0, "total": 0, "fini": False, "erreur": ""}
    try:
        liste, _ = skills_du_depot(depot, http)
        etat["total"] = len(liste)
        for i in range(0, len(liste), 24):
            descriptions(depot, liste[i:i + 24], http, dossiers)
            etat["fait"] = min(len(liste), i + 24)
    except ValueError as e:
        etat["erreur"] = str(e)
    etat["fini"] = True
    return etat


def _jetons_octets(octets):
    return int(octets / 3.6)


# ------------------------------------------------------------------ analyse de sécurité
INVISIBLES = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")          # espaces de largeur nulle, marques de direction, séparateurs invisibles
MOTIFS = (          # (gravité, identifiant, expression, explication)
    ("danger", "pipe-shell", re.compile(r"(curl|wget|iwr|irm|Invoke-WebRequest|Invoke-RestMethod)[^\n|]*\|\s*(sudo\s+)?((ba|z|da|k)?sh\b|iex\b|Invoke-Expression\b)|\b(iex|Invoke-Expression)\b\s*[\(\$]?.*(DownloadString|Invoke-WebRequest|iwr)", re.I), "télécharge du code sur internet et l'exécute aussitôt"),
    ("danger", "base64-exec", re.compile(r"base64\s+(-d|--decode)[^\n]*\|\s*(ba)?sh|FromBase64String[^\n]*(iex|Invoke-Expression)", re.I), "exécute du code caché sous forme encodée"),
    ("danger", "destructif", re.compile(r"\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(/|~|\$HOME|\*)(\s|$)|\bmkfs\.|\bformat\s+[a-z]:|\bdd\s+if=.*\bof=/dev/", re.I), "efface ou formate des données"),
    ("danger", "injection", re.compile(r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts)|disregard\s+(the\s+)?(system|previous|above)|do\s+not\s+(tell|inform|mention|reveal)[^\n]{0,40}(user|human)|without\s+(telling|informing)\s+the\s+user|"
                                        r"ignore\s+(toutes\s+)?(les\s+)?(instructions|consignes)\s+pr[ée]c[ée]dentes|ne\s+(le\s+)?(dis|dites)\s+(pas|rien|jamais)\s+[àa]\s+l'utilisateur|sans\s+(en\s+)?informer\s+l'utilisateur", re.I), "tente de donner au modèle un ordre qui contredit les tiens, ou de te le cacher"),
    ("danger", "invisible", INVISIBLES, "contient des caractères invisibles (texte caché que le modèle lit et pas toi)"),
    ("attention", "commentaire-cache", re.compile(r"<!--[\s\S]{60,}?-->"), "un long commentaire HTML : lu par le modèle, invisible à l'affichage"),
    ("attention", "secrets", re.compile(r"\.ssh/id_|id_rsa|\.aws/credentials|\.git-credentials|\.npmrc|\.netrc|Login Data|wallet\.dat|\bprintenv\b|\bos\.environ\b|process\.env", re.I), "touche à des secrets (clés, jetons, identifiants)"),
    ("attention", "envoi", re.compile(r"requests\.post|httpx\.post|curl[^\n]*\s(-d|--data|-F|--form|-T)\s|Invoke-RestMethod[^\n]*-Method\s+Post|fetch\([^\n]*method\s*:\s*['\"]POST", re.I), "envoie des données vers un serveur"),
    ("attention", "telechargement", re.compile(r"\b(curl|wget)\s+(-[A-Za-z]+\s+)*https?://|urlopen\(|requests\.get\(|Invoke-WebRequest|git\s+clone\s+https?://", re.I), "télécharge quelque chose sur internet"),
    ("attention", "droits", re.compile(r"\bsudo\b|chmod\s+(-R\s+)?[0-7]*7[0-7]*\s|chmod\s+\+x|runas|Set-ExecutionPolicy", re.I), "demande des droits élevés ou rend un fichier exécutable"),
    ("attention", "exec", re.compile(r"os\.system|subprocess\.|shell\s*=\s*True|\beval\(|\bexec\(|child_process|Runtime\.getRuntime", re.I), "lance des programmes ou évalue du code"),
    ("attention", "blob", re.compile(r"[A-Za-z0-9+/]{400,}={0,2}"), "un très long bloc encodé (impossible à relire)"),
)
GRAVITES = {"danger": 2, "attention": 1, "info": 0}


def analyser(fichiers):
    """Cherche dans les textes {chemin: texte} ce qui doit alerter. Rend [{gravite, motif, explication, fichier, ligne, extrait}] (trois par motif et par fichier au plus), les plus graves d'abord.
    Les motifs « attention » sont normaux dans un script (il lance, télécharge, envoie) : ils informent ; les motifs « danger » ne le sont jamais."""
    trouves = []
    for chemin, texte in fichiers.items():
        for gravite, motif, regle, explication in MOTIFS:
            n = 0
            for m in regle.finditer(texte):
                ligne = texte.count("\n", 0, m.start()) + 1
                if motif == "invisible" and m.start() == 0:
                    continue          # une marque d'ordre des octets au tout début d'un fichier n'est pas un texte caché
                trouves.append({"gravite": gravite, "motif": motif, "explication": _t(explication), "fichier": chemin, "ligne": ligne, "extrait": texte[max(0, m.start() - 20): m.end() + 40].replace("\n", " ")[:120]})
                n += 1
                if n >= 3:
                    break
    return sorted(trouves, key=lambda t: (-GRAVITES[t["gravite"]], t["fichier"], t["ligne"]))


def gravite_max(constats):
    return max((c["gravite"] for c in constats), key=lambda g: GRAVITES[g], default="aucune")


# ------------------------------------------------------------------ fiche
def _dossier_du_skill(depot, dossier, http):
    a = arbre(depot, http)
    prefixe = dossier + "/" if dossier else ""
    fichiers = [e for e in a["entrees"] if e.get("type") == "blob" and e["path"].startswith(prefixe) and not any(seg.startswith(".") for seg in e["path"][len(prefixe):].split("/"))]
    sha = next((e.get("sha", "") for e in a["entrees"] if e.get("type") == "tree" and e["path"] == dossier), a["sha"])
    return fichiers, prefixe, sha, a["entrees"]


def fiche(depot, dossier, http=None):
    """Tout ce qu'il faut pour décider : le texte de SKILL.md, les fichiers, la licence, le poids pour un petit modèle et l'analyse de sécurité (texte + scripts + références, bornés)."""
    fichiers, prefixe, sha, entrees = _dossier_du_skill(depot, dossier, http)
    if not any(f["path"] == prefixe + "SKILL.md" for f in fichiers):
        raise ValueError(_t("Ce dossier ne contient pas de SKILL.md."))
    principal = (_texte(depot, prefixe + "SKILL.md", http, 200_000) or b"").decode("utf-8", "replace")
    en_tete = _entete_skill(principal)
    a_scanner = {prefixe + "SKILL.md": principal}
    lisibles = [f for f in fichiers if f["path"] != prefixe + "SKILL.md" and int(f.get("size") or 0) <= 200_000 and re.search(r"\.(md|txt|py|sh|bash|ps1|js|mjs|ts|json|ya?ml|toml|bat|cmd|rb|pl|html)$", f["path"], re.I)]
    lisibles = sorted(lisibles, key=lambda f: ("/scripts/" not in "/" + f["path"], f["path"]))[:30]

    def lire(f):
        try:
            return f["path"], (_texte(depot, f["path"], http, 200_000) or b"").decode("utf-8", "replace")
        except ValueError:
            return f["path"], ""
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for chemin, texte in pool.map(lire, lisibles):
            if texte:
                a_scanner[chemin] = texte
    constats = analyser(a_scanner)
    racine = [e["path"] for e in entrees if e.get("type") == "blob" and "/" not in e["path"] and re.match(r"(?i)^licen[cs]e", e["path"])]
    licence_fichier = any(re.match(r"(?i)^licen[cs]e", f["path"][len(prefixe):]) for f in fichiers)
    scripts = [f["path"][len(prefixe):] for f in fichiers if f["path"][len(prefixe):].startswith("scripts/")]
    octets = sum(int(f.get("size") or 0) for f in fichiers)
    trop_gros = [f["path"][len(prefixe):] for f in fichiers if int(f.get("size") or 0) > MAX_OCTET_FICHIER]
    return {"depot": depot, "dir": dossier, "sha": sha, "nom": en_tete["nom"] or (dossier.rsplit("/", 1)[-1] if dossier else depot.split("/")[1]), "description": en_tete["description"], "licence": en_tete["licence"], "licence_fichier": licence_fichier,
            "licence_depot": bool(racine), "texte": principal[:20_000], "texte_coupe": len(principal) > 20_000, "fichiers": [{"chemin": f["path"][len(prefixe):], "octets": int(f.get("size") or 0)} for f in fichiers][:80],
            "nombre_fichiers": len(fichiers), "octets": octets, "scripts": scripts, "jetons_skill": _jetons_octets(len(principal.encode("utf-8"))), "lourd": _jetons_octets(len(principal.encode("utf-8"))) > JETONS_LOURD,
            "champs_claude": sorted(c for c in claude_project.frontmatter(principal[:6000]) if c in ("allowed-tools", "model", "context", "agent", "hooks", "disable-model-invocation", "user-invocable", "argument-hint")),
            "constats": constats, "gravite": gravite_max(constats), "trop_gros": trop_gros, "analyses": len(a_scanner), "installable": len(fichiers) <= MAX_FICHIERS and octets <= MAX_OCTETS}


# ------------------------------------------------------------------ installation
def nom_sur(nom):
    n = RE_NOM_SUR.sub("-", str(nom or "").lower()).strip("-.")[:64]
    if not n or n in (".", ".."):
        raise ValueError(_t("Nom de skill invalide."))
    return n


def _destination(racine, nom):
    base = Path(racine) / CHEMIN_SKILLS
    return base, base / nom_sur(nom)


def installer(depot, dossier, racine, http=None, danger_ok=False, licence_ok=False, remplacer=False, nom=""):
    """Copie le skill dans `<racine>/.claude/skills/<nom>/` (jamais d'exécution), avec sa signature. Refusé : danger non confirmé, licence absente non confirmée, trop de fichiers, nom déjà pris par autre chose
    qu'un skill installé par Lutin. `remplacer` : mise à jour d'un skill signé. Rend {nom, dossier, fichiers, ignores}."""
    f = fiche(depot, dossier, http)
    if not f["installable"]:
        raise ValueError(_t("Ce skill est trop gros ({} fichiers, {} Mo) : un skill fait au plus {} fichiers et {} Mo.").format(f["nombre_fichiers"], round(f["octets"] / 1e6, 1), MAX_FICHIERS, MAX_OCTETS // 1_000_000))
    if f["gravite"] == "danger" and not danger_ok:
        raise ValueError(_t("Ce skill contient des éléments dangereux (voir la fiche) : confirme explicitement pour l'installer."))
    sans_licence = not (f["licence"] or f["licence_fichier"] or f["licence_depot"])
    if sans_licence and not licence_ok:
        raise ValueError(_t("Ce skill ne déclare aucune licence : sans elle tu n'as pas le droit de le réutiliser. Confirme que tu veux l'installer quand même."))
    base, cible = _destination(racine, nom or f["nom"])
    signature = cible / SIGNATURE
    if cible.exists() and not (remplacer and signature.is_file()):
        raise ValueError(_t("Un dossier « {} » existe déjà dans .claude/skills : Lutin ne remplace que les skills qu'il a installés lui-même.").format(cible.name))
    fichiers, prefixe, sha, _ = _dossier_du_skill(depot, dossier, http)
    a_copier, ignores = [], []
    for e in fichiers:
        relatif = e["path"][len(prefixe):]
        morceaux = relatif.split("/")
        if str(e.get("mode")) == "120000" or any(s in ("", ".", "..") or s.startswith(".git") for s in morceaux) or relatif.startswith("/") or "\\" in relatif or ":" in morceaux[0]:
            ignores.append(relatif)          # lien symbolique ou chemin douteux : jamais copié
        elif int(e.get("size") or 0) > MAX_OCTET_FICHIER:
            ignores.append(relatif)
        else:
            a_copier.append((e["path"], relatif))
    base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".lutin-skill-", dir=str(base)))
    try:
        def lire(item):
            return item[1], _texte(depot, item[0], http, MAX_OCTET_FICHIER)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for relatif, corps in pool.map(lire, a_copier):
                if corps is None:
                    ignores.append(relatif)
                    continue
                destination = (tmp / relatif)
                if tmp.resolve() not in destination.resolve().parents:
                    raise ValueError(_t("Chemin refusé : {}").format(relatif[:60]))
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(corps)
        (tmp / SIGNATURE).write_text(json.dumps({"depot": depot, "dir": dossier, "sha": sha, "installe": datetime.now().isoformat(timespec="seconds"), "licence": f["licence"], "gravite": f["gravite"],
                                                 "nom": f["nom"], "fichiers": len(a_copier)}, ensure_ascii=False), encoding="utf-8")
        if cible.exists():
            shutil.rmtree(cible)
        os.replace(tmp, cible)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {"nom": cible.name, "dossier": str(cible), "fichiers": len(a_copier), "ignores": ignores[:20]}


# ------------------------------------------------------------------ ce qui est installé
def installes(racines):
    """Les skills installés par Lutin dans ces dossiers de travail ({id: chemin}) : [{travail, nom, dossier, depot, dir, sha, installe, licence, gravite, jetons}]."""
    sortie = []
    for ident, racine in racines.items():
        base = Path(racine) / CHEMIN_SKILLS
        try:
            dossiers = sorted(p for p in base.iterdir() if p.is_dir() and (p / SIGNATURE).is_file())
        except OSError:
            continue
        for d in dossiers:
            try:
                s = json.loads((d / SIGNATURE).read_text(encoding="utf-8"))
                texte = (d / "SKILL.md").read_text(encoding="utf-8", errors="replace") if (d / "SKILL.md").is_file() else ""
            except (OSError, ValueError):
                continue
            sortie.append({"travail": ident, "nom": d.name, "dossier": str(d), "depot": str(s.get("depot", "")), "dir": str(s.get("dir", "")), "sha": str(s.get("sha", "")), "installe": str(s.get("installe", "")),
                           "licence": str(s.get("licence", "")), "gravite": str(s.get("gravite", "")), "jetons": _jetons_octets(len(texte.encode("utf-8"))), "description": _entete_skill(texte)["description"]})
    return sortie


def retirer(racine, nom):
    """Supprime un skill installé par Lutin (signature présente). Rien d'autre n'est jamais supprimé."""
    base, cible = _destination(racine, nom)
    if cible.parent.resolve() != base.resolve() or not (cible / SIGNATURE).is_file():
        raise ValueError(_t("Ce skill n'a pas été installé par Lutin : il ne le supprime pas."))
    shutil.rmtree(cible)
    return True


def mises_a_jour(liste, http=None):
    """Ajoute `maj` (le skill a changé dans son dépôt) et `disparu` à chaque skill installé, en une requête par dépôt. Une erreur de lecture est mise dans `erreur` (sans casser le reste)."""
    par_depot = {}
    for s in liste:
        par_depot.setdefault(s["depot"], []).append(s)
    sortie = []
    for depot, groupe in par_depot.items():
        try:
            a = arbre(depot, http)
            shas = {e["path"]: e.get("sha", "") for e in a["entrees"] if e.get("type") == "tree"}
            for s in groupe:
                actuel = shas.get(s["dir"]) if s["dir"] else a["sha"]
                sortie.append(dict(s, maj=bool(actuel) and actuel != s["sha"], disparu=actuel is None or actuel == "", erreur=""))
        except ValueError as e:
            sortie += [dict(s, maj=False, disparu=False, erreur=str(e)) for s in groupe]
    return sortie


# ------------------------------------------------------------------ les dépôts choisis
def _fichier_sources():
    from . import core as _m
    return _m.DONNEES / "skills_sources.json"


def sources():
    """Les dépôts parcourus : ceux proposés au départ (non modifiables) puis ceux que l'utilisateur a ajoutés."""
    ajoutes = _donnees.lire_json(_fichier_sources(), {}).get("depots", []) if isinstance(_donnees.lire_json(_fichier_sources(), {}), dict) else []
    sortie = [{"depot": d, "nom": _t(n), "defaut": True} for d, n in SOURCES_DEFAUT]
    sortie += [{"depot": d, "nom": d, "defaut": False} for d in ajoutes if isinstance(d, str) and d not in dict(SOURCES_DEFAUT)]
    return sortie


def ajouter_source(texte):
    o, r = lire_depot(texte)
    depot = "{}/{}".format(o, r)
    with VERROU:
        courant = [s["depot"] for s in sources() if not s["defaut"]]
        if depot in dict(SOURCES_DEFAUT) or depot in courant:
            return sources()
        if len(courant) >= 30:
            raise ValueError(_t("Déjà 30 dépôts ajoutés : retire-en un d'abord."))
        _donnees.ecrire_atomique(_fichier_sources(), json.dumps({"depots": courant + [depot]}))
    return sources()


def retirer_source(depot):
    with VERROU:
        courant = [s["depot"] for s in sources() if not s["defaut"]]
        if depot not in courant:
            raise ValueError(_t("Ce dépôt n'est pas dans ta liste (ceux proposés au départ ne se retirent pas)."))
        _donnees.ecrire_atomique(_fichier_sources(), json.dumps({"depots": [d for d in courant if d != depot]}))
    return sources()
