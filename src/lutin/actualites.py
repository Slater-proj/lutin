"""Les actualités avec un petit modèle : Lutin enchaîne lui-même les étapes.

« Les news du jour » demande de chercher, de lire quelques pages puis de résumer. Un petit modèle (7 milliards de paramètres ou moins) se perd dans cet enchaînement : il répond à côté, recopie
des liens ou n'appelle aucun outil. Ici, quand la demande est une demande d'actualités et que le modèle est petit, Lutin fait la recherche et la lecture des pages (les outils web habituels,
résultat jamais affiché brut), puis ne laisse au modèle que le travail qu'il sait faire : résumer ce qu'on lui met sous les yeux, sans outil. Un modèle plus grand garde la main."""
import re
from datetime import date

from . import moteur as _m
from .i18n import t as _t

PETIT_B = 10          # au plus 10 milliards de paramètres : le modèle est « petit » pour cette tâche
DEMANDE = re.compile(r"\b(actualit[ée]s?|news|nouvelles?\s+du\s+jour|derni[eè]res?\s+nouvelles?|quoi\s+de\s+neuf|infos?\s+du\s+jour|à\s+la\s+une|headlines|what'?s\s+new\s+today)\b", re.I)
NETTOYAGE = re.compile(r"^(?:peux-tu|pourrais-tu|tu\s+peux|donne[- ]moi|dis[- ]moi|je\s+voudrais|j'aimerais|cherche|trouve|résume|résumé\s+de)\s+", re.I)


def demande_actualites(texte):
    """Le message demande-t-il des nouvelles récentes (et pas, par exemple, de corriger une phrase qui contient le mot « news ») ? Message court, d'une ou deux phrases."""
    texte = str(texte or "").strip()
    return bool(texte) and len(texte) <= 300 and bool(DEMANDE.search(texte))


def milliards_du_modele(nom):
    """Taille d'un modèle en milliards de paramètres d'après le catalogue ou son nom (« qwen3:8b ») ; 0 si on ne sait pas."""
    nom = str(nom or "")
    for m in (_m._CATALOGUE.get("modeles") or []):
        if m.get("id") == nom and m.get("params_b"):
            return float(m["params_b"])
    trouve = re.search(r"(?<![\w.])(\d+(?:\.\d+)?)b\b", nom.lower())
    return float(trouve.group(1)) if trouve else 0


def petit_modele(nom):
    """Petit, ou de taille inconnue : dans le doute on guide (guider un grand modèle ne coûte presque rien, ne pas guider un petit le fait échouer)."""
    b = milliards_du_modele(nom)
    return b == 0 or b <= PETIT_B


MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
MOTS_VIDES = frozenset("""tu peux pourrais me moi te toi nous vous je j il ils elle elles on s c d l m n t qu que qui quoi quand est sont ce cette ces ca ça et ou a à au aux en dans sur sous pour par avec sans
le la les un une des du de mon ma mes ton ta tes son sa ses leur leurs chercher cherche cherches trouve trouver donne donner dis dire montre montrer voir fais faire peut veux voudrais aimerais svp stp merci
bonjour salut hello alors aussi encore plutot plutôt vraiment""".split())


def requete(texte, aujourdhui=None, reformuler=None):
    """La requête de recherche. Si `reformuler` est donné (un appel court au modèle : il corrige les fautes et ne garde que le sujet), on l'essaie d'abord ; sinon, ou s'il échoue, la demande est nettoyée
    (formules de politesse, mots vides, ponctuation). Le mois et l'année attirent des résultats récents (une date jj/mm/aaaa, elle, fait chuter la pertinence d'un moteur de recherche)."""
    aujourdhui = aujourdhui or date.today()
    sujet = ""
    if reformuler is not None:
        try:
            propose = str(reformuler(texte) or "").strip().splitlines()
            sujet = " ".join(re.sub(r"[^\w' -]", " ", propose[0] if propose else "").split())[:120]
        except (OSError, ValueError, IndexError):
            sujet = ""
    if not sujet or len(sujet.split()) > 14:
        brut = NETTOYAGE.sub("", " ".join(str(texte or "").split()))
        mots = [m for m in re.findall(r"[\w'’-]+", brut.lower()) if m not in MOTS_VIDES and len(m) > 1]
        sujet = " ".join(mots[:12])
    return "{} {} {}".format(sujet or "actualités", MOIS[aujourdhui.month - 1], aujourdhui.year)[:200]


def consigne(aujourdhui=None):
    aujourdhui = aujourdhui or date.today()
    return _t("Nous sommes le {}. Les résultats de recherche et les pages lues sont au-dessus. Fais maintenant une synthèse courte de l'actualité qu'ils contiennent : 5 à 8 points, une phrase par point, "
              "en citant le média ou le site de chaque information. N'invente rien : si les sources ne couvrent pas la question, dis-le simplement. Réponds dans la langue de la demande.").format(aujourdhui.strftime("%d/%m/%Y"))


def preparer(conv, texte, ctx, emit, chercher=None, reformuler=None):
    """Fait la recherche et la lecture à la place du modèle ; ajoute l'appel et son résultat à la conversation (comme s'il les avait demandés). Renvoie la consigne de synthèse, ou None si la recherche
    n'a rien donné (la boucle habituelle prend alors le relais). Lève ErreurOutil si le web est coupé."""
    from . import web
    chercher = chercher or web.outil_web_chercher
    q = requete(texte, reformuler=reformuler)
    args = {"requete": q, "nombre": 6, "lire": 3}
    emit({"type": "info", "texte": _t("🔎 Actualités : je cherche et je lis quelques sources, puis je les résume.")})
    emit({"type": "outil", "nom": "web_chercher", "args": args})
    resultat = chercher(q, 6, ctx, 3)
    if not resultat or "CONTENU WEB NON FIABLE" not in str(resultat)[:80]:          # pas de résultat (ou une réponse sans l'avertissement des pages web)
        emit({"type": "resultat", "nom": "web_chercher", "texte": str(resultat)[:300]})
        conv["messages"].append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "web_chercher", "arguments": args}}]})
        conv["messages"].append({"role": "tool", "tool_name": "web_chercher", "content": str(resultat)})
        return None
    emit({"type": "resultat", "nom": "web_chercher", "texte": _t("(résultat transmis à l'assistant, non affiché)")})
    conv["messages"].append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "web_chercher", "arguments": args}}]})
    conv["messages"].append({"role": "tool", "tool_name": "web_chercher", "content": resultat})
    return consigne()
