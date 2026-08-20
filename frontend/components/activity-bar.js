// <avl-activity-bar> — bottom strip surfacing background task/pipeline
// activity at a glance. Consumes status vocabulary; never a duplicate
// status computation. Content driven entirely by attributes so it can be
// wired to identity/contracts.py's pipeline_status()/command_center()
// payloads without this component knowing about fetch/HTTP at all.
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";

export class AvlActivityBar extends AvlElement {
  static get observedAttributes() {
    return ["message", "domain", "state"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const message = this.getAttribute("message") || "No active work.";
    const domain = this.getAttribute("domain") || "core";
    const state = this.getAttribute("state") || "idle";

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .bar {
        display: flex; align-items: center; gap: var(--avl-space-3);
        height: var(--avl-layout-activity-bar-height);
        padding: 0 var(--avl-space-3);
        background: var(--avl-color-surface-activity-bar);
        border-top: 1px solid var(--avl-color-border-default);
        font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family);
        color: var(--avl-color-text-secondary);
      }
      .message { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    `;
    this.shadowRoot.appendChild(style);

    const bar = document.createElement("div");
    bar.className = "bar";
    bar.setAttribute("role", "status");

    const badge = document.createElement("avl-status-badge");
    badge.setAttribute("domain", domain);
    badge.setAttribute("state", state);

    const messageEl = document.createElement("span");
    messageEl.className = "message";
    messageEl.textContent = message;

    bar.append(badge, messageEl, document.createElement("slot"));
    this.shadowRoot.appendChild(bar);
  }
}

defineComponent("avl-activity-bar", AvlActivityBar);
