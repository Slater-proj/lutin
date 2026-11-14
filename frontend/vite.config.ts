// Build of the interface (ADR 0002): static files written into the Python package, served by Lutin under /app/.
// Nothing here runs when Lutin runs: Node.js is needed to build, never to install or use Lutin.
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

const here = fileURLToPath(new URL(".", import.meta.url));
const out = resolve(here, "../src/lutin/web/app");
// What the build is made from, with everything under src/. The same list and the same computation are in src/lutin/web_app.py (sources_stamp):
// tests/test_web_app.py fails when a shipped build no longer matches the sources.
const STAMPED = ["index.html", "package.json", "package-lock.json", "svelte.config.js", "tsconfig.json", "vite.config.ts"];

function filesUnder(folder: string): string[] {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? filesUnder(join(folder, entry.name)) : entry.isFile() ? [join(folder, entry.name)] : [],
  );
}

function sourcesStamp(): string {
  const files = [...STAMPED.map((name) => join(here, name)).filter((file) => existsSync(file)), ...filesUnder(join(here, "src"))];
  const named = files.map((file) => [relative(here, file).split("\\").join("/"), file] as const).sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  const digest = createHash("sha256");
  for (const [name, file] of named) {
    const content = Buffer.from(readFileSync(file).toString("latin1").replace(/\r\n/g, "\n"), "latin1"); // line endings do not count
    digest.update(Buffer.concat([Buffer.from(name, "utf8"), Buffer.from([0]), content, Buffer.from([0])]));
  }
  return digest.digest("hex");
}

function stamp(): Plugin {
  return {
    name: "lutin-build-stamp",
    apply: "build",
    closeBundle() {
      writeFileSync(join(out, "build.json"), JSON.stringify({ sources: sourcesStamp() }) + "\n");
    },
  };
}

export default defineConfig({
  base: "/app/",
  plugins: [svelte(), stamp()],
  build: { outDir: out, emptyOutDir: true, assetsDir: "assets", target: "es2022", sourcemap: false, assetsInlineLimit: 0 },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
