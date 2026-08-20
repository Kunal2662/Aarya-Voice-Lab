// <avl-import-queue> — the real, client-side import queue table (VL-D2
// §5, §16, §17). Set `.queue` to a state/import-engine.js `ImportQueue`
// instance. Renders every item's live status, supports per-row and bulk
// retry/cancel/remove, and shows overall progress. This component reads
// the queue; it does not create one — the host (workspace-import.js)
// owns the ImportQueue so it can persist across navigation.
import { AvlElement, defineComponent } from "./base-element.js";
import { ImportItemStatus } from "../state/import-engine.js";
import "./status-badge.js";
import "./button.js";

const JOB_STATUS_DOMAIN = "pipeline_stage";
// Map the import engine's closed status set onto the shared
// pipeline_stage badge domain (VL-D1 already reuses this domain for job
// status; import status is the same kind of execution-lifecycle axis).
const STATUS_TO_BADGE_STATE = {
  [ImportItemStatus.QUEUED]: "queued",
  [ImportItemStatus.SCANNING]: "running",
  [ImportItemStatus.HASHING]: "running",
  [ImportItemStatus.VALIDATING]: "running",
  [ImportItemStatus.ACCEPTED]: "success",
  [ImportItemStatus.WARNING]: "warning",
  [ImportItemStatus.INVALID]: "failed",
  [ImportItemStatus.BLOCKED]: "blocked",
  [ImportItemStatus.DUPLICATE]: "paused",
  [ImportItemStatus.FAILED]: "failed",
  [ImportItemStatus.CANCELLED]: "cancelled",
};

const RETRYABLE = new Set([ImportItemStatus.FAILED, ImportItemStatus.INVALID, ImportItemStatus.BLOCKED]);

export class AvlImportQueue extends AvlElement {
  get queue() {
    return this._queue;
  }

  set queue(value) {
    if (this._queue) this._queue.removeEventListener("change", this._onChange);
    this._queue = value;
    this._selected = new Set();
    if (value) {
      this._onChange = () => this._render();
      value.addEventListener("change", this._onChange);
    }
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._selected = this._selected || new Set();
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .toolbar { display: flex; gap: var(--avl-space-2); margin-bottom: var(--avl-space-2); flex-wrap: wrap; }
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      th { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); }
      .filename { font: var(--avl-type-code-weight) var(--avl-type-code-size) / 1 var(--avl-type-code-family); }
      .msg { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .row-actions { display: flex; gap: var(--avl-space-1); }
    `;
    this.shadowRoot.appendChild(style);

    const queue = this._queue;
    if (!queue || !queue.items.size) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Queue is empty.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const items = queue.list();

    const toolbar = document.createElement("div");
    toolbar.className = "toolbar";
    const selectAll = document.createElement("avl-button");
    selectAll.setAttribute("variant", "secondary");
    selectAll.textContent = this._selected.size === items.length ? "Deselect all" : "Select all";
    selectAll.addEventListener("click", () => {
      this._selected = this._selected.size === items.length ? new Set() : new Set(items.map((i) => i.itemId));
      this._render();
    });

    const retrySelected = document.createElement("avl-button");
    retrySelected.setAttribute("variant", "secondary");
    retrySelected.textContent = "Retry selected";
    retrySelected.addEventListener("click", async () => {
      for (const itemId of this._selected) await queue.retry(itemId);
    });

    const retryFailed = document.createElement("avl-button");
    retryFailed.setAttribute("variant", "secondary");
    retryFailed.textContent = "Retry all failed";
    retryFailed.addEventListener("click", async () => {
      for (const item of items) if (RETRYABLE.has(item.status)) await queue.retry(item.itemId);
    });

    const start = document.createElement("avl-button");
    start.setAttribute("variant", "primary");
    start.textContent = "Start processing";
    start.addEventListener("click", () => queue.processAll());

    toolbar.append(selectAll, start, retrySelected, retryFailed);
    this.shadowRoot.appendChild(toolbar);

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML =
      "<tr><th></th><th>File</th><th>Status</th><th>Container</th><th>Details</th><th>Actions</th></tr>";
    const tbody = document.createElement("tbody");

    for (const item of items) {
      const tr = document.createElement("tr");

      const selectTd = document.createElement("td");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = this._selected.has(item.itemId);
      checkbox.setAttribute("aria-label", `Select ${item.originalFilename}`);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) this._selected.add(item.itemId);
        else this._selected.delete(item.itemId);
      });
      selectTd.appendChild(checkbox);

      const nameTd = document.createElement("td");
      nameTd.className = "filename";
      nameTd.textContent = item.originalFilename;

      const statusTd = document.createElement("td");
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", JOB_STATUS_DOMAIN);
      badge.setAttribute("state", STATUS_TO_BADGE_STATE[item.status] || "not_started");
      statusTd.appendChild(badge);

      const containerTd = document.createElement("td");
      containerTd.textContent = item.detectedContainer || "—";

      const detailTd = document.createElement("td");
      const messages = [...item.warnings, ...item.errors];
      if (item.status === ImportItemStatus.DUPLICATE) messages.push(`duplicate of ${item.duplicateOf}`);
      const msg = document.createElement("div");
      msg.className = "msg";
      msg.textContent = messages.join(" · ");
      detailTd.appendChild(msg);

      const actionsTd = document.createElement("td");
      const actions = document.createElement("div");
      actions.className = "row-actions";
      if (item.status === ImportItemStatus.QUEUED) {
        const cancel = document.createElement("avl-button");
        cancel.setAttribute("variant", "ghost");
        cancel.textContent = "Cancel";
        cancel.addEventListener("click", () => queue.cancel(item.itemId));
        actions.appendChild(cancel);
      }
      if (RETRYABLE.has(item.status)) {
        const retry = document.createElement("avl-button");
        retry.setAttribute("variant", "ghost");
        retry.textContent = "Retry";
        retry.addEventListener("click", () => queue.retry(item.itemId));
        actions.appendChild(retry);
        if (item.errors.length) {
          const ask = document.createElement("avl-button");
          ask.setAttribute("variant", "ghost");
          ask.textContent = "Ask Claude";
          ask.addEventListener("click", () => {
            this.dispatchEvent(
              new CustomEvent("avl-import-ask-claude", {
                detail: { batchId: queue.batchId, itemId: item.itemId, item },
                bubbles: true,
                composed: true,
              }),
            );
          });
          actions.appendChild(ask);
        }
      }
      actionsTd.appendChild(actions);

      tr.append(selectTd, nameTd, statusTd, containerTd, detailTd, actionsTd);
      tbody.appendChild(tr);
    }

    table.append(thead, tbody);
    this.shadowRoot.appendChild(table);
  }
}

defineComponent("avl-import-queue", AvlImportQueue);
