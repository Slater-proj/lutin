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
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import engine_capabilities, engines
from . import offline as _offline
from .engine_replace import free_process, replace_folder  # noqa: F401  (le remplacement d'un dossier est commun à tous les moteurs)
from .i18n import t as _t
from .openai_engine import OpenAIEngine

API_RELEASES = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=8"
SHARED_CACHE = {}
API_HF = "https://huggingface.co/api/models"
DEFAULT_PORT = 8089
DEFAULT_CTX = 8192
STARTUP_MAX_S = 180
RE_REPO = re.compile(r"^[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*$")
RE_FILE = re.compile(r"^[\w][\w./+-]*\.gguf$", re.I)
RE_SHARD = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)          # modèle coupé en plusieurs fichiers : pas géré
SERVER = {"proc": None, "modele": "", "ctx": 0, "noms": (), "verrou": threading.RLock(), "actifs": 0}          # actifs : réponses en cours (on ne redémarre jamais le serveur sous elles)
API_VERSION = "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/"
RE_VERSION = re.compile(r"^b\d{1,7}$")
RE_PRESET_NAME = re.compile(r"^[^\[\]\r\n=#;]{1,200}$")
EMBEDDING_WORDS = ("embed", "bge-", "bge:", "e5-", "gte-", "minilm", "arctic-embed")          # les modèles qui vectorisent au lieu de discuter (sans eux, un routeur les chargerait comme des modèles de conversation)
DEFAULT_MAX_MODELS = 2
ROUTER = "(routeur)"


class EngineError(ValueError):
    pass


DEBIAN_PACKAGES = {"libgomp.so.1": "libgomp1", "libstdc++.so.6": "libstdc++6", "libcurl.so.4": "libcurl4", "libvulkan.so.1": "libvulkan1", "libgcc_s.so.1": "libgcc-s1"}


def library_help(texte):
    """Le serveur a répondu « error while loading shared libraries: X » : le paquet Debian/Ubuntu qui la fournit, quand on le connaît."""
    m = re.search(r"error while loading shared libraries: (\S+?):", str(texte))
    if not m:
        return ""
    paquet = DEBIAN_PACKAGES.get(m.group(1))
    return _t(" Bibliothèque manquante : {}.").format(m.group(1)) + (_t(" Sous Debian ou Ubuntu : apt install {} (dans Docker : à ajouter à l'image).").format(paquet) if paquet else "")


# --------------------------------------------------------------------------- réglages des moteurs (donnees/moteurs.json)

def _config_path():
    d = engines.CONTEXT["donnees"]()
    return (Path(d) / "moteurs.json") if d else None


CONFIG_ATTEMPTS = 20          # moteurs.json tenu un instant (Windows : en cours de remplacement, antivirus) : relu ou remplacé toutes les 50 ms, une seconde au plus
CONFIG_LOCK = threading.Lock()


def read_config():
    """Les réglages des moteurs. Un fichier tenu un instant est relu un peu plus tard : lu vide, il était réécrit par l'appelant avec le seul
    changement, et les moteurs externes et leurs clés étaient perdus."""
    f = _config_path()
    donnees = {}
    for essai in range(CONFIG_ATTEMPTS):
        try:
            donnees = json.loads(f.read_text(encoding="utf-8")) if f and f.is_file() else {}
            break
        except PermissionError:
            if essai == CONFIG_ATTEMPTS - 1:
                raise EngineError(_t("Les réglages des moteurs (moteurs.json) ne se lisent pas : un autre programme les tient. Réessaie dans un moment.")) from None
            time.sleep(0.05)
        except (OSError, ValueError):
            donnees = {}
            break
    return donnees if isinstance(donnees, dict) else {}


def write_config(config):
    f = _config_path()
    if f is None:
        raise EngineError(_t("Dossier de données inconnu."))
    f.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_LOCK:                                    # deux écritures à la fois partageaient moteurs.json.tmp
        tmp = f.with_name("{}.{}.tmp".format(f.name, threading.get_ident()))
        try:
            tmp.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)          # il peut contenir une clé d'accès
            except OSError:
                pass
            for essai in range(CONFIG_ATTEMPTS):
                try:
                    os.replace(tmp, f)
                    break
                except PermissionError:
                    if essai == CONFIG_ATTEMPTS - 1:
                        raise
                    time.sleep(0.05)
        finally:
            tmp.unlink(missing_ok=True)


# What a managed server kept in the section of the `openai` engine before it became an engine of its own (ADR 0020).
LEGACY_KEYS = {engines.EXLLAMAV3: ("port_exllamav3", "dossier_modeles"), engines.LMSTUDIO: ("port_lmstudio",), engines.COLIBRI: ("port_colibri", "modele_colibri")}


def section(config, moteur):
    """The settings of one engine in `config` (moteurs.json read), not to be modified. A managed server that has no section yet reads what the
    `openai` engine kept for it: the old settings work without being migrated."""
    own = config.get(moteur)
    if isinstance(own, dict):
        return own
    old = config.get(engines.OPENAI) if moteur in LEGACY_KEYS else None
    return {k: old[k] for k in LEGACY_KEYS[moteur] if k in old} if isinstance(old, dict) else {}


def section_to_write(config, moteur):
    """The section of `config` that a change of this engine's settings writes into: created from `section` the first time, so a managed server keeps what
    it had in the old section of `openai`."""
    if not isinstance(config.get(moteur), dict):
        config[moteur] = dict(section(config, moteur))
    return config[moteur]


def old_server():
    """The old choice of server inside the settings of the `openai` engine (« exllamav3 », « lmstudio », « colibri »), or ""."""
    c = read_config().get(engines.OPENAI)
    return str(c.get("serveur") or "") if isinstance(c, dict) else ""


def forget_old_server():
    """The person chose the `openai` engine itself: its old choice of server must no longer turn it into that server (engines.chosen_id)."""
    config = read_config()
    c = config.get(engines.OPENAI)
    if isinstance(c, dict) and c.get("serveur"):
        c.pop("serveur")
        write_config(config)


def normalize_address(adresse):
    """« http://hote:8080 » -> « http://hote:8080/v1 » ; « » reste « ». Lève ErreurMoteur si l'adresse n'est pas http(s)."""
    adresse = str(adresse or "").strip().rstrip("/")
    if not adresse:
        return ""
    if not re.match(r"^https?://[^\s/]+", adresse, re.I):
        raise EngineError(_t("L'adresse doit commencer par http:// ou https://."))
    return adresse if re.search(r"/v\d+$", adresse) else adresse + "/v1"


def configure(moteur, adresse=None, cle=None, **autres):
    """Enregistre l'adresse (et la clé) d'un moteur compatible OpenAI. Une adresse vide remet llama.cpp en mode « géré par Lutin »."""
    config = read_config()
    c = config.setdefault(moteur, {})
    if adresse is not None:
        c["url"] = normalize_address(adresse)
    if cle is not None:
        c["cle"] = str(cle).strip()
    for k, v in autres.items():
        if v is not None:
            c[k] = v
    write_config(config)


def configure_advanced(moteur, donnees):
    """Les réglages propres à llama.cpp géré par Lutin : mode routeur (plusieurs modèles sans redémarrer le serveur), nombre de modèles gardés en mémoire, couches d'experts laissées au processeur
    (modèles « à experts »), version épinglée. Chaque valeur est contrôlée ; une valeur vide remet le réglage par défaut. Le serveur est arrêté pour que le changement compte au prochain message."""
    mo = engines.ENGINES.get(moteur)
    if not isinstance(mo, LlamaCppEngine):
        return False
    config = read_config()
    c = config.setdefault(moteur, {})
    if "routeur" in donnees:
        if donnees["routeur"] and not mo.routeur_possible():
            raise EngineError(_t("Ce llama-server ne sait pas faire le mode routeur : mets-le à jour (Réglages > Moteur > Mettre à jour)."))
        c["routeur"] = bool(donnees["routeur"])
    if "modeles_max" in donnees:
        try:
            n = int(donnees["modeles_max"] or DEFAULT_MAX_MODELS)
        except (TypeError, ValueError):
            raise EngineError(_t("Nombre de modèles invalide."))
        if not 1 <= n <= 8:
            raise EngineError(_t("Entre 1 et 8 modèles en mémoire."))
        c["modeles_max"] = n
    if "n_cpu_moe" in donnees:
        try:
            n = int(donnees["n_cpu_moe"] or 0)
        except (TypeError, ValueError):
            raise EngineError(_t("Nombre de couches invalide."))
        if not 0 <= n <= 512:
            raise EngineError(_t("Entre 0 et 512 couches."))
        if n:
            c["n_cpu_moe"] = n
        else:
            c.pop("n_cpu_moe", None)
    if "version_epinglee" in donnees:
        v = str(donnees["version_epinglee"] or "").strip().lower()
        if v and not RE_VERSION.match(v):
            raise EngineError(_t("Une version de llama.cpp s'écrit « b » suivi de son numéro, par exemple b6500."))
        if v:
            c["version_epinglee"] = v
        else:
            c.pop("version_epinglee", None)
    write_config(config)
    mo.arreter()
    return True


def configure_server(moteur, donnees):
    """Le serveur compatible OpenAI choisi dans la liste (« serveur ») et, pour Colibri, le dossier de son modèle et son port. Renvoie vrai si un de ces réglages était dans la demande."""
    mo = engines.ENGINES.get(moteur)
    if not isinstance(mo, ExternalEngine) or not any(k in donnees for k in ("serveur", "modele_colibri", "port_colibri", "port_lmstudio", "port_exllamav3")):
        return False
    config = read_config()
    c = section_to_write(config, moteur)
    if "serveur" in donnees:          # the old select of the `openai` engine (ADR 0020): still read from an old client, never shown
        if mo.serveur:
            raise EngineError(_t("Ce moteur n'a pas de serveur à choisir."))
        s = str(donnees["serveur"] or "").strip().lower()
        if not re.match(r"^[a-z0-9-]{0,30}$", s):
            raise EngineError(_t("Serveur inconnu."))
        avant = engines.ENGINES.get(str(c.get("serveur") or ""))
        if s != str(c.get("serveur") or "") and isinstance(avant, ManagedServerEngine):
            avant.arreter_gere()          # un seul serveur compatible OpenAI à la fois : celui que Lutin a lancé est arrêté (sa mémoire est rendue), jamais laissé tourner en cachette
        if s:
            c["serveur"] = s
        else:
            c.pop("serveur", None)
    if "modele_colibri" in donnees:
        m = str(donnees["modele_colibri"] or "").strip()
        if m:
            p = Path(m).expanduser()
            if not p.is_absolute():
                raise EngineError(_t("Donne un chemin complet (par exemple D:/IA/colibri-modele)."))
            if not p.is_dir():
                raise EngineError(_t("Ce dossier n'existe pas : {}").format(p))
            c["modele_colibri"] = str(p)
        else:
            c.pop("modele_colibri", None)
    if "port_colibri" in donnees:
        try:
            n = int(donnees["port_colibri"] or 0)
        except (TypeError, ValueError):
            raise EngineError(_t("Port invalide (un nombre entre 1024 et 65535)."))
        if n and not 1024 <= n <= 65535:
            raise EngineError(_t("Port invalide (un nombre entre 1024 et 65535)."))
        if n:
            c["port_colibri"] = n
        else:
            c.pop("port_colibri", None)
    if "port_lmstudio" in donnees:
        try:
            n = int(donnees["port_lmstudio"] or 0)
        except (TypeError, ValueError):
            raise EngineError(_t("Port invalide (un nombre entre 1024 et 65535)."))
        if n and not 1024 <= n <= 65535:
            raise EngineError(_t("Port invalide (un nombre entre 1024 et 65535)."))
        if n:
            c["port_lmstudio"] = n
        else:
            c.pop("port_lmstudio", None)
    if "port_exllamav3" in donnees:
        try:
            n = int(donnees["port_exllamav3"] or 0)
        except (TypeError, ValueError):
            raise EngineError(_t("Port invalide (un nombre entre 1024 et 65535)."))
        if n and not 1024 <= n <= 65535:
            raise EngineError(_t("Port invalide (un nombre entre 1024 et 65535)."))
        if n:
            c["port_exllamav3"] = n
        else:
            c.pop("port_exllamav3", None)
    write_config(config)
    return True


