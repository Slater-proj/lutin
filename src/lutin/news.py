"""Les actualités avec un petit modèle : Lutin enchaîne lui-même les étapes.

« Les news du jour » demande de chercher, de lire quelques pages puis de résumer. Un petit modèle (7 milliards de paramètres ou moins) se perd dans cet enchaînement : il répond à côté, recopie
des liens ou n'appelle aucun outil. Ici, quand la demande est une demande d'actualités et que le modèle est petit, Lutin fait la recherche et la lecture des pages (les outils web habituels,
résultat jamais affiché brut), puis ne laisse au modèle que le travail qu'il sait faire : résumer ce qu'on lui met sous les yeux, sans outil. Un modèle plus grand garde la main."""
import re
from datetime import date

from . import core as _m
from .i18n import t as _t

PETIT_B = 10          # au plus 10 milliards de paramètres : le modèle est « petit » pour cette tâche
DEMANDE = re.compile(r"\b(actualit[ée]s?|news|nouvelles?\s+du\s+jour|derni[eè]res?\s+nouvelles?|quoi\s+de\s+neuf|infos?\s+du\s+jour|à\s+la\s+une|headlines|what'?s\s+new\s+today)\b", re.I)
NETTOYAGE = re.compile(r"^(?:peux-tu|pourrais-tu|tu\s+peux|donne[- ]moi|dis[- ]moi|je\s+voudrais|j'aimerais|cherche|trouve|résume|résumé\s+de)\s+", re.I)


def demande_actualites(texte):
    """Le message demande-t-il des nouvelles récentes (et pas, par exemple, de corriger une phrase qui contient le mot « news ») ? Message court, d'une ou deux phrases."""
    texte = str(texte or "").strip()
    return bool(texte) and len(texte) <= 300 and bool(DEMANDE.search(texte))


URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
EXPLICITE = re.compile(r"\b(cherch\w*|recherch\w*|sur\s+(?:internet|le\s+(?:web|net))|en\s+ligne|google|search(?:\s+for)?|look\s*up)\b", re.I)
LIEN = re.compile(r"\b(liens?|links?)\b", re.I)          # « donne-moi le lien de la page html » peut être un fichier de TON dossier : un lien ne suffit pas à partir sur internet
SUJET_WEB = re.compile(r"\b(site|sites|article|articles|vid[ée]o|youtube|wikip[ée]dia|actualit\w*|tuto\w*|documentation|officiel\w*|internet|web|blog|forum|github|reddit)\b", re.I)
IMPLICITE = re.compile(r"\b(qui\s+est|c'?est\s+qui|histoire\s+de|derni[eè]res?|r[ée]cents?|prix\s+d\w*|m[ée]t[ée]o|cours\s+d\w*|quand\s+sort|date\s+de\s+sortie|who\s+is|latest|price\s+of|weather)\b", re.I)
PAS_LE_WEB = re.compile(r"```|\b(code|fichiers?|script|bug|erreur|fonction|dossiers?|d[ée]p[ôo]t|repo|projet|variable|classe|commande|html?|css|galerie|chemin|r[ée]pertoire|disque|nas|sauvegard\w*|locale?s?)\b|\b[\w-]+\.(?:html?|md|py|js|pdf|png|jpe?g|webp|txt|json|csv|docx?|xlsx?|pptx?|zip|mp4)\b|[A-Za-z]:\\|\\\\|\bfile:///", re.I)
SUJET_VIDE = frozenset("internet web net ligne lien liens link links google recherche recherches recherché cherché sources source article articles info infos information informations sujet propos".split())


NOM_RECHERCHE = re.compile(r"\b(?:de|des|la|une|ta|tes|ma|mes|cette|ces|ton|mon|en|ou|et)\s+recherches?\b", re.I)          # « tes résultats de recherche » : un nom, pas un ordre
RECLAMATION = re.compile(r"\btu\s+(?:ne|n')|\b(?:m')?as\s+pas\b|\bm[êe]me\s+r[ée]ponse\b|\bd[ée]j[àa]\b", re.I)                    # « tu ne m'as pas donné… », « c'est la même réponse » : un reproche, pas une demande
ORDRE_RECHERCHE = re.compile(r"\b(?:fai[ts]|fais|faire|lance[rz]?|effectue[rz]?|fait)\s+(?:moi\s+)?(?:une\s+)?recherches?\b", re.I)          # « fais une recherche sur… » : là, c'est bien un ordre
NOM_PROPRE = re.compile(r"[A-ZÀ-ÖØ-Þ][\wà-öø-ÿ'’-]+(?:\s+[A-ZÀ-ÖØ-Þ][\wà-öø-ÿ'’-]+)*")


