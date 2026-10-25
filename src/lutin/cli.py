"""La commande `lutin`."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, bench, catalogue, chat_terminal, client, config, horsligne, installation, machine, miseajour, ollama_client, sauvegarde, securite, selection, travaux

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
  lutin journal       ce que Lutin a modifié ou lancé, avec quel accord
  lutin bench         mesurer un modèle sur cette machine (vitesse, outils, code, français)
  lutin sauvegarde    exporter tes données dans un .zip ; lutin restaurer pour les remettre
  lutin doctor        diagnostic (à joindre à un rapport de problème)
"""

# Codes de sortie d'un arrêt voulu (Ctrl+C, arrêt demandé) : pas de relance automatique.
SORTIES_VOULUES = {0, 130, -2, -15, 3221225786, -1073741510}


def superviser(lancer, attendre=time.sleep, horloge=time.time, maximum=5, fenetre=600, delai=3, ecrire=print):
    """Relance le serveur s'il s'arrête sur une erreur (au plus `maximum` fois par `fenetre` secondes), jamais s'il a été arrêté volontairement.
    `lancer(premiere_fois)` exécute le serveur et renvoie son code de sortie."""
    pannes, premiere = [], True
    while True:
        code = lancer(premiere)
        premiere = False
        if code in SORTIES_VOULUES:
            return 0
        maintenant = horloge()
        pannes = [t for t in pannes if maintenant - t < fenetre] + [maintenant]
        if len(pannes) > maximum:
            ecrire("Lutin s'est arrêté {} fois en {} minutes (dernier code : {}) : je n'insiste pas. Voir le journal : lutin doctor.".format(len(pannes), fenetre // 60, code))
            return 1
        ecrire("Lutin s'est arrêté sur une erreur (code {}). Relance dans {} s ({}/{}).".format(code, delai, len(pannes), maximum))
        attendre(delai)


def parseur():
    p = argparse.ArgumentParser(prog="lutin", description=AIDE_GENERALE, formatter_class=argparse.RawDescriptionHelpFormatter, epilog="« lutin <commande> --help » détaille chaque commande.")
    p.add_argument("--version", action="version", version="Lutin " + __version__)
    sp = p.add_subparsers(dest="commande")
    s = sp.add_parser("setup", help="installation guidée")
    s.add_argument("--oui", action="store_true", help="ne rien demander : valeurs conseillées ou options données")
    s.add_argument("--niveau", choices=securite.NIVEAUX)
    s.add_argument("--port", type=int)
    s.add_argument("--url", help="adresse publique (niveau proxy)")
    s.add_argument("--proxy-ip", action="append", dest="proxy_ips", help="adresse du proxy de confiance (niveau proxy), répétable")
    s.add_argument("--travail", help="dossier de travail")
    s.add_argument("--dossier-modeles", help="où ranger les modèles")
    s.add_argument("--roles", help="rôles à installer, séparés par des virgules (polyvalent,rapide,creatif,code,vision)")
    s.add_argument("--sans-modeles", action="store_true")
    s.add_argument("--sans-ollama", action="store_true")
    s.add_argument("--ecoute", help="adresse d'écoute imposée (conteneur : 0.0.0.0) ; interdite au niveau « local »")
    s.add_argument("--reconfigurer", action="store_true", help="refaire l'installation guidée même si Lutin est déjà installé (les modèles déjà là ne sont pas retéléchargés)")
    sv = sp.add_parser("serve", help="démarrer le serveur")
    sv.add_argument("--sans-navigateur", action="store_true")
    sv.add_argument("--sans-superviseur", action="store_true", help="ne pas relancer automatiquement le serveur s'il s'arrête sur une erreur")
    u = sp.add_parser("update", help="mettre à jour Lutin et les modèles")
    u.add_argument("--app", action="store_true", help="seulement Lutin")
    u.add_argument("--modeles", action="store_true", help="seulement la recherche de mises à jour de modèles")
    c = sp.add_parser("chat", help="discuter dans le terminal")
    c.add_argument("message", nargs="*", help="un message à envoyer tout de suite (sinon, mode interactif)")
    m = sp.add_parser("modeles", help="modèles")
    m.add_argument("action", nargs="?", choices=("recommander", "lister", "installer", "supprimer", "maj"), default="recommander")
    m.add_argument("modele", nargs="?")
    m.add_argument("--avance", action="store_true", help="inclure les modèles avancés (sans filtre)")
    sp.add_parser("pin", help="nouveau code PIN")
    a = sp.add_parser("appareils", help="appareils connectés")
    a.add_argument("action", nargs="?", choices=("lister", "revoquer"), default="lister")
    a.add_argument("id", nargs="?")
    sp.add_parser("securite", help="niveau d'accès")
    tr = sp.add_parser("travaux", help="dossiers de travail")
    tr.add_argument("action", nargs="?", choices=("lister", "ajouter", "retirer", "actif"), default="lister")
    tr.add_argument("valeur", nargs="?", help="chemin (ajouter) ou identifiant (retirer, actif)")
    tr.add_argument("--nom", default="", help="nom affiché (ajouter)")
    jo = sp.add_parser("journal", help="journal des actions")
    jo.add_argument("-n", type=int, default=30, help="nombre d'actions affichées (30)")
    be = sp.add_parser("bench", help="banc d'essai d'un modèle")
    be.add_argument("modeles", nargs="*", help="modèles à mesurer (défaut : le modèle principal)")
    be.add_argument("--rapide", action="store_true", help="vitesse seulement (environ 20 secondes)")
    be.add_argument("--exporter", action="store_true", help="affiche le résultat en JSON, à coller dans une proposition de note au catalogue")
    sa = sp.add_parser("sauvegarde", help="exporter tes données dans un .zip")
    sa.add_argument("fichier", nargs="?", help="fichier de destination (défaut : lutin-sauvegarde-<date>.zip)")
    re_ = sp.add_parser("restaurer", help="remettre une sauvegarde")
    re_.add_argument("fichier")
    re_.add_argument("--oui", action="store_true", help="ne pas demander de confirmation")
    re_.add_argument("--forcer", action="store_true", help="restaurer même si Lutin tourne (déconseillé)")
    hl = sp.add_parser("hors-ligne", help="mode hors ligne strict (aucune connexion vers Internet)")
    hl.add_argument("etat", nargs="?", choices=("oui", "non", "etat"), default="etat")
    sp.add_parser("doctor", help="diagnostic")
    return p


def contexte():
    d = config.dossiers()
    return d, config.charger(d)


def commande_setup(args, es=None):
    d, cfg = contexte()
    options = {"niveau": args.niveau, "port": args.port, "url": args.url, "proxy_ips": args.proxy_ips, "travail": args.travail, "dossier_modeles": args.dossier_modeles,
               "roles": [r.strip() for r in args.roles.split(",") if r.strip()] if args.roles else None, "sans_modeles": args.sans_modeles, "sans_ollama": args.sans_ollama,
               "reconfigurer": getattr(args, "reconfigurer", False), "ecoute": getattr(args, "ecoute", None)}
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
    enfant = subprocess.Popen(commande)
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


def commande_serve(args):
    from . import demarrage
    d, cfg = contexte()
    if not cfg["installe"]:
        print("Première utilisation : installation guidée.\n")
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
        print("Lutin ne sait pas d'où se mettre à jour (installé à la main ?). Relance le script d'installation, ou : python -m pip install --upgrade <source>")
        return 0
    if source.startswith("github:"):
        version, roue = miseajour.derniere_release(source[len("github:"):])
        if not roue:
            print("✘ Impossible de lire la dernière version de Lutin sur GitHub (pas d'internet, ou aucune publication).", file=sys.stderr)
            return 1
        if not miseajour.plus_recente(version, __version__):
            print("Lutin est déjà à jour ({}).".format(__version__))
            return 0
        source = roue
    avant = __version__
    if subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", source]).returncode != 0:
        print("✘ La mise à jour de Lutin a échoué (pip).", file=sys.stderr)
        return 1
    apres = subprocess.run([sys.executable, "-m", "lutin", "--version"], capture_output=True, text=True).stdout.strip().replace("Lutin ", "")
    print("Lutin est déjà à jour ({}).".format(avant) if apres in ("", avant) else "✔ Lutin mis à jour : {} → {}.".format(avant, apres))
    return 0


def commande_update(args):
    """Met à jour Lutin lui-même (avec la source mémorisée par l'installateur) puis cherche des mises à jour de modèles. Ne change rien si tout est à jour."""
    tout = not (args.app or args.modeles)
    code = 0
    if (args.app or tout) and horsligne.actif(Path(config.dossiers()["config"]) / "config.json"):
        print("Mode hors ligne strict : Lutin n'est pas mis à jour (lutin hors-ligne non pour le permettre).")
    elif args.app or tout:
        code = mettre_a_jour_lutin()
    if args.modeles or tout:
        d, cfg = contexte()
        r = miseajour.verifier(machine.detecter(), cfg, d, ollama_client.Ollama(), force=True)
        for p in r["propositions"]:
            print("• {} : {}".format(p["modele"], p["raison"]))
        print("Modèles : rien de nouveau." if not r["propositions"] else "Pour en installer un :  lutin modeles installer <identifiant>")
        for e in r["erreurs"]:
            print("  (" + e + ")")
    return code


def client_pret():
    d, _ = contexte()
    c = client.ClientLocal(d["donnees"])
    if not c.disponible():
        print("Lutin ne tourne pas. Lance « lutin serve » (ou « lutin ») dans une autre fenêtre, puis recommence.", file=sys.stderr)
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
        print("Ta machine : " + profil.resume() + "\n")
        for role in catalogue.ROLES:
            c = choix.get(role)
            titre, _ = catalogue.LIBELLES[role]
            print("{:<11} {}".format(titre, "—" if not c else "{} ({:g} Go)".format(c.id, c.modele["go"])))
            if c:
                print("            " + c.modele["phrase"])
        print("\nInstaller :  lutin modeles installer <identifiant>")
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
            etat = "installé" if m["id"] in installes else ("tient" if x["tient"] else "trop gros")
            print("{:<38} {:>5g} Go  {:<10} {}".format(m["id"], m["go"], etat, m["phrase"]))
            if m["id"] in mesures:
                print("{:<38} {}".format("", "mesuré ici : " + bench.resume(mesures[m["id"]])))
        return 0
    if args.action in ("installer", "supprimer") and not args.modele:
        print("Indique un modèle : lutin modeles {} <identifiant>".format(args.action), file=sys.stderr)
        return 2
    try:
        if args.action == "installer":
            m = catalogue.par_id(cat).get(args.modele)
            if m and m.get("avertissement"):
                print("⚠ " + m["avertissement"])
            o.telecharger(args.modele, installation.barre(installation.Es()))
            print("✔ installé : " + args.modele)
        elif args.action == "supprimer":
            o.supprimer(args.modele)
            print("✔ supprimé : " + args.modele)
        elif args.action == "maj":
            r = miseajour.verifier(profil, cfg, d, o, force=True)
            for p in r["propositions"]:
                print("• {} : {}".format(p["modele"], p["raison"]))
            print("Rien de nouveau." if not r["propositions"] else "\nInstaller :  lutin modeles installer <identifiant>")
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
    print("Code PIN : {}   (valable {} minutes, un seul appareil)".format(r["pin"], r["valable_s"] // 60))
    return 0


def commande_appareils(args):
    c = client_pret()
    if not c:
        return 1
    try:
        if args.action == "revoquer":
            r = c.envoyer("/api/appareils-revoquer", {"id": args.id})
            print("{} appareil(s) déconnecté(s).".format(r["revoques"]))
            return 0
        r = c.envoyer("/api/appareils", {})
    except client.ErreurClient as e:
        print("✘ " + str(e), file=sys.stderr)
        return 1
    if not r["appareils"]:
        print("Aucun appareil connecté (niveau : {}).".format(r["niveau"]))
    for a in r["appareils"]:
        print("{}  {}".format(a["id"], a["nom"]))
    return 0


def commande_hors_ligne(args):
    d, _ = contexte()
    chemin = Path(d["config"]) / "config.json"
    if args.etat != "etat":
        horsligne.definir(args.etat == "oui", chemin)
    actif = horsligne.actif(chemin)
    print("Mode hors ligne strict : {}.".format("ACTIF (aucune connexion vers Internet)" if actif else "coupé"))
    if args.etat != "etat":
        print("Si Lutin tourne, il en tient compte tout de suite.")
    return 0


def commande_travaux(args):
    d, cfg = contexte()
    interdits = [d["config"], d["donnees"], d["memoire"], d["cache"]]
    try:
        if args.action == "ajouter":
            t = travaux.ajouter(cfg, args.valeur, args.nom, interdits)
            config.enregistrer(d, cfg)
            print("✔ Dossier de travail « {} » : {}".format(t["nom"], t["chemin"]))
        elif args.action == "retirer":
            travaux.retirer(cfg, args.valeur or "")
            config.enregistrer(d, cfg)
            print("✔ Retiré de la liste (les fichiers ne sont pas touchés).")
        elif args.action == "actif":
            t = travaux.choisir(cfg, args.valeur or "")
            config.enregistrer(d, cfg)
            print("✔ Dossier actif : {} ({})".format(t["nom"], t["chemin"]))
            print("Si Lutin tourne déjà, choisis aussi ce dossier dans l'interface (ou relance Lutin).")
    except travaux.ErreurTravail as e:
        print("✘ " + str(e), file=sys.stderr)
        return 1
    actif = travaux.actif(cfg)
    for t in travaux.liste(cfg):
        print("{} {:<14} {:<22} {}".format("→" if actif and t["id"] == actif["id"] else " ", t["id"], t["nom"], t["chemin"]))
    if not travaux.liste(cfg):
        print("Aucun dossier de travail : lutin travaux ajouter <chemin>")
    return 0


def commande_journal(args):
    d, _ = contexte()
    f = Path(d["donnees"]) / "journal-actions.jsonl"
    try:
        lignes = f.read_text(encoding="utf-8").splitlines()[-max(1, args.n):]
    except OSError:
        print("Aucune action enregistrée pour le moment.")
        return 0
    import json
    for ligne in lignes:
        try:
            e = json.loads(ligne)
        except ValueError:
            continue
        print("{} {:<18} {:<8} accord {:<6} par {:<10} {}".format(e["ts"].replace("T", " "), e["outil"], e["issue"][:8], e["accord"], e.get("qui") or "?", e["cible"]))
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
        print("Aucun modèle installé à mesurer.", file=sys.stderr)
        return 1
    resume = machine.detecter().resume()
    code = 0
    for m in cibles:
        if m not in installes:
            print("✘ {} n'est pas installé.".format(m), file=sys.stderr)
            code = 1
            continue
        print("Mesure de {} ({})…".format(m, "vitesse seulement" if args.rapide else "banc complet, quelques minutes"))
        mesure = bench.executer(o, m, rapide=args.rapide, resume_machine=resume, progression=lambda nom, i, n: print("  {} ({}/{})".format(nom, i + 1, n)))
        bench.enregistrer(Path(d["cache"]) / "bench.json", mesure)
        print("  → " + bench.resume(mesure))
        if mesure["notes"]:
            print("  Notes mesurées (indicatives, onze questions) : " + ", ".join("{} {}/10".format(catalogue.LIBELLES[r][0].lower(), n) for r, n in mesure["notes"].items()))
        if mesure.get("erreur"):
            print("  ⚠ Mesure incomplète : " + mesure["erreur"])
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
    print("✔ {} : {} fichier(s), {:.1f} Mo avant compression.".format(destination, r["fichiers"], r["octets"] / 1024 ** 2))
    print("Contient tes conversations, réglages, journal et mémoire. Ne contient ni appareils connectés, ni jeton, ni fichiers de ton dossier de travail.")
    return 0


def commande_restaurer(args):
    d, _ = contexte()
    try:
        m = sauvegarde.verifier(args.fichier)
    except sauvegarde.ErreurSauvegarde as e:
        print("✘ " + str(e), file=sys.stderr)
        return 1
    if not args.forcer and client.ClientLocal(d["donnees"]).disponible():
        print("✘ Lutin tourne : arrête-le avant de restaurer (ou --forcer).", file=sys.stderr)
        return 1
    print("Sauvegarde du {} (Lutin {}) : {} fichier(s).".format(m.get("date", "?"), m.get("lutin", "?"), len(m.get("fichiers", []))))
    if not args.oui and input("Remplacer tes données actuelles par celles-ci ? L'état actuel est gardé dans un zip « avant-restauration ». [o/N] ").strip().lower() not in ("o", "oui", "y", "yes"):
        print("Rien n'a été changé.")
        return 0
    r = sauvegarde.restaurer(d, args.fichier, d["cache"])
    print("✔ {} fichier(s) restauré(s). État précédent : {}".format(r["fichiers"], r["secours"]))
    return 0


def commande_securite(args):
    d, cfg = contexte()
    s = securite.Securite.depuis_dict(cfg["securite"])
    texte = {securite.LOCAL: "cette machine seulement", securite.RESEAU: "réseau local (code PIN)", securite.PROXY: "derrière un proxy"}[s.niveau]
    print("Niveau : {} — {}".format(s.niveau, texte))
    if s.niveau == securite.PROXY:
        print("Adresse publique : {}   Proxy de confiance : {}".format(s.url_publique, ", ".join(s.proxy_ips)))
    for p in s.valider():
        print("⚠ " + p)
    print("Pour changer : lutin setup --niveau local|reseau|proxy")
    return 0


def diagnostic(cfg, dossiers, profil, ollama):
    """[(niveau, texte)] — sans conversation ni contenu personnel : peut être collé dans un rapport de problème."""
    lignes = [("info", "Lutin " + __version__), ("info", "Machine : " + profil.resume()), ("info", "Système : {} {}".format(profil.systeme, profil.architecture))]
    if profil.sans_gpu():
        lignes.append(("attention", "Pas de carte graphique utilisable : les modèles tourneront sur le processeur."))
    for g in profil.gpus:
        lignes.append(("info", "Carte : {} ({:g} Go, source : {})".format(g.nom, g.vram_go, g.source)))
    try:
        lignes.append(("ok", "Ollama {} répond".format(ollama.version())))
        installes = ollama.installes()
        lignes.append(("ok" if installes else "attention", "{} modèle(s) installé(s)".format(len(installes))))
    except ollama_client.ErreurOllama:
        lignes.append(("erreur", "Ollama ne répond pas (installé : {})".format("oui" if ollama_client.trouver_executable(profil.systeme) else "non")))
    s = securite.Securite.depuis_dict(cfg["securite"])
    lignes.append(("info", "Niveau de sécurité : " + s.niveau))
    lignes += [("erreur", p) for p in s.valider()]
    for disque in profil.disques:
        lignes.append(("attention" if disque.libre_go < 20 else "info", "Disque {} : {:g} Go libres".format(disque.racine, disque.libre_go)))
    lignes.append(("ok" if cfg["installe"] else "attention", "Installation guidée : " + ("faite" if cfg["installe"] else "à faire (lutin setup)")))
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
                 "appareils": commande_appareils, "securite": commande_securite, "hors-ligne": commande_hors_ligne,
                 "travaux": commande_travaux, "journal": commande_journal, "bench": commande_bench, "sauvegarde": commande_sauvegarde, "restaurer": commande_restaurer, "doctor": commande_doctor}
    try:
        if args.commande is None:
            return commande_serve(argparse.Namespace(sans_navigateur=False))
        return commandes[args.commande](args) or 0
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(principal())
