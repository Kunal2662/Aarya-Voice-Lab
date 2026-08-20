// <avl-inspector-router> — the Inspector's content (VL-D1 §22). Set
// `.selection` to a {kind, id, data} object from
// state/selection-model.js. Renders progressive disclosure: a compact
// summary always visible, with any longer/structured data (job logs
// reference, activity detail JSON) behind a native <details> so the
// panel never dumps everything at once.
import { AvlElement, defineComponent } from "./base-element.js";
import { JOB_STATUS_DOMAIN } from "../state/job-model.js";
import {
  syntheticQualityAssessments,
  syntheticSegments,
  syntheticOverlapCandidates,
  syntheticWaveformPeaks,
} from "../state/synthetic-fixtures.js";
import "./status-badge.js";
import "./metric-placeholder.js";
import "./quality-profile.js";
import "./waveform-visualization.js";
import "./segment-timeline.js";
import "./overlap-review-list.js";
import "./candidate-review-panel.js";
import "./feedback-form.js";
import "./claude-review-context.js";
import "./audio-player.js";

const RENDERERS = {
  batch: (data) => [
    ["Batch", data.id],
    ["Status", { badge: [JOB_STATUS_DOMAIN, data.status] }],
    ["Files", data.fileCount],
    ["Valid / warning / invalid / blocked", `${data.valid} / ${data.warning} / ${data.invalid} / ${data.blocked}`],
    ["Review items", data.reviewItems],
    ["Created", data.created],
  ],
  recording: (data) => [
    ["Content-addressed ID", data.contentAddressedId],
    ["Filename", data.filename],
    ["Format", data.format],
    ["Duration", `${data.durationSeconds}s`],
    ["Sample rate", `${data.sampleRate} Hz`],
    ["Channels", data.channels],
    ["Validation", data.validation],
    ["Quality", data.quality],
    ["Classification", data.classification],
    ["Batch", data.batchId],
    ["Pipeline status", { badge: [JOB_STATUS_DOMAIN, data.processingState === "candidate_manifest" ? "success" : "running"] }],
    // Future engines (VL-D3+). Never fabricated — always the honest
    // placeholder until a real analysis exists (VL-D2 §15).
    ["Speaker identity", "NOT AVAILABLE — behind the Phase 3+ speaker-identity boundary"],
    ["Accent fidelity", "NOT ANALYZED"],
    ["Pronunciation fidelity", "NOT ANALYZED"],
    ["Calibration", "NOT CALIBRATED"],
  ],
  "pipeline-stage": (data) => [
    ["Stage", data.name],
    ["Phase", data.phase],
    ["Implemented", data.implemented ? "yes" : "no"],
    ["Runtime status", { badge: [JOB_STATUS_DOMAIN, data.runtimeState || "not_started"] }],
    ["Logs reference", data.logsRef || "not available"],
  ],
  job: (data) => [
    ["Job", data.id],
    ["Type", data.type],
    ["Status", { badge: [JOB_STATUS_DOMAIN, data.status] }],
    ["Current stage", data.currentStage || "—"],
    ["Started", data.startTime || "—"],
    ["Ended", data.endTime || "—"],
    ["Related", data.relatedEntity ? `${data.relatedEntity.kind}:${data.relatedEntity.id}` : "—"],
    ["Logs reference", data.logsRef || "not available"],
    ["Error", data.error || "—"],
  ],
  activity: (data) => [
    ["Event", data.id],
    ["Source", data.source],
    ["Severity", { badge: ["activity_severity", data.severity] }],
    ["Timestamp", data.timestamp],
    ["Summary", data.summary],
  ],
  voice: (data) => [
    ["Voice", data.name],
    ["Version", data.version],
    ["Preview version", data.previewVersion],
    ["Feedback", data.feedback],
    ["Calibration state", { badge: ["calibration", data.calibrationState] }],
    ["Speaker verification", data.speakerVerificationState],
  ],
  model: (data) => [
    ["Model", data.name],
    ["Version", data.version],
    ["Runtime", data.runtime],
    ["Backend", data.backend],
    ["Hardware compatibility", data.hardwareCompatible],
    ["Status", { badge: ["hardware", (data.status || "unknown").toUpperCase()] }],
    ["Calibration state", { badge: ["calibration", data.calibrationState] }],
  ],
};

