"""Mémoire, compétences (skills) et conversations : lecture, écriture atomique, réparation, sauvegardes de secours."""
from pathlib import Path
from .i18n import t as _t
from datetime import datetime
import json
import os
import re
import secrets
import shutil
import time
import unicodedata
from . import modes as _modes
from . import moteur as _m


# --------------------------------------------------------------------------- réglages, mémoire, conversations
def lire_json(chemin, defaut):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return defaut


def ecrire_atomique(chemin, texte):
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + "." + secrets.token_hex(3) + ".tmp")
    tmp.write_text(texte, encoding="utf-8")
    for essai in range(40):
        try:
            os.replace(str(tmp), str(chemin))
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(str(tmp), str(chemin))


def enregistrer_reglages(nouveau, de_confiance=True):
    """Écrit les réglages. On part de ce qui est écrit dans le fichier (pas de la version « masquée » par la règle de sécurité) : enregistrer un autre réglage ne fait pas perdre les cases d'accord automatique.
    Seul le navigateur de cette machine (de_confiance) peut les changer."""
    r = _m.reglages(masquer=False)
    for k in _m.REGLAGES_DEFAUT:
        if k in nouveau and (de_confiance or k not in ("auto_ecriture", "auto_commandes")):
            r[k] = nouveau[k]
    if not _modes.valide(r["mode"]):
        raise ValueError("Mode inconnu.")
    if not re.match(r"^[A-Za-z0-9_./:-]{1,100}$", str(r["modele"])):
        raise ValueError("Nom de modèle invalide.")
    r["num_ctx"] = max(4096, min(131072, int(r["num_ctx"])))
    r["num_predict"] = max(0, min(32768, int(r.get("num_predict", 0))))
    r["tours_max"] = max(4, min(40, int(r.get("tours_max", 14))))
    r["web"] = bool(r.get("web", True))
    r["essai_a_blanc"] = bool(r.get("essai_a_blanc"))
    r["copie_conversations"] = bool(r.get("copie_conversations"))
    if r.get("memoire_longue") not in ("resume", "fichier", "demander"):
        raise ValueError(_t("Mémoire des longues conversations inconnue (resume, fichier ou demander)."))
    _m.nettoyer_echantillonnage(r)
    _m.nettoyer_ressources(r)
    ecrire_atomique(_m.DONNEES / "reglages.json", json.dumps(dict(r, memoire_v=2), ensure_ascii=False, indent=1))
    return _m.reglages(de_confiance=de_confiance)


def lire_memoire(nom):
    f = _m.MEMOIRE / nom
    try:
        return f.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def ecrire_memoire(nom, texte):
    if nom not in ("CONTEXTE.md", "MEMOIRE.md"):
        raise ValueError("Fichier de mémoire inconnu.")
    if len(texte) > 60000:
        raise ValueError("Texte trop long (60 000 caractères au maximum).")
    ecrire_atomique(_m.MEMOIRE / nom, texte)


def noter(note):
    note = " ".join(str(note).split())[:600]
    if not note:
        raise _m.ErreurOutil("Note vide.")
    ligne = "- {} : {}\n".format(datetime.now().strftime("%Y-%m-%d"), note)
    f = _m.MEMOIRE / "MEMOIRE.md"
    existant = lire_memoire("MEMOIRE.md") or _t("# Mémoire de l'assistant\n\nNotes durables (ajoutées par l'assistant ou à la main).\n\n")
    texte = existant.rstrip("\n") + "\n" + ligne
    i = position_notes(texte)
    if i >= 0:                                              # la section des notes ne grossit pas sans fin : on garde les 40 dernières lignes
        tete, notes = texte[:i], texte[i:].split("\n")
        if len(notes) > 43:
            notes = notes[:2] + notes[-40:]
        texte = tete + "\n".join(notes) + "\n"
    ecrire_atomique(f, texte)
    return _t("Noté dans memoire/MEMOIRE.md.")


def lister_notes():
    """Les notes durables de l'assistant (les lignes « - date : texte » de la section des notes de MEMOIRE.md), dans l'ordre du fichier : la plus récente en dernier."""
    memoire = lire_memoire("MEMOIRE.md")
    i = position_notes(memoire)
    notes = []
    for ligne in (memoire[i:] if i >= 0 else "").split("\n"):
        if ligne.startswith("- "):
            date, sep, texte = ligne[2:].partition(" : ")
            notes.append({"ligne": ligne, "date": date if sep and re.match(r"^\d{4}-\d\d-\d\d$", date) else "", "texte": texte if sep and re.match(r"^\d{4}-\d\d-\d\d$", date) else ligne[2:]})
    return notes


