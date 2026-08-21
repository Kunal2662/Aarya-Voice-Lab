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
import { ImportQueue } from "../state/import-engine.js";
import { CandidateReviewStore, FeedbackStore } from "../state/review-model.js";
import { createActivityEvent, ActivitySource, ActivitySeverity } from "../state/activity-model.js";
import { ProcessingQueueStore, ProcessingProfileStore, ProcessingHistoryStore, ProcessingStatus } from "../state/processing-model.js";
import {
  GenerationQueueStore,
  VoiceProfileStore,
  GenerationModelStore,
  PreviewHistoryStore,
  PreviewFeedbackStore,
  GenerationStatus,
} from "../state/generation-model.js";
import { syntheticGenerationModels } from "../state/synthetic-fixtures.js";
import { EvaluationStore, ABEvaluationStore, EvaluationCompletionState, ABDecision, summarizeOutputEvaluations } from "../state/evaluation-model.js";
import { CalibrationProfileStore } from "../state/calibration-engine-model.js";

const DESTINATION_META = {
  "command-center": { icon: "◆", label: "Command Center", tag: "avl-workspace-command-center" },
  import: { icon: "⇩", label: "Import", tag: "avl-workspace-import" },
  batches: { icon: "▤", label: "Batches", tag: "avl-workspace-batches" },
  recordings: { icon: "♫", label: "Recordings", tag: "avl-workspace-recordings" },
  review: { icon: "◎", label: "Dataset Review", tag: "avl-workspace-dataset-review" },
  processing: { icon: "▶", label: "Processing", tag: "avl-workspace-processing" },
  preview: { icon: "♬", label: "Preview", tag: "avl-workspace-preview" },
  feedback: { icon: "★", label: "Feedback", tag: "avl-workspace-feedback" },
  pipeline: { icon: "≋", label: "Pipeline", tag: "avl-workspace-pipeline" },
  voices: { icon: "♪", label: "Voices", tag: "avl-workspace-voices" },
  models: { icon: "▣", label: "Models", tag: "avl-workspace-models" },
  calibration: { icon: "✓", label: "Calibration", tag: "avl-workspace-calibration" },
  claude: { icon: "⌘", label: "Claude", tag: "avl-workspace-claude" },
  activity: { icon: "☰", label: "Activity", tag: "avl-workspace-activity" },
  settings: { icon: "⚙", label: "Settings", tag: "avl-workspace-settings" },
};

async function loadJson(relativePath) {
  const response = await fetch(new URL(relativePath, import.meta.url));
  return response.json();
}

function buildSidebar(router) {
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
    if (!profile) return;
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
  calibrationStore.addEventListener("change", (event) => {
    const record = event.detail.record;
    activityStore.append(
      createActivityEvent({
        id: `calibration-activity-${record.profile_id}`,
        severity: record.run_state === "FAILED" ? ActivitySeverity.DANGER : ActivitySeverity.INFO,
        source: ActivitySource.CALIBRATION,
        status: record.is_rollback ? "calibration_rolled_back" : "calibration_run_completed",
        summary: record.is_rollback
          ? `Calibration rolled back to ${record.profile_id} (supersedes ${record.supersedes})`
          : `Calibration run completed: run_state=${record.run_state}, calibration_state=${record.calibration_state}`,
      }),
    );
  });

  const shell = document.createElement("avl-app-shell");
  shell.id = "shell";

  const sidebar = buildSidebar(router);
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
