// D11 audit follow-up -- fetches the live identity/enrollment status
// snapshot (frontend/contracts/live/identity_status_snapshot.json,
// written by scripts/export_identity_status_snapshot.py from the real,
// tested identity.contracts.desktop_snapshot()). Same honest
// "missing/malformed/wrong-shape -> null, never thrown, never
// fabricated" pattern as state/command-center-snapshot.js
// (fetchCommandCenterSnapshot), which this deliberately mirrors line for
// line so the two fetchers stay obviously equivalent in behavior.
export async function fetchIdentityStatusSnapshot(url) {
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
  // rendered as if it were real identity/enrollment data.
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  if (payload.contract !== "desktop_snapshot") return null;

  return payload;
}
