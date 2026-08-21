// <avl-generation-queue> — VL-D5 §13. Set `.queue` to a
// state/generation-model.js GenerationQueueStore. Renders every request's
// live status/progress/current operation/warnings/errors, with per-row
// Start/Cancel/Retry/Open result — the same table shape VL-D4's
// avl-processing-queue already established for a session-only queue.
// One item's failure never stops the rest of the queue (the store's own
// processOne() already guarantees this; this component just renders it).
import { AvlElement, defineComponent } from "./base-element.js";
import { GenerationStatus, isTerminalGenerationStatus } from "../state/generation-model.js";
import "./status-badge.js";
import "./button.js";

const RETRYABLE = new Set([GenerationStatus.FAILED, GenerationStatus.BLOCKED, GenerationStatus.WARNING]);

export class AvlGenerationQueue extends AvlElement {
  set queue(value) {
    if (this._queue) this._queue.removeEventListener("change", this._onChange);
    this._queue = value;
    if (value) {
      this._onChange = () => this._render();
      value.addEventListener("change", this._onChange);
    }
    if (this.isConnected) this._render();
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
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      th { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; }
      .text-preview { max-width: 16rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .progress { width: var(--avl-space-24); height: 0.4rem; background: var(--avl-color-surface-sunken); border-radius: var(--avl-radius-pill); overflow: hidden; }
      .progress-fill { height: 100%; background: var(--avl-color-brand-accent); }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._queue) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No generation queue attached.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const items = this._queue.list();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Nothing queued for generation yet.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML =
      "<tr><th>Text</th><th>Voice profile</th><th>Model</th><th>Status</th><th>Progress</th><th>Operation</th><th>Notes</th><th>Actions</th></tr>";
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const item of items) {
      const row = document.createElement("tr");

      const textCell = document.createElement("td");
      textCell.className = "text-preview";
      textCell.textContent = item.request.text;
      textCell.title = item.request.text;
      row.appendChild(textCell);

      const profileCell = document.createElement("td");
      profileCell.textContent = item.request.voice_profile_id;
      row.appendChild(profileCell);

      const modelCell = document.createElement("td");
      modelCell.textContent = item.request.model_id;
      row.appendChild(modelCell);

      const statusCell = document.createElement("td");
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "generation_status");
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
      opCell.textContent = item.current_operation || "—";
      row.appendChild(opCell);

      const notesCell = document.createElement("td");
      const problems = [...item.errors, ...item.warnings];
      notesCell.textContent = problems.length ? `${problems.length} note(s)` : "—";
      notesCell.title = problems.join("\n");
      row.appendChild(notesCell);

      const actionsCell = document.createElement("td");
      if (item.status === GenerationStatus.QUEUED) {
        const startButton = document.createElement("avl-button");
        startButton.setAttribute("variant", "primary");
        startButton.textContent = "Start";
        startButton.addEventListener("click", () => this._queue.processOne(item.item_id));
        actionsCell.appendChild(startButton);

        const cancelButton = document.createElement("avl-button");
        cancelButton.setAttribute("variant", "secondary");
        cancelButton.textContent = "Cancel";
        cancelButton.addEventListener("click", () => this._queue.cancel(item.item_id));
        actionsCell.appendChild(cancelButton);
      } else if (RETRYABLE.has(item.status)) {
        const retryButton = document.createElement("avl-button");
        retryButton.setAttribute("variant", "secondary");
        retryButton.textContent = "Retry";
        retryButton.addEventListener("click", () => this._queue.retry(item.item_id));
        actionsCell.appendChild(retryButton);
      } else if (!isTerminalGenerationStatus(item.status)) {
        const note = document.createElement("span");
        note.className = "note";
        note.textContent = "in progress…";
        actionsCell.appendChild(note);
      }

      if (item.artifact) {
        const openButton = document.createElement("avl-button");
        openButton.setAttribute("variant", "secondary");
        openButton.textContent = "Open result";
        openButton.addEventListener("click", () => {
          this.dispatchEvent(new CustomEvent("avl-preview-open", { detail: { item }, bubbles: true, composed: true }));
        });
        actionsCell.appendChild(openButton);
      }
      row.appendChild(actionsCell);

      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    this.shadowRoot.appendChild(table);
  }
}

defineComponent("avl-generation-queue", AvlGenerationQueue);
