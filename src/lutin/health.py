"""Santé du PC : mémoire, carte graphique, disques ; garde-fous avant chaque demande ; autotest."""
from pathlib import Path
from . import offline as _hl
from . import i18n as _i18n
from .i18n import t as _t
from .i18n import traduire as _tr
import ctypes
import os
import secrets
import shutil
import subprocess
import threading
import time
import urllib.request
from . import core as _m


# --------------------------------------------------------------------------- santé du PC : mémoire, carte graphique, disques ; garde-fous ; autotest


VRAM_MARGIN = int(1.5 * 1024 ** 3)                                              # place à garder en plus du modèle (cache de contexte, affichage)


GB = 1024 ** 3


SIZE_CACHE = {}                                                             # dossier -> (date, octets) : mesurer un gros dossier coûte, on le fait au plus une fois par minute
MEMO = {}                                                                      # mesure -> (date, valeur, fonction) : voir memo()
REFRESHED = set()                                                             # dossiers en cours de remesure en arrière-plan
MEMO_TTL_S = {"vram": 4, "comfy": 4, "disques": 30, "jauge": 10}                            # secondes : assez court pour rester juste, assez long pour qu'une rafale de demandes ne remesure pas à chaque fois


def memo(cle, fonction):
    """Résultat de fonction() gardé quelques secondes (DUREE_MEMO). Une mesure coûte cher (nvidia-smi lance un programme, ComfyUI et les disques réseau peuvent mettre du temps à répondre) et le
    garde-fou en demande plusieurs avant CHAQUE message. Si la fonction a été remplacée (tests), la mesure gardée est ignorée."""
    maintenant = time.monotonic()
    gardee = MEMO.get(cle)
    if gardee and gardee[2] is fonction and maintenant - gardee[0] < MEMO_TTL_S[cle]:
        return gardee[1]
    valeur = fonction()
    MEMO[cle] = (maintenant, valeur, fonction)
    return valeur


def forget_measures(*cles):
    for c in cles or list(MEMO):
        MEMO.pop(c, None)


def system_memory():
    """Mémoire du PC : RAM totale et libre, et « engagement » libre (RAM + fichier d'échange : quand il est épuisé, Windows ferme des programmes). None si inconnu."""
    if os.environ.get("LUTIN_DEMO"):          # captures de la documentation : une machine fictive
        return {"total": 32 * 1024 ** 3, "libre": 17 * 1024 ** 3, "engagement_libre": 40 * 1024 ** 3}
    try:
        if os.name == "nt":
            class EtatMemoire(ctypes.Structure):
                _fields_ = [("longueur", ctypes.c_ulong), ("charge", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("libre", ctypes.c_ulonglong), ("echange_total", ctypes.c_ulonglong),
                            ("echange_libre", ctypes.c_ulonglong), ("virtuel_total", ctypes.c_ulonglong), ("virtuel_libre", ctypes.c_ulonglong), ("etendu_libre", ctypes.c_ulonglong)]
            e = EtatMemoire()
            e.longueur = ctypes.sizeof(e)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e)):
                return {"total": e.total, "libre": e.libre, "engagement_libre": e.echange_libre}
            return None
        valeurs = {}
        for ligne in Path("/proc/meminfo").read_text().splitlines():
            cle, _, reste = ligne.partition(":")
            valeurs[cle] = int(reste.split()[0]) * 1024
        return {"total": valeurs["MemTotal"], "libre": valeurs.get("MemAvailable", valeurs["MemFree"]), "engagement_libre": valeurs.get("MemAvailable", valeurs["MemFree"]) + valeurs.get("SwapFree", 0)}
    except (OSError, KeyError, ValueError, AttributeError):
        return None


