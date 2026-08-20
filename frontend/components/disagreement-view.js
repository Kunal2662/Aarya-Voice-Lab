// <avl-disagreement-view> -- VL-D6. Set `.summary` to a
// state/evaluation-model.js summarizeOutputEvaluations()-shaped object.
// Surfaces exactly which dimensions reviewers disagree on and the raw
// score spread behind that call -- never a synthesized "why", never a
// significance claim. Disagreement is only ever asserted when the
// summary itself says has_disagreement (>=2 evaluations and a
// >=DISAGREEMENT_SPREAD_THRESHOLD score spread on that dimension); with
// fewer samples this renders the honest "too few reviewers" state
// instead of silently showing nothing.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlDisagreementView extends AvlElement {
  set summary(value) {
    this._summary = value || null;
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .panel { display: flex; flex-direction: column; gap: var(--avl-space-2); }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      th { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; }
      .flagged { color: var(--avl-color-state-warning); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    const summary = this._summary;
    if (!summary) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select an output to view reviewer disagreement.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const panel = document.createElement("div");
    panel.className = "panel";

    const note = document.createElement("p");
    note.className = "note";
    note.textContent = summary.note;
    panel.appendChild(note);

    const dimensionEntries = Object.entries(summary.dimension_statistics || {}).filter(([, stats]) => stats.sample_count > 0);
    if (!dimensionEntries.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No scored dimensions yet.";
      panel.appendChild(empty);
      this.shadowRoot.appendChild(panel);
      return;
    }

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Dimension</th><th>Samples</th><th>Min</th><th>Max</th><th>Spread</th><th>Disagreement</th></tr>";
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const [dimension, stats] of dimensionEntries) {
      const flagged = (summary.disagreement_dimensions || []).includes(dimension);
      const row = document.createElement("tr");
      if (flagged) row.className = "flagged";
      const spread = stats.min_score != null && stats.max_score != null ? stats.max_score - stats.min_score : null;
      row.innerHTML = `
        <td>${dimension}</td>
        <td>${stats.sample_count}</td>
        <td>${stats.min_score ?? "—"}</td>
        <td>${stats.max_score ?? "—"}</td>
        <td>${spread ?? "—"}</td>
        <td>${flagged ? "Yes" : stats.sample_count < 2 ? "too few reviewers" : "No"}</td>
      `;
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    panel.appendChild(table);

    this.shadowRoot.appendChild(panel);
  }
}

defineComponent("avl-disagreement-view", AvlDisagreementView);
