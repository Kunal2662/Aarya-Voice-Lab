// <avl-workspace-recordings> — VL-D1 §11. Recording explorer, technical/
// provenance fields only — no speaker identity field exists anywhere in
// this component or the synthetic fixture it renders, preserving the
// Phase 2 speaker boundary (pipeline/stages.py's SPEAKER_IDENTITY_BOUNDARY).
import { AvlElement, defineComponent } from "./base-element.js";
import { syntheticRecordings } from "../state/synthetic-fixtures.js";
import "./workspace-state.js";
import "./recording-row.js";

export class AvlWorkspaceRecordings extends AvlElement {
  set selectionModel(value) {
    this._selectionModel = value;
  }

  connectedCallback() {
    this._load();
  }

  async _load() {
    this._state = "loading";
    this._render();
    this._recordings = syntheticRecordings();
    this._state = this._recordings.length ? "ready" : "empty";
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      .list { display: flex; flex-direction: column; gap: var(--avl-space-2); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "empty") wrapper.setAttribute("title", "No recordings in this batch");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Recordings";
    wrapper.appendChild(heading);

    const list = document.createElement("div");
    list.className = "list";
    for (const recording of this._recordings || []) {
      const row = document.createElement("avl-recording-row");
      row.recording = recording;
      row.addEventListener("avl-recording-select", () => {
        this._selectionModel?.select("recording", recording.id, recording);
      });
      list.appendChild(row);
    }
    wrapper.appendChild(list);

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-recordings", AvlWorkspaceRecordings);
