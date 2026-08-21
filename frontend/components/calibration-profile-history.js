// <avl-calibration-profile-history> -- VL-D7. Set `.calibrationStore` (a
// state/calibration-engine-model.js CalibrationProfileStore) and
// optionally `.selectionModel` (VL-D8 -- clicking a row selects that
// profile into the Inspector, kind "calibration-profile"). Lists every
// calibration run, oldest first, with a "Roll back to this" action on
// any non-current profile -- rollback never deletes or edits, it
// appends a new record, so every prior entry stays listed here
// afterward. Mirrors avl-processing-history-panel's exact pattern.
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";
import "./button.js";

export class AvlCalibrationProfileHistory extends AvlElement {
  set calibrationStore(value) {
    if (this._calibrationStore) this._calibrationStore.removeEventListener("change", this._onChange);
    this._calibrationStore = value;
    if (value) {
      this._onChange = () => this._render();
      value.addEventListener("change", this._onChange);
    }
    if (this.isConnected) this._render();
  }

  set selectionModel(value) {
    this._selectionModel = value || null;
  }

  connectedCallback() {
    this._render();
  }

  disconnectedCallback() {
    if (this._calibrationStore) this._calibrationStore.removeEventListener("change", this._onChange);
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--avl-space-2); }
      li { border: 1px solid var(--avl-color-border-subtle); border-radius: var(--avl-radius-sm); padding: var(--avl-space-2); }
      .row { display: flex; justify-content: space-between; align-items: center; gap: var(--avl-space-2); flex-wrap: wrap; }
      .meta { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-1); }
      .current { border-color: var(--avl-color-brand-accent); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._calibrationStore || !this._calibrationStore.history().length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No calibration runs yet.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const records = this._calibrationStore.history();
    const current = this._calibrationStore.current();
    const list = document.createElement("ul");
    for (const record of records) {
      const item = document.createElement("li");
      const isCurrent = current && current.profile_id === record.profile_id;
      if (isCurrent) item.className = "current";

      const row = document.createElement("div");
      row.className = "row";
      const label = document.createElement("span");
      label.textContent = `${record.profile_id} (v${record.profile_version})${record.is_rollback ? " — rollback" : ""}`;
      if (this._selectionModel) {
        label.style.cursor = "pointer";
        label.style.textDecoration = "underline";
        label.addEventListener("click", () => this._selectionModel.select("calibration-profile", record.profile_id, record));
      }
      row.appendChild(label);

      const badges = document.createElement("div");
      badges.style.display = "flex";
      badges.style.gap = "var(--avl-space-2)";
      const runBadge = document.createElement("avl-status-badge");
      runBadge.setAttribute("domain", "hardware_calibration");
      runBadge.setAttribute("state", record.run_state);
      const evidenceBadge = document.createElement("avl-status-badge");
      evidenceBadge.setAttribute("domain", "calibration");
      evidenceBadge.setAttribute("state", record.calibration_state);
      badges.append(runBadge, evidenceBadge);
      row.appendChild(badges);
      item.appendChild(row);

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent =
        `strategy ${record.strategy} — application ${record.application_state || "PROPOSED"} — ${record.created_at}` +
        (record.applied_from_profile_id ? ` — applied from ${record.applied_from_profile_id}` : "") +
        (record.supersedes ? ` — supersedes ${record.supersedes}` : "") +
        (isCurrent ? " — active" : "");
      item.appendChild(meta);

      if (!isCurrent) {
        const rollbackButton = document.createElement("avl-button");
        rollbackButton.setAttribute("variant", "secondary");
        rollbackButton.textContent = "Roll back to this";
        rollbackButton.addEventListener("click", () => {
          this._calibrationStore.rollback(record.profile_id);
        });
        item.appendChild(rollbackButton);
      }

      list.appendChild(item);
    }
    this.shadowRoot.appendChild(list);
  }
}

defineComponent("avl-calibration-profile-history", AvlCalibrationProfileHistory);
