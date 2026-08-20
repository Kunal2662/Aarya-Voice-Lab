// <avl-ab-evaluation> -- VL-D6. Deliberately kept separate from VL-D5's
// avl-ab-comparison.js: that component pairs playback with single-output
// accept/reject feedback (PreviewFeedbackOutcome); this one is the
// broader comparative judgement -- full listen/replay/inspect-metadata/
// rate on BOTH sides (each embeds its own avl-evaluation-form, so each
// side still produces its own independent, multi-dimension Evaluation
// record), followed by a PREFER_A/PREFER_B/NO_PREFERENCE/CANNOT_JUDGE
// decision recorded to a separate ABEvaluationStore. Set `.left`/`.right`
// (PreviewArtifact-shaped dicts), `.labels` (default ["A","B"]),
// `.evaluationStore` (shared by both embedded forms) and
// `.abEvaluationStore`.
//
// The A/B decision buttons (other than CANNOT_JUDGE) are gated on BOTH
// sides having been listened to -- tracked by listening for the
// `avl-playback-started` event that bubbles out of each embedded
// avl-evaluation-form's own avl-voice-player (composed:true carries it
// across every shadow boundary in between, the same mechanism
// avl-preview-feedback-form.js already relies on one level down).
//
// Blinding (`.blinded`) is UI-level metadata suppression ONLY: when on,
// this component hides the buildAbComparison() metadata table (which
// would otherwise reveal model/kind info that could bias a "blind"
// comparison) and shows generic "Output 1"/"Output 2" labels instead of
// A/B. It is never a cryptographic or acoustic-anonymity guarantee --
// the same caveat avl-ab-comparison.js's own labelling does not need to
// make, since this project has no ability to alter the audio itself.
import { AvlElement, defineComponent } from "./base-element.js";
import { buildAbComparison } from "../state/generation-model.js";
import { ABDecision, UnlistenedEvaluationError } from "../state/evaluation-model.js";
import "./evaluation-form.js";
import "./button.js";

const DECISION_LABELS = {
  [ABDecision.PREFER_A]: "Prefer A",
  [ABDecision.PREFER_B]: "Prefer B",
  [ABDecision.NO_PREFERENCE]: "No preference",
  [ABDecision.CANNOT_JUDGE]: "Cannot judge",
};

const REQUIRES_BOTH_LISTENED = new Set([ABDecision.PREFER_A, ABDecision.PREFER_B, ABDecision.NO_PREFERENCE]);

export class AvlAbEvaluation extends AvlElement {
  set left(value) {
    this._left = value || null;
    this._listenedA = false;
    if (this.isConnected) this._render();
  }

  set right(value) {
    this._right = value || null;
    this._listenedB = false;
    if (this.isConnected) this._render();
  }

  set labels(value) {
    this._labels = Array.isArray(value) && value.length === 2 ? value : ["A", "B"];
    if (this.isConnected) this._render();
  }

  set blinded(value) {
    this._blinded = Boolean(value);
    if (this.isConnected) this._render();
  }

  set evaluationStore(value) {
    this._evaluationStore = value;
  }

  set abEvaluationStore(value) {
    this._abEvaluationStore = value;
  }

  set reviewer(value) {
    this._reviewer = value || "operator";
  }

  connectedCallback() {
    this._labels = this._labels || ["A", "B"];
    this._blinded = this._blinded || false;
    this._reviewer = this._reviewer || "operator";
    this._listenedA = this._listenedA || false;
    this._listenedB = this._listenedB || false;
    // Only initialize on the very first connect -- a later
    // disconnect/reconnect cycle (e.g. an ancestor workspace re-rendering
    // in reaction to the abEvaluationStore "change" event this
    // component's own submission just fired) must not wipe a
    // just-recorded status message before the reviewer ever sees it.
    if (this._statusMessage === undefined) this._statusMessage = null;
    this._render();
  }

