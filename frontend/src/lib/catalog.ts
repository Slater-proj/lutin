// The catalogue of connectors as the Agents screen sends it. Pure functions (tested in catalog.test.ts).

export type FieldType = "folder" | "file" | "url" | "secret";

export interface CatalogField {
  key: string;
  type: FieldType;
  required: boolean;
  multiple: boolean;
  label: string;
  example: string;
}

export interface CatalogEntry {
  id: string;
  name: string;
  description: string;
  category: string;
  runner: "npx" | "uvx" | "http";
  version: string;
  installed: boolean;
  prerequisite: string;
  fields: CatalogField[];
}

/** The values typed in the form, as the body of the installation: a field that takes several values (one per line) becomes a list, an empty field is left out. */
export function installInput(fields: CatalogField[], typed: Record<string, string>): Record<string, string | string[]> {
  const input: Record<string, string | string[]> = {};
  for (const field of fields) {
    const raw = typed[field.key] ?? "";
    if (field.multiple) {
      const lines = raw.split("\n").map((line) => line.trim()).filter((line) => line !== "");
      if (lines.length > 0) input[field.key] = lines;
    } else if (raw.trim() !== "") {
      input[field.key] = raw.trim();
    }
  }
  return input;
}

/** Whether the form may be sent: every required field has something in it. */
export function readyToInstall(fields: CatalogField[], typed: Record<string, string>): boolean {
  const input = installInput(fields, typed);
  return fields.every((field) => !field.required || field.key in input);
}
