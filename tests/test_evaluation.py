"""Reduced evaluation suite (plan step 6, ADR 0018 « Not done yet »): does a long conversation keep its thread on a small window?

    python tests/test_evaluation.py

A project of twenty exchanges (an objective, five decisions spread over the conversation, a current step), then « Où en est-on ? », then a precise
question. Run on 4,096 and 8,192 tokens with the progress sheet, the one memory of a long conversation since ADR 0019 (the summary mode was
measured here before it was retired: 9 summaries in 22 turns, 0 to 1 decision of 5 kept with a weak model), and with two fake models:

- « faithful » does what its instructions ask: the scribe notes every decision and the current step;
- « weak » loses the details, like a small model: a scribe that writes nothing.

The fake engine of tests/test_moteur.py answers; no real model is needed. What is measured is what the request of the last turns puts in front of the
model (and where: history, summary, sheet, recalled extracts), not whether a real model then answers well: that needs a real small model (see the
report at the end of the run, and ADR 0018). Set LUTIN_EVAL_REPORT=<file> to keep the report.
"""
import json
import os
import re
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_moteur as M  # noqa: E402  (starts the fake engine and the assistant, as in test_moteur.py)

A = M.A
from lutin import agent as AG  # noqa: E402

OBJECTIVE = ("Objectif : écrire convertir.py, un outil qui transforme les relevés CSV de la station météo de Marly en JSON pour le tableau de bord "
             "du club.")
# turn (1-based user message) -> (sentence said by the person, words that prove it reached the model)
FACTS = {
    3: ("Décision : le séparateur des fichiers CSV est le point-virgule.", "point-virgule"),
    6: ("Décision : les dates sortent au format ISO 8601.", "ISO 8601"),
    10: ("Décision : une ligne invalide est écrite dans rejets.log, jamais ignorée en silence.", "rejets.log"),
    14: ("Décision : le fichier de sortie s'appelle releves.json.", "releves.json"),
    18: ("Décision : les températures sont arrondies au dixième de degré.", "arrondies au dixième"),
}
STEP = ("Étape suivante : écrire les tests unitaires de la lecture des dates.", "tests unitaires de la lecture")
TURNS = 20
CORE = {"lire", "ecrire", "modifier", "chercher", "executer", "rappeler", "memoriser"}
WHERE_ARE_WE = "Où en est-on ?"
PRECISE = "Quel séparateur avait-on choisi pour les fichiers CSV ?"

SYLLABLES = "ba co di fu ga he ji ko lu ma ne pi qo ru sa te vi wo xu zy bra cle dro fri glu pla tri sto vra mon".split()


def filler(seed, count):
    """Deterministic text that holds none of the facts, made of words built from syllables: two answers share few words, as two real answers on
    different points would (with a small vocabulary, Lutin rightly took them for a model repeating itself)."""
    out, x = [], seed * 7919 + 17
    for _ in range(count):
        x = (x * 1103515245 + 12345) % 2 ** 31
        out.append("".join(SYLLABLES[(x >> s) % len(SYLLABLES)] for s in (0, 5, 10)[:2 + x % 2]))
    return " ".join(out)


def user_message(turn):
    if turn == 1:
        return OBJECTIVE + " " + filler(turn, 25) + "."
    if turn in FACTS:
        return FACTS[turn][0] + " " + filler(turn, 35) + "."
    if turn == TURNS:
        return STEP[0] + " " + filler(turn, 20) + "."
    return "Point " + str(turn) + " : " + filler(turn, 45) + " ?"


def assistant_message(turn):
    return "Réponse " + str(turn) + ". " + filler(1000 + turn, 190) + "."


def extract(text):
    """What a faithful small task model keeps of a text: the objective, the decisions, the latest step (sentence by sentence)."""
    objective = re.findall(r"Objectif : [^.]*\.[^.]*\.", text)
    decisions = list(dict.fromkeys(re.findall(r"Décision : [^.]*\.(?:json\.|log[^.]*\.)?", text)))
    steps = re.findall(r"Étape suivante : [^.]*\.", text)
    return objective[:1], decisions, steps[-1:]


