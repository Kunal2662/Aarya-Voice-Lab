// <avl-voice-preview-card> — set `.artifact` (PreviewArtifact.to_dict()
// shape) and optionally `.feedback` (PreviewFeedback.to_dict() shape, or
// null if no feedback yet). Wraps avl-voice-player + avl-voice-status +
// avl-card. The single card used everywhere a preview needs to be shown.
import { AvlElement, defineComponent } from "./base-element.js";
import "./card.js";
import "./voice-player.js";
import "./voice-status.js";

export class AvlVoicePreviewCard extends AvlElement {
  set artifact(value) {
    this._artifact = value || null;
    if (this.isConnected) this._render();
  }

  get artifact() {
    return this._artifact || null;
  }

  set feedback(value) {
    this._feedback = value || null;
    if (this.isConnected) this._render();
  }

  get feedback() {
    return this._feedback || null;
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
    `;
    this.shadowRoot.appendChild(style);

    const card = document.createElement("avl-card");

    const header = document.createElement("div");
    header.slot = "header";
    header.className = "header";
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = this._artifact ? `Preview · iteration ${this._artifact.iteration ?? 1}` : "Preview";
    header.appendChild(title);

    const status = document.createElement("avl-voice-status");
    status.feedback = this._feedback;
    header.appendChild(status);

    const player = document.createElement("avl-voice-player");
    player.artifact = this._artifact;

    card.append(header, player);
    this.shadowRoot.appendChild(card);
  }
}

defineComponent("avl-voice-preview-card", AvlVoicePreviewCard);