def noms_propres(texte):
    """Les noms propres de la demande (« Fiona Warr »), hors début de phrase : ils servent à entourer la recherche de guillemets et à vérifier que les résultats parlent bien de la personne."""
    texte = URL.sub(" ", str(texte or ""))
    sortie = []
    for m in NOM_PROPRE.finditer(texte):
        debut = texte[:m.start()].rstrip()
        if not debut or debut[-1] in ".!?:":
            continue
        nom = m.group(0).strip(" '’-")
        if len(nom) > 2 and nom not in sortie:
            sortie.append(nom)
    return sortie[:2]


def mode_guide(texte, modele):
    """Comment Lutin aide ce message : « lecture » (une adresse collée : il lit la page), « actualites », « recherche » (le message demande de chercher), ou '' (le modèle décide seul).
    Une demande claire de chercher est guidée pour tous les modèles (la recherche est demandée de toute façon) ; une question qui suppose le web sans le dire (« qui est… », « le dernier… »)
    seulement pour un petit modèle, qui n'appelle pas l'outil de lui-même."""
    texte = str(texte or "").strip()
    if not texte or len(texte) > 400 or "```" in texte:
        return ""
    if URL.search(texte) and len(URL.sub("", texte).split()) <= 25:
        return "lecture"
    if DEMANDE.search(texte):
        return "actualites" if petit_modele(modele) else ""
    if PAS_LE_WEB.search(texte) or RECLAMATION.search(texte) or not _mots(texte):          # code, fichiers... ; un reproche ; ou rien à chercher (« Cherche » tout seul)
        return ""
    sans_nom = NOM_RECHERCHE.sub(" ", texte)
    if EXPLICITE.search(sans_nom) or ORDRE_RECHERCHE.search(texte) or (LIEN.search(sans_nom) and SUJET_WEB.search(texte)):
        return "recherche"
    return "recherche" if IMPLICITE.search(texte) and petit_modele(modele) else ""


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


def _mots(texte):
    brut = NETTOYAGE.sub("", " ".join(URL.sub(" ", str(texte or "")).split()))
    brut = re.sub(r"\b\w+-(?:moi|toi|nous|vous|lui|leur|le|la|les|y|en)\b", " ", brut, flags=re.I)          # « donne-moi », « dis-le » : des formules, pas le sujet
    brut = re.sub(r"\b(?:l|d|j|m|t|s|n|c|qu)['’]", " ", brut, flags=re.I)                                    # « l'histoire » -> « histoire »
    return [m for m in re.findall(r"[\w'’-]+", brut.lower()) if m not in MOTS_VIDES and m not in SUJET_VIDE and len(m) > 1]


def requete(texte, aujourdhui=None, reformuler=None, datee=True):
    """La requête de recherche. Si `reformuler` est donné (un appel court au modèle : il corrige les fautes et ne garde que le sujet), on l'essaie d'abord ; sinon, ou s'il échoue, la demande est nettoyée
    (formules de politesse, mots vides, ponctuation). Le mois et l'année attirent des résultats récents (une date jj/mm/aaaa, elle, fait chuter la pertinence d'un moteur de recherche)."""
    aujourdhui = aujourdhui or date.today()
    sujet = ""
    if not datee and len(_mots(texte)) <= 8:          # une demande courte se nettoie sans appeler le modèle (plus rapide, aucun autre modèle à charger)
        reformuler = None
    if reformuler is not None:
        try:
            propose = str(reformuler(texte) or "").strip().splitlines()
            sujet = " ".join(re.sub(r"[^\w' -]", " ", propose[0] if propose else "").split())[:120]
        except (OSError, ValueError, IndexError):
            sujet = ""
    if not sujet or len(sujet.split()) > 14:
        sujet = " ".join(_mots(texte)[:12])
    if not datee:
        return (sujet or " ".join(str(texte or "").split()))[:200]
    return "{} {} {}".format(sujet or "actualités", MOIS[aujourdhui.month - 1], aujourdhui.year)[:200]


def consigne(aujourdhui=None):
    aujourdhui = aujourdhui or date.today()
    return _t("Nous sommes le {}. Les résultats de recherche et les pages lues sont au-dessus. Fais maintenant une synthèse courte de l'actualité qu'ils contiennent : 5 à 8 points, une phrase par point, "
              "en citant le média ou le site de chaque information. N'invente rien : si les sources ne couvrent pas la question, dis-le simplement. Réponds dans la langue de la demande.").format(aujourdhui.strftime("%d/%m/%Y"))


def consigne_recherche(aujourdhui=None):
    aujourdhui = aujourdhui or date.today()
    return _t("Nous sommes le {}. Les résultats de recherche et le début des pages lues sont au-dessus. Réponds à la demande d'après ces sources : cite-les par leur numéro [1], [2]… N'invente rien : "
              "si elles ne contiennent pas la réponse, dis-le et propose une autre recherche. Les adresses des sources sont déjà affichées à l'utilisateur ; ne les recopie que s'il demande les liens. Réponds dans la langue de la demande.").format(aujourdhui.strftime("%d/%m/%Y"))


