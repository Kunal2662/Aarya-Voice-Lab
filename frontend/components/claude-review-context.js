// <avl-claude-review-context> — VL-D3 §25. A bounded "Ask Claude"
// affordance for one recording's quality findings: shows exactly the
// context (state/claude-context.js's buildReviewClaudeContext()) that
// would be sent — never arbitrary filesystem access, never secrets — and
// routes the actual ask through the same CommandExecutor interface
// VL-D1's Claude workflow uses (state/command-executor.js), which
// honestly reports NOT_AVAILABLE until a real execution transport
// exists. This never claims to run a shell command itself.
import { AvlElement, defineComponent } from "./base-element.js";
import { buildReviewClaudeContext } from "../state/claude-context.js";
import { NullCommandExecutor, CommandExecutionOutcome } from "../state/command-executor.js";
import "./button.js";
import "./status-badge.js";

export class AvlClaudeReviewContext extends AvlElement {
  set recording(value) {
    this._recording = value || null;
    if (this.isConnected) this._render();
  }

  set assessment(value) {
    this._assessment = value || null;
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
    const warning = this._assessment && this._assessment.findings.length ? this._assessment.findings[0].message : null;
    const metric =
      this._assessment && this._assessment.measurements.estimatedSnrDb != null
        ? { name: "estimated_snr_db", value: this._assessment.measurements.estimatedSnrDb }
        : null;
    return buildReviewClaudeContext({
      recordingId: this._recording ? this._recording.id : null,
      batchId: this._recording ? this._recording.batchId : null,
      stage: "quality_analysis",
      metric,
      warning,
      error: null,
      config: null,
      provenance: { sourceSha256: this._recording ? this._recording.contentAddressedId : null, configHash: null },
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

    if (!this._recording) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select a recording to ask Claude about its technical review.";
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
      const result = await this._executor.execute(`review-context: ${this._recording.id}`);
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

defineComponent("avl-claude-review-context", AvlClaudeReviewContext);
