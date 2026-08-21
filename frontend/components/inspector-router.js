// <avl-inspector-router> — the Inspector's content (VL-D1 §22). Set
// `.selection` to a {kind, id, data} object from
// state/selection-model.js. Renders progressive disclosure: a compact
// summary always visible, with any longer/structured data (job logs
// reference, activity detail JSON) behind a native <details> so the
// panel never dumps everything at once.
import { AvlElement, defineComponent } from "./base-element.js";
import { JOB_STATUS_DOMAIN } from "../state/job-model.js";
import { summarizeOutputEvaluations } from "../state/evaluation-model.js";
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
import "./processing-history-panel.js";
import "./processing-feedback-form.js";
import "./claude-processing-context.js";
import "./generation-history-panel.js";
import "./preview-feedback-form.js";
import "./claude-generation-context.js";
import "./evaluation-history-panel.js";
import "./disagreement-view.js";
import "./aggregated-results-panel.js";
import "./claude-evaluation-context.js";

// FE-1.8 -- human-readable heading text per selection.kind, so the
// panel's content is reachable by heading-based screen-reader
// navigation (previously jumped straight from a workspace's own <h2>
// to an isolated <h4> subsection heading with nothing bridging them).
const KIND_LABELS = {
  batch: "Batch",
  recording: "Recording",
  "pipeline-stage": "Pipeline stage",
  job: "Job",
  activity: "Activity event",
  voice: "Voice",
  model: "Model",
  "calibration-profile": "Calibration profile",
  "voice-profile": "Voice profile",
};

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
  // VL-D8 -- one calibration engine profile, selected from
  // avl-calibration-profile-history. run_state/calibration_state/
  // application_state are three deliberately independent badges, never
  // merged. before/after values render exactly what validation
  // measured, honestly "—" when not yet validated or not measurable.
  "calibration-profile": (data) => [
    ["Profile", data.profile_id],
    ["Version", data.profile_version],
    ["Run state", { badge: ["hardware_calibration", data.run_state] }],
    ["Evidence state", { badge: ["calibration", data.calibration_state] }],
    ["Application state", data.application_state],
    ["Strategy", data.strategy],
    ["Applied parameter", data.applied_parameter_name],
    ["Applied value", data.applied_value],
    ["Applied from", data.applied_from_profile_id],
    ["Before (batches)", data.validation ? data.validation.before_batch_count : null],
    ["After (batches)", data.validation ? data.validation.after_batch_count : null],
    ["Measured delta", data.validation ? data.validation.measured_delta : null],
    ["Not measurable", data.validation ? String(data.validation.not_measurable) : null],
    ["Supersedes", data.supersedes],
    ["Is rollback", String(data.is_rollback)],
    ["Created", data.created_at],
  ],
  "voice-profile": (data) => [
    ["Profile", data.name],
    ["Version", data.version],
    ["State", { badge: ["voice_profile_state", data.state] }],
    ["Style controls", Object.keys(data.style_controls || {}).length ? JSON.stringify(data.style_controls) : "—"],
    [
      "Generation preferences",
      Object.keys(data.generation_preferences || {}).length ? JSON.stringify(data.generation_preferences) : "—",
    ],
    ["Notes", data.notes],
    ["Created", data.created_at],
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
      /* FE-1.5 -- .row/.row:last-child replaced by the shared
         avl-row/avl-row--bordered utilities (css/base.css); see every
         className = "avl-row avl-row--bordered" call site below. */
      .label { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); }
      .value { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); text-align: right; word-break: break-word; }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      details { margin-top: var(--avl-space-3); border-top: 1px solid var(--avl-color-border-subtle); padding-top: var(--avl-space-2); }
      summary { cursor: pointer; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; color: var(--avl-color-text-secondary); }
      details > *:not(summary) { margin-top: var(--avl-space-2); }
      h4 { margin: var(--avl-space-3) 0 var(--avl-space-1) 0; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; color: var(--avl-color-text-secondary); }
      /* FE-1.8 -- selection-kind heading, same visual treatment as the
         h4 subsections below it (no visual redesign). Nests under the
         wrapping <avl-panel title="Inspector">'s own <h3> (also fixed
         in FE-1.8 -- was a plain <span> before), so heading-based
         navigation reads Inspector (h3) -> Batch/Recording/etc (h4)
         instead of jumping straight to an unlabelled subsection. */
      h4.panel-heading { margin: 0 0 var(--avl-space-2) 0; }
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

    const heading = document.createElement("h4");
    heading.className = "panel-heading";
    heading.textContent = KIND_LABELS[selection.kind] || "Inspector";
    this.shadowRoot.appendChild(heading);

    const rows = document.createElement("div");
    rows.className = "rows";
    for (const [label, value] of RENDERERS[selection.kind](selection.data || {})) {
      const row = document.createElement("div");
      row.className = "avl-row avl-row--bordered";
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
    if (selection.kind === "voice-profile") {
      this._appendPreviewSection(selection.data || {});
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
      row.className = "avl-row avl-row--bordered";
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
      row.className = "avl-row avl-row--bordered";
      row.innerHTML = `<span class="label">${label}</span><span class="value">${value == null || value === "" ? "—" : value}</span>`;
      provenanceRows.appendChild(row);
    }
    provenanceDetails.appendChild(provenanceRows);
    this.shadowRoot.appendChild(provenanceDetails);

    this._appendProcessingSection(data);
  }

  // VL-D4 §20 — Processing Profile / Input / Output / Measurements /
  // Decisions / Warnings / Errors / Quality Before / Quality After /
  // Provenance / History, for whatever the latest processing run against
  // this recording produced. Unknown values stay UNKNOWN/NOT AVAILABLE —
  // never guessed. Nothing here can express speaker identity (VL-D4 §2
  // never touches that boundary at all).
  _appendProcessingSection(data) {
    const queueStore = this._services ? this._services.processingQueueStore : null;
    const historyStore = this._services ? this._services.processingHistoryStore : null;
    const items = queueStore ? queueStore.list().filter((i) => i.recordingId === data.id) : [];
    const item = items.length ? items[items.length - 1] : null;

    const processingDetails = document.createElement("details");
    processingDetails.innerHTML = "<summary>Processing</summary>";

    if (!item) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Not queued for processing yet.";
      processingDetails.appendChild(empty);
      this.shadowRoot.appendChild(processingDetails);
      return;
    }

    const summaryRows = document.createElement("div");
    summaryRows.className = "rows";
    const statusRow = document.createElement("div");
    statusRow.className = "avl-row avl-row--bordered";
    const statusLabel = document.createElement("span");
    statusLabel.className = "label";
    statusLabel.textContent = "Status";
    statusRow.appendChild(statusLabel);
    const statusBadge = document.createElement("avl-status-badge");
    statusBadge.setAttribute("domain", "processing_status");
    statusBadge.setAttribute("state", item.status);
    statusRow.appendChild(statusBadge);
    summaryRows.appendChild(statusRow);

    const decisionRow = document.createElement("div");
    decisionRow.className = "avl-row avl-row--bordered";
    const decisionLabel = document.createElement("span");
    decisionLabel.className = "label";
    decisionLabel.textContent = "Decision";
    decisionRow.appendChild(decisionLabel);
    if (item.decision) {
      const decisionBadge = document.createElement("avl-status-badge");
      decisionBadge.setAttribute("domain", "processing_decision");
      decisionBadge.setAttribute("state", item.decision);
      decisionRow.appendChild(decisionBadge);
    } else {
      const decisionValue = document.createElement("span");
      decisionValue.className = "value";
      decisionValue.textContent = "—";
      decisionRow.appendChild(decisionValue);
    }
    summaryRows.appendChild(decisionRow);

    for (const [label, value] of [
      ["Profile", item.profileId],
      ["Output path", item.derivedArtifact ? item.derivedArtifact.outputPath : null],
      ["Output SHA-256", item.derivedArtifact ? item.derivedArtifact.outputSha256 : null],
      ["Artifact ID", item.derivedArtifact ? item.derivedArtifact.artifactId : null],
      ["Warnings", item.warnings.length ? item.warnings.join("; ") : null],
      ["Errors", item.errors.length ? item.errors.join("; ") : null],
    ]) {
      const row = document.createElement("div");
      row.className = "avl-row avl-row--bordered";
      row.innerHTML = `<span class="label">${label}</span><span class="value">${value == null || value === "" ? "—" : value}</span>`;
      summaryRows.appendChild(row);
    }
    processingDetails.appendChild(summaryRows);

    const qualityBeforeHeading = document.createElement("h4");
    qualityBeforeHeading.textContent = "Quality before";
    processingDetails.appendChild(qualityBeforeHeading);
    const qualityBefore = document.createElement("avl-quality-profile");
    qualityBefore.assessment = item.qualityBefore;
    processingDetails.appendChild(qualityBefore);

    const qualityAfterHeading = document.createElement("h4");
    qualityAfterHeading.textContent = "Quality after";
    processingDetails.appendChild(qualityAfterHeading);
    const qualityAfter = document.createElement("avl-quality-profile");
    qualityAfter.assessment = item.qualityAfter;
    processingDetails.appendChild(qualityAfter);

    const historyHeading = document.createElement("h4");
    historyHeading.textContent = "History";
    processingDetails.appendChild(historyHeading);
    const historyPanel = document.createElement("avl-processing-history-panel");
    historyPanel.historyStore = historyStore;
    historyPanel.recordingId = data.id;
    processingDetails.appendChild(historyPanel);

    const feedbackHeading = document.createElement("h4");
    feedbackHeading.textContent = "Processing feedback";
    processingDetails.appendChild(feedbackHeading);
    const processingFeedbackForm = document.createElement("avl-processing-feedback-form");
    processingFeedbackForm.feedbackStore = this._services ? this._services.feedbackStore : null;
    const currentHistory = historyStore ? historyStore.current(data.id) : null;
    processingFeedbackForm.targetId = currentHistory ? currentHistory.recordId : null;
    processingDetails.appendChild(processingFeedbackForm);

    const claudeHeading = document.createElement("h4");
    claudeHeading.textContent = "Ask Claude";
    processingDetails.appendChild(claudeHeading);
    const claudeContext = document.createElement("avl-claude-processing-context");
    claudeContext.recording = data;
    claudeContext.item = item;
    if (this._services && this._services.executor) claudeContext.executor = this._services.executor;
    processingDetails.appendChild(claudeContext);

    this.shadowRoot.appendChild(processingDetails);
  }

  // VL-D5 §20 — Latest generation / History / Feedback / Ask Claude for
  // whichever voice profile is selected. Generated outputs are tied to a
  // voice profile id, not a recording, so this is keyed differently from
  // _appendProcessingSection above — mirrors its shape otherwise. No
  // speaker identity is ever expressed here (VL-D5 §8, §9).
  _appendPreviewSection(data) {
    const queueStore = this._services ? this._services.generationQueueStore : null;
    const historyStore = this._services ? this._services.previewHistoryStore : null;
    const items = queueStore
      ? queueStore.list().filter((i) => i.request.voice_profile_id === data.profile_id && i.artifact)
      : [];
    const item = items.length ? items[items.length - 1] : null;

    const previewDetails = document.createElement("details");
    previewDetails.open = true;
    previewDetails.innerHTML = "<summary>Preview</summary>";

    if (!item) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No generations for this voice profile yet.";
      previewDetails.appendChild(empty);
      this.shadowRoot.appendChild(previewDetails);
      return;
    }

    const summaryRows = document.createElement("div");
    summaryRows.className = "rows";
    const statusRow = document.createElement("div");
    statusRow.className = "avl-row avl-row--bordered";
    statusRow.innerHTML = '<span class="label">Status</span>';
    const statusBadge = document.createElement("avl-status-badge");
    statusBadge.setAttribute("domain", "generation_status");
    statusBadge.setAttribute("state", item.status);
    statusRow.appendChild(statusBadge);
    summaryRows.appendChild(statusRow);
    for (const [label, value] of [
      ["Model", item.request.model_id],
      ["Output ID", item.artifact.preview_id],
      ["Output SHA-256", item.artifact.sha256],
      ["Config hash", item.request.config_hash],
      ["Warnings", item.warnings.length ? item.warnings.join("; ") : null],
      ["Errors", item.errors.length ? item.errors.join("; ") : null],
    ]) {
      const row = document.createElement("div");
      row.className = "avl-row avl-row--bordered";
      row.innerHTML = `<span class="label">${label}</span><span class="value">${value == null || value === "" ? "—" : value}</span>`;
      summaryRows.appendChild(row);
    }
    previewDetails.appendChild(summaryRows);

    const historyHeading = document.createElement("h4");
    historyHeading.textContent = "History";
    previewDetails.appendChild(historyHeading);
    const historyPanel = document.createElement("avl-generation-history-panel");
    historyPanel.historyStore = historyStore;
    historyPanel.voiceProfileId = data.profile_id;
    previewDetails.appendChild(historyPanel);

    const feedbackHeading = document.createElement("h4");
    feedbackHeading.textContent = "Feedback";
    previewDetails.appendChild(feedbackHeading);
    const previewFeedbackForm = document.createElement("avl-preview-feedback-form");
    previewFeedbackForm.feedbackStore = this._services ? this._services.previewFeedbackStore : null;
    previewFeedbackForm.artifact = item.artifact;
    previewDetails.appendChild(previewFeedbackForm);

    const claudeHeading = document.createElement("h4");
    claudeHeading.textContent = "Ask Claude";
    previewDetails.appendChild(claudeHeading);
    const claudeContext = document.createElement("avl-claude-generation-context");
    claudeContext.item = item;
    claudeContext.voiceProfileId = data.profile_id;
    if (this._services && this._services.executor) claudeContext.executor = this._services.executor;
    previewDetails.appendChild(claudeContext);

    this.shadowRoot.appendChild(previewDetails);

    this._appendEvaluationSection(data, item);
  }

  // VL-D6 -- Evaluation History / Disagreement / Aggregated Results /
  // Ask Claude for whichever output this voice profile's latest
  // generation produced. Genuinely separate from _appendPreviewSection's
  // own single-outcome Feedback block above -- this reads
  // this._services.evaluationStore, the multi-dimension, multi-reviewer
  // VL-D6 log, never identity.preview.PreviewFeedback.
  _appendEvaluationSection(data, item) {
    const evaluationStore = this._services ? this._services.evaluationStore : null;
    const outputId = item.artifact.preview_id;

    const evaluationDetails = document.createElement("details");
    evaluationDetails.innerHTML = "<summary>Evaluation</summary>";

    const historyHeading = document.createElement("h4");
    historyHeading.textContent = "History";
    evaluationDetails.appendChild(historyHeading);
    const historyPanel = document.createElement("avl-evaluation-history-panel");
    historyPanel.evaluationStore = evaluationStore;
    historyPanel.outputId = outputId;
    evaluationDetails.appendChild(historyPanel);

    const evaluations = evaluationStore ? evaluationStore.evaluationsFor(outputId) : [];
    const summary = summarizeOutputEvaluations(evaluations, outputId);

    const disagreementHeading = document.createElement("h4");
    disagreementHeading.textContent = "Disagreement";
    evaluationDetails.appendChild(disagreementHeading);
    const disagreement = document.createElement("avl-disagreement-view");
    disagreement.summary = summary;
    evaluationDetails.appendChild(disagreement);

    const aggregatedHeading = document.createElement("h4");
    aggregatedHeading.textContent = "Aggregated results";
    evaluationDetails.appendChild(aggregatedHeading);
    const aggregated = document.createElement("avl-aggregated-results-panel");
    aggregated.summary = summary;
    evaluationDetails.appendChild(aggregated);

    const claudeHeading = document.createElement("h4");
    claudeHeading.textContent = "Ask Claude";
    evaluationDetails.appendChild(claudeHeading);
    const claudeContext = document.createElement("avl-claude-evaluation-context");
    claudeContext.outputId = outputId;
    claudeContext.voiceProfileId = data.profile_id;
    claudeContext.summary = summary;
    if (this._services && this._services.executor) claudeContext.executor = this._services.executor;
    evaluationDetails.appendChild(claudeContext);

    this.shadowRoot.appendChild(evaluationDetails);
  }
}

defineComponent("avl-inspector-router", AvlInspectorRouter);
