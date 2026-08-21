// <avl-calibration-readiness-panel> -- VL-D7. Set `.readiness` to a
// state/calibration-engine-model.js assessReadiness()-shaped object.
// Renders exactly the real evidence counts and reasons the assessment
// produced -- never a fabricated "ready" verdict beyond what the real
// evaluation count actually supports.
import { AvlElement, defineComponent } from "./base-element.js";
import "./metric-placeholder.js";

export class AvlCalibrationReadinessPanel extends AvlElement {
  set readiness(value) {
    this._readiness = value || null;
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
      .metrics { display: flex; gap: var(--avl-space-4); flex-wrap: wrap; }
      .reasons { margin: 0; padding-left: var(--avl-space-4); }
      .reasons li { color: var(--avl-color-text-secondary); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .sufficient { color: var(--avl-color-state-success); }
      .insufficient { color: var(--avl-color-state-warning); }
    `;
    this.shadowRoot.appendChild(style);

    const readiness = this._readiness;
    if (!readiness) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No readiness assessment yet.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const panel = document.createElement("div");
    panel.className = "panel";

    const verdict = document.createElement("p");
    verdict.className = readiness.evidence_sufficient_for_provisional ? "sufficient" : "insufficient";
    verdict.textContent = readiness.evidence_sufficient_for_provisional
      ? "Evidence sufficient for PROVISIONAL evidence state."
      : "Evidence insufficient -- hardware-only calibration only.";
    panel.appendChild(verdict);

    const metrics = document.createElement("div");
    metrics.className = "metrics";
    const evalMetric = document.createElement("avl-metric-placeholder");
    evalMetric.setAttribute("label", "Evaluations");
    evalMetric.setAttribute("value", String(readiness.total_evaluations));
    const outputsMetric = document.createElement("avl-metric-placeholder");
    outputsMetric.setAttribute("label", "Outputs evaluated");
    outputsMetric.setAttribute("value", String(readiness.total_outputs_evaluated));
    const previewMetric = document.createElement("avl-metric-placeholder");
    previewMetric.setAttribute("label", "Preview feedback");
    previewMetric.setAttribute("value", String(readiness.total_preview_feedback));
    metrics.append(evalMetric, outputsMetric, previewMetric);
    panel.appendChild(metrics);

    if (readiness.reasons && readiness.reasons.length) {
      const reasons = document.createElement("ul");
      reasons.className = "reasons";
      for (const reason of readiness.reasons) {
        const li = document.createElement("li");
        li.textContent = reason;
        reasons.appendChild(li);
      }
      panel.appendChild(reasons);
    }

    const note = document.createElement("p");
    note.className = "note";
    note.textContent = readiness.note;
    panel.appendChild(note);

    this.shadowRoot.appendChild(panel);
  }
}

defineComponent("avl-calibration-readiness-panel", AvlCalibrationReadinessPanel);
