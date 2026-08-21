// <avl-panel title="..." collapsible> — a titled content region used
// throughout the inspector and workspace areas of the shell.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlPanel extends AvlElement {
  static get observedAttributes() {
    return ["title", "collapsible", "collapsed"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const title = this.getAttribute("title") || "";
    const collapsible = this.hasAttribute("collapsible");
    const collapsed = this.hasAttribute("collapsed");

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .panel { display: flex; flex-direction: column; height: 100%; }
      .titlebar {
        display: flex; align-items: center; justify-content: space-between;
        padding: var(--avl-space-2) var(--avl-space-3);
        border-bottom: 1px solid var(--avl-color-border-subtle);
        font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family);
        color: var(--avl-color-text-secondary);
        text-transform: uppercase; letter-spacing: 0.04em;
      }
      .toggle {
        background: none; border: none; cursor: pointer; color: inherit;
        font: inherit; padding: 0;
      }
      /* FE-1.8 -- the titlebar's label is now a real <h3> (was a plain
         <span>) so panel titles are reachable via screen-reader
         heading navigation; margin/font/weight reset to zero so this
         is purely a semantic change, not a visual one. */
      .titlebar h3 { margin: 0; font: inherit; font-weight: inherit; }
      .content { padding: var(--avl-space-3); overflow: auto; flex: 1; }
      .content[hidden] { display: none; }
    `;
    this.shadowRoot.appendChild(style);

    const panel = document.createElement("div");
    panel.className = "panel";

    const titlebar = document.createElement("div");
    titlebar.className = "titlebar";
    const heading = document.createElement("h3");
    heading.textContent = title;
    titlebar.appendChild(heading);

    const content = document.createElement("div");
    content.className = "content";
    content.appendChild(document.createElement("slot"));
    if (collapsed) content.hidden = true;

    if (collapsible) {
      const toggle = document.createElement("button");
      toggle.className = "toggle";
      toggle.type = "button";
      toggle.setAttribute("aria-expanded", String(!collapsed));
      toggle.textContent = collapsed ? "Show" : "Hide";
      toggle.addEventListener("click", () => {
        const nowCollapsed = !content.hidden ? true : false;
        content.hidden = nowCollapsed;
        toggle.setAttribute("aria-expanded", String(!nowCollapsed));
        toggle.textContent = nowCollapsed ? "Show" : "Hide";
      });
      titlebar.appendChild(toggle);
    }

    panel.append(titlebar, content);
    this.shadowRoot.appendChild(panel);
  }
}

defineComponent("avl-panel", AvlPanel);
