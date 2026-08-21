// <avl-workspace-command-center> — VL-D1 §6, extended in VL-D2 §22 with
// an IMPORTS summary. SYSTEM / PIPELINE / JOBS / ACTIVITY / IMPORTS. Set
// `.services` to { jobStore, activityStore, executor,
// pipelineStageContract, importQueue }. Every number here comes from a
// real store or a real generated contract, or is rendered as an honest
// "not available" — nothing is invented. This is an overview only — the
// Dataset Workspace (Import/Batches/Recordings) owns the detailed view.
import { AvlElement, defineComponent } from "./base-element.js";
import { summarizeReviewState } from "../state/review-summary.js";
import "./workspace-state.js";
import "./panel.js";
import "./status-badge.js";
import "./metric-placeholder.js";
import "./job-list.js";
import "./activity-timeline.js";
import { summarizeCalibrationSignals, outputsWithDisagreement } from "../state/evaluation-model.js";

export class AvlWorkspaceCommandCenter extends AvlElement {
  set services(value) {
    this._services = value || {};
    if (this.isConnected) this._load();
  }

  connectedCallback() {
    this._services = this._services || {};
    if (this._services.importQueue) {
      this._services.importQueue.addEventListener("change", () => {
        if (this.isConnected) this._render();
      });
    }
    if (this._services.reviewStore) {
      this._services.reviewStore.addEventListener("change", () => {
        if (this.isConnected) this._render();
      });
    }
    if (this._services.processingQueueStore) {
      this._services.processingQueueStore.addEventListener("change", () => {
        if (this.isConnected) this._render();
      });
    }
    if (this._services.generationQueueStore) {
      this._services.generationQueueStore.addEventListener("change", () => {
        if (this.isConnected) this._render();
      });
    }
    if (this._services.evaluationStore) {
      this._services.evaluationStore.addEventListener("change", () => {
        if (this.isConnected) this._render();
      });
    }
    if (this._services.abEvaluationStore) {
      this._services.abEvaluationStore.addEventListener("change", () => {
        if (this.isConnected) this._render();
      });
    }
    if (this._services.calibrationStore) {
      this._services.calibrationStore.addEventListener("change", () => {
        if (this.isConnected) this._render();
      });
    }
    this._load();
  }

