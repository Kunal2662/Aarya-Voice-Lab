// <avl-workspace-dataset-review> — VL-D3 §4, §14, §19, §20. The Dataset
// Review + Voice Quality Analysis dashboard: real counts computed from
// actual fixture/state data (never fabricated), a filterable/sortable
// recording table, and a persistent review queue of not-yet-decided
// candidate segments. Selecting a recording routes through the shared
// selectionModel exactly like avl-workspace-recordings, so the expanded
// Inspector (§21) renders its Quality/Waveform/Segments/Overlap/Technical
// Review sections for whatever is selected here.
//
// This surface stays inside the technical-review boundary throughout
// (VL-D3 §3): it reports quality, warnings, segmentation, and overlap
// CANDIDATES only. It never asks or records who is speaking.
import { AvlElement, defineComponent } from "./base-element.js";
import {
  syntheticRecordings,
  syntheticBatches,
  syntheticQualityAssessments,
  syntheticSegments,
  syntheticOverlapCandidates,
} from "../state/synthetic-fixtures.js";
import { summarizeQuality } from "../state/quality-summary.js";
import "./workspace-state.js";
import "./status-badge.js";
import "./dataset-quality-summary.js";

const QUALITY_RANK = { NOT_ANALYZED: 0, FAIL: 1, REVIEW: 2, WARNING: 3, PASS: 4 };

const SORT_OPTIONS = [
  ["filename", "Filename"],
  ["durationSeconds", "Duration"],
  ["qualityRank", "Quality"],
  ["snr", "SNR"],
  ["noiseFloor", "Noise floor"],
  ["speechRatio", "Speech ratio"],
  ["warningCount", "Warning count"],
];

function buildRow(recording, assessments) {
  const assessment = assessments[recording.id] || null;
  const segments = syntheticSegments(recording.id);
  const overlapCandidates = syntheticOverlapCandidates(recording.id);
  const speechSegments = segments.filter((s) => s.kind === "speech");
  const candidateStates = new Set(speechSegments.map((s) => s.candidateState).filter(Boolean));
  let candidateState = "PENDING";
  if (candidateStates.has("NEEDS_REVIEW")) candidateState = "NEEDS_REVIEW";
  else if (candidateStates.size === 1 && candidateStates.has("ACCEPTED")) candidateState = "ACCEPTED";
  else if (candidateStates.size === 1 && candidateStates.has("REJECTED")) candidateState = "REJECTED";
  else if (candidateStates.has("PENDING")) candidateState = "PENDING";

  const measurements = assessment ? assessment.measurements : {};
  const speech = assessment ? assessment.speech : {};
  const narrowband = assessment ? assessment.characteristics.some((c) => c.includes("narrowband")) : false;
  const hasOverlap = overlapCandidates.length > 0;

  return {
    recording,
    assessment,
    segments,
    overlapCandidates,
    candidateState,
    decision: assessment ? assessment.decision : "NOT_ANALYZED",
    qualityRank: QUALITY_RANK[assessment ? assessment.decision : "NOT_ANALYZED"],
    warningCount: assessment ? assessment.findings.length : 0,
    snr: measurements.estimatedSnrDb ?? null,
    noiseFloor: measurements.noiseFloorDbfs ?? null,
    speechRatio: speech.speechRatio ?? null,
    narrowband,
    hasOverlap,
  };
}

export class AvlWorkspaceDatasetReview extends AvlElement {
  set selectionModel(value) {
    this._selectionModel = value;
  }

  set services(value) {
    this._services = value || {};
    if (this._reviewStore) this._reviewStore.removeEventListener("change", this._onReviewChange);
    this._reviewStore = this._services.reviewStore || null;
    this._onReviewChange = () => this._render();
    if (this._reviewStore) this._reviewStore.addEventListener("change", this._onReviewChange);
  }

  connectedCallback() {
    this._search = this._search || "";
    this._batchFilter = this._batchFilter || "";
    this._qualityFilter = this._qualityFilter || "";
    this._sampleRateFilter = this._sampleRateFilter || "";
    this._channelsFilter = this._channelsFilter || "";
    this._narrowbandOnly = this._narrowbandOnly || false;
    this._overlapOnly = this._overlapOnly || false;
    this._candidateFilter = this._candidateFilter || "";
    this._sortKey = this._sortKey || "filename";
    this._sortDir = this._sortDir || 1;
    this._load();
  }

  disconnectedCallback() {
    if (this._reviewStore) this._reviewStore.removeEventListener("change", this._onReviewChange);
  }

