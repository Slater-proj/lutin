"""Alimentation (décision D8) : réveiller une machine, l'éteindre (avec accord), démarrer Lutin à l'ouverture de session.

- **Réveil** : un « paquet magique » (6 octets 0xFF puis 16 fois l'adresse MAC) envoyé en UDP à tout le réseau local. Bibliothèque standard seulement. Il ne marche que si la machine l'accepte : BIOS (Wake-on-LAN),
  carte réseau, câble Ethernet (le Wi-Fi réveille rarement), et sous Windows « démarrage rapide » désactivé. `raison_echec()` dit lesquelles de ces limites vérifier quand rien ne répond.
- **Extinction** : une action EXPLICITE. Le propriétaire de la machine à éteindre doit l'avoir autorisée (case décochée par défaut, dans Réglages > Machines) ; la demande vient d'une machine appairée, avec son jeton ;
  l'extinction a 30 secondes de délai et se laisse annuler ; tout est journalisé des deux côtés.
- **Démarrage automatique** : la clé « Run » de la session de l'utilisateur sous Windows (une tâche planifiée « à l'ouverture de session » exige les droits d'administrateur) (pas un service : un service tourne dans la session 0, sans accès à la carte graphique ni au bureau), une unité systemd
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


def adresses_locales():
    """Les adresses IPv4 de cette machine (une par carte réseau, hors boucle locale et adresses auto-attribuées). Un paquet de diffusion ne part que par UNE carte si on ne dit pas laquelle :
    avec un VPN, Hyper-V, WSL ou Docker, c'est souvent la mauvaise, et le réveil n'atteint jamais le réseau."""
    trouvees = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            trouvees.append(info[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:        # l'adresse de la route par défaut (rien n'est envoyé)
            s.connect(("192.0.2.1", 9))
            trouvees.append(s.getsockname()[0])
    except OSError:
        pass
    sortie = []
    for a in trouvees:
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", a) and not a.startswith(("127.", "169.254.", "0.")) and a not in sortie:
            sortie.append(a)
    return sortie


def emission_limitee():
    """Un message si cette machine ne PEUT PAS atteindre le réseau local par diffusion (conteneur Docker en réseau « bridge » : le paquet reste dans le réseau interne de Docker), sinon « »."""
    if not (os.environ.get("LUTIN_DOCKER") or os.path.exists("/.dockerenv")):
        return ""
    locales = adresses_locales()
    if locales and not all(re.match(r"^172\.(1[6-9]|2\d|3[01])\.", a) for a in locales):
        return ""
    return _t("Lutin tourne dans Docker en réseau « bridge » : un paquet de réveil ne sort pas sur ton réseau local. Un envoi direct à la machine est tenté (il marche si l'hôte la connaît encore, par exemple juste après son extinction). Pour un réveil fiable, dans docker-compose.yml, ajoute « network_mode: host » (et retire « ports: ») pour pouvoir réveiller des machines, ou, sans changer le réseau, depuis l'hôte : « docker run --rm --network host ghcr.io/slater-proj/lutin lutin wake <MAC> ».")


def envoyer_reveil(mac, adresse_machine="", ports=(9, 7), socket_factory=socket.socket, locales=None):
    """Envoie le paquet magique PAR CHAQUE CARTE RÉSEAU de cette machine ; renvoie la liste des (adresse, port) atteints. Lève ValueError si rien n'a pu partir."""
    paquet = paquet_magique(mac)
    envoyes = []
    sources = [""] + list(adresses_locales() if locales is None else locales)
    for source in sources:
        cibles = diffusions(adresse_machine)
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", str(adresse_machine or "")):
            cibles.append(adresse_machine)          # envoi direct : seul chemin d'un conteneur « bridge » (marche si l'hôte connaît encore la machine : ARP récent ou statique)
        m = re.match(r"^(\d{1,3}\.\d{1,3}\.\d{1,3})\.\d{1,3}$", source)
        if m and m.group(1) + ".255" not in cibles:
            cibles.append(m.group(1) + ".255")
        try:
            s = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        except OSError:
            continue
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            if source:
                try:
                    s.bind((source, 0))
                except OSError:
                    continue
            for cible in cibles:
                for port in ports:
                    try:
                        s.sendto(paquet, (cible, port))
                        if (cible, port) not in envoyes:
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


