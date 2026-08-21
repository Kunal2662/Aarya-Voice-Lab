// <avl-card> with named slots: header, default (body), footer.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlCard extends AvlElement {
  connectedCallback() {
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      /* FE-3 -- avl-card now uses the same glass-surface treatment as
         avl-panel/base.css's .avl-glass, so cards and panels read as
         one consistent surface family instead of two different looks
         (card was previously an opaque solid, panel had no surface
         at all). */
      .card {
        background: var(--avl-color-glass-surface);
        border: 1px solid var(--avl-color-glass-border);
        border-radius: var(--avl-radius-md);
        box-shadow: 0 1px 3px var(--avl-color-shadow-ambient);
        overflow: hidden;
      }
      .header {
        padding: var(--avl-space-3) var(--avl-space-4);
        border-bottom: 1px solid var(--avl-color-border-subtle);
      }
      .header:empty { display: none; }
      .body { padding: var(--avl-space-4); }
      .footer {
        padding: var(--avl-space-3) var(--avl-space-4);
        border-top: 1px solid var(--avl-color-border-subtle);
        background: var(--avl-color-surface-sunken);
      }
      .footer:empty { display: none; }
    `;
    this.shadowRoot.appendChild(style);

    const card = document.createElement("div");
    card.className = "card";

    const header = document.createElement("div");
    header.className = "header";
    header.appendChild(Object.assign(document.createElement("slot"), { name: "header" }));

    const body = document.createElement("div");
    body.className = "body";
    body.appendChild(document.createElement("slot"));

    const footer = document.createElement("div");
    footer.className = "footer";
    footer.appendChild(Object.assign(document.createElement("slot"), { name: "footer" }));

    card.append(header, body, footer);
    this.shadowRoot.appendChild(card);
  }
}

defineComponent("avl-card", AvlCard);
