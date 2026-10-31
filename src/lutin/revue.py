"""Revue des changements d'une demande (annulation fichier par fichier) et git assisté (état, message de commit, commit)."""
from pathlib import Path
from .i18n import t as _t
import json
import re
import secrets
import shutil
import subprocess
from . import moteur as _m


# --------------------------------------------------------------------------- revue des changements d'une demande, et git
def lire_utf8(f):
    try:
        return Path(f).read_bytes().decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError):
        return None


def retablir_fichier(dossier, chemin, e):
    """Remet un fichier dans l'état d'avant la demande. Renvoie (réussi, raison de l'échec)."""
    try:
        f = _m.chemin_sur(chemin, ecriture=True)
    except _m.ErreurOutil:
        return False, "chemin refusé"
    if e.get("apres") and _m.sha_fichier(f) != e["apres"]:
        return False, "modifié depuis"
    if e.get("avant"):
        source = dossier / chemin
        if not source.is_file():
            return False, "sauvegarde absente"
        f.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, f)
    elif f.is_file():
        f.unlink()                                                      # le fichier avait été créé par la demande
    return True, ""


def manifeste_annulable(ident):
    if ident in _m.TOURS_ACTIFS:
        raise ValueError("Une réponse est en cours dans cette conversation : arrête-la d'abord.")
    conv = _m.conv_lire(ident)
    info = conv.get("annulable")
    if not info:
        raise ValueError("Aucune modification de fichier à annuler dans cette conversation.")
    dossier = _m.DONNEES / "sauvegardes" / info["id"]
    manifeste = _m.lire_json(dossier / "_tour.json", None)
    if not manifeste:
        raise ValueError("Les sauvegardes de cette demande ont disparu (purge après 60 jours ?).")
    return conv, dossier, manifeste


def revue_tour(ident):
    """Pour chaque fichier touché par la dernière demande : état, lignes ajoutées et retirées, différences."""
    conv = _m.conv_lire(ident)
    if not conv.get("annulable"):
        return {"fichiers": []}
    dossier = _m.DONNEES / "sauvegardes" / conv["annulable"]["id"]
    manifeste = _m.lire_json(dossier / "_tour.json", None) or {"fichiers": {}}
    sortie = []
    for chemin, e in manifeste["fichiers"].items():
        if e.get("annule"):
            continue
        try:
            f = _m.chemin_sur(chemin)
        except _m.ErreurOutil:
            continue
        avant = lire_utf8(dossier / chemin) if e.get("avant") else ""
        apres = lire_utf8(f) if f.is_file() else ""
        binaire = avant is None or apres is None
        diff = "" if binaire else _m.difference(avant, apres, chemin)
        sortie.append({"chemin": chemin, "etat": "créé" if not e.get("avant") else ("supprimé" if not f.is_file() else "modifié"), "binaire": binaire, "diff": diff,
                       "plus": sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")), "moins": sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")),
                       "modifie_depuis": bool(e.get("apres")) and _m.sha_fichier(f) != e["apres"]})
    return {"fichiers": sortie}


def annuler_tour(ident, seulement=None):
    """Rétablit les fichiers modifiés ou créés par la dernière demande qui en a touché (outils « modifier », « ecrire » et « modifier_plusieurs » ;
    pas les effets des commandes). Un fichier modifié depuis par quelqu'un d'autre n'est pas touché. seulement : un chemin, pour n'annuler que celui-là."""
    conv, dossier, manifeste = manifeste_annulable(ident)
    retablis, ignores = [], []
    for chemin, e in manifeste["fichiers"].items():
        if e.get("annule") or (seulement is not None and chemin != seulement):
            continue
        ok, raison = retablir_fichier(dossier, chemin, e)
        if ok:
            retablis.append(chemin)
            e["annule"] = True
        else:
            ignores.append("{} ({})".format(chemin, raison))
    if seulement is not None and not retablis:
        raise ValueError(_t("Pas rétabli : {}").format(ignores[0] if ignores else _t("{} ne fait pas partie de la dernière demande.").format(seulement)))
    restants = [c for c, e in manifeste["fichiers"].items() if not e.get("annule")]
    manifeste["annule"] = not restants
    _m.ecrire_atomique(dossier / "_tour.json", json.dumps(manifeste, ensure_ascii=False, indent=1))
    if restants and seulement is not None:
        conv["annulable"]["fichiers"] = sorted(restants)
    else:
        conv.pop("annulable", None)
    conv["messages"].append({"role": "user", "content": "[Note automatique : l'utilisateur a annulé des modifications de fichiers de la demande précédente. Rétablis : {}.{} Ne considère plus ces modifications comme faites.]".format(
        ", ".join(retablis) or "aucun", (" Non rétablis : " + ", ".join(ignores) + ".") if ignores else "")})
    _m.conv_ecrire(conv)
    _m.journaliser("Demande annulée (conversation {}) : {} rétabli(s), {} ignoré(s).".format(ident, len(retablis), len(ignores)))
    return {"ok": True, "retablis": retablis, "ignores": ignores}


