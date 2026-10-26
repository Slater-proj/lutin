"""Parler à Ollama (le moteur qui fait tourner les modèles) et l'installer si besoin.

Tout ce qui touche au réseau ou au système passe par des fonctions injectables : les tests utilisent un faux Ollama et ne téléchargent rien.
"""
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from . import horsligne
from .i18n import t as _t

URL_PAR_DEFAUT = "http://127.0.0.1:11434"
URL_TELECHARGEMENT_WINDOWS = "https://ollama.com/download/OllamaSetup.exe"
COMMANDE_LINUX = "curl -fsSL https://ollama.com/install.sh | sh"
EDITEUR_ATTENDU = "ollama"            # le nom de l'éditeur dans la signature Authenticode de l'installateur Windows


class ErreurOllama(RuntimeError):
    pass


class Ollama:
    def __init__(self, url=None, ouvrir=urllib.request.urlopen):
        self.url = (url or os.environ.get("OLLAMA_URL") or URL_PAR_DEFAUT).rstrip("/")
        self.ouvrir = ouvrir

    def _requete(self, chemin, corps=None, delai=5, methode=None):
        donnees = None if corps is None else json.dumps(corps).encode("utf-8")
        req = urllib.request.Request(self.url + chemin, data=donnees, method=methode, headers={"Content-Type": "application/json"})
        return self.ouvrir(req, timeout=delai)

    def json(self, chemin, corps=None, delai=5, methode=None):
        try:
            with self._requete(chemin, corps, delai, methode) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except (OSError, ValueError, urllib.error.URLError) as e:
            raise ErreurOllama(_t("Ollama ne répond pas ({}) : {}").format(self.url, e)) from e

    def actif(self):
        try:
            self.json("/api/version", delai=2)
            return True
        except ErreurOllama:
            return False

    def version(self):
        return self.json("/api/version", delai=3).get("version", "")

    def installes(self):
        """{nom: {"digest": ..., "taille": octets}}"""
        return {m["name"]: {"digest": m.get("digest", ""), "taille": m.get("size", 0)} for m in self.json("/api/tags").get("models", []) if m.get("name")}

    def capacites(self, modele):
        """Liste des capacités annoncées (« tools », « vision »…) ou None si Ollama ne le dit pas (ancienne version)."""
        try:
            c = self.json("/api/show", {"model": modele}, 8).get("capabilities")
        except ErreurOllama:
            return None
        return c if isinstance(c, list) else None

    def telecharger(self, modele, progression=None):
        """Télécharge un modèle (reprise automatique par Ollama). progression(texte, fait, total) est appelée pendant le téléchargement."""
        horsligne.exiger_en_ligne(_t("télécharger un modèle"))
        try:
            with self._requete("/api/pull", {"model": modele, "stream": True}, delai=3600) as r:
                for brut in r:
                    try:
                        e = json.loads(brut.decode("utf-8"))
                    except ValueError:
                        continue
                    if e.get("error"):
                        raise ErreurOllama(e["error"])
                    if progression:
                        progression(e.get("status", ""), e.get("completed") or 0, e.get("total") or 0)
        except (OSError, urllib.error.URLError) as e:
            raise ErreurOllama(_t("Téléchargement interrompu : {}").format(e)) from e

    def supprimer(self, modele):
        self.json("/api/delete", {"model": modele}, methode="DELETE")


# ---------------------------------------------------------------- installation d'Ollama