export class AvlInspectorRouter extends AvlElement {
  set selection(value) {
    this._selection = value || null;
    this._selectedSegment = null;
    if (this.isConnected) this._render();
  }

  set services(value) {
    this._services = value || {};
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .rows { display: flex; flex-direction: column; gap: var(--avl-space-1); }
      .row { display: flex; justify-content: space-between; gap: var(--avl-space-2); padding: var(--avl-space-1) 0; border-bottom: 1px solid var(--avl-color-border-subtle); }
      .row:last-child { border-bottom: none; }
      .label { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); }
      .value { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); text-align: right; word-break: break-word; }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      details { margin-top: var(--avl-space-3); border-top: 1px solid var(--avl-color-border-subtle); padding-top: var(--avl-space-2); }
      summary { cursor: pointer; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; color: var(--avl-color-text-secondary); }
      details > *:not(summary) { margin-top: var(--avl-space-2); }
    `;
    this.shadowRoot.appendChild(style);

    const selection = this._selection;
    if (!selection || !RENDERERS[selection.kind]) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Nothing selected.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const rows = document.createElement("div");
    rows.className = "rows";
    for (const [label, value] of RENDERERS[selection.kind](selection.data || {})) {
      const row = document.createElement("div");
      row.className = "row";
      const labelEl = document.createElement("span");
      labelEl.className = "label";
      labelEl.textContent = label;
      row.appendChild(labelEl);

      if (value && typeof value === "object" && value.badge) {
        const badge = document.createElement("avl-status-badge");
        badge.setAttribute("domain", value.badge[0]);
        badge.setAttribute("state", value.badge[1]);
        row.appendChild(badge);
      } else {
        const valueEl = document.createElement("span");
        valueEl.className = "value";
        valueEl.textContent = value == null || value === "" ? "—" : String(value);
        row.appendChild(valueEl);
      }
      rows.appendChild(row);
    }
    this.shadowRoot.appendChild(rows);

    if (selection.kind === "recording") {
      this._appendRecordingSections(selection.data || {});
    }
  }

  // VL-D3 §21 — the sections a technical review of one recording needs:
  // Quality, Waveform, Speech-Silence, Segments, Overlap, Technical
  // Review, Provenance. Identity/Metadata/Pipeline are already covered by
  // RENDERERS.recording above. Nothing here determines or displays
  // speaker identity (VL-D3 §3) — that stays outside this surface.
  _appendRecordingSections(data) {
    const assessment = syntheticQualityAssessments()[data.id] || null;
    const segments = syntheticSegments(data.id);
    const overlapCandidates = syntheticOverlapCandidates(data.id);
    const peaks = syntheticWaveformPeaks(data.id);

    const qualityDetails = document.createElement("details");
    qualityDetails.open = true;
    qualityDetails.innerHTML = "<summary>Quality</summary>";
    const qualityProfile = document.createElement("avl-quality-profile");
    qualityProfile.assessment = assessment;
    qualityDetails.appendChild(qualityProfile);
    const askClaude = document.createElement("avl-claude-review-context");
    askClaude.recording = data;
    askClaude.assessment = assessment;
    if (this._services && this._services.executor) askClaude.executor = this._services.executor;
    qualityDetails.appendChild(askClaude);
    this.shadowRoot.appendChild(qualityDetails);

    const waveformDetails = document.createElement("details");
    waveformDetails.innerHTML = "<summary>Waveform</summary>";
    // VL-D3 §9 — the audio player lives beside the waveform it plays
    // over. No real recording exists to play (and won't until the
    // dataset access gate is satisfied) — see components/audio-player.js
    // and state/synthetic-tone.js for why this is a synthetic tone.
    const player = document.createElement("avl-audio-player");
    player.setAttribute("recording-id", data.id || "");
    player.setAttribute("duration-seconds", String(data.durationSeconds || 3));
    waveformDetails.appendChild(player);
    const waveform = document.createElement("avl-waveform-visualization");
    waveform.peaks = peaks;
    waveform.durationSeconds = data.durationSeconds || 0;
    waveform.segments = segments;
    waveform.overlapCandidates = overlapCandidates;
    waveformDetails.appendChild(waveform);
    this.shadowRoot.appendChild(waveformDetails);

    const speechDetails = document.createElement("details");
    speechDetails.innerHTML = "<summary>Speech / Silence</summary>";
    const speechRows = document.createElement("div");
    speechRows.className = "rows";
    const speech = assessment ? assessment.speech : {};
    const measurements = assessment ? assessment.measurements : {};
    for (const [label, value] of [
      ["Speech ratio", speech.speechRatio != null ? `${(speech.speechRatio * 100).toFixed(1)}%` : null],
      ["Silence ratio", measurements.silentFrameRatio != null ? `${(measurements.silentFrameRatio * 100).toFixed(1)}%` : null],
      ["Speech region count", speech.speechRegionCount],
      ["Long pause count", speech.longPauseCount],
    ]) {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `<span class="label">${label}</span><span class="value">${value == null ? "—" : value}</span>`;
      speechRows.appendChild(row);
    }
    speechDetails.appendChild(speechRows);
    this.shadowRoot.appendChild(speechDetails);

    const segmentsDetails = document.createElement("details");
    segmentsDetails.innerHTML = "<summary>Segments</summary>";
    const segmentTimeline = document.createElement("avl-segment-timeline");
    segmentTimeline.segments = segments;
    segmentTimeline.addEventListener("select", (event) => {
      this._selectedSegment = event.detail.segment;
      this._render();
    });
    segmentsDetails.appendChild(segmentTimeline);
    segmentsDetails.open = true;
    this.shadowRoot.appendChild(segmentsDetails);

    const overlapDetails = document.createElement("details");
    overlapDetails.innerHTML = "<summary>Overlap</summary>";
    const overlapList = document.createElement("avl-overlap-review-list");
    overlapList.overlapCandidates = overlapCandidates;
    overlapDetails.appendChild(overlapList);
    this.shadowRoot.appendChild(overlapDetails);

    const reviewDetails = document.createElement("details");
    reviewDetails.open = true;
    reviewDetails.innerHTML = "<summary>Technical Review</summary>";
    const reviewPanel = document.createElement("avl-candidate-review-panel");
    reviewPanel.reviewStore = this._services ? this._services.reviewStore : null;
    reviewPanel.segment = this._selectedSegment;
    reviewDetails.appendChild(reviewPanel);
    this.shadowRoot.appendChild(reviewDetails);

    const feedbackDetails = document.createElement("details");
    feedbackDetails.innerHTML = "<summary>Feedback</summary>";
    const feedbackForm = document.createElement("avl-feedback-form");
    feedbackForm.feedbackStore = this._services ? this._services.feedbackStore : null;
    feedbackForm.targetId = data.id || null;
    feedbackDetails.appendChild(feedbackForm);
    this.shadowRoot.appendChild(feedbackDetails);

    const provenanceDetails = document.createElement("details");
    provenanceDetails.innerHTML = "<summary>Provenance</summary>";
    const provenanceRows = document.createElement("div");
    provenanceRows.className = "rows";
    for (const [label, value] of [
      ["Source content ID", data.contentAddressedId],
      ["Recording ID", data.id],
      ["Batch ID", data.batchId],
      ["Classification", data.classification],
    ]) {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `<span class="label">${label}</span><span class="value">${value == null || value === "" ? "—" : value}</span>`;
      provenanceRows.appendChild(row);
    }
    provenanceDetails.appendChild(provenanceRows);
    this.shadowRoot.appendChild(provenanceDetails);
  }
}

defineComponent("avl-inspector-router", AvlInspectorRouter);
