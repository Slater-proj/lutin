"""Piloter un vrai Chrome sans dépendance : démarrage, navigation, évaluation de JavaScript (protocole DevTools par WebSocket, écrit avec la bibliothèque standard).

    with Page(chrome, profil) as p:
        p.aller("http://127.0.0.1:8777/")
        p.attendre("document.querySelector('#bEnvoyer')")           # une expression JavaScript qui devient vraie
        p.evaluer("document.querySelector('[data-p=acces]').click()")
"""
import base64
import json
import os
import socket
import struct
import subprocess
import time
import urllib.request
from pathlib import Path


class ErreurCdp(Exception):
    pass


class WebSocket:
    """Le minimum du protocole WebSocket (RFC 6455) côté client : une poignée de main, des trames texte masquées, des trames texte reçues."""

    def __init__(self, hote, port, chemin):
        self.s = socket.create_connection((hote, port), timeout=30)
        cle = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(("GET {} HTTP/1.1\r\nHost: {}:{}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n\r\n".format(chemin, hote, port, cle)).encode())
        reponse = b""
        while b"\r\n\r\n" not in reponse:
            morceau = self.s.recv(4096)
            if not morceau:
                raise ErreurCdp("poignée de main refusée")
            reponse += morceau
        if b" 101 " not in reponse.split(b"\r\n")[0]:
            raise ErreurCdp("poignée de main refusée : " + reponse.split(b"\r\n")[0].decode())
        self.reste = reponse.split(b"\r\n\r\n", 1)[1]

    def lire(self, n):
        while len(self.reste) < n:
            morceau = self.s.recv(65536)
            if not morceau:
                raise ErreurCdp("connexion fermée")
            self.reste += morceau
        sortie, self.reste = self.reste[:n], self.reste[n:]
        return sortie

    def envoyer(self, texte):
        donnees = texte.encode("utf-8")
        entete = bytearray([0x81])
        if len(donnees) < 126:
            entete.append(0x80 | len(donnees))
        elif len(donnees) < 65536:
            entete += bytes([0x80 | 126]) + struct.pack(">H", len(donnees))
        else:
            entete += bytes([0x80 | 127]) + struct.pack(">Q", len(donnees))
        masque = os.urandom(4)
        self.s.sendall(bytes(entete) + masque + bytes(b ^ masque[i % 4] for i, b in enumerate(donnees)))

    def recevoir(self):
        texte = b""
        while True:
            octet1, octet2 = self.lire(2)
            fin, code, longueur = octet1 & 0x80, octet1 & 0x0F, octet2 & 0x7F
            if longueur == 126:
                longueur = struct.unpack(">H", self.lire(2))[0]
            elif longueur == 127:
                longueur = struct.unpack(">Q", self.lire(8))[0]
            donnees = self.lire(longueur)
            if code == 0x8:
                raise ErreurCdp("connexion fermée par Chrome")
            if code in (0x1, 0x0):
                texte += donnees
                if fin:
                    return texte.decode("utf-8")

    def fermer(self):
        try:
            self.s.close()
        except OSError:
            pass


class Page:
    def __init__(self, chrome, profil, taille="1200,1400"):
        self.profil = Path(profil)
        self.processus = subprocess.Popen([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--remote-debugging-port=0", "--user-data-dir=" + str(self.profil),
                                           "--window-size=" + taille, "--no-first-run", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        fichier = self.profil / "DevToolsActivePort"
        debut = time.time()
        while time.time() - debut < 30 and not fichier.is_file():
            time.sleep(0.2)
        if not fichier.is_file():
            self.processus.kill()
            raise ErreurCdp("Chrome n'a pas annoncé son port de débogage")
        time.sleep(0.3)
        self.port = int(fichier.read_text().split()[0])
        cible = None
        for _ in range(50):
            try:
                cible = [t for t in json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json" % self.port, timeout=5).read()) if t.get("type") == "page"][0]
                break
            except (OSError, IndexError, ValueError):
                time.sleep(0.2)
        if not cible:
            self.processus.kill()
            raise ErreurCdp("aucun onglet")
        chemin = cible["webSocketDebuggerUrl"].split("%d" % self.port, 1)[1]
        self.ws = WebSocket("127.0.0.1", self.port, chemin)
        self.numero = 0
        self.erreurs = []
        self.commande("Runtime.enable")
        self.commande("Page.enable")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fermer()

    def commande(self, methode, **parametres):
        self.numero += 1
        mon_numero = self.numero
        self.ws.envoyer(json.dumps({"id": mon_numero, "method": methode, "params": parametres}))
        while True:
            message = json.loads(self.ws.recevoir())
            if message.get("method") == "Runtime.exceptionThrown":
                self.erreurs.append(message["params"]["exceptionDetails"].get("exception", {}).get("description") or message["params"]["exceptionDetails"].get("text", "?"))
            elif message.get("method") == "Runtime.consoleAPICalled" and message["params"].get("type") == "error":
                self.erreurs.append(" ".join(str(a.get("value", a.get("description", ""))) for a in message["params"].get("args", [])))
            if message.get("id") == mon_numero:
                if "error" in message:
                    raise ErreurCdp(str(message["error"]))
                return message.get("result", {})

    def aller(self, adresse, delai=30):
        self.commande("Page.navigate", url=adresse)
        self.attendre("document.readyState === 'complete'", delai)

    def evaluer(self, expression):
        r = self.commande("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            raise ErreurCdp("JavaScript : " + str(r["exceptionDetails"].get("exception", {}).get("description") or r["exceptionDetails"]))
        return r.get("result", {}).get("value")

    def attendre(self, expression, delai=20):
        debut = time.time()
        derniere = None
        while time.time() - debut < delai:
            try:
                derniere = self.evaluer(expression)
            except ErreurCdp:
                derniere = None
            if derniere:
                return derniere
            time.sleep(0.25)
        raise ErreurCdp("jamais vrai en {} s : {}".format(delai, expression))

    def fermer(self):
        try:
            self.commande("Browser.close")
        except Exception:  # noqa: BLE001
            pass
        self.ws.fermer()
        try:
            self.processus.wait(10)
        except subprocess.TimeoutExpired:
            self.processus.kill()