# --------------------------------------------------------------------------- l'adresse MAC de cette machine, et peut-elle être réveillée à distance ?

def normaliser_mac(mac):
    """« 00-1A-2B-3C-4D-5E » ou « 001a2b3c4d5e » -> « 00:1A:2B:3C:4D:5E » ; « » si ce n'est pas une adresse MAC utilisable (nulle, multicast, mal formée)."""
    brut = re.sub(r"[^0-9A-Fa-f]", "", str(mac or ""))
    if len(brut) != 12 or int(brut, 16) == 0 or int(brut[1], 16) & 1:
        return ""
    return ":".join(brut[i:i + 2] for i in range(0, 12, 2)).upper()


def analyser_cartes_windows(texte):
    """Sortie JSON de `Get-NetAdapter -Physical` (+ adresses IPv4) -> [{nom, mac, ip, filaire, pret}]."""
    import json
    try:
        brut = json.loads(texte) if str(texte).strip() else []
    except ValueError:
        return []
    if isinstance(brut, dict):
        brut = [brut]
    cartes = []
    for x in brut if isinstance(brut, list) else []:
        mac = normaliser_mac(x.get("mac"))
        if mac and str(x.get("etat", "")).lower() == "up":
            cartes.append({"nom": str(x.get("nom") or ""), "mac": mac, "ip": str(x.get("ip") or ""), "filaire": not re.search(r"wi-?fi|wireless|wlan|sans fil", str(x.get("description") or "") + " " + str(x.get("nom") or ""), re.I),
                           "reveil": x.get("reveil")})
    return cartes


