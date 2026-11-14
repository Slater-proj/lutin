"""Le catalogue des connecteurs MCP : des serveurs connus, à brancher en un clic.

Le catalogue (data/mcp_catalogue.json) est livré avec Lutin ; il ne change pas tout seul. Chaque entrée dit quel programme lancer, À QUELLE VERSION EXACTE (npx et uvx ne lancent jamais « la dernière »
au hasard : une version publiée qui se corrompt ne se retrouve pas chez toi), et ce qu'il faut saisir (un dossier, un fichier, une adresse, un jeton).

Règles de solidité :
- on vérifie d'abord que le programme qui lance le serveur existe (Node.js pour npx, uv pour uvx) et on dit sinon comment l'installer ;
- chaque valeur saisie est contrôlée (un dossier ou un fichier qui existe, une adresse http, jamais une valeur qui commence par « - » : elle serait prise pour une option) ;
- le connecteur est ESSAYÉ tout de suite : s'il ne répond pas, il est retiré et la raison est donnée, au lieu de laisser un connecteur cassé ;
- seuls les outils que le serveur déclare en lecture seule sont autorisés d'emblée ; les autres restent à cocher par l'utilisateur, et le connecteur reste en lecture seule tant qu'il ne le décide pas."""
import json
import re
import shutil
from pathlib import Path

from . import i18n as _i18n
from . import mcp as _mcp
from . import external_programs
from .i18n import t as _t

FICHIER = Path(__file__).parent / "data" / "mcp_catalogue.json"
PREREQUIS = {"npx": ("node", "Node.js"), "uvx": ("uv", "uv")}          # programme qui lance le serveur -> (outil à installer, nom affiché) ; voir outils_externes
RE_ADRESSE = re.compile(r"^https?://[^\s]{3,500}$", re.I)
DOSSIERS_MAX = 10


def charger():
    """Les entrées du catalogue (liste de dictionnaires), ou [] si le fichier est illisible."""
    try:
        return json.loads(FICHIER.read_text(encoding="utf-8")).get("serveurs", [])
    except (OSError, ValueError):
        return []


def entree(ident):
    for e in charger():
        if e["id"] == ident:
            return e
    raise ValueError(_t("Connecteur du catalogue introuvable."))


def _texte(valeur):
    """Un texte {fr, en} dans la langue affichée."""
    if isinstance(valeur, dict):
        return valeur.get(_i18n.langue()) or valeur.get("fr") or ""
    return str(valeur or "")


def programme(execution, chercher=shutil.which):
    """Le chemin complet du programme qui lance le serveur (npx, ou uv pour « uv tool run »), ou '' s'il est absent : celui que Lutin a installé d'abord, sinon celui de la machine.
    Le chemin complet évite que Windows ne trouve pas « npx.cmd »."""
    if execution == "npx":
        return external_programs.chemin("npx", chercher=chercher)
    if execution == "uvx":
        return external_programs.chemin("uv", chercher=chercher)
    return ""


def liste(chercher=shutil.which):
    """Ce que la page affiche : le catalogue dans la langue courante, avec ce qui manque (programme absent) et ce qui est déjà branché."""
    installes = {s.get("catalogue") for s in _mcp.lire()["serveurs"].values() if s.get("catalogue")}
    sortie = []
    for e in charger():
        manque = ""
        if e["execution"] in PREREQUIS and not programme(e["execution"], chercher):
            manque = _t("Lutin installera d'abord {} (un téléchargement d'environ 30 Mo, retirable ensuite).").format(PREREQUIS[e["execution"]][1])
        sortie.append({"id": e["id"], "nom": _texte(e["nom"]), "description": _texte(e["description"]), "categorie": e.get("categorie", ""), "execution": e["execution"],
                       "version": e.get("version", ""), "installe": e["id"] in installes, "manque": manque, "outil": PREREQUIS.get(e["execution"], ("", ""))[0] if manque else "",
                       "champs": [{"cle": c["cle"], "type": c["type"], "obligatoire": bool(c.get("obligatoire")), "multiple": bool(c.get("multiple")),
                                   "libelle": _texte(c["libelle"]), "exemple": c.get("exemple", "")} for c in e.get("champs", [])]})
    return sortie


