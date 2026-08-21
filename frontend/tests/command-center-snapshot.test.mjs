// Unit tests for state/command-center-snapshot.js (VL-D10's live
// Command Center snapshot fetch). No browser needed: this is a pure
// fetch-and-parse function, tested here against a minimal local HTTP
// server (node:http) that this file fully controls -- distinct from
// frontend/contracts/live/command_center_snapshot.json itself, which
// this file never reads or writes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fetchCommandCenterSnapshot } from "../state/command-center-snapshot.js";

function realSnapshotFixture() {
  return {
    contract: "command_center_snapshot",
    contract_version: "1.0.0",
    processing_version: "0.1.0",
    repository: {
      contract: "repository_context",
      branch: "claude/phase3-speaker-verification",
      head: "1224407ae47f083ec17f076defa85b12e81e848a",
      head_short: "1224407",
      head_subject: "feat: implement local session persistence",
      working_tree_clean: false,
      changed_file_count: 3,
      recent_commits: ["1224407 feat: implement local session persistence"],
    },
    commands: {
      contract: "command_catalogue",
      commands: [{ command: "system-info", summary: "Hardware and environment facts.", risk: "read_only", supports_json: true, requires_confirmation: false, gate_reason: null }],
      count: 1,
    },
    verification: {
      contract: "verification_commands",
      commands: [{ id: "tests", label: "Run test suite", command: ["python", "-m", "pytest", "-q"] }],
    },
    activity: { contract: "activity_feed", entries: [], count: 0, total_available: 0, chain_intact: true },
    diagnostics: {
      contract: "diagnostics",
      healthy: true,
      problems: [],
      git_safety_ok: true,
      audit_chain_intact: true,
      stages_implemented: 9,
      identity_boundary_stage: "speaker_enrollment",
      real_provider_installed: false,
      real_recordings_present: false,
    },
  };
}

/** Starts a tiny server whose response is fully controlled per test,
 * calls `fn(baseUrl)`, and always tears the server down afterward. */
async function withServer(handler, fn) {
  const server = createServer(handler);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    await fn(`http://127.0.0.1:${port}/snapshot.json`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test("1. a valid, well-shaped snapshot is fetched and parsed as-is", async () => {
  const fixture = realSnapshotFixture();
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(fixture));
    },
    async (url) => {
      const result = await fetchCommandCenterSnapshot(url);
      assert.deepEqual(result, fixture);
    },
  );
});

test("2. real repository state is preserved verbatim (branch/head/working-tree)", async () => {
  const fixture = realSnapshotFixture();
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(fixture));
    },
    async (url) => {
      const result = await fetchCommandCenterSnapshot(url);
      assert.equal(result.repository.branch, "claude/phase3-speaker-verification");
      assert.equal(result.repository.head_short, "1224407");
      assert.equal(result.repository.working_tree_clean, false);
    },
  );
});

test("3. real activity entries are preserved verbatim", async () => {
  const fixture = realSnapshotFixture();
  fixture.activity.entries = [{ kind: "identity_review", summary: "identity_review · seg-1", timestamp: "2026-01-01T00:00:00Z", subject_id: "seg-1", detail: {} }];
  fixture.activity.count = 1;
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(fixture));
    },
    async (url) => {
      const result = await fetchCommandCenterSnapshot(url);
      assert.deepEqual(result.activity.entries, fixture.activity.entries);
    },
  );
});

test("4. real diagnostics (healthy) are preserved verbatim", async () => {
  const fixture = realSnapshotFixture();
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(fixture));
    },
    async (url) => {
      const result = await fetchCommandCenterSnapshot(url);
      assert.equal(result.diagnostics.healthy, true);
      assert.deepEqual(result.diagnostics.problems, []);
    },
  );
});

test("5. real diagnostics (unhealthy) surface their real problems, never silently healthy", async () => {
  const fixture = realSnapshotFixture();
  fixture.diagnostics.healthy = false;
  fixture.diagnostics.problems = ["1 protected-material violation(s) in Git"];
  fixture.diagnostics.git_safety_ok = false;
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(fixture));
    },
    async (url) => {
      const result = await fetchCommandCenterSnapshot(url);
      assert.equal(result.diagnostics.healthy, false);
      assert.deepEqual(result.diagnostics.problems, ["1 protected-material violation(s) in Git"]);
    },
  );
});

test("6. real command catalogue (with risk and gate_reason) is preserved verbatim", async () => {
  const fixture = realSnapshotFixture();
  fixture.commands.commands.push({ command: "train", summary: "PLANNED — not implemented.", risk: "gated", supports_json: true, requires_confirmation: false, gate_reason: "No voice model training exists in this project." });
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(fixture));
    },
    async (url) => {
      const result = await fetchCommandCenterSnapshot(url);
      const gated = result.commands.commands.find((c) => c.command === "train");
      assert.equal(gated.risk, "gated");
      assert.equal(gated.gate_reason, "No voice model training exists in this project.");
    },
  );
});

test("7. real verification-command descriptors are preserved verbatim", async () => {
  const fixture = realSnapshotFixture();
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(fixture));
    },
    async (url) => {
      const result = await fetchCommandCenterSnapshot(url);
      assert.deepEqual(result.verification.commands[0].command, ["python", "-m", "pytest", "-q"]);
    },
  );
});

test("8. a missing snapshot (404) resolves to null, never throws, never fabricates a fallback", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(404);
      res.end("Not Found");
    },
    async (url) => {
      await assert.doesNotReject(() => fetchCommandCenterSnapshot(url));
      const result = await fetchCommandCenterSnapshot(url);
      assert.equal(result, null);
    },
  );
});

test("9. a server error (500) resolves to null, never throws", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(500);
      res.end("Internal Server Error");
    },
    async (url) => {
      const result = await fetchCommandCenterSnapshot(url);
      assert.equal(result, null);
    },
  );
});

test("10. malformed JSON resolves to null, never throws", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end("{not valid json");
    },
    async (url) => {
      await assert.doesNotReject(() => fetchCommandCenterSnapshot(url));
      const result = await fetchCommandCenterSnapshot(url);
      assert.equal(result, null);
    },
  );
});

test("11. a well-formed JSON payload from the wrong contract is rejected, not rendered as if real", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ contract: "dataset_gate_status", access_allowed: true }));
    },
    async (url) => {
      const result = await fetchCommandCenterSnapshot(url);
      assert.equal(result, null);
    },
  );
});

test("12. a bare array or primitive JSON response is rejected", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(["not", "an", "envelope"]));
    },
    async (url) => {
      const result = await fetchCommandCenterSnapshot(url);
      assert.equal(result, null);
    },
  );
});

test("13. a network-level failure (connection refused) resolves to null, never throws", async () => {
  // Port 1 is a real, always-closed low port -- a genuine connection
  // failure, not a simulated one.
  const result = await fetchCommandCenterSnapshot("http://127.0.0.1:1/unreachable.json");
  assert.equal(result, null);
});