def supprimer_note(ligne):
    """Retire la première ligne de notes identique à `ligne` (le texte exact reçu de lister_notes : pas d'indice qui pourrait viser une autre note si le fichier a changé entre-temps)."""
    memoire = lire_memoire("MEMOIRE.md")
    i = position_notes(memoire)
    if i < 0 or not ligne.startswith("- "):
        raise ValueError(_t("Note introuvable."))
    lignes = memoire[i:].split("\n")
    if ligne not in lignes:
        raise ValueError(_t("Note introuvable."))
    lignes.remove(ligne)
    ecrire_atomique(_m.MEMOIRE / "MEMOIRE.md", memoire[:i] + "\n".join(lignes))
    return {"ok": True}


def lister_skills():
    """Les fiches de skills (skills/*.md) : le contenu du projet, construit par l'utilisateur.
    On ne lit que les titres ici (le contenu se lit à la demande avec l'outil « lire »)."""
    dossier = _m.RACINE / "skills"
    try:
        fichiers = sorted(dossier.glob("*.md"), key=lambda p: p.name)
    except OSError:
        return []
    fiches = []
    for f in fichiers:
        titre = f.stem
        try:
            for ligne_txt in f.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
                if ligne_txt.startswith("# "):
                    titre = ligne_txt[2:].strip()
                    break
        except OSError:
            pass
        fiches.append((f.name, titre))
    return fiches


RE_DESC_SKILL = re.compile(r"^[ÀA] lire quand\s+(.+)$", re.M)


def description_skill(nom):
    """« À lire quand… » : la phrase que la fiche donne sur elle-même, pour que le modèle sache quand l'ouvrir. Vide si la fiche n'en a pas (le contenu n'est jamais copié dans le prompt)."""
    try:
        tete = (_m.RACINE / "skills" / nom).read_text(encoding="utf-8-sig", errors="ignore")[:1500]
    except OSError:
        return ""
    m = RE_DESC_SKILL.search(tete)
    return " ".join(m.group(1).split())[:170].rstrip(".") if m else ""


MARQUE_NOTES = "\n## Notes de l'assistant"


MARQUES_NOTES = (MARQUE_NOTES, "\n## Assistant notes")          # le modèle de mémoire anglais (data/en/MEMOIRE.md) a son propre titre


def position_notes(texte):
    """Où commence la section des notes de l'assistant (dans l'une ou l'autre langue), ou -1."""
    trouvees = [i for i in (texte.find(m) for m in MARQUES_NOTES) if i >= 0]
    return min(trouvees) if trouvees else -1


def texte_memoire(memoire, budget=6000):
    """Ce qui est relu de MEMOIRE.md à chaque conversation : les parties fixes (décisions de l'utilisateur, limites) toujours, et seulement la fin de la section « Notes de l'assistant »
    (qui grossit). Sans cette section, les derniers caractères du fichier, comme avant."""
    i = position_notes(memoire)
    if i < 0:
        return memoire[-budget:]
    fixe = memoire[:i][:budget - 1500]
    return fixe + memoire[i:][-(budget - len(fixe)):]


RE_SKILL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\- ]{0,98}\.md$")


def _fichier_skill(nom):
    if not RE_SKILL.match(str(nom)):
        raise ValueError("Nom de skill invalide (lettres, chiffres, tirets, espaces, et .md).")
    dossier = _m.RACINE / "skills"
    dossier.mkdir(exist_ok=True)
    return dossier / nom


def lire_skill(nom):
    return _fichier_skill(nom).read_text(encoding="utf-8-sig")


def ecrire_skill(nom, texte):
    if len(texte) > 60000:
        raise ValueError("Texte trop long (60 000 caractères au maximum).")
    ecrire_atomique(_fichier_skill(nom), texte)
    return {"ok": True}


def supprimer_skill(nom):
    f = _fichier_skill(nom)
    if not f.is_file():
        raise ValueError("Skill introuvable : " + str(nom))
    f.unlink()
    return {"ok": True}


RE_CONV = re.compile(r"^[0-9a-f]{8,16}$")


