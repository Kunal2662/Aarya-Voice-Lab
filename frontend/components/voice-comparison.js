// <avl-voice-comparison> — set `.left` and `.right` to PreviewArtifact
// dicts (or null) for an A/B listen. Purely a side-by-side composition of
// two avl-voice-player instances; no comparison logic (no scoring, no
// automated "which is better") lives here — that judgment is the whole
// point of VL-V0's human-in-the-loop requirement.
import { AvlElement, defineComponent } from "./base-element.js";
import "./voice-player.js";

export class AvlVoiceComparison extends AvlElement {
  set left(value) {
    this._left = value || null;
    if (this.isConnected) this._render();
  }

  set right(value) {
    this._right = value || null;
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .comparison { display: grid; grid-template-columns: 1fr 1fr; gap: var(--avl-space-4); }
      .column { display: flex; flex-direction: column; gap: var(--avl-space-2); }
      .label { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); text-transform: uppercase; }
    `;
    this.shadowRoot.appendChild(style);

    const comparison = document.createElement("div");
    comparison.className = "comparison";

    for (const [labelText, artifact] of [
      ["A", this._left],
      ["B", this._right],
    ]) {
      const column = document.createElement("div");
      column.className = "column";
      const label = document.createElement("span");
      label.className = "label";
      label.textContent = labelText;
      const player = document.createElement("avl-voice-player");
      player.artifact = artifact;
      column.append(label, player);
      comparison.appendChild(column);
    }

    this.shadowRoot.appendChild(comparison);
  }
}

defineComponent("avl-voice-comparison", AvlVoiceComparison);
