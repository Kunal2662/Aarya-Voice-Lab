// <avl-processing-feedback-form> — VL-D4 §28. Set `.targetId` (a
// processing history record id) and `.feedbackStore` (a
// state/review-model.js FeedbackStore — reused unmodified; feedback is
// feedback, regardless of what it's about). Records PROCESSING_FEEDBACK
// with a category drawn only from state/processing-model.js's
// ProcessingFeedbackCategory. Never converted into a training label —
// same disclosure components/feedback-form.js already carries.
import { AvlElement, defineComponent } from "./base-element.js";
import { FeedbackType } from "../state/review-model.js";
import { ProcessingFeedbackCategory } from "../state/processing-model.js";
import "./button.js";

const CATEGORY_LABELS = {
  [ProcessingFeedbackCategory.TOO_AGGRESSIVE]: "Too aggressive",
  [ProcessingFeedbackCategory.TOO_NOISY]: "Too noisy",
  [ProcessingFeedbackCategory.TOO_QUIET]: "Too quiet",
  [ProcessingFeedbackCategory.OVER_PROCESSED]: "Over-processed",
  [ProcessingFeedbackCategory.UNDER_PROCESSED]: "Under-processed",
  [ProcessingFeedbackCategory.BOUNDARY_INCORRECT]: "Boundary incorrect",
  [ProcessingFeedbackCategory.QUALITY_DEGRADED]: "Quality degraded",
  [ProcessingFeedbackCategory.GOOD_RESULT]: "Good result",
  [ProcessingFeedbackCategory.OTHER]: "Other",
};

export class AvlProcessingFeedbackForm extends AvlElement {
  set targetId(value) {
    this._targetId = value || null;
    if (this.isConnected) this._render();
  }

  set feedbackStore(value) {
    this._feedbackStore = value;
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
      empty.textContent = "Process this recording to leave feedback on the result.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const form = document.createElement("form");

    const categoryLabel = document.createElement("label");
    categoryLabel.textContent = "Category";
    const categorySelect = document.createElement("select");
    for (const value of Object.values(ProcessingFeedbackCategory)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = CATEGORY_LABELS[value] || value;
      categorySelect.appendChild(option);
    }
    categoryLabel.appendChild(categorySelect);
    form.appendChild(categoryLabel);

    const commentLabel = document.createElement("label");
    commentLabel.textContent = "Comment";
    const comment = document.createElement("textarea");
    comment.rows = 2;
    comment.setAttribute("aria-label", "Processing feedback comment");
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
        feedbackType: FeedbackType.PROCESSING_FEEDBACK,
        targetId: this._targetId,
        comment: comment.value || null,
        attributes: { category: categorySelect.value },
      });
      comment.value = "";
      status.textContent = `Recorded ${record.feedbackId} (${CATEGORY_LABELS[categorySelect.value]}).`;
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

defineComponent("avl-processing-feedback-form", AvlProcessingFeedbackForm);
