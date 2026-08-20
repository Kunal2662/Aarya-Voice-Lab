// <avl-evaluation-queue> -- VL-D6. Set `.outputs` to an array of
// PreviewArtifact-shaped dicts (the outputs available to evaluate) and
// `.evaluationStore`. Renders one row per output with a live-computed
// status (not evaluated / in progress / evaluated / disagreement) --
// computed from the store's own records via
// state/evaluation-model.js's summarizeOutputEvaluations, never a
// separately tracked and possibly-stale flag. Clicking "Evaluate"
// dispatches `avl-evaluation-select` so a workspace can load that
// output into avl-evaluation-form.
import { AvlElement, defineComponent } from "./base-element.js";
import { EvaluationCompletionState, summarizeOutputEvaluations } from "../state/evaluation-model.js";
import "./status-badge.js";
import "./button.js";

function statusFor(evaluations) {
  if (!evaluations.length) return EvaluationCompletionState.IN_PROGRESS; // not started yet -- reuse label via display text below
  const hasCompleted = evaluations.some((e) => e.completion_state === EvaluationCompletionState.COMPLETED);
  const hasCannotJudge = evaluations.some((e) => e.completion_state === EvaluationCompletionState.CANNOT_JUDGE);
  if (hasCompleted || hasCannotJudge) return EvaluationCompletionState.COMPLETED;
  return EvaluationCompletionState.IN_PROGRESS;
}

export class AvlEvaluationQueue extends AvlElement {
  set outputs(value) {
    this._outputs = Array.isArray(value) ? value : [];
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
    this._outputs = this._outputs || [];
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
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      th { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; }
      .disagreement { color: var(--avl-color-state-warning); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._outputs.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No outputs available to evaluate yet.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML =
      "<tr><th>Output</th><th>Status</th><th>Evaluations</th><th>Reviewers</th><th>Disagreement</th><th>Actions</th></tr>";
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const output of this._outputs) {
      const outputId = output.preview_id;
      const evaluations = this._evaluationStore ? this._evaluationStore.evaluationsFor(outputId) : [];
      const summary = summarizeOutputEvaluations(evaluations, outputId);

      const row = document.createElement("tr");

      const idCell = document.createElement("td");
      idCell.textContent = outputId;
      row.appendChild(idCell);

      const statusCell = document.createElement("td");
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "evaluation_completion_state");
      badge.setAttribute("state", statusFor(evaluations));
      statusCell.appendChild(badge);
      if (!evaluations.length) {
        const notStarted = document.createElement("span");
        notStarted.textContent = " (not started)";
        statusCell.appendChild(notStarted);
      }
      row.appendChild(statusCell);

      const countCell = document.createElement("td");
      countCell.textContent = String(summary.evaluation_count);
      row.appendChild(countCell);

      const reviewerCell = document.createElement("td");
      reviewerCell.textContent = String(summary.reviewer_count);
      row.appendChild(reviewerCell);

      const disagreementCell = document.createElement("td");
      disagreementCell.className = summary.has_disagreement ? "disagreement" : "";
      disagreementCell.textContent = summary.has_disagreement ? `Yes (${summary.disagreement_dimensions.join(", ")})` : "No";
      row.appendChild(disagreementCell);

      const actionsCell = document.createElement("td");
      const evaluateButton = document.createElement("avl-button");
      evaluateButton.setAttribute("variant", "primary");
      evaluateButton.textContent = "Evaluate";
      evaluateButton.addEventListener("click", () => {
        this.dispatchEvent(new CustomEvent("avl-evaluation-select", { detail: { output }, bubbles: true, composed: true }));
      });
      actionsCell.appendChild(evaluateButton);
      row.appendChild(actionsCell);

      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    this.shadowRoot.appendChild(table);
  }
}

defineComponent("avl-evaluation-queue", AvlEvaluationQueue);
