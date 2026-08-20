// Unified activity timeline model (VL-D1 §13). Renders through the
// "activity_severity" status-vocabulary domain for severity, and a
// closed ActivitySource list for where an event came from. Sourced from
// the existing audit architecture (identity/command_center.py's
// activity_feed(), which already reads the sanitised audit log) where
// available; VL-D1 also accepts synthetic-fixture events for sources the
// backend doesn't emit yet (import, pipeline stage progress, etc.).

export const ActivitySource = Object.freeze({
  IMPORT: "import",
  VALIDATION: "validation",
  QUALITY: "quality",
  VAD: "vad",
  SEGMENTATION: "segmentation",
  REVIEW: "review",
  // VL-D4 §26 — processing/conditioning events (boundary trim,
  // normalization, noise-conditioning decision, quality re-check).
  PROCESSING: "processing",
  SPEAKER_VERIFICATION: "speaker_verification",
  MODEL: "model",
  CALIBRATION: "calibration",
  PREVIEW: "preview",
  CLAUDE: "claude",
  SYSTEM: "system",
  SECURITY: "security",
  ERROR: "error",
});

export const ActivitySeverity = Object.freeze({
  INFO: "info",
  SUCCESS: "success",
  WARNING: "warning",
  DANGER: "danger",
});

/** @typedef {{id:string,timestamp:string,severity:string,source:string,status:string|null,summary:string,details:string|null}} ActivityEvent */

/** @param {Partial<ActivityEvent> & {id:string,summary:string,source:string}} fields */
export function createActivityEvent(fields) {
  if (!fields.id || !fields.summary || !fields.source) {
    throw new Error("createActivityEvent requires at least { id, summary, source }");
  }
  return {
    id: fields.id,
    timestamp: fields.timestamp || new Date().toISOString(),
    severity: fields.severity || ActivitySeverity.INFO,
    source: fields.source,
    status: fields.status ?? null,
    summary: fields.summary,
    details: fields.details ?? null,
  };
}

/**
 * Adapts one aarya_voice_lab.identity.command_center.ActivityEntry.to_dict()
 * record into this module's ActivityEvent shape. Already-sanitised by the
 * backend (no vectors, no absolute paths) — this function reshapes only,
 * it does not redact anything further.
 */
export function fromCommandCenterEntry(entry) {
  return createActivityEvent({
    id: `${entry.kind}-${entry.timestamp}-${entry.subject_id ?? ""}`,
    timestamp: entry.timestamp,
    severity: ActivitySeverity.INFO,
    source: ActivitySource.SYSTEM,
    status: entry.kind,
    summary: entry.summary,
    details: Object.keys(entry.detail || {}).length ? JSON.stringify(entry.detail) : null,
  });
}

/** In-memory, event-based activity store. Read/append only — no execution. */
export class ActivityStore extends EventTarget {
  constructor(initialEvents = []) {
    super();
    /** @type {ActivityEvent[]} */
    this._events = [...initialEvents];
  }

  append(event) {
    this._events.push(event);
    this.dispatchEvent(new CustomEvent("change", { detail: { event } }));
    return event;
  }

  list({ source, severity, limit } = {}) {
    let events = [...this._events].sort((a, b) => b.timestamp.localeCompare(a.timestamp));
    if (source) events = events.filter((e) => e.source === source);
    if (severity) events = events.filter((e) => e.severity === severity);
    if (limit) events = events.slice(0, limit);
    return events;
  }
}
