"""Client de la ligne de commande : parle au serveur Lutin de CETTE machine avec le jeton de la console (fichier réservé à l'utilisateur), par /api/v1."""
import json
import urllib.error
import urllib.request
from pathlib import Path
from .i18n import t as _t


class ClientError(RuntimeError):
    pass


class LocalClient:
    def __init__(self, dossier_donnees, ouvrir=urllib.request.urlopen):
        self.fichier, self.ouvrir = Path(dossier_donnees) / "console.json", ouvrir
        self.adresse = self.jeton = ""

    def lire_fichier(self):
        try:
            d = json.loads(self.fichier.read_text(encoding="utf-8"))
            self.adresse, self.jeton = d["adresse"].rstrip("/"), d["jeton"]
            return True
        except (OSError, ValueError, KeyError):
            return False

    def _requete(self, chemin, corps=None, delai=30, methode=None):
        if not self.adresse and not self.lire_fichier():
            raise ClientError(_t("Lutin ne tourne pas. Lance « lutin serve » dans une autre fenêtre."))
        donnees = None if corps is None else json.dumps(corps).encode("utf-8")
        req = urllib.request.Request(self.adresse + "/api/v1" + chemin, data=donnees, headers={"Content-Type": "application/json", "X-Token": self.jeton}, method=methode)
        try:
            return self.ouvrir(req, timeout=delai)
        except urllib.error.HTTPError as e:
            try:
                message = (json.loads(e.read().decode("utf-8")).get("error") or {}).get("message", "")          # every v1 error: {"error": {"code", "message"}}
            except (ValueError, AttributeError):
                message = ""
            raise ClientError(message or "erreur {}".format(e.code)) from e
        except (OSError, urllib.error.URLError) as e:
            raise ClientError(_t("Lutin ne répond pas ({}). Lance « lutin serve » dans une autre fenêtre.").format(self.adresse or "serveur inconnu")) from e

    def disponible(self):
        if not self.lire_fichier():
            return False
        try:
            with self._requete("/status", delai=3):
                return True
        except ClientError:
            return False

    def obtenir(self, chemin):
        with self._requete(chemin) as r:
            return json.loads(r.read().decode("utf-8"))

    def envoyer(self, chemin, corps, methode="POST"):
        with self._requete(chemin, corps, methode=methode) as r:
            return json.loads(r.read().decode("utf-8") or "{}")

    def supprimer(self, chemin):
        with self._requete(chemin, methode="DELETE") as r:
            return json.loads(r.read().decode("utf-8") or "{}")

    def flux(self, chemin, corps):
        """Évènements d'une réponse en cours (une ligne JSON chacun)."""
        with self._requete(chemin, corps, delai=3600) as r:
            for brut in r:
                try:
                    yield json.loads(brut.decode("utf-8"))
                except ValueError:
                    continue