def video_memory():
    """Mémoire de la carte graphique NVIDIA (via nvidia-smi). None si absente ou muette."""
    if os.environ.get("LUTIN_DEMO"):
        return {"nom": "NVIDIA GeForce RTX 4070", "total": 12 * 1024 ** 3, "utilise": 5600 * 1024 ** 2, "libre": 12 * 1024 ** 3 - 5600 * 1024 ** 2}
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--query-gpu=name,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"], capture_output=True, timeout=6)
        nom, total, utilise, libre = [p.strip() for p in r.stdout.decode("utf-8", "replace").strip().splitlines()[0].split(",")][:4]
        return {"nom": nom, "total": int(float(total)) * 1024 ** 2, "utilise": int(float(utilise)) * 1024 ** 2, "libre": int(float(libre)) * 1024 ** 2}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def disk_space(chemin):
    """Espace libre du disque qui contient ce chemin (ou du plus proche dossier existant). None si injoignable (NAS éteint...)."""
    p = Path(chemin)
    for _ in range(6):
        try:
            if p.exists():
                u = shutil.disk_usage(str(p))
                return {"total": u.total, "libre": u.free, "racine": str(p.anchor or p)}
        except OSError:
            return None
        p = p.parent
    return None


def measure_folder(cle, delai):
    total, limite = 0, time.time() + delai
    for racine, _, noms in os.walk(cle):
        for n in noms:
            try:
                total += os.path.getsize(os.path.join(racine, n))
            except OSError:
                pass
        if time.time() > limite:
            break
    SIZE_CACHE[cle] = (time.time(), total)
    return total


def folder_size(d, delai=4.0):
    """Taille d'un dossier en octets (au plus quelques secondes de parcours). Une mesure de plus d'une minute est renvoyée telle quelle et refaite en arrière-plan : parcourir un gros dossier de
    données (ou un partage réseau) ne retarde donc jamais une réponse. Seule la toute première mesure se fait sur place."""
    cle = str(d)
    en_cache = SIZE_CACHE.get(cle)
    if en_cache is None:
        return measure_folder(cle, delai)
    if time.time() - en_cache[0] >= 60 and cle not in REFRESHED:
        REFRESHED.add(cle)

        def refaire():
            try:
                measure_folder(cle, delai)
            finally:
                REFRESHED.discard(cle)
        threading.Thread(target=refaire, daemon=True).start()
    return en_cache[1]


def ollama_models_folder():
    from . import locations
    return locations.models_folder()


def model_size(nom, charge=None):
    """Octets de mémoire vidéo qu'il faut au modèle : sa taille d'après Ollama (celle du modèle déjà chargé si on l'a, sinon la liste des modèles installés), sinon celle annoncée dans le catalogue."""
    if charge and charge.get("taille"):
        return int(charge["taille"])
    if charge is not None:
        return 0          # déjà chargé par un moteur qui ne dit pas sa taille (llama.cpp) : il n'y a rien de plus à lui trouver — avant, la demande réclamait une 2e fois la place du modèle déjà là et attendait 15 minutes
    t = (_m.etat_moteur().get("tailles") or {}).get(nom)
    if t:
        return int(t)
    return int(next((m["go"] for m in _m.MODELES if m["id"] == nom), 0) * GB)


def gb(octets):
    return "{:.1f} {}".format(octets / GB, "GB" if _i18n.langue() == "en" else "Go")


def threshold_level(libre, seuil_attention, seuil_critique):
    return "critique" if libre < seuil_critique else "attention" if libre < seuil_attention else "ok"


