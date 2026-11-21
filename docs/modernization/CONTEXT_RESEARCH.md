# Keeping the context on small local models: what others do, what Lutin should take

Research of 2026-11-19, asked by the maintainer: how other open projects handle tokens, conversation history, summaries, prompts and tool use, whether
their mechanisms are better than Lutin's, and what Lutin should copy or do better. It feeds plan step 7 (review of the prompt and the tools), which the
maintainer placed first (2026-11-19).

Four studies were made, by reading the source code of the projects (each claim in them is marked as read in the code, in the docs, or not verified):

- coding agents: Aider, Cline (v3.35 and the new SDK), Roo Code, OpenAI Codex CLI, Google Gemini CLI, opencode, Goose, Continue;
- chat applications for local models: SillyTavern, Open WebUI, LibreChat, AnythingLLM, Jan, KoboldCpp, text-generation-webui, llama.cpp server,
  Ollama, Khoj;
- memory libraries and published research: mem0, LangChain/LangGraph/LangMem, LlamaIndex, Zep/Graphiti, A-MEM, MemoryOS, MemoryBank, cognee;
  « Lost in the Middle », context rot, recursive summarisation, LLMLingua, StreamingLLM, ACE, « The Complexity Trap », multi-turn instruction loss,
  Anthropic and Manus context engineering notes, BFCL, LongMemEval, LoCoMo;
- the earlier pre-analysis (AtomicAgent, Hermes, Letta, OpenHands, the9), checked against the current code.

The detailed reports are kept by the maintainer outside the repository. Only ideas are taken: every mechanism below is to be rewritten in the Python
standard library (Lutin has no runtime dependency). Licences seen: Apache-2.0 (Codex, Gemini CLI, Goose, Cline, Roo, Continue, Aider, Jan), MIT
(opencode, LibreChat, AnythingLLM, Ollama, llama.cpp), BSD-3 with a branding clause (Open WebUI since 0.6.6), AGPL-3.0 (SillyTavern, KoboldCpp,
text-generation-webui, Khoj). A prompt copied word for word needs its attribution.

## Where Lutin stands

Lutin already does several things the others do or recommend: a stable prefix with the changing block just before the last question (ADR 0013), the
first request kept word for word (ADR 0018), fewer tools on a small window, a structured progress sheet updated by a separate call, the archive of
what leaves the history with a `rappeler` tool, the automatic recall of the thread, a loop guard that compares results, skills loaded on demand,
paged reading of large files. The evaluation suite (`tests/test_evaluation.py`, ADR 0018 decision 10) measures what the request carries on 4,096
and 8,192 tokens.

What the evaluation and the studies show is weak:

1. **A summary every two or three answers** on 4,096 and 8,192 tokens (9 in 22 turns), each a model call of minutes on a processor. Open WebUI has
   the same defect (its issue 30035): the trigger is a token count, but a fixed share of the messages is kept, so the history stays near the
   threshold.
