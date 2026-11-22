"""Langue de Lutin : français ou anglais, pour l'interface, la ligne de commande et les messages du serveur.

La langue se choisit (par ordre de priorité) : variable LUTIN_LANGUE, réglage `langue` de config.json (« lutin language en »), puis la langue du système (français si elle commence par « fr »,
anglais sinon). Le **français est la langue d'écriture du code** : `t("texte français")` renvoie le texte tel quel en français, sa traduction en anglais sinon (dictionnaire
`langues/messages.en.json`). Un texte sans traduction reste en français : jamais d'erreur, mais un test (`tests/test_langue.py`) garantit que chaque `t("…")` du code est traduit.
"""
import json
import os
import re
import threading
from pathlib import Path

LANGUAGES = ("fr", "en")
FOLDER = Path(__file__).resolve().parent / "langues"
_lock = threading.RLock()                    # réentrant : gabarits() appelle dico()
_dictionaries = {}
_config = {"chemin": "", "mtime": None, "valeur": None}
_forced = {"valeur": None}                   # choix fait pendant l'installation guidée, avant que config.json soit écrit


def system_language():
    """« fr » si le système est réglé en français, « en » sinon."""
    for variable in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        v = os.environ.get(variable, "").strip().lower()
        if v and v not in ("c", "posix"):
            return "fr" if v.startswith("fr") else "en"
    if os.name == "nt":
        try:
            import ctypes
            tampon = ctypes.create_unicode_buffer(85)
            ctypes.windll.kernel32.GetUserDefaultLocaleName(tampon, 85)
            return "fr" if tampon.value.lower().startswith("fr") else "en"
        except (OSError, AttributeError):
            pass
    try:
        import locale
        return "fr" if (locale.getlocale()[0] or "").lower().startswith("fr") else "en"
    except ValueError:
        return "en"


def _config_path():
    chemin = os.environ.get("LUTIN_CONFIG")
    if chemin:
        return Path(chemin)
    from . import config
    return Path(config.folders()["config"]) / "config.json"


def configured_language(chemin_config=None):
    """Le réglage de config.json (« fr » ou « en »), ou None s'il n'y en a pas (langue automatique). Relit le fichier seulement quand il a changé."""
    chemin = Path(chemin_config) if chemin_config else _config_path()
    try:
        mtime = chemin.stat().st_mtime_ns
    except OSError:
        return None
    with _lock:
        if _config["chemin"] == str(chemin) and _config["mtime"] == mtime:
            return _config["valeur"]
        try:
            v = json.loads(chemin.read_text(encoding="utf-8")).get("langue")
        except (OSError, ValueError, AttributeError):
            v = None
        v = v if v in LANGUAGES else None
        _config.update(chemin=str(chemin), mtime=mtime, valeur=v)
        return v


def language():
    """La langue courante : « fr » ou « en »."""
    v = os.environ.get("LUTIN_LANGUE", "").strip().lower()
    if v in LANGUAGES:
        return v
    return _forced["valeur"] or configured_language() or system_language()


def force(valeur):
    """Fixe la langue du processus en cours (None pour revenir au réglage) : sert à l'installation guidée, qui enregistre la configuration seulement à la fin."""
    _forced["valeur"] = valeur if valeur in LANGUAGES else None


def save_language(valeur, chemin_config=None):
    """Enregistre la langue dans config.json (« fr », « en », ou « auto » pour suivre le système). Renvoie la langue effective."""
    if valeur not in LANGUAGES + ("auto",):
        raise ValueError("Langue inconnue : {} (fr, en ou auto).".format(valeur))
    chemin = Path(chemin_config) if chemin_config else _config_path()
    from . import config
    config.update_file(chemin, {"langue": None if valeur == "auto" else valeur})          # sous le verrou de config.save ; jamais la seule langue à la place du fichier
    with _lock:
        _config["mtime"] = None
    return language()


def dictionary(nom, code="en"):
    """Un dictionnaire de traduction {texte français: texte traduit} (`messages` pour Python, `interface` pour la page web). Vide s'il n'existe pas."""
    cle = (nom, code)
    with _lock:
        if cle not in _dictionaries:
            try:
                d = json.loads((FOLDER / "{}.{}.json".format(nom, code)).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                d = {}
            _dictionaries[cle] = d if isinstance(d, dict) else {}
        return _dictionaries[cle]


def t(texte):
    """Le texte dans la langue courante. Le français est la langue source : il passe tel quel ; sinon la traduction, ou le français si elle manque."""
    if language() == "fr":
        return texte
    return dictionary("messages").get(texte, texte)


_templates = {"liste": None}


def templates():
    """[(longueur du texte fixe, expression régulière, traduction, morceaux fixes)] pour reconnaître un message déjà formaté d'après son gabarit (« Lutin est déjà à jour ({}). »). Les plus précis d'abord."""
    with _lock:
        if _templates["liste"] is None:
            liste = []
            for fr, en in dictionary("messages").items():
                morceaux = re.split(r"\{[^{}]*\}", fr)
                if len(morceaux) < 2 or len("".join(morceaux).strip()) < 6:
                    continue                                             # pas de variable, ou trop peu de texte fixe : il reconnaîtrait n'importe quoi
                liste.append((len("".join(morceaux)), re.compile("(.*?)".join(re.escape(m) for m in morceaux), re.S), en, tuple(morceaux)))
            liste.sort(key=lambda x: -x[0])
            _templates["liste"] = liste
        return _templates["liste"]


TEMPLATE_MAX_LENGTH = 2000                  # au-delà, ce n'est plus un message de l'application (et les expressions à trous deviendraient lentes)


def _possible(texte, morceaux):
    """Contrôle bon marché avant l'expression régulière : début et fin identiques, et les morceaux fixes dans l'ordre."""
    if not texte.startswith(morceaux[0]) or not texte.endswith(morceaux[-1]):
        return False
    position = len(morceaux[0])
    fin = len(texte) - len(morceaux[-1])
    for m in morceaux[1:-1]:
        position = texte.find(m, position, fin)
        if position < 0:
            return False
        position += len(m)
    return position <= fin


def translate(texte):
    """Comme `t()`, mais accepte aussi un message DÉJÀ construit avec `.format()` (erreurs du serveur, évènements, mesures de santé) : texte exact d'abord, puis le gabarit qui le reconnaît.
    Sans traduction, le texte reste tel quel."""
    if not isinstance(texte, str) or language() == "fr":
        return texte
    d = dictionary("messages")
    if texte in d:
        return d[texte]
    if len(texte) > TEMPLATE_MAX_LENGTH:
        return texte
    for _, regex, en, morceaux in templates():
        if not _possible(texte, morceaux):
            continue
        m = regex.fullmatch(texte)
        if m:
            try:
                return re.sub(r"\{[^{}]*\}", "{}", en).format(*(translate(g) for g in m.groups()))          # les groupes sont déjà du texte : les formats numériques (:g, :.1f) ne s'appliquent plus
            except (IndexError, ValueError, KeyError):
                return texte
    return texte
