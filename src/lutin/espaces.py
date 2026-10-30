"""Les dossiers de travail côté moteur : choisir, ajouter, retirer, déplacer, parcourir ; et la reprise des données d'un autre assistant ou d'un projet Claude, qui les alimente.

La logique pure (vérifier un chemin, écrire la configuration) est dans travaux.py ; ici, ce qui touche à l'état du moteur (dossier courant, réponses en cours). Les variables partagées sont lues
dans lutin.moteur au moment de l'appel (`_m.RACINE`…), comme dans les autres modules découpés."""
import os
import shutil
import sys
import time
from pathlib import Path

from . import moteur as _m
from . import projet_claude as _pc
from . import reprise as _rep
from . import travaux as _trav
from .i18n import t as _t


def activer_travail(conv, demande=""):
    """Dossier de travail de cette conversation : le sien s'il en a un, sinon celui demandé, sinon le dossier actif. Appelé avec VERROU_TOURS tenu.
    Une seule racine à la fois : si une autre réponse travaille dans un autre dossier, celle-ci attend. Sans dossier configuré (tests, usage direct), la racine ne change pas."""
    cfg = _m.config_lue()
    t = _trav.par_id(cfg, conv["travail"]) if conv.get("travail") else None
    if conv.get("travail") and t is None:
        raise ValueError("Le dossier de travail de cette conversation (« {} ») n'est plus dans la liste. Ajoute-le de nouveau, ou ouvre une nouvelle conversation.".format(conv["travail"]))
    if t is None:
        t = _trav.par_id(cfg, demande) if demande else None
        t = t or _trav.actif(cfg)
    if t is None:
        return None
    chemin = Path(t["chemin"])
    raison = _trav.diagnostic(chemin)
    if raison:
        raise ValueError(raison)
    if any(r != str(chemin.resolve()) for r in _m.RACINE_TOURS.values()):
        raise ValueError("Une réponse est en cours dans un autre dossier de travail : attends sa fin, ou arrête-la.")
    _m.definir_racine(chemin)
    conv["travail"] = t["id"]
    return t


def travaux_etat():
    cfg = _m.config_lue()
    liste = _trav.liste(cfg)
    courant = next((t["id"] for t in liste if _trav.cle(t["chemin"]) == _trav.cle(_m.RACINE)), "")
    return {"liste": liste, "actif": courant or (_trav.actif(cfg) or {}).get("id", "")}


def choisir_travail(ident):
    cfg = _m.config_lue()
    t = _trav.par_id(cfg, ident)
    if not t:
        raise ValueError("Dossier de travail inconnu.")
    raison = _trav.diagnostic(Path(t["chemin"]))
    if raison:
        raise ValueError(raison)
    with _m.VERROU_TOURS:
        if any(r != str(Path(t["chemin"]).resolve()) for r in _m.RACINE_TOURS.values()):
            raise ValueError("Une réponse est en cours dans un autre dossier de travail : attends sa fin pour changer.")
        _m.definir_racine(t["chemin"])
    _trav.choisir(cfg, ident)
    if _m.chemin_config():
        _m.config_ecrire(cfg)
    return travaux_etat()


def ajouter_travail(chemin, nom):
    cfg = _m.config_lue()
    _trav.ajouter(cfg, chemin, nom, _m.dossiers_de_lutin())
    _m.config_ecrire(cfg)
    return travaux_etat()


def retirer_travail(ident, nettoyer=False):
    """Retire le dossier de la liste. `nettoyer` : supprime aussi ce que Lutin y a créé lui-même (le sous-dossier des copies de conversations) ; jamais un autre fichier."""
    cfg = _m.config_lue()
    t = _trav.par_id(cfg, ident)
    supprimes = 0
    if nettoyer and t:
        supprimes = nettoyer_copies(Path(t["chemin"]))
    with _m.VERROU_TOURS:
        if t and str(Path(t["chemin"]).resolve()) in _m.RACINE_TOURS.values():
            raise ValueError("Une réponse travaille dans ce dossier : attends sa fin.")
    _trav.retirer(cfg, ident)
    _m.config_ecrire(cfg)
    with _m.VERROU_TOURS:
        if t and str(Path(t["chemin"]).resolve()) == str(_m.RACINE):          # le dossier qu'on retire était le courant : on bascule tout de suite
            suivant = _trav.actif(cfg)
            defaut = Path.home() / "Lutin"
            if not suivant:
                defaut.mkdir(parents=True, exist_ok=True)
            _m.definir_racine(suivant["chemin"] if suivant else defaut)
    return dict(travaux_etat(), copies_supprimees=supprimes)


