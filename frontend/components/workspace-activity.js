// <avl-workspace-activity> — VL-D1 §13. Unified activity timeline with a
// source filter. Set `.services = { activityStore }`.
import { AvlElement, defineComponent } from "./base-element.js";
import { ActivitySource } from "../state/activity-model.js";
import "./workspace-state.js";
import "./activity-timeline.js";
import "./panel.js";
import "./stat-tile.js";

// FE-3 -- same 5-tone cycle every other workspace dashboard uses.
const TILE_TONES = ["blue", "teal", "green", "violet", "pink"];

export class AvlWorkspaceActivity extends AvlElement {
  set services(value) {
    this._services = value || {};
  }

  connectedCallback() {
    this._services = this._services || {};
    this._filter = "";
    this._load();
  }

  async _load() {
    this._state = "loading";
    this._render();
    const events = this._services.activityStore ? this._services.activityStore.list() : [];
    this._state = events.length ? "ready" : "empty";
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      /* FE-3 -- padding/border/background/color/font now come from
         css/base.css's shared input/select baseline; only this
         workspace's own layout spacing stays local. */
      select { margin-bottom: var(--avl-space-3); }
      .dashboard-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: var(--avl-space-3); margin-bottom: var(--avl-space-3); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "empty") wrapper.setAttribute("title", "No activity recorded yet");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Activity";
    wrapper.appendChild(heading);

    const allEvents = this._services.activityStore ? this._services.activityStore.list() : [];

    if (this._state === "ready") {
      const dashboard = document.createElement("avl-panel");
      dashboard.setAttribute("title", "Activity dashboard");
      const grid = document.createElement("div");
      grid.className = "dashboard-grid";
      const counts = {
        "Total events": allEvents.length,
        "Sources active": new Set(allEvents.map((e) => e.source)).size,
      };
      Object.entries(counts).forEach(([label, value], i) => {
        const tile = document.createElement("avl-stat-tile");
        tile.setAttribute("label", label);
        tile.setAttribute("value", String(value));
        tile.setAttribute("tone", TILE_TONES[i % TILE_TONES.length]);
        tile.setAttribute("icon", "activity");
        grid.appendChild(tile);
      });
      dashboard.appendChild(grid);
      wrapper.appendChild(dashboard);
    }

    const select = document.createElement("select");
    select.setAttribute("aria-label", "Filter activity by source");
    const allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = "All sources";
    select.appendChild(allOption);
    for (const source of Object.values(ActivitySource)) {
      const option = document.createElement("option");
      option.value = source;
      option.textContent = source.replace(/_/g, " ");
      select.appendChild(option);
    }
    select.value = this._filter;
    select.addEventListener("change", () => {
      this._filter = select.value;
      this._render();
    });
    wrapper.appendChild(select);

    const timeline = document.createElement("avl-activity-timeline");
    timeline.events = this._filter ? allEvents.filter((e) => e.source === this._filter) : allEvents;
    wrapper.appendChild(timeline);

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-activity", AvlWorkspaceActivity);
