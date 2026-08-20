// <avl-dataset-quality-summary> — VL-D3 §18. Renders
// state/quality-summary.js's summarizeQuality() output as plain text
// tables — no charting library, no canvas, nothing beyond what this
// project's zero-dependency component set already provides.
import { AvlElement, defineComponent } from "./base-element.js";
import "./card.js";
import "./metric-placeholder.js";

function distributionTable(title, distribution) {
  const wrapper = document.createElement("div");
  const heading = document.createElement("h4");
  heading.textContent = title;
  wrapper.appendChild(heading);

  const entries = Object.entries(distribution);
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "avl-type-caption";
    empty.textContent = "No data.";
    wrapper.appendChild(empty);
    return wrapper;
  }

  const list = document.createElement("ul");
  for (const [key, count] of entries) {
    const item = document.createElement("li");
    item.textContent = `${key}: ${count}`;
    list.appendChild(item);
  }
  wrapper.appendChild(list);
  return wrapper;
}

export class AvlDatasetQualitySummary extends AvlElement {
  set summary(value) {
    this._summary = value || null;
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
      .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr)); gap: var(--avl-space-3); }
      h4 { margin: 0 0 var(--avl-space-1) 0; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; color: var(--avl-color-text-secondary); }
      ul { margin: 0; padding: 0; list-style: none; font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      li { padding: 0.1rem 0; }
      .top { display: flex; gap: var(--avl-space-4); flex-wrap: wrap; margin-bottom: var(--avl-space-3); }
    `;
    this.shadowRoot.appendChild(style);

    const card = document.createElement("avl-card");
    const header = document.createElement("span");
    header.slot = "header";
    header.className = "avl-type-subheading";
    header.textContent = "Dataset Quality Summary";
    card.appendChild(header);

    if (!this._summary || !this._summary.recordingCount) {
      const empty = document.createElement("p");
      empty.className = "avl-type-body-small";
      empty.textContent = "No recordings to summarize.";
      card.appendChild(empty);
      this.shadowRoot.appendChild(card);
      return;
    }

    const s = this._summary;

    const top = document.createElement("div");
    top.className = "top";
    for (const [label, value, unit] of [
      ["Average duration", s.averageDurationSeconds != null ? s.averageDurationSeconds.toFixed(1) : null, "s"],
      ["Median duration", s.medianDurationSeconds != null ? s.medianDurationSeconds.toFixed(1) : null, "s"],
      ["Narrowband recordings", s.narrowbandCount, ""],
      ["Overlap candidates", s.overlapCandidateCount, ""],
    ]) {
      const metric = document.createElement("avl-metric-placeholder");
      metric.setAttribute("label", label);
      if (value !== null && value !== undefined) {
        metric.setAttribute("value", String(value));
        if (unit) metric.setAttribute("unit", unit);
      }
      top.appendChild(metric);
    }
    card.appendChild(top);

    const grid = document.createElement("div");
    grid.className = "grid";
    grid.appendChild(distributionTable("Quality decision", s.decisionDistribution));
    grid.appendChild(distributionTable("Duration", s.durationDistribution));
    grid.appendChild(distributionTable("Sample rate", s.sampleRateDistribution));
    grid.appendChild(distributionTable("Channels", s.channelDistribution));
    grid.appendChild(distributionTable("SNR", s.snrDistribution));
    grid.appendChild(distributionTable("Speech ratio", s.speechRatioDistribution));
    grid.appendChild(distributionTable("Silence ratio", s.silenceRatioDistribution));
    grid.appendChild(distributionTable("Warning codes", s.warningCodeDistribution));
    card.appendChild(grid);

    this.shadowRoot.appendChild(card);
  }
}

defineComponent("avl-dataset-quality-summary", AvlDatasetQualitySummary);
