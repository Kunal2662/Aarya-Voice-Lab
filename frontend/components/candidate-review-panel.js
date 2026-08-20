// <avl-candidate-review-panel> — VL-D3 §12, §15, §22. The reviewer surface
// for one segment. Records ACCEPTED / REJECTED / NEEDS_REVIEW decisions
// with a reason code drawn only from the technical vocabulary
// (state/review-model.js CandidateReviewReason — quality, segmentation,
// overlap, duration, technical usability, other). Never asks "Is this
// Aarya?" / "Who is speaking?" / "Is this the target speaker?" — those
// questions, and any speaker-identity property, belong to a separate,
// later manual-review phase, not this one (VL-D3 §3). History is
// rendered append-only: every past decision for the segment stays
// listed, never overwritten in place, matching CandidateReviewStore's
// supersedes-based correction model.
import { AvlElement, defineComponent } from "./base-element.js";
import { CandidateReviewDecision, CandidateReviewReason } from "../state/review-model.js";
import "./status-badge.js";
import "./button.js";

const REASON_LABELS = {
  [CandidateReviewReason.QUALITY_ISSUE]: "Quality issue",
  [CandidateReviewReason.SEGMENTATION_ISSUE]: "Segmentation issue",
  [CandidateReviewReason.OVERLAP_ISSUE]: "Overlap issue",
  [CandidateReviewReason.DURATION_ISSUE]: "Duration issue",
  [CandidateReviewReason.TECHNICAL_USABILITY]: "Technical usability",
  [CandidateReviewReason.OTHER]: "Other",
};

export class AvlCandidateReviewPanel extends AvlElement {
  set segment(value) {
    this._segment = value || null;
    if (this.isConnected) this._render();
  }

  set reviewStore(store) {
    if (this._reviewStore) this._reviewStore.removeEventListener("change", this._onChange);
    this._reviewStore = store;
    this._onChange = () => this._render();
    if (this._reviewStore) this._reviewStore.addEventListener("change", this._onChange);
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._render();
  }

  disconnectedCallback() {
    if (this._reviewStore) this._reviewStore.removeEventListener("change", this._onChange);
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .segment-id { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      form { display: flex; flex-direction: column; gap: var(--avl-space-2); margin-top: var(--avl-space-2); }
      .decisions { display: flex; gap: var(--avl-space-1); flex-wrap: wrap; }
      label { display: flex; flex-direction: column; gap: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      select, textarea { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-sm); padding: var(--avl-space-1) var(--avl-space-2); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); }
      .history { margin-top: var(--avl-space-3); display: flex; flex-direction: column; gap: var(--avl-space-1); }
      .history h4 { margin: 0 0 var(--avl-space-1) 0; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; color: var(--avl-color-text-secondary); }
      .history-item { display: flex; gap: var(--avl-space-2); align-items: baseline; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .history-item .reason { color: var(--avl-color-text-secondary); }
      .history-item .when { color: var(--avl-color-text-muted); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._segment) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select a segment to review its technical candidate status.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const heading = document.createElement("div");
    heading.className = "segment-id";
    heading.textContent = `Reviewing ${this._segment.segmentId}`;
    this.shadowRoot.appendChild(heading);

    const form = document.createElement("form");

    const reasonLabel = document.createElement("label");
    reasonLabel.textContent = "Reason";
    const reasonSelect = document.createElement("select");
    for (const value of Object.values(CandidateReviewReason)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = REASON_LABELS[value] || value;
      reasonSelect.appendChild(option);
    }
    reasonLabel.appendChild(reasonSelect);
    form.appendChild(reasonLabel);

    const notesLabel = document.createElement("label");
    notesLabel.textContent = "Notes (technical usability only)";
    const notes = document.createElement("textarea");
    notes.rows = 2;
    notes.setAttribute("aria-label", "Review notes");
    notesLabel.appendChild(notes);
    form.appendChild(notesLabel);

    const decisions = document.createElement("div");
    decisions.className = "decisions";
    const decisionButtons = [
      [CandidateReviewDecision.ACCEPTED, "Accept", "primary"],
      [CandidateReviewDecision.REJECTED, "Reject", "danger"],
      [CandidateReviewDecision.NEEDS_REVIEW, "Needs review", "secondary"],
    ];
    for (const [decision, label, variant] of decisionButtons) {
      const button = document.createElement("avl-button");
      button.setAttribute("variant", variant);
      button.setAttribute("type", "button");
      button.textContent = label;
      button.addEventListener("click", () => {
        if (!this._reviewStore) return;
        const current = this._reviewStore.current(this._segment.segmentId);
        this._reviewStore.record({
          segmentId: this._segment.segmentId,
          decision,
          reasonCode: reasonSelect.value,
          notes: notes.value || null,
          supersedes: current ? current.reviewId : null,
        });
        this._announce(`Recorded ${label} for ${this._segment.segmentId}`);
      });
      decisions.appendChild(button);
    }
    form.appendChild(decisions);
    this.shadowRoot.appendChild(form);

    const historySection = document.createElement("div");
    historySection.className = "history";
    historySection.innerHTML = "<h4>Review history</h4>";
    const records = this._reviewStore ? this._reviewStore.history(this._segment.segmentId) : [];
    if (!records.length) {
      const none = document.createElement("p");
      none.className = "empty";
      none.textContent = "No review decisions recorded yet.";
      historySection.appendChild(none);
    } else {
      for (const record of records) {
        const item = document.createElement("div");
        item.className = "history-item";
        const badge = document.createElement("avl-status-badge");
        badge.setAttribute("domain", "candidate_review");
        badge.setAttribute("state", record.decision);
        const reason = document.createElement("span");
        reason.className = "reason";
        reason.textContent = REASON_LABELS[record.reasonCode] || record.reasonCode;
        const when = document.createElement("span");
        when.className = "when";
        when.textContent = record.reviewId;
        item.append(badge, reason, when);
        historySection.appendChild(item);
      }
    }
    this.shadowRoot.appendChild(historySection);
  }
}

defineComponent("avl-candidate-review-panel", AvlCandidateReviewPanel);
