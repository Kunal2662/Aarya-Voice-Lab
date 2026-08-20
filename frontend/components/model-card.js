// <avl-model-card> — set `.model` to a model-shaped object (see
// state/synthetic-fixtures.js syntheticModels()). Vendor-neutral: backend
// field is a generic label (cpu/cuda/rocm/...), never a specific product.
import { AvlElement, defineComponent } from "./base-element.js";
import "./card.js";
import "./status-badge.js";
import "./metric-placeholder.js";

export class AvlModelCard extends AvlElement {
  set model(value) {
    this._model = value || null;
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
      .header { display: flex; justify-content: space-between; align-items: center; }
      .name { font: var(--avl-type-subheading-weight) var(--avl-type-subheading-size) / var(--avl-type-subheading-line-height) var(--avl-type-subheading-family); }
    `;
    this.shadowRoot.appendChild(style);

    const model = this._model;
    if (!model) return;

    const card = document.createElement("avl-card");
    const header = document.createElement("div");
    header.slot = "header";
    header.className = "header";
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = `${model.name} (${model.version})`;
    const badge = document.createElement("avl-status-badge");
    badge.setAttribute("domain", "hardware");
    badge.setAttribute("state", (model.status || "unknown").toUpperCase());
    header.append(name, badge);
    card.appendChild(header);

    for (const [label, value] of [
      ["Runtime", model.runtime],
      ["Backend", model.backend],
      ["Hardware compatibility", model.hardwareCompatible],
    ]) {
      const metric = document.createElement("avl-metric-placeholder");
      metric.setAttribute("label", label);
      if (value && value !== "unknown" && value !== "not_installed") metric.setAttribute("value", String(value));
      card.appendChild(metric);
    }

    const calibration = document.createElement("avl-status-badge");
    calibration.setAttribute("domain", "calibration");
    calibration.setAttribute("state", model.calibrationState || "UNCALIBRATED");
    card.appendChild(calibration);

    this.shadowRoot.appendChild(card);
  }
}

defineComponent("avl-model-card", AvlModelCard);
