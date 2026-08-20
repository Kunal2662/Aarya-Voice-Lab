// <avl-workspace-activity> — VL-D1 §13. Unified activity timeline with a
// source filter. Set `.services = { activityStore }`.
import { AvlElement, defineComponent } from "./base-element.js";
import { ActivitySource } from "../state/activity-model.js";
import "./workspace-state.js";
import "./activity-timeline.js";

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
      select { margin-bottom: var(--avl-space-3); padding: var(--avl-space-1) var(--avl-space-2); border-radius: var(--avl-radius-sm); border: 1px solid var(--avl-color-border-default); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "empty") wrapper.setAttribute("title", "No activity recorded yet");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Activity";
    wrapper.appendChild(heading);

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
    const events = this._services.activityStore ? this._services.activityStore.list() : [];
    timeline.events = this._filter ? events.filter((e) => e.source === this._filter) : events;
    wrapper.appendChild(timeline);

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-activity", AvlWorkspaceActivity);
