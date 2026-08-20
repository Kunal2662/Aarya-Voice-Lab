import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

test("frontend/contracts/generated/*.json is not stale relative to backend enums", () => {
  assert.doesNotThrow(() => {
    execFileSync("python", [path.join(repoRoot, "scripts", "export_frontend_contracts.py"), "--check"], {
      stdio: "pipe",
      cwd: repoRoot,
    });
  }, "run `python scripts/export_frontend_contracts.py` to regenerate");
});