SCRIPT_CARTES_WINDOWS = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $r=@(Get-NetAdapter -Physical -ErrorAction SilentlyContinue | ForEach-Object { $i=$_; $ip=(Get-NetIPAddress -InterfaceIndex $i.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -First 1).IPAddress; "
    "$w=$null; try { $pm=Get-NetAdapterPowerManagement -Name $i.Name -ErrorAction Stop; $w=($pm.WakeOnMagicPacket -eq 'Enabled') } catch {}; "
    "[pscustomobject]@{nom=$i.Name; description=$i.InterfaceDescription; mac=$i.MacAddress; etat=[string]$i.Status; ip=$ip; reveil=$w} }); ConvertTo-Json -Compress -InputObject $r")


def cartes_reseau(lanceur=subprocess.run, systeme_actuel=None, racine_sys="/sys/class/net", sortie_ip=None):
    """Les cartes réseau physiques actives de cette machine : [{nom, mac, ip, filaire, reveil}] (reveil : True / False / None si on ne sait pas)."""
    s = systeme_actuel or systeme()
    try:
        if s == "windows":
            r = lanceur(["powershell", "-NoProfile", "-NonInteractive", "-Command", SCRIPT_CARTES_WINDOWS], capture_output=True, timeout=20, creationflags=0x08000000)
            return analyser_cartes_windows(r.stdout.decode("utf-8", "replace"))
        if s == "linux":
            adresses = {}
            texte = sortie_ip if sortie_ip is not None else lanceur(["ip", "-o", "-4", "addr"], capture_output=True, timeout=10).stdout.decode("utf-8", "replace")
            for ligne in texte.splitlines():
                m = re.match(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)", ligne)
                if m:
                    adresses.setdefault(m.group(1), m.group(2))
            cartes = []
            for d in sorted(Path(racine_sys).iterdir()):
                if not (d / "device").exists():
                    continue          # lo, docker0, veth…, ponts : pas de matériel derrière
                if (d / "operstate").read_text(encoding="utf-8", errors="replace").strip() != "up":
                    continue
                mac = normaliser_mac((d / "address").read_text(encoding="utf-8", errors="replace"))
                if mac:
                    cartes.append({"nom": d.name, "mac": mac, "ip": adresses.get(d.name, ""), "filaire": not (d / "wireless").exists(), "reveil": reveil_linux(d.name, lanceur)})
            return cartes
    except (OSError, subprocess.SubprocessError):
        pass
    return []


def reveil_linux(interface, lanceur=subprocess.run):
    """`Wake-on: g` d'après ethtool : True / False ; None si ethtool est absent ou refuse (il demande souvent root)."""
    try:
        r = lanceur(["ethtool", interface], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"^\s*Wake-on:\s*(\S+)", r.stdout.decode("utf-8", "replace"), re.M)
    return ("g" in m.group(1)) if m else None


def choisir_carte(cartes, ip_locale=""):
    """La carte à retenir pour réveiller cette machine : celle qui porte l'adresse par laquelle l'autre Lutin l'a jointe, sinon une carte filaire, sinon la première."""
    if not cartes:
        return None
    return next((c for c in cartes if ip_locale and c["ip"] == ip_locale), None) or next((c for c in cartes if c["filaire"]), cartes[0])


def demarrage_rapide_windows():
    """Le « démarrage rapide » de Windows est-il actif ? (une machine éteinte avec lui ne se réveille souvent pas par le réseau) True / False / None."""
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Power", 0, winreg.KEY_READ) as cle:
            return bool(winreg.QueryValueEx(cle, "HiberbootEnabled")[0])
    except OSError:
        return None


def etat_reveil(ip_locale="", cartes=None, en_docker=False, systeme_actuel=None, demarrage_rapide=None):
    """Ce que cette machine dit de sa capacité à être réveillée à distance : {mac, carte, pret, avertissements}. `pret` : True (tout est en règle), False (un réglage manque), None (impossible à vérifier d'ici)."""
    s = systeme_actuel or systeme()
    if en_docker:
        return {"mac": "", "carte": "", "pret": None, "avertissements": [_t("Lutin tourne dans un conteneur : il ne voit pas la carte réseau de la machine hôte. Renseigne son adresse MAC à la main (« ip link » sur l'hôte) et active le Wake-on-LAN sur l'hôte.")]}
    cartes = cartes if cartes is not None else cartes_reseau(systeme_actuel=s)
    carte = choisir_carte(cartes, ip_locale)
    if carte is None:
        return {"mac": "", "carte": "", "pret": None, "avertissements": [_t("Aucune carte réseau physique active n'a été trouvée : l'adresse MAC est à saisir à la main.")]}
    avertissements = []
    pret = True
    if carte["reveil"] is False:
        pret = False
        avertissements.append(_t("Le réveil par le réseau (Wake-on-LAN) est désactivé sur la carte « {} » : active-le dans les propriétés de la carte (Gestion de l'alimentation > « Autoriser ce périphérique à sortir l'ordinateur de veille » et « Magic packet ») et dans le BIOS.").format(carte["nom"]) if s == "windows"
                              else _t("Le Wake-on-LAN est désactivé sur la carte « {} » : « sudo ethtool -s {} wol g » (à rendre permanent avec NetworkManager ou systemd-networkd), et activé dans le BIOS.").format(carte["nom"], carte["nom"]))
    elif carte["reveil"] is None:
        pret = None
        avertissements.append(_t("Impossible de vérifier d'ici que le Wake-on-LAN est activé sur la carte « {} » : vérifie-le dans ses propriétés et dans le BIOS.").format(carte["nom"]))
    if not carte["filaire"]:
        pret = False if pret is not None else pret
        avertissements.append(_t("Cette machine est en Wi-Fi : le réveil par le réseau marche rarement sans câble Ethernet."))
    if s == "windows":
        rapide = demarrage_rapide_windows() if demarrage_rapide is None else demarrage_rapide
        if rapide:
            pret = False
            avertissements.append(_t("Le « démarrage rapide » de Windows est actif : une machine éteinte avec lui ne se réveille souvent pas par le réseau. Désactive-le (Options d'alimentation > Choisir l'action des boutons d'alimentation)."))
    return {"mac": carte["mac"], "carte": carte["nom"], "pret": pret, "avertissements": avertissements}


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
    return [sys.executable, "-m", "lutin", "serve", "--no-browser"]


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


CLE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


def interdit_pendant_les_tests():
    """Les tests (LUTIN_TESTS=1, posé par tests/context.py) n'ont pas le droit de modifier le vrai registre : ils doivent donner un faux registre. Évite qu'une valeur factice reste sur la machine de développement."""
    if os.environ.get("LUTIN_TESTS") == "1":
        raise OSError("écriture du registre interdite pendant les tests : utilise un faux registre")


class RegistreWindows:
    """La clé « Run » de l'utilisateur (HKCU) : les programmes lancés à l'ouverture de SA session. Aucun droit d'administrateur n'est nécessaire, contrairement à une tâche planifiée « à l'ouverture de session »
    que Windows refuse (« Accès refusé ») à un utilisateur ordinaire. Remplaçable par un faux dans les tests."""

    def lire(self, nom):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLE_RUN, 0, winreg.KEY_READ) as cle:
                return str(winreg.QueryValueEx(cle, nom)[0])
        except OSError:
            return ""

    def ecrire(self, nom, valeur):
        interdit_pendant_les_tests()
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CLE_RUN, 0, winreg.KEY_SET_VALUE) as cle:
            winreg.SetValueEx(cle, nom, 0, winreg.REG_SZ, valeur)

    def supprimer(self, nom):
        interdit_pendant_les_tests()
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLE_RUN, 0, winreg.KEY_SET_VALUE) as cle:
                winreg.DeleteValue(cle, nom)
        except OSError:
            pass


