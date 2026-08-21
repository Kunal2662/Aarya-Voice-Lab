// <avl-notice-banner tone="info|success|warning|danger" dismissible>
// Used for transient system notices; not a substitute for avl-error-panel,
// which handles progressive-disclosure error/recovery UX specifically.
import { AvlElement, defineComponent } from "./base-element.js";
import "./icon.js";

const TONES = ["info", "success", "warning", "danger"];

export class AvlNoticeBanner extends AvlElement {
  static get observedAttributes() {
    return ["tone", "dismissible"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const tone = TONES.includes(this.getAttribute("tone")) ? this.getAttribute("tone") : "info";
    const dismissible = this.hasAttribute("dismissible");

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .banner {
        display: flex; align-items: flex-start; gap: var(--avl-space-2);
        padding: var(--avl-space-3);
        border-radius: var(--avl-radius-md);
        border: 1px solid var(--avl-tone-border);
        background: var(--avl-tone-bg);
        color: var(--avl-color-text-primary);
      }
      .info    { --avl-tone-bg: var(--avl-color-state-info-subtle);    --avl-tone-border: var(--avl-color-state-info); }
      .success { --avl-tone-bg: var(--avl-color-state-success-subtle); --avl-tone-border: var(--avl-color-state-success); }
      .warning { --avl-tone-bg: var(--avl-color-state-warning-subtle); --avl-tone-border: var(--avl-color-state-warning); }
      .danger  { --avl-tone-bg: var(--avl-color-state-danger-subtle);  --avl-tone-border: var(--avl-color-state-danger); }
      .body { flex: 1; font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .close { background: none; border: none; cursor: pointer; color: inherit; padding: 0; display: inline-flex; }
    `;
    this.shadowRoot.appendChild(style);

    const banner = document.createElement("div");
    banner.className = `banner ${tone}`;
    banner.setAttribute("role", tone === "danger" || tone === "warning" ? "alert" : "status");

    const body = document.createElement("div");
    body.className = "body";
    body.appendChild(document.createElement("slot"));
    banner.appendChild(body);

    if (dismissible) {
      const close = document.createElement("button");
      close.className = "close";
      close.type = "button";
      close.setAttribute("aria-label", "Dismiss notice");
      // The button's own aria-label already carries the accessible
      // name, so the icon itself stays decorative/aria-hidden -- it
      // must never be announced a second time.
      const closeIcon = document.createElement("avl-icon");
      closeIcon.setAttribute("name", "close");
      closeIcon.setAttribute("size", "0.85rem");
      close.appendChild(closeIcon);
      close.addEventListener("click", () => {
        this.dispatchEvent(new CustomEvent("avl-dismiss", { bubbles: true, composed: true }));
        this.remove();
      });
      banner.appendChild(close);
    }

    this.shadowRoot.appendChild(banner);
  }
}

defineComponent("avl-notice-banner", AvlNoticeBanner);
