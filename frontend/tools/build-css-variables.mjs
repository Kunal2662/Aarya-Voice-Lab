#!/usr/bin/env node
// Reads frontend/tokens/*.json (the single source of truth) and writes
// frontend/css/variables.css as CSS custom properties. Zero dependencies —
// this project stays installable and testable with only `node`, no
// registry fetch, consistent with the local-first / no-cloud-dependency
// architecture.
//
//   node frontend/tools/build-css-variables.mjs [--check]
//
// --check exits nonzero if regenerating would change the committed file,
// without writing anything (used by frontend/tests/css-variables.test.mjs).

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(here, "..");
const tokensDir = path.join(frontendRoot, "tokens");
const outFile = path.join(frontendRoot, "css", "variables.css");

function loadJson(name) {
  return JSON.parse(readFileSync(path.join(tokensDir, name), "utf8"));
}

function kebab(name) {
  return String(name).replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
}

function flatten(obj, prefix, out) {
  for (const [key, value] of Object.entries(obj)) {
    const nextPrefix = prefix ? `${prefix}-${kebab(key)}` : kebab(key);
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      flatten(value, nextPrefix, out);
    } else {
      out.push([nextPrefix, value]);
    }
  }
  return out;
}

function renderThemeBlock(selector, themeTokens) {
  const pairs = flatten(themeTokens, "avl-color", []);
  const lines = pairs.map(([name, value]) => `  --${name}: ${value};`);
  return `${selector} {\n${lines.join("\n")}\n}\n`;
}

function buildCss() {
  const color = loadJson("color.json");
  const typography = loadJson("typography.json");
  const spacing = loadJson("spacing.json");
  const motion = loadJson("motion.json");

  const parts = [];
  parts.push(
    "/* GENERATED FILE — do not edit by hand.",
    " * Source of truth: frontend/tokens/*.json",
    " * Regenerate: node frontend/tools/build-css-variables.mjs",
    " */",
    "",
  );

  // Color: light is the default (:root), dark applies under an explicit
  // [data-theme='dark'] attribute AND under prefers-color-scheme so an
  // unset preference still resolves sensibly. See docs/VLD0_DESIGN_SYSTEM.md
  // "Theme decision" for why both paths exist.
  parts.push(renderThemeBlock(":root, [data-theme='light']", color.themes.light));
  parts.push(
    `@media (prefers-color-scheme: dark) {\n  :root:not([data-theme='light']) {\n${flatten(
      color.themes.dark,
      "avl-color",
      [],
    )
      .map(([n, v]) => `    --${n}: ${v};`)
      .join("\n")}\n  }\n}\n`,
  );
  parts.push(renderThemeBlock("[data-theme='dark']", color.themes.dark));

  // Typography
  const fontFamilyLines = Object.entries(typography.families).map(
    ([name, value]) => `  --avl-font-${kebab(name)}: ${value};`,
  );
  const scaleLines = [];
  for (const [name, def] of Object.entries(typography.scale)) {
    const n = kebab(name);
    scaleLines.push(`  --avl-type-${n}-size: ${def.size};`);
    scaleLines.push(`  --avl-type-${n}-line-height: ${def["line-height"]};`);
    scaleLines.push(`  --avl-type-${n}-weight: ${def.weight};`);
    scaleLines.push(`  --avl-type-${n}-family: var(--avl-font-${kebab(def.family)});`);
  }
  parts.push(`:root {\n${fontFamilyLines.join("\n")}\n${scaleLines.join("\n")}\n}\n`);

  // Spacing / radius / layout
  const spaceLines = Object.entries(spacing.scale).map(([n, v]) => `  --avl-space-${n}: ${v};`);
  const radiusLines = Object.entries(spacing.radius).map(([n, v]) => `  --avl-radius-${kebab(n)}: ${v};`);
  const layoutLines = Object.entries(spacing.layout).map(([n, v]) => `  --avl-layout-${kebab(n)}: ${v};`);
  parts.push(
    `:root {\n${spaceLines.join("\n")}\n${radiusLines.join("\n")}\n${layoutLines.join("\n")}\n}\n`,
  );

  // Motion
  const durationLines = Object.entries(motion.durations).map(
    ([n, v]) => `  --avl-duration-${kebab(n)}: ${v};`,
  );
  const easingLines = Object.entries(motion.easings).map(([n, v]) => `  --avl-easing-${kebab(n)}: ${v};`);
  parts.push(`:root {\n${durationLines.join("\n")}\n${easingLines.join("\n")}\n}\n`);

  parts.push(
    "/* Reduced motion: collapse every duration token to effectively",
    " * instant. Components must use these custom properties for all",
    " * durations so this single override disables motion app-wide. */",
    "@media (prefers-reduced-motion: reduce) {",
    "  :root {",
    ...Object.keys(motion.durations).map((n) => `    --avl-duration-${kebab(n)}: 1ms;`),
    "  }",
    "}",
    "",
  );

  return parts.join("\n");
}

function main() {
  const checkOnly = process.argv.includes("--check");
  const css = buildCss();
  const existing = existsSync(outFile) ? readFileSync(outFile, "utf8") : null;
  const changed = existing !== css;

  if (checkOnly) {
    if (changed) {
      console.error(`frontend/css/variables.css is stale relative to frontend/tokens/*.json.`);
      console.error("Run: node frontend/tools/build-css-variables.mjs");
      process.exit(1);
    }
    process.exit(0);
  }

  writeFileSync(outFile, css, "utf8");
  console.log(`Wrote ${outFile}`);
}

main();
