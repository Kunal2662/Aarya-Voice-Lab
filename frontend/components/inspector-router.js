// <avl-inspector-router> — the Inspector's content (VL-D1 §22). Set
// `.selection` to a {kind, id, data} object from
// state/selection-model.js. Renders progressive disclosure: a compact
// summary always visible, with any longer/structured data (job logs
// reference, activity detail JSON) behind a native <details> so the
// panel never dumps everything at once.
import { AvlElement, defineComponent } from "./base-element.js";
import { JOB_STATUS_DOMAIN } from "../state/job-model.js";
import "./status-badge.js";
import "./metric-placeholder.js";

const RENDERERS = {
  batch: (data) => [
    ["Batch", data.id],
    ["Status", { badge: [JOB_STATUS_DOMAIN, data.status] }],
    ["Files", data.fileCount],
    ["Valid / warning / invalid / blocked", `${data.valid} / ${data.warning} / ${data.invalid} / ${data.blocked}`],
    ["Review items", data.reviewItems],
    ["Created", data.created],
  ],
  recording: (data) => [
    ["Content-addressed ID", data.contentAddressedId],
    ["Filename", data.filename],
    ["Format", data.format],
    ["Duration", `${data.durationSeconds}s`],
    ["Sample rate", `${data.sampleRate} Hz`],
    ["Channels", data.channels],
    ["Validation", data.validation],
    ["Quality", data.quality],
    ["Classification", data.classification],
    ["Batch", data.batchId],
    ["Pipeline status", { badge: [JOB_STATUS_DOMAIN, data.processingState === "candidate_manifest" ? "success" : "running"] }],
    // Future engines (VL-D3+). Never fabricated — always the honest
    // placeholder until a real analysis exists (VL-D2 §15).
    ["Speaker identity", "NOT AVAILABLE — behind the Phase 3+ speaker-identity boundary"],
    ["Accent fidelity", "NOT ANALYZED"],
    ["Pronunciation fidelity", "NOT ANALYZED"],
    ["Calibration", "NOT CALIBRATED"],
  ],
  "pipeline-stage": (data) => [
    ["Stage", data.name],
    ["Phase", data.phase],
    ["Implemented", data.implemented ? "yes" : "no"],
    ["Runtime status", { badge: [JOB_STATUS_DOMAIN, data.runtimeState || "not_started"] }],
    ["Logs reference", data.logsRef || "not available"],
  ],
  job: (data) => [
    ["Job", data.id],
    ["Type", data.type],
    ["Status", { badge: [JOB_STATUS_DOMAIN, data.status] }],
    ["Current stage", data.currentStage || "—"],
    ["Started", data.startTime || "—"],
    ["Ended", data.endTime || "—"],
    ["Related", data.relatedEntity ? `${data.relatedEntity.kind}:${data.relatedEntity.id}` : "—"],
    ["Logs reference", data.logsRef || "not available"],
    ["Error", data.error || "—"],
  ],
  activity: (data) => [
    ["Event", data.id],
    ["Source", data.source],
    ["Severity", { badge: ["activity_severity", data.severity] }],
    ["Timestamp", data.timestamp],
    ["Summary", data.summary],
  ],
  voice: (data) => [
    ["Voice", data.name],
    ["Version", data.version],
    ["Preview version", data.previewVersion],
    ["Feedback", data.feedback],
    ["Calibration state", { badge: ["calibration", data.calibrationState] }],
    ["Speaker verification", data.speakerVerificationState],
  ],
  model: (data) => [
    ["Model", data.name],
    ["Version", data.version],
    ["Runtime", data.runtime],
    ["Backend", data.backend],
    ["Hardware compatibility", data.hardwareCompatible],
    ["Status", { badge: ["hardware", (data.status || "unknown").toUpperCase()] }],
    ["Calibration state", { badge: ["calibration", data.calibrationState] }],
  ],
};

export class AvlInspectorRouter extends AvlElement {
  set selection(value) {
    this._selection = value || null;
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .rows { display: flex; flex-direction: column; gap: var(--avl-space-1); }
      .row { display: flex; justify-content: space-between; gap: var(--avl-space-2); padding: var(--avl-space-1) 0; border-bottom: 1px solid var(--avl-color-border-subtle); }
      .row:last-child { border-bottom: none; }
      .label { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); }
      .value { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); text-align: right; word-break: break-word; }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    const selection = this._selection;
    if (!selection || !RENDERERS[selection.kind]) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Nothing selected.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const rows = document.createElement("div");
    rows.className = "rows";
    for (const [label, value] of RENDERERS[selection.kind](selection.data || {})) {
      const row = document.createElement("div");
      row.className = "row";
      const labelEl = document.createElement("span");
      labelEl.className = "label";
      labelEl.textContent = label;
      row.appendChild(labelEl);

      if (value && typeof value === "object" && value.badge) {
        const badge = document.createElement("avl-status-badge");
        badge.setAttribute("domain", value.badge[0]);
        badge.setAttribute("state", value.badge[1]);
        row.appendChild(badge);
      } else {
        const valueEl = document.createElement("span");
        valueEl.className = "value";
        valueEl.textContent = value == null || value === "" ? "—" : String(value);
        row.appendChild(valueEl);
      }
      rows.appendChild(row);
    }
    this.shadowRoot.appendChild(rows);
  }
}

defineComponent("avl-inspector-router", AvlInspectorRouter);