def consigne_sans_correspondance(noms):
    return _t("Aucune des sources trouvées ne parle de « {} ». Dis-le simplement à l'utilisateur, sans rien inventer sur ce sujet (aucune biographie, aucune affaire, aucune œuvre), "
              "et propose de vérifier l'orthographe du nom ou de préciser (métier, pays, titre d'un livre).").format(" », « ".join(noms))


def consigne_lecture():
    return _t("Le contenu de la page demandée est au-dessus. Réponds à la demande d'après cette page, sans rien inventer ; si la page n'a pas pu être lue ou ne contient pas la réponse, dis-le simplement.")


def sources(resultat, maximum=6):
    """[(titre, adresse)] d'un résultat de web_chercher, pour les montrer à l'utilisateur."""
    return re.findall(r"^\d+\. (.+)\n\s+(https?://\S+)", str(resultat), re.M)[:maximum]


def _ajouter(conv, nom, args, resultat):
    conv["messages"].append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": nom, "arguments": args}}]})
    conv["messages"].append({"role": "tool", "tool_name": nom, "content": str(resultat)})


def preparer(conv, texte, ctx, emit, chercher=None, reformuler=None, mode="actualites", lire=None):
    """Fait la recherche (ou la lecture de la page collée) à la place du modèle ; ajoute l'appel et son résultat à la conversation (comme s'il les avait demandés). Renvoie la consigne
    de réponse, ou None si rien n'a été trouvé (la boucle habituelle prend alors le relais). Lève ErreurOutil si le web est coupé."""
    from . import web
    if mode == "lecture":
        lire = lire or web.outil_web_lire
        adresse = URL.search(texte).group(0).rstrip(".,;:!?")
        args = {"url": adresse}
        emit({"type": "info", "texte": _t("📄 Je lis la page, puis je réponds.")})
        emit({"type": "outil", "nom": "web_lire", "args": args})
        page = lire(adresse, 0, ctx)
        emit({"type": "resultat", "nom": "web_lire", "texte": _t("(résultat transmis à l'assistant, non affiché)")})
        _ajouter(conv, "web_lire", args, page)
        return consigne_lecture()
    chercher = chercher or web.outil_web_chercher
    news = mode == "actualites"
    q = requete(texte, reformuler=reformuler, datee=news)
    args = {"requete": q, "nombre": 6, "lire": 3}
    noms = [] if news else noms_propres(texte)
    for nom in noms:
        q = re.sub(re.escape(nom), '"' + nom + '"', q, count=1, flags=re.I)          # un nom entre guillemets : le moteur cherche la personne, pas chaque mot
    args["requete"] = q
    emit({"type": "info", "texte": _t("🔎 Actualités : je cherche et je lis quelques sources, puis je les résume.") if news else _t("🔎 Je cherche « {} » et je lis les premières pages.").format(q)})
    emit({"type": "outil", "nom": "web_chercher", "args": args})
    resultat = chercher(q, 6, ctx, 3)
    absents = lambda r: [n for n in noms if n.lower() not in str(r).lower()]          # noqa: E731
    if noms and "CONTENU WEB NON FIABLE" in str(resultat)[:80] and absents(resultat):          # les résultats ne parlent pas de la personne : une seconde chance avec le nom seul
        q2 = " ".join('"' + n + '"' for n in noms)
        if q2 != q:
            autre = chercher(q2, 6, ctx, 3)
            if "CONTENU WEB NON FIABLE" in str(autre)[:80] and not absents(autre):
                q, resultat, args["requete"] = q2, autre, q2
    if not resultat or "CONTENU WEB NON FIABLE" not in str(resultat)[:80]:          # pas de résultat (ou une réponse sans l'avertissement des pages web)
        emit({"type": "resultat", "nom": "web_chercher", "texte": str(resultat)[:300]})
        _ajouter(conv, "web_chercher", args, resultat)
        return None
    emit({"type": "resultat", "nom": "web_chercher", "texte": _t("(résultat transmis à l'assistant, non affiché)")})
    liens = sources(resultat)
    manquants = absents(resultat) if noms else []
    if liens and not news:
        emit({"type": "info", "texte": _t("🔗 Sources trouvées :") + "\n" + "\n".join("{}. {} — {}".format(i + 1, t, u) for i, (t, u) in enumerate(liens))})
    if manquants:          # aucune page ne mentionne le nom demandé : le modèle ne reçoit pas ces pages hors sujet (il en tirerait une histoire inventée)
        emit({"type": "info", "texte": _t("⚠ Aucun résultat ne mentionne « {} » : vérifie l'orthographe du nom ou précise le sujet.").format(" », « ".join(manquants))})
        _ajouter(conv, "web_chercher", args, _t("Aucun résultat ne mentionne « {} ».").format(" », « ".join(manquants)))
        return consigne_sans_correspondance(manquants)
    _ajouter(conv, "web_chercher", args, resultat)
    return consigne() if news else consigne_recherche()
