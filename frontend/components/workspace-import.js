// <avl-workspace-import> — VL-D2 §9, §16, §17, §18, §19, §20. The real
// bulk-import interaction model. Set `.services = { importQueue,
// activityStore, router }`. `importQueue` is a
// state/import-engine.js `ImportQueue` instance owned by the app entry
// (frontend/app/main.js) so it survives navigating away and back — this
// component only renders it, it does not own its lifecycle.
//
// Real, client-side work happens here: SHA-256 hashing, magic-byte
// detection, duplicate detection, the full queued/scanning/hashing/
// validating/accepted/warning/invalid/blocked/duplicate/failed/cancelled
// state machine. What does NOT happen here: writing an accepted file
// into `data/source/`, or creating a persisted Batch record — no
// execution transport exists to do that (see
// state/command-executor.js). "Copy import plan" bridges the two
// honestly: it hands the operator the exact JSON a human can pass to
// `python -m aarya_voice_lab.cli.main import` to actually commit it.
import { AvlElement, defineComponent } from "./base-element.js";
import { ImportItemStatus, exportImportPlan } from "../state/import-engine.js";
import { ActivitySource, ActivitySeverity, createActivityEvent } from "../state/activity-model.js";
import { buildClaudeContext } from "../state/claude-context.js";
import "./workspace-state.js";
import "./panel.js";
import "./notice-banner.js";
import "./import-drop-zone.js";
import "./import-queue.js";
import "./status-badge.js";
import "./metric-placeholder.js";
import "./button.js";
import "./claude-fix-flow.js";

const TERMINAL = new Set([
  ImportItemStatus.ACCEPTED,
  ImportItemStatus.WARNING,
  ImportItemStatus.INVALID,
  ImportItemStatus.BLOCKED,
  ImportItemStatus.DUPLICATE,
  ImportItemStatus.FAILED,
  ImportItemStatus.CANCELLED,
]);

const ACCEPTED_LIKE = new Set([ImportItemStatus.ACCEPTED, ImportItemStatus.WARNING]);

export class AvlWorkspaceImport extends AvlElement {
  set services(value) {
    this._services = value || {};
    this._wireQueue();
  }

  connectedCallback() {
    this._services = this._services || {};
    this._seenTerminal = this._seenTerminal || new Set();
    this._wireQueue();
    this._load();
  }

  _wireQueue() {
    const queue = this._services.importQueue;
    if (!queue || queue === this._wiredQueue) return;
    this._wiredQueue = queue;
    queue.addEventListener("change", ({ detail }) => {
      this._onItemChange(detail.item);
      if (this.isConnected) this._render();
    });
  }

  _onItemChange(item) {
    if (!TERMINAL.has(item.status) || this._seenTerminal.has(item.itemId)) return;
    this._seenTerminal.add(item.itemId);
    const activityStore = this._services.activityStore;
    if (!activityStore) return;
    const severityFor = {
      [ImportItemStatus.ACCEPTED]: ActivitySeverity.SUCCESS,
      [ImportItemStatus.WARNING]: ActivitySeverity.WARNING,
      [ImportItemStatus.DUPLICATE]: ActivitySeverity.INFO,
      [ImportItemStatus.INVALID]: ActivitySeverity.DANGER,
      [ImportItemStatus.BLOCKED]: ActivitySeverity.DANGER,
      [ImportItemStatus.FAILED]: ActivitySeverity.DANGER,
      [ImportItemStatus.CANCELLED]: ActivitySeverity.INFO,
    };
    const source = item.status === ImportItemStatus.DUPLICATE ? ActivitySource.IMPORT : ActivitySource.IMPORT;
    activityStore.append(
      createActivityEvent({
        id: `import-${item.itemId}-${item.status}`,
        source,
        severity: severityFor[item.status] || ActivitySeverity.INFO,
        status: item.status,
        summary: `${item.originalFilename}: ${item.status}${item.duplicateOf ? ` (duplicate of ${item.duplicateOf})` : ""}`,
      }),
    );
  }

  async _load() {
    this._state = "loading";
    this._render();
    try {
      const response = await fetch(new URL("../contracts/live/dataset_gate_status.json", import.meta.url));
      this._gate = response.ok ? await response.json() : null;
    } catch {
      this._gate = null;
    }
    this._state = "ready";
    this._render();
  }

