// <avl-overlap-review-list> — VL-D3 §13. Lists overlap CANDIDATES for a
// recording (state/synthetic-fixtures.js syntheticOverlapCandidates()
// shape): start, end, duration, confidence, reason. Labels stay honest —
// "overlap candidate", never "confirmed multi-speaker audio" — because
// pipeline/overlap.py's own heuristic is explicitly weak evidence, not a
// verdict, and speaker identity is out of scope for this whole surface
// regardless (VL-D3 §3).
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";

export class AvlOverlapReviewList extends AvlElement {
  set overlapCandidates(value) {
    this._candidates = Array.isArray(value) ? value : [];
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._candidates = this._candidates || [];
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--avl-space-2); }
      li { border: 1px solid var(--avl-color-border-subtle); border-radius: var(--avl-radius-sm); padding: var(--avl-space-2); }
      .row { display: flex; justify-content: space-between; align-items: center; gap: var(--avl-space-2); }
      .span { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .reason { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-1); }
      .confidence { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-2); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._candidates.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No overlap candidates for this recording.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const list = document.createElement("ul");
    for (const candidate of this._candidates) {
      const item = document.createElement("li");

      const row = document.createElement("div");
      row.className = "row";
      const span = document.createElement("span");
      span.className = "span";
      span.textContent = `${candidate.segmentId} — ${candidate.start.toFixed(2)}s–${candidate.end.toFixed(2)}s (${candidate.duration.toFixed(2)}s)`;
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "overlap_status");
      badge.setAttribute("state", candidate.status);
      row.append(span, badge);
      item.appendChild(row);

      const confidence = document.createElement("div");
      confidence.className = "confidence";
      confidence.textContent =
        candidate.confidence != null
          ? `Confidence: ${candidate.confidence.toFixed(2)} (not a probability — a weak heuristic signal)`
          : "Confidence: not available";
      item.appendChild(confidence);

      const reason = document.createElement("div");
      reason.className = "reason";
      reason.textContent = `Reason: ${candidate.reason || "not available"}`;
      item.appendChild(reason);

      list.appendChild(item);
    }
    this.shadowRoot.appendChild(list);

    const note = document.createElement("p");
    note.className = "note";
    note.textContent =
      "Overlap candidate — a technical signal only. This surface never determines or implies who is speaking.";
    this.shadowRoot.appendChild(note);
  }
}

defineComponent("avl-overlap-review-list", AvlOverlapReviewList);
