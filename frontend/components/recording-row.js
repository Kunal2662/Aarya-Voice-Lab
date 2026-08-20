// <avl-recording-row> — set `.recording` to a recording-shaped object
// (see state/synthetic-fixtures.js syntheticRecordings()). Shows only
// technical/provenance fields — format, duration, sample rate, quality,
// processing state — and deliberately has no field for speaker identity:
// Phase 2 candidate data must never carry it (see pipeline/stages.py's
// SPEAKER_IDENTITY_BOUNDARY). Selecting dispatches `avl-recording-select`.
import { AvlElement, defineComponent } from "./base-element.js";
import { JOB_STATUS_DOMAIN } from "../state/job-model.js";
import "./status-badge.js";

function formatDuration(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export class AvlRecordingRow extends AvlElement {
  set recording(value) {
    this._recording = value || null;
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
      .row {
        display: flex; align-items: center; gap: var(--avl-space-3);
        padding: var(--avl-space-2) var(--avl-space-3);
        border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-sm);
        background: var(--avl-color-surface-raised); cursor: pointer; width: 100%; text-align: left;
        font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family);
        color: var(--avl-color-text-primary);
      }
      .row:hover { background: var(--avl-color-surface-sunken); }
      .id { font: var(--avl-type-code-weight) var(--avl-type-code-size) / 1 var(--avl-type-code-family); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .meta { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); }
    `;
    this.shadowRoot.appendChild(style);

    const recording = this._recording;
    if (!recording) return;

    const row = document.createElement("button");
    row.type = "button";
    row.className = "row";

    const id = document.createElement("span");
    id.className = "id";
    id.textContent = recording.contentAddressedId;

    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = `${recording.format} · ${formatDuration(recording.durationSeconds)} · ${recording.sampleRate}Hz`;

    const badge = document.createElement("avl-status-badge");
    badge.setAttribute("domain", JOB_STATUS_DOMAIN);
    badge.setAttribute("state", recording.processingState === "candidate_manifest" ? "success" : "running");

    row.append(id, meta, badge);
    row.addEventListener("click", () => {
      this.dispatchEvent(
        new CustomEvent("avl-recording-select", { detail: { recordingId: recording.id }, bubbles: true, composed: true }),
      );
    });

    this.shadowRoot.appendChild(row);
  }
}

defineComponent("avl-recording-row", AvlRecordingRow);
