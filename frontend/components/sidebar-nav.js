// <avl-sidebar-nav> wrapping <avl-sidebar-item icon="..." label="..." href="#..." active>
// Only a handful of destinations exist as of VL-D0; most are placeholders
// pointing at future milestones (VL-D1+), rendered disabled rather than
// omitted, so the shell's shape is visible without pretending those
// screens exist yet.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlSidebarItem extends HTMLElement {}
defineComponent("avl-sidebar-item", AvlSidebarItem);

export class AvlSidebarNav extends AvlElement {
  connectedCallback() {
    this._items = Array.from(this.querySelectorAll(":scope > avl-sidebar-item"));
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      nav { display: flex; flex-direction: column; gap: var(--avl-space-1); padding: var(--avl-space-2); }
      .item {
        display: flex; align-items: center; gap: var(--avl-space-2);
        padding: var(--avl-space-2) var(--avl-space-3);
        border-radius: var(--avl-radius-md);
        color: var(--avl-color-text-secondary);
        font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family);
        background: none; border: none; text-align: left; cursor: pointer; width: 100%;
      }
      .item[aria-current="page"] { background: var(--avl-color-brand-accent-subtle); color: var(--avl-color-brand-accent); }
      .item[disabled] { color: var(--avl-color-text-disabled); cursor: default; }
      .item:not([disabled]):hover { background: var(--avl-color-surface-sunken); }
      .icon { width: 1rem; text-align: center; flex: none; }
      .planned { margin-left: auto; font: var(--avl-type-caption-weight) 0.65rem/1 var(--avl-type-caption-family); color: var(--avl-color-text-disabled); }
    `;
    this.shadowRoot.appendChild(style);

    const nav = document.createElement("nav");
    nav.setAttribute("aria-label", "Primary");

    for (const item of this._items) {
      const active = item.hasAttribute("active");
      const planned = item.hasAttribute("planned");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "item";
      if (active) button.setAttribute("aria-current", "page");
      if (planned) button.disabled = true;

      const icon = document.createElement("span");
      icon.className = "icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = item.getAttribute("icon") || "•";

      const label = document.createElement("span");
      label.textContent = item.getAttribute("label") || "";

      button.append(icon, label);

      if (planned) {
        const tag = document.createElement("span");
        tag.className = "planned";
        tag.textContent = "planned";
        button.appendChild(tag);
      }

      button.addEventListener("click", () => {
        if (planned) return;
        this.dispatchEvent(
          new CustomEvent("avl-navigate", {
            detail: { destination: item.getAttribute("destination") || item.getAttribute("label") },
            bubbles: true,
            composed: true,
          }),
        );
      });

      nav.appendChild(button);
    }

    this.shadowRoot.appendChild(nav);
  }
}

defineComponent("avl-sidebar-nav", AvlSidebarNav);