def nettoyer_copies(dossier):
    """Supprime le sous-dossier des copies de conversations que Lutin a posé dans ce dossier de travail. Renvoie le nombre de fichiers supprimés (0 s'il n'y en a pas)."""
    from . import donnees
    cible = Path(dossier) / donnees.DOSSIER_COPIES
    if not cible.is_dir() or cible.is_symlink():
        return 0
    n = sum(1 for f in cible.rglob("*") if f.is_file())
    shutil.rmtree(cible, ignore_errors=True)
    return n


def compter_fichiers(dossier, maximum=20000, delai=3.0):
    """(nombre de fichiers, tronqué ?) : parcours borné en nombre et en temps, sans entrer dans .git ni node_modules."""
    n, fin = 0, time.time() + delai
    for racine, sous, noms in os.walk(dossier):
        sous[:] = [s for s in sous if s not in (".git", "node_modules", "__pycache__")]
        n += len(noms)
        if n >= maximum or time.time() > fin:
            return n, True
    return n, False


def apercu_travail(ident):
    """Ce que Lutin trouve et utilise dans un dossier de travail, pour le dire clairement après l'ajout : fichiers, consignes et skills lus, copies de conversations, et surtout un ANCIEN
    ASSISTANT (dossiers donnees/ et memoire/ avec des conversations) qu'on peut reprendre. Rien n'est écrit."""
    t = _trav.par_id(_m.config_lue(), ident)
    if not t:
        raise ValueError(_t("Dossier de travail inconnu."))
    p = Path(t["chemin"])
    fini, resultat = _trav.avec_delai(lambda: _apercu(p))
    if fini is None:
        return {"id": ident, "erreur": _t("Le dossier « {} » ne répond pas (plus de {} s) : un partage réseau éteint, un disque déconnecté ?").format(p, _trav.DELAI_DISQUE_S)}
    if not fini:
        return {"id": ident, "erreur": str(resultat)}
    return dict(resultat, id=ident)


def _apercu(p):
    raison = _trav.diagnostic(p)
    if raison:
        return {"erreur": raison}
    n, tronque = compter_fichiers(p)
    claude = _pc.detecter(p)
    lus = []
    if claude["contexte"]:
        lus.append(", ".join(claude["contexte"]))
    skills = sorted((p / "skills").glob("*.md")) if (p / "skills").is_dir() else []
    if skills:
        lus.append(_t("skills/ : {} fiche(s)").format(len(skills)))
    for cle, modele in (("skills", _t(".claude/skills : {}")), ("commandes", _t("commandes : {}")), ("agents", _t("agents : {}"))):
        if claude[cle]:
            lus.append(modele.format(len(claude[cle])))
    from . import donnees
    copies = sum(1 for f in (p / donnees.DOSSIER_COPIES).glob("*.md")) if (p / donnees.DOSSIER_COPIES).is_dir() else 0
    ancien = None
    try:
        if _trav.cle(p) != _trav.cle(_m.DONNEES.parent):
            with _rep.ouvrir(p) as d:
                if d["conversations"] or d["memoire"]:
                    ancien = dict(_rep.decrire(d), dossier=d["dossier_utilise"])
    except _rep.ErreurReprise:
        ancien = None
    return {"fichiers": n, "tronque": tronque, "lus": lus, "copies": copies, "ancien": ancien, "git": (p / ".git").exists()}


