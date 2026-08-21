// VL-D10 -- fetches the live Claude Command Center snapshot
// (frontend/contracts/live/command_center_snapshot.json, written by
// scripts/export_command_center_snapshot.py from the real, tested
// identity.command_center.command_center_snapshot()). Same honest
// "missing/malformed/wrong-shape -> null, never thrown, never
// fabricated" pattern already established by
// state/session-persistence.js's envelope validation and
// workspace-import.js's dataset-gate fetch. Pulled out of
// workspace-claude.js into its own module so this fetch-and-parse logic
// is unit-testable without a browser DOM (see
// tests/command-center-snapshot.test.mjs).
export async function fetchCommandCenterSnapshot(url) {
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
  // rendered as if it were real repository/activity/diagnostics data.
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  if (payload.contract !== "command_center_snapshot") return null;

  return payload;
}
