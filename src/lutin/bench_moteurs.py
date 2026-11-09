"""Le banc comparatif de moteurs et la recommandation de moteur.

Le banc (`lutin bench-engines`, bouton de la page) fait tourner le MÊME modèle (les modèles d'Ollama sont des fichiers GGUF que llama.cpp lit tels quels, sous les mêmes noms) sur chaque moteur
disponible, et mesure : le chargement à froid, le premier jeton, la vitesse d'écriture (jetons/s), la vitesse de lecture du texte envoyé, la mémoire prise (RAM, mémoire vidéo) et la stabilité
(réponses réussies sur plusieurs passes). Le résultat est un JSON lisible et partageable, sans chemin ni donnée personnelle. Il ne tourne jamais tout seul ; il est conservé et « à refaire » seulement
quand le matériel ou la version d'un moteur change.

La recommandation répond à « quel moteur pour cette machine ? » AVEC SA RAISON : d'après le banc quand il existe, sinon d'après des règles générales (marquées comme non mesurées). Elle ne télécharge rien.
Règle de fond : à performances proches (moins de 10 % d'écart), on garde le moteur le plus simple (Ollama) ; un autre n'est recommandé que s'il est nettement meilleur ET stable."""
import hashlib
import json
import re
import statistics
import threading
import time
from pathlib import Path

from . import estimation, moteurs
from .i18n import t as _t

VERSION = 1
PROMPT = "Écris un texte d'environ 150 mots sur la mer."
PASSES = {"rapide": 2, "approfondi": 5}
ECART_MINI = 0.10          # un moteur n'est recommandé contre le plus simple qu'au-dessus de ce gain
SIMPLE = "ollama"
MOTEURS_BANC = ("ollama", "llamacpp", "openai")          # « openai » : le serveur compatible OpenAI choisi (Colibri, LM Studio, ExLlamaV3…), seulement s'il est démarré


# --------------------------------------------------------------------------- mesure d'un moteur

def _compter(evenements, horloge):
    """Parcourt un flux et rend (jetons, durée d'écriture, premier jeton en s, fin) : chiffres du moteur quand il les donne, sinon comptés à l'horloge."""
    debut = horloge()
    premier, dernier, morceaux, fin = None, None, 0, {}
    for e in evenements:
        if e.get("error"):
            raise RuntimeError(str(e["error"]))
        m = e.get("message") or {}
        if m.get("content") or m.get("thinking"):
            if premier is None:
                premier = horloge()
            dernier = horloge()
            morceaux += 1
        if e.get("done"):
            fin = e
    if premier is None:
        raise RuntimeError(_t("aucun texte reçu"))
    jetons = int(fin.get("eval_count") or 0) or morceaux
    duree = (fin.get("eval_duration") or 0) / 1e9 or max(1e-6, dernier - premier)
    return {"jetons": jetons, "duree": duree, "premier": premier - debut, "lu": int(fin.get("prompt_eval_count") or 0), "duree_lecture": (fin.get("prompt_eval_duration") or 0) / 1e9}


def une_passe(moteur, modele, ctx, horloge=time.monotonic):
    corps = {"model": modele, "messages": [{"role": "user", "content": PROMPT}], "stream": True, "options": {"temperature": 0, "num_predict": 200, "num_ctx": ctx}}
    with moteur.chat_flux(corps, 300) as flux:
        return _compter(flux, horloge)


