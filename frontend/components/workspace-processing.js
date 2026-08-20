// <avl-workspace-processing> — VL-D4 §4, §21, §22, §23. The Voice
// Processing + Conditioning workspace: a real dashboard, the processing
// queue, profile management, and a before/after comparison for whatever
// recording is selected. Selecting a recording here routes through the
// shared selectionModel exactly like avl-workspace-dataset-review, so
// the expanded Inspector (§20) renders its Processing sections for
// whatever is selected.
//
// SOURCE AUDIO IS NEVER MODIFIED (§2). Every action here either reads
// existing state or enqueues a session-only processing simulation (see
// state/processing-model.js) — nothing writes into data/source/, and
// nothing claims to.
import { AvlElement, defineComponent } from "./base-element.js";
import { syntheticRecordings } from "../state/synthetic-fixtures.js";
import { ProcessingStatus } from "../state/processing-model.js";
import "./workspace-state.js";
import "./status-badge.js";
import "./button.js";
import "./processing-queue.js";
import "./processing-profile-editor.js";
import "./before-after-comparison.js";
import "./processing-history-panel.js";
import "./processing-feedback-form.js";

const QUALITY_RANK = { NOT_ANALYZED: 0, FAIL: 1, REVIEW: 2, WARNING: 3, PASS: 4 };

export class AvlWorkspaceProcessing extends AvlElement {
  set selectionModel(value) {
    this._selectionModel = value;
  }

  set services(value) {
    this._services = value || {};
    for (const store of [this._services.processingQueueStore, this._services.processingProfileStore]) {
      if (store) store.addEventListener("change", () => this._render());
    }
  }

  connectedCallback() {
    this._selectedRecordingId = this._selectedRecordingId || null;
    this._recordings = syntheticRecordings();
    if (this._services?.processingProfileStore && !this._services.processingProfileStore.names().length) {
      const profile = this._services.processingProfileStore.create("standard", { noiseConditioningMode: "MEASURE_ONLY" });
      this._services.processingProfileStore.setDefault("standard");
      this._defaultProfile = profile;
    }
    this._render();
  }

