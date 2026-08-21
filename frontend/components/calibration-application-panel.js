// <avl-calibration-application-panel> -- VL-D8. Set `.calibrationStore`
// (a state/calibration-engine-model.js CalibrationProfileStore) and
// optionally `.generationQueueStore` (a state/generation-model.js
// GenerationQueueStore -- when supplied, Apply actually sets its real
// max_concurrent_generations value, exactly mirroring
// pipeline.calibration_engine.apply_adjustment(queue=...)).
//
// Renders the current profile's application_state
// (PROPOSED/APPLIED/VALIDATED) as a THIRD badge, deliberately never
// merged with run_state or calibration_state (see
// calibration-run-panel.js). Apply is only offered on a PROPOSED
// profile with an adjustment; Validate is only offered once APPLIED.
// The before/after panel renders exactly what
// validateCalibration()/validate_calibration() measured -- never a
// fabricated number, and honestly renders NOT_MEASURABLE when the
// fixture size can't show a difference.
import { AvlElement, defineComponent } from "./base-element.js";
import { ApplicationState } from "../state/calibration-engine-model.js";
import "./status-badge.js";
import "./button.js";
import "./metric-placeholder.js";

const APPLICATION_BADGE_STATE = {
  [ApplicationState.PROPOSED]: "NOT_TESTED",
  [ApplicationState.APPLIED]: "CALIBRATING",
  [ApplicationState.VALIDATED]: "CALIBRATED",
};

export class AvlCalibrationApplicationPanel extends AvlElement {
  set calibrationStore(value) {
    if (this._calibrationStore) this._calibrationStore.removeEventListener("change", this._onChange);
    this._calibrationStore = value;
    if (value) {
      this._onChange = () => this._render();
      value.addEventListener("change", this._onChange);
    }
    if (this.isConnected) this._render();
  }

  set generationQueueStore(value) {
    this._generationQueueStore = value || null;
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
      .badge-row { display: flex; align-items: center; gap: var(--avl-space-2); }
      .badge-label { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; }
      .actions { display: flex; gap: var(--avl-space-2); }
      .before-after { display: flex; gap: var(--avl-space-4); flex-wrap: wrap; }
      .not-measurable { color: var(--avl-color-state-warning); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .measured { color: var(--avl-color-state-success); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    const panel = document.createElement("div");
    panel.className = "panel";

    const profile = this._calibrationStore ? this._calibrationStore.current() : null;
    if (!profile) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Run a calibration pass before applying an adjustment.";
      panel.appendChild(empty);
      this.shadowRoot.appendChild(panel);
      return;
    }

    const badgeRow = document.createElement("div");
    badgeRow.className = "badge-row";
    const badgeLabel = document.createElement("span");
    badgeLabel.className = "badge-label";
    badgeLabel.textContent = "Application state";
    const badge = document.createElement("avl-status-badge");
    badge.setAttribute("domain", "hardware_calibration");
    badge.setAttribute("state", APPLICATION_BADGE_STATE[profile.application_state] || "UNKNOWN");
    const badgeText = document.createElement("span");
    badgeText.className = "avl-type-body-small";
    badgeText.textContent = profile.application_state;
    badgeRow.append(badgeLabel, badge, badgeText);
    panel.appendChild(badgeRow);

    const actions = document.createElement("div");
    actions.className = "actions";

    if (profile.application_state === ApplicationState.PROPOSED && (profile.adjustments || []).length) {
      const applyButton = document.createElement("avl-button");
      applyButton.setAttribute("variant", "primary");
      applyButton.textContent = "Apply";
      applyButton.addEventListener("click", () => {
        this._calibrationStore.applyAdjustment({
          profileId: profile.profile_id,
          parameterName: profile.adjustments[0].parameter_name,
          queue: this._generationQueueStore,
        });
      });
      actions.appendChild(applyButton);
    }

    if (profile.application_state === ApplicationState.APPLIED) {
      const validateButton = document.createElement("avl-button");
      validateButton.setAttribute("variant", "primary");
      validateButton.textContent = "Validate";
      validateButton.addEventListener("click", () => {
        this._calibrationStore.validateCalibration({ profileId: profile.profile_id });
      });
      actions.appendChild(validateButton);
    }

    if (actions.childElementCount) panel.appendChild(actions);

    if (profile.application_state === ApplicationState.APPLIED || profile.application_state === ApplicationState.VALIDATED) {
      const appliedMetrics = document.createElement("div");
      appliedMetrics.className = "before-after";
      const paramMetric = document.createElement("avl-metric-placeholder");
      paramMetric.setAttribute("label", "Applied parameter");
      paramMetric.setAttribute("value", profile.applied_parameter_name || "");
      const valueMetric = document.createElement("avl-metric-placeholder");
      valueMetric.setAttribute("label", "Applied value");
      if (profile.applied_value != null) valueMetric.setAttribute("value", String(profile.applied_value));
      appliedMetrics.append(paramMetric, valueMetric);
      panel.appendChild(appliedMetrics);
    }

    if (profile.application_state === ApplicationState.VALIDATED && profile.validation) {
      const v = profile.validation;
      const beforeAfter = document.createElement("div");
      beforeAfter.className = "before-after";
      const beforeMetric = document.createElement("avl-metric-placeholder");
      beforeMetric.setAttribute("label", "Before (batches)");
      if (v.before_batch_count != null) beforeMetric.setAttribute("value", String(v.before_batch_count));
      const afterMetric = document.createElement("avl-metric-placeholder");
      afterMetric.setAttribute("label", "After (batches)");
      if (v.after_batch_count != null) afterMetric.setAttribute("value", String(v.after_batch_count));
      const deltaMetric = document.createElement("avl-metric-placeholder");
      deltaMetric.setAttribute("label", "Measured delta");
      if (v.measured_delta != null) deltaMetric.setAttribute("value", String(v.measured_delta));
      beforeAfter.append(beforeMetric, afterMetric, deltaMetric);
      panel.appendChild(beforeAfter);

      const resultLine = document.createElement("p");
      resultLine.className = v.not_measurable ? "not-measurable" : "measured";
      resultLine.textContent = v.not_measurable ? "NOT_MEASURABLE" : "Measured";
      panel.appendChild(resultLine);

      const note = document.createElement("p");
      note.className = "note";
      note.textContent = v.note;
      panel.appendChild(note);
    }

    this.shadowRoot.appendChild(panel);
  }
}

defineComponent("avl-calibration-application-panel", AvlCalibrationApplicationPanel);
