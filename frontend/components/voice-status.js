// <avl-voice-status> — set `.feedback` to a PreviewFeedback.to_dict()
// shape, or null/undefined for "no feedback yet". Renders through the
// shared status vocabulary (domain "voice"); never invents its own labels.
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";

const OUTCOME_TO_VOICE_STATE = {
  accepted: "accepted",
  rejected: "rejected",
  regenerate: "review-required",
  uncertain: "review-required",
};

export class AvlVoiceStatus extends AvlElement {
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

    const badge = document.createElement("avl-status-badge");
    badge.setAttribute("domain", "voice");
    const state = this._feedback ? OUTCOME_TO_VOICE_STATE[this._feedback.outcome] || "processing" : "idle";
    badge.setAttribute("state", state);

    this.shadowRoot.appendChild(badge);
  }
}

defineComponent("avl-voice-status", AvlVoiceStatus);
