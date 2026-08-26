// <avl-app-shell> — the VL-D0 layout skeleton: sidebar nav (left),
// workspace (main, slot="workspace"), inspector panel (right, collapsible,
// slot="inspector"), activity bar (bottom, slot="activity-bar"). Sidebar
// nav content goes in slot="sidebar". This component only lays regions
// out; it owns no navigation state and fetches nothing.
//
// FE-1.2 -- a "narrow desktop" media query automatically swaps the
// sidebar column to `--avl-layout-sidebar-width-collapsed` (previously
// a dead token, never read anywhere) instead of the full
// `--avl-layout-sidebar-width`. This is a *desktop* adaptive behavior,
// not a mobile breakpoint: the shell's `--avl-layout-shell-min-width`
// floor (60rem) is unchanged and still enforced, and the narrow
// threshold below only ever reclaims sidebar width for the workspace/
// inspector columns -- it never restructures the grid into a stacked
// mobile layout. CSS custom properties cannot appear inside an
// `@media` feature value (a platform limitation, not a choice made
// here), so the threshold itself is a plain literal, kept in sync by
// hand with the identical value in sidebar-nav.js's own media query --
// both must change together if this threshold is ever revisited.
import { AvlElement, defineComponent } from "./base-element.js";

const NARROW_DESKTOP_BREAKPOINT = "75rem";

export class AvlAppShell extends AvlElement {
  static get observedAttributes() {
    return ["inspector-collapsed", "sidebar-collapsed"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const inspectorCollapsed = this.hasAttribute("inspector-collapsed");
    // FE-4 -- an explicit manual override (see state/sidebar-view-model.js
    // and app/main.js's wiring of it), distinct from the narrow-desktop
    // media query below: this can force the compact rail at any width,
    // but never forces the wide column back open below the narrow-
    // desktop threshold -- see the `.shell[data-sidebar-view="icon"]`
    // rule's higher specificity over the plain `.shell` media-query rule.
    const sidebarCollapsed = this.hasAttribute("sidebar-collapsed");

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
      /* FE-3 -- sidebar/inspector are the shell's persistent chrome,
         sitting above the plain workspace canvas -- a subtle glass
         tint (background + border only, no shadow/blur) distinguishes
         them from the canvas without competing with the glass panels
         inside the workspace itself. */
      .sidebar {
        grid-area: sidebar;
        background: var(--avl-color-glass-surface);
        border-right: 1px solid var(--avl-color-glass-border);
        overflow-y: auto;
        overflow-x: hidden;
        /* FE-4 -- a handful of nav items plus the theme/view toggles can
           exceed the sidebar's height by a few pixels in a real browser
           chrome (not just in the narrow-desktop icon rail this was
           first reported against), which made overflow:auto paint a
           visible, permanent-looking scrollbar track for content that
           barely overflows at all. Scrolling itself stays available for
           a future sidebar with more items; only the always-visible
           track is suppressed, cross-browser. */
        scrollbar-width: none; /* Firefox */
        -ms-overflow-style: none; /* legacy Edge */
      }
      .sidebar::-webkit-scrollbar { width: 0; height: 0; } /* Chromium/WebKit */
      .workspace { grid-area: workspace; overflow: auto; padding: var(--avl-space-4); }
      .inspector {
        grid-area: inspector; width: var(--avl-layout-inspector-width);
        background: var(--avl-color-glass-surface);
        border-left: 1px solid var(--avl-color-glass-border); overflow: auto;
      }
      .inspector[data-collapsed="true"] { width: 0; overflow: hidden; border-left: none; }
      .activity-bar { grid-area: activity-bar; }

      /* FE-1.2 -- below the narrow-desktop threshold, reclaim sidebar
         width for the workspace/inspector columns by swapping to the
         collapsed sidebar-width token; the Inspector column and the
         60rem shell floor are both untouched, so nothing here can ever
         cause horizontal overflow or clip the Inspector. */
      @media (max-width: ${NARROW_DESKTOP_BREAKPOINT}) {
        .shell { grid-template-columns: var(--avl-layout-sidebar-width-collapsed) 1fr auto; }
      }

      /* FE-4 -- the manual icon-view override. Higher specificity than
         the bare ".shell" media-query rule above (an attribute selector
         adds a selector, not just a media condition), so this applies
         at any width once set, including on top of the narrow-desktop
         collapse it already agrees with. */
      .shell[data-sidebar-view="icon"] {
        grid-template-columns: var(--avl-layout-sidebar-width-collapsed) 1fr auto;
      }
    `;
    this.shadowRoot.appendChild(style);

    const shell = document.createElement("div");
    shell.className = "shell";
    shell.dataset.sidebarView = sidebarCollapsed ? "icon" : "full";

    const sidebar = document.createElement("div");
    sidebar.className = "sidebar";
    sidebar.appendChild(Object.assign(document.createElement("slot"), { name: "sidebar" }));

    const workspace = document.createElement("main");
    workspace.className = "workspace";
    workspace.appendChild(Object.assign(document.createElement("slot"), { name: "workspace" }));

    const inspector = document.createElement("div");
    inspector.className = "inspector";
    inspector.dataset.collapsed = String(inspectorCollapsed);
    // FE-1.8 -- matches workspace's <main> and the sidebar's own
    // internal <nav aria-label="Primary">: gives this region a
    // landmark screen-reader users can jump to directly, alongside
    // avl-inspector-router's own content heading (see that file).
    inspector.setAttribute("role", "complementary");
    inspector.setAttribute("aria-label", "Inspector");
    inspector.appendChild(Object.assign(document.createElement("slot"), { name: "inspector" }));

    const activityBar = document.createElement("div");
    activityBar.className = "activity-bar";
    activityBar.appendChild(Object.assign(document.createElement("slot"), { name: "activity-bar" }));

    shell.append(sidebar, workspace, inspector, activityBar);
    this.shadowRoot.appendChild(shell);
  }
}

defineComponent("avl-app-shell", AvlAppShell);