  _dashboardCounts() {
    const queue = this._services?.processingQueueStore;
    const items = queue ? queue.list() : [];
    const counts = queue ? queue.counts() : {};
    const durations = items.map((i) => i.processingDurationSeconds).filter((d) => d != null);
    const avgDuration = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null;

    const profileDistribution = {};
    for (const item of items) profileDistribution[item.profileId] = (profileDistribution[item.profileId] || 0) + 1;

    let improved = 0;
    let degraded = 0;
    let unchanged = 0;
    for (const item of items) {
      if (!item.qualityBefore || !item.qualityAfter) continue;
      const before = QUALITY_RANK[item.qualityBefore.decision] ?? 0;
      const after = QUALITY_RANK[item.qualityAfter.decision] ?? 0;
      if (after > before) improved += 1;
      else if (after < before) degraded += 1;
      else unchanged += 1;
    }

    return { total: items.length, counts, avgDuration, profileDistribution, improved, degraded, unchanged };
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      h3 { margin: var(--avl-space-4) 0 var(--avl-space-2) 0; font: var(--avl-type-subheading-weight) var(--avl-type-subheading-size) / var(--avl-type-subheading-line-height) var(--avl-type-subheading-family); }
      .dashboard { display: grid; grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr)); gap: var(--avl-space-2); margin-bottom: var(--avl-space-4); }
      .metric { border: 1px solid var(--avl-color-border-subtle); border-radius: var(--avl-radius-sm); padding: var(--avl-space-2); }
      .metric .value { font: var(--avl-type-heading-weight) var(--avl-type-heading-size) / 1 var(--avl-type-heading-family); }
      .metric .label { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; }
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      tr[data-selectable] { cursor: pointer; }
      tr[data-selectable]:hover { background: var(--avl-color-surface-sunken); }
      .count { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); margin-bottom: var(--avl-space-2); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", "ready");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Voice Processing";
    wrapper.appendChild(heading);

    const stats = this._dashboardCounts();
    const dashboard = document.createElement("div");
    dashboard.className = "dashboard";
    for (const [label, value] of [
      ["Total selected", stats.total],
      ["Queued", stats.counts[ProcessingStatus.QUEUED] || 0],
      ["Processing", (stats.counts[ProcessingStatus.PREPARING] || 0) + (stats.counts[ProcessingStatus.PROCESSING] || 0) + (stats.counts[ProcessingStatus.QUALITY_CHECK] || 0)],
      ["Success", stats.counts[ProcessingStatus.SUCCESS] || 0],
      ["Warning", stats.counts[ProcessingStatus.WARNING] || 0],
      ["Failed", stats.counts[ProcessingStatus.FAILED] || 0],
      ["Blocked", stats.counts[ProcessingStatus.BLOCKED] || 0],
      ["Cancelled", stats.counts[ProcessingStatus.CANCELLED] || 0],
      ["Avg duration", stats.avgDuration != null ? `${stats.avgDuration.toFixed(2)}s` : "—"],
      ["Quality improved", stats.improved],
      ["Quality degraded", stats.degraded],
    ]) {
      const metric = document.createElement("div");
      metric.className = "metric";
      metric.innerHTML = `<div class="value">${value}</div><div class="label">${label}</div>`;
      dashboard.appendChild(metric);
    }
    wrapper.appendChild(dashboard);

    const profilesHeading = document.createElement("h3");
    profilesHeading.textContent = "Processing profiles";
    wrapper.appendChild(profilesHeading);
    const profileEditor = document.createElement("avl-processing-profile-editor");
    profileEditor.profileStore = this._services?.processingProfileStore;
    wrapper.appendChild(profileEditor);

    const recordingsHeading = document.createElement("h3");
    recordingsHeading.textContent = "Recordings";
    wrapper.appendChild(recordingsHeading);
    wrapper.appendChild(this._buildRecordingsTable());

    const queueHeading = document.createElement("h3");
    queueHeading.textContent = "Processing queue";
    wrapper.appendChild(queueHeading);
    const queueEl = document.createElement("avl-processing-queue");
    queueEl.profileStore = this._services?.processingProfileStore;
    queueEl.queue = this._services?.processingQueueStore;
    wrapper.appendChild(queueEl);

    if (this._selectedRecordingId) {
      const recording = this._recordings.find((r) => r.id === this._selectedRecordingId);
      const item = this._latestItemFor(this._selectedRecordingId);

      const compareHeading = document.createElement("h3");
      compareHeading.textContent = "Before / After";
      wrapper.appendChild(compareHeading);
      const comparison = document.createElement("avl-before-after-comparison");
      comparison.recording = recording;
      comparison.item = item;
      wrapper.appendChild(comparison);

      const historyHeading = document.createElement("h3");
      historyHeading.textContent = "Processing history";
      wrapper.appendChild(historyHeading);
      const historyPanel = document.createElement("avl-processing-history-panel");
      historyPanel.historyStore = this._services?.processingHistoryStore;
      historyPanel.recordingId = this._selectedRecordingId;
      wrapper.appendChild(historyPanel);

      const feedbackHeading = document.createElement("h3");
      feedbackHeading.textContent = "Processing feedback";
      wrapper.appendChild(feedbackHeading);
      const feedbackForm = document.createElement("avl-processing-feedback-form");
      feedbackForm.feedbackStore = this._services?.feedbackStore;
      const current = this._services?.processingHistoryStore?.current(this._selectedRecordingId);
      feedbackForm.targetId = current ? current.recordId : null;
      wrapper.appendChild(feedbackForm);
    }

    this.shadowRoot.appendChild(wrapper);
  }

  _latestItemFor(recordingId) {
    const items = this._services?.processingQueueStore?.list().filter((i) => i.recordingId === recordingId) || [];
    return items.length ? items[items.length - 1] : null;
  }

  _buildRecordingsTable() {
    const count = document.createElement("div");
    count.className = "count";
    count.textContent = `${this._recordings.length} recording(s)`;

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Filename</th><th>Batch</th><th>Latest status</th><th>Actions</th></tr>";
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const recording of this._recordings) {
      const row = document.createElement("tr");
      row.setAttribute("data-selectable", "");
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.innerHTML = `<td>${recording.filename}</td><td>${recording.batchId}</td>`;

      const statusCell = document.createElement("td");
      const latest = this._latestItemFor(recording.id);
      if (latest) {
        const badge = document.createElement("avl-status-badge");
        badge.setAttribute("domain", "processing_status");
        badge.setAttribute("state", latest.status);
        statusCell.appendChild(badge);
      } else {
        statusCell.textContent = "not queued";
      }
      row.appendChild(statusCell);

      const actionsCell = document.createElement("td");
      const queueButton = document.createElement("avl-button");
      queueButton.setAttribute("variant", "primary");
      queueButton.setAttribute("type", "button");
      queueButton.textContent = "Queue for processing";
      queueButton.addEventListener("click", (event) => {
        event.stopPropagation();
        const profile = this._services?.processingProfileStore?.default();
        if (!profile || !this._services?.processingQueueStore) return;
        const item = this._services.processingQueueStore.enqueue({ recordingId: recording.id, profile });
        this._services.processingQueueStore.processOne(item.itemId).then((result) => {
          if (this._services.processingHistoryStore) {
            const priorCurrent = this._services.processingHistoryStore.current(recording.id);
            this._services.processingHistoryStore.record({
              recordingId: recording.id,
              item: result,
              supersedes: priorCurrent ? priorCurrent.recordId : null,
            });
          }
        });
      });
      actionsCell.appendChild(queueButton);
      row.appendChild(actionsCell);

      row.addEventListener("click", () => {
        this._selectedRecordingId = recording.id;
        this._selectionModel?.select("recording", recording.id, recording);
        this._render();
      });
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          row.click();
        }
      });
      tbody.appendChild(row);
    }
    table.appendChild(tbody);

    const wrapper = document.createElement("div");
    wrapper.append(count, table);
    return wrapper;
  }
}

defineComponent("avl-workspace-processing", AvlWorkspaceProcessing);
