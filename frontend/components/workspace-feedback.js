// <avl-workspace-feedback> -- VL-D6. The Voice Feedback + Human
// Evaluation workspace: Evaluation Dashboard / Evaluation Queue /
// Evaluation Form (rating/confidence/comments/listening controls) /
// A-B Comparison / Evaluation History / Disagreement / Aggregated
// Results / Calibration Readiness / Provenance, over the session-only
// evaluation records in state/evaluation-model.js.
//
// This is evaluation SOFTWARE only (§3 of the VL-D6 spec) -- it never
// trains, tunes, or establishes Aarya's actual voice or identity.
// Evaluation targets are the same generated outputs VL-D5's Preview
// workspace produces (this._services.generationQueueStore); VL-D6 adds a
// genuinely separate, multi-dimension, multi-reviewer judgement layer on
// top, never replacing avl-preview-feedback-form's single-outcome
// accept/reject loop.
import { AvlElement, defineComponent } from "./base-element.js";
import { summarizeOutputEvaluations, summarizeCalibrationSignals, outputsWithDisagreement } from "../state/evaluation-model.js";
import "./workspace-state.js";
import "./button.js";
import "./evaluation-queue.js";
import "./evaluation-form.js";
import "./ab-evaluation.js";
import "./evaluation-history-panel.js";
import "./disagreement-view.js";
import "./aggregated-results-panel.js";
import "./calibration-panel.js";
import "./claude-evaluation-context.js";
import "./stat-tile.js";

// FE-2.3 -- see workspace-batches.js's identical constant.
const TILE_TONES = ["blue", "teal", "green", "violet", "pink"];

export class AvlWorkspaceFeedback extends AvlElement {
  set selectionModel(value) {
    this._selectionModel = value;
  }

  set services(value) {
    this._services = value || {};
    for (const store of [this._services.generationQueueStore, this._services.evaluationStore, this._services.abEvaluationStore]) {
      if (store) store.addEventListener("change", () => this._scheduleRender());
    }
  }

  // Same coalescing rationale as avl-workspace-preview._scheduleRender():
  // a burst of "change" events (evaluation submitted, then the queue's
  // own re-render) must not tear down an in-flight <audio> element mid
  // playback.
  _scheduleRender() {
    if (this._renderScheduled) return;
    this._renderScheduled = true;
    setTimeout(() => {
      this._renderScheduled = false;
      this._render();
    }, 0);
  }

  connectedCallback() {
    this._focusedOutputId = this._focusedOutputId || null;
    this._compareWithOutputId = this._compareWithOutputId || null;
    this._render();
  }

  _outputs() {
    const queue = this._services?.generationQueueStore;
    return queue ? queue.list().filter((i) => i.artifact).map((i) => i.artifact) : [];
  }

