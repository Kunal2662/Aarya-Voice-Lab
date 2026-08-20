// <avl-accent-panel> — VL-D21 concepts only. No pronunciation engine
// exists; this renders a fixed, honest "not implemented" state plus the
// shape a future accent/pronunciation profile would take, so later work
// has a UI target without this component pretending analysis has run.
import { AvlElement, defineComponent } from "./base-element.js";
import "./card.js";
import "./metric-placeholder.js";

export class AvlAccentPanel extends AvlElement {
  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .title { font: var(--avl-type-subheading-weight) var(--avl-type-subheading-size) / var(--avl-type-subheading-line-height) var(--avl-type-subheading-family); }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); margin-top: var(--avl-space-2); }
    `;
    this.shadowRoot.appendChild(style);

    const card = document.createElement("avl-card");
    const header = document.createElement("span");
    header.slot = "header";
    header.className = "title";
    header.textContent = "Accent & pronunciation";
    card.appendChild(header);

    for (const label of ["Detected accent region", "Pronunciation deviation score", "Phoneme confidence"]) {
      const metric = document.createElement("avl-metric-placeholder");
      metric.setAttribute("label", label);
      card.appendChild(metric);
    }

    const note = document.createElement("div");
    note.className = "note";
    note.textContent = "No accent or pronunciation analysis engine exists yet (VL-D21 is concepts only).";
    card.appendChild(note);

    this.shadowRoot.appendChild(card);
  }
}

defineComponent("avl-accent-panel", AvlAccentPanel);
