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

    grid.append(systemPanel, pipelinePanel, jobsPanel, activityPanel, importsPanel, reviewPanel);
    wrapper.appendChild(grid);
    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-command-center", AvlWorkspaceCommandCenter);
