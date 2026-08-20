// <avl-claude-fix-flow> — the VL-D1 §16 fix workflow:
//
//   ERROR -> VIEW DETAILS -> ASK CLAUDE -> CLAUDE ANALYSIS -> PROPOSE FIX
//   -> USER APPROVAL -> EXECUTION (approved gate) -> TEST -> RESULT -> AUDIT EVENT
//
// Set `.error` to {summary, detail} and optionally `.executor` (a
// state/command-executor.js CommandExecutor; defaults to
// NullCommandExecutor). "Ask Claude" is the one step that actually does
// something — it calls executor.execute(), which VL-D1's default
// executor honestly answers with NOT_AVAILABLE. Every step from
// "Claude analysis" onward is rendered as an upcoming step in the flow,
// never as if it already ran: this component does not automatically
// execute a fix, and never fabricates a result or a test pass.
import { AvlElement, defineComponent } from "./base-element.js";
import { NullCommandExecutor, CommandExecutionOutcome } from "../state/command-executor.js";
import "./button.js";
import "./error-panel.js";
import "./status-badge.js";

const STEPS = [
  "Error",
  "View details",
  "Ask Claude",
  "Claude analysis",
  "Propose fix",
  "User approval",
  "Execution",
  "Test",
  "Result",
  "Audit event",
];

export class AvlClaudeFixFlow extends AvlElement {
  set error(value) {
    this._error = value || null;
    this._stepIndex = 0;
    this._outcome = null;
    if (this.isConnected) this._render();
  }

  set executor(value) {
    this._executor = value;
  }

  connectedCallback() {
    this._stepIndex = this._stepIndex ?? 0;
    this._outcome = this._outcome ?? null;
    this._executor = this._executor || new NullCommandExecutor();
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .steps { display: flex; flex-wrap: wrap; gap: var(--avl-space-1); margin: var(--avl-space-3) 0; }
      .step {
        font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family);
        padding: 0.2rem var(--avl-space-2); border-radius: var(--avl-radius-pill);
        border: 1px solid var(--avl-color-border-default); color: var(--avl-color-text-muted);
      }
      .step[data-reached="true"] { color: var(--avl-color-text-primary); border-color: var(--avl-color-brand-accent); background: var(--avl-color-brand-accent-subtle); }
      .actions { display: flex; gap: var(--avl-space-2); margin-top: var(--avl-space-2); }
      .outcome { margin-top: var(--avl-space-3); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._error) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No error selected.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const errorPanel = document.createElement("avl-error-panel");
    errorPanel.setAttribute("summary", this._error.summary || "An error occurred.");
    if (this._error.detail) errorPanel.setAttribute("detail", this._error.detail);
    this.shadowRoot.appendChild(errorPanel);

    const steps = document.createElement("div");
    steps.className = "steps";
    steps.setAttribute("role", "list");
    steps.setAttribute("aria-label", "Fix workflow progress");
    STEPS.forEach((label, index) => {
      const step = document.createElement("span");
      step.className = "step";
      step.setAttribute("role", "listitem");
      step.dataset.reached = String(index <= this._stepIndex);
      step.textContent = label;
      steps.appendChild(step);
    });
    this.shadowRoot.appendChild(steps);

    const actions = document.createElement("div");
    actions.className = "actions";

    if (this._stepIndex === 0) {
      const viewDetails = document.createElement("avl-button");
      viewDetails.setAttribute("variant", "secondary");
      viewDetails.textContent = "View details";
      viewDetails.addEventListener("click", () => {
        this._stepIndex = 1;
        this._render();
      });
      actions.appendChild(viewDetails);
    } else if (this._stepIndex === 1) {
      const askClaude = document.createElement("avl-button");
      askClaude.setAttribute("variant", "primary");
      askClaude.textContent = "Ask Claude";
      askClaude.addEventListener("click", async () => {
        this._stepIndex = 2;
        this._render();
        const result = await this._executor.execute(`diagnose: ${this._error.summary}`);
        this._outcome = result;
        if (result.outcome !== CommandExecutionOutcome.NOT_AVAILABLE) {
          this._stepIndex = 3;
        }
        this._render();
      });
      actions.appendChild(askClaude);
    }

    this.shadowRoot.appendChild(actions);

    if (this._outcome) {
      const outcome = document.createElement("div");
      outcome.className = "outcome";
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "core");
      badge.setAttribute(
        "state",
        this._outcome.outcome === CommandExecutionOutcome.NOT_AVAILABLE ? "offline" : "ready",
      );
      outcome.appendChild(badge);
      const message = document.createElement("p");
      message.className = "avl-type-body-small";
      message.textContent = this._outcome.error || this._outcome.output || "";
      outcome.appendChild(message);
      this.shadowRoot.appendChild(outcome);
    }
  }
}

defineComponent("avl-claude-fix-flow", AvlClaudeFixFlow);
