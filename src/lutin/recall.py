"""Rappel : recherche par mots dans les documents et les anciennes conversations."""
from pathlib import Path
from .i18n import t as _t
import collections
import fnmatch
import hashlib
import json
import math
import os
import re
import unicodedata
from . import archive as _archive
from . import embeddings as _embeddings
from . import text_extraction
from . import modes as _modes
from . import core as _m


# --------------------------------------------------------------------------- rappel : recherche par mots dans les documents et les anciennes conversations
STOP_WORDS = set("les des une dans pour par sur avec sans est sont ete etre elle ils elles nous vous leur leurs cette ces cet que qui quoi dont mais donc car aux son sa ses mon ma mes ton ta tes the and for with that this from not are was has have".split())


RECALL = {"signature": None, "morceaux": [], "df": collections.Counter(), "moyenne": 1.0, "erreurs": []}
DOCUMENT_FOLDERS = ("docs", "documents")          # où poser ses PDF, documents Word, notes… : lus pour de vrai, avec page ou diapositive dans la citation
MAX_DOCUMENTS = 300
FORMATS_READ_BY_EXTRACTION = (".pdf", ".docx", ".odt", ".ods", ".odp", ".pptx", ".xlsx")
PARTS_CACHE = {}
INDEX_CACHE = {}                       # fichier -> (signature, morceaux, erreur, fréquences des mots) : seuls les fichiers modifiés sont relus
RELIRE = "relire"                      # clé d'une erreur de file_chunks : le fichier n'a été lu qu'en partie (illisible un instant), ne pas garder l'index en cache
MAX_TEXT_SIZE = 600_000


