"""Measures proposal 8 of docs/modernization/CONTEXT_RESEARCH.md on real models of this machine's Ollama (ADR 0007: measure before changing).

Ways to give the model its tools, on the tool questions of the bench (`lutin.bench.CASES_TOOLS`) and the tools Lutin really sends on a 4,096-token
window (`agent.mode_tools`):

- native: the tools in the request (`tools`), what Lutin does today for a model whose /api/show announces them;
- text-full: no `tools`; their full schemas in the system prompt, the call written as <tool_call>{...}</tool_call> and read by
  `agent.extract_text_calls` (AnythingLLM « UnTooled »);
- text-line: the same, with a one-line catalogue (name, arguments, first sentence) instead of the schemas (Cline `xs`, Goose tiny prompt);
- json-full, json-line: the same two, the call written as a JSON object alone (no tag: see FORMAT_JSON).

A model without tools gets nothing from Lutin today (its answers are text only): every tool question fails for it, the two others pass.
Usage: LUTIN_HOME=<temporary folder> [VARIANTS=native,json-line] python tools/measure_tool_prompt.py <model> [<model>...]
(temperature 0, one run per question, 4,096 tokens).
"""
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("LUTIN_HOME", tempfile.mkdtemp(prefix="lutin-measure-"))
from lutin import core as _m  # noqa: E402,F401  (first: the modules below import it)
from lutin import agent, bench  # noqa: E402

OLLAMA = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")
NUM_CTX = 4096
EXAMPLE = {"name": "lire", "arguments": {"chemin": "src/app.py"}}
NO_TOOL = "Si aucun outil n'est utile (une question de culture générale, une salutation), réponds normalement en texte"
FORMAT = ("Pour appeler un outil, réponds UNIQUEMENT par une ligne de cette forme, sans autre texte :\n"
          "<tool_call>{\"name\": \"NOM_DE_L_OUTIL\", \"arguments\": {\"parametre\": \"valeur\"}}</tool_call>\n"
          + NO_TOOL + ", sans <tool_call>.\nExemple : pour lire le fichier src/app.py, réponds : <tool_call>" + json.dumps(EXAMPLE, ensure_ascii=False) + "</tool_call>")
# The same without the tag: on a model whose template has a tool parser (Qwen through Ollama), an answer that writes <tool_call> itself in a request
# without `tools` ends in « EOF » (measured on 2026-11-22). A JSON object alone is read by `extract_text_calls` too.
FORMAT_JSON = ("Pour appeler un outil, réponds UNIQUEMENT par un objet JSON de cette forme, sans autre texte :\n"
               "{\"name\": \"NOM_DE_L_OUTIL\", \"arguments\": {\"parametre\": \"valeur\"}}\n"
               + NO_TOOL + ", sans JSON.\nExemple : pour lire le fichier src/app.py, réponds : " + json.dumps(EXAMPLE, ensure_ascii=False))
VARIANTS = [v for v in os.environ.get("VARIANTS", "native,text-full,text-line,json-full,json-line").split(",") if v]


def tools_of_small_window():
    return agent.mode_tools({"mode": "polyvalent", "num_ctx": NUM_CTX, "web": True})


def full_catalogue(tools):
    return "Tu as ces outils (schémas JSON) :\n" + "\n".join(json.dumps(t["function"], ensure_ascii=False) for t in tools)


def line_catalogue(tools):
    lines = []
    for t in tools:
        f = t["function"]
        properties = (f.get("parameters") or {}).get("properties") or {}
        required = set((f.get("parameters") or {}).get("required") or [])
        arguments = ", ".join(name + ("" if name in required else "?") for name in properties)
        first = (f.get("description") or "").split(". ")[0].split("\n")[0][:110]
        lines.append("- {}({}) : {}".format(f["name"], arguments, first))
    return "Tu as ces outils :\n" + "\n".join(lines)


def system_prompt(variant, tools):
    if variant == "native":
        return ""
    catalogue = full_catalogue(tools) if variant.endswith("full") else line_catalogue(tools)
    return catalogue + "\n\n" + (FORMAT if variant.startswith("text") else FORMAT_JSON)


def ask(model, messages, tools=None):
    body = {"model": model, "messages": messages, "stream": False, "think": False, "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": 150}}
    if tools:
        body["tools"] = tools
    request = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as refused:
        return {"error": refused.read().decode("utf-8", "replace")[:200]}


def graded(answer, expected, pattern, names):
    message = answer.get("message") or {}
    calls = message.get("tool_calls") or []
    content = message.get("content") or ""
    if not calls:
        calls, _ = agent.extract_text_calls(content, names)
    if expected is None:
        return not calls and bool(bench.clean(content))
    if not calls:
        return False
    function = calls[0].get("function") or {}
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            arguments = {}
    return function.get("name") == expected and pattern in json.dumps(arguments or {}, ensure_ascii=False)


def measure(model, variant, tools):
    names = {t["function"]["name"] for t in tools}
    system = system_prompt(variant, tools)
    passed, prompt_tokens, failures = 0, [], []
    for question, expected, pattern in bench.CASES_TOOLS:
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": question}]
        answer = ask(model, messages, tools if variant == "native" else None)
        if answer.get("error"):
            return {"model": model, "variant": variant, "error": answer["error"]}
        prompt_tokens.append(int(answer.get("prompt_eval_count") or 0))
        if graded(answer, expected, pattern, names):
            passed += 1
        else:
            failures.append((question[:40], ((answer.get("message") or {}).get("content") or "")[:90]))
    return {"model": model, "variant": variant, "passed": passed, "of": len(bench.CASES_TOOLS), "prompt_tokens": max(prompt_tokens or [0]), "failures": failures}


def main(models):
    tools = tools_of_small_window()
    print("tools sent on {} tokens: {} ({})".format(NUM_CTX, len(tools), ", ".join(t["function"]["name"] for t in tools)))
    for model in models:
        for variant in VARIANTS:
            print(json.dumps(measure(model, variant, tools), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
