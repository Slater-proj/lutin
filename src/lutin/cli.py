"""La commande `lutin`."""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import __version__, bench, catalogue, chat_terminal, client, config, horsligne, i18n, installation, machine, miseajour, ollama_client, projet_claude, reprise, sauvegarde, securite, selection, travaux
from .i18n import t as _t

AIDE_GENERALE = """Lutin : un assistant IA local qui choisit les modèles adaptés à ta machine.

  lutin               démarre (la première fois : installation guidée ; sinon il ne change rien)
  lutin setup         installation guidée (sans effet si Lutin est déjà installé ; --reconfigure pour changer)
  lutin update        met à jour Lutin et cherche des mises à jour de modèles
  lutin chat          discuter dans le terminal
  lutin models       modèles conseillés pour ta machine, installés, mises à jour
  lutin pin           code PIN pour connecter un appareil (niveau « réseau »)
  lutin devices     appareils connectés / révoquer
  lutin security      niveau d'accès actuel
  lutin offline    mode hors ligne strict (aucune connexion vers Internet)
  lutin workspaces       dossiers de travail (lister, ajouter, retirer, actif)
  lutin import-project      reprendre un projet Claude (CLAUDE.md, .claude/) : travailler dedans ou en copie
  lutin migrate     reprendre les données d'un autre assistant (conversations, mémoire, skills, réglages)
  lutin log       ce que Lutin a modifié ou lancé, avec quel accord
  lutin bench         mesurer un modèle sur cette machine (vitesse, outils, code, français)
  lutin bench-engines comparer les moteurs (Ollama, llama.cpp) sur le même modèle
  lutin backup    exporter tes données dans un .zip ; lutin restore pour les remettre
  lutin doctor        diagnostic (à joindre à un rapport de problème)
  lutin colibri       Colibri (expérimental) : installer (somme vérifiée), démarrer, arrêter
"""

# Codes de sortie d'un arrêt voulu (Ctrl+C, arrêt demandé) : pas de relance automatique.
SORTIES_VOULUES = {0, 130, -2, -15, 3221225786, -1073741510}
CODE_REDEMARRAGE = 75          # « relance-moi » demandé depuis la page (voir lutin.acces) : relance immédiate, ce n'est pas une panne


