// <avl-workspace-command-center> — VL-D1 §6, extended in VL-D2 §22 with
// an IMPORTS summary. SYSTEM / PIPELINE / JOBS / ACTIVITY / IMPORTS. Set
// `.services` to { jobStore, activityStore, executor,
// pipelineStageContract, importQueue }. Every number here comes from a
// real store or a real generated contract, or is rendered as an honest
// "not available" — nothing is invented. This is an overview only — the
// Dataset Workspace (Import/Batches/Recordings) owns the detailed view.
import { AvlElement, defineComponent } from "./base-element.js";
import { summarizeReviewState } from "../state/review-summary.js";
import { JobStatus } from "../state/job-model.js";
import "./workspace-state.js";
import "./panel.js";
import "./status-badge.js";
import "./metric-placeholder.js";
import "./job-list.js";
import "./activity-timeline.js";
import "./stat-tile.js";
import "./meter.js";
import { summarizeCalibrationSignals, outputsWithDisagreement } from "../state/evaluation-model.js";
import { hasAnySessionData } from "../state/session-persistence.js";

const STORE_KEYS = [
  "importQueue",
  "reviewStore",
  "processingQueueStore",
  "generationQueueStore",
  "evaluationStore",
  "abEvaluationStore",
  "calibrationStore",
];

export class AvlWorkspaceCommandCenter extends AvlElement {
  set services(value) {
    this._services = value || {};
    if (this.isConnected) this._load();
  }

  connectedCallback() {
    this._services = this._services || {};
    this._teardownStoreListeners();
    this._storeListeners = [];
    for (const key of STORE_KEYS) {
      const store = this._services[key];
      if (!store) continue;
      const onChange = () => {
        if (this.isConnected) this._render();
      };
      store.addEventListener("change", onChange);
      this._storeListeners.push([store, onChange]);
    }
    this._load();
  }

  _teardownStoreListeners() {
    for (const [store, onChange] of this._storeListeners || []) {
      store.removeEventListener("change", onChange);
    }
    this._storeListeners = [];
  }