def mesurer(moteur, modele, mode="rapide", ctx=4096, horloge=time.monotonic, memoire=None, estime_go=None):
    """Mesure UN moteur avec UN modèle. Ne lève jamais : une panne est notée dans `erreurs` et `ok` vaut faux. `memoire()` rend {ram, vram} (octets) après les passes, ou None."""
    from .mesures_moteurs import nom_affiche
    r = {"id": moteur.id, "nom": nom_affiche(moteur), "modele": modele, "version": str(moteur.statut().get("version") or ""), "ok": False, "passes": 0, "erreurs": [], "charge_s": None, "premier_jeton_s": None,
         "tok_s": None, "lecture_tok_s": None, "ram": None, "vram": None}
    debut = horloge()
    try:
        froid = une_passe(moteur, modele, ctx, horloge)          # la première demande charge le modèle : son temps est le chargement à froid
        r["charge_s"] = round(horloge() - debut - froid["duree"], 1)
        r["passes"] += 1
    except Exception as e:  # noqa: BLE001  (une panne de moteur est un résultat du banc, pas une erreur du banc)
        r["erreurs"].append(str(e)[:200])
        return r
    vitesses, premiers, lectures = [], [], []
    for _ in range(PASSES.get(mode, PASSES["rapide"])):
        try:
            p = une_passe(moteur, modele, ctx, horloge)
        except Exception as e:  # noqa: BLE001
            r["erreurs"].append(str(e)[:200])
            continue
        r["passes"] += 1
        if p["jetons"] >= 5:
            vitesses.append(p["jetons"] / p["duree"])
        premiers.append(p["premier"])
        if p["lu"] >= 20 and p["duree_lecture"] > 0:
            lectures.append(p["lu"] / p["duree_lecture"])
    if vitesses:
        r["tok_s"] = round(statistics.median(vitesses), 1)
    if premiers:
        r["premier_jeton_s"] = round(statistics.median(premiers), 2)
    if lectures:
        r["lecture_tok_s"] = round(statistics.median(lectures))
    try:
        m = memoire() if memoire else None
    except Exception:  # noqa: BLE001
        m = None
    if m:
        r["ram"], r["vram"] = m.get("ram"), m.get("vram")
        if estime_go and (m.get("ram") or m.get("vram")):
            mesure = ((m.get("ram") or 0) + (m.get("vram") or 0)) / 1024 ** 3
            r["estimation"] = {"estime_go": estime_go, "mesure_go": round(mesure, 1), "ecart_pct": estimation.ecart(estime_go, mesure)}          # l'estimation d'avant chargement, comparée à ce qui est réellement pris
    r["ok"] = bool(vitesses) and not r["erreurs"]
    return r


def memoire_du_moteur(ident, modele):
    """Mémoire prise par ce moteur pour ce modèle, d'après ressources_chargees : {ram, vram}."""
    from . import ressources_chargees as rc
    if ident == "ollama":
        for c in rc.charges_ollama():
            if c["nom"] == modele:
                return {"ram": c["ram"], "vram": c["vram"]}
    elif ident == "llamacpp":
        for c in rc.charges_llamacpp():
            return {"ram": c["ram"], "vram": c["vram"]}
    return None


def liberer(autres, modele):
    """Avant de mesurer un moteur, on décharge les autres : la mémoire et la carte graphique sont à lui seul, la comparaison est juste.
    `modele` : un nom, ou {moteur: son modèle} (le même modèle porte un nom différent d'un moteur à l'autre)."""
    from . import ressources_chargees as rc
    for ident in autres:
        nom = modele.get(ident, "") if isinstance(modele, dict) else modele
        try:
            if ident == "ollama":
                rc.decharger("ollama:" + nom)
            elif ident == "llamacpp":
                rc.decharger("llamacpp")
        except ValueError:
            pass


# --------------------------------------------------------------------------- le banc complet, conservation, empreinte

GENERIQUES = {"instruct", "chat", "it", "latest", "gguf", "exl3", "exl2", "base", "hf", "ai"}
RE_QUANTIFICATION = re.compile(r"^(i?q\d.*|\d+(\.\d+)?bpw|f16|bf16|fp16|fp8|int[48]|mlx)$")
RE_TAILLE = re.compile(r"^\d+(\.\d+)?[bm]$")


def _jetons(nom):
    """Les mots d'un nom de modèle sans l'éditeur, la quantification ni l'extension : « qwen3:8b » -> {qwen3, 8b} ; « Qwen3-8B-Q4_K_M.gguf » -> {qwen3, 8b}."""
    nom = str(nom).lower().rsplit("/", 1)[-1]
    nom = re.sub(r"\.(gguf|safetensors)$", "", nom)
    mots = [m for m in re.split(r"[^a-z0-9.]+", nom) if m]
    return {m for m in mots if m not in GENERIQUES and not RE_QUANTIFICATION.match(m)}


def equivalent(modele, installes):
    """Le modèle d'un moteur qui correspond à `modele` : le même nom, sinon même famille et même taille d'après le nom (« qwen3:8b » ~ « Qwen3-8B-Q4_K_M »). None si rien ne correspond."""
    if modele in installes:
        return modele
    voulus = _jetons(modele)
    taille = {m for m in voulus if RE_TAILLE.match(m)}
    if not voulus or not taille:
        return None          # sans taille dans le nom on ne devine pas : un « qwen3 » seul peut être n'importe quelle taille
    candidats = [n for n in installes if voulus <= _jetons(n)]
    return min(candidats, key=lambda n: (len(n), n)) if candidats else None


