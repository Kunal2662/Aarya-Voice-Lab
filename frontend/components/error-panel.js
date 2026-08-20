// <avl-error-panel summary="..." detail="..." claude-action>
// Progressive disclosure per VL-D0 §22: a plain-language summary is
// always visible; technical detail is opt-in behind a disclosure control;
// an "Ask Claude" action (when claude-action is set) ties into the
// Command Center rather than duplicating its logic here.
import { AvlElement, defineComponent } from "./base-element.js";
import "./button.js";

export class AvlErrorPanel extends AvlElement {
  static get observedAttributes() {
    return ["summary", "detail", "claude-action"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const summary = this.getAttribute("summary") || "Something needs attention.";
    const detail = this.getAttribute("detail") || "";
    const claudeAction = this.getAttribute("claude-action");

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .panel {
        border: 1px solid var(--avl-color-state-danger);
        background: var(--avl-color-state-danger-subtle);
        border-radius: var(--avl-radius-md);
        padding: var(--avl-space-3);
      }
      .summary { font: var(--avl-type-body-weight) var(--avl-type-body-size) / var(--avl-type-body-line-height) var(--avl-type-body-family); margin: 0 0 var(--avl-space-2) 0; }
      details { margin-top: var(--avl-space-2); }
      summary { cursor: pointer; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      pre {
        white-space: pre-wrap; word-break: break-word;
        font: var(--avl-type-code-weight) var(--avl-type-code-size) / var(--avl-type-code-line-height) var(--avl-type-code-family);
        background: var(--avl-color-surface-sunken);
        padding: var(--avl-space-2); border-radius: var(--avl-radius-sm);
        margin: var(--avl-space-2) 0 0 0;
      }
      .actions { margin-top: var(--avl-space-3); display: flex; gap: var(--avl-space-2); }
    `;
    this.shadowRoot.appendChild(style);

    const panel = document.createElement("div");
    panel.className = "panel";
    panel.setAttribute("role", "alert");

    const summaryEl = document.createElement("p");
    summaryEl.className = "summary";
    summaryEl.textContent = summary;
    panel.appendChild(summaryEl);

    if (detail) {
      const details = document.createElement("details");
      const summaryToggle = document.createElement("summary");
      summaryToggle.textContent = "Technical details";
      const pre = document.createElement("pre");
      pre.textContent = detail;
      details.append(summaryToggle, pre);
      panel.appendChild(details);
    }

    if (claudeAction) {
      const actions = document.createElement("div");
      actions.className = "actions";
      const askButton = document.createElement("avl-button");
      askButton.setAttribute("variant", "secondary");
      askButton.textContent = "Ask Claude";
      askButton.addEventListener("click", () => {
        this.dispatchEvent(
          new CustomEvent("avl-ask-claude", {
            detail: { action: claudeAction, summary, detail },
            bubbles: true,
            composed: true,
          }),
        );
      });
      actions.appendChild(askButton);
      panel.appendChild(actions);
    }

    this.shadowRoot.appendChild(panel);
  }
}

defineComponent("avl-error-panel", AvlErrorPanel);