def assess_health(m, r, besoin_modele=0, charge=None, partiel_possible=False):
    """Interprète les mesures. Chaque ligne : id, nom, niveau (ok / attention / critique), valeur, conseil. charge : l'état du modèle dans Ollama (ps_modele) ou None. partiel_possible : le moteur répartit tout seul les couches entre la carte et le processeur (llama.cpp), donc un modèle un peu trop gros n'est pas un blocage."""
    items = []

    def ajouter(id_, nom, niveau, valeur, conseil=""):
        items.append({"id": id_, "nom": nom, "niveau": niveau, "valeur": valeur, "conseil": conseil})
    seuil_ram, seuil_disque = r["seuil_ram_go"] * GB, r["seuil_disque_go"] * GB
    if m.get("ram"):
        libre = m["ram"]["libre"]
        n = threshold_level(libre, seuil_ram, seuil_ram / 2)
        ajouter("ram", "Mémoire vive (RAM)", n, "{} libres sur {}".format(gb(libre), gb(m["ram"]["total"])), "" if n == "ok" else "Ferme des programmes (navigateur, ComfyUI...) avant de continuer : Windows ferme des applications quand la mémoire est épuisée.")
        eng = m["ram"]["engagement_libre"]
        n = threshold_level(eng, seuil_ram * 2, seuil_ram)
        conseil = "" if n == "ok" else "Risque de plantage de Windows : libère de la mémoire, ou agrandis le fichier d'échange (Paramètres système avancés)."
        if charge is not None and n == "critique":
            # Windows counts the card's memory in the commit (llama-server: 20.8 GB on an RTX 4090, 21.9 GB of commit): the loaded model is most of it
            n, conseil = "attention", "Le modèle chargé en occupe la plus grande partie (sous Windows, sa place sur la carte graphique y est comptée) : une demande n'en prend pas plus. Pour charger un autre modèle, Lutin déchargera d'abord celui-ci ; agrandir le fichier d'échange laisse plus de marge."
        ajouter("engagement", "Mémoire + fichier d'échange", n, "{} disponibles".format(gb(eng)), conseil)
    else:
        ajouter("ram", "Mémoire vive (RAM)", "attention", "mesure impossible", "Je ne peux pas lire la mémoire de ce PC.")
    v = m.get("vram")
    if v:
        besoin = besoin_modele
        if charge and not charge.get("taille"):
            ajouter("vram", "Mémoire vidéo ({})".format(v["nom"]), "ok", "{} libres sur {} ({} déjà pris) ; modèle chargé (sa part sur la carte est dans la liste ci-dessous)".format(gb(v["libre"]), gb(v["total"]), gb(v["utilise"])))
        elif charge:
            partiel = charge["taille"] and charge["vram"] < 0.9 * charge["taille"]
            ajouter("vram", "Mémoire vidéo ({})".format(v["nom"]), "attention" if partiel else "ok", "{} libres sur {} ; modèle chargé à {} % sur la carte".format(gb(v["libre"]), gb(v["total"]), round(100 * charge["vram"] / charge["taille"]) if charge["taille"] else 0),
                    "Une partie du modèle tourne sur le processeur (lent) : ferme ComfyUI ou baisse la fenêtre de contexte." if partiel else "")
        else:
            n = "critique" if besoin and v["libre"] < 0.9 * besoin else "attention" if besoin and v["libre"] < besoin + VRAM_MARGIN else "ok"
            if n == "critique" and partiel_possible:
                n = "attention"          # llama.cpp met le reste sur le processeur : plus lent, pas bloqué
            # Le niveau ne vient PAS de l'occupation de la carte : il compare la place libre à ce que demande le modèle CHOISI (pas encore chargé).
            manque = max(0, besoin - v["libre"])
            texte = "{} libres sur {} ({} déjà pris) ; le modèle choisi demande environ {}".format(gb(v["libre"]), gb(v["total"]), gb(v["utilise"]), gb(besoin))
            if n == "ok":
                conseil = ""
            elif partiel_possible:
                conseil = "Il manque environ {} pour tout mettre sur la carte : llama.cpp en laissera une partie sur le processeur (plus lent). Libère de la place (liste ci-dessous : « Autres programmes ») ou choisis un modèle plus petit.".format(gb(manque))
            else:
                conseil = "Le modèle ne tiendra pas (ou juste) sur la carte, il manque environ {} : ferme les programmes qui l'utilisent (liste ci-dessous), ou clique sur « 🧹 VRAM ».".format(gb(manque))
            ajouter("vram", "Mémoire vidéo ({})".format(v["nom"]), n, texte, conseil)
    c = m.get("comfy") or {}
    if c.get("actif"):
        occupe = c.get("en_cours", 0) > 0
        ajouter("comfy", "ComfyUI", "attention" if occupe else "ok", "génère {} image(s), {} en attente".format(c["en_cours"], c["attente"]) if occupe else "ouvert, au repos",
                "Il occupe la carte graphique : attends la fin de la génération avant de poser une question lourde." if occupe else "Il garde des modèles en mémoire vidéo : ferme-le si le modèle de langage déborde.")
    for nom, d in (m.get("disques") or {}).items():
        id_ = {"Ollama (modèles)": "disque-ollama", "Projet": "disque-projet", "Données de l'assistant": "disque-donnees"}.get(nom, "disque")
        if d:
            n = threshold_level(d["libre"], seuil_disque, seuil_disque / 2)
            ajouter(id_, _t("Disque : {}").format(_t(nom)), n, "{} libres sur {} ({})".format(gb(d["libre"]), gb(d["total"]), d["racine"]), "" if n == "ok" else "Fais de la place sur ce disque.")
        else:
            ajouter(id_, _t("Disque : {}").format(_t(nom)), "attention", _t("injoignable"), "Le disque ou le partage réseau ne répond pas.")
    plafond = r["plafond_donnees_go"] * GB
    taille = m.get("donnees_octets", 0)
    n = "critique" if taille > plafond * 1.5 else "attention" if taille > plafond else "ok"
    ajouter("donnees", "Dossier de données de l'assistant", n, "{} (plafond {})".format(gb(taille), gb(plafond)), "" if n == "ok" else "Les plus anciennes sauvegardes de fichiers sont supprimées automatiquement ; vérifie aussi les conversations.")
    ordre = {"ok": 0, "attention": 1, "critique": 2}
    return {"niveau": max((i["niveau"] for i in items), key=lambda x: ordre[x], default="ok"), "items": items}


