// Unit tests for state/model-registry-snapshot.js (VL-D12's live model
// registry fetch). No browser needed: this is a pure fetch-and-parse
// function, tested here against a minimal local HTTP server (node:http)
// this file fully controls -- distinct from
// frontend/contracts/live/model_registry_snapshot.json itself, which
// this file never reads or writes. Deliberately mirrors
// command-center-snapshot.test.mjs / identity-status-snapshot.test.mjs.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fetchModelRegistrySnapshot } from "../state/model-registry-snapshot.js";

function realSnapshotFixture() {
  return {
    contract: "model_registry_snapshot",
    $generated_by: "scripts/export_model_registry_snapshot.py",
    $live_snapshot: true,
    note: "Point-in-time read of models/registry.jsonl, not a frozen contract.",
    models: [
      {
        model_name: "titanet_large",
        version: "1.0.0",
        provider: "nvidia-nemo",
        model_type: "other",
        status: "approved",
        lifecycle_state: "AVAILABLE",
        architecture: "titanet",
        artifact_checksum: "e838520693f269e7984f55bc8eb3c2d60ccf246bf4b896d4be9bcabe3e4b0fe3",
        license: "NVIDIA (see NGC model card)",
      },
    ],
    count: 1,
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
      const result = await fetchModelRegistrySnapshot(url);
      assert.deepEqual(result, fixture);
    },
  );
});

test("2. real model entries (name/version/provider/lifecycle) are preserved verbatim", async () => {
  const fixture = realSnapshotFixture();
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(fixture));
    },
    async (url) => {
      const result = await fetchModelRegistrySnapshot(url);
      assert.equal(result.models[0].model_name, "titanet_large");
      assert.equal(result.models[0].lifecycle_state, "AVAILABLE");
      assert.equal(result.models[0].provider, "nvidia-nemo");
    },
  );
});

test("3. an empty registry (zero models) is a valid, honest snapshot, not rejected", async () => {
  const fixture = realSnapshotFixture();
  fixture.models = [];
  fixture.count = 0;
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(fixture));
    },
    async (url) => {
      const result = await fetchModelRegistrySnapshot(url);
      assert.deepEqual(result.models, []);
    },
  );
});

test("4. a snapshot with a non-array 'models' field is rejected, not rendered as if real", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ contract: "model_registry_snapshot", models: "not-an-array", count: 0 }));
    },
    async (url) => {
      const result = await fetchModelRegistrySnapshot(url);
      assert.equal(result, null);
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
      await assert.doesNotReject(() => fetchModelRegistrySnapshot(url));
      const result = await fetchModelRegistrySnapshot(url);
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
      const result = await fetchModelRegistrySnapshot(url);
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
      await assert.doesNotReject(() => fetchModelRegistrySnapshot(url));
      const result = await fetchModelRegistrySnapshot(url);
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
      const result = await fetchModelRegistrySnapshot(url);
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
      const result = await fetchModelRegistrySnapshot(url);
      assert.equal(result, null);
    },
  );
});

test("10. a network-level failure (connection refused) resolves to null, never throws", async () => {
  // Port 1 is a real, always-closed low port -- a genuine connection
  // failure, not a simulated one.
  const result = await fetchModelRegistrySnapshot("http://127.0.0.1:1/unreachable.json");
  assert.equal(result, null);
});
