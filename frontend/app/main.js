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

const DESTINATION_META = {
  "command-center": { icon: "◆", label: "Command Center", tag: "avl-workspace-command-center" },
  import: { icon: "⇩", label: "Import", tag: "avl-workspace-import" },
  batches: { icon: "▤", label: "Batches", tag: "avl-workspace-batches" },
  recordings: { icon: "♫", label: "Recordings", tag: "avl-workspace-recordings" },
  review: { icon: "◎", label: "Dataset Review", tag: "avl-workspace-dataset-review" },
  processing: { icon: "▶", label: "Processing", tag: "avl-workspace-processing" },
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
