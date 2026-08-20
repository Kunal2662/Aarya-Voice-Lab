// <avl-voice-player> — set `.artifact` to a PreviewArtifact-shaped object
// (aarya_voice_lab.identity.preview.PreviewArtifact.to_dict()). Composes
// avl-waveform-container + avl-playback-controls; still no audio engine —
// this is the visual contract, not a player implementation.
import { AvlElement, defineComponent } from "./base-element.js";
import "./waveform-container.js";
import "./playback-controls.js";

export class AvlVoicePlayer extends AvlElement {
  set artifact(value) {
    this._artifact = value || null;
    if (this.isConnected) this._render();
  }

  get artifact() {
    return this._artifact || null;
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .player { display: flex; flex-direction: column; gap: var(--avl-space-2); }
      .meta { display: flex; justify-content: space-between; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      .synthetic-flag { color: var(--avl-color-voice-synthetic); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    const artifact = this._artifact;
    if (!artifact) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No preview loaded.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const player = document.createElement("div");
    player.className = "player";

    const waveform = document.createElement("avl-waveform-container");
    waveform.setAttribute("label", artifact.kind || "preview");

    const controls = document.createElement("avl-playback-controls");
    controls.setAttribute("duration-seconds", String(artifact.duration_seconds ?? 0));

    const meta = document.createElement("div");
    meta.className = "meta";
    const kindEl = document.createElement("span");
    kindEl.textContent = artifact.kind ? artifact.kind.replace(/_/g, " ") : "unknown kind";
    const flagEl = document.createElement("span");
    flagEl.className = "synthetic-flag";
    flagEl.textContent = artifact.is_synthetic ? "synthetic" : "real audio";
    meta.append(kindEl, flagEl);

    player.append(waveform, controls, meta);
    this.shadowRoot.appendChild(player);
  }
}

defineComponent("avl-voice-player", AvlVoicePlayer);
