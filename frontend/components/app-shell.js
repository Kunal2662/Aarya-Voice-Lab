// <avl-app-shell> — the VL-D0 layout skeleton: sidebar nav (left),
// workspace (main, slot="workspace"), inspector panel (right, collapsible,
// slot="inspector"), activity bar (bottom, slot="activity-bar"). Sidebar
// nav content goes in slot="sidebar". This component only lays regions
// out; it owns no navigation state and fetches nothing.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlAppShell extends AvlElement {
  static get observedAttributes() {
    return ["inspector-collapsed"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const inspectorCollapsed = this.hasAttribute("inspector-collapsed");

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .shell {
        display: grid;
        grid-template-columns: var(--avl-layout-sidebar-width) 1fr auto;
        grid-template-rows: 1fr var(--avl-layout-activity-bar-height);
        grid-template-areas:
          "sidebar workspace inspector"
          "activity-bar activity-bar activity-bar";
        min-width: var(--avl-layout-shell-min-width);
        height: 100vh;
        background: var(--avl-color-surface-canvas);
        color: var(--avl-color-text-primary);
      }
      .sidebar { grid-area: sidebar; border-right: 1px solid var(--avl-color-border-default); overflow: auto; }
      .workspace { grid-area: workspace; overflow: auto; padding: var(--avl-space-4); }
      .inspector {
        grid-area: inspector; width: var(--avl-layout-inspector-width);
        border-left: 1px solid var(--avl-color-border-default); overflow: auto;
      }
      .inspector[data-collapsed="true"] { width: 0; overflow: hidden; border-left: none; }
      .activity-bar { grid-area: activity-bar; }
    `;
    this.shadowRoot.appendChild(style);

    const shell = document.createElement("div");
    shell.className = "shell";

    const sidebar = document.createElement("div");
    sidebar.className = "sidebar";
    sidebar.appendChild(Object.assign(document.createElement("slot"), { name: "sidebar" }));

    const workspace = document.createElement("main");
    workspace.className = "workspace";
    workspace.appendChild(Object.assign(document.createElement("slot"), { name: "workspace" }));

    const inspector = document.createElement("div");
    inspector.className = "inspector";
    inspector.dataset.collapsed = String(inspectorCollapsed);
    inspector.appendChild(Object.assign(document.createElement("slot"), { name: "inspector" }));

    const activityBar = document.createElement("div");
    activityBar.className = "activity-bar";
    activityBar.appendChild(Object.assign(document.createElement("slot"), { name: "activity-bar" }));

    shell.append(sidebar, workspace, inspector, activityBar);
    this.shadowRoot.appendChild(shell);
  }
}

defineComponent("avl-app-shell", AvlAppShell);