ETATS_GIT = {"??": "nouveau", "M": "modifié", "A": "ajouté", "D": "supprimé", "R": "renommé", "C": "copié", "U": "conflit"}


def git_etat():
    """Les changements en attente dans le dépôt du projet, pour l'écran Git."""
    if not shutil.which("git"):
        return {"dispo": False, "raison": "git n'est pas installé sur cette machine."}
    try:
        code, sortie, erreur = _m.git(["status", "--porcelain=v1"])
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"dispo": False, "raison": "git n'a pas répondu : {}".format(e)}
    if code != 0:
        if "dubious ownership" in erreur or "safe.directory" in erreur:
            return {"dispo": False, "raison": "git refuse encore ce dossier (propriétaire différent, fréquent sur un partage réseau), malgré l'autorisation donnée à chaque appel : ta version de git est peut-être trop ancienne. Mets git à jour, ou lance une fois dans un terminal : git config --global --add safe.directory \"{}\"".format(str(_m.RACINE).replace("\\", "/"))}
        return {"dispo": False, "raison": "Ce dossier n'est pas un dépôt git, ou git a échoué : " + erreur.strip()[:200]}
    modifies = []
    for ligne in sortie.splitlines():
        if len(ligne) < 4:
            continue
        xy, chemin = ligne[:2], ligne[3:].strip().strip('"')
        if " -> " in chemin:
            chemin = chemin.split(" -> ", 1)[1]
        etat = ETATS_GIT.get(xy.strip()) or ETATS_GIT.get(xy.strip()[:1]) or ETATS_GIT.get(xy.strip()[-1:], "modifié")
        modifies.append({"chemin": chemin, "etat": etat})
    code2, branche, _ = _m.git(["rev-parse", "--abbrev-ref", "HEAD"])
    return {"dispo": True, "branche": branche.strip() if code2 == 0 else "(aucun commit)", "modifies": modifies[:400], "total": len(modifies)}


def chemins_git(fichiers):
    if not isinstance(fichiers, list) or not fichiers or len(fichiers) > 300:
        raise ValueError("Choisis entre 1 et 300 fichiers.")
    propres = []
    for x in fichiers:
        try:
            p = _m.chemin_sur(str(x))
        except _m.ErreurOutil as e:
            raise ValueError(str(e))
        propres.append(_m.rel(p) if p.exists() else str(x).replace("\\", "/").strip("/"))
    return propres


def git_message(fichiers, r=None):
    """Fait écrire par le modèle un message de commit à partir des changements des fichiers choisis (rien n'est commité)."""
    r = r or _m.reglages()
    fichiers = chemins_git(fichiers)
    code, sortie, _ = _m.git(["status", "--porcelain=v1", "--"] + fichiers)
    nouveaux = [l[3:].strip().strip('"') for l in sortie.splitlines() if l.startswith("??")]
    suivis = [f for f in fichiers if f not in nouveaux]
    diff = ""
    if suivis:
        c, stat, _ = _m.git(["diff", "HEAD", "--stat", "--"] + suivis)
        c2, corps, _ = _m.git(["diff", "HEAD", "-U1", "--"] + suivis)
        if c != 0:                                    # dépôt sans commit : on regarde ce qui est déjà ajouté
            stat, corps = "", _m.git(["diff", "--cached", "-U1", "--"] + suivis)[1]
        diff = stat + "\n" + corps
    for n in nouveaux[:6]:
        p = _m.chemin_sur(n)
        extrait = "\n".join((lire_utf8(p) or "(fichier non texte)").splitlines()[:40]) if p.is_file() else "(dossier)"
        diff += "\n\nNouveau fichier {} :\n{}".format(n, extrait)
    if not diff.strip():
        raise ValueError("Aucune différence à décrire pour ces fichiers.")
    if len(diff) > 14000:
        diff = diff[:14000] + "\n[... différences coupées]"
    _, journal, _ = _m.git(["log", "-8", "--pretty=%s"])
    consigne = ("Écris le message de commit de ces changements.\n"
                "Format : une première ligne de 72 caractères au plus (ce qui change, en français, au présent ou à l'infinitif), une ligne vide, puis 2 à 6 puces « - » avec les changements importants.\n"
                "Pas de guillemets autour, pas de blabla : réponds UNIQUEMENT avec le message.\n"
                "Style des commits récents du projet :\n" + (journal.strip() or "(aucun)") + "\n\nCHANGEMENTS :\n" + diff)
    corps = {"model": r["modele"], "messages": [{"role": "user", "content": consigne}], "stream": False, "think": False, "options": _m.options_modele(r, 0.3)}
    reponse = _m.ollama_json("/api/chat", corps, 300)
    texte = (reponse.get("message", {}).get("content") or "").strip()
    texte = re.sub(r"^```\w*\n|\n```$", "", texte).strip().strip('"')
    if not texte:
        raise ValueError("Le modèle n'a pas répondu.")
    return {"message": texte[:3000]}