  _load() {
    this._state = "loading";
    this._render();
    const recordings = syntheticRecordings();
    const assessments = syntheticQualityAssessments();
    this._batches = syntheticBatches();
    this._rows = recordings.map((recording) => buildRow(recording, assessments));
    this._state = this._rows.length ? "ready" : "empty";
    this._render();
  }

  _counts() {
    const rows = this._rows || [];
    const blockedBatchIds = new Set();
    let blocked = 0;
    for (const row of rows) {
      if (!blockedBatchIds.has(row.recording.batchId)) {
        blockedBatchIds.add(row.recording.batchId);
        const batch = (this._batches || []).find((b) => b.id === row.recording.batchId);
        blocked += batch ? batch.blocked : 0;
      }
    }
    return {
      total: rows.length,
      analyzed: rows.filter((r) => r.assessment).length,
      notAnalyzed: rows.filter((r) => !r.assessment).length,
      ready: rows.filter((r) => r.decision === "PASS").length,
      warning: rows.filter((r) => r.decision === "WARNING").length,
      invalid: rows.filter((r) => r.decision === "FAIL").length,
      blocked,
      reviewRequired: rows.filter((r) => r.decision === "REVIEW").length,
      segments: rows.reduce((sum, r) => sum + r.segments.length, 0),
      candidates: rows.reduce((sum, r) => sum + r.segments.filter((s) => s.kind === "speech").length, 0),
    };
  }