def is_embedding(nom):
    """Ce modèle vectorise-t-il (recherche par le sens) au lieu de discuter ? D'après son nom."""
    n = str(nom).lower()
    return any(m in n for m in EMBEDDING_WORDS)


def preset_text(modeles, ctx, reglages):
    """Le fichier de préréglages du mode routeur (format INI de llama-server) : une section par modèle, avec son fichier, son éventuel projecteur d'images et ses réglages.
    `modeles` : [(nom, fichier, projecteur ou None)] ; `reglages` : {fils, n_cpu_moe, ngl}."""
    lignes = ["version = 1", "", "[*]", "c = {}".format(int(ctx))]
    if reglages.get("fils"):
        lignes.append("threads = {}".format(int(reglages["fils"])))
    if reglages.get("n_cpu_moe"):
        lignes.append("n-cpu-moe = {}".format(int(reglages["n_cpu_moe"])))
    if reglages.get("ngl"):
        lignes.append("n-gpu-layers = {}".format(int(reglages["ngl"])))
    if reglages.get("sans_mmap"):
        lignes.append("no-mmap = true")
    elif reglages.get("chargement_direct"):
        lignes.append("load-mode = none")          # llama.cpp 1.0 : `no-mmap` n'existe plus
    if reglages.get("cache_ram") is not None:
        lignes.append("cache-ram = {}".format(int(reglages["cache_ram"])))
    if reglages.get("cache_8_bits"):
        lignes += ["flash-attn = on", "cache-type-k = q8_0", "cache-type-v = q8_0"]
    for nom, fichier, projecteur in modeles:
        if not RE_PRESET_NAME.match(str(nom)):
            continue
        lignes += ["", "[{}]".format(nom), "model = {}".format(str(fichier).replace("\\", "/"))]
        if projecteur:
            lignes.append("mmproj = {}".format(str(projecteur).replace("\\", "/")))
        if is_embedding(nom):
            lignes.append("embeddings = true")
    return "\n".join(lignes) + "\n"


def free_space(p):
    """Go libres sur le disque qui porte ce dossier (même s'il n'existe pas encore : on remonte au premier dossier existant) ; None si inconnu."""
    while p is not None and not Path(p).exists() and Path(p) != Path(p).parent:
        p = Path(p).parent
    try:
        return round(shutil.disk_usage(str(p)).free / 1e9, 1) if p is not None else None
    except OSError:
        return None


def set_models_folder(moteur, chemin):
    """Change le dossier où llama.cpp range ses modèles (vide : le sous-dossier « modeles » de son dossier). Les modèles déjà téléchargés ne sont pas déplacés."""
    mo = engines.ENGINES.get(moteur)
    exl = isinstance(mo, ExternalEngine) and mo.exllamav3_choisi()
    if not isinstance(mo, LlamaCppEngine) and not exl:
        raise EngineError(_t("Les modèles de ce moteur se règlent dans l'onglet Modèles."))
    valeur = validate_folder(chemin, False, "ExLlamaV3" if exl else "llama.cpp")
    config = read_config()
    c = section_to_write(config, moteur)
    if exl:
        mo.arreter_gere()          # TabbyAPI lit son dossier de modèles au démarrage : arrêté ici, il repart sur le nouveau dossier au prochain « Démarrer »
    if valeur:
        c["dossier_modeles"] = valeur
    else:
        c.pop("dossier_modeles", None)
    write_config(config)


def engines_installed_by_lutin():
    """Les moteurs que Lutin a installés dans le dossier des moteurs (ceux qu'un changement de dossier laisserait derrière)."""
    from . import docker_engines
    trouves = []
    llama = engines.ENGINES.get("llamacpp")
    if isinstance(llama, LlamaCppEngine) and not llama.config().get("dossier") and llama.serveur_installe() is not None:
        trouves.append("llama.cpp")
    if engines.CONTEXT["en_docker"]() and docker_engines.ollama_installed_by_lutin():
        trouves.append("Ollama")
    autre = engines.ENGINES.get(engines.OPENAI)
    if isinstance(autre, ExternalEngine) and autre._colibri() is not None:
        trouves.append("Colibri")
    if isinstance(autre, ExternalEngine) and autre._exl() is not None:
        trouves.append("ExLlamaV3")
    return trouves


def engines_folder_view():
    """Ce que la page montre pour le dossier des moteurs : où, pourquoi là, la place libre, ce qui y est installé, et pourquoi /engines n'est pas utilisé quand c'est le cas."""
    from . import docker_engines
    detail = docker_engines.detail_folder_engines()
    actuel = detail["dossier"]
    donnees = engines.CONTEXT["donnees"]()
    defaut = docker_engines.default_folder(donnees) if donnees else None
    docker = engines.CONTEXT["en_docker"]()
    if docker and docker_engines.is_mounted(docker_engines.MOUNT) and os.access(docker_engines.MOUNT, os.W_OK):
        defaut = Path(docker_engines.MOUNT)          # sans choix de ta part, c'est lui qui serait pris
    propose = None
    try:
        ollama = engines.CONTEXT["dossier_ollama"]()
        if ollama and not docker:          # Ollama dans un dossier à lui (pas celui de son profil) : les autres moteurs peuvent vivre à côté de lui
            o = Path(ollama)
            if not (o == Path.home() / ".ollama" / "models" or Path.home() in o.parents and ".ollama" in o.parts) and o.parent != Path(actuel or "."):
                propose = o.parent
    except Exception:  # noqa: BLE001  (une proposition de plus : jamais une page cassée)
        propose = None
    return {"actuel": str(actuel or ""), "defaut": str(defaut or ""), "propose": str(propose or ""), "libre_go_propose": free_space(propose) if propose else None, "source": detail["source"], "probleme": detail["probleme"], "docker": docker,
            "montage": docker_engines.MOUNT, "modifiable": detail["source"] != "env", "personnalise": detail["source"] == "reglage", "libre_go": free_space(actuel), "installes": engines_installed_by_lutin(),
            "sous_dossiers": ["ollama", "llamacpp", "colibri", "exllamav3"]}


def set_engines_folder(chemin):
    """Choisit le dossier des moteurs (un sous-dossier par moteur y est créé). Chaîne vide : revenir au dossier par défaut. Rien n'est déplacé en douce : refusé tant qu'un moteur installé par Lutin est dans l'ancien dossier."""
    from . import docker_engines
    if docker_engines.detail_folder_engines()["source"] == "env":
        raise EngineError(_t("Le dossier des moteurs est fixé par la variable LUTIN_ENGINES du docker-compose : change-la là."))
    installes = engines_installed_by_lutin()
    if installes:
        raise EngineError(_t("{} est déjà installé dans le dossier actuel : désinstalle-le d'abord (tes modèles restent où ils sont), puis change de dossier.").format(", ".join(installes)))
    valeur = validate_folder(chemin, False, _t("Le dossier des moteurs"))
    config = read_config()
    if valeur:
        config["dossier_moteurs"] = valeur
    else:
        config.pop("dossier_moteurs", None)
    write_config(config)


def set_folder(moteur, chemin):
    """Change le dossier d'installation d'un moteur géré par Lutin (voir valider_dossier)."""
    mo = engines.ENGINES.get(moteur)
    if not hasattr(mo, "info_dossier") or not mo.info_dossier().get("modifiable"):
        raise EngineError(_t("Ce moteur n'a pas de dossier d'installation."))
    valeur = validate_folder(chemin, mo.serveur_installe() is not None, mo.nom)
    config = read_config()
    c = config.setdefault(moteur, {})
    if valeur:
        c["dossier"] = valeur
    else:
        c.pop("dossier", None)
    write_config(config)


def apply_settings(mo, donnees):
    """Ce que la page change d'un moteur, en une demande (ancienne page et /api/v1) : dossier d'installation, dossier des modèles, serveur compatible
    OpenAI choisi et ses ports, réglages avancés de llama.cpp, adresse, clé et variante. ErreurMoteur (un ValueError) dit ce qui ne va pas."""
    if "dossier" in donnees:
        set_folder(mo.id, donnees.get("dossier"))
    if "dossier_modeles" in donnees:
        set_models_folder(mo.id, donnees.get("dossier_modeles"))
    serveur_regle = configure_server(mo.id, donnees)          # Colibri : choix du serveur, dossier du modèle, port
    avance = configure_advanced(mo.id, {k: donnees[k] for k in ("routeur", "modeles_max", "n_cpu_moe", "version_epinglee") if k in donnees})
    if not mo.adresse_modifiable:
        if avance or serveur_regle or "dossier" in donnees or "dossier_modeles" in donnees:          # a managed server: its port, Colibri's model
            return
        raise EngineError(_t("Ce moteur n'a pas d'adresse à régler."))
    if mo.id == "llamacpp" and "url" not in donnees and "variante" not in donnees and avance:
        return
    if serveur_regle and "url" not in donnees and "cle" not in donnees:
        return
    configure(mo.id, donnees.get("url"), donnees.get("cle"), variante=donnees.get("variante") if donnees.get("variante") in ("auto", "cuda", "vulkan", "cpu", "metal") else None)


def settings_view(moteur):
    c = section(read_config(), moteur)
    vue = {"url": c.get("url", ""), "cle_definie": bool(c.get("cle")), "variante": c.get("variante", "auto")}
    mo = engines.ENGINES.get(moteur)
    if isinstance(mo, LlamaCppEngine):
        vue["avance"] = {"routeur": bool(c.get("routeur")), "routeur_possible": mo.routeur_possible(), "modeles_max": int(c.get("modeles_max") or DEFAULT_MAX_MODELS), "n_cpu_moe": int(c.get("n_cpu_moe") or 0),
                         "n_cpu_moe_possible": mo.option_possible("--n-cpu-moe"), "version_epinglee": c.get("version_epinglee", "")}
    if hasattr(mo, "info_dossier"):
        info = mo.info_dossier()
        if info:
            vue["dossier"] = info
    if isinstance(mo, ExternalEngine):
        vue["serveur"] = mo.serveur or str(c.get("serveur") or "")
        if mo.colibri_choisi():
            modele = mo.modele_colibri()
            vue["colibri"] = {"modele": modele, "modele_ok": bool(modele) and Path(modele).is_dir(), "port": mo.port_colibri(), "installe": mo._colibri() is not None}
        if mo.lmstudio_choisi():
            vue["lmstudio"] = {"port": mo.port_lmstudio(), "installe": mo._lms() is not None}
        if mo.exllamav3_choisi():
            vue["exllamav3"] = {"port": mo.port_exllamav3(), "installe": mo._exl() is not None}
        vue["serveurs_geres"] = {"exllamav3": mo._exl() is not None, "colibri": mo._colibri() is not None, "lmstudio": mo._lms() is not None}          # la liste des serveurs dit lesquels sont installés
    return vue