def _engine_splits_itself(r):
    """Le moteur choisi répartit-il tout seul le modèle entre la carte et le processeur ? Oui pour Ollama et llama.cpp (`--fit`) : un modèle un peu trop gros tourne alors plus lentement mais tourne.
    Un serveur « compatible OpenAI » est un inconnu : on ne promet rien."""
    return ((r or {}).get("moteur") or "ollama") in ("ollama", "llamacpp")


def _model_on_another_machine(r):
    """Le modèle choisi n'existe que sur une autre machine (liste de choix) : ni la carte ni la mémoire d'ici n'ont à le contenir."""
    try:
        from . import machines
        return machines.modele_distant(r, _m.etat_moteur().get("installes", [])) is not None
    except Exception:  # noqa: BLE001
        return False


def _unload_before_loading(r):
    """Le déchargement automatique des modèles restés en mémoire (et l'attente) se déclenche sur l'état « critique », donc seulement pour un moteur qui sait décharger : Ollama. Avec llama.cpp, le serveur gère lui-même la place."""
    return ((r or {}).get("moteur") or "ollama") == "ollama"


def _cache_reserve(r, charge):
    """What the chosen engine reserves for the conversation cache when it loads the model and cannot spill (ExLlamaV3); 0 once the model is loaded."""
    if charge is not None:
        return 0
    try:
        return int(_m.moteur_local(r).cache_reserve(r.get("modele"), int(r.get("num_ctx") or 0)) or 0)
    except Exception:  # noqa: BLE001  (an estimate: never an error more)
        return 0


def health_state(r=None):
    r = r or _m.reglages()
    charge = _m.ps_modele(r["modele"])
    besoin = 0 if _model_on_another_machine(r) else model_size(r["modele"], charge) + _cache_reserve(r, charge)
    etat = assess_health(_m.mesures_systeme(), r, besoin, charge, _engine_splits_itself(r))
    try:
        from . import store
        avis = store.notices()                                      # partage réseau, base illisible mise de côté (ADR 0017)
    except Exception as erreur:  # noqa: BLE001  (une ligne de santé de plus : jamais l'écran entier perdu)
        _m.journaliser("Santé : avis de la base impossibles ({!r}).".format(erreur))
        avis = []
    for niveau, texte in avis:
        etat["items"].append({"id": "base", "nom": _t("Base des conversations"), "niveau": "critique" if niveau == "erreur" else "attention", "valeur": texte, "conseil": ""})
    if avis:
        ordre = {"ok": 0, "attention": 1, "critique": 2}
        etat["niveau"] = max((i["niveau"] for i in etat["items"]), key=lambda x: ordre[x])
    return etat


ALERTS_SEEN = {}          # (conversation, ligne de santé) -> dernier niveau annoncé : un avertissement n'est répété que s'il change


