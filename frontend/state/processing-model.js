// Client-side voice-processing state (VL-D4 §5, §6, §16, §17, §18).
// Mirrors pipeline.processing / pipeline.processing_profile /
// pipeline.processing_history's vocabulary and append-only semantics
// exactly, but this is a session-scoped, in-memory simulation over
// state/synthetic-fixtures.js data -- there is still no execution
// transport (state/command-executor.js, unchanged since VL-D1) to
// actually run FFmpeg or write a derived artifact into data/working/.
// "Processing" an item here replays the fixture outcome already
// recorded for that recording id (or an honest generic NO_PROCESSING
// result for a recording the fixtures don't cover) after a short,
// clearly-labelled simulated delay -- it never fabricates a specific
// measurement or artifact hash for audio nobody actually processed.
// `exportProcessingPlan()` bridges the same way VL-D2/VL-D3's
// export*Plan() functions do: JSON shaped closely enough to the
// backend's records that an operator can hand it to a future CLI
// command, never a claim that anything was actually written to disk.

import { syntheticProcessingItems } from "./synthetic-fixtures.js";

export const ProcessingStatus = Object.freeze({
  QUEUED: "QUEUED",
  PREPARING: "PREPARING",
  PROCESSING: "PROCESSING",
  QUALITY_CHECK: "QUALITY_CHECK",
  SUCCESS: "SUCCESS",
  WARNING: "WARNING",
  FAILED: "FAILED",
  BLOCKED: "BLOCKED",
  CANCELLED: "CANCELLED",
});

const TERMINAL_STATUSES = new Set([
  ProcessingStatus.SUCCESS,
  ProcessingStatus.WARNING,
  ProcessingStatus.FAILED,
  ProcessingStatus.BLOCKED,
  ProcessingStatus.CANCELLED,
]);

export function isTerminalProcessingStatus(status) {
  return TERMINAL_STATUSES.has(status);
}

export const ProcessingDecision = Object.freeze({
  NO_PROCESSING: "NO_PROCESSING",
  LIGHT_CONDITIONING: "LIGHT_CONDITIONING",
  STANDARD_CONDITIONING: "STANDARD_CONDITIONING",
  REVIEW_REQUIRED: "REVIEW_REQUIRED",
});

export const NoiseConditioningMode = Object.freeze({
  OFF: "OFF",
  MEASURE_ONLY: "MEASURE_ONLY",
  LIGHT: "LIGHT",
  STANDARD: "STANDARD",
});

// Mirrors pipeline.feedback.ProcessingFeedbackCategory exactly (VL-D4 §28).
export const ProcessingFeedbackCategory = Object.freeze({
  TOO_AGGRESSIVE: "TOO_AGGRESSIVE",
  TOO_NOISY: "TOO_NOISY",
  TOO_QUIET: "TOO_QUIET",
  OVER_PROCESSED: "OVER_PROCESSED",
  UNDER_PROCESSED: "UNDER_PROCESSED",
  BOUNDARY_INCORRECT: "BOUNDARY_INCORRECT",
  QUALITY_DEGRADED: "QUALITY_DEGRADED",
  GOOD_RESULT: "GOOD_RESULT",
  OTHER: "OTHER",
});

/** Versioned, named processing profiles (VL-D4 §22). Mirrors
 * pipeline.processing_profile.ProcessingProfileRegistry: create()
 * refuses a duplicate name, every subsequent change goes through
 * createVersion(), which always appends rather than editing. */
export class ProcessingProfileStore extends EventTarget {
  constructor() {
    super();
    /** @type {Map<string, object[]>} */
    this._versions = new Map();
    this._defaultName = null;
  }

  create(name, fields = {}) {
    if (this._versions.has(name)) {
      throw new Error(`profile ${name} already exists; use createVersion() to change it`);
    }
    const profile = { profileId: `${name}-v1`, name, version: 1, ...fields };
    this._versions.set(name, [profile]);
    if (this._defaultName === null) this._defaultName = name;
    this._announce(profile);
    return profile;
  }

  createVersion(name, overrides = {}) {
    const versions = this._versions.get(name);
    if (!versions) throw new Error(`no profile named ${name}`);
    const base = versions[versions.length - 1];
    const nextVersion = base.version + 1;
    const profile = { ...base, ...overrides, profileId: `${name}-v${nextVersion}`, name, version: nextVersion };
    versions.push(profile);
    this._announce(profile);
    return profile;
  }

  duplicate(name, newName) {
    const source = this.latest(name);
    const { profileId, name: _n, version, ...rest } = source;
    return this.create(newName, rest);
  }

  latest(name) {
    const versions = this._versions.get(name);
    if (!versions) throw new Error(`no profile named ${name}`);
    return versions[versions.length - 1];
  }

