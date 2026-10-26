"""La commande `lutin`."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, bench, catalogue, chat_terminal, client, config, horsligne, i18n, installation, machine, miseajour, ollama_client, projet_claude, reprise, sauvegarde, securite, selection, travaux
from .i18n import t as _t

AIDE_GENERALE = """Lutin : un assistant IA local qui choisit les modèles adaptés à ta machine.

  lutin               démarre (la première fois : installation guidée ; sinon il ne change rien)
  lutin setup         installation guidée (sans effet si Lutin est déjà installé ; --reconfigurer pour changer)
  lutin update        met à jour Lutin et cherche des mises à jour de modèles
  lutin chat          discuter dans le terminal
  lutin modeles       modèles conseillés pour ta machine, installés, mises à jour
  lutin pin           code PIN pour connecter un appareil (niveau « réseau »)
  lutin appareils     appareils connectés / révoquer
  lutin securite      niveau d'accès actuel
  lutin hors-ligne    mode hors ligne strict (aucune connexion vers Internet)
  lutin travaux       dossiers de travail (lister, ajouter, retirer, actif)
  lutin importer      reprendre un projet Claude (CLAUDE.md, .claude/) : travailler dedans ou en copie
  lutin reprendre     reprendre les données d'un autre assistant (conversations, mémoire, skills, réglages)
  lutin journal       ce que Lutin a modifié ou lancé, avec quel accord
  lutin bench         mesurer un modèle sur cette machine (vitesse, outils, code, français)
  lutin sauvegarde    exporter tes données dans un .zip ; lutin restaurer pour les remettre
  lutin doctor        diagnostic (à joindre à un rapport de problème)
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


