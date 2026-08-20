// <avl-workspace-pipeline> — VL-D1 §12. The real visual pipeline,
// rendered from frontend/contracts/generated/pipeline_stage.json (which
// is exported from pipeline/stages.py — never recomputed here). Stage
// selection updates the Inspector. Nothing executes pipeline logic from
// this workspace.
import { AvlElement, defineComponent } from "./base-element.js";
import "./workspace-state.js";
import "./pipeline-stage-track.js";
import "./notice-banner.js";

export class AvlWorkspacePipeline extends AvlElement {
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
      const response = await fetch(new URL("../contracts/generated/pipeline_stage.json", import.meta.url));
      const contract = await response.json();
      this._stages = contract.stages.map((name, index) => ({
        name,
        phase: contract.phase_2_stages.includes(name) ? "phase-2" : "phase-3+",
        implemented: contract.phase_2_stages.includes(name),
        past_identity_boundary: index >= contract.speaker_identity_boundary_index,
        runtimeState: "not_started",
      }));
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
    style.textContent = `h2 { margin: 0 0 var(--avl-space-3) 0; }`;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "error") wrapper.setAttribute("detail", this._errorDetail || "");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Pipeline";
    wrapper.appendChild(heading);

    const notice = document.createElement("avl-notice-banner");
    notice.setAttribute("tone", "info");
    notice.textContent = "Technical processing (Phase 2) and speaker-identity processing (Phase 3+) are always shown distinctly — the boundary is never hidden.";
    wrapper.appendChild(notice);

    if (this._stages) {
      const track = document.createElement("avl-pipeline-stage-track");
      track.stages = this._stages;
      track.addEventListener("avl-stage-select", (event) => {
        this._selectionModel?.select("pipeline-stage", event.detail.stage.name, event.detail.stage);
      });
      wrapper.appendChild(track);
    }

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-pipeline", AvlWorkspacePipeline);
