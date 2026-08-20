// <avl-pipeline-stage-track> — set `.stages` to the array from
// aarya_voice_lab.identity.contracts.pipeline_status()["stages"]
// (optionally each entry extended with a `runtimeState`). Renders the
// canonical stage order left-to-right; never reorders, filters, or
// summarises what the backend reports — the boundary and the
// implemented/not-implemented split come from the backend, not a guess.
import { AvlElement, defineComponent } from "./base-element.js";
import "./pipeline-stage-node.js";

export class AvlPipelineStageTrack extends AvlElement {
  set stages(value) {
    this._stages = Array.isArray(value) ? value : [];
    if (this.isConnected) this._render();
  }

  get stages() {
    return this._stages || [];
  }

  connectedCallback() {
    this._stages = this._stages || [];
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .track { display: flex; gap: var(--avl-space-2); overflow-x: auto; padding-bottom: var(--avl-space-2); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._stages.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No stage data.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const track = document.createElement("div");
    track.className = "track";
    track.setAttribute("role", "list");
    track.setAttribute("aria-label", "Pipeline stages");

    for (const stage of this._stages) {
      const node = document.createElement("avl-pipeline-stage-node");
      node.setAttribute("role", "listitem");
      node.stage = {
        name: stage.name,
        phase: stage.phase,
        implemented: stage.implemented,
        pastIdentityBoundary: stage.past_identity_boundary ?? stage.pastIdentityBoundary,
        runtimeState: stage.runtimeState || (stage.implemented ? "not_started" : "not_started"),
      };
      track.appendChild(node);
    }

    this.shadowRoot.appendChild(track);
  }
}

defineComponent("avl-pipeline-stage-track", AvlPipelineStageTrack);
