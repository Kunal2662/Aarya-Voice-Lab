// <avl-stat-tile label="Datasets" value="4" unit="Total" tone="violet" icon="batches">
// FE-2.1 -- the dashboard-style summary tile for the denser visual
// language (Command Center and, later, other workspaces' own summary
// rows). Deliberately reuses avl-metric-placeholder's honest-fallback
// rule rather than inventing a new one: omitting `value` renders
// "Not available" in the same italic/muted treatment, never a
// fabricated 0 or a blank tile -- see FE1_FRONTEND_POLISH.md and
// FE2's own real-data-only ground rules for why this matters here
// specifically (several of the mockup's original numbers, like GPU
// utilization or a recording's private/shared split, have no real
// backing anywhere in this codebase and must never be invented).
//
// The default slot is an optional secondary detail line (e.g. "3
// Ready · 1 Processing"), left to the caller since only the caller
// knows which breakdown, if any, is real for that specific count.
import { AvlElement, defineComponent } from "./base-element.js";
import "./icon-badge.js";

export class AvlStatTile extends AvlElement {
  static get observedAttributes() {
    return ["label", "value", "unit", "tone", "icon"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const label = this.getAttribute("label") || "";
    const hasValue = this.hasAttribute("value") && this.getAttribute("value") !== "";
    const value = this.getAttribute("value");
    const unit = this.getAttribute("unit") || "";
    const tone = this.getAttribute("tone") || "blue";
    const icon = this.getAttribute("icon") || "";

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .tile {
        display: flex; flex-direction: column; gap: var(--avl-space-3);
        padding: var(--avl-space-4);
        background: var(--avl-color-surface-raised);
        border: 1px solid var(--avl-color-border-default);
        border-radius: var(--avl-radius-lg);
      }
      .top { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--avl-space-2); }
      .label { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; color: var(--avl-color-text-secondary); }
      .value-row { display: flex; align-items: baseline; gap: var(--avl-space-1); }
      .value { font: var(--avl-type-title-weight) var(--avl-type-title-size) / 1 var(--avl-type-title-family); color: var(--avl-color-text-primary); font-variant-numeric: tabular-nums; }
      .unavailable { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); color: var(--avl-color-text-disabled); font-style: italic; }
      .unit { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); color: var(--avl-color-text-muted); }
      .detail { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); color: var(--avl-color-text-secondary); }
    `;
    this.shadowRoot.appendChild(style);

    const tile = document.createElement("div");
    tile.className = "tile";

    const top = document.createElement("div");
    top.className = "top";

    const labelEl = document.createElement("span");
    labelEl.className = "label";
    labelEl.textContent = label;
    top.appendChild(labelEl);

    if (icon) {
      const badge = document.createElement("avl-icon-badge");
      badge.setAttribute("tone", tone);
      badge.setAttribute("icon", icon);
      top.appendChild(badge);
    }
    tile.appendChild(top);

    if (hasValue) {
      const valueRow = document.createElement("div");
      valueRow.className = "value-row";
      const valueEl = document.createElement("span");
      valueEl.className = "value";
      valueEl.textContent = value;
      valueRow.appendChild(valueEl);
      if (unit) {
        const unitEl = document.createElement("span");
        unitEl.className = "unit";
        unitEl.textContent = unit;
        valueRow.appendChild(unitEl);
      }
      tile.appendChild(valueRow);
    } else {
      const unavailable = document.createElement("span");
      unavailable.className = "unavailable";
      unavailable.textContent = "Not available";
      tile.appendChild(unavailable);
    }

    const detail = document.createElement("div");
    detail.className = "detail";
    detail.appendChild(document.createElement("slot"));
    tile.appendChild(detail);

    this.shadowRoot.appendChild(tile);
  }
}

defineComponent("avl-stat-tile", AvlStatTile);
