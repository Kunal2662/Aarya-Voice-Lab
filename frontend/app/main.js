// VL-D1 app entry. Wires the VL-D0 shell (sidebar/workspace/inspector/
// activity-bar) to the state layer (frontend/state/) and mounts one
// workspace component per destination. Owns no business logic itself —
// every real decision (job status, activity severity, contract shape)
// lives in the state modules or the backend contracts they read.

import "../components/app-shell.js";
import "../components/sidebar-nav.js";
import "../components/activity-bar.js";
import "../components/panel.js";
import "../components/theme-toggle.js";
import "../components/sidebar-view-toggle.js";
import "../components/inspector-router.js";
import "../components/workspace-command-center.js";
import "../components/workspace-import.js";
import "../components/workspace-batches.js";
import "../components/workspace-recordings.js";
import "../components/workspace-dataset-review.js";
import "../components/workspace-processing.js";
import "../components/workspace-preview.js";
import "../components/workspace-feedback.js";
import "../components/workspace-pipeline.js";
import "../components/workspace-voices.js";
import "../components/workspace-models.js";
import "../components/workspace-calibration.js";
import "../components/workspace-claude.js";
import "../components/workspace-activity.js";
import "../components/workspace-settings.js";

import { Router, DESTINATIONS } from "../state/router.js";
import { SelectionModel } from "../state/selection-model.js";
import { JobStore } from "../state/job-model.js";
import { ActivityStore } from "../state/activity-model.js";
import { NullCommandExecutor } from "../state/command-executor.js";
import { syntheticJobs, syntheticActivity } from "../state/synthetic-fixtures.js";
import { ImportQueue, exportImportPlan } from "../state/import-engine.js";
import { CandidateReviewStore, FeedbackStore, exportReviewPlan, hydrateReviewPlan } from "../state/review-model.js";
import { createActivityEvent, ActivitySource, ActivitySeverity } from "../state/activity-model.js";
import {
  ProcessingQueueStore,
  ProcessingProfileStore,
  ProcessingHistoryStore,
  ProcessingStatus,
  exportProcessingPlan,
  hydrateProcessingPlan,
} from "../state/processing-model.js";
import {
  GenerationQueueStore,
  VoiceProfileStore,
  GenerationModelStore,
  PreviewHistoryStore,
  PreviewFeedbackStore,
  GenerationStatus,
  exportGenerationPlan,
  hydrateGenerationPlan,
} from "../state/generation-model.js";
import { syntheticGenerationModels } from "../state/synthetic-fixtures.js";
import {
  EvaluationStore,
  ABEvaluationStore,
  EvaluationCompletionState,
  ABDecision,
  summarizeOutputEvaluations,
  exportEvaluationPlan,
  hydrateEvaluationPlan,
} from "../state/evaluation-model.js";
import { CalibrationProfileStore, exportCalibrationPlan } from "../state/calibration-engine-model.js";
import { SessionPersistence, SessionNamespace, isPersistenceAvailable, clearAllSessionData } from "../state/session-persistence.js";
import { SidebarViewModel } from "../state/sidebar-view-model.js";

// FE-1.3 -- `icon` now names a real inline-SVG icon from
// components/icon.js's catalogue (its keys are the same names as the
// destinations themselves) instead of a Unicode glyph.
const DESTINATION_META = {
  "command-center": { icon: "command-center", label: "Command Center", tag: "avl-workspace-command-center" },
  import: { icon: "import", label: "Import", tag: "avl-workspace-import" },
  batches: { icon: "batches", label: "Batches", tag: "avl-workspace-batches" },
  recordings: { icon: "recordings", label: "Recordings", tag: "avl-workspace-recordings" },
  review: { icon: "review", label: "Dataset Review", tag: "avl-workspace-dataset-review" },
  processing: { icon: "processing", label: "Processing", tag: "avl-workspace-processing" },
  preview: { icon: "preview", label: "Preview", tag: "avl-workspace-preview" },
  feedback: { icon: "feedback", label: "Feedback", tag: "avl-workspace-feedback" },
  pipeline: { icon: "pipeline", label: "Pipeline", tag: "avl-workspace-pipeline" },
  voices: { icon: "voices", label: "Voices", tag: "avl-workspace-voices" },
  models: { icon: "models", label: "Models", tag: "avl-workspace-models" },
  calibration: { icon: "calibration", label: "Calibration", tag: "avl-workspace-calibration" },
  claude: { icon: "claude", label: "Claude", tag: "avl-workspace-claude" },
  activity: { icon: "activity", label: "Activity", tag: "avl-workspace-activity" },
  settings: { icon: "settings", label: "Settings", tag: "avl-workspace-settings" },
};