def trouver_executable(systeme, env=None, quelle=shutil.which):
    env = os.environ if env is None else env
    trouve = quelle("ollama")
    if trouve:
        return trouve
    candidats = []
    if systeme == "windows":
        candidats = [Path(env.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe", Path(env.get("ProgramFiles", "")) / "Ollama" / "ollama.exe"]
    elif systeme == "macos":
        candidats = [Path("/Applications/Ollama.app/Contents/Resources/ollama"), Path("/usr/local/bin/ollama"), Path("/opt/homebrew/bin/ollama")]
    else:
        candidats = [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]
    for c in candidats:
        if c.is_file():
            return str(c)
    return ""


def variables_serveur(profil, dossier_modeles=""):
    """Réglages d'Ollama adaptés à CETTE machine (au lieu de ceux d'une carte précise) : attention rapide, cache de contexte compressé, déchargement après 5 min."""
    v = {"OLLAMA_KEEP_ALIVE": "5m"}
    if not profil.sans_gpu():
        v["OLLAMA_FLASH_ATTENTION"] = "1"
        v["OLLAMA_KV_CACHE_TYPE"] = "q8_0"
    if dossier_modeles:
        v["OLLAMA_MODELS"] = str(dossier_modeles)
    return v


def demarrer_serveur(exe, variables, systeme, lanceur=subprocess.Popen):
    env = dict(os.environ)
    env.update(variables)
    options = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "env": env}
    if systeme == "windows":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        options["start_new_session"] = True
    return lanceur([exe, "serve"], **options)


def telecharger_fichier(url, destination, progression=None, ouvrir=urllib.request.urlopen, taille_min=50_000_000):
    """Télécharge `url` vers `destination` (fichier .part renommé à la fin, reprise si interrompu). HTTPS obligatoire."""
    if not url.startswith("https://"):
        raise ErreurOllama(_t("téléchargement refusé : adresse non sécurisée"))
    horsligne.garde(url)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    deja = part.stat().st_size if part.is_file() else 0
    req = urllib.request.Request(url, headers={"Range": "bytes={}-".format(deja)} if deja else {})
    try:
        with ouvrir(req, timeout=60) as r:
            reprise = deja and getattr(r, "status", 200) == 206
            total = int(r.headers.get("Content-Length") or 0) + (deja if reprise else 0)
            with open(part, "ab" if reprise else "wb") as f:
                fait = deja if reprise else 0
                while True:
                    bloc = r.read(1 << 20)
                    if not bloc:
                        break
                    f.write(bloc)
                    fait += len(bloc)
                    if progression:
                        progression(_t("téléchargement"), fait, total)
    except (OSError, urllib.error.URLError) as e:
        raise ErreurOllama(_t("téléchargement interrompu (relance la commande : il reprend où il s'est arrêté) : {}").format(e)) from e
    if part.stat().st_size < taille_min:
        part.unlink(missing_ok=True)
        raise ErreurOllama(_t("fichier téléchargé trop petit : abandon"))
    part.replace(destination)
    return destination


def verifier_signature_windows(chemin, lanceur):
    """(ok, sujet) : l'installateur doit porter une signature Authenticode valide dont le sujet contient « Ollama »."""
    sortie = lanceur(["powershell", "-NoProfile", "-Command",
                      "$s = Get-AuthenticodeSignature -LiteralPath '{}'; \"$($s.Status)|$($s.SignerCertificate.Subject)\"".format(str(chemin).replace("'", "''"))], 30)
    statut, _, sujet = (sortie or "").strip().partition("|")
    return statut == "Valid" and EDITEUR_ATTENDU in sujet.lower(), sujet


def installer_windows(dossier_cache, progression=None, ouvrir=urllib.request.urlopen, lanceur_sortie=None, executer=subprocess.run, taille_min=50_000_000):
    """Télécharge, VÉRIFIE LA SIGNATURE, puis installe Ollama en silence (pour l'utilisateur courant, sans droits administrateur)."""
    from .machine import lancer
    lanceur_sortie = lanceur_sortie or lancer
    installateur = telecharger_fichier(URL_TELECHARGEMENT_WINDOWS, Path(dossier_cache) / "OllamaSetup.exe", progression, ouvrir, taille_min)
    ok, sujet = verifier_signature_windows(installateur, lanceur_sortie)
    if not ok:
        installateur.unlink(missing_ok=True)
        raise ErreurOllama(_t("la signature de l'installateur d'Ollama n'est pas valide ({}) : installation annulée").format(sujet or "aucune signature"))
    r = executer([str(installateur), "/SILENT"], timeout=900)
    if getattr(r, "returncode", 0) != 0:
        raise ErreurOllama(_t("l'installation d'Ollama a échoué (code {})").format(r.returncode))
    exe = trouver_executable("windows")
    if not exe:
        raise ErreurOllama(_t("Ollama est installé mais introuvable : relance Lutin dans une nouvelle fenêtre"))
    return exe
