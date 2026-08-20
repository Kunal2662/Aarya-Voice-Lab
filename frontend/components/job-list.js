// <avl-job-list> wrapping rows for each Job (state/job-model.js). Set
// `.jobs` to an array of Job objects. Selecting a row dispatches
// `avl-job-select` with the job id — the host wires that to
// state/selection-model.js; this component holds no selection state.
import { AvlElement, defineComponent } from "./base-element.js";
import { JOB_STATUS_DOMAIN } from "../state/job-model.js";
import "./status-badge.js";

export class AvlJobList extends AvlElement {
  set jobs(value) {
    this._jobs = Array.isArray(value) ? value : [];
    if (this.isConnected) this._render();
  }

  get jobs() {
    return this._jobs || [];
  }

  connectedCallback() {
    this._jobs = this._jobs || [];
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      ul { display: flex; flex-direction: column; gap: var(--avl-space-1); }
      li button {
        width: 100%; display: flex; justify-content: space-between; align-items: center; gap: var(--avl-space-2);
        text-align: left; background: var(--avl-color-surface-raised);
        border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-sm);
        padding: var(--avl-space-2) var(--avl-space-3); cursor: pointer; color: var(--avl-color-text-primary);
        font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family);
      }
      li button:hover { background: var(--avl-color-surface-sunken); }
      .type { flex: 1; }
      .stage { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._jobs.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No jobs.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const list = document.createElement("ul");
    list.setAttribute("role", "list");
    for (const job of this._jobs) {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";

      const type = document.createElement("span");
      type.className = "type";
      type.textContent = job.type.replace(/_/g, " ");

      if (job.currentStage) {
        const stage = document.createElement("span");
        stage.className = "stage";
        stage.textContent = job.currentStage.replace(/_/g, " ");
        type.appendChild(document.createTextNode(" · "));
        type.appendChild(stage);
      }

      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", JOB_STATUS_DOMAIN);
      badge.setAttribute("state", job.status);

      button.append(type, badge);
      button.addEventListener("click", () => {
        this.dispatchEvent(new CustomEvent("avl-job-select", { detail: { jobId: job.id }, bubbles: true, composed: true }));
      });
      li.appendChild(button);
      list.appendChild(li);
    }
    this.shadowRoot.appendChild(list);
  }
}

defineComponent("avl-job-list", AvlJobList);
