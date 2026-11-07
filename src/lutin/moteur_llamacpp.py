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
CACHE_PARTAGE = {}
API_HF = "https://huggingface.co/api/models"
PORT_DEFAUT = 8089
CTX_DEFAUT = 8192
DEMARRAGE_MAX_S = 180
RE_REPO = re.compile(r"^[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*$")
RE_FICHIER = re.compile(r"^[\w][\w./+-]*\.gguf$", re.I)
RE_MORCEAU = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)          # modèle coupé en plusieurs fichiers : pas géré
SERVEUR = {"proc": None, "modele": "", "ctx": 0, "noms": (), "verrou": threading.RLock(), "actifs": 0}          # actifs : réponses en cours (on ne redémarre jamais le serveur sous elles)
API_VERSION = "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/"
RE_VERSION = re.compile(r"^b\d{1,7}$")
RE_NOM_PRESET = re.compile(r"^[^\[\]\r\n=#;]{1,200}$")
MOTS_EMBEDDING = ("embed", "bge-", "bge:", "e5-", "gte-", "minilm", "arctic-embed")          # les modèles qui vectorisent au lieu de discuter (sans eux, un routeur les chargerait comme des modèles de conversation)
MODELES_MAX_DEFAUT = 2
ROUTEUR = "(routeur)"


class ErreurMoteur(ValueError):
    pass


PAQUETS_DEBIAN = {"libgomp.so.1": "libgomp1", "libstdc++.so.6": "libstdc++6", "libcurl.so.4": "libcurl4", "libvulkan.so.1": "libvulkan1", "libgcc_s.so.1": "libgcc-s1"}


def aide_bibliotheque(texte):
    """Le serveur a répondu « error while loading shared libraries: X » : le paquet Debian/Ubuntu qui la fournit, quand on le connaît."""
    m = re.search(r"error while loading shared libraries: (\S+?):", str(texte))
    if not m:
        return ""
    paquet = PAQUETS_DEBIAN.get(m.group(1))
    return _t(" Bibliothèque manquante : {}.").format(m.group(1)) + (_t(" Sous Debian ou Ubuntu : apt install {} (dans Docker : à ajouter à l'image).").format(paquet) if paquet else "")


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


def regler_avance(moteur, donnees):
    """Les réglages propres à llama.cpp géré par Lutin : mode routeur (plusieurs modèles sans redémarrer le serveur), nombre de modèles gardés en mémoire, couches d'experts laissées au processeur
    (modèles « à experts »), version épinglée. Chaque valeur est contrôlée ; une valeur vide remet le réglage par défaut. Le serveur est arrêté pour que le changement compte au prochain message."""
    mo = moteurs.MOTEURS.get(moteur)
    if not isinstance(mo, MoteurLlamaCpp):
        return False
    config = lire_config()
    c = config.setdefault(moteur, {})
    if "routeur" in donnees:
        if donnees["routeur"] and not mo.routeur_possible():
            raise ErreurMoteur(_t("Ce llama-server ne sait pas faire le mode routeur : mets-le à jour (Réglages > Moteur > Mettre à jour)."))
        c["routeur"] = bool(donnees["routeur"])
    if "modeles_max" in donnees:
        try:
            n = int(donnees["modeles_max"] or MODELES_MAX_DEFAUT)
        except (TypeError, ValueError):
            raise ErreurMoteur(_t("Nombre de modèles invalide."))
        if not 1 <= n <= 8:
            raise ErreurMoteur(_t("Entre 1 et 8 modèles en mémoire."))
        c["modeles_max"] = n
    if "n_cpu_moe" in donnees:
        try:
            n = int(donnees["n_cpu_moe"] or 0)
        except (TypeError, ValueError):
            raise ErreurMoteur(_t("Nombre de couches invalide."))
        if not 0 <= n <= 512:
            raise ErreurMoteur(_t("Entre 0 et 512 couches."))
        if n:
            c["n_cpu_moe"] = n
        else:
            c.pop("n_cpu_moe", None)
    if "version_epinglee" in donnees:
        v = str(donnees["version_epinglee"] or "").strip().lower()
        if v and not RE_VERSION.match(v):
            raise ErreurMoteur(_t("Une version de llama.cpp s'écrit « b » suivi de son numéro, par exemple b6500."))
        if v:
            c["version_epinglee"] = v
        else:
            c.pop("version_epinglee", None)
    ecrire_config(config)
    mo.arreter()
    return True


