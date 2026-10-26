"""Démarrer le serveur de Lutin : dossiers, niveau de sécurité, Ollama, vérification des modèles en arrière-plan."""
import os
import threading
import time
from pathlib import Path

from . import config, machine, miseajour, ollama_client, securite, travaux
from .i18n import t as _t


def preparer_environnement(cfg, dossiers):
    """Fixe l'environnement lu par le moteur AVANT son import (il lit ces variables au chargement)."""
    config.preparer(dossiers)
    actif = travaux.actif(cfg)
    travail = Path(actif["chemin"] if actif else Path.home() / "Lutin")
    travail.mkdir(parents=True, exist_ok=True)
    cache_catalogue = Path(dossiers["cache"]) / "catalogue.json"
    polyvalent = cfg["modeles"]["choisis"].get("polyvalent") or next(iter(cfg["modeles"]["choisis"].values()), "")
    env = {"LUTIN_RACINE": str(travail), "LUTIN_DONNEES": str(dossiers["donnees"]), "LUTIN_MEMOIRE": str(dossiers["memoire"]),
           "LUTIN_PORT": str(cfg["securite"]["port"]), "LUTIN_PROPOSITIONS": str(Path(dossiers["cache"]) / "propositions.json"), "LUTIN_BENCH": str(Path(dossiers["cache"]) / "bench.json"),
           "LUTIN_CONFIG": str(Path(dossiers["config"]) / "config.json"), "LUTIN_VERSION_CACHE": str(miseajour.fichier_version(dossiers))}
    if polyvalent:
        env["LUTIN_MODELE"] = polyvalent
    if cache_catalogue.is_file():
        env["LUTIN_CATALOGUE"] = str(cache_catalogue)
    os.environ.update(env)
    return travail


def s_assurer_qu_ollama_tourne(cfg, profil, ecrire=print):
    """Démarre Ollama s'il est installé mais arrêté. Renvoie True s'il répond."""
    o = ollama_client.Ollama()
    if o.actif():
        return True
    exe = ollama_client.trouver_executable(config.systeme())
    if not exe:
        ecrire(_t("Ollama n'est pas installé : lance « lutin setup »."))
        return False
    ollama_client.demarrer_serveur(exe, ollama_client.variables_serveur(profil, cfg["emplacements"]["modeles"]), config.systeme())
    import time
    for _ in range(30):
        if o.actif():
            return True
        time.sleep(0.5)
    ecrire(_t("Ollama ne répond pas après son démarrage."))
    return False


def lancer_serveur(cfg, dossiers, ouvrir_navigateur=True, ecrire=print):
    profil = machine.detecter()
    preparer_environnement(cfg, dossiers)
    if not ouvrir_navigateur:
        os.environ["LUTIN_SANS_NAVIGATEUR"] = "1"
    s_assurer_qu_ollama_tourne(cfg, profil, ecrire)
    from . import moteur
    moteur.SECURITE = securite.Securite.depuis_dict(cfg["securite"])
    moteur.PORT = int(cfg["securite"]["port"])
    moteur.APPAREILS = securite.Appareils(Path(dossiers["config"]) / "appareils.json")

    def verifier_a_la_demande(portee):
        """Boutons de l'onglet Modèles : la configuration est relue à chaque fois (les propositions refusées entre-temps comptent)."""
        return miseajour.verifier(profil, config.charger(dossiers), dossiers, ollama_client.Ollama(), force=True, portee=portee)
    moteur.VERIFICATEUR = verifier_a_la_demande
    if cfg.get("verifier_maj", True):
        def verification():
            try:
                miseajour.verifier(profil, cfg, dossiers, ollama_client.Ollama())
            except Exception as e:  # noqa: BLE001 — jamais bloquant
                ecrire(_t("(vérification des modèles impossible : {})").format(e))
        threading.Thread(target=verification, daemon=True, name="verification-modeles").start()

        def verification_lutin():
            while True:
                try:
                    miseajour.verifier_lutin(dossiers)
                except Exception:  # noqa: BLE001 — jamais bloquant, jamais bruyant
                    pass
                time.sleep(6 * 3600)          # le serveur peut tourner des semaines : on recontrôle (au plus une requête par 24 h grâce au cache)
        threading.Thread(target=verification_lutin, daemon=True, name="verification-lutin").start()
    moteur.principal()
