// How numbers are shown to a person. Pure functions (tested in format.test.ts).

/** A size in bytes as « 4,7 Go » / « 4.7 GB »: the unit and the decimal mark follow the language. */
export function formatBytes(bytes: number | null | undefined, lang: "en" | "fr"): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes < 0) return "";
  const units = lang === "fr" ? ["o", "Ko", "Mo", "Go", "To"] : ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  const text = value.toFixed(digits);
  return `${lang === "fr" ? text.replace(".", ",") : text} ${units[unit]}`;
}

/** The share of a download that is done, 0 to 100, or null while its total is not known. */
export function percent(done: number, total: number): number | null {
  if (!(total > 0)) return null;
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
}
