// <avl-pixel-sprite motif="idle-orb|calibration-glyph|..." animated>
// Purely decorative/environmental. Always aria-hidden — this component
// must never be the sole carrier of information; anything it echoes
// (state, progress) must also be stated in real text elsewhere. Renders
// a small deterministic pixel-grid pattern from a named motif so no
// image assets need to ship in VL-D0.
import { AvlElement, defineComponent } from "./base-element.js";

// 8x8 boolean grids. 1 = pixel-accent color, 0 = transparent.
const MOTIFS = {
  "idle-orb": [
    "00111100",
    "01111110",
    "11111111",
    "11111111",
    "11111111",
    "11111111",
    "01111110",
    "00111100",
  ],
  "calibration-glyph": [
    "00011000",
    "00111100",
    "01100110",
    "11000011",
    "11000011",
    "01100110",
    "00111100",
    "00011000",
  ],
  "waveform-motif": [
    "00000000",
    "01000010",
    "01011010",
    "01111110",
    "01111110",
    "01011010",
    "01000010",
    "00000000",
  ],
};

export class AvlPixelSprite extends AvlElement {
  static get observedAttributes() {
    return ["motif", "animated"];
  }

  connectedCallback() {
    this.setAttribute("aria-hidden", "true");
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const motif = MOTIFS[this.getAttribute("motif")] ? this.getAttribute("motif") : "idle-orb";
    const animated = this.hasAttribute("animated");
    const grid = MOTIFS[motif];

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      :host { display: inline-block; }
      .grid {
        display: grid;
        grid-template-columns: repeat(8, 3px);
        grid-template-rows: repeat(8, 3px);
        image-rendering: pixelated;
        animation: ${animated ? "avl-pixel-pulse var(--avl-duration-deliberate) ease-in-out infinite alternate" : "none"};
      }
      .cell { width: 3px; height: 3px; }
      .on { background: var(--avl-color-pixel-accent-primary); }
      @keyframes avl-pixel-pulse { from { opacity: 0.55; } to { opacity: 1; } }
    `;
    this.shadowRoot.appendChild(style);

    const container = document.createElement("div");
    container.className = "grid";
    for (const row of grid) {
      for (const bit of row) {
        const cell = document.createElement("div");
        cell.className = bit === "1" ? "cell on" : "cell";
        container.appendChild(cell);
      }
    }
    this.shadowRoot.appendChild(container);
  }
}

defineComponent("avl-pixel-sprite", AvlPixelSprite);
