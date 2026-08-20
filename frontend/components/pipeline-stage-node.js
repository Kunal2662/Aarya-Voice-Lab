// <avl-pipeline-stage-node> — one stage in the pipeline track. Set
// `.stage` to { name, phase, implemented, pastIdentityBoundary,
// runtimeState }. `runtimeState` is one of the "pipeline_stage" domain
// states from tokens/status.json (default "not_started" — this component
// never invents progress that hasn't actually happened). Stages past the
// speaker-identity boundary are marked distinctly but never hidden: the
// boundary's existence is itself something the UI must always show.
//
// Selecting a node (click or Enter/Space) dispatches `avl-stage-select`
// with the stage's `.stage` object (VL-D1 §12: "support stage selection,
// stage inspector"). The node itself holds no selection state — a host
// wires the event to state/selection-model.js.
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";

export class AvlPipelineStageNode extends AvlElement {
  set stage(value) {
    this._stage = value || null;
    if (this.isConnected) this._render();
  }

  get stage() {
    return this._stage;
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .node {
        display: flex; flex-direction: column; gap: var(--avl-space-1);
        padding: var(--avl-space-2); border: 1px solid var(--avl-color-border-default);
        border-radius: var(--avl-radius-sm); background: var(--avl-color-surface-raised);
        min-width: 9rem; cursor: pointer; text-align: left; font: inherit; color: inherit;
      }
      .node:hover { background: var(--avl-color-surface-sunken); }
      .node[data-boundary="true"] { border-left: 3px solid var(--avl-color-brand-accent); }
      .name { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .phase { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-muted); }
    `;
    this.shadowRoot.appendChild(style);

    const stage = this._stage || {};
    const node = document.createElement("button");
    node.type = "button";
    node.className = "node";
    node.dataset.boundary = String(!!stage.pastIdentityBoundary);
    node.setAttribute("aria-label", `${(stage.name || "unknown").replace(/_/g, " ")} stage, ${stage.runtimeState || "not_started"}`);

    const name = document.createElement("div");
    name.className = "name";
    name.textContent = (stage.name || "unknown").replace(/_/g, " ");

    const phase = document.createElement("div");
    phase.className = "phase";
    phase.textContent = stage.implemented ? (stage.phase || "") : `${stage.phase || ""} · not implemented`;

    const badge = document.createElement("avl-status-badge");
    badge.setAttribute("domain", "pipeline_stage");
    badge.setAttribute("state", stage.runtimeState || "not_started");

    node.append(name, phase, badge);
    node.addEventListener("click", () => {
      this.dispatchEvent(new CustomEvent("avl-stage-select", { detail: { stage }, bubbles: true, composed: true }));
    });
    this.shadowRoot.appendChild(node);
  }
}

defineComponent("avl-pipeline-stage-node", AvlPipelineStageNode);
