"""Les moteurs de modèles : ce qui fait réellement tourner un modèle de langage derrière Lutin.

Lutin parlait directement à Ollama. Cette couche met un nom sur ce que Lutin demande à un moteur, pour qu'un autre (llama.cpp server, LM Studio, vLLM… par leur interface compatible OpenAI) puisse
prendre la place d'Ollama sans toucher au reste : conversation, outils, mémoire, missions, connecteurs.

Ce qu'un moteur sait faire (`Moteur`) :
  - discuter en flux continu (`chat_flux`) ou d'un coup (`chat`) : les messages vont et viennent dans le format d'Ollama (messages, outils, flux d'évènements {message, done, …}) ; un moteur d'un
    autre genre traduit à ses frontières ;
  - dire s'il répond (`actif`), quels modèles il propose (`modeles`), ce qu'un modèle sait faire (`capacites`) et la mémoire qu'il prend (`en_memoire`) ;
  - gérer lui-même ses modèles ou non (`gere_modeles`) : Ollama télécharge et supprime ; les autres moteurs ont leurs modèles à eux, que Lutin liste sans y toucher.
Aucune dépendance, et aucun import de moteur.py (pas de cycle) : le moteur Ollama est défini dans dialogue.py, à côté des fonctions qu'il enveloppe."""
import threading

OLLAMA = "ollama"
VERROU = threading.Lock()
MOTEURS = {}          # identifiant -> instance (voir enregistrer)


class Moteur:
    """L'interface commune. Les attributs décrivent le moteur pour la page ; les méthodes sont ce que Lutin lui demande."""
    id = ""
    nom = ""
    genre = ""                  # « ollama », puis « openai » (llama.cpp, LM Studio, vLLM, Strata…)
    gere_modeles = False        # vrai : Lutin peut télécharger et supprimer des modèles par ce moteur
    description = ""

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

    def vue(self, courant=False):
        """Ce que la page affiche."""
        return {"id": self.id, "nom": self.nom, "genre": self.genre, "gere_modeles": self.gere_modeles, "description": self.description, "courant": bool(courant)}


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
