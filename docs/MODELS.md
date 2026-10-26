**English** · [Français](MODELS.fr.md)

# The models

## How Lutin chooses

1. It reads your machine: graphics card and its memory, RAM, disks.
2. It computes a **memory budget**: 85 % of the card's memory (NVIDIA, AMD), 75 % of the memory of a Mac with an Apple chip, otherwise 60 % of the RAM (no graphics card: slow but usable).
3. For each role, it keeps the **best rated model that fits**: model weights + context memory (halved thanks to the compressed cache) + a margin. The context is reduced (32,000 tokens, then 16,000, then 8,000) as long as it does not fit.
4. A « mixture of experts » model (few active parameters per word) may spill over into RAM: it is offered with the mention « slower ».
5. Only models able to **call tools** are offered: without that, Lutin can neither read nor modify your files.

The result is shown by `lutin modeles` and in the guided installation. You can always choose something else in the Models tab.

## The roles

| Role | For | Ticked by default |
|---|---|---|
| General | doing everything, every day | yes |
| Fast | almost instant answers | only if it weighs less than 5 GB |
| Creative | writing, stories, ideas | no |
| Code | programming, scripts | no |
| Images | understanding images, screenshots, documents | no |

## Advanced models

Some models are modified by the community so that they no longer refuse requests. They are hidden by default, never chosen automatically, and shown with a warning when you tick « Show advanced models ». You are responsible for them.

## The catalogue

`src/lutin/data/modeles.json`: data, not code. Each model has a one-sentence description (140 characters at most), its size, its capabilities, its licence, and 1 to 10 ratings per role.

**The current ratings are editorial: they have not been measured.** They are used to rank models against each other for the same role, not to compare roles. To correct them, open a « Suggest or correct a model » proposal explaining what justifies it. The `verifie` field will become a date once the weekly CI (`tools/verifier_catalogue.py`) has confirmed that the model exists in Ollama's registry.

## The benchmark: measure instead of believing

`lutin bench [model]` (or the « Test the speed » and « Full bench » buttons of the Models tab) measures **this model on this machine**:

| Measure | How |
|---|---|
| Speed | tokens written per second on a 150-word text, model loading time |
| Tool calls | 3 requests: open a file, search a function, and **not** call a tool for a simple hello |
| Code (reading) | 4 small programs whose result must be given |
| French | an answer in one sentence, and exactly three bullet points |
| Instructions | a valid JSON object, with no text around it |

The answers are checked automatically; **no code written by the model is ever executed**. A single pass at temperature 0: it is an **indicator**, not a scientific ranking. Results are kept in the cache, shown in the model list, and exportable (`lutin bench --exporter`) to propose a rating correction to the catalogue.

Measured ratings (0 to 10): *code* = 60 % code + 40 % tools; *creative* = 60 % French + 40 % instructions; *general* = average of the four; *fast* = scale on tokens per second (capped at 4 if the model does not call tools: unusable for Lutin). The formulas are in `lutin/bench.py`: challenge them.

## Updates

At launch (at most once a day, never blocking), then on demand with the buttons of the Models tab or `lutin update`:

- **Check for updates**: compares the fingerprint of each installed model with that of Ollama's registry.
- **Look for new models**: downloads the online catalogue (if configured), then compares with what you installed for each role. A proposal appears if a clearly better rated model fits your machine, or if yours no longer fits.

Nothing is downloaded without your approval. « Stop suggesting » remembers your refusal.
