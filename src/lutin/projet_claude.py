"""Un projet « Claude » (le dépôt d'un utilisateur de Claude Code : CLAUDE.md, dossier .claude/) comme source de contexte pour Lutin.

Lutin reconnaît, dans le dossier de travail : `CLAUDE.md` (et `CLAUDE.local.md`, `.claude/CLAUDE.md`), `.claude/skills/<nom>/SKILL.md`, `.claude/commands/**/*.md`, `.claude/agents/*.md`
et `.claude/rules/**/*.md`. Le contenu de CLAUDE.md entre dans les consignes du modèle (avec ses imports `@chemin`, un niveau) ; les skills, commandes, agents et règles sont LISTÉS avec
leur description et lus à la demande, comme les fiches `skills/` de Lutin. On peut travailler dans le dépôt lui-même (les mêmes fichiers servent à Claude Code et à Lutin : rien ne se perd
en passant de l'un à l'autre) ou dans une copie (l'original n'est jamais touché).
"""
import re
import shutil
from pathlib import Path

from .i18n import t as _t

FICHIERS_CONTEXTE = ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md")
MAX_PAR_LISTE = 80
LIMITE_CONTEXTE = 7000
LIMITE_IMPORT = 3000
COPIE_MAX_OCTETS = 1_500_000_000
IGNORES_COPIE = ("node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".pytest_cache", ".ruff_cache", ".mypy_cache", "target", ".terraform")
RE_IMPORT = re.compile(r"^@(\S+)\s*$")


def frontmatter(texte):
    """{clé: valeur} de l'en-tête `---` d'un fichier Markdown (valeurs d'une ligne, ou bloc `>` / `|` replié) ; {} s'il n'y en a pas."""
    lignes = texte.lstrip("﻿").splitlines()
    if not lignes or lignes[0].strip() != "---":
        return {}
    d, cle = {}, None
    for ligne in lignes[1:]:
        if ligne.strip() == "---":
            break
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", ligne)
        if m and not ligne.startswith((" ", "\t")):
            cle, v = m.group(1), m.group(2).strip()
            d[cle] = "" if v in (">", "|", ">-", "|-") else v.strip("\"'")
        elif cle and ligne.startswith((" ", "\t")) and ligne.strip():
            d[cle] = (d[cle] + " " + ligne.strip()).strip()
    return d


def _description(chemin):
    """La description d'un fichier : `description:` de l'en-tête, sinon la première ligne de texte ; 200 caractères au plus."""
    try:
        texte = chemin.read_text(encoding="utf-8-sig", errors="ignore")[:4000]
    except OSError:
        return ""
    d = frontmatter(texte).get("description")
    if not d:
        corps = texte.split("---", 2)[-1] if texte.lstrip().startswith("---") else texte
        d = next((l.strip().lstrip("#").strip() for l in corps.splitlines() if l.strip()), "")
    return d[:200]


def _fichiers_md(dossier):
    try:
        return sorted(p for p in dossier.rglob("*.md") if p.is_file())
    except OSError:
        return []


def detecter(racine):
    """Ce que le dossier contient du côté Claude : {contexte, regles, skills, commandes, agents} (chemins relatifs avec « / », description pour skills, commandes et agents)."""
    racine = Path(racine)
    c = racine / ".claude"
    contexte = [f for f in FICHIERS_CONTEXTE if (racine / f).is_file()]
    skills = []
    try:
        for d in sorted(p for p in (c / "skills").iterdir() if p.is_dir()):
            f = d / "SKILL.md"
            if f.is_file():
                skills.append({"nom": frontmatter(f.read_text(encoding="utf-8-sig", errors="ignore")[:4000]).get("name") or d.name, "description": _description(f), "chemin": f.relative_to(racine).as_posix()})
    except OSError:
        pass
    commandes = [{"nom": f.relative_to(c / "commands").with_suffix("").as_posix().replace("/", ":"), "description": _description(f), "chemin": f.relative_to(racine).as_posix()} for f in _fichiers_md(c / "commands")]
    agents = [{"nom": f.stem, "description": _description(f), "chemin": f.relative_to(racine).as_posix()} for f in _fichiers_md(c / "agents")]
    regles = [f.relative_to(racine).as_posix() for f in _fichiers_md(c / "rules")]
    return {"contexte": contexte, "regles": regles[:MAX_PAR_LISTE], "skills": skills[:MAX_PAR_LISTE], "commandes": commandes[:MAX_PAR_LISTE], "agents": agents[:MAX_PAR_LISTE]}


def est_vide(d):
    return not any(d.get(k) for k in ("contexte", "regles", "skills", "commandes", "agents"))


def resume(d):
    """Une phrase pour dire ce qui a été trouvé."""
    morceaux = []
    if d["contexte"]:
        morceaux.append(", ".join(d["contexte"]))
    for cle, modele in (("skills", _t("{} skill(s)")), ("commandes", _t("{} commande(s)")), ("agents", _t("{} agent(s)")), ("regles", _t("{} règle(s)"))):
        if d[cle]:
            morceaux.append(modele.format(len(d[cle])))
    return ", ".join(morceaux)


def texte_contexte(racine, limite=LIMITE_CONTEXTE):
    """Le contenu des fichiers CLAUDE.md du dossier, avec leurs imports `@chemin` (un niveau, dans le dossier seulement), coupé à `limite` caractères."""
    racine = Path(racine).resolve()
    sortie = []
    for nom in FICHIERS_CONTEXTE:
        f = racine / nom
        if not f.is_file():
            continue
        try:
            texte = f.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            continue
        lignes = []
        for ligne in texte.splitlines():
            m = RE_IMPORT.match(ligne.strip())
            if m:
                cible = (f.parent / m.group(1)).resolve()
                if (cible == racine or racine in cible.parents) and cible.is_file() and cible.name != f.name:
                    try:
                        lignes.append("[{}]\n{}".format(cible.relative_to(racine).as_posix(), cible.read_text(encoding="utf-8-sig", errors="ignore")[:LIMITE_IMPORT]))
                        continue
                    except OSError:
                        pass
            lignes.append(ligne)
        sortie.append("## {}\n{}".format(nom, "\n".join(lignes).strip()))
    return "\n\n".join(sortie)[:limite]


def _liste(titre, elements):
    if not elements:
        return ""
    lignes = "\n".join("- {}{}".format(e["chemin"], (" (" + e["nom"] + ") : " + e["description"]) if e["description"] else (" (" + e["nom"] + ")")) for e in elements)
    return "\n\n## " + titre + "\n" + lignes


def bloc_prompt(racine, limite=LIMITE_CONTEXTE):
    """Le morceau des consignes du modèle qui vient du projet Claude du dossier de travail ; "" s'il n'y en a pas."""
    d = detecter(racine)
    if est_vide(d):
        return ""
    texte = _t("\n\n# PROJET CLAUDE (CLAUDE.md et dossier .claude/ du dossier de travail)\n"
               "Ces fichiers viennent d'un projet utilisé avec Claude Code : suis-les comme les consignes du projet. Le contenu des skills, commandes et agents se lit avec l'outil « lire » quand le sujet se présente.\n")
    ctx = texte_contexte(racine, limite)
    if ctx:
        texte += "\n" + ctx
    texte += _liste(_t("Skills (.claude/skills)"), d["skills"])
    texte += _liste(_t("Commandes (.claude/commands) : si l'utilisateur en nomme une, lis son fichier et applique-la"), d["commandes"])
    texte += _liste(_t("Agents (.claude/agents)"), d["agents"])
    if d["regles"]:
        texte += "\n\n## " + _t("Règles (.claude/rules)") + "\n" + "\n".join("- " + r for r in d["regles"])
    return texte + "\n"


def corps_markdown(texte):
    """Le texte d'un fichier Markdown sans son en-tête `---`."""
    texte = texte.lstrip("\ufeff")
    if texte.startswith("---"):
        morceaux = texte.split("\n---", 1)
        if len(morceaux) == 2:
            return morceaux[1].split("\n", 1)[1] if "\n" in morceaux[1] else ""
    return texte


def commande(racine, nom, arguments=""):
    """Le message à envoyer pour la commande `.claude/commands/<nom>.md` du projet : le fichier sans son en-tête, avec $ARGUMENTS (tout ce qui suit le nom) et $1, $2… (mot par mot) remplacés.
    Les lignes de commande (« !… ») d'une commande Claude Code ne sont PAS exécutées : on le dit au modèle, qui peut les lancer avec l'outil « executer » (avec ton accord). ValueError si la commande n'existe pas."""
    racine = Path(racine)
    trouvee = next((c for c in detecter(racine)["commandes"] if c["nom"] == nom), None)
    if not trouvee:
        raise ValueError(_t("Commande du projet inconnue : {}").format(nom))
    texte = corps_markdown((racine / trouvee["chemin"]).read_text(encoding="utf-8-sig", errors="ignore")[:20000]).strip()
    mots = arguments.split()
    texte = re.sub(r"\$(\d)", lambda m: mots[int(m.group(1)) - 1] if 1 <= int(m.group(1)) <= len(mots) else "", texte).replace("$ARGUMENTS", arguments.strip())
    if re.search(r"^!|!`", texte, re.M):
        texte += "\n\n" + _t("(Les lignes de commande « !… » de cette commande ne sont pas exécutées toutes seules : lance-les avec l'outil « executer » si besoin.)")
    return texte


def taille_a_copier(source):
    """Octets à copier (sans les dossiers lourds : node_modules, .venv…), ou la limite dès qu'elle est dépassée."""
    total = 0
    for p in Path(source).rglob("*"):
        if any(part in IGNORES_COPIE for part in p.relative_to(source).parts):
            continue
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
        if total > COPIE_MAX_OCTETS:
            break
    return total


def copier(source, vers):
    """Copie le projet dans `vers` (nouveau dossier ou dossier vide), historique git compris (`.git`) : on peut ensuite comparer, fusionner ou pousser avec les outils git habituels.
    Les dossiers lourds (node_modules, .venv…) ne sont pas copiés. Renvoie le dossier créé."""
    source, vers = Path(source).resolve(), Path(vers).resolve()
    if not source.is_dir():
        raise ValueError(_t("Ce dossier n'existe pas : {}").format(source))
    if vers == source or source in vers.parents or vers in source.parents:
        raise ValueError(_t("La copie ne peut pas être dans le projet (ni le contenir)."))
    if vers.exists() and any(vers.iterdir()):
        raise ValueError(_t("Le dossier de destination n'est pas vide : {}").format(vers))
    if taille_a_copier(source) > COPIE_MAX_OCTETS:
        raise ValueError(_t("Ce projet est trop gros pour être copié (plus de 1,5 Go hors dossiers techniques) : travaille dedans plutôt."))
    shutil.copytree(source, vers, symlinks=True, ignore=shutil.ignore_patterns(*IGNORES_COPIE), dirs_exist_ok=True)
    return vers
