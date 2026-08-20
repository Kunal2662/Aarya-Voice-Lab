// <avl-claude-output-log> — set `.entries` to an array shaped like
// aarya_voice_lab.identity.command_center.ActivityEntry.to_dict() (kind,
// summary, timestamp, subject_id, detail). Read-only log renderer; it
// does not fetch, poll, or execute anything.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlClaudeOutputLog extends AvlElement {
  set entries(value) {
    this._entries = Array.isArray(value) ? value : [];
    if (this.isConnected) this._render();
  }

  get entries() {
    return this._entries || [];
  }

  connectedCallback() {
    this._entries = this._entries || [];
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .log {
        display: flex; flex-direction: column; gap: var(--avl-space-1);
        font: var(--avl-type-code-weight) var(--avl-type-code-size) / var(--avl-type-code-line-height) var(--avl-type-code-family);
        background: var(--avl-color-surface-sunken);
        border: 1px solid var(--avl-color-border-subtle);
        border-radius: var(--avl-radius-sm);
        padding: var(--avl-space-2);
        max-height: 16rem; overflow-y: auto;
      }
      .entry { display: flex; gap: var(--avl-space-2); }
      .kind { color: var(--avl-color-brand-accent); flex: none; }
      .timestamp { color: var(--avl-color-text-muted); flex: none; }
      .summary { color: var(--avl-color-text-primary); word-break: break-word; }
      .empty { color: var(--avl-color-text-muted); }
    `;
    this.shadowRoot.appendChild(style);

    const log = document.createElement("div");
    log.className = "log";
    log.setAttribute("role", "log");
    log.setAttribute("aria-label", "Claude Code activity log");

    if (!this._entries.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No activity yet.";
      log.appendChild(empty);
    }

    for (const entry of this._entries) {
      const row = document.createElement("div");
      row.className = "entry";
      const kind = document.createElement("span");
      kind.className = "kind";
      kind.textContent = `[${entry.kind || "event"}]`;
      const summary = document.createElement("span");
      summary.className = "summary";
      summary.textContent = entry.summary || "";
      row.append(kind, summary);
      log.appendChild(row);
    }

    this.shadowRoot.appendChild(log);
  }
}

defineComponent("avl-claude-output-log", AvlClaudeOutputLog);
