// Unit tests for state/identity-status-snapshot.js (D11 audit's live
// identity/enrollment status fetch). No browser needed: this is a pure
// fetch-and-parse function, tested here against a minimal local HTTP
// server (node:http) this file fully controls -- distinct from
// frontend/contracts/live/identity_status_snapshot.json itself, which
// this file never reads or writes. Deliberately mirrors
// command-center-snapshot.test.mjs's structure.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fetchIdentityStatusSnapshot } from "../state/identity-status-snapshot.js";

function realSnapshotFixture() {
  return {
    contract: "desktop_snapshot",
    contract_version: "1.0.0",
    processing_version: "0.1.0",
    profiles: { contract: "speaker_profiles", profiles: [], count: 0, usable_count: 0 },
    enrollment: {
      contract: "enrollment_status",
      by_state: {},
      by_role: {},
      available_strategies: [],
      available_providers: ["local-neural-embedding", "synthetic-cosine-projection"],
      real_provider_installed: true,
      note: "A real embedding provider is installed and loaded on this machine (see identity.embeddings.any_real_provider_available).",
    },
    pipeline: { contract: "pipeline_status", stages: [], identity_boundary_index: 5, identity_boundary_stage: "speaker_enrollment", batches: [], implemented_count: 9 },
    embeddings: { contract: "embedding_inventory", entries: [], count: 0 },
    runtime: { contract: "runtime_capabilities", components: [], portability: {} },
    preview: { contract: "voice_preview_status" },
    audit: { entry_count: 0, event_counts: {}, chain_intact: true, chain_problems: [], first_entry: null, last_entry: null },
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
      const result = await fetchIdentityStatusSnapshot(url);
      assert.deepEqual(result, fixture);
    },
  );
});

test("2. real_provider_installed=true is preserved verbatim, never flattened to a fixed value", async () => {
  const fixture = realSnapshotFixture();
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(fixture));
    },
    async (url) => {
      const result = await fetchIdentityStatusSnapshot(url);
      assert.equal(result.enrollment.real_provider_installed, true);
    },
  );
});

test("3. real_provider_installed=false is preserved verbatim too -- this fetch never assumes either direction", async () => {
  const fixture = realSnapshotFixture();
  fixture.enrollment.real_provider_installed = false;
  fixture.enrollment.note = "No real embedding provider is installed. Only the synthetic development provider exists in this environment.";
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(fixture));
    },
    async (url) => {
      const result = await fetchIdentityStatusSnapshot(url);
      assert.equal(result.enrollment.real_provider_installed, false);
    },
  );
});

test("4. real profile/pipeline counts are preserved verbatim", async () => {
  const fixture = realSnapshotFixture();
  fixture.profiles.count = 3;
  fixture.profiles.usable_count = 2;
  fixture.pipeline.implemented_count = 9;
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(fixture));
    },
    async (url) => {
      const result = await fetchIdentityStatusSnapshot(url);
      assert.equal(result.profiles.count, 3);
      assert.equal(result.profiles.usable_count, 2);
      assert.equal(result.pipeline.implemented_count, 9);
    },
  );
});

test("5. a missing snapshot (404) resolves to null, never throws, never fabricates a fallback", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(404);
      res.end("Not Found");
    },
    async (url) => {
      await assert.doesNotReject(() => fetchIdentityStatusSnapshot(url));
      const result = await fetchIdentityStatusSnapshot(url);
      assert.equal(result, null);
    },
  );
});

test("6. a server error (500) resolves to null, never throws", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(500);
      res.end("Internal Server Error");
    },
    async (url) => {
      const result = await fetchIdentityStatusSnapshot(url);
      assert.equal(result, null);
    },
  );
});

test("7. malformed JSON resolves to null, never throws", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end("{not valid json");
    },
    async (url) => {
      await assert.doesNotReject(() => fetchIdentityStatusSnapshot(url));
      const result = await fetchIdentityStatusSnapshot(url);
      assert.equal(result, null);
    },
  );
});

test("8. a well-formed JSON payload from the wrong contract is rejected, not rendered as if real", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ contract: "command_center_snapshot", repository: {} }));
    },
    async (url) => {
      const result = await fetchIdentityStatusSnapshot(url);
      assert.equal(result, null);
    },
  );
});

test("9. a bare array or primitive JSON response is rejected", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(["not", "an", "envelope"]));
    },
    async (url) => {
      const result = await fetchIdentityStatusSnapshot(url);
      assert.equal(result, null);
    },
  );
});

test("10. a network-level failure (connection refused) resolves to null, never throws", async () => {
  // Port 1 is a real, always-closed low port -- a genuine connection
  // failure, not a simulated one.
  const result = await fetchIdentityStatusSnapshot("http://127.0.0.1:1/unreachable.json");
  assert.equal(result, null);
});
