import { test } from "node:test";
import assert from "node:assert/strict";
import { labelFor, tokenPathToCssVar, loadStatusVocabulary } from "../components/status-vocabulary.js";

test("labelFor humanises snake_case and SCREAMING_CASE alike", () => {
  assert.equal(labelFor("not_started"), "Not started");
  assert.equal(labelFor("UNCALIBRATED"), "Uncalibrated");
  assert.equal(labelFor("review-required"), "Review required");
  assert.equal(labelFor(""), "");
});

test("tokenPathToCssVar builds the exact custom-property name build-css-variables.mjs emits", () => {
  assert.equal(tokenPathToCssVar("state.success"), "--avl-color-state-success");
  assert.equal(tokenPathToCssVar("voice.review-required"), "--avl-color-voice-review-required");
});

test("loadStatusVocabulary rejects when fetch is unavailable (no silent empty vocabulary)", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = undefined;
  try {
    await assert.rejects(() => loadStatusVocabulary());
  } finally {
    globalThis.fetch = originalFetch;
  }
});
