"""Les moteurs de modèles : ce qui fait réellement tourner un modèle de langage derrière Lutin.

Lutin parlait directement à Ollama. Cette couche met un nom sur ce que Lutin demande à un moteur, pour qu'un autre (llama.cpp server, LM Studio, vLLM, Strata… par leur interface compatible OpenAI)
prenne la place d'Ollama sans toucher au reste : conversation, outils, mémoire, missions, connecteurs.

Ce qu'un moteur sait faire (`Moteur`) :
  - discuter en flux continu (`chat_flux`) ou d'un coup (`chat`) : les messages vont et viennent dans le format d'Ollama (messages, outils, flux d'évènements {message, done, …}) ; un moteur d'un
    autre genre traduit à ses frontières ;
  - dire s'il répond (`actif`), quels modèles il propose (`modeles`), ce qu'un modèle sait faire (`capacites`) et la mémoire qu'il prend (`en_memoire`) ;
  - se décrire (`points_forts`, `points_faibles`, `description`) et dire ce qui est POSSIBLE avec lui (`actions`) : installer, désinstaller, réinstaller, démarrer, arrêter, télécharger ou supprimer
    un modèle. La page ne montre que ce qui est possible, avec la raison de ce qui ne l'est pas (Docker, système, droits) ;
  - faire ces actions en tâche de fond (`lancer_tache`), dont l'avancement est montré dans la barre d'état.
Aucune dépendance, et aucun import de moteur.py (pas de cycle) : le moteur Ollama est défini dans dialogue.py, à côté des fonctions qu'il enveloppe."""
import queue
import socket
import threading
import time

OLLAMA = "ollama"
LLAMACPP = "llamacpp"
OPENAI = "openai"
VERROU = threading.Lock()
MOTEURS = {}          # identifiant -> instance (voir enregistrer)
TACHES = {}          # identifiant du moteur -> {action, statut, texte, fait, total, erreur, debut}
ACTIONS = ("installer", "desinstaller", "reinstaller", "demarrer", "arreter", "mettre_a_jour")
# Ce que les moteurs ont besoin de savoir de Lutin sans l'importer (rempli par dialogue.py) : le dossier des données, Docker, le mode hors ligne, le profil de la machine.
CONTEXTE = {"donnees": lambda: None, "en_docker": lambda: False, "hors_ligne": lambda: False, "profil": lambda: None, "profil_attendu": None, "dossier_ollama": lambda: None}


