// <avl-workspace-settings> — VL-D1 §21. Appearance, storage, runtime,
// logging, Claude integration. Local-first only — this workspace has no
// field, toggle, or affordance for cloud storage, cloud datasets, cloud
// model storage, or cloud audio processing anywhere in it.
import { AvlElement, defineComponent } from "./base-element.js";
import "./workspace-state.js";
import "./panel.js";
import "./theme-toggle.js";
import "./status-badge.js";
import "./metric-placeholder.js";
import "./notice-banner.js";

export class AvlWorkspaceSettings extends AvlElement {
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
    try {
      const response = await fetch(new URL("../contracts/generated/compute_backend.json", import.meta.url));
      this._backends = (await response.json()).values;
      this._state = "ready";
    } catch (err) {
      this._state = "error";
      this._errorDetail = String(err);
    }
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      .section { margin-bottom: var(--avl-space-4); }
      .row { display: flex; justify-content: space-between; align-items: center; padding: var(--avl-space-1) 0; }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "error") wrapper.setAttribute("detail", this._errorDetail || "");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Settings";
    wrapper.appendChild(heading);

    const appearance = document.createElement("avl-panel");
    appearance.setAttribute("title", "Appearance");
    appearance.appendChild(document.createElement("avl-theme-toggle"));
    wrapper.appendChild(appearance);

    const storage = document.createElement("avl-panel");
    storage.setAttribute("title", "Storage");
    const storageNotice = document.createElement("avl-notice-banner");
    storageNotice.setAttribute("tone", "info");
    storageNotice.textContent = "Local-first only. No cloud storage, cloud dataset, cloud model storage, or cloud audio processing is configured or configurable here.";
    storage.appendChild(storageNotice);
    wrapper.appendChild(storage);

    const runtime = document.createElement("avl-panel");
    runtime.setAttribute("title", "Runtime");
    for (const backend of this._backends || []) {
      const row = document.createElement("div");
      row.className = "row";
      const label = document.createElement("span");
      label.textContent = backend;
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "hardware");
      badge.setAttribute("state", "UNKNOWN");
      row.append(label, badge);
      runtime.appendChild(row);
    }
    wrapper.appendChild(runtime);

    const logging = document.createElement("avl-panel");
    logging.setAttribute("title", "Logging");
    const logMetric = document.createElement("avl-metric-placeholder");
    logMetric.setAttribute("label", "Audit log entries");
    logging.appendChild(logMetric);
    wrapper.appendChild(logging);

    const claude = document.createElement("avl-panel");
    claude.setAttribute("title", "Claude integration");
    const claudeRow = document.createElement("div");
    claudeRow.className = "row";
    const claudeLabel = document.createElement("span");
    claudeLabel.textContent = "Execution transport";
    const claudeBadge = document.createElement("avl-status-badge");
    claudeBadge.setAttribute("domain", "core");
    claudeBadge.setAttribute("state", this._services.executor?.available() ? "ready" : "offline");
    claudeRow.append(claudeLabel, claudeBadge);
    claude.appendChild(claudeRow);
    wrapper.appendChild(claude);

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-settings", AvlWorkspaceSettings);