def words(texte):
    t = unicodedata.normalize("NFD", str(texte).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return [singular(m) for m in re.findall(r"[a-z0-9_]{3,}", t) if m not in STOP_WORDS]


def singular(mot):
    """« chats » -> « chat », « fonctions » -> « fonction », « tests » -> « test » : le pluriel (français et anglais) ne doit pas empêcher de retrouver un passage. Les mots en -ss, -us, -is restent tels quels (« access », « bonus », « mois »)."""
    if len(mot) > 4 and mot.endswith(("s", "x")) and not mot.endswith(("ss", "us", "is")):
        return mot[:-1]
    return mot


def recall_sources():
    """Les documents interrogeables : docs/, skills/, mémoires de l'assistant, puis les conversations enregistrées."""
    if (_m.RACINE / "CLAUDE.md").is_file():
        yield _m.RACINE / "CLAUDE.md"
    texte = ("*.md", "*.txt")
    sources = [(_m.RACINE / d, texte + tuple("*" + e for e in text_extraction.FORMATS)) for d in DOCUMENT_FOLDERS] + [(_m.RACINE / "skills", ("*.md",)), (_m.RACINE / ".claude", ("*.md",)), (_m.MEMOIRE, ("*.md",))]
    vus, documents = set(), 0
    for dossier, motifs in sources:
        if dossier.is_dir():
            for racine, sous, noms in os.walk(str(dossier)):
                sous[:] = sorted(s for s in sous if s not in _m.DOSSIERS_IGNORES)
                for nom in sorted(noms):
                    if any(fnmatch.fnmatch(nom.lower(), p) for p in motifs):
                        f = Path(racine) / nom
                        if f in vus:
                            continue
                        vus.add(f)
                        if f.suffix.lower() in text_extraction.FORMATS:
                            documents += 1
                            if documents > MAX_DOCUMENTS:
                                continue
                        yield f
    from . import store
    for ident in sorted(store.ids()):
        yield ConversationRef(ident)


class ConversationRef:
    """A conversation as a source of the recall index (lutin.store, ADR 0017): what the index asks of a file (a key, a signature that changes when
    the conversation does, its content), without a file."""

    def __init__(self, ident):
        self.stem = ident
        self.suffix = ".conversation"

    def __str__(self):
        return "conversation:" + self.stem

    def read(self):
        from . import store
        return store.read(self.stem)

    def signature(self):
        """Changes when the conversation is written: its date « maj » and its number of messages. OSError when it is gone, as for a file."""
        from . import store
        entry = store.summary(self.stem)
        if entry is None:
            raise FileNotFoundError(self.stem)
        return (entry["maj"], entry["messages"])


def split_text(texte, source, titre_defaut=""):
    """Morceaux d'environ 800 caractères, coupés aux titres Markdown et aux paragraphes."""
    morceaux, courant, titre = [], [], titre_defaut

    def clore():
        if courant:
            corps = "\n".join(courant).strip()
            if len(corps) > 40:
                morceaux.append({"source": source, "titre": titre, "texte": corps})
            courant.clear()
    taille = 0
    for ligne in texte.splitlines():
        if ligne.startswith("#"):
            clore()
            taille = 0
            titre = ligne.lstrip("# ").strip()[:80]
        courant.append(ligne)
        taille += len(ligne) + 1
        if taille > 800 and not ligne.strip():
            clore()
            taille = 0
    clore()
    return morceaux


def document_parts(f):
    """[(titre de la partie, texte)] d'un document, lu une seule fois : en mémoire, puis dans donnees/cache-documents/ (clé : chemin, date, taille). ErreurExtraction si illisible."""
    st = Path(f).stat()
    cle = (str(f), st.st_mtime_ns, st.st_size)
    if cle in PARTS_CACHE:
        return PARTS_CACHE[cle]
    fichier = _m.DONNEES / "cache-documents" / (hashlib.sha1("|".join(map(str, cle)).encode("utf-8")).hexdigest() + ".json")
    try:
        parties = [tuple(p) for p in json.loads(fichier.read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        parties = text_extraction.parts(f)
        try:
            fichier.parent.mkdir(parents=True, exist_ok=True)
            _m.ecrire_atomique(fichier, json.dumps(parties, ensure_ascii=False))
        except OSError:
            pass
    PARTS_CACHE.clear() if len(PARTS_CACHE) > 400 else None
    PARTS_CACHE[cle] = parties
    return parties


def recall_label(f):
    """Nom affiché d'un document : chemin dans le dossier de travail, ou « memoire/… » pour les mémoires (qui vivent dans le dossier de données, hors du projet)."""
    try:
        return _m.rel(f)
    except ValueError:
        try:
            return "memoire/" + Path(f).resolve().relative_to(_m.MEMOIRE.resolve()).as_posix()
        except ValueError:
            return Path(f).name


def file_chunks(f):
    """Les morceaux d'un fichier, avec leurs comptes de mots. Renvoie (morceaux, erreur ou None)."""
    morceaux, erreur = [], None
    try:
        if f.suffix.lower() in text_extraction.FORMATS:
            try:
                for titre, texte in document_parts(f):
                    morceaux += split_text(texte, recall_label(f), titre)
            except text_extraction.ExtractionError as e:
                erreur = {"nom": recall_label(f), "message": str(e)}
        elif isinstance(f, ConversationRef):
            c = f.read()
            if c:
                nom = "conversation « {} »".format(c.get("titre", "")[:60])
                texte = "\n\n".join("[{}] {}".format("moi" if m.get("role") == "user" else "assistant", m.get("content", "")) for m in c.get("messages", []) if m.get("role") in ("user", "assistant") and m.get("content"))
                if c.get("resume"):
                    texte = "# Résumé\n" + c["resume"] + "\n\n" + texte
                archive = _archive.text_of(c.get("id"), strict=True)            # ce que le résumé automatique a retiré de la conversation
                if archive:
                    texte = texte + "\n\n# Début de la conversation (avant le résumé)\n" + archive
                for m_ in split_text(texte, nom):
                    m_["conv"] = c.get("id")
                    morceaux.append(m_)
        elif f.stat().st_size <= MAX_TEXT_SIZE:
            morceaux += split_text(f.read_text(encoding="utf-8", errors="replace"), recall_label(f))
    except OSError as e:
        # lu en partie seulement (un fichier ou une archive tenus un instant) : l'erreur le dit, et les index ne le gardent pas en cache sous la
        # signature du fichier (avant, l'index incomplet restait jusqu'à la prochaine modification du fichier)
        erreur = {"nom": str(f) if isinstance(f, ConversationRef) else recall_label(f), "message": str(e), RELIRE: True}
    for m in morceaux:
        m["tf"] = collections.Counter(words(m["titre"] + " " + m["texte"]))
        m["longueur"] = sum(m["tf"].values()) or 1
    return morceaux, erreur


def file_signature(f):
    """Ce qui dit qu'un fichier a changé : sa date, sa taille, et pour une conversation, celles de son archive."""
    if isinstance(f, ConversationRef):
        sig = f.signature()
    else:
        st = f.stat()
        sig = (st.st_mtime_ns, st.st_size)
    if isinstance(f, ConversationRef):
        try:
            sa = _archive.path_of(f.stem).stat()
            sig += (sa.st_mtime_ns, sa.st_size)
        except (OSError, ValueError):
            pass
    return sig


def index_recall():
    """Met l'index à jour : seuls les fichiers qui ont changé sont relus et redécoupés (une longue conversation qui grandit ne force pas à tout reprendre)."""
    fichiers = list(recall_sources())
    signature, presents = [], {}
    for f in fichiers:
        try:
            sig = file_signature(f)
        except OSError:
            continue
        signature.append((str(f), sig))
        presents[str(f)] = (f, sig)
    signature = tuple(signature)
    if RECALL["signature"] == signature:
        return
    for cle in [k for k in INDEX_CACHE if k not in presents]:
        del INDEX_CACHE[cle]
    for cle, (f, sig) in presents.items():
        if cle not in INDEX_CACHE or INDEX_CACHE[cle][0] != sig:
            morceaux_f, erreur_f = file_chunks(f)
            df_f = collections.Counter()
            for m in morceaux_f:
                df_f.update(m["tf"].keys())
            if (erreur_f or {}).get(RELIRE):
                sig, signature = None, None                        # relu au prochain appel
            INDEX_CACHE[cle] = (sig, morceaux_f, erreur_f, df_f)
    morceaux, erreurs, df = [], [], collections.Counter()
    for cle in presents:
        _, morceaux_f, erreur_f, df_f = INDEX_CACHE[cle]
        morceaux += morceaux_f
        df.update(df_f)
        if erreur_f:
            erreurs.append(erreur_f)
    RECALL.update({"erreurs": erreurs, "signature": signature, "morceaux": morceaux, "df": df, "moyenne": (sum(m["longueur"] for m in morceaux) / len(morceaux)) if morceaux else 1.0})


def recall_passages(requete, nombre=5, exclure_conv="", min_termes=1, seulement_conv=""):
    """Les passages les plus pertinents (méthode BM25) : liste de {score, m, trouves}. exclure_conv : conversation à ignorer (celle en cours) ;
    min_termes : nombre minimal de mots de la requête présents dans le passage (pour ne garder que des passages vraiment liés). seulement_conv : ne chercher que dans cette conversation (début archivé compris)."""
    termes = set(words(requete))
    if not termes:
        return []
    index_recall()
    morceaux = [m for m in RECALL["morceaux"] if not (exclure_conv and m.get("conv") == exclure_conv) and not (seulement_conv and m.get("conv") != seulement_conv)]
    return rank_chunks(morceaux, RECALL["df"], RECALL["moyenne"], len(RECALL["morceaux"]), termes, nombre, min_termes)


def rank_chunks(morceaux, df, moyenne, n, termes, nombre, min_termes):
    """Classe des morceaux par pertinence (BM25) : les `nombre` meilleurs, qui contiennent au moins `min_termes` des mots cherchés."""
    scores = []
    for m in morceaux:
        score, trouves = 0.0, 0
        for t in termes:
            tf = m["tf"].get(t, 0)
            if tf:
                trouves += 1
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * m["longueur"] / moyenne))
        if score > 0 and trouves >= min(min_termes, len(termes)):
            scores.append({"score": score, "m": m, "trouves": trouves, "termes": termes})
    scores.sort(key=lambda x: -x["score"])
    return scores[:nombre]


RE_ROLE = re.compile(r"\[(?:moi|assistant)\] ")
THREAD = {}                       # conversation -> (signature, morceaux, df, moyenne) : l'index d'UNE conversation, refait seulement quand elle change


def thread_chunks(ident):
    """Les morceaux de la conversation (messages gardés + début archivé par le résumé), sans parcourir les dossiers de documents : rapide à chaque réponse."""
    _m.conv_chemin(ident)                                         # checks the identifier
    f = ConversationRef(ident)
    try:
        sig = file_signature(f)
    except OSError:
        return [], collections.Counter(), 1.0
    en_cache = THREAD.get(ident)
    if en_cache and en_cache[0] == sig:
        return en_cache[1], en_cache[2], en_cache[3]
    morceaux, erreur = file_chunks(f)
    df = collections.Counter()
    for m in morceaux:
        df.update(m["tf"].keys())
    moyenne = (sum(m["longueur"] for m in morceaux) / len(morceaux)) if morceaux else 1.0
    if (erreur or {}).get(RELIRE):
        return morceaux, df, moyenne                                   # lu en partie : pas en cache, relu à la prochaine réponse
    if len(THREAD) > 20:
        THREAD.clear()
    THREAD[ident] = (sig, morceaux, df, moyenne)
    return morceaux, df, moyenne


def thread_passages(ident, question, nombre=3, min_termes=1):
    """Les passages de CETTE conversation (début archivé compris) qui répondent à la question : par les mots (BM25) et, si la recherche par le sens est activée, par le sens ; les deux classements sont
    fusionnés (rangs réciproques) : un passage bien classé par l'un OU par l'autre remonte. Sans la recherche par le sens (ou si elle échoue), les mots seuls."""
    try:
        morceaux, df, moyenne = thread_chunks(ident)
    except ValueError:                                               # conversation inconnue
        return []
    if not morceaux:
        return []
    termes = set(words(question[:900]))
    par_mots = rank_chunks(morceaux, df, moyenne, len(morceaux), termes, 8, min_termes) if termes else []
    sims = _embeddings.similarities(ident, morceaux, question[:900])
    if not sims:
        return par_mots[:nombre]
    par_sens = sorted(((s, i) for i, s in sims.items() if s >= _embeddings.THRESHOLD), reverse=True)[:8]
    rangs = {}
    for r, p in enumerate(par_mots):
        rangs.setdefault(id(p["m"]), [p["m"], p, 0.0])[2] += 1.0 / (60 + r)
    for r, (s, i) in enumerate(par_sens):
        m = morceaux[i]
        entree = rangs.setdefault(id(m), [m, {"score": s, "m": m, "trouves": 0, "termes": termes}, 0.0])
        entree[2] += 1.0 / (60 + r)
    classes = sorted(rangs.values(), key=lambda e: -e[2])
    return [e[1] for e in classes[:nombre]]


RESULTS = {}                      # conversation -> (signature, chunks, df, mean): the index of its tool results, rebuilt only when it changes
RESULT_CHUNK = 800                # characters of a chunk of a tool result


def split_result(text, source):
    """Chunks of about RESULT_CHUNK characters of a tool result, cut at line ends: an output seldom has paragraphs (split_text would keep it whole)."""
    chunks, current, size = [], [], 0
    for line in text.splitlines():
        while len(line) > RESULT_CHUNK:                                # one very long line (minified file, JSON): cut by characters
            chunks.append(line[:RESULT_CHUNK])
            line = line[RESULT_CHUNK:]
        if size + len(line) > RESULT_CHUNK and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return [{"source": source, "titre": "", "texte": c} for c in chunks if len(c.strip()) > 20]


def result_chunks(ident):
    """The tool results of this conversation, those still in it and those kept in full in its archive because they were cut to fit the window
    (ADR 0019, decision 5), as chunks with their word counts. Searched by words only, by « rappeler » with ici=true: the meaning of an output is
    its exact words (a name, an error, a number), and the vectors of the thread stay those of its messages."""
    _m.conv_chemin(ident)                                         # checks the identifier
    f = ConversationRef(ident)
    try:
        sig = file_signature(f)
    except OSError:
        return [], collections.Counter(), 1.0
    cached = RESULTS.get(ident)
    if cached and cached[0] == sig:
        return cached[1], cached[2], cached[3]
    c = f.read() or {}
    try:
        kept, complete = _archive.results_of(ident, strict=True), True
    except OSError:
        kept, complete = [], False                                  # held an instant: searched without it, and not cached
    parts = kept + [(m.get("tool_name") or "", str(m.get("content") or "")) for m in c.get("messages", []) if m.get("role") == "tool" and m.get("content")]
    chunks = []
    for name, text in parts:
        chunks += split_result(text, "résultat de « {} » (cette conversation)".format(name))
    df = collections.Counter()
    for m in chunks:
        m["tf"] = collections.Counter(words(m["texte"]))
        m["longueur"] = sum(m["tf"].values()) or 1
        df.update(m["tf"].keys())
    mean = (sum(m["longueur"] for m in chunks) / len(chunks)) if chunks else 1.0
    if not complete:
        return chunks, df, mean
    if len(RESULTS) > 20:
        RESULTS.clear()
    RESULTS[ident] = (sig, chunks, df, mean)
    return chunks, df, mean


def result_passages(ident, question, nombre=3):
    """The chunks of the tool results of this conversation that contain the words of the question (BM25)."""
    try:
        chunks, df, mean = result_chunks(ident)
    except ValueError:
        return []
    terms = set(words(question[:900]))
    return rank_chunks(chunks, df, mean, len(chunks), terms, nombre, 1) if chunks and terms else []


# Below this BM25 score a passage is not put back by itself (ADR 0019, decision 6: a close but wrong passage harms the answer). Measured on the
# corpus of tools/mesurer_rappel.py: wrong passages reach 2.32 (one word in common), right ones go from 2.12 to 10.4; 2.5 drops every wrong one
# and 3 right ones out of 23. A passage found by meaning alone (« trouves » 0) has already passed the threshold of the embeddings.
# The thread recall only runs once the history overflows its room (`rappel_ici`): its index then has several chunks (eight or more on 4,096
# tokens), close to that corpus. On a conversation of three chunks every word is rare and a right passage can score below the threshold.
THREAD_MIN_SCORE = 2.5


def thread_recall(conv, fiche_etape="", budget=1800, vus=None):
    """Ce qui a été dit plus tôt dans CETTE conversation et qui touche à la dernière demande, retrouvé tout seul (sans que le modèle ait à le demander) : une fiche ou un résumé perd des détails,
    mais le texte complet reste sur le disque. Renvoie (texte pour le prompt, nombre de passages). Un « oui » ou un « continue » est complété par la dernière réponse et l'étape en cours.
    budget : caractères de passages au plus (les rappels du fil et des documents se partagent une part de la fenêtre : prompt_layout).
    vus : les messages que la requête ajustée à la fenêtre enverra vraiment (agent.ce_que_voit_le_modele) ; sans eux, les six derniers et les épinglés.
    Un passage déjà sous les yeux du modèle n'est pas remis ; ceux des messages que l'ajustement vient de retirer passent avant ceux du début archivé (ADR 0018)."""
    ident = conv.get("id")
    msgs = conv.get("messages", [])
    demandes = [m["content"] for m in msgs if m.get("role") == "user" and m.get("content") and not str(m["content"]).startswith("[")]
    if not ident or not demandes:
        return "", 0
    question = demandes[-1]
    precise = len(words(question)) >= 4
    if len(demandes) >= 2:
        question = " ".join([question, demandes[-2][:600]])          # the previous request of the person: a follow-up (« et pour l'autre fichier ? ») keeps its subject (ADR 0019, decision 6)
    if not precise:
        precedente = next((m["content"] for m in reversed(msgs[:-1]) if m.get("role") == "assistant" and m.get("content")), "")
        question = " ".join([question, precedente[:300], fiche_etape])
    termes = set(words(question[:1200]))
    if not termes:
        return "", 0
    passages = [p for p in thread_passages(ident, question, 8, 2 if precise else 1) if p["trouves"] == 0 or p["score"] >= THREAD_MIN_SCORE]
    if not passages:
        return "", 0
    if vus is None:
        vus = msgs[-6:] + [m for m in msgs[:-6] if m.get("epingle")]                       # sans mieux : les derniers échanges sont dans la fenêtre
    sous_les_yeux = " ".join(" ".join(str(m.get("content") or "").split()) for m in vus)
    retires = " ".join(" ".join(str(m.get("content") or "").split()) for m in msgs)          # encore dans la conversation : ce qui n'est pas vu, l'ajustement l'a retiré

    def debut(p):
        return " ".join(RE_ROLE.sub("", p["m"]["texte"]).split())[:60]
    gardes = [p for p in passages if debut(p) not in sous_les_yeux]
    gardes.sort(key=lambda p: debut(p) not in retires)                 # stable : le classement reste dans chaque groupe
    gardes = gardes[:3]
    if not gardes:
        return "", 0
    texte = ("[Extraits de la conversation] " + _t("Passages retrouvés plus tôt dans cette même conversation, en rapport avec la demande. Ils peuvent être hors sujet : ignore-les alors. "
             "Si un détail compte, appelle « rappeler » avec ici=true pour en voir davantage.") + "\n" + format_passages(gardes, 500)[:max(0, int(budget))])
    return texte, len(gardes)


def format_passages(passages, taille=600):
    lignes = []
    for i, p in enumerate(passages, 1):
        m, termes = p["m"], p["termes"]
        extrait = " ".join(m["texte"].split())
        pos = min((extrait.lower().find(t) for t in termes if extrait.lower().find(t) >= 0), default=0)
        debut = max(0, pos - 150)
        lignes.append("{}. {}{}\n   {}{}{}".format(i, m["source"], (" — " + m["titre"]) if m["titre"] else "", "…" if debut else "", extrait[debut:debut + taille], "…" if debut + taille < len(extrait) else ""))
    return "\n\n".join(lignes)


def documents_state():
    """Les documents lisibles posés dans docs/ ou documents/ (nom, nombre de parties), ceux qui n'ont pas pu être lus, et où les poser."""
    index_recall()
    fichiers, lus = [], collections.Counter(m["source"] for m in RECALL["morceaux"])
    for f in recall_sources():
        if f.suffix.lower() in text_extraction.FORMATS:
            nom = recall_label(f)
            fichiers.append({"nom": nom, "passages": lus.get(nom, 0)})
    return {"dossiers": ["{}/".format(d) for d in DOCUMENT_FOLDERS], "formats": list(text_extraction.FORMATS), "fichiers": fichiers, "erreurs": RECALL["erreurs"], "max": MAX_DOCUMENTS}


def search_documents(requete, nombre=8):
    """La recherche de la page : passages {source, titre, extrait, conversation} les plus pertinents (documents, notes, skills et anciennes conversations)."""
    sortie = []
    for p in recall_passages(requete, max(1, min(20, int(nombre)))):
        m, termes = p["m"], p["termes"]
        extrait = " ".join(m["texte"].split())
        pos = min((extrait.lower().find(t) for t in termes if extrait.lower().find(t) >= 0), default=0)
        debut = max(0, pos - 120)
        sortie.append({"source": m["source"], "titre": m["titre"], "extrait": ("…" if debut else "") + extrait[debut:debut + 420] + ("…" if debut + 420 < len(extrait) else ""), "conversation": bool(m.get("conv"))})
    return sortie


def recall_tool(requete, nombre=5, conv_id="", ici=False):
    """Les passages les plus pertinents dans docs/, skills/, les mémoires et les anciennes conversations."""
    if not words(requete):
        raise _m.ErreurOutil(_t("Requête vide ou trop vague : donne quelques mots-clés."))
    try:
        nombre = max(1, min(10, int(nombre or 5)))
    except (TypeError, ValueError):
        nombre = 5
    if ici and conv_id:
        # the messages of the thread and the tool results (a result cut to fit the window is kept in full: its header sends here), in turn
        fil, sorties = thread_passages(conv_id, requete, nombre), result_passages(conv_id, requete, nombre)
        passages = [p for paire in zip(fil, sorties) for p in paire] + fil[len(sorties):] + sorties[len(fil):]
        passages = passages[:nombre]
    else:
        passages = recall_passages(requete, nombre)
    if not passages:
        return _t("Aucun passage pertinent dans cette conversation.") if ici else _t("Aucun passage pertinent dans les documents ni dans les conversations enregistrées.")
    return format_passages(passages) + _t("\n\n(lis le document complet avec « lire » si un passage t'intéresse)")


def automatic_recalls(conv, r, budget=2200):
    """Passages des documents et des anciennes conversations liés à la dernière question, ajoutés au prompt sans que le modèle ait à les demander (mode scénariste par défaut).
    Renvoie (texte pour le prompt, liste des sources) ; vide si le réglage est coupé ou si rien de vraiment lié n'existe. budget : caractères de passages au plus."""
    mode = r.get("rappels_auto", "scenario")
    if mode == "jamais" or (mode == "scenario" and not _modes.default_recalls(r.get("mode"))):
        return "", []
    question = next((m["content"] for m in reversed(conv["messages"]) if m.get("role") == "user" and m.get("content") and not m["content"].startswith("[")), "")
    if len(question) < 15:
        return "", []
    passages = recall_passages(question[:600], 4, exclure_conv=conv.get("id", ""), min_termes=2)
    if not passages:
        return "", []
    sources = []
    for p in passages:
        if p["m"]["source"] not in sources:
            sources.append(p["m"]["source"])
    texte = (_t("\n\n# RAPPELS POSSIBLEMENT PERTINENTS (extraits automatiques des documents et des anciennes conversations ; ils peuvent être hors sujet : ignore-les alors, "
             "et ouvre le document avec « lire » si un détail compte)\n") + format_passages(passages, 450)[:max(0, int(budget))] + "\n")
    return texte, sources
