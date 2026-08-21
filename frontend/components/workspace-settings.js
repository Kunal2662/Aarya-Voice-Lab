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
import "./confirm-action.js";

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
    storage.appendChild(this._buildSessionSection());
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

  /** VL-D9 -- the explicit "Clear session data" control (Task #190).
   * Requires two distinct clicks (never a single accidental click, never
   * an automatic trigger): the first opens a confirmation dialog naming
   * exactly what will be cleared; only an explicit "Confirm clear"
   * inside it actually calls services.session.clear(). Clears only this
   * app's own namespaced localStorage keys (see clearAllSessionData())
   * -- never anything else in the browser's storage.
   *
   * FE-1.1 -- the confirmation step is now a real <avl-confirm-action>
   * dialog (role="dialog", aria-modal, Escape-to-cancel, focus trap,
   * focus returned to "Clear session data" on close) instead of the
   * hand-built hidden-<div> warning VL-D9 shipped. Its Confirm/Cancel
   * actions stay plain native <button> elements, not the primitive's
   * own recommended <avl-button> default (see components/confirm-
   * action.js's header comment), specifically so the existing,
   * untouched session.test.mjs tests #4/#5/#6 -- which query
   * `settings.shadowRoot.querySelectorAll("button")` and match on
   * `.textContent` -- keep finding real <button> tags with unchanged
   * text. */
  _buildSessionSection() {
    const section = document.createElement("div");
    section.style.marginTop = "var(--avl-space-3)";

    const session = this._services.session || {};

    const statusRow = document.createElement("div");
    statusRow.className = "row";
    const statusLabel = document.createElement("span");
    statusLabel.textContent = "Local session persistence";
    const statusBadge = document.createElement("avl-status-badge");
    statusBadge.setAttribute("domain", "core");
    statusBadge.setAttribute("state", session.available ? "ready" : "offline");
    statusRow.append(statusLabel, statusBadge);
    section.appendChild(statusRow);

    const explanation = document.createElement("p");
    explanation.className = "avl-type-caption";
    explanation.textContent = session.available
      ? "Your Import/Review/Processing/Preview/Feedback/Calibration state is saved to this browser only, so it survives a reload. It is never uploaded anywhere."
      : "Persistence is unavailable in this browser (private browsing or storage disabled) -- your session will not be saved locally.";
    section.appendChild(explanation);

    const clearButton = document.createElement("button");
    clearButton.type = "button";
    clearButton.textContent = "Clear session data";
    clearButton.disabled = !session.available;

    const confirmDialog = document.createElement("avl-confirm-action");
    confirmDialog.setAttribute("dialog-title", "Clear session data?");
    confirmDialog.setAttribute("variant", "danger");
    confirmDialog.setAttribute(
      "description",
      "This removes all locally saved Import/Review/Processing/Preview/Feedback/Calibration state from this browser and cannot be undone. Nothing outside this app's own local storage is touched.",
    );

    const confirmButton = document.createElement("button");
    confirmButton.type = "button";
    confirmButton.slot = "actions";
    confirmButton.textContent = "Confirm clear";
    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.slot = "actions";
    cancelButton.textContent = "Cancel";
    confirmDialog.append(cancelButton, confirmButton);

    const closeDialog = () => confirmDialog.removeAttribute("open");
    clearButton.addEventListener("click", () => {
      confirmDialog.setAttribute("open", "");
    });
    cancelButton.addEventListener("click", closeDialog);
    confirmDialog.addEventListener("avl-dialog-cancel", closeDialog);
    confirmButton.addEventListener("click", () => {
      if (typeof session.clear === "function") session.clear();
      closeDialog();
      this._announce("Session data cleared");
      this._render();
    });

    section.append(clearButton, confirmDialog);
    return section;
  }
}

defineComponent("avl-workspace-settings", AvlWorkspaceSettings);