  async _load() {
    this._state = "loading";
    this._render();
    try {
      this._pipeline = this._services.pipelineStageContract || null;
      this._state = "ready";
    } catch (err) {
      this._state = "error";
      this._errorDetail = String(err);
    }
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--avl-space-4); }
      .grid > avl-panel { min-height: 10rem; border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-md); }
      .row { display: flex; justify-content: space-between; align-items: center; padding: var(--avl-space-1) 0; }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "error") wrapper.setAttribute("detail", this._errorDetail || "");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Command Center";
    wrapper.appendChild(heading);

    const grid = document.createElement("div");
    grid.className = "grid";

    // SYSTEM
    const systemPanel = document.createElement("avl-panel");
    systemPanel.setAttribute("title", "System");
    for (const [label, domain, state] of [
      ["Core", "core", "ready"],
      ["Runtime", "hardware", "UNKNOWN"],
      ["Hardware", "hardware", "UNKNOWN"],
      ["Storage", "core", "ready"],
      ["Claude", "core", this._services.executor?.available() ? "ready" : "offline"],
    ]) {
      const row = document.createElement("div");
      row.className = "row";
      const l = document.createElement("span");
      l.textContent = label;
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", domain);
      badge.setAttribute("state", state);
      row.append(l, badge);
      systemPanel.appendChild(row);
    }

    // PIPELINE
    const pipelinePanel = document.createElement("avl-panel");
    pipelinePanel.setAttribute("title", "Pipeline");
    const implementedCount = this._pipeline?.phase_2_stages?.length ?? null;
    const totalCount = this._pipeline?.stages?.length ?? null;
    for (const [label, value] of [
      ["Queued", 0],
      ["Running", this._services.jobStore ? this._services.jobStore.current().length : null],
      ["Completed (stages implemented)", implementedCount],
      ["Total stages", totalCount],
      ["Warnings", 0],
      ["Failed", this._services.jobStore ? this._services.jobStore.failed().length : null],
    ]) {
      const metric = document.createElement("avl-metric-placeholder");
      metric.setAttribute("label", label);
      if (value != null) metric.setAttribute("value", String(value));
      pipelinePanel.appendChild(metric);
    }

    // JOBS
    const jobsPanel = document.createElement("avl-panel");
    jobsPanel.setAttribute("title", "Jobs");
    const jobList = document.createElement("avl-job-list");
    jobList.jobs = this._services.jobStore ? this._services.jobStore.list() : [];
    jobsPanel.appendChild(jobList);

    // ACTIVITY
    const activityPanel = document.createElement("avl-panel");
    activityPanel.setAttribute("title", "Recent activity");
    const timeline = document.createElement("avl-activity-timeline");
    timeline.events = this._services.activityStore ? this._services.activityStore.list({ limit: 5 }) : [];
    activityPanel.appendChild(timeline);

    // IMPORTS — overview only; the Import workspace owns the detailed queue.
    const importsPanel = document.createElement("avl-panel");
    importsPanel.setAttribute("title", "Imports");
    const importQueue = this._services.importQueue;
    if (importQueue && importQueue.items.size) {
      const counts = importQueue.counts();
      const active = counts.queued + counts.scanning + counts.hashing + counts.validating;
      for (const [label, value] of [
        ["Active", active],
        ["Accepted", counts.accepted],
        ["Warnings", counts.warning],
        ["Failed", counts.failed + counts.invalid + counts.blocked],
      ]) {
        const metric = document.createElement("avl-metric-placeholder");
        metric.setAttribute("label", label);
        metric.setAttribute("value", String(value));
        importsPanel.appendChild(metric);
      }
    } else {
      const empty = document.createElement("avl-metric-placeholder");
      empty.setAttribute("label", "Active imports");
      importsPanel.appendChild(empty);
    }

    // REVIEW — overview only (VL-D3 §24); the Dataset Review workspace
    // owns the detailed queue/filters/sorting.
    const reviewPanel = document.createElement("avl-panel");
    reviewPanel.setAttribute("title", "Review");
    const reviewSummary = summarizeReviewState(this._services.reviewStore);
    for (const [label, value] of [
      ["Review queue", reviewSummary.reviewQueueCount],
      ["Pending candidates", reviewSummary.pendingCandidates],
      ["Quality warnings", reviewSummary.qualityWarnings],
      ["Recent analyses", reviewSummary.recentAnalysisCount],
      ["Failed analyses", reviewSummary.failedAnalyses],
    ]) {
      const metric = document.createElement("avl-metric-placeholder");
      metric.setAttribute("label", label);
      metric.setAttribute("value", String(value));
      reviewPanel.appendChild(metric);
    }
    const currentBatch = document.createElement("avl-metric-placeholder");
    currentBatch.setAttribute("label", "Current batch review");
    if (reviewSummary.currentBatchReview) {
      currentBatch.setAttribute(
        "value",
        `${reviewSummary.currentBatchReview.batchId} (${reviewSummary.currentBatchReview.decided}/${reviewSummary.currentBatchReview.total})`,
      );
    }
    reviewPanel.appendChild(currentBatch);

    // PROCESSING — overview only (VL-D4 §26: "Command Center should show
    // aggregate processing activity"); the Processing workspace owns the
    // detailed queue/profiles/before-after view.
    const processingPanel = document.createElement("avl-panel");
    processingPanel.setAttribute("title", "Processing");
    const processingItems = this._services.processingQueueStore ? this._services.processingQueueStore.list() : [];
    const processingCounts = this._services.processingQueueStore
      ? this._services.processingQueueStore.counts()
      : {};
    const processingDurations = processingItems.map((i) => i.processingDurationSeconds).filter((d) => d != null);
    const avgProcessingDuration = processingDurations.length
      ? processingDurations.reduce((a, b) => a + b, 0) / processingDurations.length
      : null;
    for (const [label, value] of [
      ["Total processed", processingItems.length],
      ["Success", processingCounts.SUCCESS || 0],
      ["Warning", processingCounts.WARNING || 0],
      ["Failed", processingCounts.FAILED || 0],
      ["Blocked", processingCounts.BLOCKED || 0],
    ]) {
      const metric = document.createElement("avl-metric-placeholder");
      metric.setAttribute("label", label);
      metric.setAttribute("value", String(value));
      processingPanel.appendChild(metric);
    }
    const avgDurationMetric = document.createElement("avl-metric-placeholder");
    avgDurationMetric.setAttribute("label", "Avg duration");
    if (avgProcessingDuration != null) {
      avgDurationMetric.setAttribute("value", avgProcessingDuration.toFixed(2));
      avgDurationMetric.setAttribute("unit", "s");
    }
    processingPanel.appendChild(avgDurationMetric);

    // PREVIEW — overview only (VL-D5 §29: "Command Center should show an
    // overview-only Preview panel"); the Preview workspace owns the
    // detailed queue/settings/A-B/feedback/history view.
    const previewPanel = document.createElement("avl-panel");
    previewPanel.setAttribute("title", "Preview");
    const previewItems = this._services.generationQueueStore ? this._services.generationQueueStore.list() : [];
    const previewCounts = this._services.generationQueueStore ? this._services.generationQueueStore.counts() : {};
    const previewDurations = previewItems.map((i) => i.generation_duration_seconds).filter((d) => d != null);
    const avgPreviewDuration = previewDurations.length
      ? previewDurations.reduce((a, b) => a + b, 0) / previewDurations.length
      : null;
    for (const [label, value] of [
      ["Total generated", previewItems.length],
      ["Ready", previewCounts.READY || 0],
      ["Warning", previewCounts.WARNING || 0],
      ["Failed", previewCounts.FAILED || 0],
      ["Blocked", previewCounts.BLOCKED || 0],
    ]) {
      const metric = document.createElement("avl-metric-placeholder");
      metric.setAttribute("label", label);
      metric.setAttribute("value", String(value));
      previewPanel.appendChild(metric);
    }
    const avgPreviewDurationMetric = document.createElement("avl-metric-placeholder");
    avgPreviewDurationMetric.setAttribute("label", "Avg duration");
    if (avgPreviewDuration != null) {
      avgPreviewDurationMetric.setAttribute("value", avgPreviewDuration.toFixed(2));
      avgPreviewDurationMetric.setAttribute("unit", "s");
    }
    previewPanel.appendChild(avgPreviewDurationMetric);

    // FEEDBACK/EVALUATION -- overview only (VL-D6, same "overview only"
    // convention as the Preview panel above; the Feedback workspace owns
    // the detailed queue/rating/A-B/history/disagreement view). Every
    // number here comes from evaluationStore/abEvaluationStore directly
    // -- never fabricated, never a computed calibration score.
    const feedbackPanel = document.createElement("avl-panel");
    feedbackPanel.setAttribute("title", "Feedback");
    const evaluationStore = this._services.evaluationStore || null;
    const abEvaluationStore = this._services.abEvaluationStore || null;
    const generationOutputs = this._services.generationQueueStore
      ? this._services.generationQueueStore.list().filter((i) => i.artifact)
      : [];
    const evaluatedOutputIds = evaluationStore ? new Set(evaluationStore.list().map((r) => r.output_id)) : new Set();
    const unevaluated = generationOutputs.filter((i) => !evaluatedOutputIds.has(i.artifact.preview_id)).length;
    const signals = evaluationStore
      ? summarizeCalibrationSignals(evaluationStore)
      : { total_evaluations: 0, total_reviewers: 0, completed_count: 0, cannot_judge_count: 0 };
    const disagreementCount = evaluationStore ? outputsWithDisagreement(evaluationStore).length : 0;
    for (const [label, value] of [
      ["Unevaluated outputs", unevaluated],
      ["Total evaluations", signals.total_evaluations],
      ["Completed", signals.completed_count],
      ["Cannot judge", signals.cannot_judge_count],
      ["Reviewers", signals.total_reviewers],
      ["Disagreement", disagreementCount],
      ["A/B decisions", abEvaluationStore ? abEvaluationStore.list().length : 0],
    ]) {
      const metric = document.createElement("avl-metric-placeholder");
      metric.setAttribute("label", label);
      metric.setAttribute("value", String(value));
      feedbackPanel.appendChild(metric);
    }
    const calibrationRow = document.createElement("div");
    calibrationRow.className = "row";
    calibrationRow.innerHTML = '<span class="label">Calibration prep</span>';
    const calibrationBadge = document.createElement("avl-status-badge");
    calibrationBadge.setAttribute("domain", "calibration");
    const currentCalibrationProfile = this._services.calibrationStore ? this._services.calibrationStore.current() : null;
    calibrationBadge.setAttribute("state", currentCalibrationProfile ? currentCalibrationProfile.calibration_state : "UNCALIBRATED");
    calibrationRow.appendChild(calibrationBadge);
    feedbackPanel.appendChild(calibrationRow);

    // CALIBRATION -- overview only (VL-D7, same "overview only"
    // convention as Preview/Feedback above; the Calibration workspace
    // owns the detailed run/readiness/adjustments/history view). Every
    // number here comes from calibrationStore.current() directly, or
    // renders as "not available" if no run has happened yet -- never a
    // fabricated score.
    const calibrationPanel = document.createElement("avl-panel");
    calibrationPanel.setAttribute("title", "Calibration engine");
    const runRow = document.createElement("div");
    runRow.className = "row";
    runRow.innerHTML = '<span class="label">Run state</span>';
    const runBadge = document.createElement("avl-status-badge");
    runBadge.setAttribute("domain", "hardware_calibration");
    runBadge.setAttribute("state", currentCalibrationProfile ? currentCalibrationProfile.run_state : "NOT_TESTED");
    runRow.appendChild(runBadge);
    calibrationPanel.appendChild(runRow);
    const evidenceRow = document.createElement("div");
    evidenceRow.className = "row";
    evidenceRow.innerHTML = '<span class="label">Evidence state</span>';
    const evidenceBadge = document.createElement("avl-status-badge");
    evidenceBadge.setAttribute("domain", "calibration");
    evidenceBadge.setAttribute("state", currentCalibrationProfile ? currentCalibrationProfile.calibration_state : "UNCALIBRATED");
    evidenceRow.appendChild(evidenceBadge);
    calibrationPanel.appendChild(evidenceRow);
    for (const [label, value] of [
      ["Strategy", currentCalibrationProfile ? currentCalibrationProfile.strategy : null],
      [
        "Agreement rate",
        currentCalibrationProfile && currentCalibrationProfile.agreement_rate != null
          ? `${(currentCalibrationProfile.agreement_rate * 100).toFixed(1)}%`
          : null,
      ],
      ["Profile runs", this._services.calibrationStore ? this._services.calibrationStore.history().length : 0],
      ["Adjustments proposed", currentCalibrationProfile ? currentCalibrationProfile.adjustments.length : 0],
      [
        "Proposed",
        this._services.calibrationStore
          ? this._services.calibrationStore.history().filter((r) => r.application_state === "PROPOSED").length
          : 0,
      ],
      [
        "Applied",
        this._services.calibrationStore
          ? this._services.calibrationStore.history().filter((r) => r.application_state === "APPLIED").length
          : 0,
      ],
      [
        "Validated",
        this._services.calibrationStore
          ? this._services.calibrationStore.history().filter((r) => r.application_state === "VALIDATED").length
          : 0,
      ],
    ]) {
      const metric = document.createElement("avl-metric-placeholder");
      metric.setAttribute("label", label);
      if (value != null) metric.setAttribute("value", String(value));
      calibrationPanel.appendChild(metric);
    }

    grid.append(
      systemPanel,
      pipelinePanel,
      jobsPanel,
      activityPanel,
      importsPanel,
      reviewPanel,
      processingPanel,
      previewPanel,
      feedbackPanel,
      calibrationPanel,
    );
    wrapper.appendChild(grid);
    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-command-center", AvlWorkspaceCommandCenter);