  _updateDecisionGate() {
    for (const button of this.shadowRoot.querySelectorAll("avl-button[data-listen-gated]")) {
      if (this._listenedA && this._listenedB) button.removeAttribute("disabled");
      else button.setAttribute("disabled", "");
    }
    const gate = this.shadowRoot.querySelector(".gate");
    if (gate) {
      gate.textContent =
        this._listenedA && this._listenedB
          ? "Both outputs listened to — a preference decision is available."
          : "Prefer A/Prefer B/No preference require listening to BOTH outputs first (Cannot judge doesn't).";
    }
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .toolbar { display: flex; align-items: center; gap: var(--avl-space-2); margin-bottom: var(--avl-space-2); }
      .blind-toggle { display: flex; align-items: center; gap: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      .comparison { display: grid; grid-template-columns: 1fr 1fr; gap: var(--avl-space-4); }
      .column { display: flex; flex-direction: column; gap: var(--avl-space-2); border: 1px solid var(--avl-color-border-subtle); border-radius: var(--avl-radius-sm); padding: var(--avl-space-2); }
      .label { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); text-transform: uppercase; }
      table { width: 100%; border-collapse: collapse; margin-top: var(--avl-space-3); }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      .decision-row { display: flex; gap: var(--avl-space-2); flex-wrap: wrap; margin-top: var(--avl-space-2); }
      label.comment { display: flex; flex-direction: column; gap: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); margin-top: var(--avl-space-2); }
      textarea { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-sm); padding: var(--avl-space-1) var(--avl-space-2); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); }
      .gate { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-2); }
      .status { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); color: var(--avl-color-text-secondary); margin-top: var(--avl-space-1); }
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
      [this._left, this._right] = [this._right, this._left];
      [this._listenedA, this._listenedB] = [this._listenedB, this._listenedA];
      this._render();
    });
    toolbar.appendChild(swap);

    const blindWrap = document.createElement("label");
    blindWrap.className = "blind-toggle";
    const blindCheckbox = document.createElement("input");
    blindCheckbox.type = "checkbox";
    blindCheckbox.checked = this._blinded;
    blindCheckbox.addEventListener("change", () => {
      this._blinded = blindCheckbox.checked;
      this._render();
    });
    blindWrap.append(blindCheckbox, document.createTextNode("Blind comparison (hides the metadata table below — UI display only, not a real anonymity guarantee)"));
    toolbar.appendChild(blindWrap);
    this.shadowRoot.appendChild(toolbar);

    if (!this._left && !this._right) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select two outputs to compare.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const comparison = document.createElement("div");
    comparison.className = "comparison";
    const forms = [];
    for (const [index, artifact] of [this._left, this._right].entries()) {
      const column = document.createElement("div");
      column.className = "column";
      const label = document.createElement("span");
      label.className = "label";
      label.textContent = this._blinded ? `Output ${index + 1}` : this._labels[index];
      column.appendChild(label);

      const form = document.createElement("avl-evaluation-form");
      form.evaluationStore = this._evaluationStore;
      form.reviewer = this._reviewer;
      form.output = artifact;
      const isLeft = index === 0;
      form.addEventListener("avl-playback-started", () => {
        if (isLeft) this._listenedA = true;
        else this._listenedB = true;
        this._updateDecisionGate();
      });
      column.appendChild(form);
      comparison.appendChild(column);
      forms.push(form);
    }
    this.shadowRoot.appendChild(comparison);

    if (!this._blinded && this._left && this._right) {
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

    const gate = document.createElement("p");
    gate.className = "gate";
    this.shadowRoot.appendChild(gate);

    const commentLabel = document.createElement("label");
    commentLabel.className = "comment";
    commentLabel.textContent = "Comparison comment";
    const comment = document.createElement("textarea");
    comment.rows = 2;
    comment.setAttribute("aria-label", "A/B comparison comment");
    commentLabel.appendChild(comment);
    this.shadowRoot.appendChild(commentLabel);

    const status = document.createElement("p");
    status.className = "status";
    status.setAttribute("role", "status");
    status.textContent = this._statusMessage || "";

    const decisionRow = document.createElement("div");
    decisionRow.className = "decision-row";
    for (const decision of Object.values(ABDecision)) {
      const button = document.createElement("avl-button");
      button.setAttribute("variant", "primary");
      button.textContent = DECISION_LABELS[decision] || decision;
      if (REQUIRES_BOTH_LISTENED.has(decision)) button.dataset.listenGated = "";
      button.addEventListener("click", () => {
        if (!this._abEvaluationStore || !this._left || !this._right) return;
        try {
          const record = this._abEvaluationStore.record({
            outputIdA: this._left.preview_id,
            outputIdB: this._right.preview_id,
            reviewer: this._reviewer,
            listenedA: this._listenedA,
            listenedB: this._listenedB,
            decision,
            blinded: this._blinded,
            comment: comment.value || null,
          });
          this._statusMessage = `Recorded ${record.ab_evaluation_id} (${DECISION_LABELS[decision]}).`;
        } catch (err) {
          this._statusMessage = err instanceof UnlistenedEvaluationError ? err.message : `Could not record A/B decision: ${err.message || err}`;
        }
        this._announce(this._statusMessage);
        this._render();
      });
      decisionRow.appendChild(button);
    }
    this.shadowRoot.appendChild(decisionRow);
    this.shadowRoot.appendChild(status);
    this._updateDecisionGate();
  }
}

defineComponent("avl-ab-evaluation", AvlAbEvaluation);
