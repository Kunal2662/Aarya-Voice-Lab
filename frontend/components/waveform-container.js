// <avl-waveform-container> — UI-only. No audio engine, no decoding, no
// playback logic. Renders a static placeholder unless given `peaks` (an
// array of 0..1 floats) via the `.peaks` property, in which case it draws
// them as bars. This is the visual contract a future real waveform
// renderer (VL-D2+) fills in; it must never claim to represent audio it
// hasn't been given.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlWaveformContainer extends AvlElement {
  static get observedAttributes() {
    return ["label"];
  }

  set peaks(values) {
    this._peaks = Array.isArray(values) ? values : null;
    if (this.isConnected) this._render();
  }

  get peaks() {
    return this._peaks || null;
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const label = this.getAttribute("label") || "Waveform";

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .frame {
        display: flex; align-items: flex-end; gap: 2px;
        height: 4rem; padding: var(--avl-space-2);
        background: var(--avl-color-surface-sunken);
        border: 1px solid var(--avl-color-border-subtle);
        border-radius: var(--avl-radius-sm);
      }
      .bar { flex: 1; background: var(--avl-color-brand-accent); min-width: 2px; border-radius: 1px; }
      .placeholder {
        flex: 1; display: flex; align-items: center; justify-content: center;
        color: var(--avl-color-text-muted);
        font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family);
      }
    `;
    this.shadowRoot.appendChild(style);

    const frame = document.createElement("div");
    frame.className = "frame";
    frame.setAttribute("role", "img");
    frame.setAttribute("aria-label", this._peaks ? `${label} waveform` : `${label}: no waveform data available`);

    if (this._peaks && this._peaks.length) {
      for (const value of this._peaks) {
        const bar = document.createElement("div");
        bar.className = "bar";
        const clamped = Math.max(0, Math.min(1, Number(value) || 0));
        bar.style.height = `${Math.max(4, clamped * 100)}%`;
        frame.appendChild(bar);
      }
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "placeholder";
      placeholder.textContent = "No waveform data";
      frame.appendChild(placeholder);
    }

    this.shadowRoot.appendChild(frame);
  }
}

defineComponent("avl-waveform-container", AvlWaveformContainer);
