// <avl-preview-feedback-form> — VL-D5 §15, §21, §22. Set `.artifact` (a
// PreviewArtifact-shaped dict) and `.feedbackStore` (a
// state/generation-model.js PreviewFeedbackStore). Embeds its own
// avl-voice-player so Accept/Reject stay gated on having actually
// pressed Play first, listening for the bubbling `avl-playback-started`
// event avl-audio-player now dispatches (VL-D5 §14) -- this mirrors
// pipeline.preview_feedback.record_preview_feedback()'s
// UnlistenedFeedbackError exactly. Regenerate/Uncertain never require
// listening first, same as the backend. Feedback is never converted
// directly into a training label (§21) -- same disclosure every other
// feedback form in this app already carries.
import { AvlElement, defineComponent } from "./base-element.js";
import { PreviewFeedbackCategory, PreviewFeedbackOutcome, UnlistenedFeedbackError } from "../state/generation-model.js";
import "./voice-player.js";
import "./button.js";

const CATEGORY_LABELS = {
  [PreviewFeedbackCategory.VOICE_QUALITY]: "Voice quality",
  [PreviewFeedbackCategory.NATURALNESS]: "Naturalness",
  [PreviewFeedbackCategory.CLARITY]: "Clarity",
  [PreviewFeedbackCategory.PRONUNCIATION]: "Pronunciation",
  [PreviewFeedbackCategory.PACE]: "Pace",
  [PreviewFeedbackCategory.PITCH]: "Pitch",
  [PreviewFeedbackCategory.PROSODY]: "Prosody",
  [PreviewFeedbackCategory.STYLE]: "Style",
  [PreviewFeedbackCategory.ARTIFACTS]: "Artifacts",
  [PreviewFeedbackCategory.OVERALL]: "Overall",
};

const OUTCOME_LABELS = {
  [PreviewFeedbackOutcome.ACCEPTED]: "Accept",
  [PreviewFeedbackOutcome.REJECTED]: "Reject",
  [PreviewFeedbackOutcome.REGENERATE]: "Needs improvement (regenerate)",
  [PreviewFeedbackOutcome.UNCERTAIN]: "Uncertain",
};

const REQUIRES_LISTEN = new Set([PreviewFeedbackOutcome.ACCEPTED, PreviewFeedbackOutcome.REJECTED]);

export class AvlPreviewFeedbackForm extends AvlElement {
  set artifact(value) {
    this._artifact = value || null;
    this._listened = false;
    this._statusMessage = null;
    if (this.isConnected) this._render();
  }

  set feedbackStore(value) {
    this._feedbackStore = value;
  }

  set listener(value) {
    this._listener = value || "operator";
  }

  connectedCallback() {
    this._listened = this._listened || false;
    this._listener = this._listener || "operator";
    this._render();
  }

  _updateListenGate() {
    const gate = this.shadowRoot.querySelector(".gate");
    if (gate) {
      gate.textContent = "Listened — Accept/Reject are available.";
    }
    for (const button of this.shadowRoot.querySelectorAll("avl-button[data-listen-gated]")) {
      button.removeAttribute("disabled");
    }
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .row { display: flex; gap: var(--avl-space-2); flex-wrap: wrap; margin-top: var(--avl-space-2); }
      label { display: flex; flex-direction: column; gap: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); margin-top: var(--avl-space-2); }
      select, textarea, input { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-sm); padding: var(--avl-space-1) var(--avl-space-2); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); }
      .gate { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-1); }
      .status { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); color: var(--avl-color-text-secondary); margin-top: var(--avl-space-1); }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-2); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._artifact) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Generate a preview to leave feedback on the result.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const player = document.createElement("avl-voice-player");
    player.artifact = this._artifact;
    player.addEventListener("avl-playback-started", () => {
      if (this._listened) return;
      this._listened = true;
      // Update the gate text and button-disabled state in place rather
      // than calling _render(): a full re-render here would tear down
      // and recreate this very player mid-playback (destroying the
      // <audio> element the browser just started fetching), which is
      // exactly the kind of blob-URL race VL-D5 §14's audio-player.js
      // fix already had to guard against once.
      this._updateListenGate();
    });
    this.shadowRoot.appendChild(player);

    const gate = document.createElement("p");
    gate.className = "gate";
    gate.textContent = this._listened
      ? "Listened — Accept/Reject are available."
      : "Press Play above before Accept/Reject become available (Regenerate/Uncertain don't require listening first).";
    this.shadowRoot.appendChild(gate);

    const categoryLabel = document.createElement("label");
    categoryLabel.textContent = "Category";
    const categorySelect = document.createElement("select");
    categorySelect.setAttribute("aria-label", "Feedback category");
    for (const value of Object.values(PreviewFeedbackCategory)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = CATEGORY_LABELS[value] || value;
      categorySelect.appendChild(option);
    }
    categoryLabel.appendChild(categorySelect);
    this.shadowRoot.appendChild(categoryLabel);

    const ratingLabel = document.createElement("label");
    ratingLabel.textContent = "Rating (1-5)";
    const ratingInput = document.createElement("input");
    ratingInput.type = "number";
    ratingInput.min = "1";
    ratingInput.max = "5";
    ratingInput.setAttribute("aria-label", "Rating, 1 to 5");
    ratingLabel.appendChild(ratingInput);
    this.shadowRoot.appendChild(ratingLabel);

    const commentLabel = document.createElement("label");
    commentLabel.textContent = "Comment";
    const comment = document.createElement("textarea");
    comment.rows = 2;
    comment.setAttribute("aria-label", "Feedback comment");
    commentLabel.appendChild(comment);
    this.shadowRoot.appendChild(commentLabel);

    const status = document.createElement("p");
    status.className = "status";
    status.setAttribute("role", "status");
    status.textContent = this._statusMessage || "";

    const row = document.createElement("div");
    row.className = "row";
    for (const outcome of Object.values(PreviewFeedbackOutcome)) {
      const button = document.createElement("avl-button");
      const gated = REQUIRES_LISTEN.has(outcome) && !this._listened;
      button.setAttribute("variant", outcome === PreviewFeedbackOutcome.REJECTED ? "danger" : "secondary");
      button.textContent = OUTCOME_LABELS[outcome] || outcome;
      if (REQUIRES_LISTEN.has(outcome)) button.dataset.listenGated = "";
      if (gated) button.setAttribute("disabled", "");
      button.addEventListener("click", () => {
        if (!this._feedbackStore) return;
        try {
          const record = this._feedbackStore.record({
            preview_id: this._artifact.preview_id,
            listener: this._listener,
            outcome,
            listened: this._listened,
            category: categorySelect.value || null,
            rating: ratingInput.value ? Number(ratingInput.value) : null,
            comment: comment.value || null,
          });
          this._statusMessage = `Recorded ${record.feedback_id} (${OUTCOME_LABELS[outcome]}).`;
        } catch (err) {
          this._statusMessage =
            err instanceof UnlistenedFeedbackError ? err.message : `Could not record feedback: ${err.message || err}`;
        }
        this._announce(this._statusMessage);
        this._render();
      });
      row.appendChild(button);
    }
    this.shadowRoot.appendChild(row);
    this.shadowRoot.appendChild(status);

    const note = document.createElement("p");
    note.className = "note";
    note.textContent = "Feedback is stored for future calibration review only — it is never converted into a training label.";
    this.shadowRoot.appendChild(note);
  }
}

defineComponent("avl-preview-feedback-form", AvlPreviewFeedbackForm);