class FakeModel:
    """Answers the request it is sent: the summary, the scribe and the first fill of the sheet by their instructions, the turn by REPLY."""

    def __init__(self, faithful):
        self.faithful = faithful
        self.reply = ""
        self.calls = {"turn": 0, "summary": 0, "scribe": 0, "sheet": 0, "other": 0}

    def __call__(self, body):
        if body.get("stream", True):
            self.calls["turn"] += 1
            return [{"content": self.reply}]
        msgs = body.get("messages", [])
        system = msgs[0].get("content", "") if msgs and msgs[0].get("role") == "system" else ""
        text = "\n".join(str(m.get("content", "")) for m in msgs[1:])
        objective, decisions, steps = extract(text)
        if system.startswith("Tu résumes"):
            self.calls["summary"] += 1
            return [{"content": " ".join(objective + decisions + steps) if self.faithful else "On travaille sur un outil de conversion."}]
        if system.startswith("Tu tiens la fiche"):
            self.calls["scribe"] += 1
            ops = {"decisions": [d.removeprefix("Décision : ") for d in decisions], "etape": steps} if self.faithful else {}
            return [{"content": json.dumps(ops, ensure_ascii=False)}]
        if system.startswith("Tu remplis la fiche"):
            self.calls["sheet"] += 1
            ops = {"objectif": objective, "decisions": [d.removeprefix("Décision : ") for d in decisions], "etape": steps} if self.faithful else {}
            return [{"content": json.dumps(ops, ensure_ascii=False)}]
        self.calls["other"] += 1
        return [{"content": "{}" if body.get("format") == "json" else ""}]


def source_of(message):
    """Where a message of the request comes from."""
    content = str(message.get("content", ""))
    if message.get("role") == "system":
        return "system"
    for prefix, name in (("[Résumé", "summary"), ("[Demande de départ]", "first request"), ("[Fiche de suivi", "sheet"), ("[Extraits", "recall")):
        if content.startswith(prefix) or prefix + " " in content[:60]:
            return name
    return "history"


def seen(request, words):
    """The places of the request where these words are, or [] if the model does not see them."""
    return sorted({source_of(m) for m in request["messages"] if words in str(m.get("content", ""))})


REPORT = []


