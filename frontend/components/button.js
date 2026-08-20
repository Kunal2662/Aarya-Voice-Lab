// <avl-button variant="primary|secondary|danger|ghost" disabled>
import { AvlElement, defineComponent } from "./base-element.js";

const VARIANTS = ["primary", "secondary", "danger", "ghost"];

export class AvlButton extends AvlElement {
  static get observedAttributes() {
    return ["variant", "disabled"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const variant = VARIANTS.includes(this.getAttribute("variant")) ? this.getAttribute("variant") : "secondary";
    const disabled = this.hasAttribute("disabled");

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      button {
        font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family);
        padding: var(--avl-space-2) var(--avl-space-4);
        border-radius: var(--avl-radius-md);
        border: 1px solid var(--avl-color-border-default);
        cursor: pointer;
        transition: background var(--avl-duration-fast) var(--avl-easing-standard),
                    border-color var(--avl-duration-fast) var(--avl-easing-standard);
      }
      button:disabled { cursor: not-allowed; opacity: 0.55; }
      .primary   { background: var(--avl-color-brand-accent); border-color: var(--avl-color-brand-accent); color: var(--avl-color-text-inverse); }
      .primary:hover:not(:disabled)   { background: var(--avl-color-brand-accent-strong); }
      .secondary { background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); }
      .secondary:hover:not(:disabled) { background: var(--avl-color-surface-sunken); }
      .danger    { background: var(--avl-color-state-danger); border-color: var(--avl-color-state-danger); color: var(--avl-color-text-inverse); }
      .ghost     { background: transparent; border-color: transparent; color: var(--avl-color-text-secondary); }
      .ghost:hover:not(:disabled)     { background: var(--avl-color-surface-sunken); }
    `;
    this.shadowRoot.appendChild(style);

    const button = document.createElement("button");
    button.className = variant;
    button.type = this.getAttribute("type") || "button";
    if (disabled) button.disabled = true;
    button.append(document.createElement("slot"));
    button.addEventListener("click", (event) => {
      if (disabled) {
        event.stopImmediatePropagation();
      }
    });
    this.shadowRoot.appendChild(button);
  }
}

defineComponent("avl-button", AvlButton);
