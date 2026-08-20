// <avl-batch-card> — set `.batch` to a batch-shaped object (see
// state/synthetic-fixtures.js syntheticBatches() for VL-D1's only
// source of batch data — no real importer exists yet). Selecting
// dispatches `avl-batch-select`.
import { AvlElement, defineComponent } from "./base-element.js";
import { JOB_STATUS_DOMAIN } from "../state/job-model.js";
import "./card.js";
import "./status-badge.js";

export class AvlBatchCard extends AvlElement {
  set batch(value) {
    this._batch = value || null;
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .card { cursor: pointer; }
      .header { display: flex; justify-content: space-between; align-items: center; }
      .id { font: var(--avl-type-code-weight) var(--avl-type-code-size) / 1 var(--avl-type-code-family); }
      .counts { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--avl-space-2); margin-top: var(--avl-space-2); }
      .count { display: flex; flex-direction: column; }
      .count-label { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-muted); }
      .count-value { font: var(--avl-type-body-weight) var(--avl-type-body-size) / 1 var(--avl-type-body-family); }
    `;
    this.shadowRoot.appendChild(style);

    const batch = this._batch;
    if (!batch) return;

    const card = document.createElement("avl-card");
    card.className = "card";
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `Batch ${batch.id}`);

    const header = document.createElement("div");
    header.slot = "header";
    header.className = "header";
    const id = document.createElement("span");
    id.className = "id";
    id.textContent = batch.id;
    const badge = document.createElement("avl-status-badge");
    badge.setAttribute("domain", JOB_STATUS_DOMAIN);
    badge.setAttribute("state", batch.status);
    header.append(id, badge);

    const counts = document.createElement("div");
    counts.className = "counts";
    for (const [label, value] of [
      ["Files", batch.fileCount],
      ["Valid", batch.valid],
      ["Warning", batch.warning],
      ["Invalid", batch.invalid],
      ["Blocked", batch.blocked],
      ["Review items", batch.reviewItems],
    ]) {
      const count = document.createElement("div");
      count.className = "count";
      const l = document.createElement("span");
      l.className = "count-label";
      l.textContent = label;
      const v = document.createElement("span");
      v.className = "count-value";
      v.textContent = String(value);
      count.append(l, v);
      counts.appendChild(count);
    }

    card.append(header, counts);
    card.addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("avl-batch-select", { detail: { batchId: batch.id }, bubbles: true, composed: true }));
    });
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        card.click();
      }
    });

    this.shadowRoot.appendChild(card);
  }
}

defineComponent("avl-batch-card", AvlBatchCard);