def validate_folder(chemin, installe, nom="llama.cpp"):
    """Le dossier choisi pour un moteur : absolu, utilisable en écriture. Chaîne vide = revenir au dossier par défaut. Refusé tant que le moteur est installé ailleurs (rien n'est déplacé en douce)."""
    chemin = str(chemin or "").strip()
    if installe:
        raise EngineError(_t("{} est déjà installé : désinstalle-le d'abord (tes modèles restent où ils sont), puis change de dossier.").format(nom))
    if not chemin:
        return ""
    p = Path(chemin).expanduser()
    if not p.is_absolute():
        raise EngineError(_t("Donne un chemin complet (par exemple D:/IA/llama.cpp)."))
    try:
        p.mkdir(parents=True, exist_ok=True)
        essai = p / ".lutin-ecriture"
        essai.write_text("ok", encoding="utf-8")
        essai.unlink()
    except OSError as e:
        raise EngineError(_t("Ce dossier n'est pas utilisable en écriture : {}").format(e))
    return str(p)


# --------------------------------------------------------------------------- réglages adaptés à la machine

HELP_CACHE = {}


def server_help(exe):
    """Le texte d'aide de ce llama-server (en minuscules), pour ne passer que les options qu'il connaît : elles changent d'une version à l'autre, et une option inconnue l'empêcherait de démarrer. Gardé en mémoire."""
    cle = str(exe)
    if cle not in HELP_CACHE:
        try:
            r = subprocess.run([cle, "--help"], capture_output=True, timeout=20, cwd=str(Path(cle).parent))
            HELP_CACHE[cle] = (r.stdout + r.stderr).decode("utf-8", "replace").lower()
        except (OSError, subprocess.SubprocessError):
            HELP_CACHE[cle] = ""
    return HELP_CACHE[cle]


def ram_cache_mb(profil):
    """La mémoire vive (en Mio) que llama-server peut garder pour son cache de conversations (`--cache-ram`). Les versions récentes en prennent jusqu'à 8 Go par défaut,
    EN PLUS du modèle : sur une machine où le modèle est dans la carte graphique, la mémoire vive se remplissait quand même au fil des messages (« chargé deux fois »).
    Lutin le borne à 5 % de la mémoire vive, 2 Go au plus, et le coupe (0) sous 12 Go : le cache du créneau en cours, lui, reste (il est avec le modèle)."""
    ram = float(getattr(profil, "ram_go", 0) or 0)
    if ram < 12:
        return 0
    return int(min(2048, ram * 1024 * 0.05))


def without_projector(aide):
    """Les arguments qui chargent le modèle sans projeter son fichier en mémoire, dans les mots du serveur : `--no-mmap` jusqu'à llama.cpp 0.x, `--load-mode none`
    depuis que ces options sont réunies dans `--load-mode` (llama.cpp 1.0, `--no-mmap` retiré). [] si le serveur ne connaît ni l'un ni l'autre."""
    if "--no-mmap" in aide:
        return ["--no-mmap"]
    if "--load-mode" in aide:
        return ["--load-mode", "none"]
    return []


def compressed_cache(aide, variante):
    """Le cache de conversation en 8 bits (`-ctk q8_0 -ctv q8_0`), comme Lutin le demande à Ollama (OLLAMA_KV_CACHE_TYPE) et à TabbyAPI (cache_mode Q8) : la moitié
    de la mémoire pour la même fenêtre. Sans lui, llama.cpp réservait 9,4 Go de cache pour un 32B à 36 864 jetons, Ollama 4,7. Le cache des valeurs compressé
    exige l'attention « flash » : demandée avec, et seulement sur une carte où elle est sûre (CUDA, Metal). [] si le serveur ne connaît pas ces options."""
    if variante not in ("cuda", "metal") or not all(o in aide for o in ("--cache-type-k", "--cache-type-v", "--flash-attn")):
        return []
    return (["-fa", "on"] if "[on|off|auto]" in aide else ["-fa"]) + ["-ctk", "q8_0", "-ctv", "q8_0"]


def without_fit(machine):
    """`machine` (reglages_machine) sans `--fit on`."""
    sortie, i = [], 0
    while i < len(machine):
        if machine[i] == "--fit":
            i += 2
            continue
        sortie.append(machine[i])
        i += 1
    return sortie


def machine_settings(aide, variante, taille_go, profil):
    """Ce que llama.cpp sait régler et que Lutin règle d'après la machine : (arguments, ajuste).
    - le nombre de fils de calcul = les cœurs physiques (llama.cpp en prend parfois trop, ce qui ralentit) ;
    - le cache de conversations en mémoire vive, borné (voir cache_ram_mo) ;
    - sur une carte graphique, un modèle qui ne tient pas entièrement (jugement de Lutin, comme pour Ollama) : `--fit` laisse llama.cpp répartir les couches entre la carte et le processeur, au lieu de tout y forcer.
    `ajuste` vaut True dans ce second cas : l'appelant ne force alors pas toutes les couches sur la carte. Sans profil de machine ou sans l'option dans l'aide, rien n'est ajouté."""
    arguments, ajuste = [], False
    if profil is None:
        return arguments, ajuste
    if getattr(profil, "coeurs", 0) and "--threads" in aide:
        arguments += ["--threads", str(int(profil.coeurs))]
    if "--cache-ram" in aide:
        arguments += ["--cache-ram", str(ram_cache_mb(profil))]
    if variante in ("cuda", "vulkan", "metal") and taille_go and "--fit" in aide:
        from . import model_fit
        if model_fit.judge({"go": taille_go}, profil).get("niveau") in ("limite", "trop_gros"):
            arguments += ["--fit", "on"]
            ajuste = True
    return arguments, ajuste


# --------------------------------------------------------------------------- choix du programme à télécharger

def auto_variant(profil, systeme):
    """cuda (carte NVIDIA), vulkan (autre vraie carte graphique), cpu (aucune : les puces graphiques intégrées au processeur ne comptent pas), metal (Mac)."""
    if systeme == "macos":
        return "metal"
    gpus = [g for g in (getattr(profil, "gpus", None) or []) if getattr(g, "vram_go", 0) >= 3]
    if any(getattr(g, "fabricant", "") == "nvidia" for g in gpus):
        return "cuda"
    return "vulkan" if any(getattr(g, "fabricant", "") in ("amd", "intel") for g in gpus) else "cpu"


def expected_names(systeme, arch, variante):
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


def choose_files(releases, systeme, arch, variante, epinglee=""):
    """(étiquette, [assets]) : la plus récente version qui a tous les fichiers voulus (ou, si une version est épinglée, seulement celle-là), ou None."""
    motifs = expected_names(systeme, arch, variante)
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


def extract(archive, destination):
    """Décompresse un .zip ou un .tar.gz dans `destination`, en refusant tout fichier qui sortirait du dossier."""
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    def sur(nom):
        cible = (destination / nom).resolve()
        if destination != cible and destination not in cible.parents:
            raise EngineError(_t("Archive refusée : un fichier sortirait du dossier d'installation."))
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


def find_server_in(dossier):
    nom = "llama-server.exe" if os.name == "nt" else "llama-server"
    for f in sorted(Path(dossier).rglob(nom)):
        return f
    return None


# --------------------------------------------------------------------------- le moteur

class _CountedStream:
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


