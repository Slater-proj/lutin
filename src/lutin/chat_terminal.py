"""`lutin chat` : discuter dans le terminal, comme dans l'interface web (mêmes outils, mêmes accords, même historique)."""
import sys

from .client import ErreurClient
from .i18n import t as _t

AIDE = """Commandes :
  /aide                 cette aide
  /nouvelle             nouvelle conversation
  /liste                tes conversations récentes
  /reprendre <numéro>   reprendre une conversation de la liste
  /modele [nom]         voir ou changer le modèle
  /mode travail|ecriture
  /reflexion            activer / couper la réflexion
  /quitter              sortir (Ctrl+D aussi)
Pendant une réponse : Ctrl+C l'arrête (ce qui est déjà fait est gardé)."""


class Terminal:
    def __init__(self, client, entree=input, sortie=None, erreur=None):
        self.client, self.entree = client, entree
        self.sortie = sortie or (lambda t: (sys.stdout.write(t), sys.stdout.flush()))
        self.erreur = erreur or (lambda t: print(t, file=sys.stderr))
        self.conversation = ""
        self.options = {"mode": "technique", "reflexion": False}
        self.recentes = []

    def ecrire(self, texte="", fin="\n"):
        self.sortie(texte + fin)

    def demander_accord(self, e):
        self.ecrire(_t("\n── Accord demandé : {}").format(e.get("titre", "")))
        if e.get("detail"):
            self.ecrire(str(e["detail"])[:1500])
        if e.get("diff"):
            self.ecrire(str(e["diff"])[:3000])
        try:
            reponse = self.entree("Autoriser ? [o/N] ").strip().lower()
        except EOFError:
            reponse = ""
        ok = reponse in ("o", "oui", "y", "yes")
        self.client.envoyer("/api/approuver", {"id": e["id"], "ok": ok})
        self.ecrire("   → " + (_t("accepté") if ok else _t("refusé")))

    def repondre(self, message):
        corps = dict(self.options, message=message, conversation=self.conversation)
        try:
            for e in self.client.flux("/api/chat", corps):
                t = e.get("type")
                if t == "debut":
                    self.conversation = e["conversation"]
                elif t == "texte":
                    self.ecrire(e["texte"], "")
                elif t == "pensee":
                    pass                                              # la réflexion reste dans l'interface web ; ici on affiche seulement la réponse
                elif t == "outil":
                    self.ecrire("\n⚙ {} {}".format(e.get("nom", ""), str(e.get("args", ""))[:160]))
                elif t == "resultat":
                    self.ecrire("  ↳ " + " ".join(str(e.get("texte", "")).split())[:200])
                elif t == "approbation":
                    self.demander_accord(e)
                elif t in ("info", "erreur"):
                    self.ecrire("\n{} {}".format("ⓘ" if t == "info" else "✘", e.get("texte", "")))
                elif t == "fin":
                    self.conversation = e["conversation"]["id"]
        except KeyboardInterrupt:
            if self.conversation:
                try:
                    self.client.envoyer("/api/arreter", {"conversation": self.conversation})
                except ErreurClient:
                    pass
            self.ecrire("\n(arrêté)")
        except ErreurClient as e:
            self.erreur("✘ " + str(e))
        self.ecrire()

    def commande(self, ligne):
        mot, _, arg = ligne[1:].partition(" ")
        arg = arg.strip()
        if mot in ("quitter", "q", "exit"):
            return False
        if mot == "aide":
            self.ecrire(_t(AIDE))
        elif mot == "nouvelle":
            self.conversation = ""
            self.ecrire("Nouvelle conversation.")
        elif mot == "liste":
            self.recentes = self.client.obtenir("/api/etat")["conversations"][:15]
            for i, c in enumerate(self.recentes, 1):
                self.ecrire("{:>3}. {}".format(i, c.get("titre") or "(sans titre)"))
        elif mot == "reprendre":
            if arg.isdigit() and 1 <= int(arg) <= len(self.recentes):
                self.conversation = self.recentes[int(arg) - 1]["id"]
                self.ecrire("Conversation reprise : " + (self.recentes[int(arg) - 1].get("titre") or ""))
            else:
                self.ecrire(_t("Fais d'abord /liste, puis /reprendre <numéro>."))
        elif mot == "modele":
            if arg:
                self.client.envoyer("/api/reglages", {"modele": arg})
            self.ecrire(_t("Modèle : ") + self.client.obtenir("/api/etat")["reglages"]["modele"])
        elif mot == "mode":
            if arg in ("travail", "ecriture", _t("écriture")):
                self.options["mode"] = "technique" if arg == "travail" else "scenario"
            self.ecrire(_t("Mode : ") + ("travail" if self.options["mode"] == "technique" else _t("écriture")))
        elif mot == "reflexion":
            self.options["reflexion"] = not self.options["reflexion"]
            self.ecrire(_t("Réflexion : ") + (_t("activée") if self.options["reflexion"] else _t("coupée")))
        else:
            self.ecrire(_t("Commande inconnue. /aide pour la liste."))
        return True

    def boucle(self):
        self.ecrire(_t("Lutin : écris ta demande (/aide pour les commandes, /quitter pour sortir)."))
        while True:
            try:
                ligne = self.entree("› ").strip()
            except EOFError:
                self.ecrire()
                return 0
            except KeyboardInterrupt:
                self.ecrire(_t("\n(Ctrl+D ou /quitter pour sortir)"))
                continue
            if not ligne:
                continue
            if ligne.startswith("/"):
                try:
                    if not self.commande(ligne):
                        return 0
                except ErreurClient as e:
                    self.erreur("✘ " + str(e))
                continue
            self.repondre(ligne)