def deplacer_travail(ident, nouveau_parent, nom=""):
    """Déplace un dossier de travail (ses fichiers aussi) ailleurs et met à jour la liste. Refusé tant qu'une réponse y travaille ; les nouvelles réponses attendent la fin du déplacement."""
    cfg = _m.config_lue()
    t = _trav.par_id(cfg, ident)
    if not t:
        raise ValueError(_t("Dossier de travail inconnu."))
    with _m.VERROU_TOURS:
        ancien = Path(t["chemin"])
        if str(ancien.resolve()) in _m.RACINE_TOURS.values():
            raise ValueError(_t("Une réponse travaille dans ce dossier : attends sa fin."))
        courant = _trav.cle(ancien) == _trav.cle(_m.RACINE)
        nouveau, restes = _trav.deplacer(cfg, ident, nouveau_parent, nom, _m.dossiers_de_lutin())
        _m.config_ecrire(cfg)
        if courant:
            _m.definir_racine(nouveau["chemin"])
    return dict(travaux_etat(), restes=restes, ancien=str(ancien), nouveau=nouveau["chemin"])


def changer_chemin_travail(ident, nouveau):
    """Le dossier a été déplacé à la main : on lui donne son nouveau chemin (rien n'est déplacé)."""
    cfg = _m.config_lue()
    t = _trav.par_id(cfg, ident)
    if not t:
        raise ValueError(_t("Dossier de travail inconnu."))
    with _m.VERROU_TOURS:
        if str(Path(t["chemin"]).resolve()) in _m.RACINE_TOURS.values():
            raise ValueError(_t("Une réponse travaille dans ce dossier : attends sa fin."))
        courant = _trav.cle(t["chemin"]) == _trav.cle(_m.RACINE)
        modifie = _trav.changer_chemin(cfg, ident, nouveau, _m.dossiers_de_lutin())
        _m.config_ecrire(cfg)
        if courant:
            _m.definir_racine(modifie["chemin"])
    return travaux_etat()


# --------------------------------------------------------------------------- navigateur de dossiers (la page choisit un dossier sans que l'utilisateur ait à taper son chemin)
MAX_DOSSIERS = 500


def racines():
    """Les points de départ : les disques (Windows) ou « / », le dossier personnel et ses dossiers usuels."""
    sortie = []
    if sys.platform == "win32":
        import ctypes
        masque = ctypes.windll.kernel32.GetLogicalDrives()
        genres = {2: _t("disque amovible"), 3: _t("disque local"), 4: _t("disque réseau"), 5: _t("lecteur optique"), 6: _t("disque virtuel")}
        for i in range(26):
            if masque & (1 << i):
                lettre = chr(65 + i) + ":" + chr(92)
                sortie.append({"nom": "{} ({})".format(lettre, genres.get(ctypes.windll.kernel32.GetDriveTypeW(lettre), _t("disque"))), "chemin": lettre})      # on ne touche pas au disque : un lecteur réseau éteint ferait attendre
    else:
        sortie.append({"nom": "/", "chemin": "/"})
    maison = Path.home()
    sortie.insert(0, {"nom": _t("Dossier personnel ({})").format(maison), "chemin": str(maison)})
    for nom in ("Documents", "Desktop", "Bureau", "Downloads", "Téléchargements"):
        p = maison / nom
        if p.is_dir():
            sortie.insert(1, {"nom": p.name, "chemin": str(p)})
    return sortie


def lister_dossiers(chemin=""):
    """Les sous-dossiers de `chemin` (jamais les fichiers), triés ; sans chemin, les points de départ. `parent` vide = retour aux points de départ. Lève ValueError avec la raison si le dossier est inutilisable."""
    texte = str(chemin or "").strip().strip('"')
    if not texte:
        return {"chemin": "", "parent": None, "dossiers": racines()}
    p = Path(texte)
    raison = _trav.diagnostic(p)
    if raison:
        raise ValueError(raison)

    def lire():
        sortie = []
        with os.scandir(str(p)) as it:
            for e in it:
                try:
                    if e.is_dir():
                        sortie.append({"nom": e.name, "chemin": e.path})
                except OSError:
                    continue
        return sorted(sortie, key=lambda d: d["nom"].lower())
    fini, valeur = _trav.avec_delai(lire)
    if fini is None:
        raise ValueError(_t("Le dossier « {} » ne répond pas (plus de {} s) : un partage réseau éteint, un disque déconnecté ?").format(p, _trav.DELAI_DISQUE_S))
    if not fini:
        raise ValueError(_t("Impossible de lire « {} » : {}").format(p, valeur))
    parent = p.parent
    return {"chemin": str(p), "parent": "" if parent == p else str(parent), "dossiers": valeur[:MAX_DOSSIERS], "tronque": len(valeur) > MAX_DOSSIERS}