RESOURCE_WAIT_S = 900          # une demande bloquée faute de mémoire est gardée et reprise toute seule quand la place revient, au plus pendant ce temps
WAIT_STEP_S = 5                   # secondes entre deux vérifications pendant l'attente


def _blockers(r, emit, conv_id=""):
    """Ce qui empêche de lancer le modèle en ce moment (liste d'éléments de santé « critiques »), après avoir tenté de décharger les modèles d'Ollama qui occupent la carte. Vide : on peut y aller."""
    if _model_on_another_machine(r):
        return []          # le modèle tourne sur une autre machine : rien ne manque ici
    moteur = (r or {}).get("moteur") or "ollama"
    charge = _m.ps_modele(r["modele"])
    besoin = model_size(r["modele"], charge) + _cache_reserve(r, charge)
    sante = assess_health(_m.mesures_systeme(), r, besoin, charge, _engine_splits_itself(r) and not _unload_before_loading(r))
    if charge is None and any(i["niveau"] == "critique" and i["id"] in ("ram", "engagement", "vram") for i in sante["items"]):
        # only Ollama's models were unloaded before: a llama.cpp model of 20 GB kept the card while ExLlamaV3 waited for room nothing would give back
        retenus = _m.modeles_retenus(sauf=moteur)
        if retenus:
            emit({"type": "info", "texte": _t("La mémoire est trop pleine pour charger ce modèle : je décharge ce que les moteurs gardent en mémoire ({}).").format(", ".join(retenus))})
            _m.liberer_vram(tout=True, sauf=moteur)
            time.sleep(1.5)
            forget_measures("vram")
            sante = assess_health(_m.mesures_systeme(), r, besoin, charge, _engine_splits_itself(r) and not _unload_before_loading(r))
    surveilles = ("ram", "vram", "comfy", "disque-donnees") if charge is not None else ("ram", "engagement", "vram", "comfy", "disque-donnees")
    for i in sante["items"]:
        if i["id"] in surveilles and ALERTS_SEEN.get((conv_id, i["id"]), "ok") != i["niveau"]:
            ALERTS_SEEN[(conv_id, i["id"])] = i["niveau"]
            if i["niveau"] == "attention":
                emit({"type": "info", "texte": "⚠ {} : {}. {}".format(i["nom"], i["valeur"], i["conseil"]).strip()})
    # a model already loaded by its engine asks for no more memory
    bloquants = ("ram", "engagement", "vram", "disque-donnees") if charge is None else ("disque-donnees",)
    return [i for i in sante["items"] if i["niveau"] == "critique" and i["id"] in bloquants]


def check_before_request(r, emit, conv_id="", stop=None):
    """Garde-fou : avant de lancer le modèle, vérifie qu'il y a assez de mémoire et de place. Si non : ta demande est GARDÉE et Lutin attend (au plus 15 minutes, `stop` l'interrompt) que la place
    revienne, puis répond tout seul. Renvoie False (et explique pourquoi) si la place n'est pas revenue : la demande risquerait de faire planter le PC."""
    if not _m.GARDE_RESSOURCES_ACTIF or not r.get("garde_ressources"):
        return True
    bloquants = _blockers(r, emit, conv_id)
    if bloquants and stop is not None and not r.get("_mission") and RESOURCE_WAIT_S > 0:
        emit({"type": "info", "texte": _t("⏳ Pas assez de mémoire pour l'instant ({}). Ta demande est gardée : je réponds dès que la place revient (jusqu'à {} minutes). Clique sur Arrêter pour annuler.").format(
            " ; ".join("{} : {}".format(_tr(i["nom"]), _tr(i["valeur"])) for i in bloquants), max(1, round(RESOURCE_WAIT_S / 60)))})
        fin = time.time() + RESOURCE_WAIT_S
        while bloquants and not stop.is_set() and time.time() < fin:
            stop.wait(WAIT_STEP_S)
            if stop.is_set():
                break
            bloquants = _blockers(r, lambda e: None, conv_id)
        if not bloquants:
            emit({"type": "info", "texte": _t("✔ La mémoire est revenue : je réponds.")})
            return True
        if stop.is_set():
            emit({"type": "info", "texte": _t("Attente annulée. Ta demande est gardée : écris « continue » quand il y aura de la place.")})
            return False
    if bloquants:
        emit({"type": "erreur", "texte": _t("Demande suspendue pour protéger le PC :\n{}\nRègle le problème puis écris « continue » (ou décoche « Garde-fous ressources » dans Réglages pour passer outre).").format(
            "\n".join("• {} : {}. {}".format(_tr(i["nom"]), _tr(i["valeur"]), _tr(i["conseil"])) for i in bloquants))})
        _m.journaliser("Demande suspendue (ressources) : " + "; ".join("{} {}".format(i["id"], i["valeur"]) for i in bloquants))
        return False
    return True


