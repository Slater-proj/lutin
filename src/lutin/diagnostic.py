"""Le diagnostic de démarrage : ce qui empêche Lutin de répondre, ou le gêne, dit clairement dès l'ouverture de la page, avec ce qu'il faut faire.

La pastille « Ollama » verte veut dire que le SERVEUR Ollama tourne ; elle ne dit pas qu'un modèle est installé. Un conteneur neuf, par exemple, a Ollama mais aucun modèle : sans ce diagnostic,
le premier message (ou le test de la machine) tombait sur une erreur obscure. Chaque problème porte un `niveau` (erreur : Lutin ne peut pas répondre ; attention : il répondra mal) et une `action`
que la page propose en un clic (installer le modèle conseillé, démarrer Ollama, ouvrir l'onglet Modèles)."""
import os

from . import selection
from .i18n import t as _t

SEUIL_DISQUE_GO = 2.0


def modele_conseille(profil, catalogue):
    """(identifiant, taille en Go) du modèle le plus adapté à cette machine pour un premier essai, ou None si on ne sait pas encore (machine pas détectée)."""
    if profil is None:
        return None
    try:
        choix = selection.choisir(profil, catalogue)
    except (KeyError, TypeError, ValueError):
        return None
    for role in ("polyvalent", "rapide"):
        c = choix.get(role)
        if c is not None:
            return c.id, c.modele.get("go")
    return next(((c.id, c.modele.get("go")) for c in choix.values() if c is not None), None)


def _ollama_autre_conteneur():
    """OLLAMA_URL désigne-t-il un autre conteneur ? Sinon Lutin installe et lance Ollama lui-même (ollama.log dans le volume /data)."""
    from . import moteurs_docker
    return moteurs_docker.ollama_externe()


def premier_lancement(moteur_nom, actif, detail, recommande=None):
    """Le premier lancement : tant qu'AUCUN moteur n'est prêt, la page n'envoie pas l'utilisateur dans l'onglet Modèles (où rien ne marcherait) : elle dit pourquoi et propose d'installer le moteur conseillé,
    d'en choisir un autre ou de remettre à plus tard. {pret, raison, recommande}. `recommande` : la recommandation de bench_moteurs (moteur, nom, raison)."""
    if actif:
        return {"pret": True, "raison": "", "recommande": None}
    raison = _t("Aucun moteur n'est prêt : « {} » ne répond pas ({}). Les modèles se gèrent dans le moteur, donc cet onglet attend qu'un moteur soit prêt.").format(moteur_nom, detail or _t("pas installé ou arrêté"))
    return {"pret": False, "raison": raison, "recommande": recommande}


def diagnostiquer(ollama_actif, ollama_installe, installes, reglages, profil=None, catalogue=None, adequation=None, disque_libre_go=None, docker=None, conseils=None, modeles_ailleurs=None):
    """La liste des problèmes, du plus grave au moins grave : [{code, niveau, texte, action}]. Vide quand tout va bien."""
    docker = (os.environ.get("LUTIN_DOCKER") == "1") if docker is None else docker
    problemes = []
    if not ollama_actif:
        if docker and _ollama_autre_conteneur():
            texte = _t("Ollama ne répond pas dans son conteneur : Lutin ne peut pas répondre. Regarde pourquoi avec « docker logs » sur le conteneur d'Ollama (OLLAMA_URL).")
            action = None
        elif ollama_installe:
            texte = _t("Ollama est arrêté : Lutin ne peut pas répondre tant qu'il ne tourne pas.")
            action = {"type": "demarrer_ollama"}
        else:
            texte = _t("Ollama n'est pas installé : Lutin en a besoin pour faire tourner les modèles (ollama.com).")
            action = {"type": "onglet", "nom": "reglages"}          # c'est dans Réglages > Moteurs qu'on l'installe : l'onglet Modèles n'a rien à montrer sans moteur
        problemes.append({"code": "ollama_arret", "niveau": "erreur", "texte": texte, "action": action})
    elif not installes and modeles_ailleurs:
        problemes.append({"code": "modeles_ailleurs", "niveau": "erreur", "action": {"type": "redemarrer_ollama"},
                          "texte": _t("Ollama tourne mais ne voit aucun modèle, alors que {} en contient {} : il a été relancé sans ton dossier de modèles habituel. Tes modèles ne sont pas perdus ; redémarre Ollama pour qu'il retrouve ce dossier.").format(modeles_ailleurs[0], modeles_ailleurs[1])})
    elif not installes:
        conseil = modele_conseille(profil, catalogue) if profil is not None and catalogue else None
        if conseil:
            texte = _t("Ollama tourne, mais aucun modèle n'est installé : Lutin ne peut pas encore répondre. Le plus adapté à cette machine : « {} » ({} Go).").format(conseil[0], conseil[1])
            action = {"type": "installer_modele", "modele": conseil[0], "go": conseil[1]}
        else:
            texte = _t("Ollama tourne, mais aucun modèle n'est installé : Lutin ne peut pas encore répondre. Installe-en un dans l'onglet Modèles.")
            action = {"type": "onglet", "nom": "modeles"}
        problemes.append({"code": "aucun_modele", "niveau": "erreur", "texte": texte, "action": action})
    else:
        choisi = (reglages or {}).get("modele", "")
        if choisi and choisi not in installes:
            problemes.append({"code": "modele_absent", "niveau": "attention", "texte": _t("Le modèle choisi « {} » n'est pas installé : choisis-en un déjà installé en haut à gauche.").format(choisi),
                              "action": {"type": "onglet", "nom": "modeles"}})
        elif choisi and (adequation or {}).get(choisi, {}).get("niveau") == "trop_gros":
            problemes.append({"code": "modele_trop_gros", "niveau": "attention", "texte": _t("Le modèle « {} » est trop gros pour cette machine : {}").format(choisi, (adequation[choisi] or {}).get("texte", "")),
                              "action": {"type": "onglet", "nom": "modeles"}})
    if conseils and (reglages or {}).get("conseil_machine", True) and not any(p["niveau"] == "erreur" for p in problemes):
        problemes.append({"code": "petite_machine", "niveau": "info", "texte": _t("Réglages conseillés pour cette machine (processeur ou peu de mémoire) : ") + " ".join(c["texte"] for c in conseils),
                          "action": {"type": "appliquer_conseil"}, "action2": {"type": "ignorer_conseil"}})
    if disque_libre_go is not None and disque_libre_go < SEUIL_DISQUE_GO:
        problemes.append({"code": "disque", "niveau": "attention", "texte": _t("Il reste moins de {:g} Go sur le disque des données de Lutin : les modèles et les fichiers ne tiendront pas.").format(SEUIL_DISQUE_GO), "action": None})
    return problemes