def parseur():
    p = argparse.ArgumentParser(prog="lutin", description=_t(AIDE_GENERALE), formatter_class=argparse.RawDescriptionHelpFormatter, epilog=_t("« lutin <commande> --help » détaille chaque commande."))
    p.add_argument("--version", action="version", version="Lutin " + __version__)
    sp = p.add_subparsers(dest="commande")
    s = sp.add_parser("setup", help=_t("installation guidée"))
    s.add_argument("--oui", action="store_true", help=_t("ne rien demander : valeurs conseillées ou options données"))
    s.add_argument("--niveau", choices=securite.NIVEAUX)
    s.add_argument("--port", type=int)
    s.add_argument("--url", help=_t("adresse publique (niveau proxy)"))
    s.add_argument("--proxy-ip", action="append", dest="proxy_ips", help=_t("adresse du proxy de confiance (niveau proxy), répétable"))
    s.add_argument("--travail", help=_t("dossier de travail"))
    s.add_argument("--dossier-modeles", help=_t("où ranger les modèles"))
    s.add_argument("--roles", help=_t("rôles à installer, séparés par des virgules (polyvalent,rapide,creatif,code,vision)"))
    s.add_argument("--sans-modeles", action="store_true")
    s.add_argument("--sans-ollama", action="store_true")
    s.add_argument("--ecoute", help=_t("adresse d'écoute imposée (conteneur : 0.0.0.0) ; interdite au niveau « local »"))
    s.add_argument("--langue", choices=i18n.LANGUES + ("auto",), help=_t("langue de l'application (fr, en ou auto)"))
    s.add_argument("--reconfigurer", action="store_true", help=_t("refaire l'installation guidée même si Lutin est déjà installé (les modèles déjà là ne sont pas retéléchargés)"))
    sv = sp.add_parser("serve", help=_t("démarrer le serveur"))
    sv.add_argument("--sans-navigateur", action="store_true")
    sv.add_argument("--sans-superviseur", action="store_true", help=_t("ne pas relancer automatiquement le serveur s'il s'arrête sur une erreur"))
    u = sp.add_parser("update", help=_t("mettre à jour Lutin et les modèles"))
    u.add_argument("--app", action="store_true", help=_t("seulement Lutin"))
    u.add_argument("--modeles", action="store_true", help=_t("seulement la recherche de mises à jour de modèles"))
    c = sp.add_parser("chat", help=_t("discuter dans le terminal"))
    c.add_argument("message", nargs="*", help=_t("un message à envoyer tout de suite (sinon, mode interactif)"))
    m = sp.add_parser("modeles", help=_t("modèles"))
    m.add_argument("action", nargs="?", choices=("recommander", "lister", "installer", "supprimer", "maj"), default="recommander")
    m.add_argument("modele", nargs="?")
    m.add_argument("--avance", action="store_true", help=_t("inclure les modèles avancés (sans filtre)"))
    sp.add_parser("pin", help=_t("nouveau code PIN"))
    a = sp.add_parser("appareils", help=_t("appareils connectés"))
    a.add_argument("action", nargs="?", choices=("lister", "revoquer"), default="lister")
    a.add_argument("id", nargs="?")
    sp.add_parser("securite", help=_t("niveau d'accès"))
    tr = sp.add_parser("travaux", help=_t("dossiers de travail"))
    tr.add_argument("action", nargs="?", choices=("lister", "ajouter", "retirer", "actif"), default="lister")
    tr.add_argument("valeur", nargs="?", help=_t("chemin (ajouter) ou identifiant (retirer, actif)"))
    tr.add_argument("--nom", default="", help=_t("nom affiché (ajouter)"))
    jo = sp.add_parser("journal", help=_t("journal des actions"))
    jo.add_argument("-n", type=int, default=30, help=_t("nombre d'actions affichées (30)"))
    be = sp.add_parser("bench", help=_t("banc d'essai d'un modèle"))
    be.add_argument("modeles", nargs="*", help=_t("modèles à mesurer (défaut : le modèle principal)"))
    be.add_argument("--rapide", action="store_true", help=_t("vitesse seulement (environ 20 secondes)"))
    be.add_argument("--exporter", action="store_true", help=_t("affiche le résultat en JSON, à coller dans une proposition de note au catalogue"))
    sa = sp.add_parser("sauvegarde", help=_t("exporter tes données dans un .zip"))
    sa.add_argument("fichier", nargs="?", help=_t("fichier de destination (défaut : lutin-sauvegarde-<date>.zip)"))
    re_ = sp.add_parser("restaurer", help=_t("remettre une sauvegarde"))
    re_.add_argument("fichier")
    re_.add_argument("--oui", action="store_true", help=_t("ne pas demander de confirmation"))
    re_.add_argument("--forcer", action="store_true", help=_t("restaurer même si Lutin tourne (déconseillé)"))
    hl = sp.add_parser("hors-ligne", help=_t("mode hors ligne strict (aucune connexion vers Internet)"))
    hl.add_argument("etat", nargs="?", choices=("oui", "non", "etat"), default="etat")
    sp.add_parser("doctor", help=_t("diagnostic"))
    rp = sp.add_parser("reprendre", help=_t("reprendre les données d'un autre assistant (conversations, mémoire, skills, réglages)"))
    rp.add_argument("source", help=_t("le dossier de l'ancien assistant (avec donnees/ et memoire/), ou une archive .zip"))
    rp.add_argument("--conversations", action="store_true", help=_t("reprendre les conversations"))
    rp.add_argument("--memoire", action="store_true", help=_t("reprendre la mémoire (CONTEXTE.md, MEMOIRE.md)"))
    rp.add_argument("--skills", action="store_true", help=_t("reprendre les skills (dans le dossier de travail actif)"))
    rp.add_argument("--reglages", action="store_true", help=_t("reprendre les réglages (jamais le modèle ni les accords automatiques)"))
    rp.add_argument("--tout", action="store_true", help=_t("tout reprendre"))
    rp.add_argument("--dossier-skills", help=_t("où sont les skills de l'ancien assistant (défaut : skills/ à côté)"))
    rp.add_argument("--ecraser", action="store_true", help=_t("remplacer ce qui existe déjà (sinon rien n'est écrasé)"))
    rp.add_argument("--cible", help=_t("identifiant du dossier de travail où poser les skills (défaut : le dossier actif ; voir lutin travaux)"))
    im = sp.add_parser("importer", help=_t("reprendre un projet Claude (CLAUDE.md, .claude/) comme dossier de travail"))
    im.add_argument("chemin", help=_t("le dossier du projet (celui qui contient CLAUDE.md ou .claude/)"))
    groupe = im.add_mutually_exclusive_group()
    groupe.add_argument("--ici", action="store_true", help=_t("travailler dans le dossier lui-même"))
    groupe.add_argument("--copie", action="store_true", help=_t("travailler dans une copie ; l'original n'est jamais touché"))
    im.add_argument("--vers", help=_t("dossier de la copie (défaut : ~/Lutin/<nom du projet>)"))
    im.add_argument("--nom", default="", help=_t("nom affiché"))
    lg = sp.add_parser("langue", help=_t("langue de l'application (fr, en ou auto)"))
    lg.add_argument("valeur", nargs="?", help="fr | en | auto")
    sp.add_parser("zone", help=_t("Lutin dans la zone de notification de Windows, sans fenêtre de console (code PIN, redémarrer, quitter)"))
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
    """Exécute `lutin serve --sans-superviseur` dans un processus séparé et renvoie son code ; s'il faut s'arrêter, le processus enfant s'arrête avec nous."""
    commande = [sys.executable, "-m", "lutin", "serve", "--sans-superviseur"] + (["--sans-navigateur"] if sans_navigateur else [])
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


