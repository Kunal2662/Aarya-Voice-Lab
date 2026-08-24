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
        "Embeddings stored": snap.embeddings?.count ?? 0,
        "Runtime components declared": snap.runtime?.components?.length ?? 0,
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

      // VL-D14 -- enrollment_status()'s available_strategies/
      // available_providers were already fetched here since D11 (both
      // live inside snap.enrollment), but never rendered -- the same
      // "real data fetched every load, silently dropped" gap D13 closed
      // for runtime/embeddings/preview. Neither field is biometric or
      // profile data (just strategy/provider catalogue metadata), so no
      // new security review is needed; rendered as an honest sentence
      // naming every declared entry, or an explicit "none declared"
      // state for an empty array -- never a fabricated default catalogue.
      const strategiesRow = document.createElement("div");
      strategiesRow.className = "avl-row avl-row--center";
      const strategiesLabel = document.createElement("span");
      strategiesLabel.className = "avl-type-body-small";
      const strategies = snap.enrollment?.available_strategies ?? [];
      strategiesLabel.textContent = strategies.length
        ? `Enrollment strategies available: ${strategies.map((s) => s.name).join(", ")}.`
        : "No enrollment strategies declared.";
      strategiesRow.appendChild(strategiesLabel);
      identityPanel.appendChild(strategiesRow);

      const providersRow = document.createElement("div");
      providersRow.className = "avl-row avl-row--center";
      const providersLabel = document.createElement("span");
      providersLabel.className = "avl-type-body-small";
      const providers = snap.enrollment?.available_providers ?? [];
      providersLabel.textContent = providers.length
        ? `Embedding providers available: ${providers.join(", ")}.`
        : "No embedding providers declared.";
      providersRow.appendChild(providersLabel);
      identityPanel.appendChild(providersRow);

      // VL-D13 -- desktop_snapshot()'s runtime/embeddings/preview
      // sub-payloads were already fetched here since D11, but never
      // rendered. Each stays as honest as the backend contract: a
      // component list that only ever includes the real embedding
      // provider when it is genuinely installed, an embedding count that
      // is always real (never a vector, per embedding_inventory()'s own
      // note), and a preview-loop sentence that is honestly static since
      // voice generation is not implemented.
      const runtimeRow = document.createElement("div");
      runtimeRow.className = "avl-row avl-row--center";
      const runtimeLabel = document.createElement("span");
      runtimeLabel.className = "avl-type-body-small";
      const components = snap.runtime?.components ?? [];
      runtimeLabel.textContent = components.length
        ? `Runtime capabilities declared: ${components.map((c) => c.component).join(", ")}.`
        : "No runtime capabilities declared.";
      runtimeRow.appendChild(runtimeLabel);
      identityPanel.appendChild(runtimeRow);

      const embeddingsRow = document.createElement("div");
      embeddingsRow.className = "avl-row avl-row--center";
      const embeddingsLabel = document.createElement("span");
      embeddingsLabel.className = "avl-type-caption";
      embeddingsLabel.textContent = snap.embeddings?.note || "No embedding inventory data.";
      embeddingsRow.appendChild(embeddingsLabel);
      identityPanel.appendChild(embeddingsRow);

      const previewRow = document.createElement("div");
      previewRow.className = "avl-row avl-row--center";
      const previewLabel = document.createElement("span");
      previewLabel.className = "avl-type-body-small";
      previewLabel.textContent = snap.preview?.generation_implemented
        ? "Voice generation is implemented."
        : "Voice generation is not implemented — preview loop contracts only.";
      previewRow.appendChild(previewLabel);
      identityPanel.appendChild(previewRow);

      // VL-D15 -- pipeline_status()'s `batches` (real, on-disk batch-ID
      // strings from core.data_root.list_batches()) was already fetched
      // here since D11, but never rendered -- the same "real data
      // fetched every load, silently dropped" gap D13/D14 closed for
      // their own fields. `pipeline.stages` was audited alongside this
      // field and deliberately NOT bridged here: it is already real,
      // live, and rendered by the separate avl-workspace-pipeline /
      // avl-pipeline-stage-track path (VL-D1 §12), so duplicating it in
      // this panel would only create a second, redundant surface for the
      // same data. This row is also intentionally distinct from the
      // "Batches" workspace (avl-workspace-batches), which still renders
      // syntheticBatches() fixtures and is unrelated to this real,
      // gitignored-snapshot-backed list -- never a fabricated batch id,
      // and never a status/count beyond the bare id (BatchMetadata is
      // out of scope for this milestone).
      const batchesRow = document.createElement("div");
      batchesRow.className = "avl-row avl-row--center";
      const batchesLabel = document.createElement("span");
      batchesLabel.className = "avl-type-body-small";
      const batches = snap.pipeline?.batches ?? [];
      batchesLabel.textContent = batches.length
        ? `Batches on disk: ${batches.join(", ")}.`
        : "No batches recorded yet.";
      batchesRow.appendChild(batchesLabel);
      identityPanel.appendChild(batchesRow);
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
