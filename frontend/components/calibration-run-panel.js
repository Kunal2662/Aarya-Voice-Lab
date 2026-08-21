// <avl-calibration-run-panel> -- VL-D7. Set `.calibrationStore` (a
// state/calibration-engine-model.js CalibrationProfileStore),
// `.capabilities` (Capability[] fixture), `.evaluationStore`,
// `.evaluationSummary`/`.previewSummary` (pipeline.calibration_prep-
// shaped summaries), and `.outputsWithDisagreementFn`. Renders the
// current profile's two independent badges side by side and labeled
// clearly so they are never mistaken for one another: run_state
// (process — did the engine finish?) via the "hardware_calibration"
// status domain, and calibration_state (evidence — is there real
// evidence?) via the "calibration" domain that mirrors
// identity.calibration.CalibrationState exactly. A CALIBRATED run next
// to an UNCALIBRATED or PROVISIONAL evidence badge is the expected,
// honest outcome when evaluation evidence is thin -- this component
// never hides or merges the two to make that combination look wrong.
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";
import "./button.js";
import "./metric-placeholder.js";

export class AvlCalibrationRunPanel extends AvlElement {
  set calibrationStore(value) {
    if (this._calibrationStore) this._calibrationStore.removeEventListener("change", this._onChange);
    this._calibrationStore = value;
    if (value) {
      this._onChange = () => this._render();
      value.addEventListener("change", this._onChange);
    }
    if (this.isConnected) this._render();
  }

  set capabilities(value) {
    this._capabilities = Array.isArray(value) ? value : [];
  }

  set evaluationStore(value) {
    this._evaluationStore = value || null;
  }

  set evaluationSummary(value) {
    this._evaluationSummary = value || null;
  }

  set previewSummary(value) {
    this._previewSummary = value || null;
  }

  set outputsWithDisagreementFn(value) {
    this._outputsWithDisagreementFn = value || null;
  }

  connectedCallback() {
    this._render();
  }

  disconnectedCallback() {
    if (this._calibrationStore) this._calibrationStore.removeEventListener("change", this._onChange);
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .panel { display: flex; flex-direction: column; gap: var(--avl-space-3); }
      .badges { display: flex; gap: var(--avl-space-4); align-items: center; flex-wrap: wrap; }
      .badge-group { display: flex; flex-direction: column; gap: var(--avl-space-1); }
      .badge-label { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; }
      .metrics { display: flex; gap: var(--avl-space-4); flex-wrap: wrap; }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .limitations { margin: 0; padding-left: var(--avl-space-4); }
      .limitations li { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    const panel = document.createElement("div");
    panel.className = "panel";

    const runButton = document.createElement("avl-button");
    runButton.setAttribute("variant", "primary");
    runButton.textContent = "Run calibration";
    runButton.addEventListener("click", () => {
      if (!this._calibrationStore) return;
      this._calibrationStore.run({
        capabilities: this._capabilities || [],
        evaluationStore: this._evaluationStore,
        evaluationSummary: this._evaluationSummary,
        previewSummary: this._previewSummary,
        outputsWithDisagreementFn: this._outputsWithDisagreementFn,
      });
    });
    panel.appendChild(runButton);

    const profile = this._calibrationStore ? this._calibrationStore.current() : null;
    if (!profile) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No calibration run yet. Run state defaults to UNCALIBRATED until one completes.";
      panel.appendChild(empty);
      this.shadowRoot.appendChild(panel);
      return;
    }

    const badges = document.createElement("div");
    badges.className = "badges";

    const runGroup = document.createElement("div");
    runGroup.className = "badge-group";
    const runLabel = document.createElement("span");
    runLabel.className = "badge-label";
    runLabel.textContent = "Engine run state";
    const runBadge = document.createElement("avl-status-badge");
    runBadge.setAttribute("domain", "hardware_calibration");
    runBadge.setAttribute("state", profile.run_state);
    runGroup.append(runLabel, runBadge);
    badges.appendChild(runGroup);

    const evidenceGroup = document.createElement("div");
    evidenceGroup.className = "badge-group";
    const evidenceLabel = document.createElement("span");
    evidenceLabel.className = "badge-label";
    evidenceLabel.textContent = "Evidence state";
    const evidenceBadge = document.createElement("avl-status-badge");
    evidenceBadge.setAttribute("domain", "calibration");
    evidenceBadge.setAttribute("state", profile.calibration_state);
    evidenceGroup.append(evidenceLabel, evidenceBadge);
    badges.appendChild(evidenceGroup);

    panel.appendChild(badges);

    const metrics = document.createElement("div");
    metrics.className = "metrics";
    const strategyMetric = document.createElement("avl-metric-placeholder");
    strategyMetric.setAttribute("label", "Strategy");
    strategyMetric.setAttribute("value", profile.strategy);
    const agreementMetric = document.createElement("avl-metric-placeholder");
    agreementMetric.setAttribute("label", "Agreement rate");
    if (profile.agreement_rate != null) agreementMetric.setAttribute("value", `${(profile.agreement_rate * 100).toFixed(1)}%`);
    const coresMetric = document.createElement("avl-metric-placeholder");
    coresMetric.setAttribute("label", "Logical cores");
    if (profile.hardware_snapshot.logical_cores != null) {
      coresMetric.setAttribute("value", String(profile.hardware_snapshot.logical_cores));
    }
    const acceleratorMetric = document.createElement("avl-metric-placeholder");
    acceleratorMetric.setAttribute("label", "Accelerator confirmed");
    acceleratorMetric.setAttribute("value", profile.hardware_snapshot.accelerator_confirmed ? "yes" : "no");
    metrics.append(strategyMetric, agreementMetric, coresMetric, acceleratorMetric);
    panel.appendChild(metrics);

    if (profile.limitations && profile.limitations.length) {
      const limitations = document.createElement("ul");
      limitations.className = "limitations";
      for (const limitation of profile.limitations) {
        const li = document.createElement("li");
        li.textContent = limitation;
        limitations.appendChild(li);
      }
      panel.appendChild(limitations);
    }

    const note = document.createElement("p");
    note.className = "note";
    note.textContent = profile.hardware_snapshot.limitation;
    panel.appendChild(note);

    this.shadowRoot.appendChild(panel);
  }
}

defineComponent("avl-calibration-run-panel", AvlCalibrationRunPanel);