def est_embedding(nom):
    """Ce modèle vectorise-t-il (recherche par le sens) au lieu de discuter ? D'après son nom."""
    n = str(nom).lower()
    return any(m in n for m in MOTS_EMBEDDING)


def texte_preset(modeles, ctx, reglages):
    """Le fichier de préréglages du mode routeur (format INI de llama-server) : une section par modèle, avec son fichier, son éventuel projecteur d'images et ses réglages.
    `modeles` : [(nom, fichier, projecteur ou None)] ; `reglages` : {fils, n_cpu_moe, ngl}."""
    lignes = ["version = 1", "", "[*]", "c = {}".format(int(ctx))]
    if reglages.get("fils"):
        lignes.append("threads = {}".format(int(reglages["fils"])))
    if reglages.get("n_cpu_moe"):
        lignes.append("n-cpu-moe = {}".format(int(reglages["n_cpu_moe"])))
    if reglages.get("ngl"):
        lignes.append("n-gpu-layers = {}".format(int(reglages["ngl"])))
    for nom, fichier, projecteur in modeles:
        if not RE_NOM_PRESET.match(str(nom)):
            continue
        lignes += ["", "[{}]".format(nom), "model = {}".format(str(fichier).replace("\\", "/"))]
        if projecteur:
            lignes.append("mmproj = {}".format(str(projecteur).replace("\\", "/")))
        if est_embedding(nom):
            lignes.append("embeddings = true")
    return "\n".join(lignes) + "\n"


def espace_libre(p):
    """Go libres sur le disque qui porte ce dossier (même s'il n'existe pas encore : on remonte au premier dossier existant) ; None si inconnu."""
    while p is not None and not Path(p).exists() and Path(p) != Path(p).parent:
        p = Path(p).parent
    try:
        return round(shutil.disk_usage(str(p)).free / 1e9, 1) if p is not None else None
    except OSError:
        return None


def regler_dossier_modeles(moteur, chemin):
    """Change le dossier où llama.cpp range ses modèles (vide : le sous-dossier « modeles » de son dossier). Les modèles déjà téléchargés ne sont pas déplacés."""
    mo = moteurs.MOTEURS.get(moteur)
    if not isinstance(mo, MoteurLlamaCpp):
        raise ErreurMoteur(_t("Les modèles de ce moteur se règlent dans l'onglet Modèles."))
    valeur = valider_dossier(chemin, False)
    config = lire_config()
    c = config.setdefault(moteur, {})
    if valeur:
        c["dossier_modeles"] = valeur
    else:
        c.pop("dossier_modeles", None)
    ecrire_config(config)


def regler_dossier(moteur, chemin):
    """Change le dossier d'installation d'un moteur géré par Lutin (voir valider_dossier)."""
    mo = moteurs.MOTEURS.get(moteur)
    if not hasattr(mo, "info_dossier") or not mo.info_dossier().get("modifiable"):
        raise ErreurMoteur(_t("Ce moteur n'a pas de dossier d'installation."))
    valeur = valider_dossier(chemin, mo.serveur_installe() is not None, mo.nom)
    config = lire_config()
    c = config.setdefault(moteur, {})
    if valeur:
        c["dossier"] = valeur
    else:
        c.pop("dossier", None)
    ecrire_config(config)


def vue_reglages(moteur):
    c = lire_config().get(moteur, {})
    vue = {"url": c.get("url", ""), "cle_definie": bool(c.get("cle")), "variante": c.get("variante", "auto")}
    mo = moteurs.MOTEURS.get(moteur)
    if isinstance(mo, MoteurLlamaCpp):
        vue["avance"] = {"routeur": bool(c.get("routeur")), "routeur_possible": mo.routeur_possible(), "modeles_max": int(c.get("modeles_max") or MODELES_MAX_DEFAUT), "n_cpu_moe": int(c.get("n_cpu_moe") or 0),
                         "n_cpu_moe_possible": mo.option_possible("--n-cpu-moe"), "version_epinglee": c.get("version_epinglee", "")}
    if hasattr(mo, "info_dossier") and not moteurs.CONTEXTE["en_docker"]():
        vue["dossier"] = mo.info_dossier()
    return vue


