// <avl-claude-evaluation-context> -- VL-D6. A bounded "Ask Claude"
// affordance for one output's evaluation state: reuses
// state/claude-context.js's buildReviewClaudeContext() exactly as
// avl-claude-generation-context.js does -- same bounded shape (output
// id, voice profile id, stage, a structured metric, disagreement info,
// provenance), same redaction pass, same routing through the shared
// CommandExecutor interface (still only NullCommandExecutor until a
// real execution transport exists). Never a raw reviewer comment beyond
// what buildReviewClaudeContext's own field selection already exposes,
// never a filesystem path, never a secret, no unrestricted shell, and
// never a speaker-identity field -- output_id/reviewer/scores are all
// this passes, nothing about who the target speaker is.
import { AvlElement, defineComponent } from "./base-element.js";
import { buildReviewClaudeContext } from "../state/claude-context.js";
import { NullCommandExecutor, CommandExecutionOutcome } from "../state/command-executor.js";
import "./button.js";
import "./status-badge.js";

export class AvlClaudeEvaluationContext extends AvlElement {
  set outputId(value) {
    this._outputId = value || null;
    if (this.isConnected) this._render();
  }

  set voiceProfileId(value) {
    this._voiceProfileId = value || null;
    if (this.isConnected) this._render();
  }

  set summary(value) {
    this._summary = value || null;
    if (this.isConnected) this._render();
  }

  set executor(value) {
    this._executor = value;
  }

  connectedCallback() {
    this._executor = this._executor || new NullCommandExecutor();
    this._render();
  }

  _context() {
    const summary = this._summary;
    return buildReviewClaudeContext({
      recordingId: this._outputId,
      batchId: this._voiceProfileId,
      stage: "voice_evaluation",
      metric:
        summary && summary.evaluation_count
          ? { name: "evaluation_count", value: summary.evaluation_count }
          : null,
      warning: summary && summary.has_disagreement ? `Disagreement on: ${summary.disagreement_dimensions.join(", ")}` : null,
      error: null,
      config: summary ? { reviewer_count: summary.reviewer_count, completed_count: summary.completed_count } : null,
      provenance: { sourceSha256: null, configHash: null },
    });
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      pre { font: var(--avl-type-code-weight) var(--avl-type-code-size) / var(--avl-type-code-line-height) var(--avl-type-code-family); background: var(--avl-color-surface-sunken); padding: var(--avl-space-2); border-radius: var(--avl-radius-sm); overflow-x: auto; margin: var(--avl-space-2) 0; }
      .outcome { display: flex; align-items: center; gap: var(--avl-space-2); margin-top: var(--avl-space-2); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._outputId) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select an output to ask Claude about its evaluations.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(this._context(), null, 2);
    this.shadowRoot.appendChild(pre);

    const askButton = document.createElement("avl-button");
    askButton.setAttribute("variant", "primary");
    askButton.textContent = "Ask Claude";
    askButton.addEventListener("click", async () => {
      const result = await this._executor.execute(`evaluation-context: ${this._outputId}`);
      this._outcome = result;
      this._render();
    });
    this.shadowRoot.appendChild(askButton);

    if (this._outcome) {
      const outcome = document.createElement("div");
      outcome.className = "outcome";
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "core");
      badge.setAttribute("state", this._outcome.outcome === CommandExecutionOutcome.NOT_AVAILABLE ? "offline" : "ready");
      const message = document.createElement("span");
      message.className = "avl-type-body-small";
      message.textContent = this._outcome.error || this._outcome.output || "";
      outcome.append(badge, message);
      this.shadowRoot.appendChild(outcome);
    }
  }
}

defineComponent("avl-claude-evaluation-context", AvlClaudeEvaluationContext);