def watch_comfy_once():
    """ComfyUI génère (ou a des images en attente) alors qu'un modèle d'Ollama occupe la carte : on décharge le modèle pour lui laisser la place, sauf si l'assistant est
    en train de répondre. Renvoie True si un déchargement a eu lieu. (Le modèle se recharge tout seul à la question suivante.)"""
    if not _m.reglages().get("liberer_si_comfy", True) or _m.TOURS_ACTIFS:
        return False
    c = _m.etat_comfy()
    if not (c["actif"] and (c["en_cours"] or c["attente"])):
        return False
    try:
        if not _m.ollama_json("/api/ps", None, 3).get("models"):
            return False
    except (urllib.error.URLError, OSError, ValueError):
        return False
    _m.liberer_vram()
    _m.journaliser("ComfyUI travaille ({} en cours, {} en attente) : modèle(s) d'Ollama déchargé(s) pour lui laisser la carte graphique.".format(c["en_cours"], c["attente"]))
    return True


def watch_loop():
    try:
        folder_size(_m.DONNEES)                  # première mesure du dossier de données faite ici, pas pendant la première demande
    except Exception as erreur:  # noqa: BLE001
        _m.journaliser("Mesure du dossier de données : {!r}".format(erreur))
    while True:
        try:
            watch_comfy_once()
        except Exception as erreur:  # noqa: BLE001
            _m.journaliser("Surveillance de ComfyUI : {!r}".format(erreur))
        time.sleep(3)


