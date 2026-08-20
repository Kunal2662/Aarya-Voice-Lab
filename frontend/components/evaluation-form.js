// <avl-evaluation-form> -- VL-D6. Set `.output` (a PreviewArtifact-shaped
// dict -- its `.preview_id` becomes the Evaluation's `output_id`, same
// pairing state/synthetic-fixtures.js's evaluation fixtures already use)
// and `.evaluationStore` (a state/evaluation-model.js EvaluationStore).
// Embeds its own avl-voice-player so COMPLETED submissions stay gated on
// having actually pressed Play first (same UnlistenedFeedbackError-style
// gate avl-preview-feedback-form.js established for VL-D5, generalized
// here to EvaluationStore's UnlistenedEvaluationError). CANNOT_JUDGE and
// ABANDONED never require listening -- a reviewer may reach CANNOT_JUDGE
// precisely because playback failed.
//
// Listening state (replay count / furthest position reached / completed
// playback) is tracked from avl-audio-player's `avl-playback-started` /
// `avl-playback-position` / `avl-playback-ended` events, updated in
// place rather than by calling _render() (which would tear down and
// recreate the still-playing <audio> element -- the same blob-URL race
// avl-preview-feedback-form.js already documents). furthest_position_seconds
// is never claimed as "time listened": a reviewer can seek past content
// without hearing it, so this only records the furthest point genuinely
// reached.
import { AvlElement, defineComponent } from "./base-element.js";
import {
  EvaluationCompletionState,
  UnlistenedEvaluationError,
  InvalidDimensionScoreError,
  buildListeningState,
} from "../state/evaluation-model.js";
import "./voice-player.js";
import "./rating-panel.js";
import "./confidence-control.js";
import "./button.js";

const COMPLETION_LABELS = {
  [EvaluationCompletionState.COMPLETED]: "Submit evaluation",
  [EvaluationCompletionState.CANNOT_JUDGE]: "Cannot judge",
  [EvaluationCompletionState.ABANDONED]: "Abandon",
};

const REQUIRES_LISTEN = new Set([EvaluationCompletionState.COMPLETED]);

export class AvlEvaluationForm extends AvlElement {
  set output(value) {
    this._output = value || null;
    this._resetListening();
    this._statusMessage = null;
    if (this.isConnected) this._render();
  }

  set evaluationStore(value) {
    this._evaluationStore = value;
  }

  set reviewer(value) {
    this._reviewer = value || "operator";
  }

  set voiceProfileId(value) {
    this._voiceProfileId = value || null;
  }

  set modelId(value) {
    this._modelId = value || null;
  }

  set configHash(value) {
    this._configHash = value || null;
  }

  connectedCallback() {
    this._reviewer = this._reviewer || "operator";
    this._resetListening();
    this._pendingScores = {};
    this._pendingCannotJudgeDimensions = [];
    this._pendingConfidence = null;
    this._render();
  }

  _resetListening() {
    this._listened = false;
    this._firstListenedAt = null;
    this._replayCount = 0;
    this._furthestPositionSeconds = null;
    this._completedPlayback = false;
  }

