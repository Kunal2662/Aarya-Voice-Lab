// <avl-playback-controls duration-seconds="12.5" disabled>
// UI transport only — play/pause/seek. Dispatches avl-play / avl-pause /
// avl-seek events; owns no <audio> element and decodes nothing. A real
// player (voice-player.js) or a future host wires an actual audio engine
// to these events.
import { AvlElement, defineComponent } from "./base-element.js";

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export class AvlPlaybackControls extends AvlElement {
  static get observedAttributes() {
    return ["duration-seconds", "disabled", "position-seconds"];
  }

  connectedCallback() {
    this._playing = false;
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const duration = Number(this.getAttribute("duration-seconds")) || 0;
    const position = Number(this.getAttribute("position-seconds")) || 0;
    const disabled = this.hasAttribute("disabled");

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .controls { display: flex; align-items: center; gap: var(--avl-space-2); }
      button {
        background: var(--avl-color-surface-raised); border: 1px solid var(--avl-color-border-default);
        border-radius: var(--avl-radius-pill); width: 2rem; height: 2rem; cursor: pointer;
        color: var(--avl-color-text-primary);
      }
      button:disabled { opacity: 0.5; cursor: not-allowed; }
      input[type="range"] { flex: 1; }
      .time { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); min-width: 5.5em; text-align: right; }
    `;
    this.shadowRoot.appendChild(style);

    const controls = document.createElement("div");
    controls.className = "controls";

    const playButton = document.createElement("button");
    playButton.type = "button";
    playButton.disabled = disabled;
    playButton.setAttribute("aria-label", this._playing ? "Pause" : "Play");
    playButton.textContent = this._playing ? "⏸" : "▶";
    playButton.addEventListener("click", () => {
      this._playing = !this._playing;
      this.dispatchEvent(
        new CustomEvent(this._playing ? "avl-play" : "avl-pause", { bubbles: true, composed: true }),
      );
      this._render();
    });

    const seek = document.createElement("input");
    seek.type = "range";
    seek.min = "0";
    seek.max = String(Math.max(duration, 0.01));
    seek.step = "0.01";
    seek.value = String(Math.min(position, duration));
    seek.disabled = disabled || duration === 0;
    seek.setAttribute("aria-label", "Seek");
    seek.addEventListener("input", () => {
      this.dispatchEvent(
        new CustomEvent("avl-seek", { detail: { positionSeconds: Number(seek.value) }, bubbles: true, composed: true }),
      );
    });

    const time = document.createElement("span");
    time.className = "time";
    time.textContent = `${formatTime(position)} / ${formatTime(duration)}`;

    controls.append(playButton, seek, time);
    this.shadowRoot.appendChild(controls);
  }
}

defineComponent("avl-playback-controls", AvlPlaybackControls);
