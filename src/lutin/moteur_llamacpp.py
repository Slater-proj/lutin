"""llama.cpp (`llama-server`) et les serveurs externes compatibles OpenAI (LM Studio, vLLM, Strata…).

`MoteurLlamaCpp` sait aussi s'occuper du serveur lui-même, tant qu'on ne lui donne pas d'adresse :
  - l'installer : il télécharge le programme officiel (les binaires publiés sur GitHub par le projet llama.cpp) adapté à la machine — CUDA pour une carte NVIDIA, Vulkan pour les autres cartes,
    processeur sinon, Metal sur Mac — et le range dans le dossier de données de Lutin (rien n'est installé ailleurs, pas de droits administrateur) ;
  - le démarrer et l'arrêter : un serveur par modèle ; il est démarré à la demande avec le modèle choisi (et redémarré si le modèle change) ;
  - ses modèles : des fichiers .gguf rangés dans un dossier ; Lutin les cherche sur Hugging Face, les télécharge et les supprime.
Avec une adresse (llama-server lancé à part, par exemple dans un autre conteneur), Lutin s'y connecte et ne gère plus rien.
`MoteurExterne` est le même principe pour n'importe quel autre serveur compatible OpenAI : une adresse et, si besoin, une clé."""
import json
import os
import re
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import moteurs
from .i18n import t as _t
from .moteur_openai import MoteurOpenAI

API_RELEASES = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=8"
API_HF = "https://huggingface.co/api/models"
PORT_DEFAUT = 8089
CTX_DEFAUT = 8192
DEMARRAGE_MAX_S = 180
RE_REPO = re.compile(r"^[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*$")
RE_FICHIER = re.compile(r"^[\w][\w./+-]*\.gguf$", re.I)
RE_MORCEAU = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)          # modèle coupé en plusieurs fichiers : pas géré
SERVEUR = {"proc": None, "modele": "", "ctx": 0, "verrou": threading.RLock()}


class ErreurMoteur(ValueError):
    pass


# --------------------------------------------------------------------------- réglages des moteurs (donnees/moteurs.json)

def _chemin_config():
    d = moteurs.CONTEXTE["donnees"]()
    return (Path(d) / "moteurs.json") if d else None


def lire_config():
    f = _chemin_config()
    try:
        donnees = json.loads(f.read_text(encoding="utf-8")) if f and f.is_file() else {}
    except (OSError, ValueError):
        donnees = {}
    return donnees if isinstance(donnees, dict) else {}


def ecrire_config(config):
    f = _chemin_config()
    if f is None:
        raise ErreurMoteur(_t("Dossier de données inconnu."))
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)          # il peut contenir une clé d'accès
    except OSError:
        pass
    tmp.replace(f)


def normaliser_adresse(adresse):
    """« http://hote:8080 » -> « http://hote:8080/v1 » ; « » reste « ». Lève ErreurMoteur si l'adresse n'est pas http(s)."""
    adresse = str(adresse or "").strip().rstrip("/")
    if not adresse:
        return ""
    if not re.match(r"^https?://[^\s/]+", adresse, re.I):
        raise ErreurMoteur(_t("L'adresse doit commencer par http:// ou https://."))
    return adresse if re.search(r"/v\d+$", adresse) else adresse + "/v1"


def regler(moteur, adresse=None, cle=None, **autres):
    """Enregistre l'adresse (et la clé) d'un moteur compatible OpenAI. Une adresse vide remet llama.cpp en mode « géré par Lutin »."""
    config = lire_config()
    c = config.setdefault(moteur, {})
    if adresse is not None:
        c["url"] = normaliser_adresse(adresse)
    if cle is not None:
        c["cle"] = str(cle).strip()
    for k, v in autres.items():
        if v is not None:
            c[k] = v
    ecrire_config(config)


def vue_reglages(moteur):
    c = lire_config().get(moteur, {})
    return {"url": c.get("url", ""), "cle_definie": bool(c.get("cle")), "variante": c.get("variante", "auto")}


# --------------------------------------------------------------------------- choix du programme à télécharger

