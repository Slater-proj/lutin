# ADR 0007 — Language of tool names and system prompts: measure before switching

- Status: Accepted (measurement not done yet)
- Date: 2026-11-11
- Deciders: maintainer (validated after the Phase A audit)

## Context

The tools offered to the models have French names (`lire`, `ecrire`, `executer`, `chercher`…), and so do their parameters and descriptions.
The system instructions exist in both languages (`data/CONTEXTE.md`, `data/en/CONTEXTE.md`). Tool names are also stored in every saved conversation.

Local models are mostly trained on English tool-calling examples; English names may make small models call tools more reliably. That is a hypothesis.
Lutin has a benchmark (`lutin bench`, with a « tools » score) that can test it.

## Decision

Do not rename on principle. Measure first:

1. Run the existing benchmark on the reference models with French tool names, then with English ones, same prompts otherwise.
2. Switch to English names if tool-calling success does not drop on any reference model. Publish the figures with the decision.
3. If switched: old conversations keep working through a read-time mapping of the stored tool names (part of the 1.0 data migration, ADR 0001).
   The user's language still decides the language of the instructions and of the answers.

Internal identifiers (Python functions such as `outil_lire`) are renamed with the rest of the code regardless: this ADR is about what the model sees.

## Consequences

- Positive: a decision backed by a number; no regression for French-speaking users discovered after the fact.
- Negative: the model-facing names may stay French while the code around them is English, until the measurement is done.
- Risks: the benchmark is small (about twenty questions); results on three or four models do not generalise to all.

## Rollback

Switching back is one commit; stored conversations stay readable either way thanks to the mapping.
