// What the name of a model says, read the same way for every engine (maintainer, 2026-11-21: « every model must have the same card, whether it is
// proposed, searched or fitted to my machine »). Names are the only thing every source gives (Ollama's tags, Hugging Face repositories, a folder on
// disk): the size in billions of parameters, the active part of a mixture of experts, the quantisation, the format, what it is made for, and whether
// its refusals were removed. Nothing here is guessed beyond what the name writes.

export interface NameFacts {
  family: string; // « Qwen3.6 », « Gemma 4 »… or "" when the name does not start with a known family
  paramsB: number | null; // billions of parameters (« 27B »)
  activeB: number | null; // a mixture of experts: the billions that work for each word (« A3B »)
  bpw: number | null; // ExLlamaV3: bits per weight (« 4.0bpw »)
  quant: string; // GGUF: « Q4_K_M », « IQ3_XS »…
  format: "exl3" | "gguf" | "";
  uses: Use[];
  uncensored: boolean;
}

export type Use = "code" | "vision" | "reasoning" | "embedding" | "chat";

const FAMILIES: readonly [RegExp, string][] = [
  [/qwen\s*-?(\d+(?:\.\d+)?)?/i, "Qwen"],
  [/gemma\s*-?(\d+(?:\.\d+)?)?/i, "Gemma"],
  [/llama\s*-?(\d+(?:\.\d+)?)?/i, "Llama"],
  [/mistral|ministral|magistral|devstral/i, "Mistral"],
  [/glm\s*-?(\d+(?:\.\d+)?)?/i, "GLM"],
  [/deepseek/i, "DeepSeek"],
  [/phi\s*-?(\d+(?:\.\d+)?)?/i, "Phi"],
  [/granite\s*-?(\d+(?:\.\d+)?)?/i, "Granite"],
  [/lfm\s*-?(\d+(?:\.\d+)?)?/i, "LFM"],
  [/gpt-oss/i, "gpt-oss"],
  [/olmo/i, "OLMo"],
];

const UNCENSORED = /abliterat|uncensor|huihui|dolphin|nsfw|unfilter|unalign|heretic/i;

/** The last path part of a reference (« turboderp/Qwen3-8B-exl3 » -> « Qwen3-8B-exl3 »), the tag kept (« qwen3:8b »). */
export function shortName(ref: string): string {
  return ref.split("/").pop() || ref;
}

export function readName(name: string, revision = ""): NameFacts {
  const text = name + " " + revision;
  let family = "";
  for (const [pattern, label] of FAMILIES) {
    const found = pattern.exec(name);
    if (found) {
      family = found[1] && !/b$/i.test(found[0]) ? label + " " + found[1] : label;
      break;
    }
  }
  // « 27B », « 8b », « 1.5B », « 30B-A3B »: a number followed by b, not part of a longer word (« bpw », « Bit »)
  const sizes = [...text.matchAll(/(?:^|[^a-z0-9.])(a)?(\d+(?:\.\d+)?)\s*b(?![a-z])/gi)];
  const total = sizes.find((found) => !found[1]);
  const active = sizes.find((found) => found[1]);
  const bpw = /(\d+(?:\.\d+)?)\s*bpw/i.exec(text);
  const quant = /\b(I?Q\d(?:_[A-Z0-9]+)*|F16|BF16|FP8)\b/i.exec(text);
  const format = /exl3/i.test(text) ? "exl3" : /gguf/i.test(text) || quant ? "gguf" : "";
  const uses: Use[] = [];
  if (/coder|code|devstral/i.test(name)) uses.push("code");
  if (/\bvl\b|-vl-|vision|-v-|llava/i.test(name)) uses.push("vision");
  if (/reason|think|-r1|qwq|magistral/i.test(name)) uses.push("reasoning");
  if (/embed/i.test(name)) uses.push("embedding");
  if (!uses.length) uses.push("chat");
  return {
    family,
    paramsB: total ? Number(total[2]) : null,
    activeB: active ? Number(active[2]) : null,
    bpw: bpw ? Number(bpw[1]) : null,
    quant: quant ? quant[1].toUpperCase() : "",
    format,
    uses,
    uncensored: UNCENSORED.test(name),
  };
}

/** The page of a model, to read more about it: Hugging Face for a repository (« owner/name »), ollama.com for an Ollama tag. */
export function detailsLink(ref: string, engine: string): string {
  if (/^[\w.-]+\/[\w.-]+$/.test(ref) && engine !== "ollama") return "https://huggingface.co/" + ref;
  const library = ref.split(":")[0];
  if (engine === "ollama" && library) return "https://ollama.com/" + (library.includes("/") ? library : "library/" + library);
  return "";
}