  history(name) {
    return [...(this._versions.get(name) || [])];
  }

  names() {
    return [...this._versions.keys()];
  }

  allLatest() {
    return this.names().map((name) => this.latest(name));
  }

  setDefault(name) {
    if (!this._versions.has(name)) throw new Error(`no profile named ${name}`);
    this._defaultName = name;
    this.dispatchEvent(new CustomEvent("change", { detail: { defaultName: name } }));
  }

  default() {
    return this._defaultName ? this.latest(this._defaultName) : null;
  }

  _announce(profile) {
    this.dispatchEvent(new CustomEvent("change", { detail: { profile } }));
  }
}

let _itemCounter = 0;

/** Session-only processing queue (VL-D4 §5). See module docstring for
 * exactly what "processing" means here -- a labelled replay of fixture
 * data, never a real FFmpeg/audio operation. */
export class ProcessingQueueStore extends EventTarget {
  constructor() {
    super();
    /** @type {object[]} */
    this._items = [];
  }

  enqueue({ recordingId, profile }) {
    _itemCounter += 1;
    const item = {
      itemId: `session-proc-${String(_itemCounter).padStart(4, "0")}`,
      recordingId,
      profileId: profile.profileId,
      status: ProcessingStatus.QUEUED,
      progress: 0,
      currentOperation: null,
      warnings: [],
      errors: [],
      decision: null,
      processingDurationSeconds: null,
      derivedArtifact: null,
      qualityBefore: null,
      qualityAfter: null,
    };
    this._items.push(item);
    this._announce(item);
    return item;
  }

  cancel(itemId) {
    const item = this.get(itemId);
    if (item && item.status === ProcessingStatus.QUEUED) {
      item.status = ProcessingStatus.CANCELLED;
      this._announce(item);
    }
    return item;
  }

  /** Replays the fixture outcome for this item's recording id, in
   * stages, so the UI can show real state transitions -- never a claim
   * that real audio was processed. */
  async processOne(itemId, { stepDelayMs = 150 } = {}) {
    const item = this.get(itemId);
    if (!item || item.status === ProcessingStatus.CANCELLED) return item;

    const fixture = syntheticProcessingItems()[item.recordingId];
    const started = performance.now();

    for (const [status, operation] of [
      [ProcessingStatus.PREPARING, "verifying source"],
      [ProcessingStatus.PROCESSING, "boundary conditioning + normalization"],
      [ProcessingStatus.QUALITY_CHECK, "quality re-check"],
    ]) {
      item.status = status;
      item.currentOperation = operation;
      item.progress = status === ProcessingStatus.QUALITY_CHECK ? 0.9 : item.progress + 0.3;
      this._announce(item);
      await new Promise((resolve) => setTimeout(resolve, stepDelayMs));
    }

    if (fixture) {
      item.status = fixture.status;
      item.warnings = [...fixture.warnings];
      item.errors = [...fixture.errors];
      item.decision = fixture.decision;
      item.derivedArtifact = fixture.derivedArtifact;
      item.qualityBefore = fixture.qualityBefore;
      item.qualityAfter = fixture.qualityAfter;
    } else {
      // Honest generic outcome for a recording the fixtures don't cover
      // -- never a fabricated measurement or artifact hash.
      item.status = ProcessingStatus.SUCCESS;
      item.decision = ProcessingDecision.NO_PROCESSING;
      item.warnings = ["No fixture data for this recording; outcome is a generic placeholder, not a real result."];
    }
    item.currentOperation = null;
    item.progress = 1;
    item.processingDurationSeconds = (performance.now() - started) / 1000;
    this._announce(item);
    return item;
  }

  retry(itemId, { profile } = {}) {
    const item = this.get(itemId);
    if (!item) return item;
    if (profile) item.profileId = profile.profileId;
    item.status = ProcessingStatus.QUEUED;
    item.warnings = [];
    item.errors = [];
    item.derivedArtifact = null;
    this._announce(item);
    return this.processOne(itemId);
  }

  list() {
    return [...this._items];
  }

  get(itemId) {
    return this._items.find((i) => i.itemId === itemId) || null;
  }

  counts() {
    const counts = Object.fromEntries(Object.values(ProcessingStatus).map((s) => [s, 0]));
    for (const item of this._items) counts[item.status] += 1;
    return counts;
  }

