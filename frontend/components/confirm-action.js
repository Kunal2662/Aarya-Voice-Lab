// <avl-confirm-action dialog-title="..." description="..." variant="danger" open>
// FE-1.1 -- a reusable Shadow-DOM confirmation-dialog primitive, closing
// the gap the FE-1 audit found: VL-D9's "Clear session data" control was
// the only confirmation flow in the app, hand-built once with raw
// buttons and no dialog semantics at all.
//
// This component owns dialog *chrome* only: role="dialog",
// aria-modal="true", an accessible title/description, Escape-to-cancel,
// a focus trap while open, and focus restored to whatever triggered it
// once closed. It never decides what "confirm" means -- the actual
// actions are supplied by the caller as light-DOM children with
// slot="actions", exactly like <avl-tabs>'s light-DOM <avl-tab>
// children. The recommended action element is <avl-button> (see this
// file's own tests, frontend/tests/confirm-action.test.mjs); the one
// documented exception is workspace-settings.js's Clear-session-data
// flow, which keeps plain native <button> elements for its Confirm/
// Cancel actions specifically because the existing, untouched VL-D9
// tests (session.test.mjs #4/#5/#6) query
// `settings.shadowRoot.querySelectorAll("button")` directly and must
// keep matching real <button> tags -- see that call site's own comment.
//
// Visibility is controlled by the boolean `open` attribute, exactly
// like the `warning.hidden` toggle this replaces: the host still
// decides *when* to show/hide it, this component only owns what
// happens *while* it is open. When closed, the shadow root renders
// nothing, which means slotted actions have no <slot> to project into
// and are correctly excluded from layout, hit-testing, and the tab
// order by the platform's own slot-assignment rules -- no extra
// `hidden`/`display:none` bookkeeping is needed on the actions
// themselves.
import { AvlElement, defineComponent } from "./base-element.js";
import "./button.js";

export class AvlConfirmAction extends AvlElement {
  static get observedAttributes() {
    return ["open", "dialog-title", "description", "variant"];
  }

  connectedCallback() {
    if (!this._titleId) {
      const uid = Math.random().toString(36).slice(2, 9);
      this._titleId = `avl-confirm-title-${uid}`;
      this._descId = `avl-confirm-desc-${uid}`;
    }
    this._render();
  }

  disconnectedCallback() {
    this._teardownOpenState();
  }

  attributeChangedCallback(name) {
    if (!this.isConnected) return;
    this._render();
    if (name === "open") {
      if (this.hasAttribute("open")) this._setupOpenState();
      else this._teardownOpenState();
    }
  }