async function loadJson(relativePath) {
  const response = await fetch(new URL(relativePath, import.meta.url));
  return response.json();
}

function buildSidebar(router, sidebarViewModel) {
  const nav = document.createElement("avl-sidebar-nav");
  nav.slot = "sidebar";
  for (const destination of DESTINATIONS) {
    const meta = DESTINATION_META[destination];
    const item = document.createElement("avl-sidebar-item");
    item.setAttribute("icon", meta.icon);
    item.setAttribute("label", meta.label);
    item.setAttribute("destination", destination);
    if (destination === router.current()) item.setAttribute("active", "");
    nav.appendChild(item);
  }
  const themeToggle = document.createElement("avl-theme-toggle");
  themeToggle.style.display = "block";
  themeToggle.style.marginTop = "1rem";
  themeToggle.style.padding = "0 0.5rem";
  nav.appendChild(themeToggle);

  // FE-4 -- icon-view/full-view toggle, sharing the sidebar's slot area
  // via the default <slot> sidebar-nav.js now renders (see that file's
  // FE-4 comment). nav.collapsed itself is driven from main(), not here,
  // since it also has to drive app-shell's sibling attribute in sync.
  const viewToggle = document.createElement("avl-sidebar-view-toggle");
  viewToggle.style.display = "block";
  viewToggle.style.marginTop = "0.5rem";
  viewToggle.style.padding = "0 0.5rem";
  viewToggle.model = sidebarViewModel;
  nav.appendChild(viewToggle);

  nav.addEventListener("avl-navigate", (event) => router.navigate(event.detail.destination));
  return nav;
}

function markActiveSidebarItem(nav, destination) {
  for (const item of nav.querySelectorAll("avl-sidebar-item")) {
    if (item.getAttribute("destination") === destination) item.setAttribute("active", "");
    else item.removeAttribute("active");
  }
  nav.refresh();
}

