// <avl-workspace-batches> — VL-D1 §10. Batch-level visualization from
// synthetic fixtures (state/synthetic-fixtures.js — no real importer
// exists). Selecting a batch updates `.selectionModel` so the Inspector
// shows its details.
import { AvlElement, defineComponent } from "./base-element.js";
import { syntheticBatches } from "../state/synthetic-fixtures.js";
import "./workspace-state.js";
import "./batch-card.js";

export class AvlWorkspaceBatches extends AvlElement {
  set selectionModel(value) {
    this._selectionModel = value;
  }

  connectedCallback() {
    this._load();
  }

  async _load() {
    this._state = "loading";
    this._render();
    this._batches = syntheticBatches();
    this._state = this._batches.length ? "ready" : "empty";
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      .list { display: flex; flex-direction: column; gap: var(--avl-space-3); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "empty") wrapper.setAttribute("title", "No batches yet");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Batches";
    wrapper.appendChild(heading);

    const list = document.createElement("div");
    list.className = "list";
    for (const batch of this._batches || []) {
      const card = document.createElement("avl-batch-card");
      card.batch = batch;
      card.addEventListener("avl-batch-select", (event) => {
        this._selectionModel?.select("batch", event.detail.batchId, batch);
      });
      list.appendChild(card);
    }
    wrapper.appendChild(list);

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-batches", AvlWorkspaceBatches);
