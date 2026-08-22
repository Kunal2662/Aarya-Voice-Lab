// VL-D12 -- fetches the live model registry snapshot
// (frontend/contracts/live/model_registry_snapshot.json, written by
// scripts/export_model_registry_snapshot.py from the real, tested
// registry.ModelRegistry.list_non_private_models()). Same honest
// "missing/malformed/wrong-shape -> null, never thrown, never
// fabricated" pattern as state/command-center-snapshot.js and
// state/identity-status-snapshot.js, which this deliberately mirrors
// line for line so all three fetchers stay obviously equivalent.
//
// Security note: this fetcher trusts that the source file was written
// by list_non_private_models() (never `.list()` or
// list_private_voice_models()) -- see docs/SECURITY.md and
// export_model_registry_snapshot.py's own docstring. This module does
// no additional filtering of its own; the guarantee lives at the
// registry method, the one place every consumer (this fetch, the CLI)
// actually goes through.
export async function fetchModelRegistrySnapshot(url) {
  let response;
  try {
    response = await fetch(url);
  } catch {
    // Network-level failure (no server, CORS, etc.) -- honestly
    // unavailable, never thrown at the caller.
    return null;
  }
  if (!response.ok) return null;

  let payload;
  try {
    payload = await response.json();
  } catch {
    // Malformed JSON -- honestly unavailable, not a fabricated partial
    // snapshot.
    return null;
  }

  // A shape check, not just "is it JSON": a snapshot from a different
  // contract, or a stray non-object value, is refused rather than
  // rendered as if it were real model data.
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  if (payload.contract !== "model_registry_snapshot") return null;
  if (!Array.isArray(payload.models)) return null;

  return payload;
}
