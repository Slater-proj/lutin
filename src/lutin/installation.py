"""L'assistant de première configuration (`lutin setup`) : machine, sécurité, emplacements, modèles, Ollama, téléchargements.

Le même parcours sert en interactif et en mode automatique (`--oui` : toutes les questions prennent leur valeur conseillée ou celle des options),
ce qui permet de le tester sans clavier. Rien n'est installé ni téléchargé sans que l'utilisateur ait vu la taille et confirmé (sauf avec `--oui`).
"""
import os
import shutil
import subprocess
from pathlib import Path

from . import bench, catalogue, config, horsligne, i18n, machine, ollama_client, securite, selection
from .i18n import t as _t

GO = 1024 ** 3
_lancer = subprocess.run          # un seul point d'entrée pour les commandes système : les tests le remplacent (patcher subprocess.run lui-même gênerait les autres threads)


class Es:
    """Entrées / sorties de l'assistant. `oui` : ne rien demander, prendre les valeurs conseillées."""

    def __init__(self, entree=input, sortie=print, oui=False):
        self.entree, self.sortie, self.oui = entree, sortie, oui

    def dire(self, texte=""):
        self.sortie(texte)

    def demander(self, question, defaut=""):
        if self.oui:
            return defaut
        try:
            reponse = self.entree("{}{} ".format(question, " [{}]".format(defaut) if defaut else "")).strip()
        except EOFError:
            return defaut
        return reponse or defaut

    def confirmer(self, question, defaut=True):
        if self.oui:
            return defaut
        r = self.demander(question + (" [O/n]" if defaut else " [o/N]"), "").lower()
        return defaut if not r else r in ("o", "oui", "y", "yes")


NIVEAUX_TEXTE = {
    securite.LOCAL: ("1", "Cette machine seulement", "Personne d'autre ne peut y accéder. Recommandé."),
    securite.RESEAU: ("2", "Mon réseau local", "Téléphone, tablette, autre PC de la maison, avec un code PIN à chaque nouvel appareil."),
    securite.PROXY: ("3", "Depuis Internet, derrière un proxy", "Lutin n'est pas exposé directement : un proxy (Authelia, Authentik…) s'occupe de l'identité."),
}
AVERTISSEMENT_RESEAU = ("Attention : toute personne qui connaît le code PIN et se trouve sur ton réseau pourra demander à Lutin de lire les fichiers du dossier de travail. "
                        "Les accords automatiques se règlent conversation par conversation (désactivés par défaut) : ne les active pas pour une conversation ouverte depuis un appareil que tu ne maîtrises pas.")
AVERTISSEMENT_PROXY = ("Attention : exposer un assistant capable de lire des fichiers et de lancer des commandes à Internet est risqué. Ne le fais que derrière une "
                       "authentification forte (idéalement avec second facteur) et un HTTPS valide. Les accords automatiques se règlent conversation par conversation (désactivés par défaut) : active-les avec prudence.")


def choisir_langue(es, options, cfg):
    """Première question de l'installation : la langue (français ou anglais). Posée seulement si rien ne l'a déjà fixée (option, variable LUTIN_LANGUE, réglage existant) et jamais avec --oui."""
    voulue = options.get("langue")
    if not voulue:
        if es.oui or cfg.get("langue") in i18n.LANGUES or os.environ.get("LUTIN_LANGUE", "").strip().lower() in i18n.LANGUES:
            return
        es.dire("\nLangue / Language :\n  1. Français\n  2. English")
        r = es.demander("1 / 2", "2" if i18n.langue_systeme() == "en" else "1").lower()
        voulue = "en" if r in ("2", "en", "english", "anglais") else "fr"
    cfg["langue"] = None if voulue == "auto" else voulue
    i18n.forcer(cfg["langue"])