def valider_dossier(chemin, installe, nom="llama.cpp"):
    """Le dossier choisi pour un moteur : absolu, utilisable en écriture. Chaîne vide = revenir au dossier par défaut. Refusé tant que le moteur est installé ailleurs (rien n'est déplacé en douce)."""
    chemin = str(chemin or "").strip()
    if installe:
        raise ErreurMoteur(_t("{} est déjà installé : désinstalle-le d'abord (tes modèles restent où ils sont), puis change de dossier.").format(nom))
    if not chemin:
        return ""
    p = Path(chemin).expanduser()
    if not p.is_absolute():
        raise ErreurMoteur(_t("Donne un chemin complet (par exemple D:/IA/llama.cpp)."))
    try:
        p.mkdir(parents=True, exist_ok=True)
        essai = p / ".lutin-ecriture"
        essai.write_text("ok", encoding="utf-8")
        essai.unlink()
    except OSError as e:
        raise ErreurMoteur(_t("Ce dossier n'est pas utilisable en écriture : {}").format(e))
    return str(p)


# --------------------------------------------------------------------------- réglages adaptés à la machine

AIDE_CACHE = {}


def aide_serveur(exe):
    """Le texte d'aide de ce llama-server (en minuscules), pour ne passer que les options qu'il connaît : elles changent d'une version à l'autre, et une option inconnue l'empêcherait de démarrer. Gardé en mémoire."""
    cle = str(exe)
    if cle not in AIDE_CACHE:
        try:
            r = subprocess.run([cle, "--help"], capture_output=True, timeout=20, cwd=str(Path(cle).parent))
            AIDE_CACHE[cle] = (r.stdout + r.stderr).decode("utf-8", "replace").lower()
        except (OSError, subprocess.SubprocessError):
            AIDE_CACHE[cle] = ""
    return AIDE_CACHE[cle]


def reglages_machine(aide, variante, taille_go, profil):
    """Ce que llama.cpp sait régler et que Lutin règle d'après la machine : (arguments, ajuste).
    - le nombre de fils de calcul = les cœurs physiques (llama.cpp en prend parfois trop, ce qui ralentit) ;
    - sur une carte graphique, un modèle qui ne tient pas entièrement (jugement de Lutin, comme pour Ollama) : `--fit` laisse llama.cpp répartir les couches entre la carte et le processeur, au lieu de tout y forcer.
    `ajuste` vaut True dans ce second cas : l'appelant ne force alors pas toutes les couches sur la carte. Sans profil de machine ou sans l'option dans l'aide, rien n'est ajouté."""
    arguments, ajuste = [], False
    if profil is None:
        return arguments, ajuste
    if getattr(profil, "coeurs", 0) and "--threads" in aide:
        arguments += ["--threads", str(int(profil.coeurs))]
    if variante in ("cuda", "vulkan", "metal") and taille_go and "--fit" in aide:
        from . import adequation
        if adequation.evaluer({"go": taille_go}, profil).get("niveau") in ("limite", "trop_gros"):
            arguments += ["--fit", "on"]
            ajuste = True
    return arguments, ajuste


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


def choisir_fichiers(releases, systeme, arch, variante, epinglee=""):
    """(étiquette, [assets]) : la plus récente version qui a tous les fichiers voulus (ou, si une version est épinglée, seulement celle-là), ou None."""
    motifs = noms_attendus(systeme, arch, variante)
    if not motifs:
        return None
    for r in releases or []:
        if epinglee and r.get("tag_name", "") != epinglee:
            continue
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