def git_commit(message, fichiers):
    """Commit des fichiers choisis uniquement (pas de push)."""
    message = str(message or "").strip()
    if not message or len(message) > 4000:
        raise ValueError("Écris un message de commit (4 000 caractères au plus).")
    fichiers = chemins_git(fichiers)
    code, sortie, erreur = _m.git(["add", "--"] + fichiers)
    if code != 0:
        raise ValueError(_t("git add a échoué : {}").format((erreur or sortie).strip()[:400]))
    fichier_message = _m.DONNEES / ("commit-" + secrets.token_hex(3) + ".txt")
    try:
        fichier_message.parent.mkdir(parents=True, exist_ok=True)
        fichier_message.write_text(message + "\n", encoding="utf-8")
        a_un_commit = _m.git(["rev-parse", "--verify", "-q", "HEAD"])[0] == 0
        if a_un_commit:                                  # « --only » : seuls ces fichiers entrent dans le commit, même si d'autres sont déjà ajoutés à l'index
            code, sortie, erreur = _m.git(["commit", "--only", "-F", str(fichier_message), "--"] + fichiers, delai=120)
        else:                                            # tout premier commit du dépôt : l'index ne contient que ce qu'on vient d'ajouter
            code, sortie, erreur = _m.git(["commit", "-F", str(fichier_message)], delai=120)
    finally:
        fichier_message.unlink(missing_ok=True)
    if code != 0:
        raise ValueError(_t("git commit a échoué : {}").format((erreur.strip() or sortie.strip())[:500]))
    _m.journaliser("Commit de {} fichier(s) depuis l'assistant : {}".format(len(fichiers), message.splitlines()[0][:80]))
    return {"ok": True, "sortie": sortie.strip()[:600]}


def epingler_conversation(ident, epingle):
    c = _m.conv_lire(ident)
    c["epingle"] = bool(epingle)
    _m.ecrire_atomique(_m.conv_chemin(ident), json.dumps(c, ensure_ascii=False))          # sans toucher à la date « maj » : épingler ne remonte pas la conversation
    return {"ok": True, "epingle": c["epingle"]}


EPINGLES_MAX = 8                 # messages épinglés au plus par conversation (ils prennent de la place à chaque réponse)


def epingler_message(ident, index, epingle):
    """Marque un message comme important : il n'est jamais retiré du contexte du modèle (ni par la réduction du contexte, ni par le résumé), dans la limite d'un quart de la fenêtre."""
    if ident in _m.TOURS_ACTIFS:
        raise ValueError(_t("Une réponse est en cours dans cette conversation : attends la fin ou arrête-la."))
    c = _m.conv_lire(ident)
    try:
        i = int(index)
    except (TypeError, ValueError):
        raise ValueError(_t("Message inconnu."))
    msgs = c["messages"]
    if not 0 <= i < len(msgs) or msgs[i].get("role") not in ("user", "assistant") or not (msgs[i].get("content") or "").strip():
        raise ValueError(_t("Ce message ne peut pas être épinglé."))
    if epingle:
        if not msgs[i].get("epingle") and sum(1 for m in msgs if m.get("epingle")) >= EPINGLES_MAX:
            raise ValueError(_t("{} messages épinglés au plus : désépingle-en un d'abord.").format(EPINGLES_MAX))
        msgs[i]["epingle"] = True
    else:
        msgs[i].pop("epingle", None)
    _m.ecrire_atomique(_m.conv_chemin(ident), json.dumps(c, ensure_ascii=False))          # sans toucher à la date « maj »
    return {"ok": True, "epingles": sum(1 for m in msgs if m.get("epingle"))}