def choisir_securite(es, options):
    if options.get("niveau"):
        niveau = options["niveau"]
    else:
        es.dire(_t("\nQui doit pouvoir utiliser Lutin ?"))
        for n, (num, titre, detail) in NIVEAUX_TEXTE.items():
            es.dire("  {}. {} : {}".format(num, _t(titre), _t(detail)))
        r = es.demander(_t("Ton choix"), "1")
        niveau = next((n for n, (num, _, _) in NIVEAUX_TEXTE.items() if num == r or n == r), securite.LOCAL)
    sec = securite.Securite(niveau=niveau, port=int(options.get("port") or 8777), ecoute=str(options.get("ecoute") or ""))
    if niveau == securite.RESEAU:
        es.dire("\n" + _t(AVERTISSEMENT_RESEAU))
    if niveau == securite.PROXY:
        es.dire("\n" + _t(AVERTISSEMENT_PROXY))
        sec.url_publique = options.get("url") or es.demander(_t("Adresse publique (https://…)"), "")
        ips = options.get("proxy_ips") or [x for x in es.demander(_t("Adresse du proxy de confiance (celle qu'il a vue de Lutin, ex. 192.168.1.10)"), "").replace(",", " ").split() if x]
        sec.proxy_ips = list(ips)
        if not es.oui and not es.confirmer(_t("J'ai compris les risques et je veux continuer"), False):
            es.dire(_t("Retour au niveau « cette machine seulement »."))
            return securite.Securite(port=sec.port)
    problemes = sec.valider()
    if problemes:
        raise ValueError(_t("Sécurité : ") + " ; ".join(problemes))
    return sec


def choisir_emplacements(es, options, profil, besoin_go):
    em = {"modeles": "", "travail": ""}
    maison = Path.home()
    travail = options.get("travail") or es.demander(_t("\nDossier de travail (le seul endroit où Lutin pourra lire et modifier des fichiers)"), str(maison / "Lutin"))
    em["travail"] = str(Path(travail).expanduser())
    if options.get("dossier_modeles") is not None:
        em["modeles"] = options["dossier_modeles"]
    elif len(profil.disques) > 1 and not es.oui:
        es.dire(_t("\nOù ranger les modèles ? (compte {:g} Go pour ceux proposés)").format(besoin_go))
        for i, d in enumerate(profil.disques, 1):
            es.dire(_t("  {}. {}  ({:g} Go libres sur {:g})").format(i, d.racine, d.libre_go, d.total_go))
        r = es.demander(_t("Numéro du disque, ou Entrée pour l'emplacement habituel d'Ollama"), "")
        if r.isdigit() and 1 <= int(r) <= len(profil.disques):
            em["modeles"] = str(Path(profil.disques[int(r) - 1].racine) / "Lutin" / "modeles")
    return em


def afficher_choix(es, choix, coches, profil):
    es.dire(_t("\nModèles adaptés à ta machine ({}) :").format(profil.resume()))
    es.dire(_t("(un modèle peut servir à plusieurs rôles ; la taille est celle du téléchargement)\n"))
    ordre = [r for r in catalogue.ROLES if choix.get(r)]
    for i, role in enumerate(ordre, 1):
        c = choix[role]
        titre, detail = (_t(x) for x in catalogue.LIBELLES[role])
        place = {"gpu": "", "partiel": _t("  · plus lent : déborde en mémoire vive"), "cpu": "  · sans carte graphique : lent"}[c.tient]
        es.dire("  {}. {}{}".format(i, titre, _t("   ← conseillé") if role in coches else ""))
        es.dire("     {}  ({:g} Go){}".format(c.modele["nom"], c.modele["go"], place))
        es.dire("     {}".format(c.modele["phrase"]))
    return ordre


def choisir_roles(es, options, choix, profil):
    coches = selection.par_defaut(choix)
    if options.get("sans_modeles"):
        return []
    if options.get("roles") is not None:
        return [r for r in options["roles"] if r in choix and choix[r]]
    ordre = afficher_choix(es, choix, coches, profil)
    if es.oui:
        return coches
    defaut = " ".join(str(ordre.index(r) + 1) for r in coches)
    r = es.demander(_t("\nLesquels installer ? (numéros séparés par des espaces, 0 = aucun)"), defaut)
    if r.strip() == "0":
        return []
    return [ordre[int(x) - 1] for x in r.replace(",", " ").split() if x.isdigit() and 1 <= int(x) <= len(ordre)]


def barre(es):
    """Progression d'un téléchargement : une ligne tous les 10 % (lisible dans un terminal comme dans un journal)."""
    vu = {"palier": -1, "texte": ""}

    def progression(texte, fait, total):
        pct = int(100 * fait / total) if total else -1
        palier = pct // 10 if pct >= 0 else -1
        if palier != vu["palier"] or texte != vu["texte"]:
            vu["palier"], vu["texte"] = palier, texte
            es.dire("   {}{}".format(texte[:40], "  {} %".format(pct) if pct >= 0 else ""))
    return progression


