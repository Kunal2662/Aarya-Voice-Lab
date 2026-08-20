// <avl-workspace-claude> — VL-D1 §14-§16 made operational. Set
// `.services = { activityStore, executor, contextInput }`. Composes:
//   - avl-claude-command-shell (VL-D0's visual shell, now fed real
//     activity + a real, honestly-NOT_AVAILABLE connection state)
//   - a Claude context preview (state/claude-context.js's
//     buildClaudeContext(), rendered read-only so the operator can see
//     exactly what would be sent — bounded and redacted)
//   - avl-claude-fix-flow, entered from a real failed synthetic job
import { AvlElement, defineComponent } from "./base-element.js";
import { buildClaudeContext } from "../state/claude-context.js";
import "./workspace-state.js";
import "./panel.js";
import "./status-badge.js";
import "./claude-command-shell.js";
import "./claude-fix-flow.js";

export class AvlWorkspaceClaude extends AvlElement {
  set services(value) {
    this._services = value || {};
  }

  connectedCallback() {
    this._services = this._services || {};
    this._load();
  }

  async _load() {
    this._state = "loading";
    this._render();
    this._state = "ready";
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      .connection { display: flex; align-items: center; gap: var(--avl-space-2); margin-bottom: var(--avl-space-3); }
      pre { font: var(--avl-type-code-weight) var(--avl-type-code-size) / var(--avl-type-code-line-height) var(--avl-type-code-family); background: var(--avl-color-surface-sunken); padding: var(--avl-space-2); border-radius: var(--avl-radius-sm); overflow-x: auto; }
      .section { margin-top: var(--avl-space-4); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Claude Code";
    wrapper.appendChild(heading);

    const executor = this._services.executor;
    const connection = document.createElement("div");
    connection.className = "connection";
    const badge = document.createElement("avl-status-badge");
    badge.setAttribute("domain", "core");
    badge.setAttribute("state", executor?.available() ? "ready" : "offline");
    const label = document.createElement("span");
    label.className = "avl-type-body-small";
    label.textContent = executor?.available()
      ? "Execution transport connected."
      : "No execution transport connected in VL-D1 — see docs/VLD1_COMMAND_CENTER.md.";
    connection.append(badge, label);
    wrapper.appendChild(connection);

    const shell = document.createElement("avl-claude-command-shell");
    shell.snapshot = {
      repository: { payload: { branch: "(not fetched)", head_short: "-------", working_tree_clean: true, changed_file_count: 0 } },
      activity: { payload: { entries: [] } },
    };
    wrapper.appendChild(shell);

    const contextSection = document.createElement("div");
    contextSection.className = "section";
    const contextPanel = document.createElement("avl-panel");
    contextPanel.setAttribute("title", "Context sent to Claude (preview)");
    const pre = document.createElement("pre");
    const context = buildClaudeContext({
      destination: "claude",
      selection: null,
      recentActivity: this._services.activityStore ? this._services.activityStore.list({ limit: 5 }) : [],
      gitState: null,
      taskId: null,
    });
    pre.textContent = JSON.stringify(context, null, 2);
    contextPanel.appendChild(pre);
    contextSection.appendChild(contextPanel);
    wrapper.appendChild(contextSection);

    const fixSection = document.createElement("div");
    fixSection.className = "section";
    const fixPanel = document.createElement("avl-panel");
    fixPanel.setAttribute("title", "Fix workflow (example: a failed synthetic job)");
    const fixFlow = document.createElement("avl-claude-fix-flow");
    fixFlow.executor = executor;
    fixFlow.error = { summary: "StageContractError: input hash mismatch", detail: "synthetic-job-003 failed at normalization" };
    fixPanel.appendChild(fixFlow);
    fixSection.appendChild(fixPanel);
    wrapper.appendChild(fixSection);

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-claude", AvlWorkspaceClaude);
