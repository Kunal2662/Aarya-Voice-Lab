// <avl-segment-timeline> — VL-D3 §10–§11. Lists a recording's segments
// (state/synthetic-fixtures.js syntheticSegments() shape): id, start,
// end, duration, speech/silence kind, quality state, candidate state.
// Selecting a row fires a "select" CustomEvent carrying the segment so a
// host (the Inspector) can react — this component never touches
// Inspector/selection state itself. Boundaries are display-only: nothing
// here can rewrite source audio; a correction is only ever a new
// candidate-review record layered on top (see review-model.js), never an
// edit to a segment's own start/end.
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";

export class AvlSegmentTimeline extends AvlElement {
  set segments(value) {
    this._segments = Array.isArray(value) ? value : [];
    this._selectedId = null;
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._segments = this._segments || [];
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      table { width: 100%; border-collapse: collapse; font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); }
      th { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; }
      tr[data-selectable] { cursor: pointer; }
      tr[data-selectable]:hover { background: var(--avl-color-surface-sunken); }
      tr[aria-selected="true"] { background: var(--avl-color-surface-sunken); outline: 2px solid var(--avl-color-brand-accent); outline-offset: -2px; }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._segments.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No segments for this recording.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML =
      "<tr><th>Segment</th><th>Start</th><th>End</th><th>Duration</th><th>Kind</th><th>Quality</th><th>Candidate</th></tr>";
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const segment of this._segments) {
      const row = document.createElement("tr");
      if (segment.kind === "speech") {
        row.dataset.selectable = "";
        row.tabIndex = 0;
        row.setAttribute("role", "button");
        row.setAttribute("aria-selected", String(segment.segmentId === this._selectedId));
        const select = () => {
          this._selectedId = segment.segmentId;
          this._render();
          this.dispatchEvent(new CustomEvent("select", { detail: { segment }, bubbles: true, composed: true }));
        };
        row.addEventListener("click", select);
        row.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            select();
          }
        });
      }

      const duration = (segment.end - segment.start).toFixed(2);
      row.innerHTML = `
        <td>${segment.segmentId}</td>
        <td>${segment.start.toFixed(2)}s</td>
        <td>${segment.end.toFixed(2)}s</td>
        <td>${duration}s</td>
        <td>${segment.kind}</td>
      `;

      const qualityCell = document.createElement("td");
      if (segment.qualityState) {
        const qualityBadge = document.createElement("avl-status-badge");
        qualityBadge.setAttribute("domain", "quality_decision");
        qualityBadge.setAttribute("state", segment.qualityState);
        qualityCell.appendChild(qualityBadge);
      } else {
        qualityCell.textContent = "—";
      }
      row.appendChild(qualityCell);

      const candidateCell = document.createElement("td");
      if (segment.candidateState) {
        const candidateBadge = document.createElement("avl-status-badge");
        candidateBadge.setAttribute("domain", "candidate_review");
        candidateBadge.setAttribute("state", segment.candidateState);
        candidateCell.appendChild(candidateBadge);
      } else {
        candidateCell.textContent = "—";
      }
      row.appendChild(candidateCell);

      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    this.shadowRoot.appendChild(table);
  }
}

defineComponent("avl-segment-timeline", AvlSegmentTimeline);