def installer_ollama_si_besoin(es, profil, cfg, options, cache):
    if options.get("sans_ollama"):
        return True
    o = ollama_client.Ollama()
    systeme = profil.systeme
    if o.actif() or ollama_client.trouver_executable(systeme):
        return True
    es.dire(_t("\nOllama (le moteur qui fait tourner les modèles) n'est pas installé."))
    if not es.confirmer("L'installer maintenant ?", True):
        es.dire(_t("D'accord : installe-le depuis https://ollama.com/download puis relance « lutin setup »."))
        return False
    try:
        if systeme == "windows":
            ollama_client.installer_windows(cache, lambda t, f, tot: None)
        elif systeme == "linux":
            es.dire(_t("Commande exécutée (le script officiel d'Ollama, il peut demander ton mot de passe) :\n   ") + ollama_client.COMMANDE_LINUX)
            try:
                reussi = _lancer(["sh", "-c", ollama_client.COMMANDE_LINUX]).returncode == 0
            except OSError as e:
                raise ollama_client.ErreurOllama(_t("impossible de lancer le script d'installation : {}").format(e)) from e
            if not reussi:
                raise ollama_client.ErreurOllama(_t("le script d'installation a échoué"))
        else:
            es.dire(_t("Télécharge Ollama sur https://ollama.com/download, installe-le, puis relance « lutin setup »."))
            return False
    except ollama_client.ErreurOllama as e:
        es.dire("✘ " + str(e))
        es.dire(_t("Tu peux l'installer à la main : https://ollama.com/download"))
        return False
    es.dire(_t("✔ Ollama installé."))
    return True


def definir_variables_utilisateur(variables, systeme, lanceur=machine.lancer):
    """Rend OLLAMA_MODELS permanent (Windows : variable utilisateur), pour qu'Ollama retrouve ses modèles à chaque démarrage."""
    if systeme == "windows":
        for k, v in variables.items():
            lanceur(["powershell", "-NoProfile", "-Command", "[Environment]::SetEnvironmentVariable('{}', '{}', 'User')".format(k, str(v).replace("'", "''"))], 20)


CLES_RECONFIGURATION = ("niveau", "port", "url", "proxy_ips", "travail", "dossier_modeles", "roles")


def deja_installe(cfg, dossiers, es, ollama=None):
    """Lutin est déjà en place : on regarde, on ne change rien. Seule exception, sur ta demande : retélécharger un modèle qui a disparu."""
    es.dire(_t("Lutin est déjà installé : rien à faire."))
    s = cfg["securite"]
    es.dire(_t("  Accès : {}   Dossier de travail : {}").format(s["niveau"], cfg["emplacements"]["travail"] or _t("(par défaut)")))
    o = ollama or ollama_client.Ollama()
    try:
        installes = set(o.installes())
    except ollama_client.ErreurOllama:
        es.dire(_t("  Ollama ne répond pas pour le moment (« lutin » le démarre au lancement)."))
        installes = None
    manquants = []
    for role, ident in cfg["modeles"]["choisis"].items():
        ok = installes is None or ident in installes
        es.dire("  {} {} : {}{}".format("✔" if ok else "✘", _t(catalogue.LIBELLES.get(role, (role,))[0]), ident, "" if ok else _t("  (n'est plus installé)")))
        if not ok:
            manquants.append(ident)
    if manquants and es.confirmer(_t("Retélécharger les modèles manquants ?"), False):
        for ident in manquants:
            try:
                o.telecharger(ident, barre(es))
                es.dire(_t("✔ {} installé.").format(ident))
            except (ollama_client.ErreurOllama, horsligne.HorsLigne) as e:
                es.dire("✘ " + str(e))
    es.dire(_t("Mises à jour : lutin update      Tout reconfigurer : lutin setup --reconfigurer"))
    return cfg


