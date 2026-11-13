"""Un modèle qui raconte au lieu de faire.

Les petits modèles écrivent volontiers « j'ai créé le fichier », « j'ai lancé la commande », « j'ai cherché sur internet »… sans avoir appelé le moindre outil. L'utilisateur
croit le travail fait, le modèle s'appuie ensuite sur sa propre fausse réponse et recommence. Ici, on repère ces affirmations quand aucun outil correspondant n'a été
appelé depuis la dernière demande de l'utilisateur : Lutin le fait remarquer au modèle (une fois), qui peut alors agir pour de vrai.

Le contrôle est volontairement prudent : verbe au passé à la première personne, outil réellement disponible dans ce mode, code cité (``` … ```) ignoré."""
import re

_PASSE = r"\b(?:j'ai|ai|viens de|je l'ai)\s+"
_PASSIF = r"\s+(?:a|ont)\s+[ée]t[ée]\s+"
_ECRIT = r"(?:cr[ée]{1,2}|[ée]crit|g[ée]n[ée]r[ée]|enregistr[ée]|modifi[ée]|ajout[ée]|sauvegard[ée])\b"
_ECRIT_PASSIF = r"(?:cr[ée]{1,2}|[ée]crit|g[ée]n[ée]r[ée]|enregistr[ée]|modifi[ée]|sauvegard[ée])s?\b"
_NOMS_DE_FICHIER = r"(?:fichiers?|dossiers?|scripts?|documents?|pdf|word|rapports?|compose|configs?|configuration|pages?|\.[a-z]{2,5})\b"
_OBJET = r"[^.\n]{0,80}\b" + _NOMS_DE_FICHIER          # « j'ai créé le fichier … » : un objet de type fichier dans la phrase, sinon « j'ai ajouté une précision » déclencherait
_OBJET_AVANT = r"\b" + _NOMS_DE_FICHIER + r"[^.\n]{0,80}"