def est_local(adresse):
    """L'adresse désigne-t-elle cette machine (127.0.0.1, localhost, ::1) ?"""
    import re
    return bool(re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(/|$)", str(adresse or ""), re.I))


class Moteur:
    """L'interface commune. Les attributs décrivent le moteur pour la page ; les méthodes sont ce que Lutin lui demande."""
    id = ""
    nom = ""
    genre = ""                  # « ollama » ou « openai » (llama.cpp, LM Studio, vLLM, Strata…)
    gere_modeles = False        # vrai : Lutin peut télécharger et supprimer des modèles par ce moteur
    description = ""
    points_forts = ()
    points_faibles = ()
    adresse_modifiable = False  # vrai : l'adresse du moteur se règle dans la page (moteur externe)

    # -- ce que Lutin demande pour discuter
    def actif(self):
        """Le moteur répond-il ?"""
        raise NotImplementedError

    def modeles(self):
        """{actif, installes: [noms], tailles: {nom: octets}} : les modèles que le moteur propose."""
        raise NotImplementedError

    def capacites(self, modele):
        """Ensemble des capacités du modèle (« tools », « thinking », « vision »…), ou None si le moteur ne le dit pas."""
        return None

    def en_memoire(self, modele):
        """{taille, vram} si le modèle est chargé, sinon None."""
        return None

    def chat(self, corps, delai=60):
        """Une réponse complète (sans flux) : renvoie le dictionnaire de la réponse, au format d'Ollama."""
        raise NotImplementedError

    def chat_flux(self, corps, delai=900):
        """Gestionnaire de contexte qui rend les évènements d'une réponse en flux, au format d'Ollama ({message, done, …} ; {error} en cas d'erreur). Fermer le gestionnaire coupe la génération."""
        raise NotImplementedError

    # -- ce que la page demande pour gérer le moteur
    def statut(self):
        """{installe, actif, version, detail} : l'état du moteur lui-même."""
        return {"installe": True, "actif": bool(self.actif()), "version": "", "detail": ""}

    def actions(self):
        """{action: {possible: bool, raison: texte}} pour chaque action de ACTIONS. « raison » dit pourquoi une action n'est pas possible (ou ce qu'elle fait)."""
        return {a: {"possible": False, "raison": ""} for a in ACTIONS}

    def faire(self, action, progression):
        """Fait une action de `actions()` ; `progression(texte, fait, total)` montre l'avancement. Lève ValueError avec un message clair en cas d'échec."""
        raise ValueError("Action impossible avec ce moteur.")

    def telechargeable(self):
        """Décrit comment obtenir des modèles avec ce moteur : {possible, raison, genre} (genre : « bibliotheque », « huggingface », « aucun »)."""
        return {"possible": False, "raison": "", "genre": "aucun"}

    def supprimer_modele(self, nom):
        raise ValueError("Ce moteur ne supprime pas ses modèles depuis Lutin.")

    def vue(self, courant=False):
        """Ce que la page affiche."""
        return {"id": self.id, "nom": self.nom, "genre": self.genre, "gere_modeles": self.gere_modeles, "description": self.description, "courant": bool(courant),
                "points_forts": list(self.points_forts), "points_faibles": list(self.points_faibles), "adresse_modifiable": self.adresse_modifiable}


def abandonner(reponse):
    """Coupe net une connexion HTTP en cours de lecture, même si un autre fil est bloqué dessus : le serveur de modèle voit la connexion se fermer et arrête de générer."""
    try:
        reponse.fp.raw._sock.shutdown(socket.SHUT_RDWR)
    except (AttributeError, OSError, ValueError):
        pass


class FluxInterruptible:
    """Les évènements d'une réponse en flux, lus dans un fil à part pour que le bouton Arrêter marche TOUJOURS : l'ouverture de la connexion (un modèle qui charge peut mettre des minutes à répondre)
    comme la lecture (un modèle qui se fige). `ouvrir()` rend le gestionnaire de flux du moteur ; `stop` est l'évènement du bouton Arrêter. Quand il est levé, la connexion est coupée et un évènement
    {"__stop__": True} est rendu : l'appelant le voit comme n'importe quel autre arrêt. Les erreurs du moteur (HTTP, réseau) sont relevées chez l'appelant, comme avant."""

    def __init__(self, ouvrir, stop, sondage=0.4):
        self.ouvrir, self.stop, self.sondage = ouvrir, stop, sondage
        self.file, self.flux, self.fini = queue.Queue(), None, False

    def _lire(self):
        try:
            self.flux = self.ouvrir()
            if self.fini:
                self.abandonner()
                return
            with self.flux:
                for e in self.flux:
                    self.file.put(("e", e))
            self.file.put(("fin", None))
        except BaseException as erreur:  # noqa: BLE001  (relevée chez l'appelant)
            self.file.put(("err", erreur))

    def __enter__(self):
        threading.Thread(target=self._lire, daemon=True, name="flux-moteur").start()
        return self

    def __exit__(self, *_):
        self.fini = True
        self.abandonner()
        return False

    def abandonner(self):
        reponse = getattr(self.flux, "reponse", None)
        if reponse is not None:
            abandonner(reponse)

    def __iter__(self):
        while True:
            try:
                genre, valeur = self.file.get(timeout=self.sondage)
            except queue.Empty:
                if self.stop is not None and self.stop.is_set():
                    self.fini = True
                    self.abandonner()
                    yield {"__stop__": True}
                    return
                continue
            if genre == "e":
                yield valeur
            elif genre == "fin":
                return
            else:
                raise valeur


def enregistrer(moteur):
    with VERROU:
        MOTEURS[moteur.id] = moteur
    return moteur


def liste():
    with VERROU:
        return list(MOTEURS.values())


def par_id(ident):
    """Le moteur de cet identifiant ; Ollama si l'identifiant est inconnu ou vide (un réglage ancien ne doit jamais empêcher de discuter)."""
    with VERROU:
        return MOTEURS.get(ident) or MOTEURS.get(OLLAMA)


def valide(ident):
    with VERROU:
        return ident in MOTEURS


# --------------------------------------------------------------------------- tâches de fond d'un moteur (installation, désinstallation, démarrage…)

def tache(ident):
    with VERROU:
        return dict(TACHES.get(ident) or {})


def toutes_les_taches():
    with VERROU:
        return {k: dict(v) for k, v in TACHES.items()}


def lancer_tache(moteur, action, executer=None, synchrone=False):
    """Lance `moteur.faire(action, progression)` dans un fil (ou tout de suite si `synchrone`, pour les tests). Une seule tâche à la fois par moteur."""
    with VERROU:
        en_cours = TACHES.get(moteur.id)
        if en_cours and en_cours.get("statut") == "en cours":
            raise ValueError("Une opération est déjà en cours avec ce moteur : attends sa fin.")
        TACHES[moteur.id] = {"action": action, "statut": "en cours", "texte": "", "fait": 0, "total": 0, "erreur": "", "debut": time.time()}

    def progression(texte="", fait=0, total=0):
        with VERROU:
            TACHES[moteur.id].update({"texte": str(texte), "fait": int(fait or 0), "total": int(total or 0)})

    def travail():
        try:
            (executer or moteur.faire)(action, progression)
            with VERROU:
                TACHES[moteur.id].update({"statut": "termine", "texte": "", "fait": 0, "total": 0})
            try:
                from . import moteurs_maj
                moteurs_maj.oublier(moteur.id)          # la version installée a peut-être changé : le prochain contrôle refera le constat
            except Exception:  # noqa: BLE001  (sans importance pour la tâche)
                pass
        except Exception as erreur:  # noqa: BLE001  (l'échec est montré dans la page, jamais une trace)
            with VERROU:
                TACHES[moteur.id].update({"statut": "erreur", "erreur": str(erreur)[:500]})
    if synchrone:
        travail()
    else:
        threading.Thread(target=travail, daemon=True, name="moteur-" + moteur.id).start()
    return tache(moteur.id)
