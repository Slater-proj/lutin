"""Moteur « compatible OpenAI » : llama.cpp server, LM Studio, vLLM, Strata… tout serveur qui parle `/v1/chat/completions`.

Lutin garde en interne le format d'Ollama (messages, outils, flux d'évènements). Ce module traduit à la frontière :
  - la demande : messages (appels d'outils avec leur identifiant, images en data-URL), options (température, top_p…) et outils ;
  - la réponse en flux (SSE) : texte, réflexion (`reasoning_content`), appels d'outils reconstitués morceau par morceau, comptes de jetons et durées ;
  - la réponse d'un coup.
Il ne sait rien de l'installation d'un serveur : voir moteur_llamacpp.py. Aucune dépendance."""
import json
import re
import urllib.error
import urllib.request

from . import moteurs
from .i18n import t as _t


def type_image(base64_texte):
    """Le type MIME d'une image d'après les premiers caractères de son contenu en base 64."""
    debut = str(base64_texte)[:12]
    if debut.startswith("iVBOR"):
        return "image/png"
    if debut.startswith("/9j/"):
        return "image/jpeg"
    if debut.startswith("R0lG"):
        return "image/gif"
    if debut.startswith("UklG"):
        return "image/webp"
    return "image/png"


def vers_openai(corps):
    """Le corps d'une demande de chat au format d'Ollama -> le corps de `/v1/chat/completions`."""
    messages, en_attente, compteur = [], [], 0
    for m in corps.get("messages") or []:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            appels = []
            for a in m["tool_calls"]:
                f = a.get("function") or {}
                compteur += 1
                ident = a.get("id") or "call_%d" % compteur
                en_attente.append((ident, f.get("name", "")))
                args = f.get("arguments")
                appels.append({"id": ident, "type": "function", "function": {"name": f.get("name", ""), "arguments": args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)}})
            messages.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": appels})
        elif role == "tool":
            if en_attente:
                ident, _ = en_attente.pop(0)
                messages.append({"role": "tool", "tool_call_id": ident, "content": str(m.get("content") or "")})
            else:          # un résultat dont l'appel n'est plus dans la conversation (début élagué) : le serveur le refuserait, on le garde comme texte
                messages.append({"role": "user", "content": "[{} : {}]".format(m.get("tool_name") or "outil", str(m.get("content") or "")[:4000])})
        elif m.get("images") and role == "user":
            parties = [{"type": "text", "text": m.get("content") or ""}]
            parties += [{"type": "image_url", "image_url": {"url": "data:{};base64,{}".format(type_image(i), i)}} for i in m["images"]]
            messages.append({"role": "user", "content": parties})
        else:
            messages.append({"role": role or "user", "content": m.get("content") or ""})
    options = corps.get("options") or {}
    flux = bool(corps.get("stream", True))
    sortie = {"model": corps.get("model", ""), "messages": messages, "stream": flux}
    for source, cible in (("temperature", "temperature"), ("top_p", "top_p"), ("top_k", "top_k"), ("min_p", "min_p"), ("repeat_penalty", "repeat_penalty"), ("seed", "seed")):
        if options.get(source) is not None:
            sortie[cible] = options[source]
    if int(options.get("num_predict") or 0) > 0:
        sortie["max_tokens"] = int(options["num_predict"])
    if corps.get("tools"):
        sortie["tools"] = corps["tools"]
    if corps.get("format") == "json":
        sortie["response_format"] = {"type": "json_object"}
    if flux:
        sortie["stream_options"] = {"include_usage": True}
    return sortie


def arguments_json(texte):
    """Les arguments d'un appel d'outil (texte JSON, parfois mal fermé) -> dictionnaire ({} si illisible)."""
    if isinstance(texte, dict):
        return texte
    texte = str(texte or "").strip()
    if not texte:
        return {}
    for essai in (texte, re.sub(r",\s*([}\]])", r"\1", texte), texte + "}"):
        try:
            valeur = json.loads(essai)
            return valeur if isinstance(valeur, dict) else {}
        except ValueError:
            continue
    return {}


def comptes(usage, timings):
    """Les chiffres de fin de réponse au format d'Ollama (jetons lus et écrits, durées en nanosecondes) d'après `usage` (OpenAI) et `timings` (llama.cpp)."""
    usage, timings = usage or {}, timings or {}
    sortie = {"prompt_eval_count": int(usage.get("prompt_tokens") or timings.get("prompt_n") or 0), "eval_count": int(usage.get("completion_tokens") or timings.get("predicted_n") or 0)}
    if timings.get("predicted_ms"):
        sortie["eval_duration"] = int(float(timings["predicted_ms"]) * 1e6)
    if timings.get("prompt_ms"):
        sortie["prompt_eval_duration"] = int(float(timings["prompt_ms"]) * 1e6)
    if sortie.get("eval_duration") or sortie.get("prompt_eval_duration"):
        sortie["total_duration"] = sortie.get("eval_duration", 0) + sortie.get("prompt_eval_duration", 0)
    return sortie


def depuis_openai_complet(rep):
    """La réponse d'un coup de `/v1/chat/completions` -> {message, done, …} au format d'Ollama."""
    choix = (rep.get("choices") or [{}])[0]
    m = choix.get("message") or {}
    message = {"role": "assistant", "content": m.get("content") or ""}
    raisonnement = m.get("reasoning_content") or m.get("reasoning")
    if raisonnement:
        message["thinking"] = raisonnement
    if m.get("tool_calls"):
        message["tool_calls"] = [{"function": {"name": (a.get("function") or {}).get("name", ""), "arguments": arguments_json((a.get("function") or {}).get("arguments"))}} for a in m["tool_calls"]]
    return dict({"message": message, "done": True, "done_reason": choix.get("finish_reason") or "stop"}, **comptes(rep.get("usage"), rep.get("timings")))


