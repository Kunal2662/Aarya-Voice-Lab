// <avl-workspace-import> — VL-D1 §9. The bulk-import interaction model,
// synthetic-fixtures only. Shows the real (point-in-time, gitignored)
// dataset access gate snapshot when available — see
// scripts/export_dataset_gate_status.py — and an honest "not evaluated"
// state otherwise. Files dropped/selected here are listed by name only;
// nothing is hashed, uploaded, or written — that belongs to a real
// importer (VL-D2) built against source_protection.py's immutability
// rules.
import { AvlElement, defineComponent } from "./base-element.js";
import "./workspace-state.js";
import "./panel.js";
import "./notice-banner.js";
import "./import-drop-zone.js";
import "./status-badge.js";

export class AvlWorkspaceImport extends AvlElement {
  connectedCallback() {
    this._files = [];
    this._load();
  }

  async _load() {
    this._state = "loading";
    this._render();
    try {
      const response = await fetch(new URL("../contracts/live/dataset_gate_status.json", import.meta.url));
      this._gate = response.ok ? await response.json() : null;
    } catch {
      this._gate = null;
    }
    this._state = "ready";
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      .queue { display: flex; flex-direction: column; gap: var(--avl-space-1); margin-top: var(--avl-space-3); }
      .queue-item { display: flex; justify-content: space-between; padding: var(--avl-space-1) var(--avl-space-2); border: 1px solid var(--avl-color-border-subtle); border-radius: var(--avl-radius-sm); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      .gate-row { display: flex; justify-content: space-between; padding: var(--avl-space-1) 0; font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Import";
    wrapper.appendChild(heading);

    const notice = document.createElement("avl-notice-banner");
    notice.setAttribute("tone", "info");
    notice.textContent = "VL-D1 uses synthetic fixtures only. No real recordings are read, hashed, or written here.";
    wrapper.appendChild(notice);

    const gatePanel = document.createElement("avl-panel");
    gatePanel.setAttribute("title", "Dataset access gate");
    if (this._gate) {
      const summary = document.createElement("div");
      summary.className = "gate-row";
      const label = document.createElement("span");
      label.textContent = `${this._gate.unsatisfied_count} of ${this._gate.conditions.length} conditions unsatisfied`;
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "core");
      badge.setAttribute("state", this._gate.access_allowed ? "ready" : "attention");
      summary.append(label, badge);
      gatePanel.appendChild(summary);
      const note = document.createElement("p");
      note.className = "avl-type-caption";
      note.textContent = this._gate.note;
      gatePanel.appendChild(note);
    } else {
      const notEvaluated = document.createElement("p");
      notEvaluated.className = "avl-type-body-small";
      notEvaluated.textContent =
        "Gate not evaluated in this session. Run `python scripts/export_dataset_gate_status.py` " +
        "(read-only — inspects Git/config state only, never audio) to check.";
      gatePanel.appendChild(notEvaluated);
    }
    wrapper.appendChild(gatePanel);

    const dropZone = document.createElement("avl-import-drop-zone");
    dropZone.addEventListener("avl-files-selected", (event) => {
      this._files = event.detail.files;
      this._render();
    });
    wrapper.appendChild(dropZone);

    const queue = document.createElement("div");
    queue.className = "queue";
    if (!this._files.length) {
      const empty = document.createElement("p");
      empty.className = "avl-type-body-small";
      empty.textContent = "No files queued.";
      queue.appendChild(empty);
    } else {
      for (const file of this._files) {
        const item = document.createElement("div");
        item.className = "queue-item";
        const name = document.createElement("span");
        name.textContent = file.name;
        const badge = document.createElement("avl-status-badge");
        badge.setAttribute("domain", "core");
        badge.setAttribute("state", "attention");
        item.append(name, badge);
        queue.appendChild(item);
      }
      const note = document.createElement("p");
      note.className = "avl-type-caption";
      note.textContent = "Listed only — VL-D1 does not hash, validate, or import these files. See VL-D2.";
      queue.appendChild(note);
    }
    wrapper.appendChild(queue);

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-import", AvlWorkspaceImport);
