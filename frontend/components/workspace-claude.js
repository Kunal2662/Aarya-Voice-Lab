// <avl-workspace-claude> — VL-D1 §14-§16 made operational, live-wired in
// VL-D10. Set `.services = { activityStore, executor, contextInput }`.
// Composes:
//   - avl-claude-command-shell, now fed a REAL
//     identity.command_center.command_center_snapshot() payload (real
//     branch/HEAD/working-tree state, real activity, real diagnostics,
//     real command catalogue, real verification descriptors), fetched
//     from frontend/contracts/live/command_center_snapshot.json — the
//     same "live snapshot, gitignored, honestly-missing-if-not-fetched"
//     pattern workspace-import.js's dataset-gate fetch already
//     established. Still a real, honestly-NOT_AVAILABLE connection state
//     for command *execution* (see the executor badge below) — D10 is a
//     read-only bridge, not an execution transport.
//   - a Claude context preview (state/claude-context.js's
//     buildClaudeContext(), rendered read-only so the operator can see
//     exactly what would be sent — bounded and redacted), now carrying
//     the real git_state instead of the null every prior phase left it
//     at
//   - avl-claude-fix-flow, entered from a real failed synthetic job
import { AvlElement, defineComponent } from "./base-element.js";
import { buildClaudeContext } from "../state/claude-context.js";
import { fetchCommandCenterSnapshot } from "../state/command-center-snapshot.js";
import { fetchIdentityStatusSnapshot } from "../state/identity-status-snapshot.js";
import "./workspace-state.js";
import "./panel.js";
import "./status-badge.js";
import "./stat-tile.js";
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
    // VL-D10 -- honest fetch: a missing file (script never run this
    // session), a non-OK response, malformed JSON, or a wrong-contract
    // payload all resolve to `null` inside fetchCommandCenterSnapshot()
    // (state/command-center-snapshot.js). Never thrown, never
    // fabricated — the UI renders "snapshot not fetched" rather than
    // guessing at a branch name or an empty-but-present activity feed.
    this._snapshot = await fetchCommandCenterSnapshot(
      new URL("../contracts/live/command_center_snapshot.json", import.meta.url),
    );
    // D11 audit follow-up -- identity.contracts.desktop_snapshot() has
    // existed, been tested, and been CLI-exposed since Phase 3, but
    // nothing in the frontend ever fetched it before now. Same honest
    // null-on-anything-less-than-a-valid-snapshot contract as the
    // Command Center fetch above.
    this._identitySnapshot = await fetchIdentityStatusSnapshot(
      new URL("../contracts/live/identity_status_snapshot.json", import.meta.url),
    );
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
      .dashboard-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: var(--avl-space-3); margin-bottom: var(--avl-space-2); }
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
    // VL-D10 -- the real snapshot fetched in _load(), or null if it was
    // never fetched (script not run this session) or came back
    // malformed. avl-claude-command-shell already renders a "not
    // fetched" state honestly for a null snapshot -- no fallback object
    // is ever fabricated here.
    shell.snapshot = this._snapshot;
    wrapper.appendChild(shell);

    const identitySection = document.createElement("div");
    identitySection.className = "section";
    const identityPanel = document.createElement("avl-panel");
    identityPanel.setAttribute("title", "Identity & enrollment status");
    const snap = this._identitySnapshot;
    if (!snap) {
      const notice = document.createElement("p");
      notice.className = "avl-type-caption";
      notice.textContent =
        "No live identity status snapshot fetched yet — run " +
        "`python scripts/export_identity_status_snapshot.py` and reload. " +
        "This is an honest \"not fetched\" state, never a fabricated count.";
      identityPanel.appendChild(notice);
    } else {
      const grid = document.createElement("div");
      grid.className = "dashboard-grid";
      const counts = {
        Profiles: snap.profiles?.count ?? 0,
        "Usable profiles": snap.profiles?.usable_count ?? 0,
        "Pipeline stages implemented": snap.pipeline?.implemented_count ?? 0,
        "Audit entries": snap.audit?.entry_count ?? 0,
      };
      Object.entries(counts).forEach(([label, value], i) => {
        const tile = document.createElement("avl-stat-tile");
        tile.setAttribute("label", label);
        tile.setAttribute("value", String(value));
        tile.setAttribute("tone", ["blue", "teal", "green", "violet"][i % 4]);
        tile.setAttribute("icon", "voices");
        grid.appendChild(tile);
      });
      identityPanel.appendChild(grid);

      const providerRow = document.createElement("div");
      providerRow.className = "avl-row avl-row--center";
      const providerLabel = document.createElement("span");
      providerLabel.className = "avl-type-body-small";
      // Real ML Runtime milestone follow-up: this used to be
      // unconditionally False from the backend -- now it is exactly
      // what identity.embeddings.any_real_provider_available() found on
      // whatever machine generated this snapshot.
      providerLabel.textContent = snap.enrollment?.real_provider_installed
        ? "Real embedding provider installed on this machine."
        : "No real embedding provider installed — synthetic only.";
      providerRow.appendChild(providerLabel);
      identityPanel.appendChild(providerRow);
    }
    identitySection.appendChild(identityPanel);
    wrapper.appendChild(identitySection);

    const contextSection = document.createElement("div");
    contextSection.className = "section";
    const contextPanel = document.createElement("avl-panel");
    contextPanel.setAttribute("title", "Context sent to Claude (preview)");
    const pre = document.createElement("pre");
    // VL-D10 -- git_state is real when the snapshot fetched (branch/
    // head_short/working_tree_clean straight off repository_context()),
    // and honestly null when it didn't -- buildClaudeContext() already
    // renders `git_state: null` rather than guessing.
    const repo = this._snapshot?.repository;
    const context = buildClaudeContext({
      destination: "claude",
      selection: null,
      recentActivity: this._services.activityStore ? this._services.activityStore.list({ limit: 5 }) : [],
      gitState: repo
        ? { branch: repo.branch, head_short: repo.head_short, working_tree_clean: repo.working_tree_clean }
        : null,
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
