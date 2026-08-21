// <avl-claude-task-status> — set `.command` to a CommandDescriptor.to_dict()
// shape (command, summary, risk, requires_confirmation, gate_reason) and
// `.state` to one of the "core" status-vocabulary states. GATED/DESTRUCTIVE
// commands always show their risk and, if gated, the reason — never
// hidden, per identity/command_center.py's own design note.
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";

export class AvlClaudeTaskStatus extends AvlElement {
  set command(value) {
    this._command = value || null;
    if (this.isConnected) this._render();
  }

  set state(value) {
    this._state = value || "idle";
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._state = this._state || "idle";
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      /* FE-3 -- .row replaced by the shared avl-cluster utility (css/base.css); only the wrap behavior stays local. */
      .row { flex-wrap: wrap; }
      .command { font: var(--avl-type-code-weight) var(--avl-type-code-size) / 1 var(--avl-type-code-family); }
      .risk { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); padding: 0.1rem var(--avl-space-1); border-radius: var(--avl-radius-sm); border: 1px solid var(--avl-color-border-default); }
      .gate-reason { color: var(--avl-color-state-warning); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._command) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No command selected.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const row = document.createElement("div");
    row.className = "avl-cluster row";

    const command = document.createElement("span");
    command.className = "command";
    command.textContent = this._command.command || "";

    const risk = document.createElement("span");
    risk.className = "risk";
    risk.textContent = (this._command.risk || "").replace(/_/g, " ");

    const badge = document.createElement("avl-status-badge");
    badge.setAttribute("domain", "core");
    badge.setAttribute("state", this._state);

    row.append(command, risk, badge);
    this.shadowRoot.appendChild(row);

    if (this._command.gate_reason) {
      const reason = document.createElement("div");
      reason.className = "gate-reason";
      reason.textContent = `Gated: ${this._command.gate_reason}`;
      this.shadowRoot.appendChild(reason);
    }
  }
}

defineComponent("avl-claude-task-status", AvlClaudeTaskStatus);
