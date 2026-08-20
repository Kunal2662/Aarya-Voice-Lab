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

const DESTINATION_META = {
  "command-center": { icon: "◆", label: "Command Center", tag: "avl-workspace-command-center" },
  import: { icon: "⇩", label: "Import", tag: "avl-workspace-import" },
  batches: { icon: "▤", label: "Batches", tag: "avl-workspace-batches" },
  recordings: { icon: "♫", label: "Recordings", tag: "avl-workspace-recordings" },
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

  const services = { jobStore, activityStore, executor, pipelineStageContract, importQueue, router };

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