def run_selftest(profond=False):
    """Une série de vérifications de bout en bout. profond=True fait aussi répondre le vrai modèle (le charge en mémoire, peut durer une minute)."""
    r = _m.reglages()
    resultats = []

    def essai(nom, fonction, important=True):
        debut = time.time()
        try:
            detail = fonction()
            ok = True
        except Exception as e:  # noqa: BLE001
            ok, detail = False, str(e)[:300] or type(e).__name__
        resultats.append({"nom": nom, "ok": ok, "important": important, "detail": detail if isinstance(detail, str) else "", "duree": round(time.time() - debut, 1)})
    o = _m.etat_moteur()

    def ollama_repond():
        if not o["actif"]:
            if _m.moteur_actuel(r).id != "ollama":
                raise RuntimeError(_t("Le moteur « {} » ne répond pas (Réglages > Moteur).").format(_m.moteur_actuel(r).nom))
            raise RuntimeError(_t("Ollama ne répond pas sur {} (bouton « Démarrer Ollama »).").format(_m.OLLAMA))
        return "{} modèle(s) installé(s)".format(len(o["installes"]))

    def modele_present():
        if r["modele"] not in o["installes"]:
            raise RuntimeError("Le modèle actif « {} » n'est pas installé (onglet Modèles).".format(r["modele"]))
        caps = _m.capacites(r["modele"])
        return "{} installé{}".format(r["modele"], "" if caps is None else " ; capacités : " + ", ".join(sorted(caps)))

    def ecriture_donnees():
        f = _m.DONNEES / ("autotest-" + secrets.token_hex(3) + ".tmp")
        try:
            _m.ecrire_atomique(f, "essai éàü ✓")
            if f.read_text(encoding="utf-8") != "essai éàü ✓":
                raise RuntimeError("Le fichier relu est différent de celui écrit.")
        finally:
            f.unlink(missing_ok=True)
        return "écriture, relecture et suppression dans donnees/"

    def conversations_ok():
        c = _m.conv_nouvelle()
        try:
            c["messages"].append({"role": "user", "content": "test"})
            _m.conv_ecrire(c)
            if _m.conv_lire(c["id"])["messages"][0]["content"] != "test":
                raise RuntimeError("La conversation relue est différente.")
        finally:
            _m.conv_supprimer(c["id"])
        return "création, enregistrement, lecture"

    def outils_fichiers():
        f = _m.RACINE / ".autotest-assistant.tmp"
        try:
            f.write_text("a\nb\n", encoding="utf-8")
            texte, eol = _m.lire_exact(f)
            nouveau, _ = _m.remplacer_une_fois(texte, "b", "c")
            if nouveau != "a\nc\n":
                raise RuntimeError("Le remplacement de texte ne fonctionne pas.")
        finally:
            f.unlink(missing_ok=True)
        return "lecture et remplacement de texte dans le projet"

    def plan_et_rappel():
        _m.PLAN["sections"] = _m.build_plan()
        _m.recall_tool("assistant", 1)
        return "plan du projet : {} dossier(s) ; recherche dans les documents prête".format(len(_m.PLAN["sections"]))

    def git_ok():
        g = _m.git_state()
        if not g["dispo"]:
            raise RuntimeError(g["raison"])
        return "branche {}, {} changement(s) en attente".format(g["branche"], g["total"])

    def web_ok():
        if _hl.is_active():
            return "désactivé (mode hors ligne strict)"
        if not r.get("web", True):
            return "désactivé dans les options"
        texte = _m.tool_web_search("assistant local test", 1, {"web": True})
        if "Aucun résultat" in texte:
            raise RuntimeError("DuckDuckGo n'a rien renvoyé (limitation temporaire, ou pas d'internet).")
        return "recherche web fonctionnelle"

    def autres_outils():
        t = []
        for nom, url in (("outil d'images", _m.OUTIL + "/api/sante"), ("ComfyUI", os.environ.get("COMFY_URL", "http://127.0.0.1:8188"))):
            try:
                urllib.request.urlopen(url, timeout=1.5).close()
                t.append(nom + " : répond")
            except (urllib.error.URLError, OSError, ValueError):
                t.append(nom + " : éteint (normal s'il n'est pas lancé)")
        return " ; ".join(t)

    def ressources():
        s = health_state(r)
        mauvais = [i for i in s["items"] if i["niveau"] != "ok"]
        if s["niveau"] == "critique":
            raise RuntimeError("; ".join("{} : {}".format(i["nom"], i["valeur"]) for i in mauvais if i["niveau"] == "critique"))
        return "tout est en ordre" if not mauvais else "à surveiller : " + "; ".join("{} ({})".format(i["nom"], i["valeur"]) for i in mauvais)

    def generation():
        corps = {"model": r["modele"], "messages": [{"role": "user", "content": "Réponds uniquement par le mot OK."}], "stream": False, "think": False, "options": _m.options_modele(r, 0, num_predict=12)}
        rep = _m.ollama_json("/api/chat", corps, 240)
        if not (rep.get("message", {}).get("content") or "").strip():
            raise RuntimeError("Le modèle n'a rien répondu.")
        v = _m.calculer_vitesse(dict(rep, eval_count=max(int(rep.get("eval_count") or 0), 5)))
        return "réponse reçue" + (" ({} jetons/s, chargement {} s)".format(v["ecriture"], v["chargement"]) if v else "")
    essai("Ollama répond", ollama_repond)
    essai("Modèle actif installé", modele_present)
    essai("Écriture dans les données", ecriture_donnees)
    essai("Conversations", conversations_ok)
    essai("Lecture et modification de fichiers", outils_fichiers)
    essai("Plan du projet et recherche", plan_et_rappel)
    essai("Mémoire, carte graphique, disques", ressources)
    essai("Git", git_ok, important=False)
    essai("Recherche web", web_ok, important=False)
    essai("Outil d'images et ComfyUI", autres_outils, important=False)
    if profond:
        essai("Le modèle répond vraiment", generation)
    return {"ok": all(x["ok"] for x in resultats if x["important"]), "resultats": resultats, "profond": bool(profond)}
