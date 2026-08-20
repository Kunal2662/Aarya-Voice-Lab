// <avl-processing-queue> — VL-D4 §5, §24. Set `.queue` to a
// state/processing-model.js ProcessingQueueStore. Renders every item's
// live status/progress/current operation/warnings/errors, with per-row
// Cancel/Retry and a bulk "Retry all failed" — the same shape VL-D2's
// avl-import-queue already established for a session-only, per-item
// queue table.
import { AvlElement, defineComponent } from "./base-element.js";
import { ProcessingStatus, isTerminalProcessingStatus } from "../state/processing-model.js";
import "./status-badge.js";
import "./button.js";

const RETRYABLE = new Set([ProcessingStatus.FAILED, ProcessingStatus.BLOCKED, ProcessingStatus.WARNING]);

export class AvlProcessingQueue extends AvlElement {
  set queue(value) {
    if (this._queue) this._queue.removeEventListener("change", this._onChange);
    this._queue = value;
    if (value) {
      this._onChange = () => this._render();
      value.addEventListener("change", this._onChange);
    }
    if (this.isConnected) this._render();
  }

  set profileStore(value) {
    this._profileStore = value;
  }

  connectedCallback() {
    this._render();
  }

  disconnectedCallback() {
    if (this._queue) this._queue.removeEventListener("change", this._onChange);
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .toolbar { display: flex; gap: var(--avl-space-2); margin-bottom: var(--avl-space-2); }
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      th { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; }
      .progress { width: 6rem; height: 0.4rem; background: var(--avl-color-surface-sunken); border-radius: var(--avl-radius-pill); overflow: hidden; }
      .progress-fill { height: 100%; background: var(--avl-color-brand-accent); }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._queue) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No processing queue attached.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const items = this._queue.list();

    const toolbar = document.createElement("div");
    toolbar.className = "toolbar";
    const retryAllFailed = document.createElement("avl-button");
    retryAllFailed.setAttribute("variant", "secondary");
    retryAllFailed.textContent = "Retry all failed";
    retryAllFailed.addEventListener("click", () => {
      for (const item of items) {
        if (RETRYABLE.has(item.status)) this._queue.retry(item.itemId);
      }
    });
    toolbar.appendChild(retryAllFailed);
    this.shadowRoot.appendChild(toolbar);

    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Nothing queued for processing.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML =
      "<tr><th>Recording</th><th>Profile</th><th>Status</th><th>Progress</th><th>Operation</th><th>Warnings</th><th>Actions</th></tr>";
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const item of items) {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${item.recordingId}</td>
        <td>${item.profileId}</td>
      `;

      const statusCell = document.createElement("td");
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "processing_status");
      badge.setAttribute("state", item.status);
      statusCell.appendChild(badge);
      row.appendChild(statusCell);

      const progressCell = document.createElement("td");
      const progress = document.createElement("div");
      progress.className = "progress";
      const fill = document.createElement("div");
      fill.className = "progress-fill";
      fill.style.width = `${Math.round((item.progress || 0) * 100)}%`;
      progress.appendChild(fill);
      progressCell.appendChild(progress);
      row.appendChild(progressCell);

      const opCell = document.createElement("td");
      opCell.textContent = item.currentOperation || "—";
      row.appendChild(opCell);

      const warnCell = document.createElement("td");
      const problems = [...item.errors, ...item.warnings];
      warnCell.textContent = problems.length ? `${problems.length} note(s)` : "—";
      warnCell.title = problems.join("\n");
      row.appendChild(warnCell);

      const actionsCell = document.createElement("td");
      if (item.status === ProcessingStatus.QUEUED) {
        const startButton = document.createElement("avl-button");
        startButton.setAttribute("variant", "primary");
        startButton.textContent = "Start";
        startButton.addEventListener("click", () => this._queue.processOne(item.itemId));
        actionsCell.appendChild(startButton);

        const cancelButton = document.createElement("avl-button");
        cancelButton.setAttribute("variant", "secondary");
        cancelButton.textContent = "Cancel";
        cancelButton.addEventListener("click", () => this._queue.cancel(item.itemId));
        actionsCell.appendChild(cancelButton);
      } else if (RETRYABLE.has(item.status)) {
        const retryButton = document.createElement("avl-button");
        retryButton.setAttribute("variant", "secondary");
        retryButton.textContent = "Retry";
        retryButton.addEventListener("click", () => this._queue.retry(item.itemId));
        actionsCell.appendChild(retryButton);

        if (this._profileStore) {
          const other = this._profileStore.allLatest().find((p) => p.profileId !== item.profileId);
          if (other) {
            const retryOtherButton = document.createElement("avl-button");
            retryOtherButton.setAttribute("variant", "secondary");
            retryOtherButton.textContent = `Retry with ${other.name}`;
            retryOtherButton.addEventListener("click", () => this._queue.retry(item.itemId, { profile: other }));
            actionsCell.appendChild(retryOtherButton);
          }
        }
      } else if (!isTerminalProcessingStatus(item.status)) {
        const note = document.createElement("span");
        note.className = "note";
        note.textContent = "in progress…";
        actionsCell.appendChild(note);
      }
      row.appendChild(actionsCell);

      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    this.shadowRoot.appendChild(table);
  }
}

defineComponent("avl-processing-queue", AvlProcessingQueue);
