// <avl-calibration-parameter-adjustments> -- VL-D7. Set `.adjustments`
// to an array shaped like
// pipeline.calibration_engine.CalibrationParameterAdjustment.to_dict().
// Every row shows the bounds and rationale alongside the proposed value
// -- never just a bare number. All values shown here already passed
// bounds validation before this component ever saw them
// (buildParameterAdjustment throws on an out-of-bounds proposal), so
// this is a display surface only, not a second validation layer.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlCalibrationParameterAdjustments extends AvlElement {
  set adjustments(value) {
    this._adjustments = Array.isArray(value) ? value : [];
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); vertical-align: top; }
      th { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; }
      .rationale { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    const adjustments = this._adjustments || [];
    if (!adjustments.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No parameter adjustments proposed.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Parameter</th><th>Previous</th><th>Proposed</th><th>Bounds</th><th>Rationale / evidence</th></tr>";
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const adjustment of adjustments) {
      const row = document.createElement("tr");
      const rationaleCell = document.createElement("td");
      rationaleCell.className = "rationale";
      rationaleCell.textContent = `${adjustment.rationale} (${adjustment.evidence_reference})`;
      row.innerHTML = `
        <td>${adjustment.parameter_name}</td>
        <td>${adjustment.previous_value}</td>
        <td>${adjustment.proposed_value}</td>
        <td>[${adjustment.min_bound}, ${adjustment.max_bound}]</td>
      `;
      row.appendChild(rationaleCell);
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    this.shadowRoot.appendChild(table);
  }
}

defineComponent("avl-calibration-parameter-adjustments", AvlCalibrationParameterAdjustments);