# (nom, motif, outils dont l'un au moins doit avoir été appelé, rappel donné au modèle)
CATEGORIES = (
    ("ecriture",
     re.compile(_PASSE + _ECRIT + _OBJET + "|" + _OBJET_AVANT + _PASSIF + _ECRIT_PASSIF, re.I),
     {"ecrire", "modifier", "modifier_plusieurs", "creer_document", "executer", "comfy_generer", "installer_module"},
     "Tu viens de dire que tu as créé ou modifié un fichier, mais tu n'as appelé AUCUN outil d'écriture : rien n'existe sur le disque. Fais-le maintenant en appelant l'outil « ecrire » (chemin et contenu complet), puis seulement dis ce que tu as fait."),
    ("commande",
     re.compile(_PASSE + r"(?:lanc[ée]|ex[ée]cut[ée]|install[ée]|d[ée]marr[ée]|red[ée]marr[ée]|supprim[ée]|d[ée]ploy[ée]|arr[êe]t[ée])\b|" + _PASSIF + r"(?:lanc[ée]|ex[ée]cut[ée]|install[ée]|d[ée]marr[ée]|red[ée]marr[ée]|supprim[ée]|d[ée]ploy[ée]|arr[êe]t[ée])e?s?\b", re.I),
     {"executer", "installer_module"},
     "Tu viens de dire que tu as lancé, installé ou supprimé quelque chose, mais tu n'as appelé AUCUN outil « executer » : rien n'a été fait. Appelle l'outil maintenant avec la commande exacte, lis son résultat, puis rends compte de ce qui s'est vraiment passé."),
    ("web",
     re.compile(_PASSE + r"(?:cherch[ée]|recherch[ée]|consult[ée]|v[ée]rifi[ée])\b[^.\n]{0,50}\b(?:web|internet|en ligne|sur le net|sur le site)\b", re.I),
     {"web_chercher", "web_lire"},
     "Tu viens de dire que tu as cherché sur internet, mais tu n'as appelé ni « web_chercher » ni « web_lire » : tu n'as rien lu. Appelle l'outil maintenant, lis ce qu'il rend, puis réponds d'après ces sources."),
    ("image",
     re.compile(_PASSE + r"g[ée]n[ée]r[ée]\b[^.\n]{0,30}\b(?:image|photo|vid[ée]o|illustration)", re.I),
     {"comfy_generer"},
     "Tu viens de dire que tu as généré une image, mais tu n'as pas appelé « comfy_generer » : aucune image n'existe. Appelle l'outil maintenant."),
    ("memoire",
     re.compile(_PASSE + r"m[ée]moris[ée]\b|\bnot[ée]\s+dans\s+(?:ma|la|mes)\s+m[ée]moire", re.I),
     {"memoriser"},
     "Tu viens de dire que tu as mémorisé quelque chose, mais tu n'as pas appelé « memoriser » : rien n'est gardé. Appelle l'outil maintenant avec une note courte."),
)
DEMANDE_D_ECRITURE = re.compile(r"\b(?:cr[ée]{1,2}r?|[ée]cris|[ée]crire|g[ée]n[èe]re|g[ée]n[ée]rer|pr[ée]pare|r[ée]dige|fais(?:-moi)?|monte|produis)\b[^.\n]{0,80}\b(?:docker-compose|compose|dockerfile|fichier|script|config|configuration|yaml|yml|readme|document|\.[a-z]{2,5})\b", re.I)
DEMANDE_DE_REALISATION = re.compile(r"\b(?:fais(?:-moi)?|faire|cr[ée]{1,2}r?|code|coder|programme|programmer|d[ée]veloppe|d[ée]velopper|r[ée]alise|r[ée]aliser|construis|construire|[ée]cris|[ée]crire|g[ée]n[èe]re|g[ée]n[ée]rer)\b[^.\n]{0,60}\b(?:jeu|d[ée]mineur|morpion|snake|tetris|page|site|application|appli|programme|outil|calculatrice|interface|formulaire|html|css|javascript|python|bash|batch|powershell|api|serveur|bot|extension)\b", re.I)
REFUS = re.compile(r"(?:\bne\s+(?:peux|puis|sais|suis|dispose|poss[èe]de)\s+pas\b|\bimpossible\s+de\b|\bpas\s+(?:la\s+)?possibilit[ée]\b|\bpas\s+(?:en\s+)?mesure\b|\bincapable\b|\bn'ai\s+pas\s+(?:acc[èe]s|la\s+capacit[ée])\b|\bcan(?:'|no)t\s+(?:directly\s+)?(?:create|write|save)\b|\bunable\s+to\s+(?:create|write|save)\b)[^.\n]{0,90}(?:cr[ée]er|[ée]crire|g[ée]n[ée]rer|enregistrer|sauvegarder|fichiers?|disque|syst[èe]me|directement|files?|disk)", re.I)
RAPPEL_REFUS = "Tu viens de dire que tu ne peux pas créer de fichier : c'est FAUX, tu as l'outil « ecrire » (et « executer »). Ne t'excuse pas, ne décris pas le contenu et ne demande pas la permission : appelle maintenant l'outil « ecrire » avec le chemin du fichier et son contenu complet, puis dis en une phrase ce qui a été créé."
OUTILS_D_ECRITURE = {"ecrire", "modifier", "modifier_plusieurs", "creer_document", "executer"}
RAPPEL_OUBLI = "L'utilisateur t'a demandé de CRÉER un fichier et tu ne l'as pas fait : rien n'existe sur le disque. Ne décris pas le contenu et ne demande pas la permission : appelle maintenant l'outil « ecrire » avec le chemin et le contenu complet (mets des valeurs d'exemple claires si une information manque), puis dis où se trouve le fichier."
BLOCS_DE_CODE = re.compile(r"```.*?(?:```|$)", re.S)