def variante_auto(profil, systeme):
    """cuda (carte NVIDIA), vulkan (autre vraie carte graphique), cpu (aucune : les puces graphiques intégrées au processeur ne comptent pas), metal (Mac)."""
    if systeme == "macos":
        return "metal"
    gpus = [g for g in (getattr(profil, "gpus", None) or []) if getattr(g, "vram_go", 0) >= 3]
    if any(getattr(g, "fabricant", "") == "nvidia" for g in gpus):
        return "cuda"
    return "vulkan" if any(getattr(g, "fabricant", "") in ("amd", "intel") for g in gpus) else "cpu"


def noms_attendus(systeme, arch, variante):
    """Les motifs (expressions régulières) du ou des fichiers à télécharger, du programme puis des bibliothèques d'exécution éventuelles."""
    x64 = arch in ("x86_64", "amd64", "x64")
    if systeme == "windows":
        if not x64:
            return [r"^llama-b\d+-bin-win-cpu-arm64\.zip$"]
        if variante == "cuda":
            return [r"^llama-b\d+-bin-win-cuda-12\.\d+-x64\.zip$", r"^cudart-llama-bin-win-cuda-12\.\d+-x64\.zip$"]
        if variante == "vulkan":
            return [r"^llama-b\d+-bin-win-vulkan-x64\.zip$"]
        return [r"^llama-b\d+-bin-win-cpu-x64\.zip$"]
    if systeme == "linux":
        if not x64:
            return [r"^llama-b\d+-bin-ubuntu-arm64\.tar\.gz$"]
        if variante == "cuda":
            return [r"^llama-b\d+-bin-ubuntu-cuda-12\.\d+-x64\.tar\.gz$", r"^cudart-llama-b\d+-bin-ubuntu-cuda-12\.\d+-x64\.tar\.gz$"]
        if variante == "vulkan":
            return [r"^llama-b\d+-bin-ubuntu-vulkan-x64\.tar\.gz$"]
        return [r"^llama-b\d+-bin-ubuntu-x64\.tar\.gz$"]
    if systeme == "macos":
        return [r"^llama-b\d+-bin-macos-arm64\.tar\.gz$"] if not x64 else [r"^llama-b\d+-bin-macos-x64\.tar\.gz$"]
    return []


def choisir_fichiers(releases, systeme, arch, variante):
    """(étiquette, [assets]) : la plus récente version qui a tous les fichiers voulus, ou None."""
    motifs = noms_attendus(systeme, arch, variante)
    if not motifs:
        return None
    for r in releases or []:
        assets = r.get("assets") or []
        choisis = []
        for m in motifs:
            trouves = sorted((a for a in assets if re.match(m, a.get("name", ""))), key=lambda a: a["name"])
            if not trouves:
                break
            choisis.append(trouves[0])
        else:
            return r.get("tag_name", ""), choisis
    return None


def extraire(archive, destination):
    """Décompresse un .zip ou un .tar.gz dans `destination`, en refusant tout fichier qui sortirait du dossier."""
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    def sur(nom):
        cible = (destination / nom).resolve()
        if destination != cible and destination not in cible.parents:
            raise ErreurMoteur(_t("Archive refusée : un fichier sortirait du dossier d'installation."))
    archive = Path(archive)
    if archive.name.lower().endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for nom in z.namelist():
                sur(nom)
            z.extractall(destination)
    else:
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                sur(m.name)
                if m.issym() or m.islnk():
                    sur(os.path.join(os.path.dirname(m.name), m.linkname))
            t.extractall(destination)


def trouver_serveur_dans(dossier):
    nom = "llama-server.exe" if os.name == "nt" else "llama-server"
    for f in sorted(Path(dossier).rglob(nom)):
        return f
    return None


# --------------------------------------------------------------------------- le moteur

