"""Séparer la réflexion d'un modèle de sa réponse.

Un modèle « qui réfléchit » écrit sa réflexion avant sa réponse. Ollama et certains serveurs la rendent à part (champ `thinking`) ; d'autres (llama.cpp sans réglage, LM Studio, ExLlamaV3, un modèle dont le
gabarit n'est pas reconnu…) la laissent DANS le texte, entre `<think>` et `</think>`. Sans traitement, la page montrait un seul énorme message qui commence par la balise. Ce module lit le flux au fil
de l'eau (une balise coupée entre deux morceaux est reconnue) et rend la réflexion à part : la page l'affiche, comme pour les autres, dans un bloc repliable au-dessus de la réponse.

Seule une balise placée AU DÉBUT de la réponse ouvre une réflexion : un modèle qui écrirait « <think> » au milieu d'un texte (un article sur le sujet, du code) n'est pas touché."""
import re

BALISES = (("<think>", "</think>"), ("<thinking>", "</thinking>"), ("<reasoning>", "</reasoning>"))
RE_BLOC = re.compile(r"^\s*<(think|thinking|reasoning)>(.*?)</\1>\s*", re.S | re.I)


def separer(texte):
    """(réflexion, réponse) d'un texte entier : la réflexion est le bloc balisé du début, s'il y en a un (sinon '' et le texte tel quel). Sert aux conversations déjà enregistrées."""
    m = RE_BLOC.match(str(texte or ""))
    if not m:
        return "", str(texte or "")
    return m.group(2).strip(), str(texte)[m.end():]


class Separateur:
    """À alimenter avec les morceaux du texte d'une réponse, dans l'ordre ; rend à chaque fois une liste de (genre, texte) où genre est « pensee » ou « texte ». `fin()` vide ce qui était retenu."""

    def __init__(self):
        self.tampon = ""
        self.ferme = None          # la balise fermante attendue tant qu'on est dans la réflexion
        self.debut = True          # rien de visible n'a encore été écrit : une balise ouvrante est possible
        self.apres = False         # la réflexion vient de finir : les sauts de ligne qui séparent la réponse sont retirés

    def alimenter(self, morceau):
        self.tampon += str(morceau or "")
        sortie = []
        while self.tampon:
            if self.ferme:
                i = self.tampon.lower().find(self.ferme)
                if i >= 0:
                    if i:
                        sortie.append(("pensee", self.tampon[:i]))
                    self.tampon = self.tampon[i + len(self.ferme):]
                    self.ferme, self.apres = None, True
                    continue
                garde = self._debut_de(self.ferme)
                envoyer = self.tampon[:len(self.tampon) - garde]
                if envoyer:
                    sortie.append(("pensee", envoyer))
                self.tampon = self.tampon[len(self.tampon) - garde:]
                break
            if self.debut:
                s = self.tampon.lstrip()
                if not s:
                    break                                    # que des espaces pour l'instant : on attend de savoir
                bas = s.lower()
                ouverte = next(((o, f) for o, f in BALISES if bas.startswith(o)), None)
                if ouverte:
                    self.tampon, self.ferme, self.debut = s[len(ouverte[0]):], ouverte[1], False
                    continue
                if any(o.startswith(bas) for o, _ in BALISES):
                    break                                    # « <thi » : peut-être le début d'une balise, on attend la suite
                self.debut = False
            texte = self.tampon.lstrip("\r\n") if self.apres else self.tampon
            self.tampon = ""
            if texte:
                self.apres = False
                sortie.append(("texte", texte))
        return sortie

    def _debut_de(self, balise):
        """Combien de caractères de fin du tampon pourraient être le début de cette balise (à garder pour le morceau suivant)."""
        bas = self.tampon.lower()
        for n in range(min(len(balise) - 1, len(bas)), 0, -1):
            if balise.startswith(bas[-n:]):
                return n
        return 0

    def fin(self):
        reste, self.tampon = self.tampon, ""
        if not reste:
            return []
        return [("pensee" if self.ferme else "texte", reste)]
