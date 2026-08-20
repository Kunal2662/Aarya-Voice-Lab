// <avl-feedback-form> — VL-D3 §26. Records structured feedback
// (QUALITY_FEEDBACK / SEGMENT_FEEDBACK / CANDIDATE_FEEDBACK /
// PLAYBACK_FEEDBACK) against a target object via
// state/review-model.js's FeedbackStore. This is raw operator input for
// a future calibration engine to consume — it is NEVER converted into a
// training label here or anywhere in VL-D3 (see pipeline/calibration_prep.py,
// which only ever counts feedback, never scores it).
import { AvlElement, defineComponent } from "./base-element.js";
import { FeedbackType } from "../state/review-model.js";
import "./button.js";

const TYPE_LABELS = {
  [FeedbackType.QUALITY_FEEDBACK]: "Quality feedback",
  [FeedbackType.SEGMENT_FEEDBACK]: "Segment feedback",
  [FeedbackType.CANDIDATE_FEEDBACK]: "Candidate feedback",
  [FeedbackType.PLAYBACK_FEEDBACK]: "Playback feedback",
};

export class AvlFeedbackForm extends AvlElement {
  set targetId(value) {
    this._targetId = value || null;
    if (this.isConnected) this._render();
  }

  set feedbackStore(store) {
    this._feedbackStore = store;
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      form { display: flex; flex-direction: column; gap: var(--avl-space-2); }
      label { display: flex; flex-direction: column; gap: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      select, textarea { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-sm); padding: var(--avl-space-1) var(--avl-space-2); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); }
      .status { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._targetId) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select a recording or segment to attach feedback to.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const form = document.createElement("form");

    const typeLabel = document.createElement("label");
    typeLabel.textContent = "Feedback type";
    const typeSelect = document.createElement("select");
    for (const value of Object.values(FeedbackType)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = TYPE_LABELS[value] || value;
      typeSelect.appendChild(option);
    }
    typeLabel.appendChild(typeSelect);
    form.appendChild(typeLabel);

    const commentLabel = document.createElement("label");
    commentLabel.textContent = "Comment";
    const comment = document.createElement("textarea");
    comment.rows = 2;
    comment.setAttribute("aria-label", "Feedback comment");
    commentLabel.appendChild(comment);
    form.appendChild(commentLabel);

    const submit = document.createElement("avl-button");
    submit.setAttribute("variant", "primary");
    submit.setAttribute("type", "button");
    submit.textContent = "Submit feedback";

    const status = document.createElement("p");
    status.className = "status";
    status.setAttribute("role", "status");

    submit.addEventListener("click", () => {
      if (!this._feedbackStore) return;
      const record = this._feedbackStore.record({
        feedbackType: typeSelect.value,
        targetId: this._targetId,
        comment: comment.value || null,
      });
      comment.value = "";
      status.textContent = `Recorded ${record.feedbackId} for ${this._targetId}.`;
      this._announce(status.textContent);
    });
    form.appendChild(submit);
    form.appendChild(status);
    this.shadowRoot.appendChild(form);

    const note = document.createElement("p");
    note.className = "note";
    note.textContent = "Feedback is stored for future calibration review only — it is never used as a training label.";
    this.shadowRoot.appendChild(note);
  }
}

defineComponent("avl-feedback-form", AvlFeedbackForm);
