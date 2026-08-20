// <avl-aggregated-results-panel> -- VL-D6. Set `.summary` to a
// state/evaluation-model.js summarizeOutputEvaluations()-shaped object
// (mean/median/variance/min/max per dimension, completed/cannot-judge
// counts). Renders exactly what the summary computed -- variance is
// shown as "n/a (needs >=2 samples)" rather than 0 when undefined, and
// the panel never adds a confidence interval or significance claim the
// aggregation function itself didn't produce.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlAggregatedResultsPanel extends AvlElement {
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
      .counts { display: flex; gap: var(--avl-space-4); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      .counts span { color: var(--avl-color-text-secondary); }
      .counts strong { color: var(--avl-color-text-primary); }
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      th { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    const summary = this._summary;
    if (!summary) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select an output to view aggregated results.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const panel = document.createElement("div");
    panel.className = "panel";

    const counts = document.createElement("div");
    counts.className = "counts";
    counts.innerHTML = `
      <span>Evaluations: <strong>${summary.evaluation_count}</strong></span>
      <span>Reviewers: <strong>${summary.reviewer_count}</strong></span>
      <span>Completed: <strong>${summary.completed_count}</strong></span>
      <span>Cannot judge: <strong>${summary.cannot_judge_count}</strong></span>
    `;
    panel.appendChild(counts);

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Dimension</th><th>N</th><th>Mean</th><th>Median</th><th>Variance</th><th>Range</th></tr>";
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const [dimension, stats] of Object.entries(summary.dimension_statistics || {})) {
      const row = document.createElement("tr");
      const range = stats.min_score != null && stats.max_score != null ? `${stats.min_score}–${stats.max_score}` : "—";
      row.innerHTML = `
        <td>${dimension}</td>
        <td>${stats.sample_count}</td>
        <td>${stats.mean ?? "—"}</td>
        <td>${stats.median ?? "—"}</td>
        <td>${stats.variance !== null ? stats.variance : "n/a (needs ≥ 2 samples)"}</td>
        <td>${range}</td>
      `;
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    panel.appendChild(table);

    const note = document.createElement("p");
    note.className = "note";
    note.textContent = summary.note;
    panel.appendChild(note);

    this.shadowRoot.appendChild(panel);
  }
}

defineComponent("avl-aggregated-results-panel", AvlAggregatedResultsPanel);