  _updateListenGate() {
    const gate = this.shadowRoot.querySelector(".gate");
    if (gate) {
      gate.textContent = this._listened
        ? `Listened${this._completedPlayback ? " (played to the end)" : ""} — Submit evaluation is available.`
        : "Press Play above before Submit evaluation becomes available (Cannot judge/Abandon don't require listening first).";
    }
    for (const button of this.shadowRoot.querySelectorAll("avl-button[data-listen-gated]")) {
      if (this._listened) button.removeAttribute("disabled");
      else button.setAttribute("disabled", "");
    }
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .row { display: flex; gap: var(--avl-space-2); flex-wrap: wrap; margin-top: var(--avl-space-2); }
      label { display: flex; flex-direction: column; gap: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); margin-top: var(--avl-space-3); }
      textarea { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-sm); padding: var(--avl-space-1) var(--avl-space-2); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); }
      .gate { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-1); }
      .status { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); color: var(--avl-color-text-secondary); margin-top: var(--avl-space-1); }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-2); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      h3 { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); text-transform: uppercase; letter-spacing: 0.04em; margin: var(--avl-space-3) 0 0; }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._output) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select an output from the evaluation queue to begin.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const player = document.createElement("avl-voice-player");
    player.artifact = this._output;
    player.addEventListener("avl-playback-started", () => {
      if (!this._listened) {
        this._listened = true;
        this._firstListenedAt = new Date().toISOString();
      } else {
        this._replayCount += 1;
      }
      this._updateListenGate();
    });
    player.addEventListener("avl-playback-position", (event) => {
      const seconds = event.detail && event.detail.currentTimeSeconds;
      if (typeof seconds === "number" && (this._furthestPositionSeconds === null || seconds > this._furthestPositionSeconds)) {
        this._furthestPositionSeconds = seconds;
      }
    });
    player.addEventListener("avl-playback-ended", () => {
      this._completedPlayback = true;
      this._updateListenGate();
    });
    this.shadowRoot.appendChild(player);

    const gate = document.createElement("p");
    gate.className = "gate";
    this.shadowRoot.appendChild(gate);

    const ratingHeading = document.createElement("h3");
    ratingHeading.textContent = "Ratings";
    this.shadowRoot.appendChild(ratingHeading);

    const ratingPanel = document.createElement("avl-rating-panel");
    ratingPanel.addEventListener("avl-rating-change", (event) => {
      this._pendingScores = event.detail.dimensionScores;
      this._pendingCannotJudgeDimensions = event.detail.cannotJudgeDimensions;
    });
    this.shadowRoot.appendChild(ratingPanel);

    const confidenceHeading = document.createElement("h3");
    confidenceHeading.textContent = "Confidence";
    this.shadowRoot.appendChild(confidenceHeading);

    const confidenceControl = document.createElement("avl-confidence-control");
    confidenceControl.addEventListener("avl-confidence-change", (event) => {
      this._pendingConfidence = event.detail.confidence;
    });
    this.shadowRoot.appendChild(confidenceControl);

    const commentLabel = document.createElement("label");
    commentLabel.textContent = "Comment";
    const comment = document.createElement("textarea");
    comment.rows = 2;
    comment.setAttribute("aria-label", "Evaluation comment");
    commentLabel.appendChild(comment);
    this.shadowRoot.appendChild(commentLabel);

    const status = document.createElement("p");
    status.className = "status";
    status.setAttribute("role", "status");
    status.textContent = this._statusMessage || "";

    const row = document.createElement("div");
    row.className = "row";
    for (const completionState of Object.values(EvaluationCompletionState)) {
      if (completionState === EvaluationCompletionState.IN_PROGRESS) continue;
      const button = document.createElement("avl-button");
      button.setAttribute("variant", completionState === EvaluationCompletionState.ABANDONED ? "danger" : "primary");
      button.textContent = COMPLETION_LABELS[completionState] || completionState;
      if (REQUIRES_LISTEN.has(completionState)) button.dataset.listenGated = "";
      button.addEventListener("click", () => {
        if (!this._evaluationStore) return;
        try {
          const record = this._evaluationStore.record({
            outputId: this._output.preview_id,
            reviewer: this._reviewer,
            listening: buildListeningState({
              listened: this._listened,
              firstListenedAt: this._firstListenedAt,
              replayCount: this._replayCount,
              furthestPositionSeconds: this._furthestPositionSeconds,
              completedPlayback: this._completedPlayback,
            }),
            dimensionScores: this._pendingScores,
            cannotJudgeDimensions: this._pendingCannotJudgeDimensions,
            confidence: this._pendingConfidence,
            completionState,
            comment: comment.value || null,
            voiceProfileId: this._voiceProfileId,
            modelId: this._modelId,
            configHash: this._configHash,
            outputSha256: this._output.sha256 || null,
          });
          this._statusMessage = `Recorded ${record.evaluation_id} (${COMPLETION_LABELS[completionState]}).`;
          this._pendingScores = {};
          this._pendingCannotJudgeDimensions = [];
          this._pendingConfidence = null;
        } catch (err) {
          this._statusMessage =
            err instanceof UnlistenedEvaluationError || err instanceof InvalidDimensionScoreError
              ? err.message
              : `Could not record evaluation: ${err.message || err}`;
        }
        this._announce(this._statusMessage);
        this._render();
      });
      row.appendChild(button);
    }
    this.shadowRoot.appendChild(row);
    this.shadowRoot.appendChild(status);
    this._updateListenGate();

    const note = document.createElement("p");
    note.className = "note";
    note.textContent =
      "Each submission is a new, append-only record — a second evaluation of this output (by you or another reviewer) is how disagreement is represented, never an edit of this one.";
    this.shadowRoot.appendChild(note);
  }
}

defineComponent("avl-evaluation-form", AvlEvaluationForm);