def mettre_a_jour_lutin():
    """Met Lutin à jour d'après la source mémorisée à l'installation : « github:propriétaire/dépôt » (dernière publication, comparée à la version installée) ou une adresse / une roue
    donnée à pip. Ne fait rien si Lutin est déjà à jour. Renvoie un code de sortie."""
    source = config.lire_source()
    if not source:
        print(_t("Lutin ne sait pas d'où se mettre à jour (installé à la main ?). Relance le script d'installation, ou : python -m pip install --upgrade <source>"))
        return 0
    if source.startswith("github:"):
        version, roue = miseajour.derniere_release(source[len("github:"):])
        if not roue:
            print(_t("✘ Impossible de lire la dernière version de Lutin sur GitHub (pas d'internet, ou aucune publication)."), file=sys.stderr)
            return 1
        if not miseajour.plus_recente(version, __version__):
            print(_t("Lutin est déjà à jour ({}).").format(__version__))
            return 0
        source = roue
    avant = __version__
    if subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", source]).returncode != 0:
        print(_t("✘ La mise à jour de Lutin a échoué (pip)."), file=sys.stderr)
        return 1
    apres = subprocess.run([sys.executable, "-m", "lutin", "--version"], capture_output=True, text=True).stdout.strip().replace("Lutin ", "")
    print(_t("Lutin est déjà à jour ({}).").format(avant) if apres in ("", avant) else _t("✔ Lutin mis à jour : {} → {}.").format(avant, apres))
    return 0


def commande_update(args):
    """Met à jour Lutin lui-même (avec la source mémorisée par l'installateur) puis cherche des mises à jour de modèles. Ne change rien si tout est à jour."""
    tout = not (args.app or args.modeles)
    code = 0
    if (args.app or tout) and horsligne.actif(Path(config.dossiers()["config"]) / "config.json"):
        print(_t("Mode hors ligne strict : Lutin n'est pas mis à jour (lutin hors-ligne non pour le permettre)."))
    elif args.app or tout:
        code = mettre_a_jour_lutin()
    if args.modeles or tout:
        d, cfg = contexte()
        r = miseajour.verifier(machine.detecter(), cfg, d, ollama_client.Ollama(), force=True)
        for p in r["propositions"]:
            print("• {} : {}".format(p["modele"], p["raison"]))
        print(_t("Modèles : rien de nouveau.") if not r["propositions"] else _t("Pour en installer un :  lutin modeles installer <identifiant>"))
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
        choix = selection.choisir(profil, cat)
        print(_t("Ta machine : ") + profil.resume() + "\n")
        for role in catalogue.ROLES:
            c = choix.get(role)
            titre = _t(catalogue.LIBELLES[role][0])
            print("{:<11} {}".format(titre, "—" if not c else "{} ({:g} Go)".format(c.id, c.modele["go"])))
            if c:
                print("            " + c.modele["phrase"])
        print(_t("\nInstaller :  lutin modeles installer <identifiant>"))
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
        print(_t("Indique un modèle : lutin modeles {} <identifiant>").format(args.action), file=sys.stderr)
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
            print(_t("Rien de nouveau.") if not r["propositions"] else _t("\nInstaller :  lutin modeles installer <identifiant>"))
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
        print(_t("Aucun dossier de travail : lutin travaux ajouter <chemin>"))
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
            print(_t("  Notes mesurées (indicatives, onze questions) : ") + ", ".join("{} {}/10".format(_t(catalogue.LIBELLES[r][0]).lower(), n) for r, n in mesure["notes"].items()))
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
        print(_t("✘ Lutin tourne : arrête-le avant de restaurer (ou --forcer)."), file=sys.stderr)
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
    s = securite.Securite.depuis_dict(cfg["securite"])
    texte = {securite.LOCAL: _t("cette machine seulement"), securite.RESEAU: _t("réseau local (code PIN)"), securite.PROXY: _t("derrière un proxy")}[s.niveau]
    print(_t("Niveau : {} — {}").format(s.niveau, texte))
    if s.niveau == securite.PROXY:
        print(_t("Adresse publique : {}   Proxy de confiance : {}").format(s.url_publique, ", ".join(s.proxy_ips)))
    for p in s.valider():
        print("⚠ " + p)
    print(_t("Pour changer : lutin setup --niveau local|reseau|proxy"))
    return 0


def commande_reprendre(args, entree=input):
    """Reprend les données d'un autre assistant, au choix. Rien n'est écrasé sans --ecraser ; l'état actuel de Lutin est gardé dans un zip avant."""
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
        print("✘ " + _t("Ni CLAUDE.md ni dossier .claude/ dans ce dossier : ce n'est pas un projet Claude (pour l'utiliser quand même : lutin travaux ajouter <dossier>)."), file=sys.stderr)
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
        print(_t("Attention : Lutin travaille dans ton dépôt lui-même. Il peut y lire et y modifier des fichiers (chaque modification demande ton accord, avec les différences, et peut être annulée). Pour revenir à ton ancien dossier de travail : lutin travaux actif <identifiant> (liste : lutin travaux)."))
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
        print(_t("Pour changer : lutin langue fr|en|auto (auto : suivre la langue du système)"))
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


def commande_doctor(args):
    d, cfg = contexte()
    for niveau, texte in diagnostic(cfg, d, machine.detecter(), ollama_client.Ollama()):
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
                 "travaux": commande_travaux, "journal": commande_journal, "bench": commande_bench, "sauvegarde": commande_sauvegarde, "restaurer": commande_restaurer, "doctor": commande_doctor, "zone": commande_zone}
    try:
        if args.commande is None:
            return commande_serve(argparse.Namespace(sans_navigateur=False))
        return commandes[args.commande](args) or 0
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(principal())
