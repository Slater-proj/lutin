"""`lutin chat` : discuter dans le terminal, comme dans l'interface web (mêmes outils, mêmes accords, même historique)."""
import sys

from .client import ClientError
from .i18n import t as _t

HELP = """Commandes :
  /aide                 cette aide
  /nouvelle             nouvelle conversation
  /liste                tes conversations récentes
  /reprendre <numéro>   reprendre une conversation de la liste
  /modele [nom]         voir ou changer le modèle
  /mode travail|ecriture
  /reflexion            activer / couper la réflexion
  /quitter              sortir (Ctrl+D aussi)
Pendant une réponse : Ctrl+C l'arrête (ce qui est déjà fait est gardé)."""


MODE_ALIASES = {"polyvalent": "polyvalent", "travail": "technique", "code": "technique", "technique": "technique", "ecriture": "scenario", "écriture": "scenario", "scenario": "scenario",
               "recherche": "recherche", "discussion": "discussion"}
MODE_NAMES = {"polyvalent": "polyvalent", "technique": "travail", "scenario": "écriture", "recherche": "recherche", "discussion": "discussion"}
V1_MODES = {"polyvalent": "general", "technique": "technical", "scenario": "scenario", "recherche": "research", "discussion": "chat"}          # the words of /api/v1 (api_v1.SETTING_WORDS)


class Terminal:
    def __init__(self, client, entree=input, sortie=None, erreur=None):
        self.client, self.entree = client, entree
        self.sortie = sortie or (lambda t: (sys.stdout.write(t), sys.stdout.flush()))
        self.erreur = erreur or (lambda t: print(t, file=sys.stderr))
        self.conversation = ""
        self.options = {"mode": "polyvalent", "reflexion": False}
        self.recentes = []
        self.mode_sent = None          # (conversation, mode) last written to the options of the conversation

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
        self.client.envoyer("/approvals/" + e["id"], {"approved": ok})
        self.ecrire("   → " + (_t("accepté") if ok else _t("refusé")))

    def repondre(self, message):
        try:
            if not self.conversation:
                self.conversation = self.client.envoyer("/conversations", {})["id"]
            if self.mode_sent != (self.conversation, self.options["mode"]):
                self.client.envoyer("/conversations/{}/options".format(self.conversation), {"mode": V1_MODES[self.options["mode"]]}, "PATCH")
                self.mode_sent = (self.conversation, self.options["mode"])
            for e in self.client.flux("/conversations/{}/turns".format(self.conversation), {"message": message, "thinking": self.options["reflexion"]}):
                t = e.get("type")
                if t == "text":
                    self.ecrire(e.get("text", ""), "")
                elif t == "tool_call":
                    self.ecrire("\n⚙ {} {}".format(e.get("name", ""), str(e.get("arguments", ""))[:160]))
                elif t == "tool_result":
                    self.ecrire("  ↳ " + " ".join(str(e.get("text", "")).split())[:200])
                elif t == "approval_request":
                    self.demander_accord(e)
                elif t == "notice":
                    self.ecrire("\nⓘ " + str(e.get("text", "")))
                elif t == "error":
                    self.ecrire("\n✘ " + str((e.get("error") or {}).get("message", "")))
                elif t == "end":
                    self.conversation = (e.get("conversation") or {}).get("id") or self.conversation
                # the thinking stays in the web interface: here only the answer is shown
        except KeyboardInterrupt:
            if self.conversation:
                try:
                    self.client.envoyer("/conversations/{}/stop".format(self.conversation), {})
                except ClientError:
                    pass
            self.ecrire("\n(arrêté)")
        except ClientError as e:
            self.erreur("✘ " + str(e))
        self.ecrire()

    def commande(self, ligne):
        mot, _, arg = ligne[1:].partition(" ")
        arg = arg.strip()
        if mot in ("quitter", "q", "exit"):
            return False
        if mot == "aide":
            self.ecrire(_t(HELP))
        elif mot == "nouvelle":
            self.conversation = ""
            self.ecrire("Nouvelle conversation.")
        elif mot == "liste":
            self.recentes = self.client.obtenir("/conversations")["conversations"][:15]
            for i, c in enumerate(self.recentes, 1):
                self.ecrire("{:>3}. {}".format(i, c.get("title") or "(sans titre)"))
        elif mot == "reprendre":
            if arg.isdigit() and 1 <= int(arg) <= len(self.recentes):
                self.conversation = self.recentes[int(arg) - 1]["id"]
                self.ecrire("Conversation reprise : " + (self.recentes[int(arg) - 1].get("title") or ""))
            else:
                self.ecrire(_t("Fais d'abord /liste, puis /reprendre <numéro>."))
        elif mot == "modele":
            if arg:
                self.client.envoyer("/settings", {"model": arg}, "PATCH")
            self.ecrire(_t("Modèle : ") + self.client.obtenir("/settings")["model"])
        elif mot == "mode":
            if arg in MODE_ALIASES:
                self.options["mode"] = MODE_ALIASES[arg]
            elif arg:
                self.ecrire(_t("Modes : polyvalent, travail, écriture, recherche, discussion."))
            self.ecrire(_t("Mode : ") + _t(MODE_NAMES[self.options["mode"]]))
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
                except ClientError as e:
                    self.erreur("✘ " + str(e))
                continue
            self.repondre(ligne)
