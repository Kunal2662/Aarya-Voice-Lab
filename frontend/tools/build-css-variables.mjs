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
  //
  // FE-1 token-delivery fix -- deliberately kept :root-scoped, NOT
  // :host-scoped, unlike the blocks below. [data-theme='dark']/
  // [data-theme='light'] are attributes avl-theme-toggle.js sets on the
  // real <html> element (see app/main.js), and a :host selector can
  // only ever match attributes on its OWN shadow host, never on an
  // ancestor elsewhere in the document -- there is no CSS selector that
  // lets a shadow tree react to an attribute on a *different* element up
  // the light-DOM tree. Custom properties, uniquely, are INHERITED
  // through shadow boundaries, so the fix for this block is on the
  // consumption side, not here: app/index.html and shell/index.html now
  // also link this generated file at the real document root (see their
  // own comments), so these exact :root/[data-theme] rules finally have
  // a genuine <html> to match against, and every shadow tree inherits
  // the resulting values automatically -- reacting correctly to both
  // prefers-color-scheme and the explicit toggle, exactly as before this
  // fix was needed to matter. Each component's own per-shadow-root copy
  // of this same block (linked via _linkSharedStyles(), unchanged)
  // stays harmlessly unmatched for :root selectors specifically -- that
  // is expected, not a bug, since those values now arrive by inheritance
  // instead. Redeclaring color via :host here would be actively wrong:
  // a value set directly via :host on a component's own host element
  // always wins over an inherited one in the cascade, which would
  // permanently pin every component to whichever theme's :host rule
  // happened to load, ignoring runtime theme changes entirely.
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
  // FE-1 token-delivery fix -- unlike the color block above, typography/
  // spacing/radius/layout/motion never vary by an ancestor's attribute
  // (no theme reactivity to preserve), so :host is both safe and
  // sufficient here: it makes these tokens available directly inside
  // each component's own shadow root through the existing
  // _linkSharedStyles() mechanism, with no risk of shadowing a runtime
  // override the way redeclaring color via :host would. :root is kept
  // alongside it (harmless duplication, same static values either way)
  // so the same file also works correctly now that app/index.html and
  // shell/index.html additionally link it at the real document root.
  parts.push(`:host, :root {\n${fontFamilyLines.join("\n")}\n${scaleLines.join("\n")}\n}\n`);

  // Spacing / radius / layout
  const spaceLines = Object.entries(spacing.scale).map(([n, v]) => `  --avl-space-${n}: ${v};`);
  const radiusLines = Object.entries(spacing.radius).map(([n, v]) => `  --avl-radius-${kebab(n)}: ${v};`);
  const layoutLines = Object.entries(spacing.layout).map(([n, v]) => `  --avl-layout-${kebab(n)}: ${v};`);
  parts.push(
    `:host, :root {\n${spaceLines.join("\n")}\n${radiusLines.join("\n")}\n${layoutLines.join("\n")}\n}\n`,
  );

  // Motion
  const durationLines = Object.entries(motion.durations).map(
    ([n, v]) => `  --avl-duration-${kebab(n)}: ${v};`,
  );
  const easingLines = Object.entries(motion.easings).map(([n, v]) => `  --avl-easing-${kebab(n)}: ${v};`);
  parts.push(`:host, :root {\n${durationLines.join("\n")}\n${easingLines.join("\n")}\n}\n`);

  parts.push(
    "/* Reduced motion: collapse every duration token to effectively",
    " * instant. Components must use these custom properties for all",
    " * durations so this single override disables motion app-wide.",
    " * :host, :root for the same reason as the token blocks above --",
    " * prefers-reduced-motion is a pure media feature (not dependent on",
    " * a DOM attribute), so it's safe to deliver locally per shadow root",
    " * as well as from the document root. */",
    "@media (prefers-reduced-motion: reduce) {",
    "  :host, :root {",
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
