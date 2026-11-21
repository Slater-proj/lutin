import { describe, expect, it } from "vitest";
import { installInput, readyToInstall, type CatalogField } from "./catalog";

const folders: CatalogField = { key: "folders", type: "folder", required: true, multiple: true, label: "Folders", example: "C:/Documents" };
const token: CatalogField = { key: "token", type: "secret", required: false, multiple: false, label: "Token", example: "" };

describe("installInput", () => {
  it("makes a list of the lines of a field that takes several values and drops empty lines", () => {
    expect(installInput([folders], { folders: " C:/a \n\n C:/b\n" })).toEqual({ folders: ["C:/a", "C:/b"] });
  });
  it("keeps a single value trimmed and leaves an empty field out", () => {
    expect(installInput([token], { token: "  abc  " })).toEqual({ token: "abc" });
    expect(installInput([token], { token: "   " })).toEqual({});
    expect(installInput([token], {})).toEqual({});
  });
});

describe("readyToInstall", () => {
  it("waits for every required field", () => {
    expect(readyToInstall([folders, token], {})).toBe(false);
    expect(readyToInstall([folders, token], { folders: "\n \n" })).toBe(false);
    expect(readyToInstall([folders, token], { folders: "C:/a" })).toBe(true);
  });
  it("is ready at once when nothing is required", () => {
    expect(readyToInstall([], {})).toBe(true);
  });
});