  _setupOpenState() {
    // Whatever had focus the instant `open` was set is the trigger --
    // captured synchronously, before any focus movement below.
    this._returnFocusTo = document.activeElement;
    this._onKeydown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        this.dispatchEvent(new CustomEvent("avl-dialog-cancel", { bubbles: true, composed: true }));
        return;
      }
      if (event.key === "Tab") this._trapFocus(event);
    };
    this.shadowRoot.addEventListener("keydown", this._onKeydown);
    // Focus the dialog panel itself first, not an action button --
    // announces the dialog's role/title to assistive tech immediately
    // and avoids an accidental Enter-press landing on Confirm before the
    // description has been read.
    const panel = this.shadowRoot.querySelector(".panel");
    if (panel) panel.focus();
  }

  _teardownOpenState() {
    if (this._onKeydown) {
      this.shadowRoot.removeEventListener("keydown", this._onKeydown);
      this._onKeydown = null;
    }
    if (this._returnFocusTo && typeof this._returnFocusTo.focus === "function") {
      this._returnFocusTo.focus();
    }
    this._returnFocusTo = null;
  }

  // Resolves each slot="actions" child to the element that can actually
  // receive focus. A native <button>/<input>/etc. is its own target. A
  // custom element like <avl-button> is not itself focusable (no
  // tabindex, no delegatesFocus) -- its real focus target is the
  // focusable element inside its OWN shadow root. `document.activeElement`
  // still reports the outer custom-element host once that inner element
  // is focused (shadow encapsulation retargets activeElement to the
  // host), so `host` is what gets compared against, while `target` is
  // what focus() is actually called on.
  _focusableActions() {
    const assigned = Array.from(this.querySelectorAll('[slot="actions"]'));
    // a[href] (an anchor link), not bare [href] -- a bare [href] selector
    // would also match the shared-stylesheet <link href="..."> elements
    // every component's _linkSharedStyles() inserts into its own shadow
    // root, and querySelector would find that non-focusable <link>
    // before it ever reached the real <button>.
    const NATIVE_FOCUSABLE = 'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
    const resolved = [];
    for (const el of assigned) {
      if (el.matches(NATIVE_FOCUSABLE)) {
        resolved.push({ host: el, target: el });
      } else if (el.shadowRoot) {
        const inner = el.shadowRoot.querySelector(NATIVE_FOCUSABLE);
        if (inner) resolved.push({ host: el, target: inner });
      }
    }
    return resolved;
  }

  _trapFocus(event) {
    const actions = this._focusableActions();
    if (!actions.length) return;
    const first = actions[0];
    const last = actions[actions.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && active === first.host) {
      event.preventDefault();
      last.target.focus();
    } else if (!event.shiftKey && active === last.host) {
      event.preventDefault();
      first.target.focus();
    }
  }

  _render() {
    const isOpen = this.hasAttribute("open");
    const title = this.getAttribute("dialog-title") || "Confirm action";
    const description = this.getAttribute("description") || "";
    const danger = this.getAttribute("variant") === "danger";

    this.shadowRoot.innerHTML = "";
    if (!isOpen) return;
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .backdrop {
        position: fixed; inset: 0;
        background: rgba(0, 0, 0, 0.45);
        display: flex; align-items: center; justify-content: center;
        padding: var(--avl-space-4);
        z-index: 1000;
      }
      .panel {
        background: var(--avl-color-surface-raised);
        border: 1px solid ${danger ? "var(--avl-color-state-danger)" : "var(--avl-color-border-default)"};
        border-radius: var(--avl-radius-lg);
        padding: var(--avl-space-4);
        max-width: 26rem;
        width: 100%;
        box-shadow: 0 var(--avl-space-2) var(--avl-space-6) rgba(0, 0, 0, 0.3);
      }
      .panel:focus { outline: 2px solid var(--avl-color-border-focus); outline-offset: 2px; }
      h2 {
        margin: 0 0 var(--avl-space-2) 0;
        font: var(--avl-type-heading-weight) var(--avl-type-heading-size) / var(--avl-type-heading-line-height) var(--avl-type-heading-family);
        color: ${danger ? "var(--avl-color-state-danger)" : "var(--avl-color-text-primary)"};
      }
      p {
        margin: 0 0 var(--avl-space-3) 0;
        font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family);
        color: var(--avl-color-text-secondary);
      }
      .actions { display: flex; gap: var(--avl-space-2); justify-content: flex-end; }
      ::slotted(*) { font: inherit; }
    `;
    this.shadowRoot.appendChild(style);

    const backdrop = document.createElement("div");
    backdrop.className = "backdrop";
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) {
        this.dispatchEvent(new CustomEvent("avl-dialog-cancel", { bubbles: true, composed: true }));
      }
    });

    const panel = document.createElement("div");
    panel.className = "panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-labelledby", this._titleId);
    if (description) panel.setAttribute("aria-describedby", this._descId);
    panel.tabIndex = -1;

    const heading = document.createElement("h2");
    heading.id = this._titleId;
    heading.textContent = title;
    panel.appendChild(heading);

    if (description) {
      const desc = document.createElement("p");
      desc.id = this._descId;
      desc.textContent = description;
      panel.appendChild(desc);
    }

    const actions = document.createElement("div");
    actions.className = "actions";
    const slot = document.createElement("slot");
    slot.name = "actions";
    actions.appendChild(slot);
    panel.appendChild(actions);

    backdrop.appendChild(panel);
    this.shadowRoot.appendChild(backdrop);
  }
}

defineComponent("avl-confirm-action", AvlConfirmAction);
