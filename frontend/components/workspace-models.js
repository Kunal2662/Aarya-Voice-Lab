// <avl-workspace-models> — VL-D1 §18. Model/runtime explorer.
// Vendor-neutral: the list of supported backends comes from
// frontend/contracts/generated/compute_backend.json (exported from
// identity/runtime.py's ComputeBackend) so NVIDIA is never privileged
// over AMD/Intel/CPU-only in this UI.
import { AvlElement, defineComponent } from "./base-element.js";
import { syntheticModels } from "../state/synthetic-fixtures.js";
import "./workspace-state.js";
import "./model-card.js";
import "./panel.js";
import "./stat-tile.js";

// FE-3 -- same 5-tone cycle every other workspace dashboard uses.
const TILE_TONES = ["blue", "teal", "green", "violet", "pink"];

export class AvlWorkspaceModels extends AvlElement {
  set selectionModel(value) {
    this._selectionModel = value;
  }

  connectedCallback() {
    this._load();
  }

  async _load() {
    this._state = "loading";
    this._render();
    try {
      const response = await fetch(new URL("../contracts/generated/compute_backend.json", import.meta.url));
      this._backends = (await response.json()).values;
      this._models = syntheticModels();
      this._state = "ready";
    } catch (err) {
      this._state = "error";
      this._errorDetail = String(err);
    }
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      .list { display: flex; flex-direction: column; gap: var(--avl-space-3); }
      .backend-list { display: flex; flex-wrap: wrap; gap: var(--avl-space-1); }
      .backend { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); padding: var(--avl-space-1) var(--avl-space-2); border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-pill); color: var(--avl-color-text-secondary); }
      .dashboard-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: var(--avl-space-3); margin-bottom: var(--avl-space-4); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "error") wrapper.setAttribute("detail", this._errorDetail || "");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Models";
    wrapper.appendChild(heading);

    if (this._state === "ready" && this._models) {
      const dashboard = document.createElement("avl-panel");
      dashboard.setAttribute("title", "Model dashboard");
      const grid = document.createElement("div");
      grid.className = "dashboard-grid";
      const counts = {
        "Total models": this._models.length,
        "Backends supported": (this._backends || []).length,
        Installed: this._models.filter((m) => m.runtime === "installed").length,
        "Not installed": this._models.filter((m) => m.runtime !== "installed").length,
      };
      Object.entries(counts).forEach(([label, value], i) => {
        const tile = document.createElement("avl-stat-tile");
        tile.setAttribute("label", label);
        tile.setAttribute("value", String(value));
        tile.setAttribute("tone", TILE_TONES[i % TILE_TONES.length]);
        tile.setAttribute("icon", "models");
        grid.appendChild(tile);
      });
      dashboard.appendChild(grid);
      wrapper.appendChild(dashboard);
    }

    if (this._backends) {
      const panel = document.createElement("avl-panel");
      panel.setAttribute("title", "Supported compute backends");
      const list = document.createElement("div");
      list.className = "backend-list";
      for (const backend of this._backends) {
        const el = document.createElement("span");
        el.className = "backend";
        el.textContent = backend;
        list.appendChild(el);
      }
      panel.appendChild(list);
      wrapper.appendChild(panel);
    }

    const list = document.createElement("div");
    list.className = "list";
    for (const model of this._models || []) {
      const card = document.createElement("avl-model-card");
      card.model = model;
      card.addEventListener("click", () => this._selectionModel?.select("model", model.id, model));
      list.appendChild(card);
    }
    wrapper.appendChild(list);

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-models", AvlWorkspaceModels);
