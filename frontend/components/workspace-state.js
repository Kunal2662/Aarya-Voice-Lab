// <avl-workspace-state state="loading|empty|error|blocked|ready" title="..." detail="...">
// The one place every workspace's non-happy-path renders through (VL-D1
// §5: "Each workspace needs... loading state, empty state, error state,
// blocked state where applicable"). When state="ready", only the default
// slot renders — the workspace's real content. Every other state renders
// a consistent, honest placeholder instead of the workspace guessing at
// its own empty/error copy.
import { AvlElement, defineComponent } from "./base-element.js";
import "./error-panel.js";

const STATES = ["loading", "empty", "error", "blocked", "ready"];

export class AvlWorkspaceState extends AvlElement {
  static get observedAttributes() {
    return ["state", "title", "detail"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const state = STATES.includes(this.getAttribute("state")) ? this.getAttribute("state") : "loading";
    const title = this.getAttribute("title") || "";
    const detail = this.getAttribute("detail") || "";

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .placeholder {
        display: flex; flex-direction: column; align-items: flex-start; gap: var(--avl-space-2);
        padding: var(--avl-space-6) var(--avl-space-4);
        color: var(--avl-color-text-secondary);
      }
      .placeholder-title { font: var(--avl-type-subheading-weight) var(--avl-type-subheading-size) / var(--avl-type-subheading-line-height) var(--avl-type-subheading-family); color: var(--avl-color-text-primary); }
      .spinner {
        width: 1rem; height: 1rem; border-radius: 999px;
        border: 2px solid var(--avl-color-border-default);
        border-top-color: var(--avl-color-brand-accent);
        animation: avl-spin var(--avl-duration-deliberate) linear infinite;
      }
      @keyframes avl-spin { to { transform: rotate(360deg); } }
      :host([data-state="ready"]) .placeholder { display: none; }
    `;
    this.shadowRoot.appendChild(style);
    this.dataset.state = state;

    if (state === "ready") {
      this.shadowRoot.appendChild(document.createElement("slot"));
      return;
    }

    const placeholder = document.createElement("div");
    placeholder.className = "placeholder";
    placeholder.setAttribute("role", state === "error" || state === "blocked" ? "alert" : "status");

    if (state === "loading") {
      const spinner = document.createElement("div");
      spinner.className = "spinner";
      spinner.setAttribute("aria-hidden", "true");
      placeholder.appendChild(spinner);
      const label = document.createElement("span");
      label.textContent = title || "Loading…";
      placeholder.appendChild(label);
      this._announce("Loading");
    } else if (state === "empty") {
      const label = document.createElement("div");
      label.className = "placeholder-title";
      label.textContent = title || "Nothing here yet";
      placeholder.appendChild(label);
      if (detail) {
        const detailEl = document.createElement("div");
        detailEl.textContent = detail;
        placeholder.appendChild(detailEl);
      }
    } else if (state === "blocked") {
      const label = document.createElement("div");
      label.className = "placeholder-title";
      label.textContent = title || "Blocked";
      placeholder.appendChild(label);
      if (detail) {
        const detailEl = document.createElement("div");
        detailEl.textContent = detail;
        placeholder.appendChild(detailEl);
      }
    } else if (state === "error") {
      const errorPanel = document.createElement("avl-error-panel");
      errorPanel.setAttribute("summary", title || "Something went wrong.");
      if (detail) errorPanel.setAttribute("detail", detail);
      placeholder.appendChild(errorPanel);
    }

    this.shadowRoot.appendChild(placeholder);
  }
}

defineComponent("avl-workspace-state", AvlWorkspaceState);