def superviser(lancer, attendre=time.sleep, horloge=time.time, maximum=5, fenetre=600, delai=3, ecrire=print):
    """Relance le serveur s'il s'arrête sur une erreur (au plus `maximum` fois par `fenetre` secondes), jamais s'il a été arrêté volontairement.
    `lancer(premiere_fois)` exécute le serveur et renvoie son code de sortie."""
    pannes, premiere = [], True
    while True:
        code = lancer(premiere)
        premiere = False
        if code in SORTIES_VOULUES:
            return 0
        if code == CODE_REDEMARRAGE:
            ecrire(_t("Redémarrage demandé : Lutin se relance."))
            continue
        maintenant = horloge()
        pannes = [t for t in pannes if maintenant - t < fenetre] + [maintenant]
        if len(pannes) > maximum:
            ecrire(_t("Lutin s'est arrêté {} fois en {} minutes (dernier code : {}) : je n'insiste pas. Voir le journal : lutin doctor.").format(len(pannes), fenetre // 60, code))
            return 1
        ecrire(_t("Lutin s'est arrêté sur une erreur (code {}). Relance dans {} s ({}/{}).").format(code, delai, len(pannes), maximum))
        attendre(delai)


def valeurs(table):
    """Un choix qui accepte l'anglais (le nom officiel, montré dans l'aide) ET le français (l'ancien nom, toujours accepté). `table` : {valeur interne (français): (nom anglais, autres noms…)}.
    Renvoie (fonction de conversion pour `type=`, texte d'aide pour `metavar=`) ; le programme continue de travailler avec les valeurs internes."""
    connus = {}
    for interne, noms in table.items():
        for nom in (interne,) + tuple(noms):
            connus[nom.lower()] = interne
    officiels = [noms[0] for noms in table.values()]

    def convertir(texte):
        interne = connus.get(str(texte).strip().lower())
        if interne is None:
            raise argparse.ArgumentTypeError(_t("valeur inconnue « {} » (choix : {})").format(texte, ", ".join(officiels)))
        return interne
    return convertir, "{" + ",".join(officiels) + "}"


# Chaque commande a un NOM ANGLAIS officiel et garde son ancien nom français comme alias : rien de ce qui est écrit dans un script ou une documentation d'avant ne casse.
ALIAS_COMMANDES = {"models": "modeles", "devices": "appareils", "security": "securite", "workspaces": "travaux", "log": "journal", "bench-engines": "bench-moteurs", "backup": "sauvegarde",
                   "restore": "restaurer", "offline": "hors-ligne", "autostart": "demarrage-auto", "migrate": "reprendre", "import-project": "importer", "language": "langue", "engine-trial": "essai-moteur"}


def parseur():
    p = argparse.ArgumentParser(prog="lutin", description=_t(AIDE_GENERALE), formatter_class=argparse.RawDescriptionHelpFormatter, epilog=_t("« lutin <commande> --help » détaille chaque commande."))
    p.add_argument("--version", action="version", version="Lutin " + __version__)
    sp = p.add_subparsers(dest="commande", metavar="<command>")

    def commande(nom, **kw):
        ancien = ALIAS_COMMANDES.get(nom)
        return sp.add_parser(nom, aliases=[ancien] if ancien else [], **kw)
    niveaux, mv_niveaux = valeurs({"local": ("local",), "reseau": ("network", "lan"), "proxy": ("proxy",)})
    s = commande("setup", help=_t("installation guidée"))
    s.add_argument("--yes", "--oui", dest="oui", action="store_true", help=_t("ne rien demander : valeurs conseillées ou options données"))
    s.add_argument("--level", "--niveau", dest="niveau", type=niveaux, metavar=mv_niveaux)
    s.add_argument("--port", type=int)
    s.add_argument("--url", help=_t("adresse publique (niveau proxy)"))
    s.add_argument("--proxy-ip", action="append", dest="proxy_ips", help=_t("adresse du proxy de confiance (niveau proxy), répétable"))
    s.add_argument("--workspace", "--travail", dest="travail", help=_t("dossier de travail"))
    s.add_argument("--models-dir", "--dossier-modeles", dest="dossier_modeles", help=_t("où ranger les modèles"))
    s.add_argument("--roles", help=_t("rôles à installer, séparés par des virgules (polyvalent,rapide,creatif,code,vision)"))
    s.add_argument("--no-models", "--sans-modeles", dest="sans_modeles", action="store_true")
    s.add_argument("--no-ollama", "--sans-ollama", dest="sans_ollama", action="store_true")
    s.add_argument("--listen", "--ecoute", dest="ecoute", help=_t("adresse d'écoute imposée (conteneur : 0.0.0.0) ; interdite au niveau « local »"))
    s.add_argument("--language", "--langue", dest="langue", choices=i18n.LANGUES + ("auto",), help=_t("langue de l'application (fr, en ou auto)"))
    s.add_argument("--reconfigure", "--reconfigurer", dest="reconfigurer", action="store_true", help=_t("refaire l'installation guidée même si Lutin est déjà installé (les modèles déjà là ne sont pas retéléchargés)"))
    w = commande("wake", help=_t("réveiller une machine par le réseau (Wake-on-LAN)"))
    w.add_argument("mac", help=_t("adresse MAC de la machine à réveiller"))
    w.add_argument("--host", default="", help=_t("adresse IP de la machine (pour viser aussi son réseau)"))
    sv = commande("serve", help=_t("démarrer le serveur"))
    sv.add_argument("--no-browser", "--sans-navigateur", dest="sans_navigateur", action="store_true")
    sv.add_argument("--no-supervisor", "--sans-superviseur", dest="sans_superviseur", action="store_true", help=_t("ne pas relancer automatiquement le serveur s'il s'arrête sur une erreur"))
    u = commande("update", help=_t("mettre à jour Lutin et les modèles"))
    u.add_argument("--app", action="store_true", help=_t("seulement Lutin"))
    u.add_argument("--models", "--modeles", dest="modeles", action="store_true", help=_t("seulement la recherche de mises à jour de modèles"))
    u.add_argument("--rollback-to", "--revenir-a", dest="revenir_a", metavar="X.Y.Z", help=_t("réinstaller une version publiée (retour arrière), après une sauvegarde de tes données"))
    c = commande("chat", help=_t("discuter dans le terminal"))
    c.add_argument("message", nargs="*", help=_t("un message à envoyer tout de suite (sinon, mode interactif)"))
    actions_modeles, mv_modeles = valeurs({"recommander": ("recommend", "suggest"), "lister": ("list",), "installer": ("install",), "supprimer": ("delete", "remove"), "maj": ("update",)})
    m = commande("models", help=_t("modèles"))
    m.add_argument("action", nargs="?", type=actions_modeles, metavar=mv_modeles, default="recommander")
    m.add_argument("modele", nargs="?", metavar="model")
    m.add_argument("--advanced", "--avance", dest="avance", action="store_true", help=_t("inclure les modèles avancés (sans filtre)"))
    m.add_argument("--engine", "--moteur", dest="moteur", default="", help=_t("recommander pour ce moteur (ollama, llamacpp…) : seuls les modèles qu'il sait faire tourner sont proposés"))
    commande("pin", help=_t("nouveau code PIN"))
    actions_appareils, mv_appareils = valeurs({"lister": ("list",), "revoquer": ("revoke",)})
    a = commande("devices", help=_t("appareils connectés"))
    a.add_argument("action", nargs="?", type=actions_appareils, metavar=mv_appareils, default="lister")
    a.add_argument("id", nargs="?")
    se = commande("security", help=_t("niveau d'accès et administration à distance"))
    se.add_argument("--remote-admin", "--admin-distance", dest="admin_distance", choices=("on", "off"), help=_t("ouvre (on) ou ferme (off) la configuration depuis la page aux appareils déjà connectés"))
    actions_travaux, mv_travaux = valeurs({"lister": ("list",), "ajouter": ("add",), "retirer": ("remove",), "actif": ("active",)})
    tr = commande("workspaces", help=_t("dossiers de travail"))
    tr.add_argument("action", nargs="?", type=actions_travaux, metavar=mv_travaux, default="lister")
    tr.add_argument("valeur", nargs="?", metavar="value", help=_t("chemin (ajouter) ou identifiant (retirer, actif)"))
    tr.add_argument("--name", "--nom", dest="nom", default="", help=_t("nom affiché (ajouter)"))
    jo = commande("log", help=_t("journal des actions"))
    jo.add_argument("-n", type=int, default=30, help=_t("nombre d'actions affichées (30)"))
    modes_banc, mv_modes = valeurs({"rapide": ("fast", "quick"), "approfondi": ("deep", "thorough")})
    bm = commande("bench-engines", help=_t("compare les moteurs (Ollama, llama.cpp) sur le même modèle"))
    bm.add_argument("modele", nargs="?", metavar="model", help=_t("modèle à mesurer (défaut : le modèle principal) ; il doit exister sur chaque moteur comparé"))
    bm.add_argument("--mode", type=modes_banc, metavar=mv_modes, default="rapide", help=_t("rapide (environ 1 minute) ou approfondi (environ 5 minutes)"))
    bm.add_argument("--output", "--sortie", dest="sortie", help=_t("écrit le résultat en JSON dans ce fichier, à partager"))
    be = commande("bench", help=_t("banc d'essai d'un modèle"))
    be.add_argument("modeles", nargs="*", metavar="models", help=_t("modèles à mesurer (défaut : le modèle principal)"))
    be.add_argument("--fast", "--rapide", dest="rapide", action="store_true", help=_t("vitesse seulement (environ 20 secondes)"))
    be.add_argument("--engine", "--moteur", dest="moteur", default="ollama", help=_t("moteur à mesurer : ollama (défaut), llamacpp ou openai"))
    be.add_argument("--export", "--exporter", dest="exporter", action="store_true", help=_t("affiche le résultat en JSON, à coller dans une proposition de note au catalogue"))
    sa = commande("backup", help=_t("exporter tes données dans un .zip"))
    sa.add_argument("fichier", nargs="?", metavar="file", help=_t("fichier de destination (défaut : lutin-sauvegarde-<date>.zip)"))
    re_ = commande("restore", help=_t("remettre une sauvegarde"))
    re_.add_argument("fichier", metavar="file")
    re_.add_argument("--yes", "--oui", dest="oui", action="store_true", help=_t("ne pas demander de confirmation"))
    re_.add_argument("--force", "--forcer", dest="forcer", action="store_true", help=_t("restaurer même si Lutin tourne (déconseillé)"))
    etats_hl, mv_hl = valeurs({"oui": ("on", "yes", "true"), "non": ("off", "no", "false"), "etat": ("status",)})
    hl = commande("offline", help=_t("mode hors ligne strict (aucune connexion vers Internet)"))
    hl.add_argument("etat", nargs="?", type=etats_hl, metavar=mv_hl, default="etat")
    commande("doctor", help=_t("diagnostic"))
    actions_colibri, mv_colibri = valeurs({"etat": ("status",), "installer": ("install",), "demarrer": ("start",), "arreter": ("stop",)})
    co = commande("colibri", help=_t("Colibri (moteur expérimental) : installer avec somme vérifiée, démarrer, arrêter"))
    co.add_argument("action", nargs="?", type=actions_colibri, metavar=mv_colibri, default="etat")
    co.add_argument("--model", "--modele", dest="modele", help=_t("dossier de modèle préparé par Colibri (pour « demarrer »)"))
    co.add_argument("--port", type=int, default=8000, help=_t("port local (8000 par défaut)"))
    co.add_argument("--version", dest="version_colibri", help=_t("version à installer (la dernière par défaut)"))
    actions_auto, mv_auto = valeurs({"etat": ("status",), "installer": ("install", "enable"), "retirer": ("remove", "disable")})
    da = commande("autostart", help=_t("démarrer Lutin à l'ouverture de ta session (Windows : clé « Run » de ta session, Linux : systemd)"))
    da.add_argument("action", nargs="?", type=actions_auto, metavar=mv_auto, default="etat")
    rp = commande("migrate", help=_t("reprendre les données d'un autre assistant (conversations, mémoire, skills, réglages)"))
    rp.add_argument("source", help=_t("le dossier de l'ancien assistant (avec donnees/ et memoire/), ou une archive .zip"))
    rp.add_argument("--conversations", action="store_true", help=_t("reprendre les conversations"))
    rp.add_argument("--memory", "--memoire", dest="memoire", action="store_true", help=_t("reprendre la mémoire (CONTEXTE.md, MEMOIRE.md)"))
    rp.add_argument("--skills", action="store_true", help=_t("reprendre les skills (dans le dossier de travail actif)"))
    rp.add_argument("--settings", "--reglages", dest="reglages", action="store_true", help=_t("reprendre les réglages (jamais le modèle ni les accords automatiques)"))
    rp.add_argument("--all", "--tout", dest="tout", action="store_true", help=_t("tout reprendre"))
    rp.add_argument("--skills-dir", "--dossier-skills", dest="dossier_skills", help=_t("où sont les skills de l'ancien assistant (défaut : skills/ à côté)"))
    rp.add_argument("--overwrite", "--ecraser", dest="ecraser", action="store_true", help=_t("remplacer ce qui existe déjà (sinon rien n'est écrasé)"))
    rp.add_argument("--target", "--cible", dest="cible", help=_t("identifiant du dossier de travail où poser les skills (défaut : le dossier actif ; voir lutin workspaces)"))
    im = commande("import-project", help=_t("reprendre un projet Claude (CLAUDE.md, .claude/) comme dossier de travail"))
    im.add_argument("chemin", metavar="path", help=_t("le dossier du projet (celui qui contient CLAUDE.md ou .claude/)"))
    groupe = im.add_mutually_exclusive_group()
    groupe.add_argument("--here", "--ici", dest="ici", action="store_true", help=_t("travailler dans le dossier lui-même"))
    groupe.add_argument("--copy", "--copie", dest="copie", action="store_true", help=_t("travailler dans une copie ; l'original n'est jamais touché"))
    im.add_argument("--to", "--vers", dest="vers", help=_t("dossier de la copie (défaut : ~/Lutin/<nom du projet>)"))
    im.add_argument("--name", "--nom", dest="nom", default="", help=_t("nom affiché"))
    lg = commande("language", help=_t("langue de l'application (fr, en ou auto)"))
    lg.add_argument("valeur", nargs="?", metavar="value", help="fr | en | auto")
    em = commande("engine-trial", help=_t("essai réel d'un moteur (installation, démarrage, conversation, appel d'outil) avec un rapport"))
    em.add_argument("moteur", nargs="?", default="llamacpp", choices=("llamacpp",), metavar="engine", help=_t("le moteur à essayer"))
    em.add_argument("--model", "--modele", dest="modele", help=_t("modèle à télécharger : auteur/dépôt/fichier.gguf"))
    em.add_argument("--local-model", "--modele-local", dest="modele_local", help=_t("nom d'un modèle déjà téléchargé"))
    em.add_argument("--test-model", "--modele-test", dest="modele_test", action="store_true", help=_t("un modèle minuscule (1 Mo) : prouve que le serveur démarre et répond, rien de plus"))
    em.add_argument("--yes", "--oui", dest="oui", action="store_true", help=_t("répond « oui » aux demandes de téléchargement"))
    em.add_argument("--no-tools", "--sans-outils", dest="sans_outils", action="store_true", help=_t("n'essaie pas l'appel d'outil"))
    em.add_argument("--ctx", type=int, default=8192, help=_t("taille de la fenêtre de contexte"))
    em.add_argument("--variant", "--variante", dest="variante", choices=("auto", "cuda", "vulkan", "cpu"), help=_t("version du programme à installer (auto : d'après la carte graphique)"))
    em.add_argument("--folder", "--dossier", dest="dossier", help=_t("dossier d'installation et de modèles (par défaut : à côté de celui d'Ollama s'il a été déplacé, sinon le dossier de Lutin)"))
    actions_mcp, mv_mcp = valeurs({"lister": ("list",), "ajouter": ("add",), "retirer": ("remove",), "actualiser": ("refresh",), "autoriser": ("allow",), "interdire": ("deny",), "ecriture": ("write",)})
    mc = commande("mcp", help=_t("connecteurs MCP (serveurs d'outils)"))
    mc.add_argument("action", nargs="?", type=actions_mcp, metavar=mv_mcp, default="lister")
    mc.add_argument("nom", nargs="?", metavar="name", help=_t("nom du connecteur"))
    mc.add_argument("cible", nargs="?", metavar="target", help=_t("commande à lancer ou adresse http (ajouter) ; nom de l'outil (autoriser, interdire)"))
    mc.add_argument("--env", action="append", default=[], help=_t("variable d'environnement CLE=VALEUR (ajouter), répétable"))
    commande("zone", help=_t("Lutin dans la zone de notification de Windows, sans fenêtre de console (code PIN, redémarrer, quitter)"))
    return p


def contexte():
    d = config.dossiers()
    return d, config.charger(d)


def commande_setup(args, es=None):
    d, cfg = contexte()
    options = {"niveau": args.niveau, "port": args.port, "url": args.url, "proxy_ips": args.proxy_ips, "travail": args.travail, "dossier_modeles": args.dossier_modeles,
               "roles": [r.strip() for r in args.roles.split(",") if r.strip()] if args.roles else None, "sans_modeles": args.sans_modeles, "sans_ollama": args.sans_ollama,
               "reconfigurer": getattr(args, "reconfigurer", False), "ecoute": getattr(args, "ecoute", None), "langue": getattr(args, "langue", None)}
    es = es or installation.Es(oui=args.oui)
    try:
        installation.executer(cfg, d, es, options)
    except ValueError as e:
        print("✘ " + str(e), file=sys.stderr)
        return 2
    return 0


def lancer_enfant(sans_navigateur):
    """Exécute `lutin serve --no-supervisor` dans un processus séparé et renvoie son code ; s'il faut s'arrêter, le processus enfant s'arrête avec nous."""
    commande = [sys.executable, "-m", "lutin", "serve", "--no-supervisor"] + (["--no-browser"] if sans_navigateur else [])
    enfant = subprocess.Popen(commande, env=dict(os.environ, LUTIN_SUPERVISE="1"))
    try:
        return enfant.wait()
    except KeyboardInterrupt:
        enfant.terminate()
        try:
            enfant.wait(10)
        except subprocess.TimeoutExpired:
            enfant.kill()
        return 130
    finally:
        if enfant.poll() is None:
            enfant.kill()


def commande_zone(args):
    from . import zone
    d, cfg = contexte()
    return zone.commande(d, cfg)


def commande_serve(args):
    from . import demarrage
    d, cfg = contexte()
    if not cfg["installe"]:
        print(_t("Première utilisation : installation guidée.\n"))
        if commande_setup(argparse.Namespace(oui=False, niveau=None, port=None, url=None, proxy_ips=None, travail=None, dossier_modeles=None, roles=None, sans_modeles=False, sans_ollama=False,
                                             reconfigurer=False)):
            return 2
        d, cfg = contexte()
    sans_navigateur = getattr(args, "sans_navigateur", False)
    if getattr(args, "sans_superviseur", False):
        demarrage.lancer_serveur(cfg, d, ouvrir_navigateur=not sans_navigateur)
        return 0
    return superviser(lambda premiere: lancer_enfant(sans_navigateur or not premiere))          # le navigateur ne s'ouvre qu'au premier démarrage, pas à chaque relance


AVANT_MAJ_GARDEES = 3


def sauvegarde_avant_mise_a_jour(dire=print):
    """Une sauvegarde des données avant de changer de version : on ne perd rien si la nouvelle version se comporte mal (voir « lutin restore »). Les trois dernières sont gardées.
    Ne bloque jamais la mise à jour : si la sauvegarde échoue, on le dit et on continue. Renvoie le chemin du fichier, ou None."""
    try:
        dossier = Path(config.dossiers()["cache"]) / "avant-mise-a-jour"
        dossier.mkdir(parents=True, exist_ok=True)
        fichier = dossier / "lutin-{}-{}.zip".format(__version__, time.strftime("%Y%m%d-%H%M%S"))
        sauvegarde.exporter(config.dossiers(), fichier)
        for ancien in sorted(dossier.glob("lutin-*.zip"), key=lambda p: p.stat().st_mtime)[:-AVANT_MAJ_GARDEES]:
            ancien.unlink(missing_ok=True)
        dire(_t("Sauvegarde de tes données avant la mise à jour : {}").format(fichier))
        return fichier
    except (OSError, ValueError) as e:
        dire(_t("Sauvegarde avant mise à jour impossible ({}) : la mise à jour continue.").format(e))
        return None


def mise_a_jour_detaillee(dire=print, erreur=None, capturer=False, revenir_a=None):
    """Met Lutin à jour d'après la source mémorisée à l'installation : « github:propriétaire/dépôt » (dernière publication, comparée à la version installée) ou une adresse / une roue
    donnée à pip. Ne fait rien si Lutin est déjà à jour. `dire` / `erreur` : où vont les messages (la console par défaut, la page ou l'icône ailleurs) ; `capturer` : cache la sortie de pip.
    `revenir_a` : un numéro de version publiée (« 0.22.0 ») à réinstaller à la place de la dernière (retour arrière).
    Renvoie (code de sortie, version avant, version après) ; « après » vaut None si rien n'a été installé."""
    erreur = erreur or (lambda texte: print(texte, file=sys.stderr))
    source = config.lire_source()
    if not source:
        dire(_t("Lutin ne sait pas d'où se mettre à jour (installé à la main ?). Relance le script d'installation, ou : python -m pip install --upgrade <source>"))
        return 0, __version__, None
    if revenir_a:
        if not source.startswith("github:"):
            erreur(_t("✘ Le retour à une version précise n'est possible que pour une installation faite depuis GitHub."))
            return 1, __version__, None
        try:
            version, source = miseajour.roue_de_version(revenir_a, source[len("github:"):])
        except ValueError as e:
            erreur("✘ " + str(e))
            return 1, __version__, None
        if version == __version__:
            dire(_t("Lutin est déjà en version {}.").format(version))
            return 0, __version__, None
    elif source.startswith("github:"):
        version, roue = miseajour.derniere_release(source[len("github:"):])
        if not roue:
            erreur(_t("✘ Impossible de lire la dernière version de Lutin sur GitHub (pas d'internet, ou aucune publication)."))
            return 1, __version__, None
        if not miseajour.plus_recente(version, __version__):
            dire(_t("Lutin est déjà à jour ({}).").format(__version__))
            return 0, __version__, None
        source = roue
    avant = __version__
    verifier = source.startswith("https://github.com/") and source.endswith(".whl")          # une publication de GitHub : sa somme est vérifiée ; une source choisie à la main (chemin, autre adresse) l'est par son auteur
    sauvegarde_avant_mise_a_jour(dire)
    with tempfile.TemporaryDirectory(prefix="lutin-maj-") as dossier:
        if verifier:
            try:
                chemin, verifie = miseajour.telecharger_roue_verifiee(source, dossier)
            except miseajour.ErreurVerification as e:
                erreur("✘ " + str(e))
                return 1, avant, None
            except OSError as e:
                erreur(_t("✘ Téléchargement impossible : {}").format(e))
                return 1, avant, None
            source = str(chemin)
            dire(_t("✔ Somme SHA-256 vérifiée.") if verifie else _t("⚠ Cette publication n'a pas de SHA256SUMS.txt : la roue n'a pas pu être vérifiée."))
        code = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", source], capture_output=capturer).returncode
    if code != 0:
        erreur(_t("✘ La mise à jour de Lutin a échoué (pip). Ta version actuelle reste en place."))
        return 1, avant, None
    apres = subprocess.run([sys.executable, "-m", "lutin", "--version"], capture_output=True, text=True).stdout.strip().replace("Lutin ", "")
    if apres in ("", avant):
        dire(_t("Lutin est déjà à jour ({}).").format(avant))
        return 0, avant, None
    dire(_t("✔ Lutin mis à jour : {} → {}.").format(avant, apres))
    return 0, avant, apres


def mettre_a_jour_lutin(revenir_a=None):
    return mise_a_jour_detaillee(revenir_a=revenir_a)[0]


def commande_update(args):
    """Met à jour Lutin lui-même (avec la source mémorisée par l'installateur) puis cherche des mises à jour de modèles. Ne change rien si tout est à jour."""
    tout = not (args.app or args.modeles)
    code = 0
    if (args.app or tout) and horsligne.actif(Path(config.dossiers()["config"]) / "config.json"):
        print(_t("Mode hors ligne strict : Lutin n'est pas mis à jour (lutin offline off pour le permettre)."))
    elif getattr(args, "revenir_a", None):
        code = mettre_a_jour_lutin(args.revenir_a)
    elif args.app or tout:
        code = mettre_a_jour_lutin()
    if args.modeles or tout:
        d, cfg = contexte()
        r = miseajour.verifier(machine.detecter(), cfg, d, ollama_client.Ollama(), force=True)
        for p in r["propositions"]:
            print("• {} : {}".format(p["modele"], p["raison"]))
        print(_t("Modèles : rien de nouveau.") if not r["propositions"] else _t("Pour en installer un :  lutin models install <identifiant>"))
        for e in r["erreurs"]:
            print("  (" + e + ")")
    return code


def client_pret():
    d, _ = contexte()
    c = client.ClientLocal(d["donnees"])
    if not c.disponible():
        print(_t("Lutin ne tourne pas. Lance « lutin serve » (ou « lutin ») dans une autre fenêtre, puis recommence."), file=sys.stderr)
        return None
    return c


def commande_chat(args):
    c = client_pret()
    if not c:
        return 1
    t = chat_terminal.Terminal(c)
    if args.message:
        t.repondre(" ".join(args.message))
        return 0
    return t.boucle()


def commande_modeles(args):
    d, cfg = contexte()
    cat = catalogue.charger(Path(d["cache"]) / "catalogue.json")
    profil = machine.detecter()
    o = ollama_client.Ollama()
    if args.action == "recommander":
        if getattr(args, "moteur", ""):          # les rôles sont propres à chaque moteur : jamais un modèle que ce moteur ne sait pas faire tourner
            os.environ.setdefault("LUTIN_RACINE", str(Path.home() / "Lutin"))
            os.environ.setdefault("LUTIN_DONNEES", str(d["donnees"]))
            os.environ.setdefault("LUTIN_MEMOIRE", str(d["memoire"]))
            from . import compat_modeles, moteur as _moteur, moteurs  # noqa: F401  (importer le moteur enregistre les moteurs)
            mo = moteurs.MOTEURS.get(args.moteur)
            if mo is None:
                print(_t("Moteur inconnu : {}.").format(args.moteur), file=sys.stderr)
                return 1
            choix = compat_modeles.roles_pour(profil, cat, mo)
        else:
            choix = selection.choisir(profil, cat)
        print(_t("Ta machine : ") + profil.resume() + "\n")
        for role in catalogue.ROLES:
            c = choix.get(role)
            titre = _t(catalogue.LIBELLES[role][0])
            print("{:<11} {}".format(titre, "—" if not c else "{} ({:g} Go)".format(c.id, c.modele["go"])))
            if c:
                print("            " + c.modele["phrase"])
        print(_t("\nInstaller :  lutin models install <identifiant>"))
        return 0
    if args.action == "lister":
        try:
            installes = o.installes()
        except ollama_client.ErreurOllama as e:
            print("✘ " + str(e), file=sys.stderr)
            return 1
        mesures = bench.lire(Path(d["cache"]) / "bench.json")
        for x in selection.lister(profil, cat, avance=args.avance or cfg.get("avance", False)):
            m = x["modele"]
            etat = _t("installé") if m["id"] in installes else ("tient" if x["tient"] else "trop gros")
            print("{:<38} {:>5g} Go  {:<10} {}".format(m["id"], m["go"], etat, m["phrase"]))
            if m["id"] in mesures:
                print("{:<38} {}".format("", _t("mesuré ici : ") + bench.resume(mesures[m["id"]])))
        return 0
    if args.action in ("installer", "supprimer") and not args.modele:
        print(_t("Indique un modèle : lutin models {} <identifiant>").format(args.action), file=sys.stderr)
        return 2
    try:
        if args.action == "installer":
            m = catalogue.par_id(cat).get(args.modele)
            if m and m.get("avertissement"):
                print("⚠ " + m["avertissement"])
            o.telecharger(args.modele, installation.barre(installation.Es()))
            print(_t("✔ installé : ") + args.modele)
        elif args.action == "supprimer":
            o.supprimer(args.modele)
            print(_t("✔ supprimé : ") + args.modele)
        elif args.action == "maj":
            r = miseajour.verifier(profil, cfg, d, o, force=True)
            for p in r["propositions"]:
                print("• {} : {}".format(p["modele"], p["raison"]))
            print(_t("Rien de nouveau.") if not r["propositions"] else _t("\nInstaller :  lutin models install <identifiant>"))
            for e in r["erreurs"]:
                print("(" + e + ")")
    except (ollama_client.ErreurOllama, horsligne.HorsLigne) as e:
        print("✘ " + str(e), file=sys.stderr)
        return 1
    return 0


def commande_pin(args):
    c = client_pret()
    if not c:
        return 1
    try:
        r = c.envoyer("/api/nouveau-pin", {})
    except client.ErreurClient as e:
        print("✘ " + str(e), file=sys.stderr)
        return 1
    print(_t("Code PIN : {}   (valable {} minutes, un seul appareil)").format(r["pin"], r["valable_s"] // 60))
    return 0


def commande_appareils(args):
    c = client_pret()
    if not c:
        return 1
    try:
        if args.action == "revoquer":
            r = c.envoyer("/api/appareils-revoquer", {"id": args.id})
            print(_t("{} appareil(s) déconnecté(s).").format(r["revoques"]))
            return 0
        r = c.envoyer("/api/appareils", {})
    except client.ErreurClient as e:
        print("✘ " + str(e), file=sys.stderr)
        return 1
    if not r["appareils"]:
        print(_t("Aucun appareil connecté (niveau : {}).").format(r["niveau"]))
    for a in r["appareils"]:
        print("{}  {}".format(a["id"], a["nom"]))
    return 0


def commande_hors_ligne(args):
    d, _ = contexte()
    chemin = Path(d["config"]) / "config.json"
    if args.etat != "etat":
        horsligne.definir(args.etat == "oui", chemin)
    actif = horsligne.actif(chemin)
    print(_t("Mode hors ligne strict : {}.").format(_t("ACTIF (aucune connexion vers Internet)") if actif else _t("coupé")))
    if args.etat != "etat":
        print(_t("Si Lutin tourne, il en tient compte tout de suite."))
    return 0


def commande_travaux(args):
    d, cfg = contexte()
    interdits = [d["config"], d["donnees"], d["memoire"], d["cache"]]
    try:
        if args.action == "ajouter":
            t = travaux.ajouter(cfg, args.valeur, args.nom, interdits)
            config.enregistrer(d, cfg)
            print(_t("✔ Dossier de travail « {} » : {}").format(t["nom"], t["chemin"]))
        elif args.action == "retirer":
            travaux.retirer(cfg, args.valeur or "")
            config.enregistrer(d, cfg)
            print(_t("✔ Retiré de la liste (les fichiers ne sont pas touchés)."))
        elif args.action == "actif":
            t = travaux.choisir(cfg, args.valeur or "")
            config.enregistrer(d, cfg)
            print(_t("✔ Dossier actif : {} ({})").format(t["nom"], t["chemin"]))
            print(_t("Si Lutin tourne déjà, choisis aussi ce dossier dans l'interface (ou relance Lutin)."))
    except travaux.ErreurTravail as e:
        print("✘ " + str(e), file=sys.stderr)
        return 1
    actif = travaux.actif(cfg)
    for t in travaux.liste(cfg):
        print("{} {:<14} {:<22} {}".format("→" if actif and t["id"] == actif["id"] else " ", t["id"], t["nom"], t["chemin"]))
    if not travaux.liste(cfg):
        print(_t("Aucun dossier de travail : lutin workspaces add <chemin>"))
    return 0


def commande_bench_moteurs(args):
    """Compare les moteurs disponibles (Ollama, llama.cpp) sur le même modèle et conserve un résultat lisible et partageable (voir bench_moteurs.py)."""
    d, cfg = contexte()
    os.environ.setdefault("LUTIN_RACINE", str(Path.home() / "Lutin"))
    os.environ.setdefault("LUTIN_DONNEES", str(d["donnees"]))
    os.environ.setdefault("LUTIN_MEMOIRE", str(d["memoire"]))
    from . import bench_moteurs, moteur as _moteur  # noqa: F401  (importer le moteur enregistre les moteurs)
    profil = machine.detecter()
    modele = args.modele or cfg["modeles"]["choisis"].get("polyvalent") or ""
    if not modele:
        print(_t("Aucun modèle à mesurer : indique-le (lutin bench-engines <modèle>)."), file=sys.stderr)
        return 1
    print(_t("Comparaison des moteurs avec {} ({}, environ {})…").format(modele, args.mode, "1 minute" if args.mode == "rapide" else "5 minutes"))
    r = bench_moteurs.comparer(modele, args.mode, profil, progression=lambda texte, i, n: print("  {} ({}/{})".format(texte, i + 1, n)))
    print(bench_moteurs.lisible(r))
    if r["moteurs"]:
        bench_moteurs.enregistrer(d["donnees"], r)
    if args.sortie:
        Path(args.sortie).write_text(bench_moteurs.exporter(r), encoding="utf-8")
        print(_t("Résultat écrit dans {} (rien de personnel : à partager tel quel).").format(args.sortie))
    return 0 if r["moteurs"] and all(m["ok"] for m in r["moteurs"]) else 1


def commande_essai_moteur(args):
    """Fait pour de vrai, sur cette machine, ce que Lutin fait avec un moteur (voir essai_moteur.py) et écrit un rapport."""
    d, cfg = contexte()
    actif = travaux.actif(cfg)
    os.environ.setdefault("LUTIN_RACINE", str(actif["chemin"] if actif else Path.home() / "Lutin"))
    os.environ.setdefault("LUTIN_DONNEES", str(d["donnees"]))
    os.environ.setdefault("LUTIN_MEMOIRE", str(d["memoire"]))
    from . import essai_moteur, moteur as _moteur, moteur_llamacpp, moteurs  # noqa: F401  (importer le moteur enregistre les moteurs)
    mo = moteurs.par_id(args.moteur)
    if args.variante:
        moteur_llamacpp.regler(mo.id, variante=args.variante)
    if args.dossier:
        try:
            moteur_llamacpp.regler_dossier(mo.id, args.dossier)
        except ValueError as e:
            print("✘ " + str(e), file=sys.stderr)
            return 1
    horodatage = time.strftime("%Y%m%d-%H%M%S")
    rapport = Path(d["donnees"]) / "essais" / "essai-{}-{}.json".format(mo.id, horodatage)
    resultat = essai_moteur.executer({"modele": args.modele, "modele_local": args.modele_local, "modele_test": args.modele_test, "oui": args.oui, "sans_outils": args.sans_outils, "ctx": args.ctx}, mo, chemin_rapport=rapport)
    return 0 if resultat["reussi"] else 1


def commande_mcp(args):
    """Les connecteurs MCP en ligne de commande (utile dans Docker, où la page ne peut pas les modifier)."""
    d, cfg = contexte()
    actif = travaux.actif(cfg)          # le moteur lit ces dossiers à l'import : on les fixe sans rien créer (ni dossier de travail, ni réglage)
    os.environ.setdefault("LUTIN_RACINE", str(actif["chemin"] if actif else Path.home() / "Lutin"))
    os.environ.setdefault("LUTIN_DONNEES", str(d["donnees"]))
    os.environ.setdefault("LUTIN_MEMOIRE", str(d["memoire"]))
    from . import mcp
    try:
        if args.action == "ajouter":
            if not args.nom or not args.cible:
                raise ValueError(_t("lutin mcp add <nom> <commande ou adresse>"))
            env = dict(x.split("=", 1) for x in args.env if "=" in x)
            ident = mcp.ajouter(args.nom, None if args.cible.lower().startswith(("http://", "https://")) else args.cible, args.cible if args.cible.lower().startswith(("http://", "https://")) else "", env)
            print(_t("✔ Connecteur « {} » ajouté. Étape suivante : lutin mcp refresh {}").format(ident, ident))
        elif args.action == "retirer":
            mcp.supprimer(mcp.identifiant(args.nom))
            print(_t("✔ Connecteur retiré."))
        elif args.action == "actualiser":
            n = mcp.actualiser(mcp.identifiant(args.nom))
            mcp.fermer()
            print(_t("✔ {} outil(s) trouvé(s). Autorise ceux que le modèle peut utiliser : lutin mcp allow {} <outil>").format(n, args.nom))
        elif args.action in ("autoriser", "interdire"):
            mcp.regler(mcp.identifiant(args.nom), outil=args.cible, autorise=args.action == "autoriser")
            print(_t("✔ Fait."))
        elif args.action == "ecriture":
            mcp.regler(mcp.identifiant(args.nom), lecture_seule=False)
            print(_t("✔ Ce connecteur n'est plus en lecture seule : ses outils qui modifient quelque chose restent soumis à ton accord, à chaque appel."))
    except ValueError as e:
        print("✘ " + str(e), file=sys.stderr)
        return 1
    for c in mcp.vue():
        print("{:<16} {:<8} {}".format(c["id"], _t("lecture seule") if c["lecture_seule"] else _t("écriture"), (c["url"] or " ".join(c["commande"] or []))[:60]))
        for o in c["outils"]:
            print("    {} {:<28} {}".format("☑" if o["autorise"] else "☐", o["nom"], _t("lecture") if o["lecture"] else _t("modifie quelque chose")))
    if not mcp.vue():
        print(_t("Aucun connecteur : lutin mcp add <nom> <commande ou adresse>"))
    return 0


def commande_journal(args):
    d, _ = contexte()
    f = Path(d["donnees"]) / "journal-actions.jsonl"
    try:
        lignes = f.read_text(encoding="utf-8").splitlines()[-max(1, args.n):]
    except OSError:
        print(_t("Aucune action enregistrée pour le moment."))
        return 0
    import json
    for ligne in lignes:
        try:
            e = json.loads(ligne)
        except ValueError:
            continue
        print(_t("{} {:<18} {:<8} accord {:<6} par {:<10} {}").format(e["ts"].replace("T", " "), e["outil"], e["issue"][:8], e["accord"], e.get("qui") or "?", e["cible"]))
    return 0


def commande_bench(args):
    d, cfg = contexte()
    if getattr(args, "moteur", "ollama") != "ollama":          # le banc ne dépend pas d'Ollama : n'importe quel moteur de Lutin se mesure de la même façon
        os.environ.setdefault("LUTIN_RACINE", str(Path.home() / "Lutin"))
        os.environ.setdefault("LUTIN_DONNEES", str(d["donnees"]))
        os.environ.setdefault("LUTIN_MEMOIRE", str(d["memoire"]))
        from . import moteur as _moteur, moteurs  # noqa: F401  (importer le moteur enregistre les moteurs)
        mo = moteurs.MOTEURS.get(args.moteur)
        if mo is None:
            print(_t("Moteur inconnu : {}.").format(args.moteur), file=sys.stderr)
            return 1
        try:
            o, installes = bench.AdaptateurMoteur(mo), set(mo.modeles()["installes"])
        except (ValueError, OSError) as e:
            print("✘ " + str(e), file=sys.stderr)
            return 1
    else:
        o = ollama_client.Ollama()
        try:
            installes = o.installes()
        except ollama_client.ErreurOllama as e:
            print("✘ " + str(e), file=sys.stderr)
            return 1
    cibles = args.modeles or [cfg["modeles"]["choisis"].get("polyvalent") or next(iter(installes), "")]
    if not cibles or not cibles[0]:
        print(_t("Aucun modèle installé à mesurer."), file=sys.stderr)
        return 1
    resume = machine.detecter().resume()
    code = 0
    for m in cibles:
        if m not in installes:
            print(_t("✘ {} n'est pas installé.").format(m), file=sys.stderr)
            code = 1
            continue
        print(_t("Mesure de {} ({})…").format(m, "vitesse seulement" if args.rapide else "banc complet, quelques minutes"))
        mesure = bench.executer(o, m, rapide=args.rapide, resume_machine=resume, progression=lambda nom, i, n: print("  {} ({}/{})".format(_t(nom), i + 1, n)))
        bench.enregistrer(Path(d["cache"]) / "bench.json", mesure)
        print("  → " + bench.resume(mesure))
        if mesure["notes"]:
            print(_t("  Notes mesurées (indicatives, une vingtaine de questions) : ") + ", ".join("{} {}/10".format(_t(catalogue.LIBELLES[r][0]).lower(), n) for r, n in mesure["notes"].items()))
        if mesure.get("erreur"):
            print(_t("  ⚠ Mesure incomplète : ") + mesure["erreur"])
            code = 1
        if args.exporter:
            print(bench.exporter(mesure))
    return code


def commande_sauvegarde(args):
    d, _ = contexte()
    destination = Path(args.fichier or "lutin-sauvegarde-{}.zip".format(time.strftime("%Y%m%d-%H%M%S")))
    try:
        r = sauvegarde.exporter(d, destination)
    except sauvegarde.ErreurSauvegarde as e:
        print("✘ " + str(e), file=sys.stderr)
        return 1
    print(_t("✔ {} : {} fichier(s), {:.1f} Mo avant compression.").format(destination, r["fichiers"], r["octets"] / 1024 ** 2))
    print(_t("Contient tes conversations, réglages, journal et mémoire. Ne contient ni appareils connectés, ni jeton, ni fichiers de ton dossier de travail."))
    return 0


def commande_restaurer(args):
    d, _ = contexte()
    try:
        m = sauvegarde.verifier(args.fichier)
    except sauvegarde.ErreurSauvegarde as e:
        print("✘ " + str(e), file=sys.stderr)
        return 1
    if not args.forcer and client.ClientLocal(d["donnees"]).disponible():
        print(_t("✘ Lutin tourne : arrête-le avant de restaurer (ou --force)."), file=sys.stderr)
        return 1
    print(_t("Sauvegarde du {} (Lutin {}) : {} fichier(s).").format(m.get("date", "?"), m.get("lutin", "?"), len(m.get("fichiers", []))))
    if not args.oui and input(_t("Remplacer tes données actuelles par celles-ci ? L'état actuel est gardé dans un zip « avant-restauration ». [o/N] ")).strip().lower() not in ("o", "oui", "y", "yes"):
        print(_t("Rien n'a été changé."))
        return 0
    r = sauvegarde.restaurer(d, args.fichier, d["cache"])
    print(_t("✔ {} fichier(s) restauré(s). État précédent : {}").format(r["fichiers"], r["secours"]))
    return 0


def commande_securite(args):
    d, cfg = contexte()
    if getattr(args, "admin_distance", None):
        cfg["admin_a_distance"] = args.admin_distance == "on"
        config.enregistrer(d, cfg)
        print(_t("✔ Administration à distance {}.").format(_t("ouverte") if cfg["admin_a_distance"] else _t("fermée")))
    s = securite.Securite.depuis_dict(cfg["securite"])
    texte = {securite.LOCAL: _t("cette machine seulement"), securite.RESEAU: _t("réseau local (code PIN)"), securite.PROXY: _t("derrière un proxy")}[s.niveau]
    print(_t("Niveau : {} — {}").format(s.niveau, texte))
    if s.niveau == securite.PROXY:
        print(_t("Adresse publique : {}   Proxy de confiance : {}").format(s.url_publique, ", ".join(s.proxy_ips)))
    for p in s.valider():
        print("⚠ " + p)
    print(_t("Administration à distance : {}").format(_t("ouverte (tout appareil connecté peut configurer)") if cfg.get("admin_a_distance") else _t("fermée (seule cette machine configure)")))
    print(_t("Pour changer : lutin setup --level local|reseau|proxy ; lutin security --remote-admin on|off"))
    return 0


def commande_reprendre(args, entree=input):
    """Reprend les données d'un autre assistant, au choix. Rien n'est écrasé sans --overwrite ; l'état actuel de Lutin est gardé dans un zip avant."""
    d, cfg = contexte()
    try:
        with reprise.ouvrir(args.source, args.dossier_skills) as trouve:
            nombres = reprise.decrire(trouve)
            lignes = [("conversations", _t("Conversations : {}").format(nombres["conversations"])),
                      ("memoire", _t("Mémoire : {}").format(", ".join(nombres["memoire"]) or "-")),
                      ("skills", _t("Skills : {}").format(nombres["skills"]) + ((" (" + trouve["dossier_skills"] + ")") if trouve["dossier_skills"] else "")),
                      ("reglages", _t("Réglages : {}").format(_t("oui") if nombres["reglages"] else _t("non")))]
            print(_t("Trouvé dans {} :").format(trouve["origine"]))
            for i, (_, texte) in enumerate(lignes, 1):
                print("  {}. {}".format(i, texte))
            choix = [k for k in reprise.CATEGORIES if getattr(args, k)] if not args.tout else list(reprise.CATEGORIES)
            if not choix:
                try:
                    reponse = entree(_t("Que reprendre ? (numéros séparés par des virgules, Entrée = tout)") + " ").strip()
                except EOFError:
                    reponse = ""
                nums = {int(x) for x in reponse.replace(" ", ",").split(",") if x.isdigit()}
                choix = [lignes[i - 1][0] for i in sorted(nums) if 1 <= i <= len(lignes)] if nums else list(reprise.CATEGORIES)
            actif = travaux.par_id(cfg, args.cible) if args.cible else travaux.actif(cfg)
            if args.cible and not actif:
                raise ValueError(_t("Dossier de travail inconnu."))
            racine = actif["chemin"] if actif else cfg["emplacements"]["travail"]
            rapport = reprise.importer(trouve, d, choix, racine_travail=racine, ecraser=args.ecraser, workspaces=[t["id"] for t in travaux.liste(cfg)])
    except ValueError as e:
        print("✘ " + str(e), file=sys.stderr)
        return 2
    for ligne in reprise.resume(rapport):
        print(ligne)
    return 0


def commande_importer(args, entree=input):
    """Reprend un projet Claude : ce que Lutin y trouve, puis « travailler dedans » ou « en faire une copie » (copie par défaut : l'original reste intact)."""
    d, cfg = contexte()
    source = Path(args.chemin).expanduser()
    if not source.is_dir():
        print("✘ " + _t("Ce dossier n'existe pas : {}").format(source), file=sys.stderr)
        return 2
    trouve = projet_claude.detecter(source)
    if projet_claude.est_vide(trouve):
        print("✘ " + _t("Ni CLAUDE.md ni dossier .claude/ dans ce dossier : ce n'est pas un projet Claude (pour l'utiliser quand même : lutin workspaces add <dossier>)."), file=sys.stderr)
        return 2
    print(_t("Trouvé dans {} : {}").format(source, projet_claude.resume(trouve)))
    mode = "ici" if args.ici else "copie" if args.copie else None
    if mode is None:
        print(_t("  1. Faire une copie (l'original n'est jamais touché)  [conseillé]\n  2. Travailler dedans (les fichiers sont lus et modifiés sur place, avec ton accord)"))
        try:
            reponse = entree(_t("Ton choix") + " [1] ").strip()
        except EOFError:
            reponse = ""
        mode = "ici" if reponse == "2" else "copie"
    try:
        if mode == "copie":
            destination = Path(args.vers).expanduser() if args.vers else Path.home() / "Lutin" / source.name
            cible = projet_claude.copier(source, destination)
            print(_t("✔ Copie faite : {}").format(cible))
        else:
            cible = source.resolve()
        interdits = [d["config"], d["donnees"], d["memoire"], d["cache"]]
        t = travaux.ajouter(cfg, str(cible), args.nom or source.name, interdits)
        travaux.choisir(cfg, t["id"])
        config.enregistrer(d, cfg)
    except ValueError as e:
        print("✘ " + str(e), file=sys.stderr)
        return 2
    print(_t("✔ Dossier de travail « {} » : {}").format(t["nom"], t["chemin"]))
    print(_t("Il est maintenant le dossier actif. Si Lutin tourne, choisis-le dans la liste des dossiers de travail."))
    if mode == "ici":
        print(_t("Attention : Lutin travaille dans ton dépôt lui-même. Il peut y lire et y modifier des fichiers (chaque modification demande ton accord, avec les différences, et peut être annulée). Pour revenir à ton ancien dossier de travail : lutin workspaces active <identifiant> (liste : lutin workspaces)."))
    return 0


NOMS_LANGUES = {"fr": "Français", "en": "English"}


def commande_langue(args):
    """Sans argument : affiche la langue. Avec fr, en ou auto : l'enregistre (auto = suivre la langue du système)."""
    d, _ = contexte()
    chemin = Path(d["config"]) / "config.json"
    if args.valeur:
        try:
            i18n.definir(args.valeur.strip().lower(), chemin)
        except ValueError as e:
            print("✘ " + str(e), file=sys.stderr)
            return 2
    print(_t("Langue : {}").format(NOMS_LANGUES[i18n.langue()]))
    imposee = os.environ.get("LUTIN_LANGUE", "").strip().lower()
    if imposee in i18n.LANGUES:
        print(_t("La variable LUTIN_LANGUE ({}) l'emporte sur ce réglage.").format(imposee))
    elif not args.valeur:
        print(_t("Pour changer : lutin language fr|en|auto (auto : suivre la langue du système)"))
    return 0


def diagnostic(cfg, dossiers, profil, ollama):
    """[(niveau, texte)] — sans conversation ni contenu personnel : peut être collé dans un rapport de problème."""
    lignes = [("info", "Lutin " + __version__), ("info", _t("Machine : {}").format(profil.resume())), ("info", _t("Système : {} {}").format(profil.systeme, profil.architecture))]
    if profil.sans_gpu():
        lignes.append(("attention", _t("Pas de carte graphique utilisable : les modèles tourneront sur le processeur.")))
        if os.environ.get("LUTIN_DOCKER"):
            lignes.append(("attention", _t("Dans un conteneur, la carte doit être donnée au conteneur : NVIDIA avec --gpus all, AMD avec l'image :rocm et /dev/kfd + /dev/dri (docs/DOCKER.md).")))
    for g in profil.gpus:
        lignes.append(("info", _t("Carte : {} ({:g} Go, source : {})").format(g.nom, g.vram_go, g.source)))
    try:
        lignes.append(("ok", _t("Ollama {} répond").format(ollama.version())))
        installes = ollama.installes()
        lignes.append(("ok" if installes else "attention", _t("{} modèle(s) installé(s)").format(len(installes))))
    except ollama_client.ErreurOllama:
        lignes.append(("erreur", _t("Ollama ne répond pas (installé : {})").format("oui" if ollama_client.trouver_executable(profil.systeme) else "non")))
    s = securite.Securite.depuis_dict(cfg["securite"])
    lignes.append(("info", _t("Niveau de sécurité : ") + s.niveau))
    lignes += [("erreur", p) for p in s.valider()]
    for disque in profil.disques:
        lignes.append(("attention" if disque.libre_go < 20 else "info", "Disque {} : {:g} Go libres".format(disque.racine, disque.libre_go)))
    lignes.append(("ok" if cfg["installe"] else "attention", _t("Installation guidée : ") + ("faite" if cfg["installe"] else _t("à faire (lutin setup)"))))
    return lignes


def commande_demarrage_auto(args):
    from . import alimentation
    try:
        e = alimentation.installer_demarrage() if args.action == "installer" else alimentation.retirer_demarrage() if args.action == "retirer" else alimentation.etat_demarrage()
    except ValueError as err:
        print("✘ " + str(err), file=sys.stderr)
        return 1
    print(_t("Démarrage automatique : ") + (_t("activé") if e["installe"] else _t("désactivé")))
    print(e["limites"])
    return 0


def commande_colibri(args):
    """Aide à Colibri, expérimentale : rien ne tourne sans cette commande, et le serveur n'écoute que sur 127.0.0.1."""
    from . import colibri
    try:
        if args.action == "installer":
            version, racine = colibri.installer(args.version_colibri)
            print(_t("✔ Colibri {} installé dans {}").format(version, racine))
            print(_t("Étape suivante : prépare un modèle avec « coli setup » ou « coli import » (voir la documentation de Colibri), puis : lutin colibri start --model <dossier>"))
        elif args.action == "demarrer":
            if not args.modele:
                print("✘ " + _t("Indique le dossier de modèle : lutin colibri start --model <dossier>"), file=sys.stderr)
                return 1
            colibri.demarrer(args.modele, args.port)
            print(_t("✔ Colibri répond sur http://127.0.0.1:{}/v1 : dans les réglages, choisis « Serveur compatible OpenAI » puis Colibri dans les serveurs connus.").format(args.port))
        elif args.action == "arreter":
            print(_t("✔ Colibri arrêté.") if colibri.arreter(args.port) else _t("Colibri n'a pas confirmé l'arrêt (déjà arrêté ?)."))
        else:
            trouve = colibri.installee()
            print(_t("Colibri {} installé dans {}").format(*trouve) if trouve else _t("Colibri n'est pas installé."))
            print(_t("Répond sur le port {} : {}").format(args.port, _t("oui") if colibri.repond(args.port) else _t("non")))
    except (ValueError, OSError) as e:
        print("✘ " + str(e), file=sys.stderr)
        return 1
    return 0


def commande_wake(args):
    """Envoie le paquet de réveil. Utile depuis l'hôte d'un conteneur Docker en réseau « bridge » (qui ne peut pas diffuser sur le réseau local) : docker run --rm --network host <image> lutin wake <MAC>."""
    from . import alimentation
    try:
        envoyes = alimentation.envoyer_reveil(args.mac, args.host)
    except ValueError as e:
        print("✘ " + str(e), file=sys.stderr)
        return 1
    print(_t("✔ Paquet de réveil envoyé ({} envois).").format(len(envoyes)))
    return 0


def commande_doctor(args):
    d, cfg = contexte()
    from . import docker_aide
    for niveau, texte in diagnostic(cfg, d, machine.detecter(), ollama_client.Ollama()) + docker_aide.diagnostiquer():
        print("{} {}".format({"ok": "✔", "info": " ", "attention": "⚠", "erreur": "✘"}[niveau], texte))
    return 0


def utf8():
    """Les consoles Windows ont souvent un jeu de caractères limité (cp1252/cp850) : sans ceci, un « ✔ » ferait planter la commande."""
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def principal(argv=None):
    utf8()
    args = parseur().parse_args(argv)
    os.environ["LUTIN_CONFIG"] = str(Path(config.dossiers()["config"]) / "config.json")          # les gardes (mode hors ligne…) lisent la configuration de cette installation
    commandes = {"setup": commande_setup, "serve": commande_serve, "update": commande_update, "chat": commande_chat, "modeles": commande_modeles, "pin": commande_pin,
                 "appareils": commande_appareils, "securite": commande_securite, "langue": commande_langue, "importer": commande_importer, "reprendre": commande_reprendre, "hors-ligne": commande_hors_ligne,
                 "travaux": commande_travaux, "journal": commande_journal, "bench": commande_bench, "sauvegarde": commande_sauvegarde, "restaurer": commande_restaurer, "doctor": commande_doctor, "demarrage-auto": commande_demarrage_auto, "zone": commande_zone, "mcp": commande_mcp, "essai-moteur": commande_essai_moteur, "bench-moteurs": commande_bench_moteurs, "colibri": commande_colibri, "wake": commande_wake}
    try:
        if args.commande is None:
            return commande_serve(argparse.Namespace(sans_navigateur=False))
        return commandes[ALIAS_COMMANDES.get(args.commande, args.commande)](args) or 0          # le nom anglais ou l'ancien nom français : la même commande
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(principal())