class LongConversationOnSmallWindow(unittest.TestCase):
    """ADR 0018: the thread of a long project on a small window, measured on what the request carries."""

    def run_project(self, num_ctx, memory, faithful):
        model = FakeModel(faithful)
        M.REPONDEUR[:] = [model]
        A.save_settings({"num_ctx": num_ctx, "modele": "qwen3.8:27b", "mode": "polyvalent", "reflexion": False, "auto_ecriture": False,
                                "memoire_longue": memory, "fiche_scribe": True})
        cid, errors, prunes = "", [], 0
        try:
            for turn in range(1, TURNS + 3):
                message = user_message(turn) if turn <= TURNS else (WHERE_ARE_WE if turn == TURNS + 1 else PRECISE)
                model.reply = assistant_message(turn)
                M.RECUES.clear()
                events = M.chat(message, conversation=cid)
                cid = cid or next(e["conversation"] for e in events if e["type"] == "debut")
                errors += [(turn, e.get("texte", "")) for e in events if e["type"] == "erreur"]
                prunes += sum(1 for e in events if e["type"] == "info" and "sortent du contexte" in e.get("texte", ""))          # the start removed in one block (sheet mode)
                turns = [b for b in M.RECUES if b.get("stream", True)]
                self.assertTrue(turns, "turn %d reached the model" % turn)
                if turn == TURNS + 1:
                    where = turns[-1]
                elif turn == TURNS + 2:
                    precise = turns[-1]
            model.calls["prune"] = prunes
            return model, where, precise, errors
        finally:
            M.REPONDEUR.clear()
            if cid:
                M.post("/api/supprimer", {"id": cid})

    def measure(self, num_ctx, memory, faithful):
        model, where, precise, errors = self.run_project(num_ctx, memory, faithful)
        label = "%d %s %s" % (num_ctx, memory, "faithful" if faithful else "weak")
        size = A.estimate(where["messages"]) + len(json.dumps(where.get("tools", []), ensure_ascii=False)) // 3
        row = {"case": label, "size": size, "objective": seen(where, "station météo de Marly"), "step": seen(where, STEP[1]),
               "decisions": {turn: seen(where, words) for turn, (_, words) in FACTS.items()},
               "separator_on_precise_question": seen(precise, FACTS[3][1]), "calls": model.calls, "errors": errors,
               "tools": sorted(t["function"]["name"] for t in where.get("tools", []))}
        REPORT.append(row)
        self.assertEqual(errors, [], label + ": no turn fails")
        # Lutin's own estimate, under the ceiling of the request: the answer keeps its room. Checking only the window let the sheet and the extracts
        # push the request to 95 % of 4,096 tokens, and the fake engine (which counts a little more) refused a turn on the CI only.
        self.assertLessEqual(size, int(num_ctx * AG.MAX_SHARE), label + ": the request stays under its ceiling (ADR 0018, decision 10)")
        self.assertTrue(row["objective"], label + ": the first request is still in front of the model (ADR 0018, decision 2)")
        self.assertTrue(row["step"], label + ": the latest step is in front of the model")
        if num_ctx >= 8192:          # on 4,096 tokens, the floor of the history cannot hold the summary, the extracts and an answer of 190 words: the recall brings it back
            self.assertIn("history", row["step"], label + ": the latest exchange is sent as it is (the floor of the history, ADR 0018 decision 6)")
        # ADR 0019, decision 2: the start leaves far enough (9 removals in 22 turns before, each a new prefix for the engine)
        self.assertLessEqual(model.calls["prune"], 6, label + ": the start does not leave at every other exchange")
        self.assertEqual(model.calls["summary"], 0, label + ": no summary is asked of the model (ADR 0019, decision 1)")
        if num_ctx <= 4096:          # the scribe keeps the sheet: its tool (240 tokens) leaves its room to the conversation (ADR 0019)
            self.assertEqual(set(row["tools"]), CORE, label + ": only the core of tools (ADR 0018, decision 9)")
        return row

    def test_faithful_model_keeps_every_decision(self):
        """With a sheet kept as asked, every decision is in front of the model when the person asks where the project is."""
        for num_ctx in (4096, 8192):
            for memory in ("fichier",):
                with self.subTest(num_ctx=num_ctx, memory=memory):
                    row = self.measure(num_ctx, memory, True)
                    lost = [turn for turn, where in row["decisions"].items() if not where]
                    self.assertEqual(lost, [], "%d %s: decisions of turns %s are lost" % (num_ctx, memory, lost))
                    self.assertTrue(row["calls"]["scribe"], "the memory of the long conversation did work")

    def test_weak_model_finds_a_lost_decision_back_when_asked_precisely(self):
        """With a sheet that keeps nothing, a precise question brings the decision back from the start of the conversation (ADR 0018, decision 3:
        the recall of the thread starts as soon as the history overflows)."""
        for num_ctx in (4096, 8192):
            for memory in ("fichier",):
                with self.subTest(num_ctx=num_ctx, memory=memory):
                    row = self.measure(num_ctx, memory, False)
                    found = row["separator_on_precise_question"]
                    self.assertTrue(found, "%d %s: the separator decided at turn 3 is in front of the model" % (num_ctx, memory))


def write_report():
    lines = ["Evaluation: a project of %d exchanges, then « %s » (decisions said at turns %s)." % (TURNS, WHERE_ARE_WE, ", ".join(map(str, FACTS)))]
    for row in REPORT:
        kept = sum(1 for where in row["decisions"].values() if where)
        lines.append("- %s: request %d tokens; objective %s; decisions kept %d/%d %s; step %s; precise question: separator %s; calls %s%s" % (
            row["case"], row["size"], row["objective"] or "LOST", kept, len(FACTS),
            {t: w or "LOST" for t, w in row["decisions"].items()}, row["step"] or "LOST", row["separator_on_precise_question"] or "LOST",
            {k: v for k, v in row["calls"].items() if v}, ("; errors %s" % row["errors"]) if row["errors"] else ""))
    lines.append("Not measured here: whether a real small model answers well with what it is given (no real model in the tests).")
    text = "\n".join(lines)
    print(text, file=sys.stderr)
    if os.environ.get("LUTIN_EVAL_REPORT"):
        Path(os.environ["LUTIN_EVAL_REPORT"]).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    write_report()
    shutil.rmtree(M.TEMP, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)