class LlamaCppEngine(OpenAIEngine):
    id = engines.LLAMACPP
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
        c = read_config().get(self.id, {})
        envie = os.environ.get("LUTIN_LLAMACPP_URL", "").strip()          # Docker : le conteneur llama.cpp à côté de Lutin (docker-compose.moteurs.yml) ; une adresse réglée dans la page l'emporte
        if envie and not c.get("url"):
            c = dict(c, url=normalize_address(envie), cle=c.get("cle") or os.environ.get("LUTIN_LLAMACPP_CLE", ""))
        return c

    def externe(self):
        return bool(self.config().get("url"))

    def adresse(self):
        if self.externe():
            return self.config()["url"]
        return "http://127.0.0.1:%d/v1" % int(self.config().get("port") or DEFAULT_PORT)

    def cle(self):
        if self.externe():
            return self.config().get("cle", "")
        return self._cle_serveur()

    def _cle_serveur(self):
        """La clé d'accès du serveur que Lutin lance (générée une fois, gardée dans moteurs.json, lisible par l'utilisateur seul) : personne d'autre sur la machine ou le réseau local ne peut lui parler."""
        config = read_config()
        c = config.setdefault(self.id, {})
        if not c.get("cle_serveur"):
            import secrets
            c["cle_serveur"] = secrets.token_urlsafe(24)
            try:
                write_config(config)
            except (OSError, EngineError):
                return c["cle_serveur"]
        return c["cle_serveur"]

    def option_possible(self, option):
        """Le llama-server installé connaît-il cette option ? (d'après son aide ; faux si on ne peut pas la lire)"""
        exe = self.serveur_pret()
        return exe is not None and option in server_help(exe)

    def routeur_possible(self):
        return self.option_possible("--models-preset")

    def routeur_actif(self):
        return not self.externe() and bool(self.config().get("routeur")) and self.routeur_possible()

    def dossier_defaut(self):
        from . import docker_engines
        base = docker_engines.base_engines()          # le dossier des moteurs : choisi dans la page, ou /engines (Docker), ou engines/ dans les données de Lutin
        return base / "llamacpp" if base else None

    def dossier(self):
        """Où llama.cpp vit (programme, modèles, journal) : le dossier choisi par l'utilisateur, sinon celui de Lutin."""
        choisi = self.config().get("dossier")
        return Path(choisi) if choisi else self.dossier_defaut()

    def dossier_propose(self):
        """Le dossier équivalent à celui d'Ollama, sur le même disque : à côté du dossier des modèles d'Ollama quand l'utilisateur lui en a choisi un (« D:/IA/ollama/models » -> « D:/IA/llama.cpp »).
        None quand Ollama est à son emplacement habituel (dans le profil de l'utilisateur) : rien d'équivalent à proposer, le dossier de Lutin convient."""
        ollama = engines.CONTEXT["dossier_ollama"]()
        if not ollama:
            return None
        ollama = Path(ollama)
        if ollama == Path.home() / ".ollama" / "models" or Path.home() in ollama.parents and ".ollama" in ollama.parts:
            return None
        return ollama.parent / "llama.cpp"

    def info_dossier(self):
        """Ce que la page montre : le dossier utilisé, celui qui est proposé, celui par défaut, et la place libre sur chacun ; puis le dossier des modèles."""
        libre = free_space
        actuel, propose, defaut = self.dossier(), self.dossier_propose(), self.dossier_defaut()
        return {"actuel": str(actuel or ""), "propose": str(propose or ""), "defaut": str(defaut or ""), "personnalise": bool(self.config().get("dossier")),
                "libre_go": {"actuel": libre(actuel), "propose": libre(propose) if propose else None, "defaut": libre(defaut)}, "installe": self.serveur_installe() is not None, "modifiable": True,
                "modeles": {"actuel": str(self.dossier_modeles()), "libre_go": libre(self.dossier_modeles()), "modifiable": True, "personnalise": bool(self.config().get("dossier_modeles"))}}

    def dossier_modeles(self):
        personnalise = self.config().get("dossier_modeles")
        if not personnalise and engines.CONTEXT["en_docker"]():
            return Path(os.environ.get("OLLAMA_MODELS") or "/models") / "gguf"          # Docker : à côté des modèles d'Ollama, dans le volume des modèles
        return Path(personnalise) if personnalise else (self.dossier() / "modeles")

    def serveur_installe(self):
        d = self.dossier()
        installe = find_server_in(d / "bin") if d and (d / "bin").is_dir() else None
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
        """Les modèles que Lutin télécharge pour llama.cpp depuis la bibliothèque d'Ollama, rangés comme Ollama le fait (voir ollama_registry.py) : mêmes noms que dans Ollama."""
        return self.dossier_modeles() / "ollama"

    def partages(self):
        """Les modèles utilisables par leur nom d'Ollama (`qwen3:8b`) : ceux qu'Ollama a déjà téléchargés (lus sur place, `origine` « ollama ») et ceux que Lutin a téléchargés pour llama.cpp depuis la même
        bibliothèque (`origine` « lutin »). {nom: {fichier, taille, projecteur, origine}}. Les modèles d'OLLAMA ne sont pas lus sous Docker (autre conteneur), ni avec un serveur externe, ni si l'utilisateur a
        coupé le partage (réglage `partager_ollama`) ; ceux que LUTIN télécharge pour llama.cpp sont toujours listés, Docker compris (sinon un modèle téléchargé n'apparaissait jamais). Relu au plus toutes les
        10 secondes (la page interroge souvent)."""
        if self.externe():
            return {}
        docker = engines.CONTEXT["en_docker"]()
        dossier = None if docker else (engines.CONTEXT["dossier_ollama"]() if self.config().get("partager_ollama") is not False else None)
        cle = (str(dossier or ""), str(self.bibliotheque()))
        cache = SHARED_CACHE
        if cache.get("cle") == cle and time.time() - cache.get("quand", 0) < 10:
            return cache["modeles"]
        from . import ollama_shared_models
        lus = {n: dict(v, origine="ollama") for n, v in ollama_shared_models.read_shared(dossier).items()} if dossier else {}
        lus.update({n: dict(v, origine="lutin") for n, v in ollama_shared_models.read_shared(self.bibliotheque()).items()})
        cache.update(cle=cle, quand=time.time(), modeles=lus)
        return lus

    def telecharger_ollama(self, modele, progression):
        """Télécharge un modèle de la bibliothèque d'Ollama (n'importe lequel : officiel ou de la communauté) pour llama.cpp, sans Ollama."""
        if self.externe():
            raise EngineError(_t("Un serveur externe gère ses modèles lui-même."))
        if engines.CONTEXT["hors_ligne"]():
            raise EngineError(_t("Mode hors ligne : aucun téléchargement."))
        from . import ollama_registry
        ollama_registry.download(modele, self.bibliotheque(), progression)
        SHARED_CACHE.clear()

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

    def charge_connue(self):
        return not self.externe()          # le serveur que Lutin gère : Lutin sait s'il tourne ; un serveur distant ne le dit pas

    def en_memoire(self, modele):
        if self.externe():
            return super().en_memoire(modele)
        with SERVER["verrou"]:
            p = SERVER["proc"]
            if p is not None and p.poll() is None and SERVER.get("pret", True) and (SERVER["modele"] == modele or (SERVER["modele"] == ROUTER and modele in SERVER["noms"])):
                return {"taille": 0, "vram": 0}          # started but still reading its model: not yet
        return None

    def vecteurs(self, modele, textes, delai=60):
        """Les vecteurs de ces textes. Avec un llama-server géré, seul le mode routeur peut servir un modèle d'embeddings à côté du modèle de conversation sans le décharger."""
        if not self.externe():
            if not self.routeur_actif():
                raise EngineError(_t("Avec llama.cpp, la recherche par le sens demande le mode routeur (Réglages > Moteur > Mode routeur)."))
            self.demarrer(modele, DEFAULT_CTX)
        return super().vecteurs(modele, textes, delai)

    def aptitudes(self):
        # D'après la documentation de llama-server (tools/server/README.md, lue le 2026-11-16) : `grammar` et `json_schema` contraignent la sortie, `id_slot` donne une place à une
        # demande, `cache_prompt` (vrai par défaut) évite de relire le début commun de deux requêtes. Lutin n'envoie encore ni `id_slot` ni `cache_prompt` (plan, étape 6, point 2).
        # Les outils passent par le gabarit du modèle (--jinja). Un modèle qui ne tient pas dans la mémoire vidéo ne se charge pas ; et c'est ce moteur, pas la boucle, qui démarre son serveur.
        return engine_capabilities.EngineCapabilities(tools=engine_capabilities.TEMPLATE, grammar=engine_capabilities.YES, slots=engine_capabilities.YES,
                                                      prompt_cache=engine_capabilities.ON_REQUEST, embeddings=engine_capabilities.YES, token_counts=engine_capabilities.YES,
                                                      starts_on_demand=False, spills_to_cpu=False, experts_in_ram=self.experts_en_ram())

    def experts_en_ram(self):
        """Le serveur sait-il garder les experts d'un modèle à experts en mémoire vive ? `--fit` les place lui-même, `--n-cpu-moe` les y met sur demande.
        Pas encore installé : oui, Lutin installe une version récente qui connaît les deux."""
        exe = self.serveur_pret()
        if exe is None:
            return True
        aide = server_help(exe)
        return "--fit" in aide or "--n-cpu-moe" in aide

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
        ctx = int((corps.get("options") or {}).get("num_ctx") or DEFAULT_CTX)
        with SERVER["verrou"]:
            SERVER["actifs"] += 1
        try:
            self.demarrer(modele, ctx, propres=1)
        except BaseException:
            self._fini()
            raise
        return True

    @staticmethod
    def _fini():
        with SERVER["verrou"]:
            SERVER["actifs"] = max(0, SERVER["actifs"] - 1)

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
        return _CountedStream(flux, self._fini) if compte else flux

    # -- le serveur géré
    def _besoin_redemarrage(self, modele, ctx, routeur):
        """Vrai si le serveur qui tourne ne convient pas à cette demande. Un contexte plus PETIT que l'actuel convient : on ne redémarre jamais pour rétrécir."""
        p = SERVER["proc"]
        if p is None or p.poll() is not None:
            return False          # rien à interrompre
        if routeur:
            return not (SERVER["modele"] == ROUTER and modele in SERVER["noms"] and ctx - SERVER["ctx"] < 1024)
        return not (SERVER["modele"] == modele and ctx - SERVER["ctx"] < 1024)

    def _attendre_reponses(self, modele, ctx, routeur, propres, maxi=900):
        """Un autre modèle ou un contexte plus grand demande un redémarrage : on attend que les réponses en cours finissent (sinon elles seraient coupées en plein milieu)."""
        fin = time.time() + maxi
        while time.time() < fin:
            with SERVER["verrou"]:
                if SERVER["actifs"] - propres <= 0 or not self._besoin_redemarrage(modele, ctx, routeur):
                    return
            time.sleep(0.3)

    def demarrer(self, modele, ctx=DEFAULT_CTX, attente=STARTUP_MAX_S, propres=0):
        exe = self.serveur_pret()
        if exe is None:
            raise EngineError(_t("llama.cpp n'est pas installé : Réglages > Moteur > Installer."))
        fichier = self._fichier_modele(modele)
        routeur = self.routeur_actif()
        self._attendre_reponses(modele, ctx, routeur, propres)
        with SERVER["verrou"]:
            p = SERVER["proc"]
            if p is not None and p.poll() is None and not self._besoin_redemarrage(modele, ctx, routeur):
                return          # le serveur (ou le routeur, qui charge et décharge tout seul) convient déjà
            self.arreter()
            port = int(self.config().get("port") or DEFAULT_PORT)
            variante = (self.config().get("variante_installee") or "cpu")
            aide = server_help(exe)
            commande = [str(exe), "--host", "127.0.0.1", "--port", str(port), "--jinja"]
            environnement = None
            if "llama_api_key" in aide:          # la clé passe par l'environnement du serveur : sur la ligne de commande, tout programme de la machine la lisait dans la liste des processus
                environnement = dict(os.environ, LLAMA_API_KEY=self._cle_serveur())
            elif "--api-key" in aide:          # une version qui ne lit pas la variable : l'ancienne manière
                commande += ["--api-key", self._cle_serveur()]
            commun = self.partages().get(str(modele))
            try:
                taille_go = Path(fichier).stat().st_size / 1e9
                machine, ajuste = machine_settings(aide, variante, taille_go, (engines.CONTEXT.get("profil_attendu") or engines.CONTEXT["profil"])())
            except Exception:  # noqa: BLE001  (les réglages adaptés ne doivent jamais empêcher de démarrer)
                machine, ajuste = [], False
            moe = int(self.config().get("n_cpu_moe") or 0)
            if routeur:
                ctx = max(ctx, DEFAULT_CTX)
                noms, texte = self._preset(ctx, variante, ajuste, machine, moe)
                preset = self.dossier() / "modeles.ini"
                preset.parent.mkdir(parents=True, exist_ok=True)
                preset.write_text(texte, encoding="utf-8")
                commande += ["--models-preset", str(preset), "--models-max", str(int(self.config().get("modeles_max") or DEFAULT_MAX_MODELS))]
                if "--cache-ram" in machine:
                    commande += machine[machine.index("--cache-ram"):machine.index("--cache-ram") + 2]          # le routeur le transmet aux serveurs qu'il lance
                SERVER["noms"] = noms
            else:
                commande += ["-m", str(fichier), "-c", str(ctx)]
                if commun is not None and commun.get("projecteur") and Path(fichier) == commun["fichier"]:
                    commande += ["--mmproj", str(commun["projecteur"])]          # un modèle d'Ollama qui voit les images : son projecteur est dans le même dossier
                if moe and "--n-cpu-moe" in aide:
                    # Experts imposés dans les réglages : `--fit` renonce quand des placements de tenseurs sont déjà donnés (common/fit.cpp : « tensor_buft_overrides
                    # already set by user, abort ») et les couches resteraient au choix par défaut de llama.cpp. La recette habituelle à la place : toutes les
                    # couches sur la carte, les experts des N premières couches sur le processeur.
                    machine, ajuste = without_fit(machine), False
                commande += machine
                if moe and "--n-cpu-moe" in aide:
                    commande += ["--n-cpu-moe", str(moe)]          # modèle « à experts » : ses experts restent sur le processeur, le reste va sur la carte
                gpu = variante in ("cuda", "vulkan", "metal")
                if gpu and not ajuste:
                    commande += ["-ngl", "99"]          # tout le modèle sur la carte ; s'il est trop gros pour elle, `--fit` (ci-dessus) répartit les couches avec le processeur
                if gpu and not moe:          # aussi avec `--fit` : un modèle « limite » pour la carte (22 Go sur 24) était gardé EN ENTIER en mémoire vive par-dessus ses couches sur la carte
                    commande += without_projector(aide)          # le fichier n'est pas laissé en mémoire vive une fois ses poids passés dans la carte (sinon : 22 Go en VRAM ET 22 Go en RAM, et un PC qui sature)
                commande += [] if SERVER.get("cache_8_refuse") else compressed_cache(aide, variante)
            journal = self.dossier() / "serveur.log"
            journal.parent.mkdir(parents=True, exist_ok=True)
            sortie = open(journal, "wb")
            try:
                SERVER["proc"] = subprocess.Popen(commande, stdout=sortie, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(Path(exe).parent), env=environnement)
            except OSError as e:
                raise EngineError(_t("Impossible de lancer llama-server : {}").format(e))
            finally:
                sortie.close()          # le processus garde sa propre copie du fichier journal
            SERVER.update({"pret": False, "modele": ROUTER if routeur else modele, "ctx": ctx, "cache_8": "-ctk" in commande or "cache-type-k = q8_0" in (texte if routeur else "")})
        lance = SERVER["proc"]
        fin = time.time() + attente
        while time.time() < fin:
            if lance is None or SERVER["proc"] is not lance:
                raise EngineError(_t("Le serveur llama.cpp a été arrêté ou remplacé pendant son démarrage : relance la demande."))
            if lance.poll() is not None:
                if SERVER.get("cache_8") and not SERVER.get("cache_8_refuse"):
                    SERVER["cache_8_refuse"] = True          # a model or a card that refuses flash attention: started as before, for the rest of the session
                    from . import core as _m
                    _m.log_event("llama-server s'est arrêté au démarrage avec le cache en 8 bits ({}) : relancé sans.".format(self._fin_du_journal()))
                    return self.demarrer(modele, ctx, attente, propres)
                fin = self._fin_du_journal()
                raise EngineError(_t("llama-server s'est arrêté au démarrage : {}").format(fin) + library_help(fin))
            if self._pret():
                SERVER["pret"] = True          # the model is in memory: until now the pill says « loading »
                return
            time.sleep(0.5)
        self.arreter()
        raise EngineError(_t("llama-server ne répond pas après {} s : {}").format(attente, self._fin_du_journal()))

    def _preset(self, ctx, variante, ajuste, machine, moe):
        """(noms des modèles, texte du fichier de préréglages) pour tous les modèles de conversation et d'embeddings installés."""
        modeles = []
        for nom in self.modeles()["installes"]:
            try:
                f = self._fichier_modele(nom)
            except EngineError:
                continue
            commun = self.partages().get(str(nom))
            projecteur = commun.get("projecteur") if commun is not None and Path(f) == commun["fichier"] else None
            modeles.append((nom, f, projecteur))
        fils = int(machine[machine.index("--threads") + 1]) if "--threads" in machine else 0
        moe = moe if moe and self.option_possible("--n-cpu-moe") else 0
        tout_sur_la_carte = variante in ("cuda", "vulkan", "metal") and (not ajuste or bool(moe))          # experts imposés : toutes les couches sur la carte (voir demarrer)
        cache = int(machine[machine.index("--cache-ram") + 1]) if "--cache-ram" in machine else None
        gpu = variante in ("cuda", "vulkan", "metal")
        reglages = {"cache_ram": cache, "fils": fils, "n_cpu_moe": moe, "ngl": 99 if tout_sur_la_carte else 0,
                    "sans_mmap": bool(gpu and not moe and self.option_possible("--no-mmap")),
                    "chargement_direct": bool(gpu and not moe and not self.option_possible("--no-mmap") and self.option_possible("--load-mode")),
                    "cache_8_bits": not SERVER.get("cache_8_refuse") and variante in ("cuda", "metal") and all(self.option_possible(o) for o in ("--cache-type-k", "--cache-type-v", "--flash-attn"))}
        return tuple(n for n, _, _ in modeles), preset_text(modeles, ctx, reglages)

    def _pret(self):
        """Le serveur a fini de charger le modèle ? `/health` répond « ok » (503 pendant le chargement) ; une ancienne version sans /health : on se contente de /models."""
        try:
            return str(self._json("/health", None, 3).get("status", "ok")) == "ok"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return OpenAIEngine.actif(self)
            return False          # 503 : il charge encore
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _fin_du_journal(self):
        try:
            return " ".join((self.dossier() / "serveur.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:])[-300:]
        except OSError:
            return ""

    def arreter(self):
        with SERVER["verrou"]:
            p = SERVER["proc"]
            SERVER.update({"proc": None, "modele": "", "ctx": 0, "noms": ()})
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
            raise EngineError(_t("Modèle introuvable dans {} : « {} ».").format(dossier, modele))
        return f

    # -- ce que la page peut faire
    def statut(self):
        if self.externe():
            actif = OpenAIEngine.actif(self)
            return {"installe": True, "actif": actif, "version": "", "detail": _t("Connecté à {}").format(self.adresse()) if actif else _t("Le serveur {} ne répond pas.").format(self.adresse()), "mode": "externe"}
        exe = self.serveur_installe()
        with SERVER["verrou"]:
            p = SERVER["proc"]
            tourne = p is not None and p.poll() is None
            modele = SERVER["modele"] if tourne else ""
        detail = (_t("Routeur démarré : {} modèle(s) disponibles, chargés à la demande.").format(len(SERVER["noms"])) if modele == ROUTER else _t("Serveur démarré avec « {} ».").format(modele)) if tourne else (_t("Installé : il démarre à la demande.") if exe or self.serveur_pret() else _t("Pas installé."))
        return {"installe": self.serveur_pret() is not None, "actif": tourne, "version": self.version(), "detail": detail, "mode": "gere", "installe_par_lutin": exe is not None}

    def actions(self):
        systeme = _system()
        vide = _t("Sans objet avec un serveur externe : l'adresse est réglée ci-dessous.")
        if self.externe():
            return {a: {"possible": False, "raison": vide} for a in engines.ACTIONS}
        exe = self.serveur_installe()
        par_lutin = exe is not None
        installer = {"possible": not par_lutin and systeme in ("windows", "linux", "macos") and not engines.CONTEXT["hors_ligne"](),
                     "raison": _t("Télécharge le programme officiel adapté à cette machine (de 25 Mo à environ 700 Mo selon la carte graphique).") if not par_lutin else _t("Déjà installé.")}
        if engines.CONTEXT["hors_ligne"]():
            installer["raison"] = _t("Mode hors ligne : aucun téléchargement.")
        elif systeme not in ("windows", "linux", "macos"):
            installer["raison"] = _t("Système non pris en charge.")
        hors_lutin = self.serveur_pret() is not None and not par_lutin
        sans = _t("Pas installé par Lutin.") if hors_lutin else _t("Pas installé.")
        with SERVER["verrou"]:
            tourne = SERVER["proc"] is not None and SERVER["proc"].poll() is None
        return {"installer": installer,
                "mettre_a_jour": {"possible": par_lutin and not engines.CONTEXT["hors_ligne"](), "raison": _t("Télécharge la dernière version et remplace l'actuelle ; tes modèles et ton dossier sont gardés.") if par_lutin else sans},
                "desinstaller": {"possible": par_lutin, "raison": _t("Supprime le programme (tes modèles restent).") if par_lutin else sans},
                "reinstaller": {"possible": par_lutin and not engines.CONTEXT["hors_ligne"](), "raison": _t("Télécharge de nouveau la dernière version, en gardant tes modèles.") if par_lutin else sans},
                "demarrer": {"possible": False, "raison": _t("Il démarre tout seul quand tu discutes avec un modèle.")},
                "arreter": {"possible": tourne, "raison": _t("Arrête le serveur et libère la mémoire.") if tourne else _t("Il n'est pas démarré.")}}

    def faire(self, action, progression):
        if action in ("installer", "reinstaller", "mettre_a_jour"):
            return self.installer(progression, reinstaller=action != "installer")
        if action == "desinstaller":
            return self.desinstaller()
        if action == "arreter":
            return self.arreter()
        raise EngineError(_t("Action impossible avec ce moteur."))

    def installer(self, progression, reinstaller=False, http_json=None, telecharger=None):
        if engines.CONTEXT["hors_ligne"]():
            raise EngineError(_t("Mode hors ligne : aucun téléchargement."))
        import platform
        systeme, arch = _system(), platform.machine().lower()
        config = read_config()
        voulue = config.get(self.id, {}).get("variante", "auto")
        variante = voulue if voulue in ("cuda", "vulkan", "cpu", "metal") else auto_variant((engines.CONTEXT.get("profil_attendu") or engines.CONTEXT["profil"])(), systeme)
        epinglee = str(config.get(self.id, {}).get("version_epinglee") or "")
        progression(_t("Recherche de la version {}…").format(epinglee) if epinglee else _t("Recherche de la dernière version…"), 0, 0)
        try:
            releases = [(http_json or _http_json)(API_VERSION + epinglee)] if epinglee else (http_json or _http_json)(API_RELEASES)
        except _offline.OfflineError:
            raise
        except (urllib.error.URLError, OSError, ValueError) as e:
            releases = None
            if http_json is None:          # l'API de GitHub refuse (limite de requêtes, HTTP 403) : les pages publiques des publications donnent les mêmes fichiers
                try:
                    from . import updates
                    releases = updates.releases_from_page("ggml-org/llama.cpp", r"b\d+", 4, epinglee)
                except (OSError, ValueError):
                    releases = None
            if releases is None:
                raise EngineError(_t("GitHub ne répond pas : {}").format(e))
        choix = choose_files(releases, systeme, arch, variante, epinglee)
        if choix is None and variante != "cpu":
            variante = "cpu"
            choix = choose_files(releases, systeme, arch, variante, epinglee)
        if choix is None:
            raise EngineError(_t("Aucun programme llama.cpp publié pour ce système ({} {}). Installe-le à la main : https://github.com/ggml-org/llama.cpp/releases").format(systeme, arch))
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
                f = (telecharger or ollama_client.download_file)(url, telechargement / a["name"], lambda t, fait, tot, d=deja: progression(_t("Téléchargement de {}").format(a["name"]), d + fait, total_octets), taille_min=100_000)
            except (RuntimeError, OSError) as e:
                raise EngineError(str(e))
            self._verifier_empreinte(f, a)
            deja += int(a.get("size") or 0)
            progression(_t("Installation…"), deja, total_octets)
            extract(f, neuf)
        exe = find_server_in(neuf)
        if exe is None:
            shutil.rmtree(neuf, ignore_errors=True)
            raise EngineError(_t("llama-server est introuvable dans l'archive téléchargée."))
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
        progression(_t("Remplacement de l'ancienne version…"), deja, total_octets)
        replace_folder(neuf, base / "bin", liberer=lambda: free_process(base))
        shutil.rmtree(telechargement, ignore_errors=True)
        (base / "version.txt").write_text("{} ({})".format(etiquette, variante), encoding="utf-8")
        config = read_config()
        config.setdefault(self.id, {})["variante_installee"] = variante
        write_config(config)
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
            raise EngineError(_t("Le fichier téléchargé est corrompu (empreinte différente de celle publiée) : réessaie."))

    def desinstaller(self):
        self.arreter()
        base = self.dossier()
        if base is None or not (base / "bin").is_dir():
            raise EngineError(_t("llama.cpp n'a pas été installé par Lutin : il n'y a rien à supprimer ici."))
        shutil.rmtree(base / "bin", ignore_errors=True)
        (base / "version.txt").unlink(missing_ok=True)

    # -- les modèles (fichiers GGUF)
    def telechargeable(self):
        if self.externe():
            return {"possible": False, "raison": _t("Un serveur externe gère ses modèles lui-même."), "genre": "aucun"}
        if engines.CONTEXT["hors_ligne"]():
            return {"possible": False, "raison": _t("Mode hors ligne : aucun téléchargement."), "genre": "huggingface"}
        return {"possible": True, "raison": _t("Les modèles se trouvent sur Hugging Face, au format GGUF."), "genre": "huggingface"}

    def chercher_modeles(self, terme, http_json=None):
        """Les dépôts GGUF de Hugging Face qui correspondent (les plus téléchargés d'abord)."""
        terme = re.sub(r"[^\w.\- ]", "", str(terme or ""))[:60].strip()
        if not terme:
            raise EngineError(_t("Écris le nom d'un modèle à chercher (par exemple qwen3 ou gemma)."))
        url = API_HF + "?" + urllib.parse.urlencode({"search": terme, "filter": "gguf", "sort": "downloads", "direction": "-1", "limit": "15"})
        try:
            lus = (http_json or _http_json)(url)
        except _offline.OfflineError:
            raise
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise EngineError(_t("Hugging Face ne répond pas : {}").format(e))
        return [{"id": m.get("id", ""), "telechargements": int(m.get("downloads") or 0), "likes": int(m.get("likes") or 0)} for m in lus if RE_REPO.match(str(m.get("id", "")))]

    def fichiers_du_depot(self, repo, http_json=None):
        """Les fichiers .gguf d'un dépôt (hors morceaux d'un modèle coupé, projecteurs d'images et matrice d'importance « .imatrix.gguf »), avec leur taille."""
        if not RE_REPO.match(str(repo or "")):
            raise EngineError(_t("Nom de dépôt invalide (attendu : auteur/nom)."))
        try:
            lus = (http_json or _http_json)("{}/{}/tree/main".format(API_HF, repo))
        except _offline.OfflineError:
            raise
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise EngineError(_t("Hugging Face ne répond pas : {}").format(e))
        sortie = []
        for f in lus:
            chemin = str(f.get("path", ""))
            if f.get("type") == "file" and RE_FILE.match(chemin) and not RE_SHARD.search(chemin) and "mmproj" not in chemin.lower() and "imatrix" not in chemin.lower():
                sortie.append({"fichier": chemin, "taille": int((f.get("lfs") or {}).get("size") or f.get("size") or 0)})
        return sorted(sortie, key=lambda x: x["taille"])

    def telecharger_modele(self, repo, fichier, progression, telecharger=None):
        if not self.telechargeable()["possible"]:
            raise EngineError(self.telechargeable()["raison"])
        if not RE_REPO.match(str(repo or "")) or not RE_FILE.match(str(fichier or "")) or ".." in str(fichier):
            raise EngineError(_t("Dépôt ou fichier invalide."))
        from . import ollama_client
        nom = fichier.replace("/", "_")
        destination = self.dossier_modeles() / nom
        url = "https://huggingface.co/{}/resolve/main/{}".format(repo, urllib.parse.quote(fichier))
        try:
            (telecharger or ollama_client.download_file)(url, destination, progression, taille_min=1_000_000)
        except (RuntimeError, OSError) as e:
            raise EngineError(str(e))
        return destination.with_suffix("").name

    def supprimer_modele(self, nom):
        commun = self.partages().get(str(nom))
        if commun is not None and not (self.dossier_modeles() / (str(nom) + ".gguf")).is_file():
            if commun.get("origine") == "ollama":
                raise EngineError(_t("« {} » appartient à Ollama : supprime-le depuis Ollama (llama.cpp ne fait que le lire).").format(nom))
            from . import ollama_registry
            with SERVER["verrou"]:
                if SERVER["modele"] == nom:
                    self.arreter()
            ollama_registry.remove(str(nom), self.bibliotheque())
            SHARED_CACHE.clear()
            return
        f = self._fichier_modele(nom)
        with SERVER["verrou"]:
            if SERVER["modele"] == nom:
                self.arreter()
        f.unlink()


class ExternalEngine(OpenAIEngine):
    """Un autre serveur compatible OpenAI (vLLM, Strata, ik_llama.cpp, un llama-server distant…) : une adresse et, si besoin, une clé. Lutin n'installe rien, il s'y connecte.
    Ses sous-classes (`MoteurServeurGere`) sont les serveurs que Lutin installe et lance lui-même : leur `serveur` est fixe (ADR 0020)."""
    id = engines.OPENAI
    nom = "Autre serveur (compatible OpenAI)"
    adresse_modifiable = True
    serveur = ""          # "" : un serveur joint par son adresse seule ; sinon l'un de engines.MANAGED_SERVERS

    @property
    def description(self):
        if self.exllamav3_choisi():
            return _t("ExLlamaV3, installé et lancé par Lutin à travers TabbyAPI (son serveur officiel), sur cette machine, avec une carte NVIDIA. Les modèles (format EXL3) se téléchargent depuis l'onglet Modèles.")
        if self.lmstudio_choisi():
            return _t("LM Studio, installé et lancé par Lutin sans son interface (son démon « llmster »), sur cette machine. Les modèles se téléchargent depuis l'onglet Modèles.")
        if self.colibri_choisi():
            return _t("Colibri, installé et lancé par Lutin sur cette machine (expérimental). Son modèle se télécharge depuis l'onglet Modèles.")
        return _t("Tout serveur qui parle l'interface OpenAI : vLLM, Strata, ik_llama.cpp, un llama-server sur un autre ordinateur… Tu donnes son adresse ; il gère ses modèles lui-même. ExLlamaV3, LM Studio et Colibri, que Lutin sait installer, ont chacun leur carte.")

    @property
    def points_forts(self):
        if self.exllamav3_choisi():
            return (_t("Très rapide sur une carte NVIDIA, avec des modèles très compressés (EXL3) qui gardent leur qualité."),
                    _t("Installation, démarrage, arrêt, mise à jour et téléchargement de modèles depuis Lutin ; il n'écoute que sur cette machine (127.0.0.1)."))
        if self.lmstudio_choisi():
            return (_t("Installation, démarrage, arrêt, mise à jour et téléchargement de modèles depuis Lutin, avec l'installeur officiel de LM Studio."),
                    _t("Il n'écoute que sur cette machine (127.0.0.1)."))
        if self.colibri_choisi():
            return (_t("Installation, mise à jour, suppression, démarrage et arrêt depuis Lutin, avec somme SHA-256 vérifiée."),
                    _t("Il n'écoute que sur cette machine (127.0.0.1)."))
        return (_t("Universel : s'adapte à n'importe quel serveur de ce genre, sur cette machine ou sur le réseau."),
                _t("Lutin n'installe ni ne démarre rien : le serveur reste maître de ses réglages."))

    @property
    def points_faibles(self):
        if self.exllamav3_choisi():
            return (_t("Carte NVIDIA obligatoire ; l'installation télécharge plusieurs Go (torch) dans un environnement Python dédié."),
                    _t("Lutin n'a pas essayé cette intégration sur une vraie carte NVIDIA ; TabbyAPI est un projet communautaire en évolution rapide."))
        if self.lmstudio_choisi():
            return (_t("Lutin lance l'installeur officiel de LM Studio (lmstudio.ai) sans l'avoir testé sur une vraie installation."),
                    _t("Lutin ne le désinstalle pas : ses modèles sont dans son dossier (~/.lmstudio)."))
        if self.colibri_choisi():
            return (_t("Moteur jeune : le démarrage avec un vrai modèle n'a pas été vérifié avec Lutin."),
                    _t("Il demande un modèle préparé par Colibri (plusieurs dizaines de Go) : Lutin ne le télécharge pas."))
        return (_t("Lutin ne peut ni installer, ni démarrer, ni mettre à jour ce serveur, ni lui télécharger de modèle."),
                _t("Selon le serveur, les appels d'outils ou les images peuvent ne pas fonctionner."))

    def config(self):
        return section(read_config(), self.id)

    # -- Colibri : installé et lancé par Lutin (sur cette machine, 127.0.0.1)
    def colibri_choisi(self):
        return self.serveur == engines.COLIBRI

    def port_colibri(self):
        from . import colibri
        try:
            p = int(self.config().get("port_colibri") or 0)
        except (TypeError, ValueError):
            p = 0
        return p if 1024 <= p <= 65535 else colibri.DEFAULT_PORT

    # -- LM Studio : installé et lancé par Lutin sans son interface (démon llmster + commande lms), sur cette machine seulement
    def lmstudio_choisi(self):
        return self.serveur == engines.LMSTUDIO

    def port_lmstudio(self):
        from . import lmstudio
        try:
            p = int(self.config().get("port_lmstudio") or 0)
        except (TypeError, ValueError):
            p = 0
        return p if 1024 <= p <= 65535 else lmstudio.DEFAULT_PORT

    # -- ExLlamaV3 : installé et lancé par Lutin à travers TabbyAPI (environnement Python dédié), sur cette machine seulement, carte NVIDIA
    def exllamav3_choisi(self):
        return self.serveur == engines.EXLLAMAV3

    def charge_connue(self):
        return self.exllamav3_choisi()          # TabbyAPI dit quel modèle il a chargé (GET /v1/model) ; les autres serveurs de cette carte ne le disent pas

    def en_memoire(self, modele):
        """ExLlamaV3 charge le modèle à la première demande : tant qu'aucune n'est faite, ou que le serveur est arrêté, rien n'est en mémoire."""
        if not self.exllamav3_choisi():
            return super().en_memoire(modele)
        try:
            charge = self._json("/model", None, 3)
        except (urllib.error.URLError, OSError, ValueError):
            return None          # arrêté, ou « aucun modèle chargé » (TabbyAPI répond alors par une erreur)
        return {"taille": 0, "vram": 0} if str(charge.get("id") or "") == str(modele) else None

    def cache_reserve(self, modele, ctx):
        """TabbyAPI réserve `cache_size` en Q8 dès le chargement, sur la carte seule : sans ce compte, le garde-fou laissait charger un 27B de 16,5 Go dans 18 Go libres,
        et TabbyAPI répondait « Insufficient VRAM in split for model and cache »."""
        if not self.exllamav3_choisi() or not modele or not ctx or Path(str(modele)).name != str(modele):
            return 0
        from . import exllamav3, kv_cache, model_fit
        kv = kv_cache.of_folder(exllamav3.folder_models(self._dossiers()) / str(modele)) or model_fit.DEFAULT_KV_MB_PER_1K
        return int(kv * (int(ctx) / 1000) / 1024 * 0.5 * 1024 ** 3)

    def port_exllamav3(self):
        from . import exllamav3
        try:
            p = int(self.config().get("port_exllamav3") or 0)
        except (TypeError, ValueError):
            p = 0
        return p if 1024 <= p <= 65535 else exllamav3.DEFAULT_PORT

    def _exl(self):
        """{tabby, lib} si ExLlamaV3 est installé par Lutin, sinon None."""
        from . import exllamav3
        return exllamav3.installed(self._dossiers()) if engines.CONTEXT["donnees"]() else None

    def _demarrer_apres_installation(self, progression, total, nom, demarrer, patience):
        """Un serveur qu'on vient d'installer est démarré tout de suite : on ne laisse pas l'utilisateur devant un bouton « Démarrer » qu'il devrait deviner. Un échec ne défait pas l'installation : il est dit."""
        progression(_t("Étape {}/{} : démarrage de {} ({})…").format(total, total, nom, patience), total - 1, total)
        try:
            demarrer()
        except (ValueError, OSError, subprocess.SubprocessError) as e:
            progression("⚠ " + _t("{} est installé, mais il ne démarre pas : {} — clique sur « Démarrer » pour réessayer.").format(nom, str(e).splitlines()[0][:160]), total, total)
            return
        progression(_t("Installé et démarré : {}.").format(nom), total, total)

    def _contexte(self):
        """La longueur de conversation des réglages de Lutin (en jetons) : TabbyAPI ne réserve en mémoire vidéo que celle-là, pas la longueur maximale du modèle."""
        try:
            from . import core as _m
            return int(_m.settings().get("num_ctx") or 0)
        except Exception:  # noqa: BLE001  (réglages illisibles : la valeur prudente d'exllamav3.py)
            return 0

    def _lms(self):
        """Le chemin de la commande `lms` si LM Studio (ou son démon) est installé, sinon None."""
        from . import lmstudio
        return lmstudio.lms_path()

    def modele_colibri(self):
        from . import colibri
        return str(self.config().get("modele_colibri") or "") or colibri.model_of_setup()          # sinon celui que « coli setup » a préparé

    def _dossiers(self):
        d = {"donnees": engines.CONTEXT["donnees"]()}
        choisi = self.config().get("dossier_modeles") if self.exllamav3_choisi() else None
        if choisi:
            d["modeles"] = choisi
        return d

    def info_dossier(self):
        """Les mêmes lignes que pour Ollama et llama.cpp : où le serveur géré par Lutin est installé et où sont ses modèles ({} quand le serveur choisi n'est pas géré par Lutin).
        Le dossier d'installation se choisit une fois pour tous les moteurs (« Dossier des moteurs ») ; celui des modèles, moteur par moteur quand c'est possible."""
        libre = free_space
        dossiers = self._dossiers()
        if self.exllamav3_choisi():
            from . import exllamav3
            actuel, modeles = exllamav3.folder(dossiers), exllamav3.folder_models(dossiers)
            return {"actuel": str(actuel), "propose": "", "defaut": str(actuel), "personnalise": False, "libre_go": {"actuel": libre(actuel), "propose": None, "defaut": libre(actuel)}, "installe": self._exl() is not None,
                    "modifiable": False, "par": "moteurs", "modeles": {"actuel": str(modeles), "libre_go": libre(modeles), "modifiable": True, "personnalise": bool(self.config().get("dossier_modeles"))}}
        if self.colibri_choisi():
            from . import colibri
            actuel, modeles = colibri.folder_colibri(dossiers), colibri.folder_models(dossiers)
            return {"actuel": str(actuel), "propose": "", "defaut": str(actuel), "personnalise": False, "libre_go": {"actuel": libre(actuel), "propose": None, "defaut": libre(actuel)}, "installe": self._colibri() is not None,
                    "modifiable": False, "par": "moteurs", "modeles": {"actuel": str(modeles), "libre_go": libre(modeles), "modifiable": False, "personnalise": False}}
        if self.lmstudio_choisi():
            actuel = Path.home() / ".lmstudio"
            return {"actuel": str(actuel), "propose": "", "defaut": str(actuel), "personnalise": False, "libre_go": {"actuel": libre(actuel), "propose": None, "defaut": libre(actuel)}, "installe": self._lms() is not None,
                    "modifiable": False, "par": "programme", "modeles": {"actuel": str(actuel / "models"), "libre_go": libre(actuel / "models"), "modifiable": False, "personnalise": False}}
        return {}

    def arreter_gere(self):
        """Arrête le serveur géré par Lutin qui est choisi en ce moment (Colibri, LM Studio ou ExLlamaV3), s'il tourne. Vrai si quelque chose a été arrêté."""
        if not (self.colibri_choisi() or self.lmstudio_choisi() or self.exllamav3_choisi()) or not OpenAIEngine.actif(self):
            return False
        if self.exllamav3_choisi():
            from . import exllamav3
            exllamav3.stop(self._dossiers())
        elif self.lmstudio_choisi():
            from . import lmstudio
            if not lmstudio.stop():
                raise EngineError(_t("LM Studio n'a pas confirmé son arrêt."))
        else:
            self._arreter_colibri()
        return True

    def _colibri(self):
        """(version, dossier de coli) si Colibri est installé par Lutin, sinon None."""
        from . import colibri
        return colibri.installed(self._dossiers()) if engines.CONTEXT["donnees"]() else None

    def version(self):
        if self.exllamav3_choisi():
            e = self._exl()
            return (e["lib"] or e["tabby"][:7]) if e else ""
        t = self._colibri() if self.colibri_choisi() else None
        return t[0] if t else ""

    def adresse(self):
        if self.exllamav3_choisi():
            return "http://127.0.0.1:{}/v1".format(self.port_exllamav3())
        if self.lmstudio_choisi():
            return "http://127.0.0.1:{}/v1".format(self.port_lmstudio())
        if self.colibri_choisi():
            return "http://127.0.0.1:{}/v1".format(self.port_colibri())
        return self.config().get("url", "")

    def cle(self):
        return self.config().get("cle", "")

    def statut(self):
        if self.exllamav3_choisi():
            e = self._exl()
            actif = OpenAIEngine.actif(self)
            if actif:
                detail = _t("ExLlamaV3 répond sur {}").format(self.adresse())
            elif e:
                detail = _t("ExLlamaV3 est installé mais son serveur est arrêté : démarre-le.")
            else:
                detail = _t("ExLlamaV3 n'est pas installé.")
            return {"installe": bool(e) or actif, "actif": actif, "version": self.version(), "detail": detail, "mode": "gere", "installe_par_lutin": bool(e)}
        if self.lmstudio_choisi():
            lms = self._lms()
            actif = OpenAIEngine.actif(self)
            if actif:
                detail = _t("LM Studio répond sur {}").format(self.adresse())
            elif lms:
                detail = _t("LM Studio est installé mais son serveur est arrêté : démarre-le.")
            else:
                detail = _t("LM Studio n'est pas installé.")
            return {"installe": bool(lms) or actif, "actif": actif, "version": "", "detail": detail, "mode": "gere", "installe_par_lutin": bool(lms)}
        if self.colibri_choisi():
            trouve = self._colibri()
            actif = OpenAIEngine.actif(self)
            if actif:
                detail = _t("Colibri répond sur {}").format(self.adresse())
            elif trouve:
                detail = _t("Colibri est installé mais arrêté : indique le dossier de son modèle puis démarre-le.")
            else:
                detail = _t("Colibri n'est pas installé.")
            return {"installe": bool(trouve) or actif, "actif": actif, "version": trouve[0] if trouve else "", "detail": detail, "mode": "gere", "installe_par_lutin": bool(trouve)}
        if not self.adresse():
            return {"installe": True, "actif": False, "version": "", "detail": _t("Aucune adresse : indique celle du serveur ci-dessous."), "mode": "externe"}
        actif = OpenAIEngine.actif(self)
        return {"installe": True, "actif": actif, "version": "", "detail": _t("Connecté à {}").format(self.adresse()) if actif else _t("Le serveur {} ne répond pas.").format(self.adresse()), "mode": "externe"}

    def _actions_exllamav3(self):
        from . import exllamav3
        e = self._exl() is not None
        hl = engines.CONTEXT["hors_ligne"]()
        actif = OpenAIEngine.actif(self)
        sans = _t("ExLlamaV3 n'est pas installé.")
        reseau = _t("Mode hors ligne : aucun téléchargement.") if hl else ""
        obstacle = ""
        if engines.CONTEXT["en_docker"]():
            obstacle = _t("Impossible dans Docker : pas de carte graphique ni d'environnement Python dédié dans le conteneur.")
        elif not exllamav3.python_compatible():
            obstacle = _t("Python {}.{} n'est pas pris en charge par TabbyAPI (3.10 à 3.14).").format(*sys.version_info[:2])
        else:
            try:
                fabricants = {g.fabricant for g in (getattr(engines.CONTEXT["profil"](), "gpus", None) or [])}
            except Exception:  # noqa: BLE001  (profil illisible : on laisse essayer)
                fabricants = {"nvidia"}
            if "nvidia" not in fabricants:
                obstacle = _t("Il faut une carte graphique NVIDIA : aucune n'a été détectée.")
        peut_installer = not e and not hl and not obstacle
        return {"installer": {"possible": peut_installer, "raison": obstacle or reseau or (_t("Déjà installé.") if e else _t("Télécharge TabbyAPI (GitHub) et installe ses dépendances dans un environnement Python dédié : plusieurs Go (torch), compte quelques minutes."))},
                "mettre_a_jour": {"possible": e and not hl, "raison": reseau or (_t("Récupère le dernier code de TabbyAPI et met à jour ExLlamaV3 ; tes modèles sont gardés.") if e else sans)},
                "desinstaller": {"possible": e, "raison": _t("Arrête TabbyAPI et supprime le programme et son environnement ; tes modèles téléchargés restent où ils sont.") if e else sans},
                "reinstaller": {"possible": e and not hl, "raison": reseau or (_t("Refait l'installation de TabbyAPI et de ses dépendances.") if e else sans)},
                "demarrer": {"possible": e and not actif, "raison": _t("Il tourne déjà.") if actif else (_t("Lance TabbyAPI sur cette machine seulement (127.0.0.1) ; le premier démarrage peut durer quelques minutes.") if e else sans)},
                "arreter": {"possible": actif, "raison": _t("Arrête TabbyAPI et libère la mémoire de la carte graphique.") if actif else _t("Il n'est pas démarré.")}}

    def _faire_exllamav3(self, action, progression):
        from . import exllamav3
        annule = lambda: bool(engines.TASKS.get(self.id, {}).get("annule"))  # noqa: E731
        dossiers = self._dossiers()
        try:
            if action in ("installer", "mettre_a_jour", "reinstaller"):
                if engines.CONTEXT["hors_ligne"]():
                    raise EngineError(_t("Mode hors ligne : aucun téléchargement."))
                if self.exllamav3_choisi() and OpenAIEngine.actif(self):
                    exllamav3.stop(dossiers)          # on ne remplace pas un programme qui tourne
                avancement = {"fait": 0, "total": exllamav3.INSTALL_STEPS + 1}          # les étapes de l'installation, puis le démarrage : une barre qui avance de vrai
                progression(_t("Installation d'ExLlamaV3 (TabbyAPI)…"), 0, avancement["total"])
                r = exllamav3.install(dossiers, self.port_exllamav3(), lambda texte: progression(texte, avancement["fait"], avancement["total"]), annule=annule,
                                        etape=lambda n, total: avancement.update(fait=n - 1), contexte=self._contexte())
                self._demarrer_apres_installation(progression, avancement["total"], "ExLlamaV3 " + (r["lib"] or r["tabby"][:7]),
                                                  lambda: exllamav3.start(self.port_exllamav3(), dossiers, contexte=self._contexte()), _t("le premier démarrage charge torch : une à deux minutes"))
            elif action == "desinstaller":
                exllamav3.uninstall(dossiers)
            elif action == "demarrer":
                progression(_t("Démarrage d'ExLlamaV3 (le premier démarrage peut être long)…"), 0, 0)
                exllamav3.start(self.port_exllamav3(), dossiers, contexte=self._contexte())
            elif action == "arreter":
                exllamav3.stop(dossiers)
            elif action.startswith("telecharger:"):
                if engines.CONTEXT["hors_ligne"]():
                    raise EngineError(_t("Mode hors ligne : aucun téléchargement."))
                depot, _, revision = action.split(":", 1)[1].partition("@")
                avance = {"fait": 0, "total": 0}
                progression(_t("Téléchargement de {}…").format(depot), 0, 0)
                exllamav3.download_model(depot, revision, dossiers, lambda texte: progression(texte, avance["fait"], avance["total"]), annule=annule, progres=lambda fait, total: avance.update(fait=fait, total=total),
                                         port=self.port_exllamav3(), contexte=self._contexte())
                progression(_t("Modèle téléchargé : {}.").format(depot), 1, 1)
            else:
                raise EngineError(_t("Action impossible avec ce serveur."))
        except EngineError:
            raise
        except (ValueError, OSError, subprocess.SubprocessError) as e:
            raise EngineError(str(e))

    def _actions_lmstudio(self):
        lms = self._lms() is not None
        hl = engines.CONTEXT["hors_ligne"]()
        actif = OpenAIEngine.actif(self)
        sans = _t("LM Studio n'est pas installé.")
        reseau = _t("Mode hors ligne : aucun téléchargement.") if hl else ""
        return {"installer": {"possible": not lms and not hl, "raison": reseau or (_t("Déjà installé.") if lms else _t("Télécharge l'installeur officiel de LM Studio (lmstudio.ai) et le lance ; il vérifie lui-même ce qu'il télécharge."))},
                "mettre_a_jour": {"possible": lms and not hl, "raison": reseau or (_t("Met à jour LM Studio (lms daemon update).") if lms else sans)},
                "desinstaller": {"possible": False, "raison": _t("Lutin ne désinstalle pas LM Studio : ses modèles sont dans son dossier (~/.lmstudio). Supprime-le toi-même si tu le veux vraiment.")},
                "reinstaller": {"possible": lms and not hl, "raison": reseau or (_t("Relance l'installeur officiel de LM Studio.") if lms else sans)},
                "demarrer": {"possible": lms and not actif, "raison": _t("Il tourne déjà.") if actif else (_t("Démarre le démon et le serveur de LM Studio sur cette machine seulement (127.0.0.1).") if lms else sans)},
                "arreter": {"possible": actif, "raison": _t("Arrête le serveur et le démon de LM Studio et libère la mémoire.") if actif else _t("Il n'est pas démarré.")}}

    def _faire_lmstudio(self, action, progression):
        from . import lmstudio
        annule = lambda: bool(engines.TASKS.get(self.id, {}).get("annule"))  # noqa: E731
        try:
            if action in ("installer", "mettre_a_jour", "reinstaller"):
                if engines.CONTEXT["hors_ligne"]():
                    raise EngineError(_t("Mode hors ligne : aucun téléchargement."))
                if action == "mettre_a_jour" and self._lms():
                    progression(_t("Mise à jour de LM Studio…"), 0, 0)
                    lmstudio.update()
                else:
                    lmstudio.install(lambda texte: progression(texte, 0, 0), annule=annule)
                self._demarrer_apres_installation(progression, 2, "LM Studio", lambda: lmstudio.start(self.port_lmstudio()), _t("quelques secondes"))
            elif action == "demarrer":
                progression(_t("Démarrage de LM Studio…"), 0, 0)
                lmstudio.start(self.port_lmstudio())
            elif action == "arreter":
                if not lmstudio.stop():
                    raise EngineError(_t("LM Studio n'a pas confirmé son arrêt."))
            elif action.startswith("telecharger:"):
                if engines.CONTEXT["hors_ligne"]():
                    raise EngineError(_t("Mode hors ligne : aucun téléchargement."))
                nom = action.split(":", 1)[1]
                progression(_t("Téléchargement de {}…").format(nom), 0, 0)
                lmstudio.download(nom, lambda texte: progression(texte, 0, 0), annule=annule)
                progression(_t("Modèle téléchargé : {}.").format(nom), 1, 1)
            else:
                raise EngineError(_t("Action impossible avec ce serveur."))
        except EngineError:
            raise
        except (ValueError, OSError, subprocess.SubprocessError) as e:
            raise EngineError(str(e))

    def actions(self):
        if self.exllamav3_choisi():
            return self._actions_exllamav3()
        if self.lmstudio_choisi():
            return self._actions_lmstudio()
        if not self.colibri_choisi():
            raison = _t("Sans objet : Lutin ne gère pas ce serveur. ExLlamaV3, LM Studio et Colibri, qu'il sait installer, ont chacun leur carte.")
            return {a: {"possible": False, "raison": raison} for a in engines.ACTIONS}
        trouve = self._colibri() is not None
        hl = engines.CONTEXT["hors_ligne"]()
        actif = OpenAIEngine.actif(self)
        modele = self.modele_colibri()
        modele_ok = bool(modele) and Path(modele).is_dir()
        sans = _t("Colibri n'est pas installé.")
        reseau = _t("Mode hors ligne : aucun téléchargement.") if hl else ""
        if not trouve:
            demarrer = sans
        elif actif:
            demarrer = _t("Il tourne déjà.")
        elif not modele:
            demarrer = _t("Prépare d'abord un modèle : onglet Modèles, carte Colibri.")
        elif not modele_ok:
            demarrer = _t("Le dossier du modèle n'existe pas : {}").format(modele)
        else:
            demarrer = _t("Lance Colibri sur cette machine seulement (127.0.0.1), avec le modèle réglé ci-dessous.")
        return {"installer": {"possible": not trouve and not hl, "raison": reseau or (_t("Déjà installé.") if trouve else _t("Télécharge l'archive officielle de Colibri et vérifie sa somme SHA-256."))},
                "mettre_a_jour": {"possible": trouve and not hl, "raison": reseau or (_t("Installe la dernière version de Colibri ; ton dossier de modèle est gardé.") if trouve else sans)},
                "desinstaller": {"possible": trouve, "raison": _t("Arrête et supprime le programme Colibri (ton modèle reste où il est).") if trouve else sans},
                "reinstaller": {"possible": trouve and not hl, "raison": reseau or (_t("Télécharge de nouveau la dernière version de Colibri.") if trouve else sans)},
                "demarrer": {"possible": trouve and not actif and modele_ok, "raison": demarrer},
                "arreter": {"possible": actif, "raison": _t("Arrête Colibri et libère la mémoire.") if actif else _t("Il n'est pas démarré.")}}

    def faire(self, action, progression):
        if self.exllamav3_choisi():
            return self._faire_exllamav3(action, progression)
        if self.lmstudio_choisi():
            return self._faire_lmstudio(action, progression)
        if not self.colibri_choisi():
            raise EngineError(_t("Action impossible : Lutin ne gère pas ce serveur."))
        from . import colibri
        dossiers = self._dossiers()
        try:
            if action in ("installer", "mettre_a_jour", "reinstaller"):
                if engines.CONTEXT["hors_ligne"]():
                    raise EngineError(_t("Mode hors ligne : aucun téléchargement."))
                progression(_t("Recherche de la dernière version de Colibri…"), 0, 0)
                actuelle = self._colibri()
                if action == "reinstaller" and actuelle:
                    shutil.rmtree(colibri.folder_colibri(dossiers) / ("v" + actuelle[0]), ignore_errors=True)
                version, _ = colibri.install(dossiers=dossiers, dire=lambda texte: progression(texte, 0, 0))
                progression(_t("Installé : Colibri {}.").format(version), 1, 1)
            elif action == "desinstaller":
                if OpenAIEngine.actif(self):
                    self._arreter_colibri()
                shutil.rmtree(colibri.folder_colibri(dossiers), ignore_errors=True)
            elif action.startswith("preparer:"):
                if engines.CONTEXT["hors_ligne"]():
                    raise EngineError(_t("Mode hors ligne : aucun téléchargement."))
                progression(_t("Colibri prépare le modèle…"), 0, 0)
                colibri.prepare(action.split(":", 1)[1], self.port_colibri(), dossiers, lambda texte: progression(texte, 0, 0), annule=lambda: bool(engines.TASKS.get(self.id, {}).get("annule")))
                progression(_t("Modèle prêt : Colibri répond sur le port {}.").format(self.port_colibri()), 1, 1)
            elif action == "demarrer":
                progression(_t("Démarrage de Colibri (le chargement du modèle peut être long)…"), 0, 0)
                colibri.start(self.modele_colibri(), self.port_colibri(), dossiers=dossiers)
            elif action == "arreter":
                self._arreter_colibri()
            else:
                raise EngineError(_t("Action impossible avec ce serveur."))
        except EngineError:
            raise
        except (ValueError, OSError, subprocess.SubprocessError, tarfile.TarError, zipfile.BadZipFile) as e:
            raise EngineError(str(e))

    def supprimer_modele(self, nom):
        """Supprime un modèle téléchargé par un serveur que Lutin gère (ExLlamaV3, LM Studio, Colibri). Un serveur qui tourne peut tenir le fichier : il est refusé avec la marche à suivre."""
        if not (self.exllamav3_choisi() or self.lmstudio_choisi() or self.colibri_choisi()):
            raise EngineError(_t("Ce serveur gère ses modèles lui-même."))
        nom_serveur = "ExLlamaV3" if self.exllamav3_choisi() else ("LM Studio" if self.lmstudio_choisi() else "Colibri")
        try:
            if self.exllamav3_choisi():
                from . import exllamav3
                for essai in range(6):
                    try:
                        exllamav3.remove_model(nom, self._dossiers())
                        break
                    except PermissionError:          # le serveur tient le modèle ouvert : on l'arrête (l'utilisateur a confirmé la suppression) et on réessaie quelques secondes ; rien n'est touché tant que ça échoue
                        if essai == 0 and OpenAIEngine.actif(self):
                            exllamav3.stop(self._dossiers())
                        if essai == 5:
                            raise
                        time.sleep(1)
            elif self.lmstudio_choisi():
                from . import lmstudio
                lmstudio.remove_model(nom)
            else:
                from . import colibri
                if OpenAIEngine.actif(self):
                    self._arreter_colibri()          # Colibri lit son modèle depuis le disque : arrêté avant d'être effacé
                colibri.remove_model(nom, self._dossiers())
        except PermissionError:
            raise EngineError(_t("Le modèle est utilisé : arrête {} (bouton « Arrêter »), puis supprime-le.").format(nom_serveur))
        except (ValueError, OSError) as e:
            raise EngineError(str(e))

    def _arreter_colibri(self):
        from . import colibri
        if not colibri.stop(self.port_colibri(), dossiers=self._dossiers()):
            raise EngineError(_t("Colibri n'a pas confirmé son arrêt : regarde son journal."))

    def telechargeable(self):
        return {"possible": False, "raison": _t("Un serveur externe gère ses modèles lui-même."), "genre": "aucun"}

    def grille(self):
        return {"discuter": ("natif", ""), "flux": ("natif", ""), "arret": ("natif", _t("La connexion est coupée : le serveur arrête de générer.")),
                "outils": ("non_teste", _t("Dépend du serveur.")), "reflexion": ("non_teste", _t("Dépend du serveur.")), "vision": ("non_teste", _t("Dépend du serveur et du modèle.")),
                "embeddings": ("non_teste", _t("Dépend du serveur.")), "plusieurs_modeles": ("non_teste", _t("Dépend du serveur.")),
                "telechargement": ("adapte", _t("Depuis Hugging Face (modèles EXL3), par Lutin.")) if self.exllamav3_choisi() else (("adapte", _t("Depuis Hugging Face (modèles GGUF), par Lutin.")) if self.lmstudio_choisi() else (("adapte", _t("Colibri prépare et télécharge ses modèles.")) if self.colibri_choisi() else ("non", _t("Le serveur gère ses modèles lui-même.")))),
                "installation": ("non_teste", _t("Lutin installe et lance Colibri ; le démarrage avec un vrai modèle n'est pas vérifié.")) if self.colibri_choisi() else (("non_teste", _t("Lutin installe et lance ExLlamaV3 (TabbyAPI) ; pas essayé sur une vraie carte NVIDIA.")) if self.exllamav3_choisi() else (("non_teste", _t("Lutin lance l'installeur officiel de LM Studio ; pas essayé sur une vraie installation.")) if self.lmstudio_choisi() else ("non", _t("Lutin n'installe pas ce serveur."))))}


class ManagedServerEngine(ExternalEngine):
    """Un serveur compatible OpenAI que Lutin installe, démarre et nourrit de modèles lui-même, sur cette machine seulement (127.0.0.1) : un moteur à part entière,
    avec sa carte (ADR 0020). Son adresse ne se règle pas : elle vient de son port."""
    adresse_modifiable = False


class ExLlamaV3Engine(ManagedServerEngine):
    id = serveur = engines.EXLLAMAV3
    nom = "ExLlamaV3"

    def compatibilite(self):
        possible, raison = super().compatibilite()
        from . import exllamav3
        if possible and not exllamav3.python_compatible():
            return False, _t("Python {}.{} n'est pas pris en charge par TabbyAPI (3.10 à 3.14).").format(*sys.version_info[:2])
        return possible, raison


class LMStudioEngine(ManagedServerEngine):
    id = serveur = engines.LMSTUDIO
    nom = "LM Studio"


class ColibriEngine(ManagedServerEngine):
    id = serveur = engines.COLIBRI
    nom = "Colibri"


def _system():
    import sys
    return "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux")


def _http_json(url, delai=20, pauses=(2, 5)):
    """Un JSON de GitHub / Hugging Face. Une panne passagère (502, 503, 504, 429, coupure) est patientée : trois essais avant de renoncer."""
    entetes = {"Accept": "application/json", "User-Agent": "Lutin"}
    from . import github as _github
    entetes.update(_github.headers_for(url))          # le compte GitHub (variable GITHUB_TOKEN ou réglages) : seulement pour l'API de GitHub, il relève la limite de requêtes
    _offline.guard(url)          # strict offline mode: Hugging Face and GitHub are refused here, before any connection (the old library route checked it, the new family did not)
    req = urllib.request.Request(url, headers=entetes)
    for pause in (*pauses, None):
        try:
            with urllib.request.urlopen(req, timeout=delai) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if pause is None or not (e.code >= 500 or e.code == 429):
                raise
        except urllib.error.URLError:
            if pause is None:
                raise
        time.sleep(pause)