2. **The summary is a summary of the previous summary, in free prose.** With a weak model it lost the five decisions of the scenario. Measured
   elsewhere: a context rewritten as a whole collapses (ACE, arXiv 2510.04618: from 18,282 to 122 tokens, under the baseline); the systems that hold
   apply deltas merged by code (ACE, Factory's anchored summary, mem0 now add-only). Lutin's sheet works that way; its summary does not.
3. **Tool results are large for the window**: a result keeps up to about 9,000 characters (about 3,000 tokens, 73 % of a 4,096 window).
4. **The token count is an estimate** (characters / 3) never checked against the engine, and an overflow is silent with Ollama: past `num_ctx` it
   keeps the first `num_keep` tokens and the end, so the system message is lost (read in Ollama's code by the study of local applications).
5. **A question about the state of the work** (« où en est-on ? ») recalls nothing useful: the keyword index has no words to match.
6. **The requests of the person get lost in the middle**: on multi-turn instructions, models lose 39 % on average and over-weight the first and last
   turns; a recap at the end of the context recovers about half of the gap (arXiv 2505.06120).

## Proposals, in the recommended order

Each is to be measured before and after on `tests/test_evaluation.py` (calls to the model per ten exchanges, what is kept, the size of the request)
and, for the engine, on a real model (maintainer's decision: measure first).

### 1. Measure what the engine really reads (decided, plan task 2)

Log for each request the real prompt size and what came from the cache: `prompt_eval_count` and, on recent Ollama, `prompt_eval_cached_count`;
`timings.prompt_n` and `timings.cache_n` on llama-server. Use the real count to calibrate the characters-per-token ratio per model (keep / 3 until a
measure exists, raise a correction only on proof of under-estimate, as Cline caps it), and detect an overflow (real count far above the estimate).
Origin: Codex, opencode, LibreChat `calibrationRatio`, Cline. Cost: no call. This is the basis of 2, 4 and 6: without it their gain cannot be shown.

### 2. Bound tool results by the window

A result gets a share of the window (about 10 %), cut in the middle (start and end kept), with a header that says how much was cut and how to get the
rest (`rappeler`, or reading the file again); the full text goes to the archive. Once a turn is over, old results are replaced by one line (tool,
arguments, size) in one batch, so the prefix changes once and not at every answer; a file read twice keeps only the latest read. Origin: Codex
middle truncation, Roo, Gemini CLI tool output masking, opencode prune, Cline duplicate reads. Evidence: masking old observations matches an LLM
summary at about half the cost and does not lengthen the work, while summaries lengthen it by 13 to 15 % (« The Complexity Trap », arXiv 2508.21433);
Anthropic reports +29 % and −84 % tokens with tool result clearing (internal evaluation). Cost: no call, low complexity.

### 3. Compact without the model first, and come down far below the threshold

On 8,192 tokens or less, a compaction first works without any call: every message of the person kept (the oldest cut in the middle, within about
10 to 15 % of the window), the latest exchange whole, the final answer of older exchanges when it fits, and the rest replaced by a deterministic
note (tools called, files read and written, commands run); everything removed goes to the archive as today. The model is called only if that is not
enough. After a compaction the history comes down to a target (30 to 40 % of its room) chosen so that at least four exchanges of the measured size
fit before the next one. Origin: Cline basic compaction (its documentation does not trust small models with automatic summaries), Codex (only the
person's messages and a summary are kept), Cline 0.9 / 0.7 ratios, Gemini CLI (50 % / keeps 30 %), KoboldCpp smart context, LibreChat
`retainRecent`. Expected: compactions two to three times rarer, most of them free. Risk: nuances of old answers are lost; the archive, the recall and
the sheet cover them.

### 4. One structured memory updated by deltas, instead of a summary and a sheet

The sheet becomes the only long memory: the model returns changes in JSON (new decisions, step, done, open questions), the code applies them, a
decision is marked replaced rather than removed, an empty or invalid answer changes nothing. One call per compaction instead of a summary and regular
passes of the scribe. Ask for the JSON with a schema where the engine supports it (`format` with a JSON schema on Ollama 0.5 and later,
`json_schema` on llama.cpp), low temperature, fallback otherwise. Origin and evidence: ACE, Factory anchored summaries (3.70 against 3.44), mem0,
LlamaIndex (invalid output ignored), LibreChat checkpoint sections, opencode summary template. Cost: the largest change (an ADR replacing part of
ADR 0018); the largest gain on decisions kept by a weak model.

### 5. Ask the summary through the cached prefix, and prepare it while the person reads

When a model call is still needed, send the conversation exactly as the last request, then the instruction as a message of the person: the engine
only computes the instruction and the answer (Open WebUI when the summary model is the chat model; opencode). Better still, run it after the answer
is shown, while the person reads, and cancel it if a new message comes first. Origin: opencode background compaction, Aider summarize worker.
Risk: one model at a time on Ollama by default, hence the cancellation; to be measured with 1.

### 6. Recall: the right question, a threshold, few passages

A question about the state of the work is answered from the sheet, not by the keyword index. Otherwise the query is the question and the previous
message of the person (SillyTavern uses the last two messages, Open WebUI the last seven of the person); a passage is put back only above a score
threshold, three at most (a wrong but close passage harms the answer: Chroma's context rot study; Llama 8B degrades past about 3,000 retrieved
tokens). Keys of each archived turn are enriched with the words of the sheet (+9.4 % recall in LongMemEval). Cost: no call.

### 7. A recap of the person's requests before the last question

Without a model call: the requests of the person since the start (short, oldest filtered on instruction words, within a budget), placed in the block
of the turn. Evidence: arXiv 2505.06120 (multi-turn loss, recap recovers about half). Codex keeps every message of the person for the same reason.

### 8. Tools for small models (plan step 7)

- Check arguments against the schema and answer with an error the model can fix (today `lire` without a path reads « . »).
- Keep the set of tools fixed for a conversation (changing it empties the engine cache: Manus masks tools instead of removing them).
- Do not select tools per request: failures are documented around 46 tools, not at 14 (BFCL and related studies); short, non-overlapping
  descriptions matter more.
- When `/api/show` does not announce tools, describe them in the prompt and parse a JSON answer (AnythingLLM « UnTooled »), with examples.
- On 4,096 tokens, a one-line catalogue of the tools (name, arguments, purpose) with full schemas only for the few really needed (Cline `xs`
  variant, Goose tiny-model prompt).
- Widen the loop guard to repeated errors with different arguments and near-identical searches.

### 9. Evaluation

Extend `tests/test_evaluation.py`: a scenario rich in tools (results of several thousand characters), the number of internal model calls per thirty
turns, the length of the prefix shared by two consecutive requests (cache), decisions updated and replaced. Keep the hermetic suite on fake models; a
real small model goes in an opt-in suite (probes in the style of Factory, a small extract of LoCoMo whose CC BY-NC licence must be checked). A
recorder of the exact request of each turn (preanalysis) helps to replay a real conversation.

## Not to take

- Temporal knowledge graphs (Zep/Graphiti: five to seven model calls per message), evolving notes (A-MEM), LLMLingua (an auxiliary model), memory
  managed by the main model itself (MemGPT style: below the full-context baseline on 1 to 3B models).
- Two calls per summary (summary then check, Gemini CLI): double the cost on a processor.
- Budgets in absolute tokens designed for 128k to 1M windows: Lutin needs shares of the window.
- Changing `num_ctx` per request (reloads the model, empties the cache).

## Already decided by the maintainer (2026-11-19)

Measure the engine first (proposal 1); `CONTEXTE.md` bounded by the window (done, ADR 0018 decision 10); answer room of 15 % kept (`PART_MAX`);
summaries on small windows: study then propose (proposals 3 to 5 are that study's candidates); plan step 7 before the English pass.
