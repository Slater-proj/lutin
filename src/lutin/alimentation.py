"""Alimentation (décision D8) : réveiller une machine, l'éteindre (avec accord), démarrer Lutin à l'ouverture de session.

- **Réveil** : un « paquet magique » (6 octets 0xFF puis 16 fois l'adresse MAC) envoyé en UDP à tout le réseau local. Bibliothèque standard seulement. Il ne marche que si la machine l'accepte : BIOS (Wake-on-LAN),
  carte réseau, câble Ethernet (le Wi-Fi réveille rarement), et sous Windows « démarrage rapide » désactivé. `raison_echec()` dit lesquelles de ces limites vérifier quand rien ne répond.
- **Extinction** : une action EXPLICITE. Le propriétaire de la machine à éteindre doit l'avoir autorisée (case décochée par défaut, dans Réglages > Machines) ; la demande vient d'une machine appairée, avec son jeton ;
  l'extinction a 30 secondes de délai et se laisse annuler ; tout est journalisé des deux côtés.
- **Démarrage automatique** : une tâche planifiée « à l'ouverture de session » sous Windows (pas un service : un service tourne dans la session 0, sans accès à la carte graphique ni au bureau), une unité systemd
  utilisateur sous Linux. Une machine qui doit démarrer SANS personne devant doit ouvrir sa session toute seule (auto-connexion Windows) : c'est une limite, dite à l'utilisateur."""
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from .i18n import t as _t

RE_MAC = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
DELAI_EXTINCTION_S = 30
ATTENTE_REVEIL_S = 600          # au-delà, on ne dit plus « réveil envoyé » : il n'a pas marché
SEUIL_RAISONS_S = 180          # après trois minutes sans réponse, on liste ce qui bloque d'habitude
NOM_TACHE = "Lutin"
NOM_UNITE = "lutin.service"


# --------------------------------------------------------------------------- réveil

def paquet_magique(mac):
    """Le paquet de réveil pour cette adresse MAC (102 octets). Lève ValueError si l'adresse est invalide."""
    mac = str(mac or "").strip()
    if not RE_MAC.match(mac):
        raise ValueError(_t("Adresse MAC invalide (exemple : 00:1A:2B:3C:4D:5E)."))
    octets = bytes.fromhex(re.sub(r"[:-]", "", mac))
    return b"\xff" * 6 + octets * 16


def diffusions(adresse_machine=""):
    """Les adresses de diffusion où envoyer le paquet : tout le réseau local, et le /24 de la machine si on connaît son adresse."""
    cibles = ["255.255.255.255"]
    m = re.match(r"^(\d{1,3}\.\d{1,3}\.\d{1,3})\.\d{1,3}$", str(adresse_machine or ""))
    if m:
        cibles.append(m.group(1) + ".255")
    return cibles


def envoyer_reveil(mac, adresse_machine="", ports=(9, 7), socket_factory=socket.socket):
    """Envoie le paquet magique ; renvoie la liste des (adresse, port) atteints. Lève ValueError si rien n'a pu partir."""
    paquet = paquet_magique(mac)
    envoyes = []
    s = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for cible in diffusions(adresse_machine):
            for port in ports:
                try:
                    s.sendto(paquet, (cible, port))
                    envoyes.append((cible, port))
                except OSError:
                    continue
    finally:
        s.close()
    if not envoyes:
        raise ValueError(_t("Le paquet de réveil n'a pu partir sur aucun réseau : cette machine est-elle connectée au réseau local ?"))
    return envoyes


def raison_echec(secondes_depuis_reveil, adresse_machine=""):
    """Quand la machine ne répond toujours pas : ce qu'il faut vérifier, dans l'ordre. Vide tant qu'il est trop tôt pour conclure."""
    if secondes_depuis_reveil < SEUIL_RAISONS_S:
        return ""
    return _t("Elle ne répond toujours pas. Vérifie : le Wake-on-LAN activé dans le BIOS de la machine ; la carte réseau autorisée à la réveiller ; "
              "un câble Ethernet (le Wi-Fi réveille rarement) ; sous Windows, le « démarrage rapide » désactivé ; l'adresse MAC exacte ; et qu'elle ouvre sa session toute seule (auto-connexion) pour que Lutin démarre.")


# --------------------------------------------------------------------------- extinction

COMMANDES_EXTINCTION = {"windows": ["shutdown", "/s", "/t", "0"], "linux": ["systemctl", "poweroff"], "macos": ["osascript", "-e", 'tell application "System Events" to shut down']}
EXTINCTION = {"minuteur": None, "quand": 0.0, "par": ""}
VERROU = threading.Lock()


