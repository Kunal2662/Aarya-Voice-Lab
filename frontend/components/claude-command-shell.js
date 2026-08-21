// <avl-claude-command-shell> — the visual shell for the Claude Code
// Command Center (VL-D6/D7/D8/D9, live-wired in VL-D10). Set `.snapshot`
// to a real identity.command_center.command_center_snapshot() payload
// (fetched by workspace-claude.js from
// frontend/contracts/live/command_center_snapshot.json — never
// fabricated here). Composes the repository context, diagnostics,
// command catalogue, verification descriptors, output log, task status,
// and a command-input row.
//
// This component executes nothing and never has. Submitting the input
// dispatches `avl-command-submit` with the typed text in `detail.text`;
// nothing in this repository listens for it yet (see
// state/command-executor.js's NullCommandExecutor) — a real integration
// is responsible for actually invoking the CLI through the same gates
// and audit log every other entry point uses, see
// identity/command_center.py's own note that "this module executes
// nothing". The command catalogue and verification descriptors below
// are rendered exactly as the backend describes them (risk tier, gate
// reason) — display only, never a button that runs anything.
import { AvlElement, defineComponent } from "./base-element.js";
import "./claude-output-log.js";
import "./claude-task-status.js";
import "./status-badge.js";
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
      /* FE-3 -- .diagnostics/.catalogue-row replaced by the shared
         avl-cluster (+ avl-row--bordered for the bordered list-row
         shape) utilities from css/base.css; only flex-wrap stays local. */
      .diagnostics .problems { color: var(--avl-color-state-danger); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .section-title { margin: 0; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; color: var(--avl-color-text-secondary); }
      .catalogue { display: flex; flex-direction: column; gap: var(--avl-space-1); max-height: 14rem; overflow-y: auto; }
      .catalogue-row { flex-wrap: wrap; }
      .catalogue-row .command { font: var(--avl-type-code-weight) var(--avl-type-code-size) / 1 var(--avl-type-code-family); flex: none; }
      .catalogue-row .summary { color: var(--avl-color-text-secondary); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .catalogue-row .risk { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); padding: 0.1rem var(--avl-space-1); border-radius: var(--avl-radius-sm); border: 1px solid var(--avl-color-border-default); flex: none; }
      .catalogue-row .gate-reason { flex-basis: 100%; color: var(--avl-color-state-warning); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .verification { display: flex; flex-direction: column; gap: var(--avl-space-1); }
      .verification-row { font: var(--avl-type-code-weight) var(--avl-type-code-size) / var(--avl-type-code-line-height) var(--avl-type-code-family); color: var(--avl-color-text-secondary); }
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

    // VL-D10 -- the real command_center_snapshot() envelope has no
    // ".payload" nesting (identity/command_center.py's _envelope()
    // spreads fields directly onto each section) -- read fields off
    // `snapshot.repository`/`snapshot.activity` themselves.
    const snapshot = this._snapshot;
    const repo = snapshot?.repository;
    const context = document.createElement("div");
    context.className = "context";
    context.textContent = repo
      ? `${repo.branch} @ ${repo.head_short} · ${repo.working_tree_clean ? "clean" : `${repo.changed_file_count} changed`}`
      : "No repository context loaded — snapshot not fetched.";
    shell.appendChild(context);

    // VL-D10 -- diagnostics: real git-safety/audit-chain health from
    // identity/command_center.py's diagnostics(). Three honest states
    // only -- healthy, unhealthy (with its real problems listed), or
    // unavailable (no snapshot). Never silently shown as healthy when
    // it isn't, never computed here.
    const diagnosticsRow = document.createElement("div");
    diagnosticsRow.className = "avl-cluster diagnostics";
    const diagnostics = snapshot?.diagnostics;
    const diagnosticsBadge = document.createElement("avl-status-badge");
    diagnosticsBadge.setAttribute("domain", "core");
    diagnosticsBadge.setAttribute("state", !diagnostics ? "offline" : diagnostics.healthy ? "ready" : "attention");
    const diagnosticsLabel = document.createElement("span");
    diagnosticsLabel.className = "avl-type-caption";
    diagnosticsLabel.textContent = !diagnostics
      ? "Diagnostics unavailable — snapshot not fetched."
      : diagnostics.healthy
        ? "Diagnostics: healthy."
        : "Diagnostics: unhealthy.";
    diagnosticsRow.append(diagnosticsBadge, diagnosticsLabel);
    shell.appendChild(diagnosticsRow);
    if (diagnostics && !diagnostics.healthy && diagnostics.problems.length) {
      const problems = document.createElement("div");
      problems.className = "problems";
      problems.textContent = diagnostics.problems.join("; ");
      shell.appendChild(problems);
    }

    const log = document.createElement("avl-claude-output-log");
    log.entries = snapshot?.activity?.entries || [];
    shell.appendChild(log);

    // VL-D10 -- the real command catalogue (identity/command_center.py's
    // COMMAND_CATALOGUE), rendered exactly as described: risk tier and,
    // for a gated command, its real gate_reason. Display only -- no row
    // here is a button that runs anything.
    const catalogueTitle = document.createElement("p");
    catalogueTitle.className = "section-title";
    catalogueTitle.textContent = "Command catalogue";
    shell.appendChild(catalogueTitle);
    const commands = snapshot?.commands?.commands || [];
    if (commands.length) {
      const catalogue = document.createElement("div");
      catalogue.className = "catalogue";
      for (const descriptor of commands) {
        const row = document.createElement("div");
        row.className = "avl-cluster avl-row--bordered catalogue-row";
        const command = document.createElement("span");
        command.className = "command";
        command.textContent = descriptor.command;
        const summary = document.createElement("span");
        summary.className = "summary";
        summary.textContent = descriptor.summary;
        const risk = document.createElement("span");
        risk.className = "risk";
        risk.textContent = (descriptor.risk || "").replace(/_/g, " ");
        row.append(command, summary, risk);
        if (descriptor.gate_reason) {
          const reason = document.createElement("span");
          reason.className = "gate-reason";
          reason.textContent = `Gated: ${descriptor.gate_reason}`;
          row.appendChild(reason);
        }
        catalogue.appendChild(row);
      }
      shell.appendChild(catalogue);
    } else {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No command catalogue loaded — snapshot not fetched.";
      shell.appendChild(empty);
    }

    // VL-D10 -- real verification-command descriptors
    // (identity/command_center.py's verification_commands()). Text only
    // -- the exact array of argv strings the backend describes, never
    // executed from here.
    const verificationTitle = document.createElement("p");
    verificationTitle.className = "section-title";
    verificationTitle.textContent = "Verification commands";
    shell.appendChild(verificationTitle);
    const verificationCommands = snapshot?.verification?.commands || [];
    if (verificationCommands.length) {
      const verification = document.createElement("div");
      verification.className = "verification";
      for (const descriptor of verificationCommands) {
        const row = document.createElement("div");
        row.className = "verification-row";
        row.textContent = `${descriptor.label}: ${descriptor.command.join(" ")}`;
        verification.appendChild(row);
      }
      shell.appendChild(verification);
    } else {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No verification descriptors loaded — snapshot not fetched.";
      shell.appendChild(empty);
    }

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