def conv_chemin(ident):
    if not RE_CONV.match(ident or ""):
        raise ValueError("Conversation inconnue.")
    return _m.DONNEES / "conversations" / (ident + ".json")


def conv_lire(ident):
    f = conv_chemin(ident)
    c = None
    for essai in range(4):
        try:
            c = json.loads(Path(f).read_text(encoding="utf-8-sig"))
            break
        except FileNotFoundError:
            break
        except ValueError:
            break                                                  # contenu illisible : la copie de secours peut servir
        except OSError as erreur:                                  # lecture qui tombe pile pendant une écriture (Windows, partage réseau) : on réessaie, on ne restaure RIEN
            if essai == 3:
                raise ValueError("Conversation momentanément illisible ({}) : réessaie dans un instant.".format(erreur))
            time.sleep(0.15 * (essai + 1))
    if not c:
        sauvegarde = Path(str(f) + ".bak")                       # fichier abîmé (plantage du PC pendant l'écriture ?) : on reprend la copie de la fois d'avant
        c = lire_json(sauvegarde, None)
        if not c:
            raise ValueError("Conversation introuvable.")
        _m.journaliser("Conversation {} illisible : restaurée depuis sa copie de secours.".format(ident))
        shutil.copyfile(sauvegarde, f)
    return c


