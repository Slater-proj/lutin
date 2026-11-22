import { describe, expect, it } from "vitest";
import { byUse, detailsLink, readName, shortName } from "./model_card";

describe("readName", () => {
  it("reads the size, the quantisation and the format of an ExLlamaV3 model", () => {
    const facts = readName("Qwen3.6-27B-exl3", "4.0bpw");
    expect(facts.family).toBe("Qwen 3.6");
    expect(facts.paramsB).toBe(27);
    expect(facts.activeB).toBeNull();
    expect(facts.bpw).toBe(4);
    expect(facts.format).toBe("exl3");
    expect(facts.uses).toEqual(["chat"]);
    expect(facts.uncensored).toBe(false);
  });

  it("reads a mixture of experts, a GGUF quantisation and what the model is made for", () => {
    const facts = readName("Qwen3-Coder-30B-A3B-Instruct-GGUF", "Q4_K_M");
    expect([facts.paramsB, facts.activeB, facts.quant, facts.format]).toEqual([30, 3, "Q4_K_M", "gguf"]);
    expect(facts.uses).toEqual(["code"]);
  });

  it("says when the refusals of a model were removed", () => {
    expect(readName("Huihui-Qwen3.8-27B-abliterated-exl3").uncensored).toBe(true);
    expect(readName("huihui_ai/qwen3.8-abliterated:27b").paramsB).toBe(27);
    expect(readName("gemma-4-31b-it-exl3", "3.50bpw_mul1").bpw).toBe(3.5);
  });

  it("does not take « bpw » nor a version for a size", () => {
    expect(readName("Model-exl3", "6.0bpw").paramsB).toBeNull();
  });
});

describe("links", () => {
  it("leads to the page of the model where it comes from", () => {
    expect(detailsLink("turboderp/Qwen3-8B-exl3", "exllamav3")).toBe("https://huggingface.co/turboderp/Qwen3-8B-exl3");
    expect(detailsLink("qwen3:8b", "ollama")).toBe("https://ollama.com/library/qwen3");
    expect(detailsLink("huihui_ai/qwen3-abliterated:27b", "ollama")).toBe("https://ollama.com/huihui_ai/qwen3-abliterated");
    expect(detailsLink("Qwen3-8B-exl3", "exllamav3")).toBe("");
    expect(shortName("turboderp/Qwen3-8B-exl3")).toBe("Qwen3-8B-exl3");
  });
});

describe("byUse", () => {
  it("groups the models by what they are for, conversation first and search by meaning last, each group by family then size", () => {
    const groups = byUse(["nomic-embed-text", "qwen3:14b", "qwen2.5-coder:7b", "gemma3:4b", "qwen3:8b", "qwen3-vl:8b", "deepseek-r1:8b"]);
    expect(groups).toEqual([
      { use: "chat", names: ["gemma3:4b", "qwen3:8b", "qwen3:14b"] },
      { use: "code", names: ["qwen2.5-coder:7b"] },
      { use: "reasoning", names: ["deepseek-r1:8b"] },
      { use: "vision", names: ["qwen3-vl:8b"] },
      { use: "embedding", names: ["nomic-embed-text"] },
    ]);
  });

  it("leaves out the empty groups, and a list of one use is one group", () => {
    expect(byUse(["qwen3:8b", "gemma3:4b"])).toEqual([{ use: "chat", names: ["gemma3:4b", "qwen3:8b"] }]);
    expect(byUse([])).toEqual([]);
  });
});
