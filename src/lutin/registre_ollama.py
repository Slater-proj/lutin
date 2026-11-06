"""Télécharger un modèle de la bibliothèque d'Ollama SANS Ollama : pour qu'un autre moteur (llama.cpp) propose les mêmes modèles, sous les mêmes noms, y compris ceux de la communauté (« sans filtre »).

Le registre d'Ollama parle le protocole des registres de conteneurs : un petit « manifeste » liste les morceaux d'un modèle, et chaque morceau se télécharge par son empreinte (adresse publique, sans compte).
Le morceau « modèle » est un fichier GGUF. On range tout dans la même disposition qu'Ollama (`manifests/registry.ollama.ai/…` et `blobs/sha256-…`), ce qui permet de relire le résultat avec ollama_partage.py
(et, le cas échéant, de le donner à Ollama lui-même). Chaque morceau est vérifié par son empreinte SHA-256 ; un téléchargement interrompu reprend où il s'est arrêté. Rien n'est installé sans clic."""
import hashlib
import json
import re
from pathlib import Path

from . import miseajour, ollama_client
from . import ollama_partage as _partage
from .i18n import t as _t

HOTE = "registry.ollama.ai"
URL = "https://" + HOTE + "/v2/{espace}/{nom}/{genre}/{reference}"
ACCEPT = "application/vnd.docker.distribution.manifest.v2+json"
RE_NOM = re.compile(r"^(?:([A-Za-z0-9][\w.-]*)/)?([A-Za-z0-9][\w.-]*)(?::([A-Za-z0-9][\w.-]*))?$")
RE_EMPREINTE = re.compile(r"^sha256:([0-9a-f]{64})$")


class ErreurRegistre(Exception):
    pass


def decomposer(modele):
    """« qwen3:8b » -> (« library », « qwen3 », « 8b ») ; « huihui_ai/x:4b » -> (« huihui_ai », « x », « 4b »). ErreurRegistre si le nom est invalide."""
    m = RE_NOM.match(str(modele or "").strip())
    if not m:
        raise ErreurRegistre(_t("Nom de modèle invalide."))
    return m.group(1) or "library", m.group(2), m.group(3) or "latest"


def lire_manifeste(modele, http=miseajour.http_get):
    espace, nom, tag = decomposer(modele)
    try:
        statut, _, corps = http(URL.format(espace=espace, nom=nom, genre="manifests", reference=tag), {"Accept": ACCEPT}, 20)
    except OSError as e:
        raise ErreurRegistre(_t("Le registre d'Ollama ne répond pas : {}").format(e))
    if statut == 404:
        raise ErreurRegistre("model does not exist: " + str(modele))
    if statut != 200:
        raise ErreurRegistre(_t("Le registre d'Ollama a répondu {}.").format(statut))
    try:
        manifeste = json.loads(corps.decode("utf-8"))
    except ValueError:
        raise ErreurRegistre(_t("Réponse illisible du registre d'Ollama."))
    if not isinstance(manifeste, dict) or not isinstance(manifeste.get("layers"), list):
        raise ErreurRegistre(_t("Réponse inattendue du registre d'Ollama."))
    return manifeste, corps


def _empreinte_fichier(f):
    h = hashlib.sha256()
    with open(f, "rb") as flux:
        for bloc in iter(lambda: flux.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _morceaux(manifeste):
    """[(empreinte hexadécimale, taille, type)] de tous les morceaux, dans l'ordre : configuration, puis couches."""
    sortie = []
    for c in ([manifeste.get("config")] if isinstance(manifeste.get("config"), dict) else []) + [c for c in manifeste["layers"] if isinstance(c, dict)]:
        m = RE_EMPREINTE.match(str(c.get("digest") or ""))
        if m:
            sortie.append((m.group(1), int(c.get("size") or 0), str(c.get("mediaType") or "")))
    return sortie


def telecharger(modele, dossier, progression=None, http=miseajour.http_get, recuperer=ollama_client.telecharger_fichier):
    """Télécharge `modele` dans `dossier` (disposition d'Ollama). progression(texte, fait, total). Renvoie le dossier. ErreurRegistre si le modèle n'existe pas, si un morceau est corrompu ou si le réseau lâche."""
    manifeste, brut = lire_manifeste(modele, http)
    if not any(c.get("mediaType") == _partage.TYPE_MODELE for c in manifeste["layers"] if isinstance(c, dict)):
        raise ErreurRegistre(_t("Ce modèle n'a pas de fichier de modèle utilisable par un autre moteur."))
    espace, nom, tag = decomposer(modele)
    dossier = Path(dossier)
    morceaux = _morceaux(manifeste)
    total = sum(t for _, t, _ in morceaux)
    deja = 0
    for hexa, taille, _type in morceaux:
        destination = dossier / "blobs" / ("sha256-" + hexa)
        if destination.is_file() and destination.stat().st_size == taille:
            deja += taille
            if progression:
                progression(modele, deja, total)
            continue
        base = deja
        try:
            recuperer(URL.format(espace=espace, nom=nom, genre="blobs", reference="sha256:" + hexa), destination,
                      (lambda texte, fait, tot, b=base: progression(modele, b + fait, total)) if progression else None, taille_min=1)
        except ollama_client.ErreurOllama as e:
            raise ErreurRegistre(str(e))
        if _empreinte_fichier(destination) != hexa:
            destination.unlink(missing_ok=True)
            raise ErreurRegistre(_t("Un morceau du modèle est corrompu (empreinte différente) : il a été supprimé, relance le téléchargement."))
        deja += taille
    manif = dossier / "manifests" / HOTE / espace / nom / tag
    manif.parent.mkdir(parents=True, exist_ok=True)
    tmp = manif.with_name(manif.name + ".tmp")
    tmp.write_bytes(brut)
    tmp.replace(manif)          # le manifeste en dernier : un modèle n'existe pour les autres qu'une fois entier
    return dossier


def supprimer(modele, dossier):
    """Supprime le manifeste de `modele` et les morceaux que plus aucun autre modèle de `dossier` n'utilise. Renvoie les octets libérés (0 si le modèle n'y était pas)."""
    espace, nom, tag = decomposer(modele)
    dossier = Path(dossier)
    manif = dossier / "manifests" / HOTE / espace / nom / tag
    if not manif.is_file():
        return 0
    try:
        a_retirer = {h for h, _, _ in _morceaux(json.loads(manif.read_text(encoding="utf-8")))}
    except (OSError, ValueError):
        a_retirer = set()
    manif.unlink()
    for autre in (dossier / "manifests" / HOTE).rglob("*"):
        if autre.is_file():
            try:
                a_retirer -= {h for h, _, _ in _morceaux(json.loads(autre.read_text(encoding="utf-8")))}
            except (OSError, ValueError):
                continue
    libere = 0
    for h in a_retirer:
        f = dossier / "blobs" / ("sha256-" + h)
        try:
            libere += f.stat().st_size
            f.unlink()
        except OSError:
            pass
    for d in (manif.parent, manif.parent.parent):          # les dossiers devenus vides
        try:
            d.rmdir()
        except OSError:
            break
    return libere
