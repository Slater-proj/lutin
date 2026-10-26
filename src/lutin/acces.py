"""Page « Accès » : qui peut se connecter (niveau de sécurité), appareils appairés, code PIN et QR code, redémarrage, restauration d'une sauvegarde.

Le niveau se change seulement depuis cette machine et pour le prochain démarrage (l'adresse d'écoute est choisie au lancement) ; dans Docker il vient de la variable LUTIN_NIVEAU, réappliquée à chaque démarrage.
L'état de Lutin (SECURITE, APPAREILS…) reste dans moteur : ce module le lit par « _m.NOM ».
"""
import os
import tempfile
import threading
from pathlib import Path

from . import installation, qr, sauvegarde
from . import moteur as _m
from . import securite as _sec
from .i18n import t as _t

CODE_REDEMARRAGE = 75          # code de sortie « relance-moi » : le superviseur (lutin / lutin serve) relance tout de suite, sans compter une panne
RESTAURATION_MAX = 1024 ** 3


def en_docker():
    return bool(os.environ.get("LUTIN_DOCKER"))


def peut_redemarrer():
    """Vrai si quelque chose relancera Lutin après sa sortie : le superviseur de `lutin`, ou la politique de redémarrage du conteneur."""
    return bool(os.environ.get("LUTIN_SUPERVISE")) or en_docker()


def securite_enregistree():
    return _sec.Securite.depuis_dict(_m.config_lue().get("securite"))


def etat(configurateur):
    """Tout ce que la page Accès affiche."""
    s = _m.SECURITE
    sur_disque = securite_enregistree()
    return {
        "niveau": s.niveau, "port": s.port, "url_publique": s.url_publique, "proxy_ips": list(s.proxy_ips), "ecoute": s.ecoute,
        "enregistre": {"niveau": sur_disque.niveau, "url_publique": sur_disque.url_publique, "proxy_ips": list(sur_disque.proxy_ips)},
        "redemarrage_necessaire": sur_disque != s,
        "modifiable": bool(configurateur) and not en_docker(), "docker": en_docker(), "peut_redemarrer": peut_redemarrer(),
        "adresse": "http://{}:{}/".format(_m.IP_LAN or _m.ip_locale(), s.port),
        "appareils": _m.APPAREILS.liste(),
        "avertissements": {"reseau": _t(installation.AVERTISSEMENT_RESEAU), "proxy": _t(installation.AVERTISSEMENT_PROXY)},
        "niveaux": {n: {"titre": _t(t), "detail": _t(d)} for n, (_, t, d) in installation.NIVEAUX_TEXTE.items()},
    }


def appliquer(donnees, configurateur):
    """Enregistre le nouveau niveau d'accès dans la configuration (pour le prochain démarrage). Les accords automatiques restent coupés hors du niveau « local » quoi qu'il arrive (règle du moteur)."""
    if en_docker():
        raise ValueError(_t("Dans Docker, le niveau d'accès vient de la variable LUTIN_NIVEAU du conteneur : change-la là (docs/DOCKER.md)."))
    if not configurateur:
        raise ValueError(_t("Le niveau d'accès ne se change que depuis cette machine."))
    niveau = str(donnees.get("niveau", ""))
    if niveau not in _sec.NIVEAUX:
        raise ValueError(_t("Niveau inconnu : {}").format(niveau))
    actuel = _m.SECURITE
    nouveau = _sec.Securite(niveau=niveau, port=actuel.port, ecoute=actuel.ecoute if niveau != _sec.LOCAL else "",
                            url_publique=str(donnees.get("url_publique", "")).strip() if niveau == _sec.PROXY else "",
                            proxy_ips=[x for x in str(" ".join(donnees.get("proxy_ips") or [])).replace(",", " ").split() if x] if niveau == _sec.PROXY else [])
    if niveau != _sec.LOCAL and not donnees.get("comprend"):
        raise ValueError(_t("Coche « J'ai compris les risques » pour ouvrir l'accès."))
    problemes = nouveau.valider()
    if problemes:
        raise ValueError(_t("Sécurité : ") + " ; ".join(problemes))
    cfg = _m.config_lue()
    cfg["securite"] = dict(vars(nouveau), proxy_ips=list(nouveau.proxy_ips))
    _m.config_ecrire(cfg)
    _m.journaliser("Niveau d'accès enregistré : {} (actif au prochain démarrage)".format(niveau))
    return {"redemarrage_necessaire": nouveau != actuel}


def redemarrer():
    """Quitte avec le code « relance-moi » après avoir répondu. Refuse pendant une réponse du modèle."""
    if not peut_redemarrer():
        raise ValueError(_t("Lutin n'a pas été lancé par la commande « lutin » : relance-le toi-même."))
    if _m.TOURS_ACTIFS:
        raise ValueError(_t("Une réponse est en cours : attends la fin avant de redémarrer."))
    _m.journaliser("Redémarrage demandé depuis la page.")
    threading.Timer(0.8, os._exit, [CODE_REDEMARRAGE]).start()
    return {"ok": True}


def qr_json(texte):
    if len(texte.encode("utf-8")) > qr.CAPACITE_MAX:
        raise ValueError(_t("Texte trop long pour le code QR."))
    m = qr.matrice(texte)
    return {"taille": len(m), "lignes": ["".join(map(str, ligne)) for ligne in m]}


def restaurer_flux(flux, taille):
    """Restaure une sauvegarde (.zip) reçue en flux : vérifiée en entier avant d'écrire, état actuel gardé dans un zip avant."""
    if taille <= 0 or taille > RESTAURATION_MAX:
        raise ValueError(_t("Archive vide ou trop grande."))
    c = _m.chemin_config()
    dossiers = {"config": c.parent if c else None, "donnees": _m.DONNEES, "memoire": _m.MEMOIRE}
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
        r = sauvegarde.restaurer(dossiers, fichier, dossier_secours=_m.DONNEES / "import")
    _m.journaliser("Sauvegarde restaurée : {} fichiers".format(r["fichiers"]))
    return dict(r, redemarrage_necessaire=True)

