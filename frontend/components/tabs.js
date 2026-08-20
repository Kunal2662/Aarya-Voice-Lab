// <avl-tabs> wrapping <avl-tab label="..."> children (each tab's content
// is its light-DOM children). Keyboard-navigable per WAI-ARIA tabs pattern
// (Left/Right/Home/End move focus and selection).
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlTab extends HTMLElement {}
defineComponent("avl-tab", AvlTab);

export class AvlTabs extends AvlElement {
  connectedCallback() {
    this._tabs = Array.from(this.querySelectorAll(":scope > avl-tab"));
    this._activeIndex = 0;
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .tablist { display: flex; gap: var(--avl-space-1); border-bottom: 1px solid var(--avl-color-border-default); }
      .tab {
        background: none; border: none; cursor: pointer;
        padding: var(--avl-space-2) var(--avl-space-3);
        font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family);
        color: var(--avl-color-text-secondary);
        border-bottom: 2px solid transparent;
      }
      .tab[aria-selected="true"] { color: var(--avl-color-text-primary); border-bottom-color: var(--avl-color-brand-accent); }
      .panels { padding: var(--avl-space-3) 0; }
    `;
    this.shadowRoot.appendChild(style);

    const tablist = document.createElement("div");
    tablist.className = "tablist";
    tablist.setAttribute("role", "tablist");

    const panels = document.createElement("div");
    panels.className = "panels";

    this._tabs.forEach((tabEl, index) => {
      const button = document.createElement("button");
      button.className = "tab";
      button.type = "button";
      button.id = `avl-tab-${index}`;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(index === this._activeIndex));
      button.tabIndex = index === this._activeIndex ? 0 : -1;
      button.textContent = tabEl.getAttribute("label") || `Tab ${index + 1}`;
      button.addEventListener("click", () => this._select(index));
      button.addEventListener("keydown", (event) => this._onKeydown(event, index));
      tablist.appendChild(button);

      tabEl.hidden = index !== this._activeIndex;
      tabEl.setAttribute("role", "tabpanel");
      tabEl.setAttribute("aria-labelledby", button.id);
    });

    const slot = document.createElement("slot");
    panels.appendChild(slot);

    this.shadowRoot.append(tablist, panels);
    this._tablistEl = tablist;
  }

  _onKeydown(event, index) {
    const last = this._tabs.length - 1;
    let next = null;
    if (event.key === "ArrowRight") next = index === last ? 0 : index + 1;
    else if (event.key === "ArrowLeft") next = index === 0 ? last : index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    if (next !== null) {
      event.preventDefault();
      this._select(next);
      this._tablistEl.children[next].focus();
    }
  }

  _select(index) {
    this._activeIndex = index;
    this._tabs.forEach((tabEl, i) => {
      tabEl.hidden = i !== index;
    });
    Array.from(this._tablistEl.children).forEach((button, i) => {
      button.setAttribute("aria-selected", String(i === index));
      button.tabIndex = i === index ? 0 : -1;
    });
    this.dispatchEvent(new CustomEvent("avl-tab-change", { detail: { index }, bubbles: true, composed: true }));
  }
}

defineComponent("avl-tabs", AvlTabs);
