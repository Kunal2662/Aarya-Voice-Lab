// <avl-generation-history-panel> — VL-D5 §17-§20. Set `.voiceProfileId`
// and `.historyStore` (a state/generation-model.js PreviewHistoryStore).
// Lists every generation for a voice profile, oldest first, labelled
// "Generation 1/2/3…" — regeneration never overwrites, so every prior
// entry stays listed here afterward (the same append-only pattern
// avl-processing-history-panel already established for derived-artifact
// versions, applied to generated-output provenance instead). Clicking a
// row dispatches `avl-generation-select` so the workspace can load that
// generation's artifact back into the main preview area.
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";

export class AvlGenerationHistoryPanel extends AvlElement {
  set voiceProfileId(value) {
    this._voiceProfileId = value || null;
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
      li { border: 1px solid var(--avl-color-border-subtle); border-radius: var(--avl-radius-sm); padding: var(--avl-space-2); cursor: pointer; }
      li:hover { background: var(--avl-color-surface-sunken); }
      /* FE-1.5 -- .row replaced by the shared avl-row avl-row--center utilities (css/base.css). */
      .meta { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-1); }
      .current { border-color: var(--avl-color-brand-accent); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._historyStore || !this._voiceProfileId) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select a voice profile to view its generation history.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const records = this._historyStore.history(this._voiceProfileId);
    if (!records.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No generations for this voice profile yet.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const current = this._historyStore.current(this._voiceProfileId);
    const list = document.createElement("ul");
    records.forEach((record, index) => {
      const item = document.createElement("li");
      const isCurrent = current && current.record_id === record.record_id;
      if (isCurrent) item.className = "current";
      item.tabIndex = 0;
      item.setAttribute("role", "button");

      const row = document.createElement("div");
      row.className = "avl-row avl-row--center";
      const label = document.createElement("span");
      label.textContent = `Generation ${index + 1}`;
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "generation_status");
      badge.setAttribute("state", record.status);
      row.append(label, badge);
      item.appendChild(row);

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = `model ${record.model_id} — ${record.recorded_at}${isCurrent ? " — latest" : ""}`;
      item.appendChild(meta);

      const select = () => {
        this.dispatchEvent(
          new CustomEvent("avl-generation-select", { detail: { record }, bubbles: true, composed: true }),
        );
      };
      item.addEventListener("click", select);
      item.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select();
        }
      });

      list.appendChild(item);
    });
    this.shadowRoot.appendChild(list);
  }
}

defineComponent("avl-generation-history-panel", AvlGenerationHistoryPanel);
