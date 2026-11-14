"""Ce qu'Ollama sait d'un modèle (/api/show), pour mieux juger les modèles que le catalogue ne connaît pas (découverts dans la bibliothèque, ajoutés à la main, installés ailleurs).

Sans cela, un modèle hors catalogue n'avait que sa taille de fichier : Lutin le jugeait « 1 milliard de paramètres, 32 000 jetons de contexte, mémoire de contexte moyenne » quoi qu'il soit.
Ici on lit les vrais chiffres : nombre de paramètres, experts (donc la part qui travaille à chaque mot), longueur de contexte, mémoire que prend le contexte, et les capacités annoncées (outils, vision…).
Le résultat est gardé sur le disque : une seule question à Ollama par modèle. Jamais bloquant : la lecture se fait en arrière-plan et la liste s'améliore au rafraîchissement suivant."""
import json
import threading
import urllib.error

from .i18n import t as _t

FIXED_EXPERT_SHARE = 0.04          # un modèle à experts garde l'attention et les couches communes : ~4 % du total travaille toujours, en plus des experts choisis
LUTIN_CAPABILITIES = {"tools": "outils", "vision": "vision", "thinking": "reflexion"}
VERSION = 2                       # numéro du format gardé sur le disque
_lock = threading.Lock()
_in_progress = set()
_memory = {}                      # modèle -> infos (ou {} si Ollama ne sait rien dire), pour cette session


def _number(valeur):
    if isinstance(valeur, bool):
        return 0
    if isinstance(valeur, (int, float)):
        return valeur
    return 0


def extract(show):
    """Les chiffres utiles d'une réponse /api/show : {params_b, actifs_b, ctx_max, kv_mo_1k, capacites}. Les champs inconnus sont absents (jamais inventés). {} si la réponse est inutilisable."""
    if not isinstance(show, dict):
        return {}
    info = show.get("model_info")
    info = info if isinstance(info, dict) else {}
    arch = str(info.get("general.architecture") or "")

    def cle(nom):
        return info.get("{}.{}".format(arch, nom)) if arch else None
    sortie = {}
    total = _number(info.get("general.parameter_count"))
    if total > 0:
        sortie["params_b"] = round(total / 1e9, 2)
        experts, utilises = _number(cle("expert_count")), _number(cle("expert_used_count"))
        if experts > 1 and 0 < utilises <= experts:
            sortie["actifs_b"] = round(sortie["params_b"] * (FIXED_EXPERT_SHARE + (1 - FIXED_EXPERT_SHARE) * utilises / experts), 2)
        else:
            sortie["actifs_b"] = sortie["params_b"]
    contexte = _number(cle("context_length"))
    if contexte >= 512:
        sortie["ctx_max"] = int(contexte)
    couches, tete_kv, tete_q, taille = _number(cle("block_count")), cle("attention.head_count_kv"), _number(cle("attention.head_count")), _number(cle("embedding_length"))
    if isinstance(tete_kv, list):                                  # modèles hybrides : seules certaines couches ont de l'attention (donc un cache)
        couches_attention = sum(1 for x in tete_kv if _number(x) > 0)
        tete_kv = max((_number(x) for x in tete_kv), default=0)
        couches = couches_attention or couches
    tete_kv = _number(tete_kv) or tete_q
    dim = _number(cle("attention.key_length")) or (taille / tete_q if tete_q else 0)
    if couches > 0 and tete_kv > 0 and dim > 0:
        sortie["kv_mo_1k"] = max(1, round(2 * couches * tete_kv * dim * 2 * 1000 / 1e6))          # clés + valeurs, en 16 bits
    details = show.get("details") if isinstance(show.get("details"), dict) else {}
    if isinstance(details.get("quantization_level"), str) and details["quantization_level"].strip():
        sortie["quantification"] = details["quantization_level"].strip()          # « Q4_K_M », « Q8_0 », « F16 » : la précision réellement installée
    caps = show.get("capabilities")
    if isinstance(caps, list):
        sortie["capacites"] = [LUTIN_CAPABILITIES[c] for c in caps if c in LUTIN_CAPABILITIES]
        if "embedding" in caps:
            sortie["embedding"] = True                       # sert à la recherche par le sens, pas à discuter
    return sortie


def sentence(infos):
    """Une phrase honnête sur un modèle découvert, tirée de ce qu'Ollama en dit (rien d'inventé : seulement ce qui est connu)."""
    if not infos:
        return ""
    if infos.get("embedding"):
        return _t("Modèle de recherche par le sens (Réglages > Conversation) : il retrouve des passages, il ne discute pas.")
    morceaux = []
    if infos.get("params_b"):
        morceaux.append(_t("{} milliards de paramètres").format(infos["params_b"]) + ((_t(" dont ~{} qui travaillent à chaque mot").format(infos["actifs_b"])) if infos.get("actifs_b") and infos["actifs_b"] < 0.7 * infos["params_b"] else ""))
    if infos.get("ctx_max"):
        morceaux.append(_t("contexte jusqu'à {} jetons").format(infos["ctx_max"]))
    if "capacites" in infos:
        morceaux.append(_t("sait appeler les outils de Lutin") if "outils" in infos["capacites"] else _t("n'appelle pas les outils (il répondra sans lire ni modifier tes fichiers)"))
    return _t("Modèle hors catalogue : ") + ", ".join(morceaux) + "." if morceaux else ""


def path_of(donnees):
    return donnees / "infos-modeles.json"


def read_disk(donnees):
    try:
        d = json.loads(path_of(donnees).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def already_known(modele, donnees):
    """Les infos gardées pour ce modèle, ou None si on ne les a pas encore (la lecture se lance alors en arrière-plan avec `demander`)."""
    with _lock:
        if modele in _memory:
            return _memory[modele]
    d = read_disk(donnees)
    if isinstance(d.get(modele), dict) and d[modele].get("v") == VERSION:          # une lecture faite par une version plus ancienne (sans la précision installée) est refaite
        with _lock:
            _memory[modele] = d[modele]
        return d[modele]
    return None


def ask(modeles, donnees, show):
    """Lance, en arrière-plan, la lecture des modèles pas encore connus. `show(modele)` renvoie la réponse de /api/show (ou lève OSError). Ne bloque jamais l'appelant."""
    a_lire = [m for m in modeles if already_known(m, donnees) is None]
    with _lock:
        a_lire = [m for m in a_lire if m not in _in_progress]
        _in_progress.update(a_lire)
    if not a_lire:
        return

    def travail():
        for m in a_lire:
            try:
                infos = dict(extract(show(m)), v=VERSION)
            except (OSError, ValueError, urllib.error.URLError):
                infos = None                                    # Ollama ne répond pas : on réessaiera au prochain rafraîchissement
            if infos is not None:                               # le disque d'abord : dès que la mémoire le sait, le disque le sait aussi
                d = read_disk(donnees)
                d[m] = infos
                try:
                    donnees.mkdir(parents=True, exist_ok=True)
                    path_of(donnees).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                except OSError:
                    pass
            with _lock:
                _in_progress.discard(m)
                if infos is not None:
                    _memory[m] = infos
    threading.Thread(target=travail, daemon=True, name="infos-modeles").start()


def forget(modele, donnees):
    """Un modèle supprimé ou remplacé : ses infos ne valent plus."""
    with _lock:
        _memory.pop(modele, None)
    d = read_disk(donnees)
    if d.pop(modele, None) is not None:
        try:
            path_of(donnees).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