def _valider(champ, brut):
    """La valeur contrôlée d'un champ (liste de textes pour un champ « multiple »)."""
    valeurs = brut if isinstance(brut, list) else str(brut or "").splitlines()
    valeurs = [str(v).strip() for v in valeurs if str(v).strip()]
    if not valeurs:
        if champ.get("obligatoire"):
            raise ValueError(_t("« {} » est obligatoire.").format(_texte(champ["libelle"])))
        return []
    if not champ.get("multiple") and len(valeurs) > 1:
        raise ValueError(_t("« {} » n'accepte qu'une seule valeur.").format(_texte(champ["libelle"])))
    if len(valeurs) > DOSSIERS_MAX:
        raise ValueError(_t("{} valeurs au plus.").format(DOSSIERS_MAX))
    for v in valeurs:
        if "\0" in v or "\r" in v or len(v) > 2000:
            raise ValueError(_t("Valeur invalide pour « {} ».").format(_texte(champ["libelle"])))
        genre = champ["type"]
        if genre in ("dossier", "fichier"):
            if v.startswith("-"):
                raise ValueError(_t("Un chemin ne peut pas commencer par « - »."))
            chemin = Path(v).expanduser()
            if genre == "dossier" and not chemin.is_dir():
                raise ValueError(_t("Ce dossier n'existe pas : {}").format(v[:200]))
            if genre == "fichier" and not chemin.is_file():
                raise ValueError(_t("Ce fichier n'existe pas : {}").format(v[:200]))
        elif genre == "url" and not RE_ADRESSE.match(v):
            raise ValueError(_t("L'adresse doit commencer par http:// ou https://."))
    return [str(Path(v).expanduser()) if champ["type"] in ("dossier", "fichier") else v for v in valeurs]


def construire(e, saisie, chercher=shutil.which):
    """(commande, url, entetes) du connecteur pour une entrée et les valeurs saisies. Lève ValueError avec la raison."""
    valeurs = {}
    for c in e.get("champs", []):
        valeurs[c["cle"]] = _valider(c, (saisie or {}).get(c["cle"]))
    if e["execution"] == "http":
        adresse = valeurs.get("adresse", [""])[0] if valeurs.get("adresse") else ""
        entetes = {}
        for nom, modele in (e.get("entetes") or {}).items():
            jeton = (valeurs.get("jeton") or [""])[0]
            if jeton:
                entetes[nom] = modele.replace("{jeton}", jeton)
        return [], adresse, entetes
    chemin = programme(e["execution"], chercher)
    if not chemin:
        raise ValueError(_t("Il faut d'abord installer {}.").format(PREREQUIS[e["execution"]][1]))
    # npx : paquet@version ; uv : « uv tool run paquet@version » (la version exacte dans les deux cas)
    commande = [chemin] + (["-y"] if e["execution"] == "npx" else ["tool", "run"]) + ["{}@{}".format(e["paquet"], e["version"])]
    for a in e.get("arguments", []):
        m = re.fullmatch(r"\{([a-z]+)\}", a)
        if m:
            commande += valeurs.get(m.group(1), [])
        else:
            commande.append(a)
    return commande, "", {}


def installer(ident, saisie, chercher=shutil.which, installer_outil=None):
    """Branche un connecteur du catalogue, l'essaie, autorise ses outils en lecture seule. Rend {id, outils, autorises}. En cas d'échec, rien ne reste branché.
    Le programme qui lance le serveur (uv, Node.js) s'il manque est installé d'abord par Lutin : un seul clic pour l'utilisateur."""
    e = entree(ident)
    if any(s.get("catalogue") == ident for s in _mcp.lire()["serveurs"].values()):
        raise ValueError(_t("Ce connecteur est déjà branché."))
    for c in e.get("champs", []):          # les valeurs d'abord : on n'installe rien pour une saisie fausse
        _valider(c, (saisie or {}).get(c["cle"]))
    if e["execution"] in PREREQUIS and not programme(e["execution"], chercher):
        (installer_outil or external_programs.installer)(PREREQUIS[e["execution"]][0])
    commande, url, entetes = construire(e, saisie, chercher)
    ident_mcp = _mcp.ajouter(_texte(e["nom"]), commande or None, url, None, entetes)
    cfg = _mcp.lire()
    cfg["serveurs"][ident_mcp]["catalogue"] = ident
    if commande and e["execution"] == "npx":
        propre = external_programs.dossier("node")
        if Path(commande[0]).is_relative_to(propre):
            cfg["serveurs"][ident_mcp]["path_ajoute"] = external_programs.dossiers_a_ajouter_au_path("node")
    _mcp.ecrire(cfg)
    try:
        total = _mcp.actualiser(ident_mcp)
    except ValueError as erreur:
        _mcp.supprimer(ident_mcp)
        raise ValueError(_t("Le connecteur « {} » n'a pas répondu, il n'a pas été branché : {}").format(_texte(e["nom"]), erreur)) from erreur
    autorises = 0
    for nom, o in _mcp.lire()["serveurs"][ident_mcp]["outils"].items():
        if o.get("lecture"):
            _mcp.regler(ident_mcp, outil=nom, autorise=True)
            autorises += 1
    return {"id": ident_mcp, "outils": total, "autorises": autorises}