class MoteurLlamaCpp(MoteurOpenAI):
    id = moteurs.LLAMACPP
    nom = "llama.cpp"
    gere_modeles = True
    adresse_modifiable = True

    @property
    def description(self):
        return _t("Le moteur de référence sur lequel Ollama est construit, utilisé directement : llama-server, avec son interface compatible OpenAI. Lutin peut l'installer, le démarrer et télécharger ses modèles (fichiers GGUF), ou se connecter à un llama-server déjà lancé.")

    @property
    def points_forts(self):
        return (_t("Un peu plus rapide qu'Ollama à l'écriture, surtout avec les modèles à experts (quelques % à une vingtaine de %, d'après des mesures publiques, à vérifier sur ta machine)."),
                _t("Reçoit les nouveaux modèles et les nouvelles optimisations avant Ollama."),
                _t("Tous les réglages sont accessibles (mémoire, répartition carte graphique / processeur)."),
                _t("Léger : un seul programme, sans service en arrière-plan."))

    @property
    def points_faibles(self):
        return (_t("Un seul modèle à la fois, rechargé quand tu en changes."),
                _t("Les modèles sont des fichiers GGUF à choisir (quantification) : moins guidé que la bibliothèque d'Ollama."),
                _t("Le premier chargement d'un modèle est plus long qu'avec le cache d'Ollama."))

    # -- où est le serveur
    def config(self):
        return lire_config().get(self.id, {})

    def externe(self):
        return bool(self.config().get("url"))

    def adresse(self):
        if self.externe():
            return self.config()["url"]
        return "http://127.0.0.1:%d/v1" % int(self.config().get("port") or PORT_DEFAUT)

    def cle(self):
        return self.config().get("cle", "")

    def dossier(self):
        d = moteurs.CONTEXTE["donnees"]()
        return (Path(d) / "moteurs" / "llamacpp") if d else None

    def dossier_modeles(self):
        personnalise = self.config().get("dossier_modeles")
        return Path(personnalise) if personnalise else (self.dossier() / "modeles")

    def serveur_installe(self):
        d = self.dossier()
        installe = trouver_serveur_dans(d / "bin") if d and (d / "bin").is_dir() else None
        return installe

    def serveur_pret(self):
        """Le programme à lancer : celui de Lutin, ou un llama-server trouvé dans le PATH."""
        return self.serveur_installe() or (Path(shutil.which("llama-server")) if shutil.which("llama-server") else None)

    def version(self):
        d = self.dossier()
        try:
            return (d / "version.txt").read_text(encoding="utf-8").strip() if d else ""
        except OSError:
            return ""

    # -- interface de discussion
    def actif(self):
        if self.externe():
            return super().actif()
        return self.serveur_pret() is not None          # géré : le serveur démarre à la demande

    def modeles(self):
        if self.externe():
            return super().modeles()
        dossier = self.dossier_modeles()
        noms, tailles = [], {}
        if dossier.is_dir():
            for f in sorted(dossier.rglob("*.gguf")):
                if "mmproj" in f.name.lower():
                    continue
                nom = f.relative_to(dossier).with_suffix("").as_posix()
                noms.append(nom)
                tailles[nom] = f.stat().st_size
        return {"actif": self.serveur_pret() is not None, "installes": noms, "tailles": tailles}

    def en_memoire(self, modele):
        if self.externe():
            return super().en_memoire(modele)
        with SERVEUR["verrou"]:
            p = SERVEUR["proc"]
            if p is not None and p.poll() is None and SERVEUR["modele"] == modele:
                return {"taille": 0, "vram": 0}
        return None

    def _assurer(self, corps):
        """Géré : le serveur tourne avec le modèle voulu et la fenêtre de contexte voulue (il est démarré ou redémarré au besoin)."""
        if self.externe():
            return
        modele = corps.get("model", "")
        ctx = int((corps.get("options") or {}).get("num_ctx") or CTX_DEFAUT)
        self.demarrer(modele, ctx)

    def chat(self, corps, delai=60):
        self._assurer(corps)
        return super().chat(corps, delai)

    def chat_flux(self, corps, delai=900):
        self._assurer(corps)
        return super().chat_flux(corps, delai)

    # -- le serveur géré
    def demarrer(self, modele, ctx=CTX_DEFAUT, attente=DEMARRAGE_MAX_S):
        exe = self.serveur_pret()
        if exe is None:
            raise ErreurMoteur(_t("llama.cpp n'est pas installé : Réglages > Moteur > Installer."))
        fichier = self._fichier_modele(modele)
        with SERVEUR["verrou"]:
            p = SERVEUR["proc"]
            if p is not None and p.poll() is None and SERVEUR["modele"] == modele and abs(SERVEUR["ctx"] - ctx) < 1024:
                return
            self.arreter()
            port = int(self.config().get("port") or PORT_DEFAUT)
            variante = (self.config().get("variante_installee") or "cpu")
            commande = [str(exe), "-m", str(fichier), "--host", "127.0.0.1", "--port", str(port), "-c", str(ctx), "--jinja"]
            if variante in ("cuda", "vulkan", "metal"):
                commande += ["-ngl", "99"]          # tout le modèle sur la carte (le reste va sur le processeur s'il ne tient pas : llama.cpp l'ajuste)
            journal = self.dossier() / "serveur.log"
            journal.parent.mkdir(parents=True, exist_ok=True)
            sortie = open(journal, "wb")
            try:
                SERVEUR["proc"] = subprocess.Popen(commande, stdout=sortie, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(Path(exe).parent))
            except OSError as e:
                raise ErreurMoteur(_t("Impossible de lancer llama-server : {}").format(e))
            finally:
                sortie.close()          # le processus garde sa propre copie du fichier journal
            SERVEUR.update({"modele": modele, "ctx": ctx})
        fin = time.time() + attente
        while time.time() < fin:
            if SERVEUR["proc"].poll() is not None:
                raise ErreurMoteur(_t("llama-server s'est arrêté au démarrage : {}").format(self._fin_du_journal()))
            if MoteurOpenAI.actif(self):
                return
            time.sleep(0.5)
        self.arreter()
        raise ErreurMoteur(_t("llama-server ne répond pas après {} s : {}").format(attente, self._fin_du_journal()))

    def _fin_du_journal(self):
        try:
            return " ".join((self.dossier() / "serveur.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:])[-300:]
        except OSError:
            return ""

    def arreter(self):
        with SERVEUR["verrou"]:
            p = SERVEUR["proc"]
            SERVEUR.update({"proc": None, "modele": "", "ctx": 0})
        if p is not None and p.poll() is None:
            try:
                p.terminate()
                p.wait(8)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    p.kill()
                except OSError:
                    pass

    def _fichier_modele(self, modele):
        dossier = self.dossier_modeles()
        f = (dossier / (str(modele) + ".gguf")).resolve()
        if dossier.resolve() not in f.parents or not f.is_file():
            raise ErreurMoteur(_t("Modèle introuvable dans {} : « {} ».").format(dossier, modele))
        return f

    # -- ce que la page peut faire
    def statut(self):
        if self.externe():
            actif = MoteurOpenAI.actif(self)
            return {"installe": True, "actif": actif, "version": "", "detail": _t("Connecté à {}").format(self.adresse()) if actif else _t("Le serveur {} ne répond pas.").format(self.adresse()), "mode": "externe"}
        exe = self.serveur_installe()
        with SERVEUR["verrou"]:
            p = SERVEUR["proc"]
            tourne = p is not None and p.poll() is None
            modele = SERVEUR["modele"] if tourne else ""
        detail = _t("Serveur démarré avec « {} ».").format(modele) if tourne else (_t("Installé : il démarre à la demande.") if exe or self.serveur_pret() else _t("Pas installé."))
        return {"installe": self.serveur_pret() is not None, "actif": tourne, "version": self.version(), "detail": detail, "mode": "gere", "installe_par_lutin": exe is not None}

    def actions(self):
        systeme = _systeme()
        vide = _t("Sans objet avec un serveur externe : l'adresse est réglée ci-dessous.")
        if self.externe():
            return {a: {"possible": False, "raison": vide} for a in moteurs.ACTIONS}
        if moteurs.CONTEXTE["en_docker"]():
            raison = _t("Dans Docker, llama-server se lance à côté de Lutin (par exemple l'image ghcr.io/ggml-org/llama.cpp:server) : indique son adresse ci-dessous.")
            return {a: {"possible": False, "raison": raison} for a in moteurs.ACTIONS}
        exe = self.serveur_installe()
        par_lutin = exe is not None
        installer = {"possible": not par_lutin and systeme in ("windows", "linux", "macos") and not moteurs.CONTEXTE["hors_ligne"](),
                     "raison": _t("Télécharge le programme officiel adapté à cette machine (de 25 Mo à environ 700 Mo selon la carte graphique).") if not par_lutin else _t("Déjà installé.")}
        if moteurs.CONTEXTE["hors_ligne"]():
            installer["raison"] = _t("Mode hors ligne : aucun téléchargement.")
        elif systeme not in ("windows", "linux", "macos"):
            installer["raison"] = _t("Système non pris en charge.")
        hors_lutin = self.serveur_pret() is not None and not par_lutin
        sans = _t("Pas installé par Lutin.") if hors_lutin else _t("Pas installé.")
        with SERVEUR["verrou"]:
            tourne = SERVEUR["proc"] is not None and SERVEUR["proc"].poll() is None
        return {"installer": installer,
                "desinstaller": {"possible": par_lutin, "raison": _t("Supprime le programme (tes modèles restent).") if par_lutin else sans},
                "reinstaller": {"possible": par_lutin and not moteurs.CONTEXTE["hors_ligne"](), "raison": _t("Télécharge de nouveau la dernière version, en gardant tes modèles.") if par_lutin else sans},
                "demarrer": {"possible": False, "raison": _t("Il démarre tout seul quand tu discutes avec un modèle.")},
                "arreter": {"possible": tourne, "raison": _t("Arrête le serveur et libère la mémoire.") if tourne else _t("Il n'est pas démarré.")}}

    def faire(self, action, progression):
        if action in ("installer", "reinstaller"):
            return self.installer(progression, reinstaller=action == "reinstaller")
        if action == "desinstaller":
            return self.desinstaller()
        if action == "arreter":
            return self.arreter()
        raise ErreurMoteur(_t("Action impossible avec ce moteur."))

    def installer(self, progression, reinstaller=False, http_json=None, telecharger=None):
        if moteurs.CONTEXTE["en_docker"]():
            raise ErreurMoteur(_t("Dans Docker, llama-server se lance à côté de Lutin : indique son adresse."))
        if moteurs.CONTEXTE["hors_ligne"]():
            raise ErreurMoteur(_t("Mode hors ligne : aucun téléchargement."))
        import platform
        systeme, arch = _systeme(), platform.machine().lower()
        config = lire_config()
        voulue = config.get(self.id, {}).get("variante", "auto")
        variante = voulue if voulue in ("cuda", "vulkan", "cpu", "metal") else variante_auto(moteurs.CONTEXTE["profil"](), systeme)
        progression(_t("Recherche de la dernière version…"), 0, 0)
        try:
            releases = (http_json or _http_json)(API_RELEASES)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ErreurMoteur(_t("GitHub ne répond pas : {}").format(e))
        choix = choisir_fichiers(releases, systeme, arch, variante)
        if choix is None and variante != "cpu":
            variante = "cpu"
            choix = choisir_fichiers(releases, systeme, arch, variante)
        if choix is None:
            raise ErreurMoteur(_t("Aucun programme llama.cpp publié pour ce système ({} {}). Installe-le à la main : https://github.com/ggml-org/llama.cpp/releases").format(systeme, arch))
        etiquette, assets = choix
        base = self.dossier()
        telechargement = base / "telechargement"
        neuf = base / "bin.neuf"
        for d in (telechargement, neuf):
            shutil.rmtree(d, ignore_errors=True)
        total_octets = sum(int(a.get("size") or 0) for a in assets)
        deja = 0
        from . import ollama_client
        for a in assets:
            progression(_t("Téléchargement de {}").format(a["name"]), deja, total_octets)
            url = a["browser_download_url"]
            try:
                f = (telecharger or ollama_client.telecharger_fichier)(url, telechargement / a["name"], lambda t, fait, tot, d=deja: progression(_t("Téléchargement de {}").format(a["name"]), d + fait, total_octets), taille_min=100_000)
            except (RuntimeError, OSError) as e:
                raise ErreurMoteur(str(e))
            self._verifier_empreinte(f, a)
            deja += int(a.get("size") or 0)
            progression(_t("Installation…"), deja, total_octets)
            extraire(f, neuf)
        exe = trouver_serveur_dans(neuf)
        if exe is None:
            shutil.rmtree(neuf, ignore_errors=True)
            raise ErreurMoteur(_t("llama-server est introuvable dans l'archive téléchargée."))
        if os.name != "nt":
            for f in neuf.rglob("llama-*"):
                try:
                    f.chmod(f.stat().st_mode | 0o111)
                except OSError:
                    pass
        self.arreter()
        shutil.rmtree(base / "bin", ignore_errors=True)
        neuf.replace(base / "bin")
        shutil.rmtree(telechargement, ignore_errors=True)
        (base / "version.txt").write_text("{} ({})".format(etiquette, variante), encoding="utf-8")
        config = lire_config()
        config.setdefault(self.id, {})["variante_installee"] = variante
        ecrire_config(config)
        progression(_t("Installé : {} ({}).").format(etiquette, variante), 1, 1)

    @staticmethod
    def _verifier_empreinte(fichier, asset):
        """GitHub publie l'empreinte sha256 de chaque fichier : on la vérifie quand elle est donnée."""
        attendu = str(asset.get("digest") or "")
        if not attendu.startswith("sha256:"):
            return
        import hashlib
        h = hashlib.sha256()
        with open(fichier, "rb") as f:
            for bloc in iter(lambda: f.read(1 << 20), b""):
                h.update(bloc)
        if h.hexdigest() != attendu[7:]:
            Path(fichier).unlink(missing_ok=True)
            raise ErreurMoteur(_t("Le fichier téléchargé est corrompu (empreinte différente de celle publiée) : réessaie."))

    def desinstaller(self):
        self.arreter()
        base = self.dossier()
        if base is None or not (base / "bin").is_dir():
            raise ErreurMoteur(_t("llama.cpp n'a pas été installé par Lutin : il n'y a rien à supprimer ici."))
        shutil.rmtree(base / "bin", ignore_errors=True)
        (base / "version.txt").unlink(missing_ok=True)

    # -- les modèles (fichiers GGUF)
    def telechargeable(self):
        if self.externe():
            return {"possible": False, "raison": _t("Un serveur externe gère ses modèles lui-même."), "genre": "aucun"}
        if moteurs.CONTEXTE["hors_ligne"]():
            return {"possible": False, "raison": _t("Mode hors ligne : aucun téléchargement."), "genre": "huggingface"}
        return {"possible": True, "raison": _t("Les modèles se trouvent sur Hugging Face, au format GGUF."), "genre": "huggingface"}

    def chercher_modeles(self, terme, http_json=None):
        """Les dépôts GGUF de Hugging Face qui correspondent (les plus téléchargés d'abord)."""
        terme = re.sub(r"[^\w.\- ]", "", str(terme or ""))[:60].strip()
        if not terme:
            raise ErreurMoteur(_t("Écris le nom d'un modèle à chercher (par exemple qwen3 ou gemma)."))
        url = API_HF + "?" + urllib.parse.urlencode({"search": terme, "filter": "gguf", "sort": "downloads", "direction": "-1", "limit": "15"})
        try:
            lus = (http_json or _http_json)(url)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ErreurMoteur(_t("Hugging Face ne répond pas : {}").format(e))
        return [{"id": m.get("id", ""), "telechargements": int(m.get("downloads") or 0), "likes": int(m.get("likes") or 0)} for m in lus if RE_REPO.match(str(m.get("id", "")))]

    def fichiers_du_depot(self, repo, http_json=None):
        """Les fichiers .gguf d'un dépôt (hors morceaux d'un modèle coupé et hors projecteurs d'images), avec leur taille."""
        if not RE_REPO.match(str(repo or "")):
            raise ErreurMoteur(_t("Nom de dépôt invalide (attendu : auteur/nom)."))
        try:
            lus = (http_json or _http_json)("{}/{}/tree/main".format(API_HF, repo))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ErreurMoteur(_t("Hugging Face ne répond pas : {}").format(e))
        sortie = []
        for f in lus:
            chemin = str(f.get("path", ""))
            if f.get("type") == "file" and RE_FICHIER.match(chemin) and not RE_MORCEAU.search(chemin) and "mmproj" not in chemin.lower():
                sortie.append({"fichier": chemin, "taille": int((f.get("lfs") or {}).get("size") or f.get("size") or 0)})
        return sorted(sortie, key=lambda x: x["taille"])

    def telecharger_modele(self, repo, fichier, progression, telecharger=None):
        if not self.telechargeable()["possible"]:
            raise ErreurMoteur(self.telechargeable()["raison"])
        if not RE_REPO.match(str(repo or "")) or not RE_FICHIER.match(str(fichier or "")) or ".." in str(fichier):
            raise ErreurMoteur(_t("Dépôt ou fichier invalide."))
        from . import ollama_client
        nom = fichier.replace("/", "_")
        destination = self.dossier_modeles() / nom
        url = "https://huggingface.co/{}/resolve/main/{}".format(repo, urllib.parse.quote(fichier))
        try:
            (telecharger or ollama_client.telecharger_fichier)(url, destination, progression, taille_min=1_000_000)
        except (RuntimeError, OSError) as e:
            raise ErreurMoteur(str(e))
        return destination.with_suffix("").name

    def supprimer_modele(self, nom):
        f = self._fichier_modele(nom)
        with SERVEUR["verrou"]:
            if SERVEUR["modele"] == nom:
                self.arreter()
        f.unlink()


class MoteurExterne(MoteurOpenAI):
    """Un autre serveur compatible OpenAI (LM Studio, vLLM, Strata, un llama-server distant…) : une adresse et, si besoin, une clé. Lutin n'installe rien, il s'y connecte."""
    id = moteurs.OPENAI
    nom = "Serveur compatible OpenAI"
    adresse_modifiable = True

    @property
    def description(self):
        return _t("Tout serveur qui parle l'interface OpenAI : LM Studio, vLLM, Strata, un llama-server sur un autre ordinateur… Tu donnes son adresse ; il gère ses modèles lui-même.")

    @property
    def points_forts(self):
        return (_t("Universel : s'adapte à n'importe quel serveur de ce genre, sur cette machine ou sur le réseau."),
                _t("Lutin n'installe ni ne démarre rien : le serveur reste maître de ses réglages."))

    @property
    def points_faibles(self):
        return (_t("Lutin ne peut ni installer, ni démarrer, ni mettre à jour ce serveur, ni lui télécharger de modèle."),
                _t("Selon le serveur, les appels d'outils ou les images peuvent ne pas fonctionner."))

    def config(self):
        return lire_config().get(self.id, {})

    def adresse(self):
        return self.config().get("url", "")

    def cle(self):
        return self.config().get("cle", "")

    def statut(self):
        if not self.adresse():
            return {"installe": True, "actif": False, "version": "", "detail": _t("Aucune adresse : indique celle du serveur ci-dessous."), "mode": "externe"}
        actif = MoteurOpenAI.actif(self)
        return {"installe": True, "actif": actif, "version": "", "detail": _t("Connecté à {}").format(self.adresse()) if actif else _t("Le serveur {} ne répond pas.").format(self.adresse()), "mode": "externe"}

    def actions(self):
        raison = _t("Sans objet : ce serveur n'est pas géré par Lutin.")
        return {a: {"possible": False, "raison": raison} for a in moteurs.ACTIONS}

    def telechargeable(self):
        return {"possible": False, "raison": _t("Un serveur externe gère ses modèles lui-même."), "genre": "aucun"}


def _systeme():
    import sys
    return "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux")


def _http_json(url, delai=20):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Lutin"})
    with urllib.request.urlopen(req, timeout=delai) as r:
        return json.loads(r.read().decode("utf-8"))
