// GENERATES web/src/features/session/generated/*.ts from backend contracts.
// Source of truth: schemas/ (Pydantic) -> docs/contracts/*.schema.json + docs/openapi.json
// Run: cd scripts/typescript-gen && npm install && npm run generate
import { execFileSync } from "node:child_process";
import { mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { compileFromFile } from "json-schema-to-typescript";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const ROOT = join(scriptDir, "..", "..");
const OPENAPI = join(ROOT, "docs", "openapi.json");
const CONTRACTS = join(ROOT, "docs", "contracts");
const OUT = join(ROOT, "web", "src", "features", "session", "generated");
mkdirSync(OUT, { recursive: true });

const bin = join(scriptDir, "node_modules", ".bin", "openapi-typescript");
execFileSync(
  bin,
  [
    "--additional-properties=false",
    "--export-type",
    "--output",
    join(OUT, "api.ts"),
    OPENAPI,
  ],
  { stdio: "inherit" },
);

const files = readdirSync(CONTRACTS).filter((f) => f.endsWith(".schema.json"));
for (const f of files) {
  const name = f.replace(/\.schema\.json$/, "");
  const ts = await compileFromFile(join(CONTRACTS, f), {
    additionalProperties: false,
    unreachableDefinitions: true,
    bannerComment: `/* AUTO-GENERATED from docs/contracts/${f} via json-schema-to-typescript — do not edit. */`,
  });
  writeFileSync(join(OUT, `${name}.ts`), ts);
  console.log(`⚙️  ${name}.ts`);
}
console.log(`wrote ${files.length + 1} files to ${OUT}`);
