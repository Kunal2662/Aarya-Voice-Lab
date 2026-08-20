// <avl-claude-command-shell> — the visual shell for the Claude Code
// Command Center (VL-D6/D7/D8/D9). Set `.snapshot` to a
// command_center_snapshot() shape. Composes the repository context,
// command catalogue, output log, task status, and a command-input row.
//
// This component executes nothing. Submitting the input dispatches
// `avl-command-submit` with the typed text in `detail.text`; a future
// integration (VL-D1) is responsible for actually invoking the CLI
// through the same gates and audit log every other entry point uses —
// see identity/command_center.py's own note that "this module executes
// nothing".
import { AvlElement, defineComponent } from "./base-element.js";
import "./claude-output-log.js";
import "./claude-task-status.js";
import "./button.js";

export class AvlClaudeCommandShell extends AvlElement {
  set snapshot(value) {
    this._snapshot = value || null;
    if (this.isConnected) this._render();
  }

  get snapshot() {
    return this._snapshot;
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .shell { display: flex; flex-direction: column; gap: var(--avl-space-3); }
      .context { display: flex; gap: var(--avl-space-3); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      .input-row { display: flex; gap: var(--avl-space-2); }
      input[type="text"] {
        flex: 1; font: var(--avl-type-code-weight) var(--avl-type-code-size) / 1 var(--avl-type-code-family);
        padding: var(--avl-space-2); border: 1px solid var(--avl-color-border-default);
        border-radius: var(--avl-radius-sm); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary);
      }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    const shell = document.createElement("div");
    shell.className = "shell";

    const snapshot = this._snapshot;
    const repo = snapshot?.repository?.payload;
    const context = document.createElement("div");
    context.className = "context";
    context.textContent = repo
      ? `${repo.branch} @ ${repo.head_short} · ${repo.working_tree_clean ? "clean" : `${repo.changed_file_count} changed`}`
      : "No repository context loaded.";
    shell.appendChild(context);

    const log = document.createElement("avl-claude-output-log");
    log.entries = snapshot?.activity?.payload?.entries || [];
    shell.appendChild(log);

    const status = document.createElement("avl-claude-task-status");
    status.state = "idle";
    shell.appendChild(status);
    this._statusEl = status;

    const inputRow = document.createElement("div");
    inputRow.className = "input-row";
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = "Ask Claude Code…";
    input.setAttribute("aria-label", "Claude Code command input");
    const send = document.createElement("avl-button");
    send.setAttribute("variant", "primary");
    send.textContent = "Send";
    const submit = () => {
      const text = input.value.trim();
      if (!text) return;
      this.dispatchEvent(new CustomEvent("avl-command-submit", { detail: { text }, bubbles: true, composed: true }));
      input.value = "";
    };
    send.addEventListener("click", submit);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") submit();
    });
    inputRow.append(input, send);
    shell.appendChild(inputRow);

    this.shadowRoot.appendChild(shell);
  }
}

defineComponent("avl-claude-command-shell", AvlClaudeCommandShell);