def chercher_conversations(q):
    """Recherche dans le titre et le contenu des conversations enregistrées."""
    q = " ".join(str(q or "").lower().split())
    if len(q) < 2:
        return {"resultats": []}
    trouves = []
    dossier = _m.DONNEES / "conversations"
    for f in (dossier.glob("*.json") if dossier.is_dir() else []):
        c = _m.lire_json(f, None)
        if not c or not _m.RE_CONV.match(c.get("id", "")):
            continue
        extrait = ""
        if q in c.get("titre", "").lower():
            extrait = c["titre"]
        else:
            for m in c.get("messages", []):
                texte = m.get("content") or ""
                if m.get("role") in ("user", "assistant") and q in texte.lower():
                    i = texte.lower().find(q)
                    extrait = "…" + " ".join(texte[max(0, i - 60):i + 100].split()) + "…"
                    break
        if extrait:
            trouves.append({"id": c["id"], "titre": c.get("titre", ""), "extrait": extrait, "maj": c.get("maj", ""), "epingle": bool(c.get("epingle"))})
    trouves.sort(key=lambda x: x["maj"], reverse=True)
    return {"resultats": trouves[:30]}


def _appeler_outil(nom, args, ctx):
    if not isinstance(args, dict):
        raise _m.ErreurOutil("Arguments invalides.")
    if nom == "lister":
        return _m.outil_lister(args.get("dossier", "."))
    if nom == "lire":
        return _m.outil_lire(args.get("chemin"), args.get("debut"), args.get("fin"))
    if nom == "chercher":
        return _m.outil_chercher(args.get("motif", ""), args.get("dossier", "."), args.get("contexte", 0), args.get("fichiers", ""))
    if nom == "symboles":
        return _m.outil_symboles(args.get("nom", ""), args.get("dossier", "."))
    if nom == "lire_plusieurs":
        return _m.outil_lire_plusieurs(args.get("fichiers"))
    if nom == "rappeler":
        return _m.outil_rappeler(args.get("requete", ""), args.get("nombre"), (ctx.get("conv") or {}).get("id", ""), bool(args.get("ici")))
    if nom == "modifier":
        return _m.outil_modifier(args.get("chemin"), str(args.get("ancien", "")), str(args.get("nouveau", "")), ctx)
    if nom == "modifier_plusieurs":
        return _m.outil_modifier_plusieurs(args.get("chemin"), args.get("remplacements"), ctx)
    if nom == "ecrire":
        return _m.outil_ecrire(args.get("chemin"), str(args.get("contenu", "")), ctx)
    if nom == "executer":
        return _m.outil_executer(args.get("commande", ""), ctx, args.get("shell", "cmd"))
    if nom == "memoriser":
        return _m.noter(args.get("note", ""))
    if nom == "web_chercher":
        return _m.outil_web_chercher(args.get("requete", ""), args.get("nombre"), ctx)
    if nom == "web_lire":
        return _m.outil_web_lire(args.get("url", ""), args.get("debut"), ctx)
    if nom == "taches":
        return _m.outil_taches(args.get("liste", []), ctx)
    if nom == "creer_document":
        return _m.outil_document(args.get("chemin"), str(args.get("contenu", "")), args.get("titre", ""), ctx)
    if nom in ("mission_terminer", "mission_bloquee"):
        from . import mission
        if not ctx.get("mission"):
            raise _m.ErreurOutil("Cet outil n'existe que pendant une mission longue.")
        return mission.signaler(ctx["mission"], "terminee" if nom == "mission_terminer" else "bloquee", args.get("bilan") or args.get("question") or "")
    if nom == "suivi":
        from . import suivi
        conv = ctx.get("conv")
        if conv is None:
            raise _m.ErreurOutil("Pas de conversation active.")
        return suivi.modifier(conv["id"], args.get("section", ""), args.get("texte", ""), args.get("mode", ""))
    if nom in ("comfy_modeles", "comfy_generer"):
        from . import addons, addons_comfyui
        if not addons.actif("comfyui"):
            raise _m.ErreurOutil("L'addon ComfyUI n'est pas activé.")
        return addons_comfyui.texte_modeles() if nom == "comfy_modeles" else addons_comfyui.outil_generer(args, ctx)
    if nom == "etat_outil":
        return _m.outil_etat()
    if nom == "installer_module":
        return _m.outil_installer_module(args.get("module", ""), ctx)
    raise _m.ErreurOutil("Outil inconnu : " + str(nom))


def appeler_outil(nom, args, ctx):
    """Exécute un outil ; les actions qui modifient quelque chose (fichiers, commandes, modules) sont inscrites au journal des actions."""
    if nom not in _m.OUTILS_JOURNALISES or not isinstance(args, dict):
        return _appeler_outil(nom, args, ctx)
    ctx.pop("dernier_accord", None)
    try:
        resultat = _appeler_outil(nom, args, ctx)
    except _m.ErreurOutil as e:
        _m.noter_action(ctx, nom, args, "erreur : " + str(e))
        raise
    except _m.Arret:
        _m.noter_action(ctx, nom, args, "arrêté")
        raise
    _m.noter_action(ctx, nom, args, "refusé" if str(resultat).startswith("Refusé par l'utilisateur") else "ok")
    return resultat