  async _copyPlan() {
    const queue = this._services.importQueue;
    if (!queue) return;
    const plan = JSON.stringify(exportImportPlan(queue), null, 2);
    try {
      await navigator.clipboard.writeText(plan);
      this._copyStatus = "Copied.";
    } catch {
      this._copyStatus = "Could not access the clipboard — plan is in the panel below.";
    }
    this._planText = plan;
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      .gate-row { display: flex; justify-content: space-between; padding: var(--avl-space-1) 0; font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .progress { display: flex; gap: var(--avl-space-4); flex-wrap: wrap; margin: var(--avl-space-3) 0; }
      .actions { display: flex; gap: var(--avl-space-2); margin: var(--avl-space-3) 0; flex-wrap: wrap; }
      pre { font: var(--avl-type-code-weight) var(--avl-type-code-size) / var(--avl-type-code-line-height) var(--avl-type-code-family); background: var(--avl-color-surface-sunken); padding: var(--avl-space-2); border-radius: var(--avl-radius-sm); overflow-x: auto; max-height: 12rem; }
      .section { margin-top: var(--avl-space-4); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Import";
    wrapper.appendChild(heading);

    const notice = document.createElement("avl-notice-banner");
    notice.setAttribute("tone", "info");
    notice.textContent =
      "Real client-side hashing and magic-byte detection (Web Crypto, no dependency). " +
      "Nothing is written into source/ from the browser — see 'Copy import plan' below.";
    wrapper.appendChild(notice);

    const gatePanel = document.createElement("avl-panel");
    gatePanel.setAttribute("title", "Dataset access gate");
    if (this._gate) {
      const summary = document.createElement("div");
      summary.className = "gate-row";
      const label = document.createElement("span");
      label.textContent = `${this._gate.unsatisfied_count} of ${this._gate.conditions.length} conditions unsatisfied`;
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "core");
      badge.setAttribute("state", this._gate.access_allowed ? "ready" : "attention");
      summary.append(label, badge);
      gatePanel.appendChild(summary);
      const note = document.createElement("p");
      note.className = "avl-type-caption";
      note.textContent = this._gate.note;
      gatePanel.appendChild(note);
    } else {
      const notEvaluated = document.createElement("p");
      notEvaluated.className = "avl-type-body-small";
      notEvaluated.textContent =
        "Gate not evaluated in this session. Run `python scripts/export_dataset_gate_status.py` " +
        "(read-only — inspects Git/config state only, never audio) to check.";
      gatePanel.appendChild(notEvaluated);
    }
    wrapper.appendChild(gatePanel);

    const dropZone = document.createElement("avl-import-drop-zone");
    dropZone.addEventListener("avl-files-selected", (event) => {
      const queue = this._services.importQueue;
      if (!queue) return;
      for (const file of event.detail.files) queue.enqueue(file);
      this._render();
    });
    wrapper.appendChild(dropZone);

    const queue = this._services.importQueue;
    if (queue) {
      const counts = queue.counts();
      const total = queue.items.size;
      const processed = Object.entries(counts)
        .filter(([status]) => status !== ImportItemStatus.QUEUED)
        .reduce((sum, [, count]) => sum + count, 0);

      const progress = document.createElement("div");
      progress.className = "progress";
      for (const [label, value] of [
        ["Importing", `${processed} / ${total}`],
        ["Accepted", counts.accepted],
        ["Warnings", counts.warning],
        ["Invalid", counts.invalid],
        ["Blocked", counts.blocked],
        ["Duplicates", counts.duplicate],
        ["Failed", counts.failed],
      ]) {
        const metric = document.createElement("avl-metric-placeholder");
        metric.setAttribute("label", label);
        metric.setAttribute("value", String(value));
        progress.appendChild(metric);
      }
      wrapper.appendChild(progress);

      const actions = document.createElement("div");
      actions.className = "actions";
      const copyPlan = document.createElement("avl-button");
      copyPlan.setAttribute("variant", "secondary");
      copyPlan.textContent = "Copy import plan";
      copyPlan.addEventListener("click", () => this._copyPlan());
      actions.appendChild(copyPlan);

      const hasAccepted = queue.list().some((item) => ACCEPTED_LIKE.has(item.status));
      if (hasAccepted) {
        const openPipeline = document.createElement("avl-button");
        openPipeline.setAttribute("variant", "primary");
        openPipeline.textContent = "Open Pipeline";
        openPipeline.addEventListener("click", () => this._services.router?.navigate("pipeline"));
        actions.appendChild(openPipeline);
      }
      wrapper.appendChild(actions);

      if (this._planText) {
        const planPanel = document.createElement("avl-panel");
        planPanel.setAttribute("title", `Import plan JSON${this._copyStatus ? ` — ${this._copyStatus}` : ""}`);
        planPanel.setAttribute("collapsible", "");
        const pre = document.createElement("pre");
        pre.textContent = this._planText;
        planPanel.appendChild(pre);
        wrapper.appendChild(planPanel);
      }

      const importQueueTable = document.createElement("avl-import-queue");
      importQueueTable.queue = queue;
      importQueueTable.addEventListener("avl-import-ask-claude", (event) => {
        this._claudeFixTarget = event.detail;
        this._render();
      });
      wrapper.appendChild(importQueueTable);

      if (this._claudeFixTarget) {
        const { batchId, itemId, item } = this._claudeFixTarget;
        // Bounded to exactly batch/item/stage/error/safe metadata (VL-D2
        // §19) via the same buildClaudeContext() the Claude workspace
        // uses — every value here is either the item's own display name
        // (browser File.name has no path component) or a string this
        // component wrote itself, and still passes through the shared
        // redaction pass rather than being assumed safe.
        const context = buildClaudeContext({
          destination: "import",
          selection: {
            kind: "import-item",
            id: itemId,
            data: {
              batch_id: batchId,
              item_id: itemId,
              stage: "import",
              filename: item.originalFilename,
              detected_container: item.detectedContainer,
              status: item.status,
              errors: item.errors,
              warnings: item.warnings,
            },
          },
          errorSummary: `Import failed: ${item.originalFilename}`,
        });

        const fixSection = document.createElement("div");
        fixSection.className = "section";
        const fixPanel = document.createElement("avl-panel");
        fixPanel.setAttribute("title", `Fix workflow — ${item.originalFilename}`);
        const fixFlow = document.createElement("avl-claude-fix-flow");
        fixFlow.executor = this._services.executor;
        fixFlow.error = {
          summary: context.error_summary,
          detail: JSON.stringify(context, null, 2),
        };
        fixPanel.appendChild(fixFlow);
        fixSection.appendChild(fixPanel);
        wrapper.appendChild(fixSection);
      }
    }

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-import", AvlWorkspaceImport);
