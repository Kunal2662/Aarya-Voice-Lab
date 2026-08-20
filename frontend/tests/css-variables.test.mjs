import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("variables.css is not stale relative to tokens/*.json", () => {
  assert.doesNotThrow(() => {
    execFileSync("node", [path.join(frontendRoot, "tools", "build-css-variables.mjs"), "--check"], {
      stdio: "pipe",
    });
  }, "run `node frontend/tools/build-css-variables.mjs` to regenerate");
});

test("light and dark themes define the same set of color token names", () => {
  const color = JSON.parse(readFileSync(path.join(frontendRoot, "tokens", "color.json"), "utf8"));

  function flattenKeys(obj, prefix = "") {
    let keys = [];
    for (const [k, v] of Object.entries(obj)) {
      const next = prefix ? `${prefix}.${k}` : k;
      if (v !== null && typeof v === "object" && !Array.isArray(v)) {
        keys = keys.concat(flattenKeys(v, next));
      } else {
        keys.push(next);
      }
    }
    return keys.sort();
  }

  const lightKeys = flattenKeys(color.themes.light);
  const darkKeys = flattenKeys(color.themes.dark);
  assert.deepEqual(lightKeys, darkKeys);
});

test("status.json calibration domain exactly matches CalibrationState export", () => {
  const status = JSON.parse(readFileSync(path.join(frontendRoot, "tokens", "status.json"), "utf8"));
  const generated = JSON.parse(
    readFileSync(path.join(frontendRoot, "contracts", "generated", "calibration_state.json"), "utf8"),
  );
  assert.deepEqual(status.domains.calibration.states, generated.values);
});

test("status.json hardware domain exactly matches CapabilityState export", () => {
  const status = JSON.parse(readFileSync(path.join(frontendRoot, "tokens", "status.json"), "utf8"));
  const generated = JSON.parse(
    readFileSync(path.join(frontendRoot, "contracts", "generated", "capability_state.json"), "utf8"),
  );
  assert.deepEqual(status.domains.hardware.states, generated.values);
});

test("every status domain state has a color_token entry", () => {
  const status = JSON.parse(readFileSync(path.join(frontendRoot, "tokens", "status.json"), "utf8"));
  for (const [domainName, domain] of Object.entries(status.domains)) {
    for (const state of domain.states) {
      assert.ok(
        Object.prototype.hasOwnProperty.call(domain.color_token, state),
        `${domainName}.${state} missing a color_token mapping`,
      );
    }
  }
});
