// <avl-audio-player> — VL-D3 §9. Real HTML5 <audio> playback of a
// synthetic tone (state/synthetic-tone.js) standing in for the selected
// recording — this project has no real recording to play, and never
// will until the dataset access gate is satisfied. Controls: play,
// pause, stop, seek, position, duration, volume. Never autoplays. Never
// loops into an automatic queue — one recording, one manual play.
import { AvlElement, defineComponent } from "./base-element.js";
import { buildSyntheticToneWavUrl } from "../state/synthetic-tone.js";
import "./button.js";

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export class AvlAudioPlayer extends AvlElement {
  static get observedAttributes() {
    return ["recording-id", "duration-seconds"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback(name) {
    if (!this.isConnected) return;
    if (name === "recording-id") this._loadSource();
    this._render();
  }

  disconnectedCallback() {
    if (this._objectUrl) URL.revokeObjectURL(this._objectUrl);
  }

  _loadSource() {
    if (this._objectUrl) URL.revokeObjectURL(this._objectUrl);
    const recordingId = this.getAttribute("recording-id") || "none";
    // Deterministic per recording id, so re-selecting the same recording
    // sounds the same, without claiming this is that recording's audio.
    const seed = recordingId.split("").reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
    const durationSeconds = Math.min(Number(this.getAttribute("duration-seconds")) || 3, 8);
    this._objectUrl = buildSyntheticToneWavUrl({
      frequencyHz: 220 + (seed % 220),
      durationSeconds,
      amplitude: 0.35,
    });
  }

  _render() {
    if (!this._objectUrl) this._loadSource();

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .player { display: flex; align-items: center; gap: var(--avl-space-2); flex-wrap: wrap; }
      .controls { display: flex; gap: var(--avl-space-1); }
      input[type="range"] { flex: 1; min-width: 8rem; }
      .time { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); min-width: 5.5em; text-align: right; }
      .volume { display: flex; align-items: center; gap: var(--avl-space-1); }
      .volume input { width: 4rem; }
      .note { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("div");

    const audio = document.createElement("audio");
    audio.src = this._objectUrl;
    audio.preload = "metadata";
    // Explicitly never autoplay (VL-D3 §9).
    audio.autoplay = false;
    audio.loop = false;

    const player = document.createElement("div");
    player.className = "player";

    const controls = document.createElement("div");
    controls.className = "controls";

    const playButton = document.createElement("avl-button");
    playButton.setAttribute("variant", "primary");
    playButton.textContent = "Play";
    playButton.addEventListener("click", () => {
      if (audio.paused) audio.play();
      else audio.pause();
    });

    const stopButton = document.createElement("avl-button");
    stopButton.setAttribute("variant", "secondary");
    stopButton.textContent = "Stop";
    stopButton.addEventListener("click", () => {
      audio.pause();
      audio.currentTime = 0;
    });

    controls.append(playButton, stopButton);

    const seek = document.createElement("input");
    seek.type = "range";
    seek.min = "0";
    seek.max = "100";
    seek.value = "0";
    seek.setAttribute("aria-label", "Seek");
    seek.addEventListener("input", () => {
      if (audio.duration) audio.currentTime = (Number(seek.value) / 100) * audio.duration;
    });

    const time = document.createElement("span");
    time.className = "time";
    time.textContent = "0:00 / 0:00";

    const volumeWrap = document.createElement("div");
    volumeWrap.className = "volume";
    const volumeLabel = document.createElement("span");
    volumeLabel.className = "avl-sr-only";
    volumeLabel.textContent = "Volume";
    const volume = document.createElement("input");
    volume.type = "range";
    volume.min = "0";
    volume.max = "100";
    volume.value = "80";
    volume.setAttribute("aria-label", "Volume");
    volume.addEventListener("input", () => {
      audio.volume = Number(volume.value) / 100;
    });
    volumeWrap.append(volumeLabel, volume);

    audio.addEventListener("play", () => {
      playButton.textContent = "Pause";
      this._announce("Playing");
    });
    audio.addEventListener("pause", () => {
      playButton.textContent = "Play";
    });
    audio.addEventListener("timeupdate", () => {
      if (audio.duration) seek.value = String((audio.currentTime / audio.duration) * 100);
      time.textContent = `${formatTime(audio.currentTime)} / ${formatTime(audio.duration)}`;
    });
    audio.addEventListener("loadedmetadata", () => {
      time.textContent = `${formatTime(audio.currentTime)} / ${formatTime(audio.duration)}`;
    });

    player.append(controls, seek, time, volumeWrap);

    const note = document.createElement("div");
    note.className = "note";
    note.textContent = "Synthetic tone (not a real recording) — playback preview only.";

    wrapper.append(player, note);
    this.shadowRoot.append(audio, wrapper);
    this._audioEl = audio;
  }
}

defineComponent("avl-audio-player", AvlAudioPlayer);
