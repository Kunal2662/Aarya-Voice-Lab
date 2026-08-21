// <avl-metric-placeholder label="..." value="...">
// The one place every "we don't have a real number yet" metric in the
// app renders through. Omitting `value` renders "Not available" rather
// than 0, "N/A" text buried in a real-looking number, or any other shape
// that could be mistaken for a measurement. Used by calibration,
// hardware, and accent panels alike.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlMetricPlaceholder extends AvlElement {
  static get observedAttributes() {
    return ["label", "value", "unit"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const label = this.getAttribute("label") || "Metric";
    const hasValue = this.hasAttribute("value") && this.getAttribute("value") !== "";
    const value = this.getAttribute("value");
    const unit = this.getAttribute("unit") || "";

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .metric { display: flex; justify-content: space-between; gap: var(--avl-space-2); padding: var(--avl-space-1) 0; }
      .label { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); }
      /* FE-1.6 -- tabular-nums keeps a column of metric values visually
         aligned (digits share a fixed width) instead of each row's
         width drifting with its digits, a small but real "precision
         instrument" touch appropriate for a measurement display; the
         font/size/weight/family are all still token-driven, unchanged. */
      .value { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); font-variant-numeric: tabular-nums; }
      .unavailable { color: var(--avl-color-text-disabled); font-style: italic; }
    `;
    this.shadowRoot.appendChild(style);

    const metric = document.createElement("div");
    metric.className = "metric";

    const labelEl = document.createElement("span");
    labelEl.className = "label";
    labelEl.textContent = label;

    const valueEl = document.createElement("span");
    if (hasValue) {
      valueEl.className = "value";
      valueEl.textContent = unit ? `${value} ${unit}` : value;
    } else {
      valueEl.className = "value unavailable";
      valueEl.textContent = "Not available";
    }

    metric.append(labelEl, valueEl);
    this.shadowRoot.appendChild(metric);
  }
}

defineComponent("avl-metric-placeholder", AvlMetricPlaceholder);