  /** VL-D9 -- restores only items in a *terminal* status
   * (isTerminalProcessingStatus). An item still QUEUED/PREPARING/
   * PROCESSING/QUALITY_CHECK reflects an async replay
   * (processOne()/setTimeout chain) that no longer exists after a page
   * reload -- restoring it would freeze a spinner on screen forever and
   * imply work is still happening when it isn't. This is a documented
   * exclusion, not an oversight: see docs/VLD9_SESSION_PERSISTENCE.md.
   * Non-terminal items and any item missing itemId/recordingId are
   * dropped. Returns true only if at least one item was restored. */
  hydrate(items) {
    if (!Array.isArray(items)) return false;
    const restored = items
      .filter(
        (i) => i && typeof i.itemId === "string" && typeof i.recordingId === "string" && isTerminalProcessingStatus(i.status),
      )
      .map((i) => ({ ...i }));
    if (!restored.length) return false;
    this._items = restored;
    const maxCounter = Math.max(0, ...restored.map((i) => parseInt((i.itemId || "").split("-").pop() || "0", 10) || 0));
    if (maxCounter > _itemCounter) _itemCounter = maxCounter;
    return true;
  }

  /** VL-D9 -- clears this store's queue in place (same object identity)
   * and announces a detail-less "change" so mounted UI re-renders
   * immediately. Backs the explicit "Clear session data" control. */
  reset() {
    this._items = [];
    this.dispatchEvent(new CustomEvent("change", { detail: {} }));
  }

  _announce(item) {
    this.dispatchEvent(new CustomEvent("change", { detail: { item } }));
  }
}

let _historyCounter = 0;

/** Append-only processing history (VL-D4 §16, §18). Mirrors
 * pipeline.processing_history: rollback() never deletes or edits,
 * it appends a new record pointing at a prior version's output. */
export class ProcessingHistoryStore extends EventTarget {
  constructor() {
    super();
    /** @type {object[]} */
    this._records = [];
  }

  record({ recordingId, item, supersedes = null }) {
    _historyCounter += 1;
    const record = {
      recordId: `session-proc-hist-${String(_historyCounter).padStart(4, "0")}`,
      recordingId,
      artifactId: item.derivedArtifact ? item.derivedArtifact.artifactId : "",
      outputSha256: item.derivedArtifact ? item.derivedArtifact.outputSha256 : null,
      profileId: item.profileId,
      status: item.status,
      supersedes,
      isRollback: false,
      recordedAt: new Date().toISOString(),
    };
    this._records.push(record);
    this._announce(record);
    return record;
  }

  history(recordingId) {
    return this._records.filter((r) => r.recordingId === recordingId);
  }

  current(recordingId) {
    const records = this.history(recordingId);
    return records.length ? records[records.length - 1] : null;
  }

  rollback(recordingId, toRecordId) {
    const target = this._records.find((r) => r.recordId === toRecordId && r.recordingId === recordingId);
    if (!target) throw new Error(`no history record ${toRecordId} for ${recordingId}`);
    const active = this.current(recordingId);
    _historyCounter += 1;
    const record = {
      recordId: `session-proc-hist-${String(_historyCounter).padStart(4, "0")}`,
      recordingId,
      artifactId: target.artifactId,
      outputSha256: target.outputSha256,
      profileId: target.profileId,
      status: target.status,
      supersedes: active ? active.recordId : null,
      isRollback: true,
      recordedAt: new Date().toISOString(),
    };
    this._records.push(record);
    this._announce(record);
    return record;
  }

  all() {
    return [...this._records];
  }

  /** VL-D9 -- append-only history records are always terminal by
   * construction (record() is only ever called with a finished item), so
   * every well-shaped record here is restored -- no status filter
   * needed. A record missing recordId/recordingId is dropped. */
  hydrate(records) {
    if (!Array.isArray(records)) return false;
    const restored = records
      .filter((r) => r && typeof r.recordId === "string" && typeof r.recordingId === "string")
      .map((r) => ({ ...r }));
    if (!restored.length) return false;
    this._records = restored;
    const maxCounter = Math.max(
      0,
      ...restored.map((r) => parseInt((r.recordId || "").split("-").pop() || "0", 10) || 0),
    );
    if (maxCounter > _historyCounter) _historyCounter = maxCounter;
    return true;
  }

  /** VL-D9 -- see ProcessingQueueStore.reset() above. */
  reset() {
    this._records = [];
    this.dispatchEvent(new CustomEvent("change", { detail: {} }));
  }

  _announce(record) {
    this.dispatchEvent(new CustomEvent("change", { detail: { record } }));
  }
}

export function exportProcessingPlan(queueStore, historyStore) {
  return {
    is_synthetic: true,
    generated_by: "frontend client-side processing model (session-only, not authoritative)",
    processing_items: queueStore.list(),
    processing_history: historyStore.all(),
  };
}

/** VL-D9 -- restores both stores from a previously exportProcessingPlan()'d
 * payload. Returns true if either store restored at least one record. */
export function hydrateProcessingPlan(queueStore, historyStore, plan) {
  if (!plan || typeof plan !== "object") return false;
  const a = queueStore.hydrate(plan.processing_items);
  const b = historyStore.hydrate(plan.processing_history);
  return a || b;
}
