// <avl-meter label="Pipeline" value="9" max="24" tone="blue" detail="9 of 24 stages">
// FE-2.1 -- a horizontal progress bar for the rare cases where a real
// percentage exists (e.g. "stages completed / total stages" -- both
// already real counts elsewhere in the app). Per FE-2's explicit
// ground rules, this is NOT a live/animated gauge and must never be
// used for a measurement nothing computes (CPU load %, GPU
// utilization %, etc. stay on avl-hardware-profile-card's honest
// AVAILABLE/UNKNOWN/NOT MEASURED badges instead -- see
// FE2_VISUAL_REDESIGN.md). Omitting `value` or `max` renders "Not
// measured" instead of a bar at 0%, matching every other honest-
// fallback primitive in this app (avl-metric-placeholder,
// avl-stat-tile).
import { AvlElement, defineComponent } from "./base-element.js";

const TONES = ["violet", "blue", "green", "pink", "teal"];

export class AvlMeter extends AvlElement {
  static get observedAttributes() {
    return ["label", "value", "max", "tone", "detail"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const label = this.getAttribute("label") || "";
    const tone = TONES.includes(this.getAttribute("tone")) ? this.getAttribute("tone") : "blue";
    const detail = this.getAttribute("detail") || "";
    const rawValue = this.getAttribute("value");
    const rawMax = this.getAttribute("max");
    const value = rawValue === null || rawValue === "" ? null : Number(rawValue);
    const max = rawMax === null || rawMax === "" ? null : Number(rawMax);
    const hasMeasurement = value !== null && max !== null && Number.isFinite(value) && Number.isFinite(max) && max > 0;
    const percent = hasMeasurement ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .row { display: flex; justify-content: space-between; align-items: baseline; gap: var(--avl-space-2); margin-bottom: var(--avl-space-1); }
      .label { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      .percent { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-primary); font-variant-numeric: tabular-nums; }
      .unmeasured { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); color: var(--avl-color-text-disabled); font-style: italic; }
      .track { height: 0.4rem; border-radius: var(--avl-radius-pill); background: var(--avl-color-surface-sunken); overflow: hidden; }
      .fill { height: 100%; border-radius: var(--avl-radius-pill); background: var(--avl-tone-fg); transition: width var(--avl-duration-base) var(--avl-easing-standard); }
      .violet { --avl-tone-fg: var(--avl-color-category-violet); }
      .blue   { --avl-tone-fg: var(--avl-color-category-blue); }
      .green  { --avl-tone-fg: var(--avl-color-category-green); }
      .pink   { --avl-tone-fg: var(--avl-color-category-pink); }
      .teal   { --avl-tone-fg: var(--avl-color-category-teal); }
      .detail { margin-top: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-muted); }
    `;
    this.shadowRoot.appendChild(style);

    const row = document.createElement("div");
    row.className = "row";
    const labelEl = document.createElement("span");
    labelEl.className = "label";
    labelEl.textContent = label;
    row.appendChild(labelEl);

    if (hasMeasurement) {
      const percentEl = document.createElement("span");
      percentEl.className = "percent";
      percentEl.textContent = `${Math.round(percent)}%`;
      row.appendChild(percentEl);
    }
    this.shadowRoot.appendChild(row);

    if (hasMeasurement) {
      const track = document.createElement("div");
      track.className = "track";
      track.setAttribute("role", "progressbar");
      track.setAttribute("aria-valuenow", String(Math.round(percent)));
      track.setAttribute("aria-valuemin", "0");
      track.setAttribute("aria-valuemax", "100");
      track.setAttribute("aria-label", label);
      const fill = document.createElement("div");
      fill.className = `fill ${tone}`;
      fill.style.width = `${percent}%`;
      track.appendChild(fill);
      this.shadowRoot.appendChild(track);
    } else {
      const unmeasured = document.createElement("span");
      unmeasured.className = "unmeasured";
      unmeasured.textContent = "Not measured";
      this.shadowRoot.appendChild(unmeasured);
    }

    if (detail) {
      const detailEl = document.createElement("div");
      detailEl.className = "detail";
      detailEl.textContent = detail;
      this.shadowRoot.appendChild(detailEl);
    }
  }
}

defineComponent("avl-meter", AvlMeter);
