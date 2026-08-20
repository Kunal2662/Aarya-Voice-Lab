// <avl-confidence-control> -- VL-D6. A 1-5 self-reported reviewer
// confidence score, or unset (null) -- confidence is optional on
// pipeline.evaluation.Evaluation, never defaulted to a fabricated
// middle value. Controlled widget, same pattern as
// avl-rating-panel: reports its value via `avl-confidence-change`
// and `.getValue()`, never writes to a store itself.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlConfidenceControl extends AvlElement {
  connectedCallback() {
    this._value = this._value === undefined ? null : this._value;
    this._render();
  }

  reset() {
    this._value = null;
    this._render();
  }

  getValue() {
    return this._value;
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .row { display: flex; align-items: center; gap: var(--avl-space-1); flex-wrap: wrap; }
      .score-btn { width: 2rem; height: 2rem; border-radius: var(--avl-radius-sm); border: 1px solid var(--avl-color-border-default); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); cursor: pointer; font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      .score-btn[aria-pressed="true"] { background: var(--avl-color-brand-accent); color: var(--avl-color-text-on-accent, var(--avl-color-text-primary)); border-color: var(--avl-color-brand-accent); }
      .clear-btn { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); background: none; border: none; cursor: pointer; text-decoration: underline; }
    `;
    this.shadowRoot.appendChild(style);

    const row = document.createElement("div");
    row.className = "row";
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", "Confidence in this evaluation, 1 (low) to 5 (high)");

    for (let value = 1; value <= 5; value += 1) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "score-btn";
      button.textContent = String(value);
      button.setAttribute("aria-label", `Confidence ${value}`);
      button.setAttribute("aria-pressed", String(this._value === value));
      button.addEventListener("click", () => {
        this._value = value;
        this.dispatchEvent(new CustomEvent("avl-confidence-change", { detail: { confidence: this._value }, bubbles: true, composed: true }));
        this._render();
      });
      row.appendChild(button);
    }

    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "clear-btn";
    clear.textContent = "Unset";
    clear.addEventListener("click", () => {
      this._value = null;
      this.dispatchEvent(new CustomEvent("avl-confidence-change", { detail: { confidence: null }, bubbles: true, composed: true }));
      this._render();
    });
    row.appendChild(clear);

    this.shadowRoot.appendChild(row);
  }
}

defineComponent("avl-confidence-control", AvlConfidenceControl);
