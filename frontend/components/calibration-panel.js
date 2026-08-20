// <avl-calibration-panel> — set `.record` to a shape matching
// aarya_voice_lab.identity.calibration.CalibrationRecord.to_dict()-like
// data: { state, evidence, threshold, sample_size, note }, or leave unset
// for the honest default: UNCALIBRATED, no evidence. This component must
// NEVER fabricate a score or upgrade a state — it renders exactly what
// it's given, through the "calibration" status-vocabulary domain, which
// mirrors CalibrationState exactly (see tokens/status.json).
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";
import "./metric-placeholder.js";

export class AvlCalibrationPanel extends AvlElement {
  set record(value) {
    this._record = value || null;
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
      .panel { display: flex; flex-direction: column; gap: var(--avl-space-2); }
      .row { display: flex; align-items: center; gap: var(--avl-space-2); }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
    `;
    this.shadowRoot.appendChild(style);

    const record = this._record || { state: "UNCALIBRATED", evidence: "none", threshold: null, sample_size: null };

    const panel = document.createElement("div");
    panel.className = "panel";

    const row = document.createElement("div");
    row.className = "row";
    const badge = document.createElement("avl-status-badge");
    badge.setAttribute("domain", "calibration");
    badge.setAttribute("state", record.state || "UNCALIBRATED");
    row.appendChild(badge);
    panel.appendChild(row);

    const threshold = document.createElement("avl-metric-placeholder");
    threshold.setAttribute("label", "Threshold");
    if (record.threshold != null) threshold.setAttribute("value", String(record.threshold));

    const sampleSize = document.createElement("avl-metric-placeholder");
    sampleSize.setAttribute("label", "Evidence sample size");
    if (record.sample_size != null) sampleSize.setAttribute("value", String(record.sample_size));

    panel.append(threshold, sampleSize);

    const note = document.createElement("div");
    note.className = "note";
    note.textContent =
      record.state === "UNCALIBRATED"
        ? "No evidence. Thresholds are defaults chosen for safety, not measurement."
        : record.evidence
          ? `Evidence: ${record.evidence.replace(/_/g, " ")}`
          : "";
    if (note.textContent) panel.appendChild(note);

    this.shadowRoot.appendChild(panel);
  }
}

defineComponent("avl-calibration-panel", AvlCalibrationPanel);