async function main() {
  const router = new Router();
  const selectionModel = new SelectionModel();
  const jobStore = new JobStore(syntheticJobs());
  const activityStore = new ActivityStore(syntheticActivity());
  const executor = new NullCommandExecutor();
  const pipelineStageContract = await loadJson("../contracts/generated/pipeline_stage.json").catch(() => null);
  // Owned here (not by workspace-import.js) so the queue — and its
  // in-flight hashing/validation state — survives navigating to another
  // workspace and back, matching VL-D2 §5's "queue" semantics.
  const importQueue = new ImportQueue({ batchId: "batch-001", source: "local_files" });
  // Session-only, like importQueue above — owned here so review/feedback
  // state survives navigating away from Dataset Review and back (VL-D3
  // §14's "persistent entries"). No execution transport exists to
  // persist these beyond the session (see state/command-executor.js).
  const reviewStore = new CandidateReviewStore();
  const feedbackStore = new FeedbackStore();
  // Same session-only ownership as reviewStore/feedbackStore above — VL-D4
  // §5's queue and §16/§18's history must survive navigating away from
  // Processing and back.
  const processingQueueStore = new ProcessingQueueStore();
  const processingProfileStore = new ProcessingProfileStore();
  const processingHistoryStore = new ProcessingHistoryStore();

  // Same session-only ownership as the processing stores above — VL-D5
  // §13's queue and §17-§20's history must survive navigating away from
  // Preview and back. The generation model store is seeded once here
  // with the synthetic-only backends VL-D5 ships (§26, §27) — never a
  // real TTS engine, never RTX/CUDA-specific.
  const generationModelStore = new GenerationModelStore();
  for (const model of syntheticGenerationModels()) generationModelStore.register(model);
  const voiceProfileStore = new VoiceProfileStore();
  const generationQueueStore = new GenerationQueueStore({ modelStore: generationModelStore });
  const previewHistoryStore = new PreviewHistoryStore();
  const previewFeedbackStore = new PreviewFeedbackStore();

  // Same session-only ownership as the stores above -- VL-D6's evaluation
  // log and A/B decisions must survive navigating away from Feedback and
  // back. Genuinely separate from previewFeedbackStore: this holds
  // multi-dimension, multi-reviewer Evaluation/ABEvaluation records, not
  // identity.preview.PreviewFeedback's single-outcome shape.
  const evaluationStore = new EvaluationStore();
  const abEvaluationStore = new ABEvaluationStore();

  // Same session-only ownership as the stores above -- VL-D7's
  // calibration profile history must survive navigating away from
  // Calibration and back. Rollback is append-only, same as
  // processingHistoryStore's rollback pattern.
  const calibrationStore = new CalibrationProfileStore();

  // ------------------------------------------------------------------
  // VL-D9 -- Local session persistence. Required sequence: every store
  // above has just initialized with fresh (empty/default) in-memory
  // state -> the persistence layer initializes here -> persisted state
  // loads from localStorage -> stores hydrate from it, still before any
  // UI element exists or any "change" listener is attached -> the shell
  // is built and mountWorkspace() (further below) is what actually
  // renders the now-restored state -> only after all of that does this
  // function attach the normal state-change listeners (the Activity
  // wiring below, and the auto-save listeners appended right after it),
  // so restoring a session can never itself fire an Activity event or an
  // immediate redundant save. See docs/VLD9_SESSION_PERSISTENCE.md.
  // ------------------------------------------------------------------
  const persistenceAvailable = isPersistenceAvailable();
  const importPersistence = new SessionPersistence(SessionNamespace.IMPORT);
  const reviewPersistence = new SessionPersistence(SessionNamespace.REVIEW);
  const processingPersistence = new SessionPersistence(SessionNamespace.PROCESSING);
  const generationPersistence = new SessionPersistence(SessionNamespace.GENERATION);
  const evaluationPersistence = new SessionPersistence(SessionNamespace.EVALUATION);
  const calibrationPersistence = new SessionPersistence(SessionNamespace.CALIBRATION);

  let sessionWasRestored = false;
  if (persistenceAvailable) {
    const importPlan = importPersistence.load();
    if (importPlan && importQueue.hydrate(importPlan)) sessionWasRestored = true;

    const reviewPlan = reviewPersistence.load();
    if (reviewPlan && hydrateReviewPlan(reviewStore, feedbackStore, reviewPlan)) sessionWasRestored = true;

    const processingPlan = processingPersistence.load();
    if (processingPlan && hydrateProcessingPlan(processingQueueStore, processingHistoryStore, processingPlan)) {
      sessionWasRestored = true;
    }

    const generationPlan = generationPersistence.load();
    if (
      generationPlan &&
      hydrateGenerationPlan(generationQueueStore, previewHistoryStore, previewFeedbackStore, generationPlan)
    ) {
      sessionWasRestored = true;
    }

    const evaluationPlan = evaluationPersistence.load();
    if (evaluationPlan && hydrateEvaluationPlan(evaluationStore, abEvaluationStore, evaluationPlan)) {
      sessionWasRestored = true;
    }

    const calibrationPlan = calibrationPersistence.load();
    if (calibrationPlan && calibrationStore.hydrate(calibrationPlan)) sessionWasRestored = true;
  }

  const services = {
    jobStore,
    activityStore,
    executor,
    pipelineStageContract,
    importQueue,
    reviewStore,
    feedbackStore,
    processingQueueStore,
    processingProfileStore,
    processingHistoryStore,
    generationModelStore,
    voiceProfileStore,
    generationQueueStore,
    previewHistoryStore,
    previewFeedbackStore,
    evaluationStore,
    abEvaluationStore,
    calibrationStore,
    router,
    // VL-D9 -- exposed so avl-workspace-settings can render honest
    // availability/status and offer the explicit "Clear session data"
    // control without needing to know about every individual store.
    session: {
      available: persistenceAvailable,
      wasRestored: sessionWasRestored,
      clear: () => clearSessionData(),
    },
  };

  // VL-D3 §23 — a technical review decision is itself an activity event
  // (recording reviewed / candidate accepted / rejected / marked for
  // review). Decision -> severity mirrors the "candidate_review" status
  // vocabulary's own color intent (rejected reads as attention-worthy,
  // needs-review as a warning, accepted/pending as routine).
  const REVIEW_DECISION_SEVERITY = {
    ACCEPTED: ActivitySeverity.SUCCESS,
    REJECTED: ActivitySeverity.DANGER,
    NEEDS_REVIEW: ActivitySeverity.WARNING,
    PENDING: ActivitySeverity.INFO,
  };
  reviewStore.addEventListener("change", (event) => {
    const record = event.detail.record;
    if (!record) return; // VL-D9 -- reset()/hydrate() dispatch a detail-less change; not a new decision to log.
    activityStore.append(
      createActivityEvent({
        id: `review-activity-${record.reviewId}`,
        severity: REVIEW_DECISION_SEVERITY[record.decision] || ActivitySeverity.INFO,
        source: ActivitySource.REVIEW,
        status: record.decision.toLowerCase(),
        summary: `Candidate ${record.decision.toLowerCase().replace("_", " ")}: ${record.segmentId} (${record.reasonCode})`,
      }),
    );
  });

  // VL-D4 §26 — one activity event per real processing item status
  // transition (queued/started/completed/warning/failed/cancelled).
  const PROCESSING_STATUS_SEVERITY = {
    [ProcessingStatus.SUCCESS]: ActivitySeverity.SUCCESS,
    [ProcessingStatus.WARNING]: ActivitySeverity.WARNING,
    [ProcessingStatus.FAILED]: ActivitySeverity.DANGER,
    [ProcessingStatus.BLOCKED]: ActivitySeverity.DANGER,
    [ProcessingStatus.CANCELLED]: ActivitySeverity.INFO,
  };
  let lastAnnouncedProcessingStatus = new Map();
  processingQueueStore.addEventListener("change", (event) => {
    const item = event.detail.item;
    if (!item) return; // VL-D9 -- reset() dispatches a detail-less change.
    if (lastAnnouncedProcessingStatus.get(item.itemId) === item.status) return;
    lastAnnouncedProcessingStatus.set(item.itemId, item.status);
    activityStore.append(
      createActivityEvent({
        id: `processing-activity-${item.itemId}-${item.status}`,
        severity: PROCESSING_STATUS_SEVERITY[item.status] || ActivitySeverity.INFO,
        source: ActivitySource.PROCESSING,
        status: item.status.toLowerCase(),
        summary: `Processing ${item.status.toLowerCase()}: ${item.recordingId} (${item.profileId})`,
      }),
    );
  });
  processingProfileStore.addEventListener("change", (event) => {
    const profile = event.detail.profile;
    if (!profile) return; // also covers VL-D9's reset() detail-less change.
    activityStore.append(
      createActivityEvent({
        id: `processing-profile-activity-${profile.profileId}`,
        severity: ActivitySeverity.INFO,
        source: ActivitySource.PROCESSING,
        status: profile.version === 1 ? "profile_created" : "profile_updated",
        summary: `Processing profile ${profile.version === 1 ? "created" : "updated"}: ${profile.name} v${profile.version}`,
      }),
    );
  });

  // VL-D5 §30 — one activity event per real generation item status
  // transition (queued/preparing/generating/post_processing/ready/
  // warning/failed/cancelled/blocked). Bounded metadata only: request id,
  // voice profile id, model id — never the raw preview text (§30's
  // "avoid logging raw text unnecessarily").
  const GENERATION_STATUS_SEVERITY = {
    [GenerationStatus.READY]: ActivitySeverity.SUCCESS,
    [GenerationStatus.WARNING]: ActivitySeverity.WARNING,
    [GenerationStatus.FAILED]: ActivitySeverity.DANGER,
    [GenerationStatus.BLOCKED]: ActivitySeverity.DANGER,
    [GenerationStatus.CANCELLED]: ActivitySeverity.INFO,
  };
  const lastAnnouncedGenerationStatus = new Map();
  generationQueueStore.addEventListener("change", (event) => {
    const item = event.detail.item;
    if (!item) return; // VL-D9 -- reset() dispatches a detail-less change.
    if (lastAnnouncedGenerationStatus.get(item.item_id) === item.status) return;
    lastAnnouncedGenerationStatus.set(item.item_id, item.status);
    activityStore.append(
      createActivityEvent({
        id: `generation-activity-${item.item_id}-${item.status}`,
        severity: GENERATION_STATUS_SEVERITY[item.status] || ActivitySeverity.INFO,
        source: ActivitySource.PREVIEW,
        status: item.status.toLowerCase(),
        summary: `Generation ${item.status.toLowerCase()}: ${item.request.voice_profile_id} (${item.request.model_id})`,
      }),
    );
  });

  // VL-D5 §21, §22, §30 — one activity event per feedback submission,
  // plus a distinct event for accept/reject/regenerate outcomes. Never
  // logs the comment text itself, only the outcome and category.
  const FEEDBACK_OUTCOME_SEVERITY = {
    accepted: ActivitySeverity.SUCCESS,
    rejected: ActivitySeverity.DANGER,
    regenerate: ActivitySeverity.WARNING,
    uncertain: ActivitySeverity.INFO,
  };
  const FEEDBACK_OUTCOME_STATUS = {
    accepted: "output_accepted",
    rejected: "output_rejected",
    regenerate: "regeneration_requested",
    uncertain: "feedback_submitted",
  };
  previewFeedbackStore.addEventListener("change", (event) => {
    const record = event.detail.record;
    if (!record) return; // VL-D9 -- reset() dispatches a detail-less change.
    activityStore.append(
      createActivityEvent({
        id: `preview-feedback-activity-${record.feedback_id}`,
        severity: FEEDBACK_OUTCOME_SEVERITY[record.outcome] || ActivitySeverity.INFO,
        source: ActivitySource.PREVIEW,
        status: FEEDBACK_OUTCOME_STATUS[record.outcome] || "feedback_submitted",
        summary: `Preview feedback recorded: ${record.outcome} (${record.preview_id})`,
      }),
    );
  });

  // VL-D5 §14, §30 — a real Play press on any preview player logs
  // "preview played" (never autoplay-triggered, since avl-audio-player
  // never autoplays — see components/audio-player.js). Composed, so this
  // single listener catches it from any nested shadow root under the
  // shell (preview cards, the feedback form's embedded player, A/B
  // comparison columns, the Inspector's Preview section).
  document.addEventListener("avl-playback-started", (event) => {
    activityStore.append(
      createActivityEvent({
        id: `preview-played-activity-${event.detail.recordingId}-${Date.now()}`,
        severity: ActivitySeverity.INFO,
        source: ActivitySource.PREVIEW,
        status: "preview_played",
        summary: `Preview played: ${event.detail.recordingId}`,
      }),
    );
    // VL-D6 -- the same physical Play press also means "output listened"
    // for the evaluation task, when it happened inside an
    // avl-evaluation-form (composedPath() carries every element the
    // event crossed, including shadow-boundary ancestors, so this can
    // tell an evaluation-context play apart from any other player in the
    // app without avl-voice-player/avl-audio-player needing to know
    // anything about evaluation at all).
    if (event.composedPath().some((el) => el.tagName === "AVL-EVALUATION-FORM")) {
      activityStore.append(
        createActivityEvent({
          id: `evaluation-listened-activity-${event.detail.recordingId}-${Date.now()}`,
          severity: ActivitySeverity.INFO,
          source: ActivitySource.EVALUATION,
          status: "output_listened",
          summary: `Output listened (evaluation): ${event.detail.recordingId}`,
        }),
      );
    }
  });

  // VL-D6 -- "evaluation started": a reviewer picking an output from the
  // queue is a real, meaningful state transition (not fabricated) --
  // avl-evaluation-queue's own "Evaluate" button already dispatches this
  // bubbling+composed event for the workspace to focus that output; this
  // listener just also logs it.
  document.addEventListener("avl-evaluation-select", (event) => {
    activityStore.append(
      createActivityEvent({
        id: `evaluation-started-activity-${event.detail.output.preview_id}-${Date.now()}`,
        severity: ActivitySeverity.INFO,
        source: ActivitySource.EVALUATION,
        status: "evaluation_started",
        summary: `Evaluation started: ${event.detail.output.preview_id}`,
      }),
    );
  });

  // VL-D6 -- one activity event per evaluation submission (COMPLETED/
  // CANNOT_JUDGE/ABANDONED -- IN_PROGRESS is never submitted by the UI),
  // plus a distinct, de-duplicated "disagreement detected" event the
  // first time an output's evaluations actually meet
  // pipeline.evaluation_aggregation's own disagreement threshold. Never
  // logs the comment text itself, only the outcome and dimension scores'
  // presence/absence.
  const EVALUATION_COMPLETION_SEVERITY = {
    [EvaluationCompletionState.COMPLETED]: ActivitySeverity.SUCCESS,
    [EvaluationCompletionState.CANNOT_JUDGE]: ActivitySeverity.INFO,
    [EvaluationCompletionState.ABANDONED]: ActivitySeverity.WARNING,
  };
  const EVALUATION_COMPLETION_STATUS = {
    [EvaluationCompletionState.COMPLETED]: "evaluation_completed",
    [EvaluationCompletionState.CANNOT_JUDGE]: "evaluation_cannot_judge",
    [EvaluationCompletionState.ABANDONED]: "evaluation_abandoned",
  };
  const alreadyAnnouncedDisagreement = new Set();
  evaluationStore.addEventListener("change", (event) => {
    const record = event.detail.record;
    if (!record) return; // VL-D9 -- reset() dispatches a detail-less change.
    activityStore.append(
      createActivityEvent({
        id: `evaluation-activity-${record.evaluation_id}`,
        severity: EVALUATION_COMPLETION_SEVERITY[record.completion_state] || ActivitySeverity.INFO,
        source: ActivitySource.EVALUATION,
        status: EVALUATION_COMPLETION_STATUS[record.completion_state] || "evaluation_submitted",
        summary: `Evaluation ${(EVALUATION_COMPLETION_STATUS[record.completion_state] || "submitted").replace("evaluation_", "")}: ${record.output_id} (reviewer: ${record.reviewer})`,
      }),
    );

    if (alreadyAnnouncedDisagreement.has(record.output_id)) return;
    const summary = summarizeOutputEvaluations(evaluationStore.evaluationsFor(record.output_id), record.output_id);
    if (summary.has_disagreement) {
      alreadyAnnouncedDisagreement.add(record.output_id);
      activityStore.append(
        createActivityEvent({
          id: `evaluation-disagreement-activity-${record.output_id}`,
          severity: ActivitySeverity.WARNING,
          source: ActivitySource.EVALUATION,
          status: "disagreement_detected",
          summary: `Reviewer disagreement detected: ${record.output_id} (${summary.disagreement_dimensions.join(", ")})`,
        }),
      );
    }
  });

  // VL-D6 -- one activity event per A/B decision.
  const AB_DECISION_SEVERITY = {
    [ABDecision.PREFER_A]: ActivitySeverity.SUCCESS,
    [ABDecision.PREFER_B]: ActivitySeverity.SUCCESS,
    [ABDecision.NO_PREFERENCE]: ActivitySeverity.INFO,
    [ABDecision.CANNOT_JUDGE]: ActivitySeverity.INFO,
  };
  abEvaluationStore.addEventListener("change", (event) => {
    const record = event.detail.record;
    if (!record) return; // VL-D9 -- reset() dispatches a detail-less change.
    activityStore.append(
      createActivityEvent({
        id: `ab-evaluation-activity-${record.ab_evaluation_id}`,
        severity: AB_DECISION_SEVERITY[record.decision] || ActivitySeverity.INFO,
        source: ActivitySource.EVALUATION,
        status: "ab_decision_submitted",
        summary: `A/B decision recorded: ${record.decision} (${record.output_id_a} vs ${record.output_id_b})`,
      }),
    );
  });

  // VL-D7 -- one activity event per calibration engine run/rollback.
  // run_state and calibration_state are both real fields off the record,
  // never a fabricated score -- see state/calibration-engine-model.js.
  // VL-D8 -- extended with distinct calibration_applied/
  // calibration_validated events, driven by the record's own
  // application_state (never inferred or fabricated).
  calibrationStore.addEventListener("change", (event) => {
    const record = event.detail.record;
    if (!record) return; // VL-D9 -- reset() dispatches a detail-less change.
    let status;
    let summary;
    if (record.is_rollback) {
      status = "calibration_rolled_back";
      summary = `Calibration rolled back to ${record.profile_id} (supersedes ${record.supersedes})`;
    } else if (record.application_state === "APPLIED") {
      status = "calibration_applied";
      summary = `Calibration applied: ${record.applied_parameter_name}=${record.applied_value} (from ${record.applied_from_profile_id})`;
    } else if (record.application_state === "VALIDATED") {
      status = "calibration_validated";
      summary = record.validation.not_measurable
        ? `Calibration validated: NOT_MEASURABLE (${record.profile_id})`
        : `Calibration validated: measured_delta=${record.validation.measured_delta} batch(es) (${record.profile_id})`;
    } else {
      status = "calibration_run_completed";
      summary = `Calibration run completed: run_state=${record.run_state}, calibration_state=${record.calibration_state}`;
    }
    activityStore.append(
      createActivityEvent({
        id: `calibration-activity-${record.profile_id}`,
        severity: record.run_state === "FAILED" ? ActivitySeverity.DANGER : ActivitySeverity.INFO,
        source: ActivitySource.CALIBRATION,
        status,
        summary,
      }),
    );
  });

  // VL-D9 -- automatic save: wired to each domain's own store(s), added
  // only after every listener above (hydration already happened before
  // any listener in this function was attached, so this cannot loop back
  // into hydrate()). Only wired when persistence is actually available;
  // if it isn't, the app still works exactly as every prior phase did,
  // purely in-memory. A save failure (quota exceeded mid-session) is
  // silently absorbed by SessionPersistence.save()'s own honest `false`
  // return -- it never throws, so it can never break the state change
  // that triggered it.
  if (persistenceAvailable) {
    const saveImport = () => importPersistence.save(exportImportPlan(importQueue));
    const saveReview = () => reviewPersistence.save(exportReviewPlan(reviewStore, feedbackStore));
    const saveProcessing = () =>
      processingPersistence.save(exportProcessingPlan(processingQueueStore, processingHistoryStore));
    const saveGeneration = () =>
      generationPersistence.save(exportGenerationPlan(generationQueueStore, previewHistoryStore, previewFeedbackStore));
    const saveEvaluation = () => evaluationPersistence.save(exportEvaluationPlan(evaluationStore, abEvaluationStore));
    const saveCalibration = () => calibrationPersistence.save(exportCalibrationPlan(calibrationStore));

    importQueue.addEventListener("change", saveImport);
    reviewStore.addEventListener("change", saveReview);
    feedbackStore.addEventListener("change", saveReview);
    processingQueueStore.addEventListener("change", saveProcessing);
    processingHistoryStore.addEventListener("change", saveProcessing);
    generationQueueStore.addEventListener("change", saveGeneration);
    previewHistoryStore.addEventListener("change", saveGeneration);
    previewFeedbackStore.addEventListener("change", saveGeneration);
    evaluationStore.addEventListener("change", saveEvaluation);
    abEvaluationStore.addEventListener("change", saveEvaluation);
    calibrationStore.addEventListener("change", saveCalibration);
  }

  /** VL-D9 -- backs services.session.clear() / the "Clear session data"
   * control in avl-workspace-settings. Clears every namespace this app
   * owns (and nothing else -- see clearAllSessionData()), resets each
   * in-memory store in place (so mounted UI reflects the clear
   * immediately via each store's own "change" event), and produces
   * exactly one Activity event. Never called automatically. */
  function clearSessionData() {
    clearAllSessionData();
    importQueue.reset();
    reviewStore.reset();
    feedbackStore.reset();
    processingQueueStore.reset();
    processingHistoryStore.reset();
    generationQueueStore.reset();
    previewHistoryStore.reset();
    previewFeedbackStore.reset();
    evaluationStore.reset();
    abEvaluationStore.reset();
    calibrationStore.reset();
    activityStore.append(
      createActivityEvent({
        id: `session-cleared-activity-${Date.now()}`,
        severity: ActivitySeverity.INFO,
        source: ActivitySource.SYSTEM,
        status: "session_data_cleared",
        summary: "Session data cleared: all locally persisted state removed from this browser.",
      }),
    );
  }

  // VL-D9 -- one honest startup Activity event: "Session restored" only
  // when hydrate() actually restored something (never fabricated), or
  // "Persistence unavailable" when localStorage itself could not be used
  // this session (private browsing, storage disabled, etc.) -- never
  // both, and never a "cloud sync" word anywhere in either summary.
  if (!persistenceAvailable) {
    activityStore.append(
      createActivityEvent({
        id: `session-persistence-unavailable-activity-${Date.now()}`,
        severity: ActivitySeverity.WARNING,
        source: ActivitySource.SYSTEM,
        status: "persistence_unavailable",
        summary: "Persistence unavailable: this browser session's state will not be saved locally.",
      }),
    );
  } else if (sessionWasRestored) {
    activityStore.append(
      createActivityEvent({
        id: `session-restored-activity-${Date.now()}`,
        severity: ActivitySeverity.INFO,
        source: ActivitySource.SYSTEM,
        status: "session_restored",
        summary: "Session restored: prior local session state was loaded from this browser.",
      }),
    );
  }

  const shell = document.createElement("avl-app-shell");
  shell.id = "shell";

  // FE-4 -- one shared model drives both app-shell's grid-column width
  // and sidebar-nav's label visibility, kept in sync here rather than
  // via any direct reference between those two sibling components (see
  // state/sidebar-view-model.js).
  const sidebarViewModel = new SidebarViewModel();
  const sidebar = buildSidebar(router, sidebarViewModel);
  const applySidebarView = () => {
    const collapsed = sidebarViewModel.get() === "icon";
    shell.toggleAttribute("sidebar-collapsed", collapsed);
    sidebar.toggleAttribute("collapsed", collapsed);
  };
  sidebarViewModel.addEventListener("change", applySidebarView);
  applySidebarView();
  shell.appendChild(sidebar);

  const workspaceMount = document.createElement("div");
  workspaceMount.slot = "workspace";
  shell.appendChild(workspaceMount);

  const inspector = document.createElement("avl-panel");
  inspector.slot = "inspector";
  inspector.setAttribute("title", "Inspector");
  inspector.setAttribute("collapsible", "");
  const inspectorRouter = document.createElement("avl-inspector-router");
  inspectorRouter.services = services;
  inspector.appendChild(inspectorRouter);
  shell.appendChild(inspector);

  const activityBar = document.createElement("avl-activity-bar");
  activityBar.slot = "activity-bar";
  activityBar.setAttribute("domain", "core");
  shell.appendChild(activityBar);

  document.body.appendChild(shell);

  selectionModel.addEventListener("change", () => {
    inspectorRouter.selection = selectionModel.get();
  });

  function updateActivityBar() {
    const running = jobStore.current().length;
    const failed = jobStore.failed().length;
    activityBar.setAttribute("state", failed ? "attention" : running ? "busy" : "ready");
    activityBar.setAttribute(
      "message",
      failed
        ? `${failed} job(s) failed — see Activity`
        : running
          ? `${running} job(s) running`
          : "No active work.",
    );
  }

  function mountWorkspace(destination) {
    const meta = DESTINATION_META[destination] || DESTINATION_META["command-center"];
    workspaceMount.innerHTML = "";
    const element = document.createElement(meta.tag);
    element.services = services;
    element.selectionModel = selectionModel;
    workspaceMount.appendChild(element);
    markActiveSidebarItem(sidebar, destination);
    updateActivityBar();
  }

  jobStore.addEventListener("change", updateActivityBar);

  router.addEventListener("change", (event) => mountWorkspace(event.detail.destination));
  mountWorkspace(router.current());
}

main();
