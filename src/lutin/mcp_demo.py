"""Serveur MCP de démonstration (stdio), pour essayer les connecteurs sans rien installer : `python -m lutin.mcp_demo`.

Trois outils : « heure » (lecture seule), « additionner » (lecture seule) et « noter » (écrit une ligne dans un fichier : il modifie quelque chose, donc il demande ton accord)."""
import json
import os
import sys
import time
from pathlib import Path

OUTILS = [
    {"name": "heure", "description": "Donne la date et l'heure du serveur.", "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}},
    {"name": "additionner", "description": "Additionne deux nombres.", "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "noter", "description": "Ajoute une ligne de texte dans le fichier de notes de démonstration.", "inputSchema": {"type": "object", "properties": {"texte": {"type": "string"}}, "required": ["texte"]},
     "annotations": {"readOnlyHint": False}},
]


def appeler(nom, args):
    if nom == "heure":
        return time.strftime("%Y-%m-%d %H:%M:%S")
    if nom == "additionner":
        return str(float(args["a"]) + float(args["b"]))
    if nom == "noter":
        f = Path(os.environ.get("LUTIN_DEMO_FICHIER") or Path.home() / "lutin-mcp-demo.txt")
        with open(f, "a", encoding="utf-8") as h:
            h.write(str(args.get("texte", "")) + "\n")
        return "Noté dans " + str(f)
    raise KeyError(nom)


def repondre(message):
    methode, ident = message.get("method"), message.get("id")
    if ident is None:
        return None          # notification
    if methode == "initialize":
        return {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "lutin-demo", "version": "1"}}
    if methode == "ping":
        return {}
    if methode == "tools/list":
        return {"tools": OUTILS}
    if methode == "tools/call":
        p = message.get("params") or {}
        try:
            return {"content": [{"type": "text", "text": appeler(p.get("name"), p.get("arguments") or {})}]}
        except (KeyError, ValueError, TypeError) as e:
            return {"content": [{"type": "text", "text": "Erreur : " + str(e)}], "isError": True}
    return {"__erreur__": "méthode inconnue : " + str(methode)}


def principal():
    for ligne in sys.stdin:
        try:
            message = json.loads(ligne)
        except ValueError:
            continue
        r = repondre(message)
        if r is None:
            continue
        if "__erreur__" in r:
            sortie = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": r["__erreur__"]}}
        else:
            sortie = {"jsonrpc": "2.0", "id": message["id"], "result": r}
        sys.stdout.write(json.dumps(sortie) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    principal()
