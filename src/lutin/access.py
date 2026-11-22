"""Page « Accès » : qui peut se connecter (niveau de sécurité), appareils appairés, code PIN et QR code, redémarrage, restauration d'une sauvegarde.

Le niveau se change seulement depuis cette machine et pour le prochain démarrage (l'adresse d'écoute est choisie au lancement) ; dans Docker il vient de la variable LUTIN_NIVEAU, réappliquée à chaque démarrage.
L'état de Lutin (SECURITE, APPAREILS…) reste dans moteur : ce module le lit par « _m.NOM ».
"""
import os
import tempfile
import threading
from pathlib import Path

from . import setup_wizard, backup
from . import core as _m
from . import security as _sec
from .i18n import t as _t

RESTART_CODE = 75          # code de sortie « relance-moi » : le superviseur (lutin / lutin serve) relance tout de suite, sans compter une panne
MAX_RESTORE = 1024 ** 3


def in_docker():
    return bool(os.environ.get("LUTIN_DOCKER"))


def can_restart():
    """Vrai si quelque chose relancera Lutin après sa sortie : le superviseur de `lutin`, ou la politique de redémarrage du conteneur."""
    return bool(os.environ.get("LUTIN_SUPERVISE")) or in_docker()


def saved_security():
    return _sec.Security.depuis_dict(_m.read_config().get("securite"))


RESTORED = {"fait": False}          # une sauvegarde remise pendant cette exécution : elle n'est entièrement prise en compte qu'au prochain démarrage


def restart_needed():
    """Vrai quand un changement attend le prochain démarrage : niveau d'accès enregistré différent de celui en cours, sauvegarde remise, ou mise à
    jour installée sans superviseur pour relancer Lutin (état « fini »)."""
    return saved_security() != _m.SECURITY or RESTORED["fait"] or UPDATE["etat"] == "fini"


def state(configurateur, strict=None, admin_distance=False):
    """Tout ce que la page Accès affiche."""
    s = _m.SECURITY
    sur_disque = saved_security()
    return {
        "niveau": s.niveau, "port": s.port, "url_publique": s.url_publique, "proxy_ips": list(s.proxy_ips), "ecoute": s.ecoute,
        "enregistre": {"niveau": sur_disque.niveau, "url_publique": sur_disque.url_publique, "proxy_ips": list(sur_disque.proxy_ips)},
        "redemarrage_necessaire": sur_disque != s,
        "modifiable": bool(configurateur) and not in_docker(), "docker": in_docker(),
        "admin_distance": {"actif": bool(admin_distance), "docker": in_docker(), "modifiable": bool(configurateur if strict is None else strict) and not in_docker()}, "peut_redemarrer": can_restart(),
        "adresse": "http://{}:{}/".format(_m.IP_LAN or _m.local_ip(), s.port),
        "appareils": _m.DEVICES.liste(),
        "avertissements": {"reseau": _t(setup_wizard.WARNING_NETWORK), "proxy": _t(setup_wizard.WARNING_PROXY)},
        "niveaux": {n: {"titre": _t(t), "detail": _t(d)} for n, (_, t, d) in setup_wizard.LEVELS_TEXT.items()},
    }


def apply(donnees, configurateur):
    """Enregistre le nouveau niveau d'accès dans la configuration (pour le prochain démarrage). Les accords automatiques restent coupés hors du niveau « local » quoi qu'il arrive (règle du moteur)."""
    if in_docker():
        raise ValueError(_t("Dans Docker, le niveau d'accès vient de la variable LUTIN_NIVEAU du conteneur : change-la là (docs/DOCKER.md)."))
    if not configurateur:
        raise ValueError(_t("Le niveau d'accès ne se change que depuis cette machine."))
    niveau = str(donnees.get("niveau", ""))
    if niveau not in _sec.LEVELS:
        raise ValueError(_t("Niveau inconnu : {}").format(niveau))
    actuel = _m.SECURITY
    nouveau = _sec.Security(niveau=niveau, port=actuel.port, ecoute=actuel.ecoute if niveau != _sec.LOCAL else "",
                            url_publique=str(donnees.get("url_publique", "")).strip() if niveau == _sec.PROXY else "",
                            proxy_ips=[x for x in str(" ".join(donnees.get("proxy_ips") or [])).replace(",", " ").split() if x] if niveau == _sec.PROXY else [])
    if niveau != _sec.LOCAL and not donnees.get("comprend"):
        raise ValueError(_t("Coche « J'ai compris les risques » pour ouvrir l'accès."))
    problemes = nouveau.valider()
    if problemes:
        raise ValueError(_t("Sécurité : ") + " ; ".join(problemes))
    cfg = _m.read_config()
    cfg["securite"] = dict(vars(nouveau), proxy_ips=list(nouveau.proxy_ips))
    _m.write_config(cfg)
    _m.log_event("Niveau d'accès enregistré : {} (actif au prochain démarrage)".format(niveau))
    return {"redemarrage_necessaire": nouveau != actuel}


