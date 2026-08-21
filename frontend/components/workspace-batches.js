// <avl-workspace-batches> — VL-D1 §10, extended in VL-D2 §13 with a
// Dataset Dashboard. Batch-level visualization from synthetic fixtures
// (state/synthetic-fixtures.js) plus real counts from the live import
// queue where one exists. Selecting a batch updates `.selectionModel`
// so the Inspector shows its details. Every dashboard number is summed
// from an actual array — never a placeholder or a guess.
import { AvlElement, defineComponent } from "./base-element.js";
import { syntheticBatches, syntheticRecordings } from "../state/synthetic-fixtures.js";
import "./workspace-state.js";
import "./batch-card.js";
import "./panel.js";
import "./stat-tile.js";

// FE-2.3 -- cycled across the dashboard's stat tiles for visual variety;
// same 5 categorical tones every other dashboard in the app uses, no
// per-workspace color meaning invented.
const TILE_TONES = ["blue", "teal", "green", "violet", "pink"];

export class AvlWorkspaceBatches extends AvlElement {
  set selectionModel(value) {
    this._selectionModel = value;
  }

  set services(value) {
    this._services = value || {};
  }

  connectedCallback() {
    this._services = this._services || {};
    this._load();
  }

  async _load() {
    this._state = "loading";
    this._render();
    this._batches = syntheticBatches();
    this._recordings = syntheticRecordings();
    this._state = this._batches.length ? "ready" : "empty";
    this._render();
  }

  _dashboardCounts() {
    const recordings = this._recordings || [];
    const importCounts = this._services.importQueue ? this._services.importQueue.counts() : {};
    return {
      "Total files": recordings.length + (this._services.importQueue?.items.size || 0),
      Accepted: recordings.filter((r) => r.validation === "valid").length + (importCounts.accepted || 0),
      Warning: recordings.filter((r) => r.validation === "warning").length + (importCounts.warning || 0),
      Invalid: recordings.filter((r) => r.validation === "invalid").length + (importCounts.invalid || 0),
      Blocked: importCounts.blocked || 0,
      Duplicates: importCounts.duplicate || 0,
      Batches: (this._batches || []).length,
      Processing: (this._batches || []).filter((b) => b.status === "running").length,
      Candidates: (this._batches || []).reduce((sum, b) => sum + (b.candidates || 0), 0),
      "Review items": (this._batches || []).reduce((sum, b) => sum + (b.reviewItems || 0), 0),
    };
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      .list { display: flex; flex-direction: column; gap: var(--avl-space-3); margin-top: var(--avl-space-4); }
      .dashboard-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: var(--avl-space-3); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "empty") wrapper.setAttribute("title", "No batches yet");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Batches";
    wrapper.appendChild(heading);

    if (this._state === "ready") {
      const dashboard = document.createElement("avl-panel");
      dashboard.setAttribute("title", "Dataset dashboard");
      const grid = document.createElement("div");
      grid.className = "dashboard-grid";
      Object.entries(this._dashboardCounts()).forEach(([label, value], i) => {
        const tile = document.createElement("avl-stat-tile");
        tile.setAttribute("label", label);
        tile.setAttribute("value", String(value));
        tile.setAttribute("tone", TILE_TONES[i % TILE_TONES.length]);
        tile.setAttribute("icon", "batches");
        grid.appendChild(tile);
      });
      dashboard.appendChild(grid);
      wrapper.appendChild(dashboard);
    }

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
