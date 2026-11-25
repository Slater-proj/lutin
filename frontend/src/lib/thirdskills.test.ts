import { describe, expect, it } from "vitest";
import { canInstall, indexingProgress, installBody, lacksLicense, searchPath, type SkillCard } from "./thirdskills";

const card = (more: Partial<SkillCard> = {}): SkillCard => ({
  repo: "anthropics/skills", dir: "skills/pdf", name: "pdf", description: "", license: "MIT", license_file: false, license_repo: false, text: "", text_truncated: false, files: [], file_count: 3,
  bytes: 100, scripts: [], tokens: 10, heavy: false, findings: [], severity: "none", too_big: [], installable: true, ...more,
});

describe("lacksLicense", () => {
  it("is false as soon as the header, a file beside it or the repository gives a licence", () => {
    expect(lacksLicense(card({ license: "" }))).toBe(true);
    expect(lacksLicense(card({ license: "", license_file: true }))).toBe(false);
    expect(lacksLicense(card({ license: "", license_repo: true }))).toBe(false);
    expect(lacksLicense(card())).toBe(false);
  });
});

describe("canInstall", () => {
  it("is open for a clean, licensed skill of an allowed size", () => {
    expect(canInstall(card(), { danger: false, noLicense: false })).toBe(true);
  });
  it("waits for the acceptance of each risk, and one acceptance never covers the other", () => {
    const risky = card({ severity: "danger", license: "" });
    expect(canInstall(risky, { danger: true, noLicense: false })).toBe(false);
    expect(canInstall(risky, { danger: false, noLicense: true })).toBe(false);
    expect(canInstall(risky, { danger: true, noLicense: true })).toBe(true);
  });
  it("never opens for a skill that is too big, whatever was ticked", () => {
    expect(canInstall(card({ installable: false }), { danger: true, noLicense: true })).toBe(false);
  });
  it("does not ask for the danger acceptance of a card that only calls for attention", () => {
    expect(canInstall(card({ severity: "attention" }), { danger: false, noLicense: false })).toBe(true);
  });
});

describe("installBody", () => {
  it("sends the repository, the folder and the confirmation, and leaves out an empty project", () => {
    expect(installBody(card(), "", { danger: false, noLicense: false }, true)).toEqual({ repo: "anthropics/skills", dir: "skills/pdf", confirm: true, accept_danger: false, accept_no_license: false });
    expect(installBody(card(), "ab12", { danger: false, noLicense: false }, false)).toMatchObject({ project: "ab12", confirm: false });
  });
  it("sends an acceptance only for a risk that is really there, even if the box stayed ticked from another card", () => {
    expect(installBody(card(), "", { danger: true, noLicense: true }, true)).toMatchObject({ accept_danger: false, accept_no_license: false });
    expect(installBody(card({ severity: "danger", license: "" }), "", { danger: true, noLicense: true }, true)).toMatchObject({ accept_danger: true, accept_no_license: true });
  });
});

describe("searchPath", () => {
  it("sends only what was filled in and encodes it", () => {
    expect(searchPath("", [], 1)).toBe("/third-party-skills/search");
    expect(searchPath(" word & pdf ", [], 1)).toBe("/third-party-skills/search?q=word%20%26%20pdf");
    expect(searchPath("x", ["a/b", "c/d"], 3)).toBe("/third-party-skills/search?q=x&repos=a%2Fb,c%2Fd&page=3");
  });
});

describe("indexingProgress", () => {
  it("adds the sources up and says whether one is still running", () => {
    expect(indexingProgress({})).toEqual({ running: false, done: 0, total: 0, error: "" });
    const state = indexingProgress({ "a/b": { done: 5, total: 10, finished: false, error: "" }, "c/d": { done: 2, total: 2, finished: true, error: "" } });
    expect(state).toEqual({ running: true, done: 7, total: 12, error: "" });
    expect(indexingProgress({ "a/b": { done: 0, total: 0, finished: true, error: "limit" } }).error).toBe("limit");
  });
});
