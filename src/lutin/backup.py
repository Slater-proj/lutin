"""Sauvegarde et restauration de tes données Lutin dans un seul fichier .zip.

Contenu : configuration, réglages, liste de modèles, conversations, journal des actions, mémoire (CONTEXTE.md, MEMOIRE.md, notes).
Jamais inclus : appareils connectés et jeton de la console (ce sont des accès : ils ne se déplacent pas), cache, journal technique, sauvegardes de fichiers du dossier de travail.
La restauration refuse tout ce qui sortirait des dossiers de Lutin, garde l'état précédent dans un zip « avant-restauration » et ne remplace rien tant que l'archive n'est pas entièrement vérifiée.
"""
import json
import os
import time
import zipfile
from pathlib import Path

from . import __version__
from .i18n import t as _t

MAX_SIZE = 2 * 1024 ** 3
MAX_MEMBERS = 100_000
ROOTS = {"config": ("config.json",), "donnees": ("reglages.json", "modeles.json", "journal-actions.jsonl"), "memoire": None}   # None = tout le dossier
SUBFOLDERS = {"donnees": ("conversations",)}
MANIFEST = "manifeste.json"


class BackupError(ValueError):
    pass


def _to_save(dossiers):
    """[(nom dans le zip, chemin sur le disque)]"""
    sortie = []
    for cle, fichiers in ROOTS.items():
        base = Path(dossiers[cle]) if dossiers.get(cle) else None
        if not base or not base.is_dir():
            continue
        if fichiers is None:
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    sortie.append(("{}/{}".format(cle, p.relative_to(base).as_posix()), p))
            continue
        for nom in fichiers:
            if (base / nom).is_file():
                sortie.append(("{}/{}".format(cle, nom), base / nom))
        for sous in SUBFOLDERS.get(cle, ()):
            if (base / sous).is_dir():
                for p in sorted((base / sous).glob("*.json")):
                    sortie.append(("{}/{}/{}".format(cle, sous, p.name), p))
    return sortie


def export(dossiers, destination):
    """Écrit l'archive (fichier ou objet binaire). Renvoie un résumé {fichiers, octets}."""
    fichiers = _to_save(dossiers)
    total = 0
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as z:
        for nom, chemin in fichiers:
            total += chemin.stat().st_size
            if total > MAX_SIZE:
                raise BackupError(_t("Trop de données pour une sauvegarde ({} Go au plus).").format(MAX_SIZE // 1024 ** 3))
            z.write(chemin, nom)
        z.writestr(MANIFEST, json.dumps({"lutin": __version__, "date": time.strftime("%Y-%m-%dT%H:%M:%S"), "fichiers": [n for n, _ in fichiers]}, ensure_ascii=False, indent=1))
    return {"fichiers": len(fichiers), "octets": total}


def _valid_name(nom):
    """Un nom de membre est accepté s'il désigne un fichier prévu, sans chemin absolu, sans « .. », sans lecteur."""
    if nom == MANIFEST:
        return True
    if not nom or nom.startswith(("/", "\\")) or "\\" in nom or ":" in nom or any(p in ("", ".", "..") for p in nom.split("/")):
        return False
    parties = nom.split("/")
    cle = parties[0]
    if cle not in ROOTS or len(parties) < 2:
        return False
    if ROOTS[cle] is None:
        return True
    reste = "/".join(parties[1:])
    return reste in ROOTS[cle] or any(reste.startswith(s + "/") and reste.endswith(".json") and reste.count("/") == 1 for s in SUBFOLDERS.get(cle, ()))


def verify(archive):
    """Ouvre l'archive et renvoie son manifeste, ou lève ErreurSauvegarde. Rien n'est écrit."""
    try:
        z = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as e:
        raise BackupError(_t("Ce n'est pas une sauvegarde Lutin lisible : {}").format(e))
    with z:
        infos = z.infolist()
        if len(infos) > MAX_MEMBERS:
            raise BackupError(_t("Archive suspecte : trop de fichiers."))
        total = 0
        for i in infos:
            if i.is_dir():
                continue
            if not _valid_name(i.filename):
                raise BackupError(_t("Archive refusée : « {} » n'est pas un fichier de sauvegarde Lutin.").format(i.filename))
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise BackupError(_t("Archive refusée : lien symbolique « {} ».").format(i.filename))
            total += i.file_size
            if total > MAX_SIZE:
                raise BackupError(_t("Archive suspecte : trop volumineuse une fois décompressée."))
        if MANIFEST not in z.namelist():
            raise BackupError(_t("Ce n'est pas une sauvegarde Lutin (manifeste absent)."))
        try:
            m = json.loads(z.read(MANIFEST).decode("utf-8"))
        except (ValueError, KeyError):
            raise BackupError("Manifeste illisible.")
        if z.testzip():
            raise BackupError(_t("Archive abîmée : {}").format(z.testzip()))
        m["octets"] = total
        return m


def restore(dossiers, archive, dossier_secours=None):
    """Remplace les fichiers de l'archive par leur contenu. L'état actuel est d'abord gardé dans `dossier_secours` (zip « avant-restauration »). Renvoie un résumé."""
    manifeste = verify(archive)
    secours = None
    if dossier_secours:
        Path(dossier_secours).mkdir(parents=True, exist_ok=True)
        secours = Path(dossier_secours) / "avant-restauration-{}.zip".format(time.strftime("%Y%m%d-%H%M%S"))
        export(dossiers, secours)
    ecrits = 0
    with zipfile.ZipFile(archive) as z:
        for i in z.infolist():
            if i.is_dir() or i.filename == MANIFEST:
                continue
            cle, _, reste = i.filename.partition("/")
            if not dossiers.get(cle):
                raise BackupError(_t("Dossier « {} » inconnu pour cette installation.").format(cle))
            cible = Path(dossiers[cle]) / reste
            cible.parent.mkdir(parents=True, exist_ok=True)
            tmp = cible.with_name(cible.name + ".restauration")
            tmp.write_bytes(z.read(i))
            os.replace(tmp, cible)
            ecrits += 1
    return {"fichiers": ecrits, "secours": str(secours) if secours else "", "version": manifeste.get("lutin", ""), "date": manifeste.get("date", "")}