class _FluxCompte:
    """Le flux d'une réponse, qui prévient quand il est fini (fermé) : tant qu'une réponse est en cours, le serveur n'est pas redémarré."""

    def __init__(self, flux, fini):
        self.flux, self.fini_cb, self.compte = flux, fini, True

    def __enter__(self):
        self.flux.__enter__()
        return self

    def __iter__(self):
        return iter(self.flux)

    def __exit__(self, *a):
        try:
            return self.flux.__exit__(*a)
        finally:
            if self.compte:
                self.compte = False
                self.fini_cb()

    def __getattr__(self, nom):
        return getattr(self.flux, nom)


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
        if self.externe():
            return self.config().get("cle", "")
        return self._cle_serveur()

    def _cle_serveur(self):
        """La clé d'accès du serveur que Lutin lance (générée une fois, gardée dans moteurs.json, lisible par l'utilisateur seul) : personne d'autre sur la machine ou le réseau local ne peut lui parler."""
        config = lire_config()
        c = config.setdefault(self.id, {})
        if not c.get("cle_serveur"):
            import secrets
            c["cle_serveur"] = secrets.token_urlsafe(24)
            try:
                ecrire_config(config)
            except (OSError, ErreurMoteur):
                return c["cle_serveur"]
        return c["cle_serveur"]

    def option_possible(self, option):
        """Le llama-server installé connaît-il cette option ? (d'après son aide ; faux si on ne peut pas la lire)"""
        exe = self.serveur_pret()
        return exe is not None and option in aide_serveur(exe)

    def routeur_possible(self):
        return self.option_possible("--models-preset")

    def routeur_actif(self):
        return not self.externe() and bool(self.config().get("routeur")) and self.routeur_possible()

    def dossier_defaut(self):
        d = moteurs.CONTEXTE["donnees"]()
        return (Path(d) / "moteurs" / "llamacpp") if d else None

    def dossier(self):
        """Où llama.cpp vit (programme, modèles, journal) : le dossier choisi par l'utilisateur, sinon celui de Lutin."""
        choisi = self.config().get("dossier")
        return Path(choisi) if choisi else self.dossier_defaut()

    def dossier_propose(self):
        """Le dossier équivalent à celui d'Ollama, sur le même disque : à côté du dossier des modèles d'Ollama quand l'utilisateur lui en a choisi un (« D:/IA/ollama/models » -> « D:/IA/llama.cpp »).
        None quand Ollama est à son emplacement habituel (dans le profil de l'utilisateur) : rien d'équivalent à proposer, le dossier de Lutin convient."""
        ollama = moteurs.CONTEXTE["dossier_ollama"]()
        if not ollama:
            return None
        ollama = Path(ollama)
        if ollama == Path.home() / ".ollama" / "models" or Path.home() in ollama.parents and ".ollama" in ollama.parts:
            return None
        return ollama.parent / "llama.cpp"

    def info_dossier(self):
        """Ce que la page montre : le dossier utilisé, celui qui est proposé, celui par défaut, et la place libre sur chacun ; puis le dossier des modèles."""
        libre = espace_libre
        actuel, propose, defaut = self.dossier(), self.dossier_propose(), self.dossier_defaut()
        return {"actuel": str(actuel or ""), "propose": str(propose or ""), "defaut": str(defaut or ""), "personnalise": bool(self.config().get("dossier")),
                "libre_go": {"actuel": libre(actuel), "propose": libre(propose) if propose else None, "defaut": libre(defaut)}, "installe": self.serveur_installe() is not None, "modifiable": True,
                "modeles": {"actuel": str(self.dossier_modeles()), "libre_go": libre(self.dossier_modeles()), "modifiable": True, "personnalise": bool(self.config().get("dossier_modeles"))}}

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

    def bibliotheque(self):
        """Les modèles que Lutin télécharge pour llama.cpp depuis la bibliothèque d'Ollama, rangés comme Ollama le fait (voir registre_ollama.py) : mêmes noms que dans Ollama."""
        return self.dossier_modeles() / "ollama"

    def partages(self):
        """Les modèles utilisables par leur nom d'Ollama (`qwen3:8b`) : ceux qu'Ollama a déjà téléchargés (lus sur place, `origine` « ollama ») et ceux que Lutin a téléchargés pour llama.cpp depuis la même
        bibliothèque (`origine` « lutin »). {nom: {fichier, taille, projecteur, origine}}. Pas de modèle d'Ollama sous Docker (autre conteneur), avec un serveur externe, ou si l'utilisateur a coupé le partage
        (réglage `partager_ollama`). Relu au plus toutes les 10 secondes (la page interroge souvent)."""
        if self.externe() or moteurs.CONTEXTE["en_docker"]():
            return {}
        dossier = moteurs.CONTEXTE["dossier_ollama"]() if self.config().get("partager_ollama") is not False else None
        cle = (str(dossier or ""), str(self.bibliotheque()))
        cache = CACHE_PARTAGE
        if cache.get("cle") == cle and time.time() - cache.get("quand", 0) < 10:
            return cache["modeles"]
        from . import ollama_partage
        lus = {n: dict(v, origine="ollama") for n, v in ollama_partage.lire(dossier).items()} if dossier else {}
        lus.update({n: dict(v, origine="lutin") for n, v in ollama_partage.lire(self.bibliotheque()).items()})
        cache.update(cle=cle, quand=time.time(), modeles=lus)
        return lus

    def telecharger_ollama(self, modele, progression):
        """Télécharge un modèle de la bibliothèque d'Ollama (n'importe lequel : officiel ou de la communauté) pour llama.cpp, sans Ollama."""
        if self.externe():
            raise ErreurMoteur(_t("Un serveur externe gère ses modèles lui-même."))
        if moteurs.CONTEXTE["hors_ligne"]():
            raise ErreurMoteur(_t("Mode hors ligne : aucun téléchargement."))
        from . import registre_ollama
        registre_ollama.telecharger(modele, self.bibliotheque(), progression)
        CACHE_PARTAGE.clear()

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
        communs = self.partages()
        for n in sorted(communs):          # sous leurs noms d'Ollama : la même liste de modèles d'un moteur à l'autre
            if n not in tailles:
                noms.append(n)
                tailles[n] = communs[n]["taille"]
        return {"actif": self.serveur_pret() is not None, "installes": noms, "tailles": tailles, "partages": [n for n in sorted(communs) if communs[n].get("origine") == "ollama"]}

    def en_memoire(self, modele):
        if self.externe():
            return super().en_memoire(modele)
        with SERVEUR["verrou"]:
            p = SERVEUR["proc"]
            if p is not None and p.poll() is None and (SERVEUR["modele"] == modele or (SERVEUR["modele"] == ROUTEUR and modele in SERVEUR["noms"])):
                return {"taille": 0, "vram": 0}
        return None

    def vecteurs(self, modele, textes, delai=60):
        """Les vecteurs de ces textes. Avec un llama-server géré, seul le mode routeur peut servir un modèle d'embeddings à côté du modèle de conversation sans le décharger."""
        if not self.externe():
            if not self.routeur_actif():
                raise ErreurMoteur(_t("Avec llama.cpp, la recherche par le sens demande le mode routeur (Réglages > Moteur > Mode routeur)."))
            self.demarrer(modele, CTX_DEFAUT)
        return super().vecteurs(modele, textes, delai)

    def grille(self):
        return {"discuter": ("natif", ""), "flux": ("natif", ""), "arret": ("natif", _t("La connexion est coupée : le serveur arrête de générer.")),
                "outils": ("adapte", _t("Lutin lance le serveur avec --jinja et traduit les appels d'outils.")),
                "reflexion": ("adapte", _t("Le raisonnement du modèle est lu dans le flux du serveur.")),
                "vision": ("adapte", _t("Les images partent en data-URL ; le projecteur (--mmproj) est ajouté tout seul pour les modèles d'Ollama.")),
                "embeddings": ("adapte", _t("Demande le mode routeur : le modèle de recherche reste chargé à côté de celui de conversation.")),
                "plusieurs_modeles": ("adapte", _t("En mode routeur ; sinon un seul modèle à la fois (le serveur redémarre quand on change).")),
                "telechargement": ("adapte", _t("Depuis la bibliothèque d'Ollama (sans Ollama) ou depuis Hugging Face.")),
                "installation": ("adapte", _t("Lutin télécharge le programme officiel adapté à la machine."))}

    def _assurer(self, corps):
        """Géré : le serveur tourne avec le modèle voulu et la fenêtre de contexte voulue (il est démarré ou redémarré au besoin, jamais sous une réponse en cours).
        Compte cette demande comme active ; l'appelant DOIT appeler `_fini()` ensuite. Rend False pour un moteur externe (rien à compter)."""
        if self.externe():
            return False
        modele = corps.get("model", "")
        ctx = int((corps.get("options") or {}).get("num_ctx") or CTX_DEFAUT)
        with SERVEUR["verrou"]:
            SERVEUR["actifs"] += 1
        try:
            self.demarrer(modele, ctx, propres=1)
        except BaseException:
            self._fini()
            raise
        return True

    @staticmethod
    def _fini():
        with SERVEUR["verrou"]:
            SERVEUR["actifs"] = max(0, SERVEUR["actifs"] - 1)

    def chat(self, corps, delai=60):
        compte = self._assurer(corps)
        try:
            return super().chat(corps, delai)
        finally:
            if compte:
                self._fini()

    def chat_flux(self, corps, delai=900):
        compte = self._assurer(corps)
        try:
            flux = super().chat_flux(corps, delai)
        except BaseException:
            if compte:
                self._fini()
            raise
        return _FluxCompte(flux, self._fini) if compte else flux

    # -- le serveur géré
    def _besoin_redemarrage(self, modele, ctx, routeur):
        """Vrai si le serveur qui tourne ne convient pas à cette demande. Un contexte plus PETIT que l'actuel convient : on ne redémarre jamais pour rétrécir."""
        p = SERVEUR["proc"]
        if p is None or p.poll() is not None:
            return False          # rien à interrompre
        if routeur:
            return not (SERVEUR["modele"] == ROUTEUR and modele in SERVEUR["noms"] and ctx - SERVEUR["ctx"] < 1024)
        return not (SERVEUR["modele"] == modele and ctx - SERVEUR["ctx"] < 1024)

    def _attendre_reponses(self, modele, ctx, routeur, propres, maxi=900):
        """Un autre modèle ou un contexte plus grand demande un redémarrage : on attend que les réponses en cours finissent (sinon elles seraient coupées en plein milieu)."""
        fin = time.time() + maxi
        while time.time() < fin:
            with SERVEUR["verrou"]:
                if SERVEUR["actifs"] - propres <= 0 or not self._besoin_redemarrage(modele, ctx, routeur):
                    return
            time.sleep(0.3)

    def demarrer(self, modele, ctx=CTX_DEFAUT, attente=DEMARRAGE_MAX_S, propres=0):
        exe = self.serveur_pret()
        if exe is None:
            raise ErreurMoteur(_t("llama.cpp n'est pas installé : Réglages > Moteur > Installer."))
        fichier = self._fichier_modele(modele)
        routeur = self.routeur_actif()
        self._attendre_reponses(modele, ctx, routeur, propres)
        with SERVEUR["verrou"]:
            p = SERVEUR["proc"]
            if p is not None and p.poll() is None and not self._besoin_redemarrage(modele, ctx, routeur):
                return          # le serveur (ou le routeur, qui charge et décharge tout seul) convient déjà
            self.arreter()
            port = int(self.config().get("port") or PORT_DEFAUT)
            variante = (self.config().get("variante_installee") or "cpu")
            aide = aide_serveur(exe)
            commande = [str(exe), "--host", "127.0.0.1", "--port", str(port), "--jinja"]
            if "--api-key" in aide:
                commande += ["--api-key", self._cle_serveur()]
            commun = self.partages().get(str(modele))
            try:
                taille_go = Path(fichier).stat().st_size / 1e9
                machine, ajuste = reglages_machine(aide, variante, taille_go, (moteurs.CONTEXTE.get("profil_attendu") or moteurs.CONTEXTE["profil"])())
            except Exception:  # noqa: BLE001  (les réglages adaptés ne doivent jamais empêcher de démarrer)
                machine, ajuste = [], False
            moe = int(self.config().get("n_cpu_moe") or 0)
            if routeur:
                ctx = max(ctx, CTX_DEFAUT)
                noms, texte = self._preset(ctx, variante, ajuste, machine, moe)
                preset = self.dossier() / "modeles.ini"
                preset.parent.mkdir(parents=True, exist_ok=True)
                preset.write_text(texte, encoding="utf-8")
                commande += ["--models-preset", str(preset), "--models-max", str(int(self.config().get("modeles_max") or MODELES_MAX_DEFAUT))]
                SERVEUR["noms"] = noms
            else:
                commande += ["-m", str(fichier), "-c", str(ctx)]
                if commun is not None and commun.get("projecteur") and Path(fichier) == commun["fichier"]:
                    commande += ["--mmproj", str(commun["projecteur"])]          # un modèle d'Ollama qui voit les images : son projecteur est dans le même dossier
                commande += machine
                if moe and "--n-cpu-moe" in aide:
                    commande += ["--n-cpu-moe", str(moe)]          # modèle « à experts » : ses experts restent sur le processeur, le reste va sur la carte
                if variante in ("cuda", "vulkan", "metal") and not ajuste:
                    commande += ["-ngl", "99"]          # tout le modèle sur la carte ; s'il est trop gros pour elle, `--fit` (ci-dessus) répartit les couches avec le processeur
            journal = self.dossier() / "serveur.log"
            journal.parent.mkdir(parents=True, exist_ok=True)
            sortie = open(journal, "wb")
            try:
                SERVEUR["proc"] = subprocess.Popen(commande, stdout=sortie, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(Path(exe).parent))
            except OSError as e:
                raise ErreurMoteur(_t("Impossible de lancer llama-server : {}").format(e))
            finally:
                sortie.close()          # le processus garde sa propre copie du fichier journal
            SERVEUR.update({"modele": ROUTEUR if routeur else modele, "ctx": ctx})
        lance = SERVEUR["proc"]
        fin = time.time() + attente
        while time.time() < fin:
            if lance is None or SERVEUR["proc"] is not lance:
                raise ErreurMoteur(_t("Le serveur llama.cpp a été arrêté ou remplacé pendant son démarrage : relance la demande."))
            if lance.poll() is not None:
                fin = self._fin_du_journal()
                raise ErreurMoteur(_t("llama-server s'est arrêté au démarrage : {}").format(fin) + aide_bibliotheque(fin))
            if self._pret():
                return
            time.sleep(0.5)
        self.arreter()
        raise ErreurMoteur(_t("llama-server ne répond pas après {} s : {}").format(attente, self._fin_du_journal()))

    def _preset(self, ctx, variante, ajuste, machine, moe):
        """(noms des modèles, texte du fichier de préréglages) pour tous les modèles de conversation et d'embeddings installés."""
        modeles = []
        for nom in self.modeles()["installes"]:
            try:
                f = self._fichier_modele(nom)
            except ErreurMoteur:
                continue
            commun = self.partages().get(str(nom))
            projecteur = commun.get("projecteur") if commun is not None and Path(f) == commun["fichier"] else None
            modeles.append((nom, f, projecteur))
        fils = int(machine[machine.index("--threads") + 1]) if "--threads" in machine else 0
        reglages = {"fils": fils, "n_cpu_moe": moe if moe and self.option_possible("--n-cpu-moe") else 0, "ngl": 99 if variante in ("cuda", "vulkan", "metal") and not ajuste else 0}
        return tuple(n for n, _, _ in modeles), texte_preset(modeles, ctx, reglages)

    def _pret(self):
        """Le serveur a fini de charger le modèle ? `/health` répond « ok » (503 pendant le chargement) ; une ancienne version sans /health : on se contente de /models."""
        try:
            return str(self._json("/health", None, 3).get("status", "ok")) == "ok"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return MoteurOpenAI.actif(self)
            return False          # 503 : il charge encore
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _fin_du_journal(self):
        try:
            return " ".join((self.dossier() / "serveur.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:])[-300:]
        except OSError:
            return ""

    def arreter(self):
        with SERVEUR["verrou"]:
            p = SERVEUR["proc"]
            SERVEUR.update({"proc": None, "modele": "", "ctx": 0, "noms": ()})
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
        commun = self.partages().get(str(modele))
        if commun is not None and not (self.dossier_modeles() / (str(modele) + ".gguf")).is_file():
            return commun["fichier"]          # un modèle d'Ollama : son fichier GGUF, lu sur place
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
        detail = (_t("Routeur démarré : {} modèle(s) disponibles, chargés à la demande.").format(len(SERVEUR["noms"])) if modele == ROUTEUR else _t("Serveur démarré avec « {} ».").format(modele)) if tourne else (_t("Installé : il démarre à la demande.") if exe or self.serveur_pret() else _t("Pas installé."))
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
                "mettre_a_jour": {"possible": par_lutin and not moteurs.CONTEXTE["hors_ligne"](), "raison": _t("Télécharge la dernière version et remplace l'actuelle ; tes modèles et ton dossier sont gardés.") if par_lutin else sans},
                "desinstaller": {"possible": par_lutin, "raison": _t("Supprime le programme (tes modèles restent).") if par_lutin else sans},
                "reinstaller": {"possible": par_lutin and not moteurs.CONTEXTE["hors_ligne"](), "raison": _t("Télécharge de nouveau la dernière version, en gardant tes modèles.") if par_lutin else sans},
                "demarrer": {"possible": False, "raison": _t("Il démarre tout seul quand tu discutes avec un modèle.")},
                "arreter": {"possible": tourne, "raison": _t("Arrête le serveur et libère la mémoire.") if tourne else _t("Il n'est pas démarré.")}}

    def faire(self, action, progression):
        if action in ("installer", "reinstaller", "mettre_a_jour"):
            return self.installer(progression, reinstaller=action != "installer")
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
        variante = voulue if voulue in ("cuda", "vulkan", "cpu", "metal") else variante_auto((moteurs.CONTEXTE.get("profil_attendu") or moteurs.CONTEXTE["profil"])(), systeme)
        epinglee = str(config.get(self.id, {}).get("version_epinglee") or "")
        progression(_t("Recherche de la version {}…").format(epinglee) if epinglee else _t("Recherche de la dernière version…"), 0, 0)
        try:
            releases = [(http_json or _http_json)(API_VERSION + epinglee)] if epinglee else (http_json or _http_json)(API_RELEASES)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ErreurMoteur(_t("GitHub ne répond pas : {}").format(e))
        choix = choisir_fichiers(releases, systeme, arch, variante, epinglee)
        if choix is None and variante != "cpu":
            variante = "cpu"
            choix = choisir_fichiers(releases, systeme, arch, variante, epinglee)
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
        if exe.parent != neuf:          # le programme est dans un sous-dossier : les bibliothèques de l'autre archive (CUDA) arrivées à la racine doivent l'y rejoindre
            for f in list(neuf.glob("*.dll")) + list(neuf.glob("*.so*")):
                if not (exe.parent / f.name).exists():
                    shutil.copy2(f, exe.parent / f.name)
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
        commun = self.partages().get(str(nom))
        if commun is not None and not (self.dossier_modeles() / (str(nom) + ".gguf")).is_file():
            if commun.get("origine") == "ollama":
                raise ErreurMoteur(_t("« {} » appartient à Ollama : supprime-le depuis Ollama (llama.cpp ne fait que le lire).").format(nom))
            from . import registre_ollama
            with SERVEUR["verrou"]:
                if SERVEUR["modele"] == nom:
                    self.arreter()
            registre_ollama.supprimer(str(nom), self.bibliotheque())
            CACHE_PARTAGE.clear()
            return
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

    def grille(self):
        return {"discuter": ("natif", ""), "flux": ("natif", ""), "arret": ("natif", _t("La connexion est coupée : le serveur arrête de générer.")),
                "outils": ("non_teste", _t("Dépend du serveur.")), "reflexion": ("non_teste", _t("Dépend du serveur.")), "vision": ("non_teste", _t("Dépend du serveur et du modèle.")),
                "embeddings": ("non_teste", _t("Dépend du serveur.")), "plusieurs_modeles": ("non_teste", _t("Dépend du serveur.")),
                "telechargement": ("non", _t("Le serveur gère ses modèles lui-même.")), "installation": ("non", _t("Lutin n'installe pas ce serveur."))}


def _systeme():
    import sys
    return "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux")


def _http_json(url, delai=20):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Lutin"})
    with urllib.request.urlopen(req, timeout=delai) as r:
        return json.loads(r.read().decode("utf-8"))
