// <avl-ab-comparison> — VL-D5 §16. Set `.left`/`.right` to
// PreviewArtifact-shaped dicts (or null) and optionally `.labels`
// (default ["A", "B"]) and `.feedbackStore` for per-side feedback. Two
// avl-voice-player instances side by side, a Swap control, and a
// metadata-only comparison table built from
// state/generation-model.js's buildAbComparison() — duration/sample
// rate/kind/synthetic-flag only. **Never computes or claims acoustic
// similarity** — that requires a validated evaluation engine this
// project does not have yet (reserved for a future phase).
import { AvlElement, defineComponent } from "./base-element.js";
import { buildAbComparison } from "../state/generation-model.js";
import "./voice-player.js";
import "./voice-feedback.js";
import "./button.js";

export class AvlAbComparison extends AvlElement {
  set left(value) {
    this._left = value || null;
    if (this.isConnected) this._render();
  }

  set right(value) {
    this._right = value || null;
    if (this.isConnected) this._render();
  }

  set labels(value) {
    this._labels = Array.isArray(value) && value.length === 2 ? value : ["A", "B"];
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._labels = this._labels || ["A", "B"];
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .toolbar { margin-bottom: var(--avl-space-2); }
      .comparison { display: grid; grid-template-columns: 1fr 1fr; gap: var(--avl-space-4); }
      .column { display: flex; flex-direction: column; gap: var(--avl-space-2); }
      .label { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); text-transform: uppercase; }
      table { width: 100%; border-collapse: collapse; margin-top: var(--avl-space-3); }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-2); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    const toolbar = document.createElement("div");
    toolbar.className = "toolbar";
    const swap = document.createElement("avl-button");
    swap.setAttribute("variant", "secondary");
    swap.textContent = "Swap A / B";
    swap.addEventListener("click", () => {
      const previousLeft = this._left;
      this._left = this._right;
      this._right = previousLeft;
      this._render();
    });
    toolbar.appendChild(swap);
    this.shadowRoot.appendChild(toolbar);

    const comparison = document.createElement("div");
    comparison.className = "comparison";
    for (const [index, artifact] of [this._left, this._right].entries()) {
      const column = document.createElement("div");
      column.className = "column";
      const label = document.createElement("span");
      label.className = "label";
      label.textContent = this._labels[index];
      const player = document.createElement("avl-voice-player");
      player.artifact = artifact;
      column.append(label, player);
      if (artifact) {
        const feedback = document.createElement("avl-voice-feedback");
        feedback.setAttribute("preview-id", artifact.preview_id);
        feedback.setAttribute("listener", "operator");
        feedback.addEventListener("avl-feedback-submit", (event) => {
          if (this._feedbackStore) {
            this._feedbackStore.record({ ...event.detail, listened: true });
          }
        });
        column.appendChild(feedback);
      }
      comparison.appendChild(column);
    }
    this.shadowRoot.appendChild(comparison);

    if (!this._left && !this._right) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select two generated outputs to compare.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const ab = buildAbComparison(this._left, this._right);
    const table = document.createElement("table");
    const tbody = document.createElement("tbody");
    for (const [key, value] of [
      ["Duration difference (s)", ab.duration_diff_seconds ?? "—"],
      ["Sample rate matches", String(ab.sample_rate_match)],
      ["Kind matches", String(ab.kind_match)],
      ["Both synthetic", String(ab.both_synthetic)],
    ]) {
      const row = document.createElement("tr");
      row.innerHTML = `<td>${key}</td><td>${value}</td>`;
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    this.shadowRoot.appendChild(table);

    const note = document.createElement("p");
    note.className = "note";
    note.textContent = ab.note;
    this.shadowRoot.appendChild(note);
  }

  set feedbackStore(value) {
    this._feedbackStore = value;
  }
}

defineComponent("avl-ab-comparison", AvlAbComparison);
