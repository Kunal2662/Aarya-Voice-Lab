// <avl-rating-panel> -- VL-D6. One row per VoiceQualityDimension: a
// 1-5 score control plus a "Cannot judge" checkbox that disables and
// clears that dimension's score (mirrors
// pipeline.evaluation._validate_dimension_scores's rule that a
// dimension can never be both scored and cannot-judge). Purely a
// controlled input widget -- it never writes to an EvaluationStore
// itself, it only reports its current value via `avl-rating-change`
// and `.getValue()`, so an ancestor form can update its own state
// in place instead of re-rendering (and tearing down a playing
// avl-audio-player) on every click.
import { AvlElement, defineComponent } from "./base-element.js";
import { VoiceQualityDimension } from "../state/evaluation-model.js";

const DIMENSION_LABELS = {
  [VoiceQualityDimension.NATURALNESS]: "Naturalness",
  [VoiceQualityDimension.CLARITY]: "Clarity",
  [VoiceQualityDimension.INTELLIGIBILITY]: "Intelligibility",
  [VoiceQualityDimension.PRONUNCIATION]: "Pronunciation",
  [VoiceQualityDimension.PROSODY]: "Prosody (incl. rhythm)",
  [VoiceQualityDimension.PACE]: "Pace",
  [VoiceQualityDimension.EXPRESSIVENESS]: "Expressiveness",
  [VoiceQualityDimension.CONSISTENCY]: "Consistency (incl. stability)",
  [VoiceQualityDimension.ARTIFACTS]: "Artifacts",
  [VoiceQualityDimension.NOISE]: "Noise",
  [VoiceQualityDimension.OVERALL]: "Overall",
};

export class AvlRatingPanel extends AvlElement {
  set dimensions(value) {
    this._dimensions = Array.isArray(value) && value.length ? value : Object.values(VoiceQualityDimension);
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._dimensions = this._dimensions || Object.values(VoiceQualityDimension);
    this._scores = this._scores || {};
    this._cannotJudge = this._cannotJudge || new Set();
    this._render();
  }

  /** Reset all dimensions to unscored. Used after a submit. */
  reset() {
    this._scores = {};
    this._cannotJudge = new Set();
    this._render();
  }

  getValue() {
    return { dimensionScores: { ...this._scores }, cannotJudgeDimensions: [...this._cannotJudge] };
  }

  _emitChange() {
    this.dispatchEvent(
      new CustomEvent("avl-rating-change", { detail: this.getValue(), bubbles: true, composed: true }),
    );
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .rows { display: flex; flex-direction: column; gap: var(--avl-space-2); }
      .row { display: grid; grid-template-columns: 12rem 1fr auto; align-items: center; gap: var(--avl-space-2); }
      .dimension-label { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); color: var(--avl-color-text-primary); }
      .scores { display: flex; gap: var(--avl-space-1); }
      .score-btn { width: 2rem; height: 2rem; border-radius: var(--avl-radius-sm); border: 1px solid var(--avl-color-border-default); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); cursor: pointer; font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      .score-btn[aria-pressed="true"] { background: var(--avl-color-brand-accent); color: var(--avl-color-text-on-accent, var(--avl-color-text-primary)); border-color: var(--avl-color-brand-accent); }
      .score-btn:disabled { opacity: 0.4; cursor: not-allowed; }
      .cannot-judge { display: flex; align-items: center; gap: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); white-space: nowrap; }
    `;
    this.shadowRoot.appendChild(style);

    const rows = document.createElement("div");
    rows.className = "rows";
    rows.setAttribute("role", "group");
    rows.setAttribute("aria-label", "Voice quality ratings");

    for (const dimension of this._dimensions) {
      const row = document.createElement("div");
      row.className = "row";

      const label = document.createElement("span");
      label.className = "dimension-label";
      label.textContent = DIMENSION_LABELS[dimension] || dimension;
      row.appendChild(label);

      const isCannotJudge = this._cannotJudge.has(dimension);

      const scores = document.createElement("div");
      scores.className = "scores";
      for (let value = 1; value <= 5; value += 1) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "score-btn";
        button.textContent = String(value);
        button.setAttribute("aria-label", `${DIMENSION_LABELS[dimension] || dimension}: ${value}`);
        button.setAttribute("aria-pressed", String(this._scores[dimension] === value));
        button.disabled = isCannotJudge;
        button.addEventListener("click", () => {
          this._scores[dimension] = value;
          this._emitChange();
          this._render();
        });
        scores.appendChild(button);
      }
      row.appendChild(scores);

      const cannotJudgeWrap = document.createElement("label");
      cannotJudgeWrap.className = "cannot-judge";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = isCannotJudge;
      checkbox.setAttribute("aria-label", `${DIMENSION_LABELS[dimension] || dimension}: cannot judge`);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          this._cannotJudge.add(dimension);
          delete this._scores[dimension];
        } else {
          this._cannotJudge.delete(dimension);
        }
        this._emitChange();
        this._render();
      });
      cannotJudgeWrap.append(checkbox, document.createTextNode("Cannot judge"));
      row.appendChild(cannotJudgeWrap);

      rows.appendChild(row);
    }
    this.shadowRoot.appendChild(rows);
  }
}

defineComponent("avl-rating-panel", AvlRatingPanel);