  disconnectedCallback() {
    this._teardownStoreListeners();
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
      h2 { margin: 0 0 var(--avl-space-1) 0; }
      /* FE-2.2 -- a real (non-"live") subtitle: this screen never
         polls, so it never claims to be real-time. */
      .subtitle { margin: 0 0 var(--avl-space-4) 0; color: var(--avl-color-text-secondary); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .headline-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: var(--avl-space-3); margin-bottom: var(--avl-space-4); }
      .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--avl-space-4); }
      /* FE-3 -- border/radius now come from avl-panel's own glass-surface styling. */
      .grid > avl-panel { min-height: 10rem; }
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

    const subtitle = document.createElement("p");
    subtitle.className = "subtitle";
    subtitle.textContent = "Overview of Aarya Voice Lab — session state, pipeline, and workspace summaries.";
    wrapper.appendChild(subtitle);

    // FE-2.2 -- headline stat tiles. Every value here reads an
    // already-real, already-wired store the same way the panels below
    // do (jobStore, pipelineStageContract, generationModelStore,
    // voiceProfileStore) -- nothing new is fetched or invented. Counts
    // that are genuinely absent (no CPU/GPU/RAM/disk measurement
    // exists anywhere in this codebase, no dataset/recording service is
    // wired into Command Center) are simply not tiled here rather than
    // filled with a placeholder number -- see FE2_VISUAL_REDESIGN.md.
    const headlineTiles = document.createElement("div");
    headlineTiles.className = "headline-tiles";

    const runningJobs = this._services.jobStore ? this._services.jobStore.current().length : null;
    const failedJobs = this._services.jobStore ? this._services.jobStore.failed().length : null;
    const jobsTile = document.createElement("avl-stat-tile");
    jobsTile.setAttribute("label", "Jobs running");
    jobsTile.setAttribute("tone", "blue");
    jobsTile.setAttribute("icon", "activity");
    if (runningJobs != null) jobsTile.setAttribute("value", String(runningJobs));
    if (failedJobs != null) jobsTile.textContent = `${failedJobs} failed`;
    headlineTiles.appendChild(jobsTile);

    const stagesTotal = this._pipeline?.stages?.length ?? null;
    const stagesDone = this._pipeline?.phase_2_stages?.length ?? null;
    const pipelineTile = document.createElement("avl-stat-tile");
    pipelineTile.setAttribute("label", "Pipeline stages");
    pipelineTile.setAttribute("tone", "teal");
    pipelineTile.setAttribute("icon", "pipeline");
    if (stagesDone != null) pipelineTile.setAttribute("value", String(stagesDone));
    if (stagesTotal != null) pipelineTile.setAttribute("unit", `of ${stagesTotal}`);
    if (stagesTotal != null) pipelineTile.textContent = "Stages implemented";
    headlineTiles.appendChild(pipelineTile);

    const modelCount = this._services.generationModelStore ? this._services.generationModelStore.list().length : null;
    const modelsTile = document.createElement("avl-stat-tile");
    modelsTile.setAttribute("label", "Models");
    modelsTile.setAttribute("tone", "green");
    modelsTile.setAttribute("icon", "models");
    if (modelCount != null) modelsTile.setAttribute("value", String(modelCount));
    headlineTiles.appendChild(modelsTile);

    const voiceCount = this._services.voiceProfileStore ? this._services.voiceProfileStore.names().length : null;
    const voicesTile = document.createElement("avl-stat-tile");
    voicesTile.setAttribute("label", "Voice profiles");
    voicesTile.setAttribute("tone", "pink");
    voicesTile.setAttribute("icon", "voices");
    if (voiceCount != null) voicesTile.setAttribute("value", String(voiceCount));
    headlineTiles.appendChild(voicesTile);

    wrapper.appendChild(headlineTiles);

    const grid = document.createElement("div");
    grid.className = "grid";

    // SYSTEM
    const systemPanel = document.createElement("avl-panel");
    systemPanel.setAttribute("title", "System");
    for (const [label, domain, state] of [
      // "Core" (the frontend JS runtime) is tautologically "ready"
      // whenever this component is rendering at all -- there is no
      // failure mode where this code runs but the core is not ready,
      // so unlike every other row here it is never read from a store.
      ["Core", "core", "ready"],
      ["Runtime", "hardware", "UNKNOWN"],
      ["Hardware", "hardware", "UNKNOWN"],
      // VL-D9 -- honest local-persistence state, never a fabricated
      // "ready": reflects whether localStorage was actually usable this
      // session (see state/session-persistence.js's isPersistenceAvailable()).
      ["Storage", "core", this._services.session?.available ? "ready" : "offline"],
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
    const jobsByStatus = this._services.jobStore ? this._services.jobStore.list() : null;
    for (const [label, value] of [
      ["Queued", jobsByStatus ? jobsByStatus.filter((j) => j.status === JobStatus.QUEUED).length : null],
      ["Running", this._services.jobStore ? this._services.jobStore.current().length : null],
      ["Completed (stages implemented)", implementedCount],
      ["Total stages", totalCount],
      ["Warnings", jobsByStatus ? jobsByStatus.filter((j) => j.status === JobStatus.WARNING).length : null],
      ["Failed", this._services.jobStore ? this._services.jobStore.failed().length : null],
    ]) {
      const metric = document.createElement("avl-metric-placeholder");
      metric.setAttribute("label", label);
      if (value != null) metric.setAttribute("value", String(value));
      pipelinePanel.appendChild(metric);
    }
    // FE-2.2 -- a real progress bar for "stages implemented / total
    // stages" (both already-real numbers above), the one legitimate
    // percentage this screen can honestly show; see the headline
    // tiles' own comment for what does NOT get this treatment.
    const pipelineMeter = document.createElement("avl-meter");
    pipelineMeter.setAttribute("label", "Stages implemented");
    pipelineMeter.setAttribute("tone", "teal");
    if (implementedCount != null) pipelineMeter.setAttribute("value", String(implementedCount));
    if (totalCount != null) pipelineMeter.setAttribute("max", String(totalCount));
    pipelinePanel.appendChild(pipelineMeter);

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
      ["Re-review disagreement", reviewSummary.disagreementCount],
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

    // SESSION -- VL-D9 overview: honest local-persistence status, never
    // "cloud sync" language. `available` reflects whether localStorage
    // itself could be used this session; `hasAnySessionData()` re-reads
    // localStorage live on every render, so "Session data saved" tracks
    // the real current state after each automatic save, not a cached
    // guess.
    const sessionPanel = document.createElement("avl-panel");
    sessionPanel.setAttribute("title", "Session");
    const session = this._services.session || {};
    const sessionStatusRow = document.createElement("div");
    sessionStatusRow.className = "row";
    const sessionLabel = document.createElement("span");
    sessionLabel.textContent = "Local persistence";
    const sessionBadge = document.createElement("avl-status-badge");
    sessionBadge.setAttribute("domain", "core");
    sessionBadge.setAttribute("state", session.available ? "ready" : "offline");
    sessionStatusRow.append(sessionLabel, sessionBadge);
    sessionPanel.appendChild(sessionStatusRow);
    const sessionDataMetric = document.createElement("avl-metric-placeholder");
    sessionDataMetric.setAttribute("label", "Session data saved");
    sessionDataMetric.setAttribute("value", session.available && hasAnySessionData() ? "yes" : "no");
    sessionPanel.appendChild(sessionDataMetric);
    const sessionRestoredMetric = document.createElement("avl-metric-placeholder");
    sessionRestoredMetric.setAttribute("label", "Restored this load");
    sessionRestoredMetric.setAttribute("value", session.wasRestored ? "yes" : "no");
    sessionPanel.appendChild(sessionRestoredMetric);

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
      sessionPanel,
    );
    wrapper.appendChild(grid);
    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-command-center", AvlWorkspaceCommandCenter);