# « Je vais vérifier… » puis rien : le modèle annonce une action, ne l'accomplit pas et rend la main sans répondre à la question.
ANNONCE = re.compile(r"\b(?:je\s+vais|je\s+m'en\s+occupe|laisse-moi|laissez-moi|un\s+instant|je\s+regarde|je\s+v[ée]rifie\s+(?:cela|ça|tout de suite))\b[^.!?\n]{0,80}", re.I)
RAPPEL_ANNONCE = ("Tu viens d'annoncer que tu allais agir (vérifier, chercher, regarder…) mais tu n'as appelé AUCUN outil et tu n'as pas répondu à la question. "
                  "Ne dis plus « je vais » : appelle MAINTENANT l'outil adapté (par exemple celui qui liste ou lit ce que l'utilisateur demande), puis réponds clairement et directement à sa question (oui, non, ou ce que tu as trouvé).")


def annonce_sans_agir(contenu, appels, autorises):
    """Le rappel à donner si la réponse n'est qu'une annonce (« Je vais vérifier si le profil est disponible. ») sans appel d'outil alors que des outils existent. Une réponse longue ou qui contient autre chose qu'une annonce n'est pas touchée."""
    if appels or not autorises:
        return ""
    texte = BLOCS_DE_CODE.sub(" ", contenu or "").strip()
    if not 8 <= len(texte) <= 260 or not ANNONCE.search(texte):
        return ""
    reste = ANNONCE.sub(" ", texte)
    return RAPPEL_ANNONCE if len(re.sub(r"[\W_]+", " ", reste).split()) <= 14 else ""


def outils_appeles(messages):
    """Les noms des outils appelés depuis la dernière demande de l'utilisateur."""
    vus = set()
    for x in reversed(messages):
        if x.get("role") == "user":
            break
        if x.get("role") == "tool":
            vus.add(x.get("tool_name"))
    return vus


def oubli_d_ecrire(demande, messages, autorises):
    """Le rappel à donner si l'utilisateur a demandé de créer un fichier et que le modèle termine sans avoir appelé un outil d'écriture (il a cherché, puis s'est arrêté, ou a seulement montré le contenu)."""
    d = str(demande or "")[:400]
    if not (OUTILS_D_ECRITURE & autorises) or not (DEMANDE_D_ECRITURE.search(d) or DEMANDE_DE_REALISATION.search(d)):
        return ""
    return "" if OUTILS_D_ECRITURE & outils_appeles(messages) else RAPPEL_OUBLI


def refus_a_tort(demande, contenu, messages, autorises):
    """Le rappel à donner si l'utilisateur a demandé de créer quelque chose (un fichier, une page, un petit programme) et que le modèle répond qu'il ne PEUT PAS créer de fichier alors que l'outil d'écriture existe.
    Certains modèles, surtout via llama.cpp, refusent ainsi au lieu d'appeler l'outil. Une fois seulement par demande (l'appelant s'en assure)."""
    if not ({"ecrire", "creer_document"} & autorises) or OUTILS_D_ECRITURE & outils_appeles(messages):
        return ""
    texte = BLOCS_DE_CODE.sub(" ", contenu or "")
    if not REFUS.search(texte):
        return ""
    d = str(demande or "")[:400]
    return RAPPEL_REFUS if (DEMANDE_D_ECRITURE.search(d) or DEMANDE_DE_REALISATION.search(d)) else ""


def affirme_sans_agir(contenu, messages, autorises):
    """Le rappel à donner au modèle s'il affirme avoir agi sans l'avoir fait ; « » sinon. `autorises` : les outils disponibles (inutile de réclamer un outil absent)."""
    texte = BLOCS_DE_CODE.sub(" ", contenu or "")
    if len(texte) < 12:
        return ""
    appeles = None
    for _, motif, outils, rappel in CATEGORIES:
        if not (outils & autorises) or not motif.search(texte):
            continue
        if appeles is None:
            appeles = outils_appeles(messages)
        if not (outils & appeles):
            return rappel
    return ""
