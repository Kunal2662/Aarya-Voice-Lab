// <avl-voice-feedback> — records a listener's response to a preview.
// Emits `avl-feedback-submit` with a detail shaped exactly like
// aarya_voice_lab.identity.preview.PreviewFeedback's constructor fields
// (minus feedback_id/created_at, which the backend assigns). This
// component never writes feedback itself — no storage, no network call.
import { AvlElement, defineComponent } from "./base-element.js";
import "./button.js";

const OUTCOMES = ["accepted", "rejected", "regenerate", "uncertain"];

export class AvlVoiceFeedback extends AvlElement {
  static get observedAttributes() {
    return ["preview-id", "listener"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const previewId = this.getAttribute("preview-id") || "";
    const listener = this.getAttribute("listener") || "operator";

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .row { display: flex; gap: var(--avl-space-2); flex-wrap: wrap; }
      textarea {
        width: 100%; margin-top: var(--avl-space-2);
        font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family);
        border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-sm);
        padding: var(--avl-space-2); resize: vertical; background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary);
      }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("div");

    const row = document.createElement("div");
    row.className = "row";
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", "Preview feedback outcome");

    const comment = document.createElement("textarea");
    comment.rows = 2;
    comment.placeholder = "Optional comment (e.g. pacing, tone)";
    comment.setAttribute("aria-label", "Feedback comment");

    for (const outcome of OUTCOMES) {
      const button = document.createElement("avl-button");
      button.setAttribute("variant", outcome === "rejected" ? "danger" : "secondary");
      button.textContent = outcome.charAt(0).toUpperCase() + outcome.slice(1);
      button.addEventListener("click", () => {
        this.dispatchEvent(
          new CustomEvent("avl-feedback-submit", {
            detail: {
              preview_id: previewId,
              listener,
              outcome,
              listened: true,
              comment: comment.value || null,
              attributes: {},
            },
            bubbles: true,
            composed: true,
          }),
        );
      });
      row.appendChild(button);
    }

    wrapper.append(row, comment);
    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-voice-feedback", AvlVoiceFeedback);
