// <avl-workspace-calibration> — VL-D1 §19, wired to real state in VL-D7.
// Three distinct calibration concepts, shown separately and labeled
// clearly so they are never confused:
//   1. AI Calibration Engine ("hardware_calibration" domain, VL-D7's
//      pipeline.calibration_engine.CalibrationRunState) — this host's
//      hardware snapshot, readiness, strategy, bounded parameter
//      proposals, and profile history/rollback. Session-only, driven by
//      state/calibration-engine-model.js over a synthetic hardware
//      fixture (see synthetic-fixtures.js's syntheticHardwareCapabilities) —
//      never a fabricated number, and never RTX/CUDA-specific.
//   2. Evidence state ("calibration" domain, identity.calibration.
//      CalibrationState, reused unchanged) — is there real evidence
//      behind the engine's profile? Rendered by avl-calibration-run-panel
//      right next to the run state, deliberately never merged into it.
//   3. Target-speaker verification calibration — reuses the VL-D0
//      avl-calibration-panel completely unchanged; a different axis
//      again (whether a verification threshold has held-out evidence).
import { AvlElement, defineComponent } from "./base-element.js";
import "./workspace-state.js";
import "./panel.js";
import "./status-badge.js";
import "./metric-placeholder.js";
import "./hardware-profile-card.js";
import "./calibration-panel.js";
import "./calibration-run-panel.js";
import "./calibration-readiness-panel.js";
import "./calibration-parameter-adjustments.js";
import "./calibration-application-panel.js";
import "./calibration-profile-history.js";
import "./claude-calibration-context.js";
import { assessReadiness } from "../state/calibration-engine-model.js";
import { summarizeCalibrationSignals, outputsWithDisagreement } from "../state/evaluation-model.js";
import { syntheticHardwareCapabilities } from "../state/synthetic-fixtures.js";

function buildPreviewSummary(previewFeedbackStore) {
  if (!previewFeedbackStore) return { accepted_count: 0, rejected_count: 0 };
  const counts = previewFeedbackStore.countsByOutcome();
  return {
    accepted_count: counts.accepted || 0,
    rejected_count: counts.rejected || 0,
  };
}

export class AvlWorkspaceCalibration extends AvlElement {
  set selectionModel(value) {
    this._selectionModel = value || null;
    if (this.isConnected) this._render();
  }

  set services(value) {
    this._services = value || {};
    if (this._services.calibrationStore) {
      this._onCalibrationChange = () => this._render();
      this._services.calibrationStore.addEventListener("change", this._onCalibrationChange);
    }
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._load();
  }

  disconnectedCallback() {
    if (this._services && this._services.calibrationStore && this._onCalibrationChange) {
      this._services.calibrationStore.removeEventListener("change", this._onCalibrationChange);
    }
  }

  async _load() {
    this._state = "loading";
    this._render();
    this._state = "ready";
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `h2 { margin: 0 0 var(--avl-space-3) 0; } .section { margin-bottom: var(--avl-space-4); }`;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Calibration";
    wrapper.appendChild(heading);

    const services = this._services || {};
    const capabilities = syntheticHardwareCapabilities();
    const evaluationStore = services.evaluationStore || null;
    const evaluationSummary = evaluationStore ? summarizeCalibrationSignals(evaluationStore) : null;
    const previewSummary = buildPreviewSummary(services.previewFeedbackStore);

    // -- AI Calibration Engine (VL-D7) ---------------------------------
    const enginePanel = document.createElement("avl-panel");
    enginePanel.setAttribute("title", "AI Calibration Engine");

    if (services.calibrationStore) {
      const runPanel = document.createElement("avl-calibration-run-panel");
      runPanel.calibrationStore = services.calibrationStore;
      runPanel.capabilities = capabilities;
      runPanel.evaluationStore = evaluationStore;
      runPanel.evaluationSummary = evaluationSummary;
      runPanel.previewSummary = previewSummary;
      runPanel.outputsWithDisagreementFn = outputsWithDisagreement;
      enginePanel.appendChild(runPanel);

      const readinessHeading = document.createElement("h4");
      readinessHeading.className = "avl-type-subheading";
      readinessHeading.textContent = "Readiness";
      enginePanel.appendChild(readinessHeading);
      const readinessPanel = document.createElement("avl-calibration-readiness-panel");
      readinessPanel.readiness = assessReadiness({ evaluationSummary, previewSummary });
      enginePanel.appendChild(readinessPanel);

      const current = services.calibrationStore.current();
      const adjustmentsHeading = document.createElement("h4");
      adjustmentsHeading.className = "avl-type-subheading";
      adjustmentsHeading.textContent = "Proposed parameter adjustments";
      enginePanel.appendChild(adjustmentsHeading);
      const adjustments = document.createElement("avl-calibration-parameter-adjustments");
      adjustments.adjustments = current ? current.adjustments : [];
      enginePanel.appendChild(adjustments);

      // VL-D8 -- Apply/Validate + before/after, a third axis
      // (application_state) alongside run_state/calibration_state above.
      const applicationHeading = document.createElement("h4");
      applicationHeading.className = "avl-type-subheading";
      applicationHeading.textContent = "Application & validation";
      enginePanel.appendChild(applicationHeading);
      const applicationPanel = document.createElement("avl-calibration-application-panel");
      applicationPanel.calibrationStore = services.calibrationStore;
      applicationPanel.generationQueueStore = services.generationQueueStore || null;
      enginePanel.appendChild(applicationPanel);

      const historyHeading = document.createElement("h4");
      historyHeading.className = "avl-type-subheading";
      historyHeading.textContent = "Profile history";
      enginePanel.appendChild(historyHeading);
      const history = document.createElement("avl-calibration-profile-history");
      history.calibrationStore = services.calibrationStore;
      history.selectionModel = this._selectionModel;
      enginePanel.appendChild(history);

      const claudeHeading = document.createElement("h4");
      claudeHeading.className = "avl-type-subheading";
      claudeHeading.textContent = "Ask Claude";
      enginePanel.appendChild(claudeHeading);
      const claudeContext = document.createElement("avl-claude-calibration-context");
      claudeContext.profile = current;
      if (services.executor) claudeContext.executor = services.executor;
      enginePanel.appendChild(claudeContext);
    } else {
      const empty = document.createElement("p");
      empty.textContent = "Calibration engine unavailable.";
      enginePanel.appendChild(empty);
    }

    const engineSection = document.createElement("div");
    engineSection.className = "section";
    engineSection.appendChild(enginePanel);
    wrapper.appendChild(engineSection);

    // -- Hardware profile card (real capability data now) --------------
    const hardwareSection = document.createElement("div");
    hardwareSection.className = "section";
    const hardwarePanel = document.createElement("avl-panel");
    hardwarePanel.setAttribute("title", "Hardware capabilities");
    const hardwareCard = document.createElement("avl-hardware-profile-card");
    hardwareCard.capabilities = capabilities;
    hardwarePanel.appendChild(hardwareCard);
    hardwareSection.appendChild(hardwarePanel);
    wrapper.appendChild(hardwareSection);

    // -- Target-speaker verification calibration (unchanged) -----------
    const speakerSection = document.createElement("div");
    speakerSection.className = "section";
    const speakerPanel = document.createElement("avl-panel");
    speakerPanel.setAttribute("title", "Target-speaker verification calibration");
    speakerPanel.appendChild(document.createElement("avl-calibration-panel"));
    speakerSection.appendChild(speakerPanel);
    wrapper.appendChild(speakerSection);

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-calibration", AvlWorkspaceCalibration);