def systeme():
    if os.name == "nt":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def programmer_extinction(par, lanceur=subprocess.run, delai=DELAI_EXTINCTION_S, systeme_actuel=None, journaliser=lambda t: None):
    """Éteint cette machine dans `delai` secondes (annulable). Renvoie le délai. À n'appeler que si le propriétaire l'a autorisée."""
    commande = COMMANDES_EXTINCTION.get(systeme_actuel or systeme())
    if not commande:
        raise ValueError(_t("Système non pris en charge."))

    def partir():
        journaliser("extinction lancée (demandée par {})".format(par))
        try:
            lanceur(commande, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            journaliser("extinction impossible : {}".format(e))
    with VERROU:
        if EXTINCTION["minuteur"] is not None:
            EXTINCTION["minuteur"].cancel()
        t = threading.Timer(delai, partir)
        t.daemon = True
        EXTINCTION.update(minuteur=t, quand=time.time() + delai, par=par)
        t.start()
    journaliser("extinction demandée par {} : dans {} s".format(par, delai))
    return delai


def annuler_extinction(journaliser=lambda t: None):
    """Annule une extinction en attente. True si quelque chose a été annulé."""
    with VERROU:
        t = EXTINCTION["minuteur"]
        if t is None or not t.is_alive():
            return False
        t.cancel()
        EXTINCTION.update(minuteur=None, quand=0.0, par="")
    journaliser("extinction annulée")
    return True


def extinction_en_attente():
    with VERROU:
        t = EXTINCTION["minuteur"]
        if t is None or not t.is_alive():
            return None
        return {"dans_s": max(0, round(EXTINCTION["quand"] - time.time())), "par": EXTINCTION["par"]}


# --------------------------------------------------------------------------- démarrage automatique

def commande_lutin():
    """Le programme qui lance Lutin : [python, -m, lutin] (celui qui tourne en ce moment, donc celui qui est installé)."""
    return [sys.executable, "-m", "lutin", "serve", "--sans-navigateur"]


def texte_unite(commande=None):
    """L'unité systemd UTILISATEUR (~/.config/systemd/user/lutin.service)."""
    commande = commande or commande_lutin()
    return ("[Unit]\nDescription=Lutin, assistant IA local\nAfter=network-online.target\n\n[Service]\nExecStart={}\nRestart=on-failure\nRestartSec=10\n\n[Install]\nWantedBy=default.target\n"
            .format(" ".join(shlex.quote(c) for c in commande)))


def dossier_unite(maison=None):
    return Path(maison or Path.home()) / ".config" / "systemd" / "user"


def limites(systeme_actuel=None):
    """Ce que le démarrage automatique ne peut PAS faire, dit à l'utilisateur."""
    s = systeme_actuel or systeme()
    if s == "windows":
        return _t("Lutin démarre à l'ouverture de ta session Windows (pas comme service : un service n'a ni la carte graphique ni le bureau). Pour un PC qui doit démarrer sans personne, active l'auto-connexion Windows et, dans le BIOS, « redémarrer après une coupure de courant ».")
    if s == "linux":
        return _t("Lutin démarre à l'ouverture de ta session. Pour qu'il démarre au démarrage de la machine sans ouvrir de session, lance une fois « sudo loginctl enable-linger $USER ».")
    return _t("Le démarrage automatique n'est pas pris en charge sur ce système.")


def etat_demarrage(lanceur=subprocess.run, systeme_actuel=None, maison=None):
    """{installe, possible, limites}."""
    s = systeme_actuel or systeme()
    if s == "windows":
        try:
            r = lanceur(["schtasks", "/Query", "/TN", NOM_TACHE], capture_output=True, timeout=15)
            installe = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            installe = False
        return {"installe": installe, "possible": True, "limites": limites(s)}
    if s == "linux":
        return {"installe": (dossier_unite(maison) / NOM_UNITE).is_file(), "possible": True, "limites": limites(s)}
    return {"installe": False, "possible": False, "limites": limites(s)}


MEMO_DEMARRAGE = {"t": 0.0, "v": None}


def etat_demarrage_memo():
    """Comme etat_demarrage, gardé 30 s (sous Windows il lance un programme ; la page le demande toutes les 8 s)."""
    if MEMO_DEMARRAGE["v"] is None or time.monotonic() - MEMO_DEMARRAGE["t"] > 30:
        MEMO_DEMARRAGE.update(t=time.monotonic(), v=etat_demarrage())
    return MEMO_DEMARRAGE["v"]


def installer_demarrage(lanceur=subprocess.run, systeme_actuel=None, maison=None, commande=None):
    s = systeme_actuel or systeme()
    commande = commande or commande_lutin()
    if s == "windows":
        r = lanceur(["schtasks", "/Create", "/TN", NOM_TACHE, "/SC", "ONLOGON", "/TR", subprocess.list2cmdline(commande), "/F"], capture_output=True, timeout=30)
        if r.returncode != 0:
            raise ValueError(_t("Windows a refusé de créer la tâche planifiée : {}").format((r.stderr or r.stdout or b"").decode("oem", "replace").strip()[:200]))
    elif s == "linux":
        d = dossier_unite(maison)
        d.mkdir(parents=True, exist_ok=True)
        (d / NOM_UNITE).write_text(texte_unite(commande), encoding="utf-8")
        for args in (["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", NOM_UNITE]):
            try:
                lanceur(args, capture_output=True, timeout=30)
            except (OSError, subprocess.SubprocessError) as e:
                raise ValueError(_t("systemd n'a pas répondu : {}").format(e)) from e
    else:
        raise ValueError(_t("Le démarrage automatique n'est pas pris en charge sur ce système."))
    MEMO_DEMARRAGE["v"] = None
    return etat_demarrage(lanceur, s, maison)


def retirer_demarrage(lanceur=subprocess.run, systeme_actuel=None, maison=None):
    s = systeme_actuel or systeme()
    if s == "windows":
        lanceur(["schtasks", "/Delete", "/TN", NOM_TACHE, "/F"], capture_output=True, timeout=15)
    elif s == "linux":
        try:
            lanceur(["systemctl", "--user", "disable", NOM_UNITE], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
        (dossier_unite(maison) / NOM_UNITE).unlink(missing_ok=True)
    MEMO_DEMARRAGE["v"] = None
    return etat_demarrage(lanceur, s, maison)
