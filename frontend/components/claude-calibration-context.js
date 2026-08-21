// <avl-claude-calibration-context> -- VL-D7. A bounded "Ask Claude"
// affordance for the current calibration profile: reuses
// state/claude-context.js's buildReviewClaudeContext() exactly as
// avl-claude-evaluation-context.js does -- same bounded shape (a
// profile id in place of recording id, run/evidence state as the
// warning, evidence counts as the metric and config, provenance limited
// to hashes/ids), same redaction pass, same routing through the shared
// CommandExecutor interface (still only NullCommandExecutor). Never
// exposes hardware capability free text beyond what the profile already
// carries, never a filesystem path, never a secret, no unrestricted
// shell, and never a speaker-identity field -- calibration profiles
// structurally cannot carry one (see pipeline.calibration_engine's
// CalibrationProfile shape).
import { AvlElement, defineComponent } from "./base-element.js";
import { buildReviewClaudeContext } from "../state/claude-context.js";
import { NullCommandExecutor, CommandExecutionOutcome } from "../state/command-executor.js";
import "./button.js";
import "./status-badge.js";

export class AvlClaudeCalibrationContext extends AvlElement {
  set profile(value) {
    this._profile = value || null;
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
    const profile = this._profile;
    return buildReviewClaudeContext({
      recordingId: profile ? profile.profile_id : null,
      batchId: null,
      stage: "calibration",
      metric: profile ? { name: "total_evaluations", value: profile.evidence_counts.total_evaluations } : null,
      warning: profile
        ? `run_state=${profile.run_state}, calibration_state=${profile.calibration_state}, strategy=${profile.strategy}`
        : null,
      error: null,
      config: profile
        ? {
            agreement_rate: profile.agreement_rate,
            adjustment_count: profile.adjustments.length,
            accelerator_confirmed: profile.hardware_snapshot.accelerator_confirmed,
          }
        : null,
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

    if (!this._profile) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Run a calibration pass to ask Claude about it.";
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
      const result = await this._executor.execute(`calibration-context: ${this._profile.profile_id}`);
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

defineComponent("avl-claude-calibration-context", AvlClaudeCalibrationContext);