class FluxOpenAI:
    """Les évènements d'une réponse en flux (SSE), traduits au format d'Ollama. Fermer le gestionnaire ferme la connexion : le serveur arrête de générer."""

    def __init__(self, reponse):
        self.reponse = reponse

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.reponse.close()
        return False

    def __iter__(self):
        appels, fin, usage, timings = {}, "", None, None
        for brut in self.reponse:
            ligne = brut.decode("utf-8", "replace").strip() if isinstance(brut, (bytes, bytearray)) else str(brut).strip()
            if not ligne.startswith("data:"):
                continue
            charge = ligne[5:].strip()
            if charge == "[DONE]":
                break
            try:
                e = json.loads(charge)
            except ValueError:
                continue
            if e.get("error"):
                erreur = e["error"]
                yield {"error": str(erreur.get("message") if isinstance(erreur, dict) else erreur)}
                return
            usage = e.get("usage") or usage
            timings = e.get("timings") or timings
            for choix in e.get("choices") or []:
                d = choix.get("delta") or {}
                if d.get("reasoning_content") or d.get("reasoning"):
                    yield {"message": {"role": "assistant", "thinking": d.get("reasoning_content") or d.get("reasoning")}, "done": False}
                if d.get("content"):
                    yield {"message": {"role": "assistant", "content": d["content"]}, "done": False}
                for a in d.get("tool_calls") or []:
                    f = a.get("function") or {}
                    cumul = appels.setdefault(a.get("index", len(appels)), {"name": "", "arguments": ""})
                    cumul["name"] = f.get("name") or cumul["name"]
                    cumul["arguments"] += f.get("arguments") or ""
                fin = choix.get("finish_reason") or fin
        if appels:
            yield {"message": {"role": "assistant", "tool_calls": [{"function": {"name": a["name"], "arguments": arguments_json(a["arguments"])}} for _, a in sorted(appels.items())]}, "done": False}
        yield dict({"done": True, "done_reason": "stop" if fin in ("", "tool_calls") else fin}, **comptes(usage, timings))


class MoteurOpenAI(moteurs.Moteur):
    """La conversation avec un serveur compatible OpenAI. Les sous-classes disent où il est (`adresse`) et comment s'identifier (`cle`) ; elles gèrent aussi son installation si elles le peuvent."""
    genre = "openai"

    def adresse(self):
        """L'adresse de base, finissant par /v1 (« http://127.0.0.1:8080/v1 »), ou « » si elle n'est pas connue."""
        return ""

    def cle(self):
        return ""

    def _requete(self, chemin, corps=None, delai=10, flux=False):
        base = self.adresse().rstrip("/")
        if not base:
            raise urllib.error.URLError(_t("aucune adresse pour ce moteur"))
        if moteurs.CONTEXTE["hors_ligne"]() and not moteurs.est_local(base):
            raise urllib.error.URLError(_t("mode hors ligne : ce moteur distant n'est pas joint"))
        entetes = {"Content-Type": "application/json"}
        if self.cle():
            entetes["Authorization"] = "Bearer " + self.cle()
        req = urllib.request.Request(base + chemin, data=None if corps is None else json.dumps(corps).encode("utf-8"), headers=entetes, method="GET" if corps is None else "POST")
        return urllib.request.urlopen(req, timeout=delai)

    def _json(self, chemin, corps=None, delai=10):
        with self._requete(chemin, corps, delai) as r:
            return json.loads(r.read().decode("utf-8"))

    def actif(self):
        try:
            self._json("/models", None, 3)
            return True
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def modeles(self):
        try:
            donnees = self._json("/models", None, 5).get("data") or []
        except (urllib.error.URLError, OSError, ValueError):
            return {"actif": False, "installes": [], "tailles": {}}
        noms = [str(m.get("id")) for m in donnees if m.get("id")]
        return {"actif": True, "installes": noms, "tailles": {str(m["id"]): int((m.get("meta") or {}).get("size") or 0) for m in donnees if m.get("id") and (m.get("meta") or {}).get("size")}}

    def en_memoire(self, modele):
        """Un serveur de ce genre tient son modèle chargé : s'il répond, il est prêt (aucun « chargement » à annoncer)."""
        return {"taille": 0, "vram": 0} if self.actif() else None

    def vecteurs(self, modele, textes, delai=60):
        """Les vecteurs de ces textes par `/v1/embeddings` (le serveur doit avoir été lancé avec un modèle d'embeddings)."""
        rep = self._json("/embeddings", {"model": modele, "input": list(textes)}, delai)
        donnees = sorted((d for d in (rep.get("data") or []) if isinstance(d, dict)), key=lambda d: d.get("index", 0))
        if len(donnees) != len(textes) or not all(isinstance(d.get("embedding"), list) and d["embedding"] for d in donnees):
            raise ValueError(_t("Réponse d'embeddings inattendue."))
        return [d["embedding"] for d in donnees]

    def chat(self, corps, delai=60):
        return depuis_openai_complet(self._json("/chat/completions", vers_openai(dict(corps, stream=False)), delai))

    def chat_flux(self, corps, delai=900):
        return FluxOpenAI(self._requete("/chat/completions", vers_openai(dict(corps, stream=True)), delai, True))