# --------------------------------------------------------------------------- projet Claude et reprise d'un autre assistant
def importer_projet_claude(chemin, mode, vers="", nom=""):
    """Reprend un projet « Claude » (CLAUDE.md, .claude/) : `ici` = on travaille dans le dossier lui-même, `copie` = dans une copie (l'original n'est jamais touché). Le dossier devient un dossier de travail
    et le dossier actif."""
    source = Path(chemin.strip()).expanduser()
    raison = _trav.diagnostic(source)
    if raison:
        raise ValueError(raison)
    d = _pc.detecter(source)
    if _pc.est_vide(d):
        raise ValueError(_t("Ni CLAUDE.md ni dossier .claude/ dans ce dossier : ce n'est pas un projet Claude (pour l'utiliser quand même, ajoute-le comme dossier de travail)."))
    if mode not in ("ici", "copie"):
        raise ValueError(_t("Mode inconnu (ici ou copie)."))
    if mode == "copie":
        destination = Path(vers.strip()).expanduser() if vers.strip() else Path.home() / "Lutin" / source.name
        cible = _pc.copier(source, destination)
    else:
        cible = source.resolve()
    etat = ajouter_travail(str(cible), nom.strip() or source.name)
    ident = next((t["id"] for t in etat["liste"] if _trav.cle(t["chemin"]) == _trav.cle(cible)), "")
    choisi = True
    try:
        etat = choisir_travail(ident)
    except ValueError:
        choisi = False          # une réponse travaille ailleurs : le dossier est ajouté, on le choisira ensuite
    return {"mode": mode, "chemin": str(cible), "resume": _pc.resume(d), "actif": choisi, "travaux": etat}


def reprise_detecter(chemin, dossier_skills=""):
    """Ce qu'on peut reprendre dans le dossier (ou l'archive .zip) d'un autre assistant : des nombres, rien n'est écrit. Avec les dossiers de travail où poser les skills."""
    with _rep.ouvrir(chemin, dossier_skills or None) as d:
        cfg = _m.config_lue()
        liste = [dict(t, claude=_rep.est_projet_claude(t["chemin"])) for t in _trav.liste(cfg)]
        actif = _trav.actif(cfg)
        cible = Path(actif["chemin"]) if actif else _m.RACINE
        return dict(_rep.decrire(d), dossier_skills=d["dossier_skills"], dossier_utilise=d["dossier_utilise"], travaux=liste, actif=travaux_etat()["actif"], cible_skills=str(cible / "skills"))


def reprise_importer(chemin, choix, dossier_skills="", ecraser=False, cible=""):
    """Reprend les catégories choisies (conversations, memoire, skills, reglages) ; l'état actuel est gardé dans un zip avant. `cible` : identifiant du dossier de travail où poser les skills (défaut : l'actif)."""
    racine = _m.RACINE
    if cible:
        t = _trav.par_id(_m.config_lue(), cible)
        if not t:
            raise ValueError(_t("Dossier de travail inconnu."))
        racine = Path(t["chemin"])
    c = _m.chemin_config()
    dossiers = {"config": c.parent if c else None, "donnees": _m.DONNEES, "memoire": _m.MEMOIRE}
    with _rep.ouvrir(chemin, dossier_skills or None) as d:
        rapport = _rep.importer(d, dossiers, choix, racine_travail=racine, ecraser=ecraser, workspaces=[t["id"] for t in _trav.liste(_m.config_lue())])
    rapport["resume"] = _rep.resume(rapport)
    return rapport
