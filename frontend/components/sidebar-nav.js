// <avl-sidebar-nav> wrapping <avl-sidebar-item icon="..." label="..." href="#..." active>
// Only a handful of destinations exist as of VL-D0; most are placeholders
// pointing at future milestones (VL-D1+), rendered disabled rather than
// omitted, so the shell's shape is visible without pretending those
// screens exist yet.
import { AvlElement, defineComponent } from "./base-element.js";
import "./icon.js";

// FE-1.2 -- kept identical to app-shell.js's own NARROW_DESKTOP_BREAKPOINT
// by hand (CSS custom properties cannot appear inside an @media feature
// value, so this can't be shared via a token); both must change together.
const NARROW_DESKTOP_BREAKPOINT = "75rem";

export class AvlSidebarItem extends HTMLElement {}
defineComponent("avl-sidebar-item", AvlSidebarItem);

export class AvlSidebarNav extends AvlElement {
  static get observedAttributes() {
    return ["collapsed"];
  }

  connectedCallback() {
    this.refresh();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  /** Re-read light-DOM <avl-sidebar-item> children and re-render — call
   * after changing one's `active`/`planned` attribute programmatically
   * (VL-D1's router does this on every navigation). */
  refresh() {
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

      /* FE-1.2 -- matches app-shell.js's own narrow-desktop collapse:
         the visible label text and the "planned" tag hide, the icon
         (already aria-hidden, decorative) stays visible, and the
         button's real accessible name/tooltip (set unconditionally
         below, not only here) keeps working via aria-label + title --
         collapsing the *visible* label must never remove the
         *accessible* one. */
      @media (max-width: ${NARROW_DESKTOP_BREAKPOINT}) {
        .item { justify-content: center; }
        .label-text, .planned { display: none; }
      }

      /* FE-4 -- manual icon-view override (see state/sidebar-view-model.js);
         same rule shape as the media query above, kept in sync with
         app-shell.js's own [data-sidebar-view="icon"] rule by hand, same
         as the two components' narrow-desktop breakpoint already is. */
      :host([collapsed]) .item { justify-content: center; }
      :host([collapsed]) .label-text, :host([collapsed]) .planned { display: none; }
    `;
    this.shadowRoot.appendChild(style);

    const nav = document.createElement("nav");
    nav.setAttribute("aria-label", "Primary");

    for (const item of this._items) {
      const active = item.hasAttribute("active");
      const planned = item.hasAttribute("planned");
      const label = item.getAttribute("label") || "";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "item";
      if (active) button.setAttribute("aria-current", "page");
      if (planned) button.disabled = true;
      // FE-1.2 -- set unconditionally, not only when the sidebar is
      // visually collapsed: aria-label always fully determines the
      // accessible name (it doesn't merely supplement visible text), so
      // this keeps the accessible name identical and correct in both
      // the expanded and collapsed states rather than having it change
      // shape at the breakpoint. `title` adds the native OS tooltip,
      // which matters once the visible label text is hidden.
      button.setAttribute("aria-label", label);
      button.title = label;

      // FE-1.3 -- icon="..." now names a real inline-SVG icon (see
      // components/icon.js's catalogue) instead of a raw Unicode glyph.
      // <avl-icon> defaults to aria-hidden itself; the wrapping <span>
      // keeps the same layout/hidden contract this replaces.
      const icon = document.createElement("span");
      icon.className = "icon";
      icon.setAttribute("aria-hidden", "true");
      const iconEl = document.createElement("avl-icon");
      iconEl.setAttribute("name", item.getAttribute("icon") || "");
      icon.appendChild(iconEl);

      const labelEl = document.createElement("span");
      labelEl.className = "label-text";
      labelEl.textContent = label;

      button.append(icon, labelEl);

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

    // FE-4 -- a default slot for light-DOM children that aren't
    // <avl-sidebar-item> (e.g. main.js's <avl-theme-toggle> and the new
    // <avl-sidebar-view-toggle> below). Discovered while adding the
    // latter: without a slot here, any such child exists in the DOM but
    // is never actually displayed (no box, not assigned anywhere) --
    // real pre-existing dead UI, not something introduced by this
    // change. <avl-sidebar-item> children still render only through the
    // explicit button-building loop above, never through this slot, so
    // this can't double-render an item.
    this.shadowRoot.appendChild(document.createElement("slot"));
  }
}

defineComponent("avl-sidebar-nav", AvlSidebarNav);