def restart():
    """Quitte avec le code « relance-moi » après avoir répondu. Refuse pendant une réponse du modèle."""
    if not can_restart():
        raise ValueError(_t("Lutin n'a pas été lancé par la commande « lutin » : relance-le toi-même."))
    if _m.ACTIVE_TURNS:
        raise ValueError(_t("Une réponse est en cours : attends la fin avant de redémarrer."))
    _m.log_event("Redémarrage demandé depuis la page.")
    threading.Timer(0.8, os._exit, [RESTART_CODE]).start()
    return {"ok": True}


UPDATE = {"etat": "", "lignes": [], "avant": "", "apres": ""}
_update_lock = threading.Lock()


def update():
    """Met Lutin à jour depuis la page (même chose que la commande `lutin update --app`), puis le redémarre tout seul s'il tourne sous la supervision de `lutin` ou de l'icône. Le suivi se lit avec etat_maj()."""
    from . import offline
    if in_docker():
        raise ValueError(_t("Dans Docker, la mise à jour se fait en récupérant la nouvelle image : docker compose pull && docker compose up -d"))
    if offline.is_active():
        raise ValueError(_t("Mode hors ligne strict : Lutin n'est pas mis à jour."))
    if _m.ACTIVE_TURNS:
        raise ValueError(_t("Une réponse est en cours : attends la fin avant de mettre à jour."))
    with _update_lock:
        if UPDATE["etat"] == "en cours":
            raise ValueError(_t("Une mise à jour est déjà en cours."))
        UPDATE.update(etat="en cours", lignes=[_t("Recherche de la dernière version…")], avant="", apres="")

    def travail():
        from . import cli
        try:
            code, avant, apres = cli.detailed_update(UPDATE["lignes"].append, UPDATE["lignes"].append, capturer=True)
        except Exception as erreur:  # noqa: BLE001 — la page doit toujours apprendre comment ça s'est fini
            UPDATE.update(etat="erreur")
            UPDATE["lignes"].append(str(erreur)[:300])
            return
        UPDATE.update(avant=avant, apres=apres or "")
        if code != 0:
            UPDATE["etat"] = "erreur"
        elif not apres:
            UPDATE["etat"] = "a_jour"
        elif can_restart():
            UPDATE["etat"] = "redemarrage"
            UPDATE["lignes"].append(_t("Redémarrage de Lutin pour appliquer la mise à jour…"))
            threading.Timer(1.5, restart).start()               # le temps que la page lise l'état
        else:
            UPDATE["etat"] = "fini"
            UPDATE["lignes"].append(_t("Relance Lutin toi-même pour appliquer la mise à jour (fermer puis rouvrir)."))
    threading.Thread(target=travail, daemon=True, name="mise-a-jour").start()
    return dict(UPDATE)


def update_state():
    return dict(UPDATE)


def restore_stream(flux, taille):
    """Restaure une sauvegarde (.zip) reçue en flux : vérifiée en entier avant d'écrire, état actuel gardé dans un zip avant."""
    if taille <= 0 or taille > MAX_RESTORE:
        raise ValueError(_t("Archive vide ou trop grande."))
    c = _m.config_path()
    dossiers = {"config": c.parent if c else None, "donnees": _m.DATA, "memoire": _m.MEMORY}
    with tempfile.TemporaryDirectory(prefix="lutin-restauration-") as tmp:
        fichier = Path(tmp) / "sauvegarde.zip"
        with open(fichier, "wb") as sortie:
            restant = taille
            while restant > 0:
                morceau = flux.read(min(1024 * 1024, restant))
                if not morceau:
                    break
                sortie.write(morceau)
                restant -= len(morceau)
        if restant:
            raise ValueError(_t("Envoi interrompu."))
        r = backup.restore(dossiers, fichier, dossier_secours=_m.DATA / "import")
    _m.log_event("Sauvegarde restaurée : {} fichiers".format(r["fichiers"]))
    RESTORED["fait"] = True
    return dict(r, redemarrage_necessaire=True)

