// <avl-evaluation-history-panel> -- VL-D6. Set `.outputId` and
// `.evaluationStore`. Lists every evaluation ever recorded for that
// output, oldest first -- append-only, so a second reviewer's
// disagreeing score stays listed alongside the first rather than
// replacing it (mirrors avl-generation-history-panel.js's "regeneration
// never overwrites" pattern, applied to reviewer records instead of
// generation attempts).
import { AvlElement, defineComponent } from "./base-element.js";
import { EvaluationCompletionState } from "../state/evaluation-model.js";
import "./status-badge.js";

export class AvlEvaluationHistoryPanel extends AvlElement {
  set outputId(value) {
    this._outputId = value || null;
    if (this.isConnected) this._render();
  }

  set evaluationStore(value) {
    if (this._evaluationStore) this._evaluationStore.removeEventListener("change", this._onChange);
    this._evaluationStore = value;
    if (value) {
      this._onChange = () => this._render();
      value.addEventListener("change", this._onChange);
    }
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._render();
  }

  disconnectedCallback() {
    if (this._evaluationStore) this._evaluationStore.removeEventListener("change", this._onChange);
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--avl-space-2); }
      li { border: 1px solid var(--avl-color-border-subtle); border-radius: var(--avl-radius-sm); padding: var(--avl-space-2); }
      /* FE-1.5 -- .row replaced by the shared avl-row avl-row--center utilities (css/base.css). */
      .reviewer { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); color: var(--avl-color-text-primary); }
      .meta { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-1); }
      .scores { display: flex; flex-wrap: wrap; gap: var(--avl-space-2); margin-top: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      .comment { margin-top: var(--avl-space-1); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._evaluationStore || !this._outputId) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select an output to view its evaluation history.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const records = this._evaluationStore.evaluationsFor(this._outputId);
    if (!records.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No evaluations for this output yet.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const list = document.createElement("ul");
    for (const record of records) {
      const item = document.createElement("li");

      const row = document.createElement("div");
      row.className = "avl-row avl-row--center";
      const reviewer = document.createElement("span");
      reviewer.className = "reviewer";
      reviewer.textContent = record.reviewer;
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "evaluation_completion_state");
      badge.setAttribute("state", record.completion_state || EvaluationCompletionState.IN_PROGRESS);
      row.append(reviewer, badge);
      item.appendChild(row);

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = `${record.evaluation_id} — listened: ${record.listening.listened} — confidence: ${record.confidence ?? "unset"} — ${record.created_at}`;
      item.appendChild(meta);

      const scoreEntries = Object.entries(record.dimension_scores || {});
      if (scoreEntries.length) {
        const scores = document.createElement("div");
        scores.className = "scores";
        for (const [dimension, score] of scoreEntries) {
          const span = document.createElement("span");
          span.textContent = `${dimension}: ${score}`;
          scores.appendChild(span);
        }
        item.appendChild(scores);
      }

      if (record.cannot_judge_dimensions && record.cannot_judge_dimensions.length) {
        const cannotJudge = document.createElement("div");
        cannotJudge.className = "scores";
        cannotJudge.textContent = `Cannot judge: ${record.cannot_judge_dimensions.join(", ")}`;
        item.appendChild(cannotJudge);
      }

      if (record.comment) {
        const comment = document.createElement("div");
        comment.className = "comment";
        comment.textContent = record.comment;
        item.appendChild(comment);
      }

      list.appendChild(item);
    }
    this.shadowRoot.appendChild(list);
  }
}

defineComponent("avl-evaluation-history-panel", AvlEvaluationHistoryPanel);
