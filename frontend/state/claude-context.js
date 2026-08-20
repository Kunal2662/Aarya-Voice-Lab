// Builds the structured context object sent to Claude Code (VL-D1 §15),
// per the interface frontend/contracts/claude-context-model.json declared
// in VL-D0. Only the fields that model names are included, each bounded,
// and every string value passes through a redaction scan before leaving
// this module — defense in depth on top of "only ever pass what's
// already in the UI's own state," since nothing here reads the
// filesystem or any backend store directly.

const SENSITIVE_KEY_FRAGMENTS = ["secret", "credential", "password", "token", "api_key", "apikey", "private_key"];

// Long opaque-looking strings (hex/base64-ish runs of 20+ chars) are
// masked even in fields that passed the key-name check, in case a value
// itself looks like a credential regardless of its field name.
const OPAQUE_VALUE_PATTERN = /\b[A-Za-z0-9_\-]{20,}\b/g;

const MAX_RECENT_ACTIVITY = 10;
const MAX_STRING_LENGTH = 2000;

function redactValue(value) {
  if (typeof value !== "string") return value;
  const truncated = value.length > MAX_STRING_LENGTH ? `${value.slice(0, MAX_STRING_LENGTH)}…(truncated)` : value;
  return truncated.replace(OPAQUE_VALUE_PATTERN, (match) => {
    // Leave short, clearly-non-secret tokens (git short hashes are 7-12
    // hex chars) alone; only mask runs long enough to plausibly be a key.
    return match.length >= 20 ? "<redacted>" : match;
  });
}

function redactDeep(value) {
  if (value == null) return value;
  if (typeof value === "string") return redactValue(value);
  if (Array.isArray(value)) return value.map(redactDeep);
  if (typeof value === "object") {
    const out = {};
    for (const [key, val] of Object.entries(value)) {
      const keyLower = key.toLowerCase();
      if (SENSITIVE_KEY_FRAGMENTS.some((fragment) => keyLower.includes(fragment))) {
        out[key] = "<redacted: field name suggests a secret>";
        continue;
      }
      out[key] = redactDeep(val);
    }
    return out;
  }
  return value;
}

/**
 * @param {object} input
 * @param {string} input.destination - current workspace (see state/router.js DESTINATIONS)
 * @param {{kind:string,id:string,data:any}|null} [input.selection]
 * @param {Array<object>} [input.recentActivity]
 * @param {{branch:string,head_short:string,working_tree_clean:boolean}|null} [input.gitState]
 * @param {string|null} [input.taskId]
 * @param {string|null} [input.errorSummary]
 */
export function buildClaudeContext(input) {
  const context = {
    active_view: input.destination || null,
    selection: input.selection ? { kind: input.selection.kind, id: input.selection.id, data: input.selection.data } : null,
    recent_commands: [],
    recent_activity: (input.recentActivity || []).slice(0, MAX_RECENT_ACTIVITY).map((event) => ({
      source: event.source,
      severity: event.severity,
      summary: event.summary,
      timestamp: event.timestamp,
    })),
    git_state: input.gitState || null,
    task_id: input.taskId || null,
    error_summary: input.errorSummary || null,
    permissions: { max_risk_tier: "read_only" },
  };
  return redactDeep(context);
}

/**
 * Bounded context for an "Ask Claude" affordance scoped to one technical
 * review question (VL-D3 §25) — deliberately a narrower shape than
 * buildClaudeContext()'s general app-state snapshot. Only the fields the
 * spec names: recording/batch identity, pipeline stage, the specific
 * metric and warning/error being asked about, a relevant config
 * fragment, and provenance limited to hashes and relative-safe IDs.
 * Never a filesystem path, never a credential, never a speaker-identity
 * field — this surface stays inside the technical-review boundary (§3)
 * exactly like everything else Dataset Review renders.
 *
 * @param {object} input
 * @param {string|null} [input.recordingId]
 * @param {string|null} [input.batchId]
 * @param {string} [input.stage] - e.g. "quality_analysis", "segmentation", "overlap"
 * @param {{name:string,value:*}|null} [input.metric]
 * @param {string|null} [input.warning]
 * @param {string|null} [input.error]
 * @param {object|null} [input.config]
 * @param {{sourceSha256:string|null,configHash:string|null}|null} [input.provenance]
 */
export function buildReviewClaudeContext(input) {
  const context = {
    recording_id: input.recordingId || null,
    batch_id: input.batchId || null,
    stage: input.stage || null,
    metric: input.metric || null,
    warning: input.warning || null,
    error: input.error || null,
    config: input.config || null,
    provenance: input.provenance || null,
    permissions: { max_risk_tier: "read_only" },
  };
  return redactDeep(context);
}

export { redactDeep, redactValue };
