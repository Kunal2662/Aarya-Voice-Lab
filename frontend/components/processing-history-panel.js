// <avl-processing-history-panel> — VL-D4 §16, §18. Set `.recordingId`
// and `.historyStore` (a state/processing-model.js ProcessingHistoryStore).
// Lists every processing run for a recording, oldest first, with a
// "Make active" (rollback) action on any non-current record — rollback
// never deletes or edits, it appends a new record, so every prior entry
// stays listed here afterward (VL-D3's append-only review history,
// applied to derived-artifact versions instead of review decisions).
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";
import "./button.js";

export class AvlProcessingHistoryPanel extends AvlElement {
  set recordingId(value) {
    this._recordingId = value || null;
    if (this.isConnected) this._render();
  }

  set historyStore(value) {
    if (this._historyStore) this._historyStore.removeEventListener("change", this._onChange);
    this._historyStore = value;
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
    if (this._historyStore) this._historyStore.removeEventListener("change", this._onChange);
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--avl-space-2); }
      li { border: 1px solid var(--avl-color-border-subtle); border-radius: var(--avl-radius-sm); padding: var(--avl-space-2); }
      /* FE-1.5 -- .row replaced by the shared avl-row avl-row--center utilities (css/base.css). */
      .meta { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-1); }
      .current { border-color: var(--avl-color-brand-accent); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._historyStore || !this._recordingId) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select a recording to view its processing history.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const records = this._historyStore.history(this._recordingId);
    if (!records.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No processing history for this recording yet.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const current = this._historyStore.current(this._recordingId);
    const list = document.createElement("ul");
    for (const record of records) {
      const item = document.createElement("li");
      const isCurrent = current && current.recordId === record.recordId;
      if (isCurrent) item.className = "current";

      const row = document.createElement("div");
      row.className = "avl-row avl-row--center";
      const label = document.createElement("span");
      label.textContent = `${record.recordId}${record.isRollback ? " (rollback)" : ""}`;
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "processing_status");
      badge.setAttribute("state", record.status);
      row.append(label, badge);
      item.appendChild(row);

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = `profile ${record.profileId} — ${record.recordedAt}${isCurrent ? " — active" : ""}`;
      item.appendChild(meta);

      if (!isCurrent) {
        const rollbackButton = document.createElement("avl-button");
        rollbackButton.setAttribute("variant", "secondary");
        rollbackButton.textContent = "Make active";
        rollbackButton.addEventListener("click", () => {
          this._historyStore.rollback(this._recordingId, record.recordId);
        });
        item.appendChild(rollbackButton);
      }

      list.appendChild(item);
    }
    this.shadowRoot.appendChild(list);
  }
}

defineComponent("avl-processing-history-panel", AvlProcessingHistoryPanel);