def disponibles(modele):
    """Les moteurs qui peuvent faire tourner ce modèle (ou son équivalent) MAINTENANT : [(moteur, raison d'absence ou '', modèle à utiliser avec lui)] pour chaque moteur du banc."""
    sortie = []
    for ident in MOTEURS_BANC:
        mo = moteurs.MOTEURS.get(ident)
        if mo is None:
            continue
        try:
            statut = mo.statut()
            if ident == "openai" and not (mo.adresse() if hasattr(mo, "adresse") else ""):
                continue          # aucun serveur réglé : rien à comparer, rien à montrer
            m = mo.modeles()
        except Exception as e:  # noqa: BLE001
            sortie.append((mo, str(e)[:120], modele))
            continue
        propre = equivalent(modele, m.get("installes", []))
        if not statut.get("installe"):
            sortie.append((mo, _t("pas installé"), modele))
        elif ident == "openai" and not statut.get("actif"):
            sortie.append((mo, _t("pas démarré"), modele))
        elif propre is None:
            sortie.append((mo, _t("n'a ni ce modèle ni un équivalent"), modele))
        elif ident == "ollama" and not m.get("actif"):
            sortie.append((mo, _t("ne répond pas"), propre))
        else:
            sortie.append((mo, "", propre))
    return sortie


