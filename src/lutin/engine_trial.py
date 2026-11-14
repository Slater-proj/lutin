"""Essai réel d'un moteur : `lutin engine-trial llamacpp`.

Les tests de Lutin utilisent de faux serveurs. Cet essai-ci fait **pour de vrai**, sur la machine où il est lancé, ce que Lutin fait avec un moteur : installer le programme, démarrer le serveur avec un
modèle, vérifier qu'il répond, tenir une conversation en flux (premier jeton, vitesse), faire un appel d'outil, puis arrêter proprement. Chaque étape dit ce qui marche ou non, et le rapport est
écrit dans un fichier JSON à joindre à un compte rendu. Rien n'est téléchargé sans une réponse « oui » (ou --yes).

L'essai ne modifie rien d'autre que le dossier de Lutin (le moteur installé, les modèles téléchargés, le rapport)."""
import json
import os
import platform
import re
import time
from datetime import datetime
from pathlib import Path

from . import engines
from .i18n import t as _t

SUGGESTION = ("unsloth/Qwen3-4B-Instruct-2507-GGUF", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")          # un modèle à outils, 2,5 Go, présent sur Hugging Face (vérifié le 2026-11-06)
MODELE_TEST = ("ggml-org/tiny-llamas", "stories260K.gguf")          # 1,2 Mo : il ne sait rien dire d'utile, mais il prouve que le serveur démarre et répond (essais automatiques)
OUTIL_HEURE = {"type": "function", "function": {"name": "heure", "description": "Donne l'heure actuelle.", "parameters": {"type": "object", "properties": {}}}}


class Rapport:
    def __init__(self, ecrire):
        self.etapes, self.ecrire = [], ecrire

    def etape(self, nom, ok, detail="", duree=0.0, avertissement=False):
        self.etapes.append({"etape": nom, "ok": bool(ok), "avertissement": bool(avertissement), "detail": str(detail)[:600], "duree_s": round(duree, 2)})
        signe = "⚠" if avertissement else ("✔" if ok else "✘")
        self.ecrire("{} {}{}{}".format(signe, nom, " : " + str(detail)[:300] if detail else "", " ({:.1f} s)".format(duree) if duree >= 0.5 else ""))

    def reussi(self):
        return all(e["ok"] or e["avertissement"] for e in self.etapes)

    def avertissements(self):
        return [e["etape"] for e in self.etapes if e["avertissement"] and not e["ok"]]


def decouper_modele(texte):
    """« auteur/depot/fichier.gguf » -> (« auteur/depot », « fichier.gguf »)."""
    morceaux = str(texte).split("/")
    if len(morceaux) < 3:
        raise ValueError(_t("Écris le modèle sous la forme auteur/dépôt/fichier.gguf (par exemple {}/{}).").format(*SUGGESTION))
    return "/".join(morceaux[:2]), "/".join(morceaux[2:])


def barre_de_progression(ecrire):
    """Une ligne de progression sobre (un point d'avancement tous les 10 %)."""
    etat = {"dernier": -1, "texte": ""}

    def progression(texte="", fait=0, total=0):
        pct = int(100 * fait / total) if total else -1
        if texte != etat["texte"]:
            etat["texte"], etat["dernier"] = texte, -1
            ecrire("   " + str(texte))
        if pct >= 0 and pct // 10 > etat["dernier"] // 10:
            etat["dernier"] = pct
            ecrire("   {} % ({} / {} Mo)".format(pct, fait // 1_000_000, total // 1_000_000))
    return progression


def diagnostic_linux(moteur):
    """Sous Linux, un serveur qui ne démarre pas manque souvent d'une bibliothèque : on la nomme."""
    exe = moteur.serveur_pret()
    if not exe or os.name == "nt":
        return ""
    import subprocess
    try:
        sortie = subprocess.run(["ldd", str(exe)], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    manquantes = [ligne.split("=>")[0].strip() for ligne in sortie.splitlines() if "not found" in ligne]
    glibc = platform.libc_ver()
    return (_t("Bibliothèques manquantes : {}. ").format(", ".join(manquantes)) if manquantes else "") + _t("glibc du système : {}.").format(" ".join(glibc))


def executer(options, moteur, ecrire=print, entree=input, chemin_rapport=None, maintenant=time.time):
    """Fait l'essai et rend le rapport (dictionnaire). `options` : modele (« auteur/depot/fichier.gguf »), modele_local, oui, sans_outils, ctx, modele_test."""
    rapport = Rapport(ecrire)

    def demande(question):
        return bool(options.get("oui")) or entree(question + " " + _t("[o/N] ")).strip().lower() in ("o", "oui", "y", "yes")

    def fin(arreter=True):
        if arreter:
            try:
                moteur.arreter()
            except Exception:  # noqa: BLE001
                pass
        resume = {"date": datetime.now().isoformat(timespec="seconds"), "systeme": "{} {}".format(platform.system(), platform.release()), "machine": platform.machine(), "python": platform.python_version(),
                  "moteur": moteur.id, "version_moteur": moteur.version(), "reussi": rapport.reussi(), "etapes": rapport.etapes}
        f = Path(chemin_rapport) if chemin_rapport else None
        if f is not None:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
            ecrire("\n" + _t("Rapport écrit : {}").format(f))
        if not rapport.reussi():
            ecrire("\n" + _t("✘ Quelque chose n'a pas fonctionné : joins le rapport ci-dessus (ou le fichier) à ton compte rendu."))
        elif rapport.avertissements():
            ecrire("\n" + _t("✔ L'essentiel fonctionne ; à regarder : {}.").format(", ".join(rapport.avertissements())))
        else:
            ecrire("\n" + _t("✔ Tout a fonctionné."))
        return resume

    # 1. la machine
    debut = maintenant()
    profil = (engines.CONTEXTE.get("profil_attendu") or engines.CONTEXTE["profil"])()          # la détection du matériel démarre en arrière-plan : on l'attend, le choix du programme en dépend
    from . import llamacpp_engine as _ml
    systeme = _ml._systeme()
    variante = (moteur.config().get("variante") if hasattr(moteur, "config") else None) or "auto"
    choisie = variante if variante in ("cuda", "vulkan", "cpu", "metal") else _ml.variante_auto(profil, systeme)
    rapport.etape(_t("Matériel détecté"), True, "{} {} · {} · {}".format(platform.system(), platform.machine(), profil.resume() if profil is not None else _t("matériel non détecté"), _t("version choisie : {}").format(choisie)), maintenant() - debut)

    # 2. le programme
    if moteur.serveur_pret() is None:
        if hasattr(moteur, "info_dossier"):
            info = moteur.info_dossier()
            if info["propose"] and not info["personnalise"] and demande(_t("Installer dans {} (à côté des modèles d'Ollama, {} Go libres) plutôt que dans le dossier de Lutin ({}) ?").format(info["propose"], info["libre_go"]["propose"], info["defaut"])):
                from . import llamacpp_engine as _m2
                _m2.regler_dossier(moteur.id, info["propose"])
                info = moteur.info_dossier()
            ecrire(_t("   Dossier d'installation : {} ({} Go libres)").format(info["actuel"], info["libre_go"]["actuel"]))
        if not demande(_t("Télécharger llama.cpp ({}), environ 25 à 700 Mo selon la carte graphique ?").format(choisie)):
            rapport.etape(_t("Installation de llama.cpp"), False, _t("refusée : rien n'a été téléchargé"))
            return fin(False)
        debut = maintenant()
        try:
            moteur.installer(barre_de_progression(ecrire))
            rapport.etape(_t("Installation de llama.cpp"), True, moteur.version(), maintenant() - debut)
        except (ValueError, OSError) as e:
            rapport.etape(_t("Installation de llama.cpp"), False, e, maintenant() - debut)
            return fin(False)
    else:
        rapport.etape(_t("Installation de llama.cpp"), True, _t("déjà présent ({})").format(moteur.version() or _t("version inconnue")))

    # 3. le modèle
    modele = options.get("modele_local") or ""
    choix = MODELE_TEST if options.get("modele_test") else (decouper_modele(options["modele"]) if options.get("modele") else None)
    if not modele:
        if choix is None:
            installes = moteur.modeles()["installes"]
            if not installes:
                rapport.etape(_t("Modèle"), False, _t("aucun modèle : relance avec --model {}/{} (2,5 Go, pense aux appels d'outils) ou --test-model (1 Mo, pour vérifier seulement)").format(*SUGGESTION))
                return fin(False)
            modele = installes[0]
        else:
            repo, fichier = choix
            nom_local = fichier.replace("/", "_")[:-5]
            if nom_local in moteur.modeles()["installes"]:
                modele = nom_local
                rapport.etape(_t("Modèle"), True, _t("déjà téléchargé : {}").format(modele))
            else:
                try:
                    taille = next((f["taille"] for f in moteur.fichiers_du_depot(repo) if f["fichier"] == fichier), 0)
                except ValueError as e:
                    rapport.etape(_t("Modèle"), False, e)
                    return fin(False)
                if not demande(_t("Télécharger {} / {} ({} Mo) ?").format(repo, fichier, taille // 1_000_000)):
                    rapport.etape(_t("Modèle"), False, _t("refusé : rien n'a été téléchargé"))
                    return fin(False)
                debut = maintenant()
                try:
                    modele = moteur.telecharger_modele(repo, fichier, barre_de_progression(ecrire))
                    rapport.etape(_t("Modèle"), True, "{} ({} Mo)".format(modele, taille // 1_000_000), maintenant() - debut)
                except (ValueError, OSError) as e:
                    rapport.etape(_t("Modèle"), False, e, maintenant() - debut)
                    return fin(False)
    else:
        rapport.etape(_t("Modèle"), modele in moteur.modeles()["installes"], _t("modèle local : {}").format(modele))
        if modele not in moteur.modeles()["installes"]:
            return fin(False)

    # 4. le démarrage
    ctx = int(options.get("ctx") or 8192)
    debut = maintenant()
    try:
        moteur.demarrer(modele, ctx)
        rapport.etape(_t("Démarrage du serveur"), True, _t("contexte {} jetons").format(ctx), maintenant() - debut)
    except (ValueError, OSError) as e:
        rapport.etape(_t("Démarrage du serveur"), False, "{} {}".format(e, diagnostic_linux(moteur)).strip(), maintenant() - debut)
        return fin()

    # 5. la santé
    debut = maintenant()
    try:
        liste = moteur._json("/models", None, 10).get("data") or []
        rapport.etape(_t("Le serveur répond (/v1/models)"), True, ", ".join(str(m.get("id")) for m in liste)[:200], maintenant() - debut)
    except Exception as e:  # noqa: BLE001
        rapport.etape(_t("Le serveur répond (/v1/models)"), False, e, maintenant() - debut)
        return fin()

    # 6. une conversation en flux
    debut = maintenant()
    corps = {"model": modele, "messages": [{"role": "user", "content": "Dis bonjour en une phrase."}], "options": {"num_ctx": ctx, "temperature": 0.2, "num_predict": 60}}
    premier, texte, final = None, "", {}
    try:
        with moteur.chat_flux(corps, 180) as flux:
            for e in flux:
                if e.get("error"):
                    raise ValueError(e["error"])
                m = e.get("message") or {}
                if (m.get("content") or m.get("thinking")) and premier is None:
                    premier = maintenant() - debut
                texte += m.get("content") or ""
                if e.get("done"):
                    final = e
        jetons, duree = int(final.get("eval_count") or 0), (final.get("eval_duration") or 0) / 1e9
        vitesse = "{:.1f} {}".format(jetons / duree, _t("jetons/s")) if jetons and duree else _t("vitesse inconnue")
        rapport.etape(_t("Conversation en flux"), bool(texte.strip()) or bool(jetons), "{} · {} {:.2f} s · « {} »".format(vitesse, _t("premier jeton"), premier or 0, " ".join(texte.split())[:80]), maintenant() - debut)
    except Exception as e:  # noqa: BLE001
        rapport.etape(_t("Conversation en flux"), False, e, maintenant() - debut)
        return fin()

    # 7. un appel d'outil
    if options.get("sans_outils") or options.get("modele_test"):
        rapport.etape(_t("Appel d'outil"), True, _t("non essayé (demandé)"), 0, avertissement=True)
    else:
        debut = maintenant()
        try:
            messages = [{"role": "user", "content": "Quelle heure est-il ? Utilise l'outil heure."}]
            appels = []
            with moteur.chat_flux({"model": modele, "messages": messages, "tools": [OUTIL_HEURE], "options": {"num_ctx": ctx, "temperature": 0.1, "num_predict": 120}}, 180) as flux:
                for e in flux:
                    appels += (e.get("message") or {}).get("tool_calls") or []
            if not any((a.get("function") or {}).get("name") == "heure" for a in appels):
                rapport.etape(_t("Appel d'outil"), False, _t("le modèle n'a pas appelé l'outil « heure » (certains modèles ou formats ne savent pas : essaie un autre modèle)"), maintenant() - debut, avertissement=True)
            else:
                messages += [{"role": "assistant", "content": "", "tool_calls": appels}, {"role": "tool", "tool_name": "heure", "content": "Il est 14 h 32."}]
                suite = ""
                with moteur.chat_flux({"model": modele, "messages": messages, "tools": [OUTIL_HEURE], "options": {"num_ctx": ctx, "temperature": 0.1, "num_predict": 80}}, 180) as flux:
                    for e in flux:
                        suite += (e.get("message") or {}).get("content") or ""
                ok = bool(re.search(r"14|32", suite))
                rapport.etape(_t("Appel d'outil"), ok, "{} « {} »".format(_t("appel reçu puis réponse"), " ".join(suite.split())[:80]), maintenant() - debut, avertissement=not ok)
        except Exception as e:  # noqa: BLE001
            rapport.etape(_t("Appel d'outil"), False, e, maintenant() - debut)

    # 8. l'arrêt
    debut = maintenant()
    moteur.arreter()
    arrete = moteur.en_memoire(modele) is None and not moteur.statut().get("actif")
    rapport.etape(_t("Arrêt du serveur"), arrete, "", maintenant() - debut)
    return fin(False)