  _dashboardCounts() {
    const evaluationStore = this._services?.evaluationStore;
    const outputs = this._outputs();
    if (!evaluationStore) {
      return { totalOutputs: outputs.length, unevaluated: outputs.length, evaluated: 0, disagreementCount: 0, calibration: null };
    }
    const evaluatedOutputIds = new Set(evaluationStore.list().map((r) => r.output_id));
    const unevaluated = outputs.filter((o) => !evaluatedOutputIds.has(o.preview_id)).length;
    const calibration = summarizeCalibrationSignals(evaluationStore);
    return {
      totalOutputs: outputs.length,
      unevaluated,
      evaluated: outputs.length - unevaluated,
      disagreementCount: outputsWithDisagreement(evaluationStore).length,
      calibration,
    };
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      h3 { margin: var(--avl-space-4) 0 var(--avl-space-2) 0; font: var(--avl-type-subheading-weight) var(--avl-type-subheading-size) / var(--avl-type-subheading-line-height) var(--avl-type-subheading-family); }
      .dashboard { display: grid; grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr)); gap: var(--avl-space-3); margin-bottom: var(--avl-space-4); }
      /* FE-1.5 -- .row replaced by the shared avl-row avl-row--bordered utilities (css/base.css). */
      .rows { display: flex; flex-direction: column; }
      .label { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); }
      .value { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); text-align: right; word-break: break-word; }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      /* FE-3 -- select styling now comes from css/base.css's shared baseline. */
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", "ready");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Voice Feedback";
    wrapper.appendChild(heading);

    const stats = this._dashboardCounts();
    const dashboard = document.createElement("div");
    dashboard.className = "dashboard";
    [
      ["Outputs available", stats.totalOutputs],
      ["Unevaluated", stats.unevaluated],
      ["Evaluated", stats.evaluated],
      ["Disagreement", stats.disagreementCount],
      ["Total evaluations", stats.calibration ? stats.calibration.total_evaluations : 0],
      ["Reviewers", stats.calibration ? stats.calibration.total_reviewers : 0],
    ].forEach(([label, value], i) => {
      const tile = document.createElement("avl-stat-tile");
      tile.setAttribute("label", label);
      tile.setAttribute("value", String(value));
      tile.setAttribute("tone", TILE_TONES[i % TILE_TONES.length]);
      tile.setAttribute("icon", "feedback");
      dashboard.appendChild(tile);
    });
    wrapper.appendChild(dashboard);

    const queueHeading = document.createElement("h3");
    queueHeading.textContent = "Evaluation Queue";
    wrapper.appendChild(queueHeading);
    const queueEl = document.createElement("avl-evaluation-queue");
    queueEl.evaluationStore = this._services?.evaluationStore;
    queueEl.outputs = this._outputs();
    queueEl.addEventListener("avl-evaluation-select", (event) => {
      this._focusedOutputId = event.detail.output.preview_id;
      this._render();
    });
    wrapper.appendChild(queueEl);

    const focusedOutput = this._focusedOutput();
    if (focusedOutput) {
      const formHeading = document.createElement("h3");
      formHeading.textContent = "Evaluate";
      wrapper.appendChild(formHeading);
      const form = document.createElement("avl-evaluation-form");
      form.evaluationStore = this._services?.evaluationStore;
      form.output = focusedOutput;
      const item = this._focusedItem();
      if (item) {
        form.voiceProfileId = item.request.voice_profile_id;
        form.modelId = item.request.model_id;
        form.configHash = item.request.config_hash;
      }
      wrapper.appendChild(form);

      const abHeading = document.createElement("h3");
      abHeading.textContent = "A / B Comparison";
      wrapper.appendChild(abHeading);
      wrapper.appendChild(this._buildAbEvaluationSection(focusedOutput));

      const historyHeading = document.createElement("h3");
      historyHeading.textContent = "Evaluation History";
      wrapper.appendChild(historyHeading);
      const history = document.createElement("avl-evaluation-history-panel");
      history.evaluationStore = this._services?.evaluationStore;
      history.outputId = focusedOutput.preview_id;
      wrapper.appendChild(history);

      const evaluations = this._services?.evaluationStore ? this._services.evaluationStore.evaluationsFor(focusedOutput.preview_id) : [];
      const summary = summarizeOutputEvaluations(evaluations, focusedOutput.preview_id);

      const disagreementHeading = document.createElement("h3");
      disagreementHeading.textContent = "Disagreement";
      wrapper.appendChild(disagreementHeading);
      const disagreement = document.createElement("avl-disagreement-view");
      disagreement.summary = summary;
      wrapper.appendChild(disagreement);

      const aggregatedHeading = document.createElement("h3");
      aggregatedHeading.textContent = "Aggregated Results";
      wrapper.appendChild(aggregatedHeading);
      const aggregated = document.createElement("avl-aggregated-results-panel");
      aggregated.summary = summary;
      wrapper.appendChild(aggregated);

      const calibrationHeading = document.createElement("h3");
      calibrationHeading.textContent = "Calibration Readiness";
      wrapper.appendChild(calibrationHeading);
      wrapper.appendChild(this._buildCalibrationPanel());

      const provenanceHeading = document.createElement("h3");
      provenanceHeading.textContent = "Provenance";
      wrapper.appendChild(provenanceHeading);
      wrapper.appendChild(this._buildProvenanceRows(focusedOutput));

      const claudeHeading = document.createElement("h3");
      claudeHeading.textContent = "Ask Claude";
      wrapper.appendChild(claudeHeading);
      const claudeContext = document.createElement("avl-claude-evaluation-context");
      claudeContext.outputId = focusedOutput.preview_id;
      claudeContext.voiceProfileId = item ? item.request.voice_profile_id : null;
      claudeContext.summary = summary;
      if (this._services?.executor) claudeContext.executor = this._services.executor;
      wrapper.appendChild(claudeContext);
    }

    this.shadowRoot.appendChild(wrapper);
  }

  _focusedItem() {
    const queue = this._services?.generationQueueStore;
    if (!queue || !this._focusedOutputId) return null;
    return queue.list().find((i) => i.artifact && i.artifact.preview_id === this._focusedOutputId) || null;
  }

  _focusedOutput() {
    const item = this._focusedItem();
    return item ? item.artifact : null;
  }

  _buildAbEvaluationSection(focusedOutput) {
    const wrapper = document.createElement("div");
    const others = this._outputs().filter((o) => o.preview_id !== focusedOutput.preview_id);

    const select = document.createElement("select");
    select.setAttribute("aria-label", "Compare with");
    const noneOption = document.createElement("option");
    noneOption.value = "";
    noneOption.textContent = "Select an output to compare with…";
    select.appendChild(noneOption);
    for (const other of others) {
      const option = document.createElement("option");
      option.value = other.preview_id;
      option.textContent = other.preview_id;
      if (this._compareWithOutputId === other.preview_id) option.selected = true;
      select.appendChild(option);
    }
    select.addEventListener("change", () => {
      this._compareWithOutputId = select.value || null;
      this._render();
    });
    wrapper.appendChild(select);

    const compareWith = this._compareWithOutputId ? others.find((o) => o.preview_id === this._compareWithOutputId) : null;
    if (compareWith) {
      const pairKey = `${focusedOutput.preview_id}::${compareWith.preview_id}`;
      if (this._abEvaluationEl && this._abEvaluationPairKey === pairKey) {
        // Reuse the same element across re-renders instead of recreating
        // it: a fresh avl-ab-evaluation would start with no listening
        // state and no status message, wiping the reviewer's own
        // just-submitted decision the moment abEvaluationStore's "change"
        // event (fired by that very submission) triggers this workspace's
        // own _scheduleRender() -- the same "don't tear down live
        // interactive state on your own event" bug class
        // _scheduleRender()'s coalescing already guards audio playback
        // against, applied here to the A/B decision panel instead.
        wrapper.appendChild(this._abEvaluationEl);
      } else {
        const ab = document.createElement("avl-ab-evaluation");
        ab.evaluationStore = this._services?.evaluationStore;
        ab.abEvaluationStore = this._services?.abEvaluationStore;
        ab.labels = ["Focused", "Compare"];
        ab.left = focusedOutput;
        ab.right = compareWith;
        this._abEvaluationEl = ab;
        this._abEvaluationPairKey = pairKey;
        wrapper.appendChild(ab);
      }
    } else {
      this._abEvaluationEl = null;
      this._abEvaluationPairKey = null;
    }
    return wrapper;
  }

  _buildCalibrationPanel() {
    const evaluationStore = this._services?.evaluationStore;
    const panel = document.createElement("avl-calibration-panel");
    if (evaluationStore) {
      const signals = summarizeCalibrationSignals(evaluationStore);
      panel.record = {
        state: "UNCALIBRATED",
        evidence: "raw_evaluation_counts",
        threshold: null,
        sample_size: signals.total_evaluations,
      };
    }
    return panel;
  }

  _buildProvenanceRows(output) {
    const item = this._focusedItem();
    const rows = document.createElement("div");
    rows.className = "rows";
    for (const [label, value] of [
      ["Output ID", output.preview_id],
      ["Output SHA-256", output.sha256],
      ["Artifact ID", output.artifact_id],
      ["Model", item ? item.request.model_id : null],
      ["Voice profile", item ? item.request.voice_profile_id : null],
      ["Config hash", item ? item.request.config_hash : null],
      ["Kind", output.kind],
      ["Synthetic", String(output.is_synthetic)],
    ]) {
      const row = document.createElement("div");
      row.className = "avl-row avl-row--bordered";
      row.innerHTML = `<span class="label">${label}</span><span class="value">${value == null || value === "" ? "—" : value}</span>`;
      rows.appendChild(row);
    }
    return rows;
  }
}

defineComponent("avl-workspace-feedback", AvlWorkspaceFeedback);
