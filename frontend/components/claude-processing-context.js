// <avl-claude-processing-context> — VL-D4 §25. A bounded "Ask Claude"
// affordance for one recording's processing result: reuses
// state/claude-context.js's buildReviewClaudeContext() exactly as
// VL-D3's claude-review-context.js does — same bounded shape (recording
// ID/batch ID/stage/metric/warning/error/config/provenance), same
// redaction pass, same routing through the shared CommandExecutor
// interface (still only NullCommandExecutor until a real execution
// transport exists). Never arbitrary filesystem access, never secrets,
// no unrestricted shell.
import { AvlElement, defineComponent } from "./base-element.js";
import { buildReviewClaudeContext } from "../state/claude-context.js";
import { NullCommandExecutor, CommandExecutionOutcome } from "../state/command-executor.js";
import "./button.js";
import "./status-badge.js";

export class AvlClaudeProcessingContext extends AvlElement {
  set recording(value) {
    this._recording = value || null;
    if (this.isConnected) this._render();
  }

  set item(value) {
    this._item = value || null;
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
    const item = this._item;
    const metric =
      item && item.qualityBefore && item.qualityBefore.measurements && item.qualityBefore.measurements.estimatedSnrDb != null
        ? { name: "estimated_snr_db", value: item.qualityBefore.measurements.estimatedSnrDb }
        : null;
    const warning = item && (item.errors[0] || item.warnings[0]) ? item.errors[0] || item.warnings[0] : null;
    return buildReviewClaudeContext({
      recordingId: this._recording ? this._recording.id : null,
      batchId: this._recording ? this._recording.batchId : null,
      stage: "voice_processing",
      metric,
      warning,
      error: item && item.errors.length ? item.errors[0] : null,
      config: item ? { profile_id: item.profileId } : null,
      provenance: {
        sourceSha256: this._recording ? this._recording.contentAddressedId : null,
        configHash: item && item.derivedArtifact ? item.derivedArtifact.artifactId : null,
      },
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
      empty.textContent = "Select a recording to ask Claude about its processing result.";
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
      const result = await this._executor.execute(`processing-context: ${this._recording.id}`);
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

defineComponent("avl-claude-processing-context", AvlClaudeProcessingContext);