def executer(cfg, dossiers, es, options=None, profil=None, ollama=None):
    """Le parcours complet. Renvoie la configuration finale (déjà enregistrée).
    Si Lutin est déjà installé, il ne fait rien (sauf `reconfigurer`, ou une option qui demande un changement) ; ce qui est déjà téléchargé n'est jamais retéléchargé."""
    options = options or {}
    if cfg.get("installe") and not (options.get("reconfigurer") or any(options.get(k) not in (None, False) for k in CLES_RECONFIGURATION)):
        return deja_installe(cfg, dossiers, es, ollama)
    choisir_langue(es, options, cfg)
    profil = profil or machine.detecter()
    es.dire(_t("Lutin {} : installation guidée.").format(__import__("lutin").__version__))
    es.dire(_t("\nTa machine : ") + profil.resume())
    if profil.sans_gpu():
        es.dire(_t("(Pas de carte graphique utilisable détectée : les modèles tourneront sur le processeur, plus lentement. Les petits modèles restent agréables.)"))
    cat = catalogue.charger(Path(dossiers["cache"]) / "catalogue.json")
    choix = selection.choisir(profil, cat)

    cfg["securite"] = vars(choisir_securite(es, options)).copy()
    cfg["securite"]["proxy_ips"] = list(cfg["securite"]["proxy_ips"])
    besoin = sum(c.modele["go"] for c in {choix[r].id: choix[r] for r in selection.par_defaut(choix)}.values())
    cfg["emplacements"].update(choisir_emplacements(es, options, profil, besoin))          # update : les autres dossiers de travail déjà ajoutés ne disparaissent pas
    roles = choisir_roles(es, options, choix, profil)
    o = ollama or ollama_client.Ollama()
    try:
        deja = set(o.installes())
    except ollama_client.ErreurOllama:
        deja = set()
    liste, total = selection.a_telecharger(choix, roles, deja)
    for r in roles:
        if choix[r] and choix[r].id in deja:
            cfg["modeles"]["choisis"][r] = choix[r].id          # déjà installé : on le garde, sans retélécharger

    config.preparer(dossiers)
    Path(cfg["emplacements"]["travail"]).mkdir(parents=True, exist_ok=True)
    cible = Path(cfg["emplacements"]["modeles"] or Path.home())
    try:
        libre = shutil.disk_usage(cible if cible.exists() else Path(cible.anchor or ".")).free / GO
    except OSError:
        libre = 0
    if total:
        es.dire(_t("\nÀ télécharger : {:g} Go ({}). Espace libre : {:g} Go.").format(total, ", ".join(c.id for c in liste), round(libre, 1)))
        if libre and total * 1.1 > libre:
            es.dire(_t("✘ Pas assez de place sur ce disque. Choisis un autre emplacement (lutin setup) ou moins de modèles."))
            liste = []
        elif not es.confirmer(_t("Lancer le téléchargement ?"), True):
            liste = []

    if liste or not options.get("sans_ollama"):
        if installer_ollama_si_besoin(es, profil, cfg, options, dossiers["cache"]) and liste:
            variables = ollama_client.variables_serveur(profil, cfg["emplacements"]["modeles"])
            if cfg["emplacements"]["modeles"]:
                definir_variables_utilisateur({"OLLAMA_MODELS": cfg["emplacements"]["modeles"]}, profil.systeme)
            if not o.actif():
                exe = ollama_client.trouver_executable(profil.systeme)
                if exe:
                    ollama_client.demarrer_serveur(exe, variables, profil.systeme)
                    import time
                    for _ in range(40):
                        if o.actif():
                            break
                        time.sleep(0.5)
            if not o.actif():
                es.dire(_t("✘ Ollama ne répond pas : relance « lutin setup » dans une nouvelle fenêtre."))
            else:
                for c in liste:
                    es.dire(_t("\nTéléchargement de {} ({:g} Go)…").format(c.id, c.modele["go"]))
                    try:
                        o.telecharger(c.id, barre(es))
                    except (ollama_client.ErreurOllama, horsligne.HorsLigne) as e:
                        es.dire("✘ " + str(e))
                        continue
                    for r in roles:
                        if choix[r] and choix[r].id == c.id:
                            cfg["modeles"]["choisis"][r] = c.id
                    es.dire(_t("✔ {} installé.").format(c.id))

    principal = cfg["modeles"]["choisis"].get("polyvalent") or next(iter(cfg["modeles"]["choisis"].values()), "")
    if principal and any(c.id == principal for c in liste) and es.confirmer(_t("Tester la vitesse de {} maintenant ? (une vingtaine de secondes)").format(principal), False):
        try:
            mesure = bench.executer(ollama or ollama_client.Ollama(), principal, rapide=True, resume_machine=profil.resume())
            bench.enregistrer(Path(dossiers["cache"]) / "bench.json", mesure)
            es.dire("  {} : {}".format(principal, bench.resume(mesure)))
        except (ollama_client.ErreurOllama, OSError) as e:
            es.dire(_t("  (test de vitesse impossible : {})").format(e))
    cfg["installe"] = True
    config.enregistrer(dossiers, cfg)
    es.dire(_t("\nTerminé. Pour démarrer :  lutin"))
    es.dire(_t("Dans le terminal :     lutin chat"))
    if cfg["securite"]["niveau"] == securite.RESEAU:
        es.dire(_t("Pour connecter un téléphone : lance « lutin », puis ouvre l'adresse affichée et entre le code PIN (« lutin pin » en donne un nouveau)."))
    return cfg
