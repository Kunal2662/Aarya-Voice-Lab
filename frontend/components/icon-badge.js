// <avl-icon-badge tone="violet|blue|green|pink|teal" icon="batches" label="...">
// FE-2.1 -- a small colored rounded chip wrapping <avl-icon>, for the
// denser dashboard visual language's stat tiles and panel headers.
// `tone` selects one of the 5 categorical accent colors added to
// tokens/color.json for FE-2 (decorative variety across tiles, never
// semantic status -- semantic state still goes through
// avl-status-badge/status.json's domain vocabulary, unchanged). The
// badge's background is always the token's `-subtle` variant with the
// full-strength color used for the icon itself, matching the existing
// tone pattern in notice-banner.js (`--avl-tone-bg`/`--avl-tone-border`).
import { AvlElement, defineComponent } from "./base-element.js";
import "./icon.js";

const TONES = ["violet", "blue", "green", "pink", "teal"];

export class AvlIconBadge extends AvlElement {
  static get observedAttributes() {
    return ["tone", "icon", "label"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const tone = TONES.includes(this.getAttribute("tone")) ? this.getAttribute("tone") : "blue";
    const iconName = this.getAttribute("icon") || "";
    const label = this.getAttribute("label");

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .badge {
        display: inline-flex; align-items: center; justify-content: center;
        width: 2.25rem; height: 2.25rem;
        border-radius: var(--avl-radius-md);
        background: var(--avl-tone-bg);
        color: var(--avl-tone-fg);
      }
      .violet { --avl-tone-bg: var(--avl-color-category-violet-subtle); --avl-tone-fg: var(--avl-color-category-violet); }
      .blue   { --avl-tone-bg: var(--avl-color-category-blue-subtle);   --avl-tone-fg: var(--avl-color-category-blue); }
      .green  { --avl-tone-bg: var(--avl-color-category-green-subtle);  --avl-tone-fg: var(--avl-color-category-green); }
      .pink   { --avl-tone-bg: var(--avl-color-category-pink-subtle);   --avl-tone-fg: var(--avl-color-category-pink); }
      .teal   { --avl-tone-bg: var(--avl-color-category-teal-subtle);   --avl-tone-fg: var(--avl-color-category-teal); }
    `;
    this.shadowRoot.appendChild(style);

    const badge = document.createElement("div");
    badge.className = `badge ${tone}`;

    const icon = document.createElement("avl-icon");
    icon.setAttribute("name", iconName);
    icon.setAttribute("size", "1.15rem");
    if (label) icon.setAttribute("label", label);
    badge.appendChild(icon);

    this.shadowRoot.appendChild(badge);
  }
}

defineComponent("avl-icon-badge", AvlIconBadge);