def commande_windows(commande=None):
    """La commande de la clé Run : `pythonw.exe` (sans fenêtre de console) quand il existe à côté de Python."""
    commande = list(commande or commande_lutin())
    exe = Path(commande[0])
    sans_console = exe.with_name("pythonw.exe")
    if exe.name.lower() == "python.exe" and sans_console.is_file():
        commande[0] = str(sans_console)
    return subprocess.list2cmdline(commande)


def etat_demarrage(lanceur=subprocess.run, systeme_actuel=None, maison=None, registre=None):
    """{installe, possible, limites}."""
    s = systeme_actuel or systeme()
    if s == "windows":
        installe = bool((registre or RegistreWindows()).lire(NOM_TACHE))
        if not installe:          # une ancienne version a pu créer une tâche planifiée : elle compte aussi (et se retire avec le bouton)
            try:
                installe = lanceur(["schtasks", "/Query", "/TN", NOM_TACHE], capture_output=True, timeout=15).returncode == 0
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


def installer_demarrage(lanceur=subprocess.run, systeme_actuel=None, maison=None, commande=None, registre=None):
    s = systeme_actuel or systeme()
    commande = commande or commande_lutin()
    if s == "windows":
        try:
            (registre or RegistreWindows()).ecrire(NOM_TACHE, commande_windows(commande))
        except OSError as e:
            raise ValueError(_t("Windows a refusé d'inscrire Lutin au démarrage de ta session : {}").format(e)) from e
        try:
            lanceur(["schtasks", "/Delete", "/TN", NOM_TACHE, "/F"], capture_output=True, timeout=15)          # une ancienne tâche planifiée « Lutin » lancerait un SECOND Lutin à chaque ouverture de session
        except (OSError, subprocess.SubprocessError):
            pass
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
    return etat_demarrage(lanceur, s, maison, registre)


def retirer_demarrage(lanceur=subprocess.run, systeme_actuel=None, maison=None, registre=None):
    s = systeme_actuel or systeme()
    if s == "windows":
        (registre or RegistreWindows()).supprimer(NOM_TACHE)
        try:
            lanceur(["schtasks", "/Delete", "/TN", NOM_TACHE, "/F"], capture_output=True, timeout=15)          # l'ancienne tâche planifiée, s'il y en a une
        except (OSError, subprocess.SubprocessError):
            pass
    elif s == "linux":
        try:
            lanceur(["systemctl", "--user", "disable", NOM_UNITE], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
        (dossier_unite(maison) / NOM_UNITE).unlink(missing_ok=True)
    MEMO_DEMARRAGE["v"] = None
    return etat_demarrage(lanceur, s, maison, registre)