  _filtered() {
    let rows = this._rows || [];
    if (this._search) {
      const needle = this._search.toLowerCase();
      rows = rows.filter(
        (r) =>
          r.recording.filename.toLowerCase().includes(needle) ||
          r.recording.id.toLowerCase().includes(needle) ||
          r.recording.batchId.toLowerCase().includes(needle) ||
          r.recording.contentAddressedId.toLowerCase().includes(needle),
      );
    }
    if (this._batchFilter) rows = rows.filter((r) => r.recording.batchId === this._batchFilter);
    if (this._qualityFilter) rows = rows.filter((r) => r.decision === this._qualityFilter);
    if (this._sampleRateFilter) rows = rows.filter((r) => String(r.recording.sampleRate) === this._sampleRateFilter);
    if (this._channelsFilter) rows = rows.filter((r) => String(r.recording.channels) === this._channelsFilter);
    if (this._narrowbandOnly) rows = rows.filter((r) => r.narrowband);
    if (this._overlapOnly) rows = rows.filter((r) => r.hasOverlap);
    if (this._candidateFilter) rows = rows.filter((r) => r.candidateState === this._candidateFilter);

    rows = [...rows].sort((a, b) => {
      let av;
      let bv;
      if (this._sortKey === "filename") {
        av = a.recording.filename;
        bv = b.recording.filename;
      } else if (this._sortKey === "durationSeconds") {
        av = a.recording.durationSeconds;
        bv = b.recording.durationSeconds;
      } else {
        av = a[this._sortKey];
        bv = b[this._sortKey];
      }
      // Deterministic: null/undefined always sorts last, ties break on recording id.
      if (av == null && bv == null) return a.recording.id.localeCompare(b.recording.id);
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av === bv) return a.recording.id.localeCompare(b.recording.id);
      return (av > bv ? 1 : -1) * this._sortDir;
    });
    return rows;
  }

  _reviewQueue() {
    const entries = [];
    for (const row of this._rows || []) {
      for (const segment of row.segments) {
        if (segment.kind !== "speech") continue;
        const current = this._reviewStore ? this._reviewStore.current(segment.segmentId) : null;
        const state = current ? current.decision : segment.candidateState;
        if (state === "PENDING" || state === "NEEDS_REVIEW") {
          entries.push({ recording: row.recording, segment, state });
        }
      }
    }
    return entries;
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
      .controls { display: flex; gap: var(--avl-space-2); flex-wrap: wrap; margin-bottom: var(--avl-space-3); align-items: center; }
      input, select { padding: var(--avl-space-1) var(--avl-space-2); border-radius: var(--avl-radius-sm); border: 1px solid var(--avl-color-border-default); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      label.check { display: flex; align-items: center; gap: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      th button { background: none; border: none; cursor: pointer; color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); padding: 0; }
      tr[data-selectable] { cursor: pointer; }
      tr[data-selectable]:hover { background: var(--avl-color-surface-sunken); }
      .count { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); margin-bottom: var(--avl-space-2); }
      .empty-queue { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "empty") wrapper.setAttribute("title", "No recordings to review yet");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Dataset Review";
    wrapper.appendChild(heading);

    if (this._state === "ready" && this._rows) {
      const counts = this._counts();
      const dashboard = document.createElement("div");
      dashboard.className = "dashboard";
      const metrics = [
        ["Total recordings", counts.total],
        ["Analyzed", counts.analyzed],
        ["Not analyzed", counts.notAnalyzed],
        ["Ready (PASS)", counts.ready],
        ["Warning", counts.warning],
        ["Invalid (FAIL)", counts.invalid],
        ["Blocked", counts.blocked],
        ["Review required", counts.reviewRequired],
        ["Segments", counts.segments],
        ["Candidates", counts.candidates],
      ];
      for (const [label, value] of metrics) {
        const metric = document.createElement("div");
        metric.className = "metric";
        metric.innerHTML = `<div class="value">${value}</div><div class="label">${label}</div>`;
        dashboard.appendChild(metric);
      }
      wrapper.appendChild(dashboard);

      const summary = document.createElement("avl-dataset-quality-summary");
      summary.summary = summarizeQuality();
      summary.style.display = "block";
      summary.style.marginBottom = "var(--avl-space-4)";
      wrapper.appendChild(summary);

      const controls = document.createElement("div");
      controls.className = "controls";

      const search = document.createElement("input");
      search.type = "search";
      search.placeholder = "Search filename, recording ID, batch ID, content ID…";
      search.value = this._search;
      search.setAttribute("aria-label", "Search recordings");
      search.style.minWidth = "16rem";
      search.addEventListener("input", () => {
        this._search = search.value;
        this._render();
      });
      controls.appendChild(search);

      const batches = [...new Set(this._rows.map((r) => r.recording.batchId))];
      controls.appendChild(this._buildSelect("Batch", batches, this._batchFilter, (v) => (this._batchFilter = v)));

      const qualities = ["NOT_ANALYZED", "PASS", "WARNING", "REVIEW", "FAIL"];
      controls.appendChild(this._buildSelect("Quality", qualities, this._qualityFilter, (v) => (this._qualityFilter = v)));

      const sampleRates = [...new Set(this._rows.map((r) => String(r.recording.sampleRate)))];
      controls.appendChild(
        this._buildSelect("Sample rate", sampleRates, this._sampleRateFilter, (v) => (this._sampleRateFilter = v)),
      );

      const channels = [...new Set(this._rows.map((r) => String(r.recording.channels)))];
      controls.appendChild(this._buildSelect("Channels", channels, this._channelsFilter, (v) => (this._channelsFilter = v)));

      const candidateStates = ["PENDING", "ACCEPTED", "REJECTED", "NEEDS_REVIEW"];
      controls.appendChild(
        this._buildSelect("Candidate state", candidateStates, this._candidateFilter, (v) => (this._candidateFilter = v)),
      );

      const narrowbandLabel = document.createElement("label");
      narrowbandLabel.className = "check";
      const narrowbandCheckbox = document.createElement("input");
      narrowbandCheckbox.type = "checkbox";
      narrowbandCheckbox.checked = this._narrowbandOnly;
      narrowbandCheckbox.addEventListener("change", () => {
        this._narrowbandOnly = narrowbandCheckbox.checked;
        this._render();
      });
      narrowbandLabel.append(narrowbandCheckbox, document.createTextNode("Narrowband only"));
      controls.appendChild(narrowbandLabel);

      const overlapLabel = document.createElement("label");
      overlapLabel.className = "check";
      const overlapCheckbox = document.createElement("input");
      overlapCheckbox.type = "checkbox";
      overlapCheckbox.checked = this._overlapOnly;
      overlapCheckbox.addEventListener("change", () => {
        this._overlapOnly = overlapCheckbox.checked;
        this._render();
      });
      overlapLabel.append(overlapCheckbox, document.createTextNode("Overlap candidates only"));
      controls.appendChild(overlapLabel);

      const sortLabel = document.createElement("label");
      sortLabel.className = "check";
      const sortSelect = document.createElement("select");
      sortSelect.setAttribute("aria-label", "Sort by");
      for (const [key, label] of SORT_OPTIONS) {
        const option = document.createElement("option");
        option.value = key;
        option.textContent = `Sort: ${label}`;
        sortSelect.appendChild(option);
      }
      sortSelect.value = this._sortKey;
      sortSelect.addEventListener("change", () => {
        this._sortKey = sortSelect.value;
        this._render();
      });
      sortLabel.appendChild(sortSelect);
      controls.appendChild(sortLabel);

      wrapper.appendChild(controls);

      const filtered = this._filtered();
      const count = document.createElement("div");
      count.className = "count";
      count.textContent = `${filtered.length} of ${this._rows.length} recording(s)`;
      wrapper.appendChild(count);

      wrapper.appendChild(this._buildTable(filtered));
      wrapper.appendChild(this._buildReviewQueue());
    }

    this.shadowRoot.appendChild(wrapper);
  }

  _buildTable(rows) {
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML =
      "<tr><th>Filename</th><th>Batch</th><th>Duration</th><th>Sample rate</th><th>Quality</th><th>Warnings</th><th>Segments</th><th>Overlap</th><th>Candidate state</th></tr>";
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.setAttribute("data-selectable", "");
      tr.tabIndex = 0;
      tr.setAttribute("role", "button");
      tr.innerHTML = `
        <td>${row.recording.filename}</td>
        <td>${row.recording.batchId}</td>
        <td>${row.recording.durationSeconds}s</td>
        <td>${row.recording.sampleRate} Hz</td>
      `;
      const qualityCell = document.createElement("td");
      const qualityBadge = document.createElement("avl-status-badge");
      qualityBadge.setAttribute("domain", "quality_decision");
      qualityBadge.setAttribute("state", row.decision);
      qualityCell.appendChild(qualityBadge);
      tr.appendChild(qualityCell);

      const warningsCell = document.createElement("td");
      warningsCell.textContent = String(row.warningCount);
      tr.appendChild(warningsCell);

      const segmentsCell = document.createElement("td");
      segmentsCell.textContent = String(row.segments.length);
      tr.appendChild(segmentsCell);

      const overlapCell = document.createElement("td");
      overlapCell.textContent = row.hasOverlap ? `${row.overlapCandidates.length} candidate(s)` : "none";
      tr.appendChild(overlapCell);

      const candidateCell = document.createElement("td");
      const candidateBadge = document.createElement("avl-status-badge");
      candidateBadge.setAttribute("domain", "candidate_review");
      candidateBadge.setAttribute("state", row.candidateState);
      candidateCell.appendChild(candidateBadge);
      tr.appendChild(candidateCell);

      tr.addEventListener("click", () => this._selectionModel?.select("recording", row.recording.id, row.recording));
      tr.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          tr.click();
        }
      });
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    return table;
  }

  _buildReviewQueue() {
    const section = document.createElement("div");
    const heading = document.createElement("h3");
    heading.textContent = "Review queue";
    section.appendChild(heading);

    const queue = this._reviewQueue();
    if (!queue.length) {
      const empty = document.createElement("p");
      empty.className = "empty-queue";
      empty.textContent = "No candidates awaiting technical review.";
      section.appendChild(empty);
      return section;
    }

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Segment</th><th>Recording</th><th>Duration</th><th>Quality</th><th>State</th></tr>";
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const entry of queue) {
      const tr = document.createElement("tr");
      tr.setAttribute("data-selectable", "");
      tr.tabIndex = 0;
      tr.setAttribute("role", "button");
      tr.innerHTML = `
        <td>${entry.segment.segmentId}</td>
        <td>${entry.recording.filename}</td>
        <td>${(entry.segment.end - entry.segment.start).toFixed(2)}s</td>
      `;
      const qualityCell = document.createElement("td");
      if (entry.segment.qualityState) {
        const badge = document.createElement("avl-status-badge");
        badge.setAttribute("domain", "quality_decision");
        badge.setAttribute("state", entry.segment.qualityState);
        qualityCell.appendChild(badge);
      } else {
        qualityCell.textContent = "—";
      }
      tr.appendChild(qualityCell);

      const stateCell = document.createElement("td");
      const stateBadge = document.createElement("avl-status-badge");
      stateBadge.setAttribute("domain", "candidate_review");
      stateBadge.setAttribute("state", entry.state);
      stateCell.appendChild(stateBadge);
      tr.appendChild(stateCell);

      tr.addEventListener("click", () => this._selectionModel?.select("recording", entry.recording.id, entry.recording));
      tr.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          tr.click();
        }
      });
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    section.appendChild(table);
    return section;
  }

  _buildSelect(label, values, current, onChange) {
    const select = document.createElement("select");
    select.setAttribute("aria-label", `Filter by ${label}`);
    const allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = `All ${label.toLowerCase()}`;
    select.appendChild(allOption);
    for (const value of values) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    }
    select.value = current;
    select.addEventListener("change", () => {
      onChange(select.value);
      this._render();
    });
    return select;
  }
}

defineComponent("avl-workspace-dataset-review", AvlWorkspaceDatasetReview);
