// <avl-quality-profile> — VL-D3 §17. Set `.assessment` to a
// state/synthetic-fixtures.js syntheticQualityAssessments() entry (or,
// later, a real pipeline.quality.QualityAssessment.to_dict()). Renders
// exactly the sections the spec lists — Signal / Noise / Speech / Format
// / Characteristics / Flags — and nothing else; every value comes from
// the assessment object, never computed here. No `.assessment` set
// yields the honest NOT_ANALYZED state (via the "quality_decision"
// domain's UI-only addition), not a blank panel.
import { AvlElement, defineComponent } from "./base-element.js";
import "./card.js";
import "./status-badge.js";
import "./metric-placeholder.js";

export class AvlQualityProfile extends AvlElement {
  set assessment(value) {
    this._assessment = value || null;
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
      .title { font: var(--avl-type-subheading-weight) var(--avl-type-subheading-size) / var(--avl-type-subheading-line-height) var(--avl-type-subheading-family); }
      section { margin-top: var(--avl-space-3); }
      section h4 { margin: 0 0 var(--avl-space-1) 0; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; color: var(--avl-color-text-secondary); }
      .flags { display: flex; flex-wrap: wrap; gap: var(--avl-space-1); }
      .flag { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); padding: var(--avl-space-1) var(--avl-space-2); border-radius: var(--avl-radius-pill); border: 1px solid var(--avl-color-state-warning); color: var(--avl-color-state-warning); }
      .characteristic { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); color: var(--avl-color-text-secondary); }
    `;
    this.shadowRoot.appendChild(style);

    const card = document.createElement("avl-card");
    const header = document.createElement("div");
    header.slot = "header";
    header.className = "header";
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = "Quality";
    const badge = document.createElement("avl-status-badge");
    badge.setAttribute("domain", "quality_decision");
    badge.setAttribute("state", this._assessment ? this._assessment.decision : "NOT_ANALYZED");
    header.append(title, badge);
    card.appendChild(header);

    if (!this._assessment) {
      const empty = document.createElement("p");
      empty.className = "avl-type-body-small";
      empty.textContent = "This recording has not been analyzed yet.";
      card.appendChild(empty);
      this.shadowRoot.appendChild(card);
      return;
    }

    const m = this._assessment.measurements || {};
    const speech = this._assessment.speech || {};

    const signal = document.createElement("section");
    signal.innerHTML = "<h4>Signal</h4>";
    for (const [label, value, unit] of [
      ["RMS", m.rmsDbfs, "dBFS"],
      ["Peak", m.peakDbfs, "dBFS"],
      ["Crest factor", m.crestFactorDb, "dB"],
    ]) {
      signal.appendChild(this._metric(label, value, unit));
    }
    card.appendChild(signal);

    const noise = document.createElement("section");
    noise.innerHTML = "<h4>Noise</h4>";
    noise.appendChild(this._metric("Estimated floor", m.noiseFloorDbfs, "dBFS"));
    noise.appendChild(this._metric("Estimated SNR", m.estimatedSnrDb, "dB"));
    card.appendChild(noise);

    const speechSection = document.createElement("section");
    speechSection.innerHTML = "<h4>Speech</h4>";
    speechSection.appendChild(this._metric("Speech ratio", speech.speechRatio != null ? (speech.speechRatio * 100).toFixed(1) : null, "%"));
    speechSection.appendChild(this._metric("Silence ratio", m.silentFrameRatio != null ? (m.silentFrameRatio * 100).toFixed(1) : null, "%"));
    card.appendChild(speechSection);

    const format = document.createElement("section");
    format.innerHTML = "<h4>Format</h4>";
    format.appendChild(this._metric("Sample rate", m.sampleRate, "Hz"));
    format.appendChild(this._metric("Duration", m.durationSeconds, "s"));
    card.appendChild(format);

    const characteristics = document.createElement("section");
    characteristics.innerHTML = "<h4>Characteristics</h4>";
    const narrowband = document.createElement("div");
    narrowband.className = "characteristic";
    narrowband.textContent = `Narrowband: ${(this._assessment.characteristics || []).some((c) => c.includes("narrowband")) ? "YES" : "NO"}`;
    const clipping = document.createElement("div");
    clipping.className = "characteristic";
    clipping.textContent = `Clipping risk: ${m.clippingRatio > 0 ? "YES" : "NO"}`;
    characteristics.append(narrowband, clipping);
    card.appendChild(characteristics);

    if (this._assessment.findings && this._assessment.findings.length) {
      const flagsSection = document.createElement("section");
      flagsSection.innerHTML = "<h4>Flags</h4>";
      const flags = document.createElement("div");
      flags.className = "flags";
      for (const finding of this._assessment.findings) {
        const flag = document.createElement("span");
        flag.className = "flag";
        flag.textContent = finding.code.toUpperCase();
        flag.title = finding.message;
        flags.appendChild(flag);
      }
      flagsSection.appendChild(flags);
      card.appendChild(flagsSection);
    }

    this.shadowRoot.appendChild(card);
  }

  _metric(label, value, unit) {
    const metric = document.createElement("avl-metric-placeholder");
    metric.setAttribute("label", label);
    if (value !== null && value !== undefined) {
      metric.setAttribute("value", String(value));
      metric.setAttribute("unit", unit);
    }
    return metric;
  }
}

defineComponent("avl-quality-profile", AvlQualityProfile);