def empreinte(profil, versions):
    """Ce qui rend un résultat caduc : le matériel (processeur, mémoire, cartes) et la version de chaque moteur."""
    gpus = sorted("{}:{:g}".format(g.nom, g.vram_go) for g in (getattr(profil, "gpus", None) or []))
    base = {"cpu": getattr(profil, "cpu", ""), "ram": round(getattr(profil, "ram_go", 0)), "gpus": gpus, "moteurs": dict(sorted(versions.items()))}
    return hashlib.sha1(json.dumps(base, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def versions_actuelles():
    out = {}
    for ident in MOTEURS_BANC:
        mo = moteurs.MOTEURS.get(ident)
        if mo is not None:
            try:
                out[ident] = str(mo.statut().get("version") or "")
            except Exception:  # noqa: BLE001
                out[ident] = ""
    return out


def comparer(modele, mode="rapide", profil=None, ctx=4096, progression=None, horloge=time.monotonic, memoire=memoire_du_moteur, liberer_autres=liberer, date=None):
    """Compare les moteurs disponibles sur ce modèle. Renvoie le résultat complet (jamais d'exception). `progression(texte, i, n)`."""
    from .mesures_moteurs import nom_affiche
    dispo = disponibles(modele)
    pret = [(mo, propre) for mo, raison, propre in dispo if not raison]
    r = {"version": VERSION, "date": date or time.strftime("%Y-%m-%dT%H:%M:%S"), "modele": modele, "mode": mode, "machine": profil.resume() if profil else "", "ctx": ctx,
         "ignores": [{"id": mo.id, "nom": nom_affiche(mo), "raison": raison} for mo, raison, _ in dispo if raison], "moteurs": []}
    estime_go = None
    try:          # ce que l'estimation d'avant chargement annonçait pour ce modèle (comparé ensuite à la mesure)
        from . import moteur as _mo
        fiche = next((x for x in _mo._CATALOGUE["modeles"] if x["id"] == modele), None)
        if fiche and profil:
            estime_go = estimation.estimer(fiche, ctx, profil)["total_go"]
    except Exception:  # noqa: BLE001  (un plus)
        estime_go = None
    par_moteur = {mo.id: propre for mo, propre in pret}
    for i, (mo, propre) in enumerate(pret):
        if progression:
            progression(_t("Mesure de {}").format(nom_affiche(mo)), i, len(pret))
        if len(pret) > 1:
            liberer_autres([x.id for x, _ in pret if x.id != mo.id], par_moteur)
        r["moteurs"].append(mesurer(mo, propre, mode, ctx, horloge, lambda mo=mo, propre=propre: memoire(mo.id, propre), estime_go=estime_go))
    r["empreinte"] = empreinte(profil, {m["id"]: m["version"] for m in r["moteurs"]}) if profil else ""
    r["recommandation"] = recommander(profil, banc=r)
    return r


ETAT = {"en_cours": False, "etape": "", "erreur": ""}


VERROU_LANCEMENT = threading.Lock()


def lancer(modele, mode, dossier, profil, **options):
    """Lance la comparaison dans un fil (une seule à la fois). Le résultat est conservé dans `dossier`. Lève ValueError si une comparaison tourne déjà ou si le modèle n'est pas choisi."""
    if not modele:
        raise ValueError(_t("Aucun modèle à mesurer."))
    if mode not in PASSES:
        raise ValueError(_t("Mode inconnu."))
    dispo = disponibles(modele)
    if sum(1 for _, raison, _p in dispo if not raison) < 2:          # comparer, c'est être au moins deux : avec un seul moteur il n'y a rien à comparer
        from .mesures_moteurs import nom_affiche
        raise ValueError(_t("Pour comparer, il faut au moins deux moteurs prêts qui ont ce modèle ou un équivalent (même famille et même taille). Pour l'instant : {}").format(" ; ".join("{} : {}".format(nom_affiche(mo), raison or _t("prêt")) for mo, raison, _p in dispo) or "?"))
    with VERROU_LANCEMENT:          # vérifier puis réserver d'un seul geste : deux demandes simultanées ne lancent pas deux comparaisons
        if ETAT["en_cours"]:
            raise ValueError(_t("Une comparaison est déjà en cours."))
        ETAT.update(en_cours=True, etape=_t("démarrage…"), erreur="")

    def travail():
        try:
            r = comparer(modele, mode, profil, progression=lambda texte, i, n: ETAT.update(etape="{} ({}/{})".format(texte, i + 1, n)), **options)
            if r["moteurs"]:
                enregistrer(dossier, r)
            else:
                ETAT["erreur"] = _t("Aucun moteur ne peut faire tourner « {} » : {}").format(modele, " ; ".join("{} : {}".format(i["nom"], i["raison"]) for i in r["ignores"]) or "?")
        except Exception as e:  # noqa: BLE001  (l'échec est montré dans la page)
            ETAT["erreur"] = str(e)[:300]
        finally:
            ETAT.update(en_cours=False, etape="")
    threading.Thread(target=travail, daemon=True, name="bench-moteurs").start()


def vue(dossier, modele, profil, docker=False):
    """Ce que la page affiche : le dernier résultat pour ce modèle, s'il est à refaire, la recommandation (avec sa raison) et l'état d'une comparaison en cours."""
    from .mesures_moteurs import nom_affiche
    resultat = lire(dossier).get(modele)
    caduc = a_refaire(resultat, profil, versions_actuelles()) if resultat else False
    banc = resultat if resultat and not caduc else None
    try:
        dispo = disponibles(modele) if modele else []
    except Exception:  # noqa: BLE001  (un plus pour la page)
        dispo = []
    return {"modele": modele, "resultat": resultat, "a_refaire": caduc, "recommandation": recommander(profil, banc=banc, docker=docker, modele_installe=bool(modele)),
            "comparables": sum(1 for _, raison, _p in dispo if not raison), "disponibilite": [{"nom": nom_affiche(mo), "raison": raison, "modele": propre if not raison else ""} for mo, raison, propre in dispo],
            "en_cours": ETAT["en_cours"], "etape": ETAT["etape"], "erreur": ETAT["erreur"]}


def a_refaire(resultat, profil, versions):
    """Vrai si le matériel ou une version de moteur a changé depuis ce résultat (ou s'il n'y en a pas)."""
    if not resultat or not resultat.get("empreinte"):
        return True
    vues = {m["id"]: m["version"] for m in resultat.get("moteurs", [])}
    return resultat["empreinte"] != empreinte(profil, {k: versions.get(k, "") for k in vues})


def _fichier(dossier):
    return Path(dossier) / "bench_moteurs.json"


def lire(dossier):
    try:
        d = json.loads(_fichier(dossier).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def enregistrer(dossier, resultat):
    """Garde le dernier résultat de chaque modèle (le fichier reste petit)."""
    tout = lire(dossier)
    tout[resultat["modele"]] = resultat
    f = _fichier(dossier)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(tout, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def exporter(resultat):
    """Le résultat à partager : ni chemin ni nom d'utilisateur (la machine n'est décrite que par son matériel)."""
    return json.dumps({k: v for k, v in resultat.items() if k != "recommandation"}, ensure_ascii=False, indent=1)


def lisible(resultat):
    """Le résultat en quelques lignes de texte."""
    lignes = [_t("Modèle : {} · {} · {}").format(resultat["modele"], resultat.get("machine") or "?", resultat["mode"])]
    for m in resultat["moteurs"]:
        if m["ok"]:
            lignes.append(_t("  {} : {} jetons/s · premier jeton {} s · chargement {} s{}").format(m["nom"] + (" (" + m["modele"] + ")" if m.get("modele") and m["modele"] != resultat["modele"] else ""), m["tok_s"], m["premier_jeton_s"], m["charge_s"],
                                                                                              _t(" · mémoire vidéo {} Go").format(round(m["vram"] / 1024 ** 3, 1)) if m.get("vram") else ""))
        else:
            lignes.append(_t("  {} : échec ({})").format(m["nom"], (m["erreurs"] or ["?"])[0]))
    for i in resultat.get("ignores", []):
        lignes.append(_t("  {} : non mesuré ({})").format(i["nom"], i["raison"]))
    rec = resultat.get("recommandation")
    if rec:
        lignes.append(_t("Recommandation : {} — {}").format(rec["nom"], rec["raison"]))
    return "\n".join(lignes)


# --------------------------------------------------------------------------- la recommandation

def _nom(ident):
    mo = moteurs.MOTEURS.get(ident)
    return mo.nom if mo else ident


def _depuis_le_banc(banc):
    bons = [m for m in banc.get("moteurs", []) if m.get("ok") and m.get("tok_s")]
    if len(bons) < 2:
        return None
    simple = next((m for m in bons if m["id"] == SIMPLE), None)
    meilleur = max(bons, key=lambda m: m["tok_s"])
    if simple is None or meilleur["id"] == SIMPLE:
        choix, autre = meilleur, next((m for m in bons if m["id"] != meilleur["id"]), None)
        raison = _t("mesuré sur cette machine avec {} : {} jetons/s contre {} jetons/s").format(banc["modele"], choix["tok_s"], autre["tok_s"])
    elif meilleur["tok_s"] >= simple["tok_s"] * (1 + ECART_MINI):
        choix = meilleur
        raison = _t("mesuré sur cette machine avec {} : {} jetons/s contre {} jetons/s pour {} ({:+.0f} %)").format(banc["modele"], meilleur["tok_s"], simple["tok_s"], simple["nom"], 100 * (meilleur["tok_s"] / simple["tok_s"] - 1))
    else:
        choix = simple
        raison = _t("mesuré sur cette machine avec {} : écart sous {} % ({} contre {} jetons/s), on garde le plus simple").format(banc["modele"], round(ECART_MINI * 100), simple["tok_s"], meilleur["tok_s"])
    return {"moteur": choix["id"], "nom": choix["nom"], "raison": raison, "source": "banc", "theorique": False, "limites": [], "espace_go": None}


def recommander(profil, banc=None, docker=False, modele_installe=True):
    """{moteur, nom, raison, source (banc | regles), theorique, limites, espace_go} : le moteur conseillé pour cette machine et pourquoi. Le banc, s'il a comparé deux moteurs, prime.
    Sinon des règles générales, présentées comme telles (pas mesurées ici) : le banc est proposé pour trancher."""
    if banc:
        r = _depuis_le_banc(banc)
        if r:
            return r
    theorique = not modele_installe
    prefixe = _t("règle générale (pas encore mesuré ici) : ")
    gpu = profil.gpu_principal() if profil else None
    if gpu and gpu.fabricant == "nvidia" and gpu.vram_go >= 6:
        return {"moteur": SIMPLE, "nom": _nom(SIMPLE), "source": "regles", "theorique": theorique, "espace_go": 4,
                "limites": [_t("llama.cpp (CUDA) peut être un peu plus rapide, surtout avec les modèles à experts : lance le banc pour le savoir sur ta machine"),
                            _t("ExLlamaV3 (Réglages > Moteur) peut être encore plus rapide avec des modèles EXL3 très compressés : installe-le puis mesure-le")],
                "raison": prefixe + _t("carte NVIDIA avec {} Go : Ollama l'utilise très bien et reste le plus simple").format(round(gpu.vram_go))}
    if gpu and gpu.fabricant in ("amd", "intel") and gpu.vram_go >= 6:
        return {"moteur": "llamacpp", "nom": _nom("llamacpp"), "source": "regles", "theorique": theorique, "espace_go": 1,
                "limites": [_t("Ollama peut aussi utiliser cette carte selon le pilote : lance le banc pour comparer")],
                "raison": prefixe + _t("carte {} : llama.cpp (Vulkan) la prend en charge sur toutes les machines, avec un programme léger").format(gpu.fabricant.upper())}
    if profil and getattr(profil, "gpus_integrees", None) and profil.gpus_integrees():
        return {"moteur": SIMPLE, "nom": _nom(SIMPLE), "source": "regles", "theorique": theorique, "espace_go": 4,
                "limites": [_t("une carte intégrée peut accélérer llama.cpp (Vulkan) ou non selon le processeur : lance le banc pour trancher")],
                "raison": prefixe + _t("carte graphique intégrée au processeur : les deux moteurs tournent surtout sur le processeur, on garde le plus simple")}
    return {"moteur": SIMPLE, "nom": _nom(SIMPLE), "source": "regles", "theorique": theorique, "espace_go": 4,
            "limites": [_t("sans carte graphique, tout dépend de la mémoire vive et des cœurs : les modèles de 7 à 8 milliards de paramètres sont lents")],
            "raison": prefixe + _t("pas de carte graphique utilisable : Ollama est le plus simple, llama.cpp donne des résultats voisins")}