def reparer_conversation(conv):
    """Après un arrêt brutal, un appel d'outil peut être resté sans réponse : on en inscrit une, pour que la conversation reste cohérente pour le modèle."""
    msgs, i, repares = conv["messages"], 0, 0
    while i < len(msgs):
        m = msgs[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            j = i + 1
            while j < len(msgs) and msgs[j].get("role") == "tool":
                j += 1
            presents = j - i - 1
            if presents < len(m["tool_calls"]):
                manquants = [{"role": "tool", "tool_name": (c.get("function") or {}).get("name", ""), "content": "Interrompu (arrêt ou plantage avant la fin de cet outil)."} for c in m["tool_calls"][presents:]]
                msgs[j:j] = manquants
                repares += len(manquants)
                j += len(manquants)
            i = j
        else:
            i += 1
    if repares:
        _m.journaliser("Conversation {} réparée : {} réponse(s) d'outil manquante(s).".format(conv.get("id"), repares))
    return repares


def conv_nouvelle():
    ident = secrets.token_hex(4)
    c = {"id": ident, "titre": "Nouvelle conversation", "date": datetime.now().isoformat(timespec="seconds"), "messages": [], "resume": ""}
    conv_ecrire(c)
    return c


def conv_ecrire(c):
    c["maj"] = datetime.now().isoformat(timespec="milliseconds")          # à la milliseconde : deux conversations écrites dans la même seconde restent dans l'ordre
    f = conv_chemin(c["id"])
    if f.is_file():
        try:
            shutil.copyfile(f, str(f) + ".bak")                  # copie de secours de la version précédente
        except OSError:
            pass
    ecrire_atomique(f, json.dumps(c, ensure_ascii=False))
    try:
        copier_dans_le_dossier_de_travail(c)
    except OSError as erreur:                               # une copie impossible (dossier en lecture seule, disque réseau absent) ne doit jamais empêcher d'enregistrer la conversation
        _m.journaliser("Copie de la conversation {} dans le dossier de travail impossible : {!r}".format(c.get("id"), erreur))


DOSSIER_COPIES = "conversations-lutin"


def conv_markdown(c):
    """La conversation en Markdown lisible : tes messages, les réponses ; les outils en une ligne ; les images et fichiers joints cités par leur nom."""
    lignes = ["# " + (c.get("titre") or _t("Conversation sans titre")), "", "*" + str(c.get("date", ""))[:16].replace("T", " ") + "*", ""]
    if c.get("resume"):
        lignes += ["> " + _t("Résumé du début de la conversation : ") + " ".join(str(c["resume"]).split())[:600], ""]
    for m in c.get("messages", []):
        role, texte = m.get("role"), (m.get("content") or "").strip()
        if role == "user":
            lignes += ["## " + _t("Moi"), "", texte]
            if m.get("images"):
                lignes += ["", "*" + _t("{} image(s) jointe(s)").format(len(m["images"])) + "*"]
            for piece in m.get("pieces") or []:
                lignes += ["", "*" + _t("Fichier joint : {}").format(piece.get("nom", "")) + "*"]
            lignes.append("")
        elif role == "assistant":
            for appel in m.get("tool_calls") or []:
                f = appel.get("function") or {}
                lignes += ["> " + _t("outil") + " `" + str(f.get("name", "")) + "` " + json.dumps(f.get("arguments", {}), ensure_ascii=False)[:160], ""]
            if texte:
                lignes += ["## Lutin", "", texte, ""]
        elif role == "tool":
            lignes += ["> ↳ " + (m.get("tool_name") or _t("résultat")) + " : " + " ".join(texte.split())[:200], ""]
    return "\n".join(lignes).rstrip() + "\n"


def nom_de_copie(c):
    titre = unicodedata.normalize("NFKD", c.get("titre") or "conversation").encode("ascii", "ignore").decode().lower()
    titre = re.sub(r"[^a-z0-9]+", "-", titre).strip("-")[:50] or "conversation"
    return "{}-{}-{}.md".format(str(c.get("date", ""))[:10] or "sans-date", titre, c["id"])


def dossier_de_travail_de(c):
    """Le dossier de travail de cette conversation (le sien, sinon le dossier courant)."""
    from . import travaux as _trav
    t = _trav.par_id(_m.config_lue(), c["travail"]) if c.get("travail") else None
    return Path(t["chemin"]) if t else _m.RACINE


def copier_dans_le_dossier_de_travail(c):
    """Si le réglage est coché : une copie lisible (Markdown) de la conversation dans `conversations-lutin/` du dossier de travail. Écrite seulement si elle change. Renvoie le chemin ou None."""
    if not _m.reglages().get("copie_conversations") or not c.get("messages"):
        return None
    dossier = dossier_de_travail_de(c) / DOSSIER_COPIES
    if not dossier.parent.is_dir():
        return None
    texte = conv_markdown(c)
    f = dossier / nom_de_copie(c)
    for ancien in dossier.glob("*-" + c["id"] + ".md") if dossier.is_dir() else []:
        if ancien != f:                                  # le titre a changé : l'ancien nom disparaît, la conversation n'a qu'une copie
            ancien.unlink(missing_ok=True)
    try:
        if f.is_file() and f.read_text(encoding="utf-8") == texte:
            return f
    except OSError:
        pass
    dossier.mkdir(exist_ok=True)
    ecrire_atomique(f, texte)
    return f


CACHE_CONV = {}          # chemin -> (date de modification, taille, entrée de liste) : la page demande la liste toutes les 4 s, on ne relit que ce qui a changé


def conv_liste():
    dossier = _m.DONNEES / "conversations"
    sortie, vus = [], set()
    for f in (dossier.glob("*.json") if dossier.is_dir() else []):
        cle = str(f)
        try:
            st = f.stat()
        except OSError:
            continue
        vus.add(cle)
        en_cache = CACHE_CONV.get(cle)
        if en_cache and en_cache[0] == st.st_mtime_ns and en_cache[1] == st.st_size:
            entree = en_cache[2]
        else:
            c = lire_json(f, None)
            entree = {"id": c["id"], "titre": c.get("titre", ""), "maj": c.get("maj", c.get("date", "")), "messages": len(c.get("messages", [])), "epingle": bool(c.get("epingle")), "memoire": c.get("memoire_longue", "")} if c and RE_CONV.match(c.get("id", "")) else None
            CACHE_CONV[cle] = (st.st_mtime_ns, st.st_size, entree)
        if entree:
            sortie.append(entree)
    for cle in [k for k in CACHE_CONV if k not in vus and k.startswith(str(dossier))]:
        del CACHE_CONV[cle]
    return sorted(sorted(sortie, key=lambda x: x["maj"], reverse=True), key=lambda x: not x["epingle"])          # les épinglées d'abord, puis les plus récentes


def conv_supprimer(ident):
    f = conv_chemin(ident)
    if f.is_file():
        f.unlink()
    Path(str(f) + ".bak").unlink(missing_ok=True)
    from . import suivi
    suivi.supprimer(ident)                                  # la fiche de suivi disparaît avec la conversation
    from . import archive, embeddings
    archive.supprimer(ident)                                # et le début archivé par le résumé
    embeddings.supprimer(ident)                             # et ses vecteurs de recherche par le sens


def conv_renommer(ident, titre):
    c = conv_lire(ident)
    c["titre"] = titre.strip()[:120]
    conv_ecrire(c)
    return c
