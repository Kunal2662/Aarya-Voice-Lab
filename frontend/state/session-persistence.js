// VL-D9 -- Local session persistence.
//
// Every prior phase (VL-D2 through VL-D8) documented the same limitation
// under "Known limitations": all frontend state is session-only, because
// there is still no execution transport (state/command-executor.js) to
// persist anything to the backend. VL-D9 does not add one. Instead it
// extends theme-toggle.js's pre-existing pattern -- the only localStorage
// usage in this app before VL-D9 -- from a single UI preference to a
// versioned envelope per store, so a browser reload can restore what the
// user already had on screen. Local-only, browser-local, additive,
// deterministic, bounded, explicit, non-cloud, non-executing: there is no
// network call anywhere in this module, no account, no server, and
// nothing here can run a command (see state/command-executor.js's
// NullCommandExecutor, unchanged).
//
// What gets saved is always exactly one of the pre-existing
// export*Plan()-shaped objects (exportImportPlan/exportReviewPlan/
// exportProcessingPlan/exportGenerationPlan/exportEvaluationPlan/
// exportCalibrationPlan) -- the same "UI validates, CLI executes" bridge
// shape every store already produces, reused rather than re-invented as a
// second serialization format. This module never inspects or rewrites
// those payloads; the field-level "is this safe to persist" decision is
// made once, in each store's own hydrate() method, next to the fields it
// already knows the shape of. See docs/VLD9_SESSION_PERSISTENCE.md for
// the full per-store safe/excluded field list.

export const SESSION_SCHEMA_VERSION = 1;

const KEY_PREFIX = "avl-session-v1:";

/** One namespaced localStorage key per store, mirroring the "UI
 * validates, CLI executes" split each export*Plan() already has -- no
 * single combined blob, so one store's malformed data can never corrupt
 * another's (see namespace-isolation tests). */
export const SessionNamespace = Object.freeze({
  IMPORT: "import",
  REVIEW: "review",
  PROCESSING: "processing",
  GENERATION: "generation",
  EVALUATION: "evaluation",
  CALIBRATION: "calibration",
});

function storageKey(namespace) {
  return `${KEY_PREFIX}${namespace}`;
}

/** True only when window.localStorage exists AND a real write/remove
 * round-trips. Private browsing, storage-disabled contexts, and some
 * embedders expose a localStorage object that throws on use -- checking
 * for its mere presence would be dishonest, so this always performs one
 * real probe write. */
export function isPersistenceAvailable() {
  try {
    if (typeof localStorage === "undefined" || localStorage === null) return false;
    const probeKey = `${KEY_PREFIX}__probe__`;
    localStorage.setItem(probeKey, "1");
    localStorage.removeItem(probeKey);
    return true;
  } catch {
    return false;
  }
}

/** Local-only, per-namespace envelope persistence. Every operation is
 * defensive by design: a save that fails (quota exceeded, storage
 * disabled, a payload that somehow isn't JSON-serializable) returns
 * false rather than throwing, so a persistence failure can never break
 * the UI action that triggered it; a load that finds anything malformed
 * -- invalid JSON, wrong shape, wrong namespace, an incompatible
 * schema_version -- returns null rather than guessing, so a corrupted or
 * stale entry is never restored as if it were valid. */
export class SessionPersistence {
  constructor(namespace) {
    if (!Object.values(SessionNamespace).includes(namespace)) {
      throw new Error(`unknown SessionNamespace: ${namespace}`);
    }
    this.namespace = namespace;
    this._key = storageKey(namespace);
  }

  isAvailable() {
    return isPersistenceAvailable();
  }

  /** Wraps `payload` (an already export*Plan()-shaped, JSON-safe object)
   * in a versioned envelope and writes it. Returns true on success,
   * false on any failure. */
  save(payload) {
    if (!this.isAvailable()) return false;
    const envelope = {
      schema_version: SESSION_SCHEMA_VERSION,
      namespace: this.namespace,
      saved_at: new Date().toISOString(),
      payload,
    };
    try {
      localStorage.setItem(this._key, JSON.stringify(envelope));
      return true;
    } catch {
      // Quota exceeded, storage disabled mid-session, or a payload that
      // turned out not to be serializable -- an honest false, never a
      // thrown error the caller didn't ask to handle.
      return false;
    }
  }

  /** Returns the envelope's `payload`, or null when nothing is stored,
   * storage is unavailable, the stored value is not valid JSON, the
   * envelope shape is wrong, its namespace doesn't match this instance,
   * or its schema_version is not the one this code understands. */
  load() {
    if (!this.isAvailable()) return null;
    let raw;
    try {
      raw = localStorage.getItem(this._key);
    } catch {
      return null;
    }
    if (raw == null) return null;

    let envelope;
    try {
      envelope = JSON.parse(raw);
    } catch {
      return null;
    }
    if (!envelope || typeof envelope !== "object" || Array.isArray(envelope)) return null;
    if (envelope.namespace !== this.namespace) return null;
    if (envelope.schema_version !== SESSION_SCHEMA_VERSION) return null;
    if (!("payload" in envelope)) return null;
    return envelope.payload;
  }

  hasSession() {
    if (!this.isAvailable()) return false;
    try {
      return localStorage.getItem(this._key) != null;
    } catch {
      return false;
    }
  }

  clear() {
    if (!this.isAvailable()) return false;
    try {
      localStorage.removeItem(this._key);
      return true;
    } catch {
      return false;
    }
  }

  /** Hook for a future schema_version upgrade to migrate an old envelope
   * forward. VL-D9 is the first schema version this app has ever
   * written, so there is nothing to migrate from yet -- load() already
   * refuses (returns null for) a mismatched version rather than
   * guessing at its shape, which is the correct behaviour until a real
   * migration path is written here. */
  migrate(_envelope) {
    return null;
  }
}

/** Clears every namespace this app owns -- and nothing else. Iterates
 * the fixed, bounded SessionNamespace set rather than scanning
 * localStorage for keys matching a prefix, so this can never remove a
 * key some other code (or a future feature) happens to store under a
 * similar-looking name. Backs Task #190's explicit "Clear session data"
 * control -- never called automatically. */
export function clearAllSessionData() {
  let clearedAny = false;
  for (const namespace of Object.values(SessionNamespace)) {
    if (new SessionPersistence(namespace).clear()) clearedAny = true;
  }
  return clearedAny;
}

export function hasAnySessionData() {
  return Object.values(SessionNamespace).some((namespace) => new SessionPersistence(namespace).hasSession());
}
