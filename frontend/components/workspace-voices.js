// <avl-workspace-voices> — VL-D1 §17. Voice profile/version/preview
// foundation, synthetic placeholders only (no real training, embeddings,
// or recordings). Shows the full future voice-producing lifecycle
// contract — GENERATE -> PREVIEW -> LISTEN -> FEEDBACK -> REGENERATE ->
// COMPARE -> ACCEPT. GENERATE/PREVIEW/LISTEN/FEEDBACK/REGENERATE/COMPARE
// now have a real (synthetic-only) implementation as of VL-D5 — see the
// dedicated #/preview workspace for the actual generation UI; this
// overview only reflects that the lifecycle step exists. ACCEPT remains
// contract-only (no final voice lifecycle promotion exists yet).
import { AvlElement, defineComponent } from "./base-element.js";
import { syntheticVoices } from "../state/synthetic-fixtures.js";
import "./workspace-state.js";
import "./voice-preview-card.js";
import "./voice-version.js";
import "./status-badge.js";
import "./notice-banner.js";

const LIFECYCLE = ["Generate", "Preview", "Listen", "Feedback", "Regenerate", "Compare", "Accept"];
const IMPLEMENTED = new Set(["Generate", "Preview", "Listen", "Feedback", "Regenerate", "Compare"]);

export class AvlWorkspaceVoices extends AvlElement {
  set selectionModel(value) {
    this._selectionModel = value;
  }

  connectedCallback() {
    this._load();
  }

  async _load() {
    this._state = "loading";
    this._render();
    this._voices = syntheticVoices();
    this._state = this._voices.length ? "ready" : "empty";
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      .lifecycle { display: flex; flex-wrap: wrap; gap: var(--avl-space-1); margin: var(--avl-space-2) 0 var(--avl-space-4) 0; }
      .step {
        font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family);
        padding: 0.2rem var(--avl-space-2); border-radius: var(--avl-radius-pill); border: 1px solid var(--avl-color-border-default);
        color: var(--avl-color-text-muted);
      }
      .step[data-implemented="true"] { color: var(--avl-color-text-primary); border-color: var(--avl-color-state-success); }
      .voice-header { display: flex; justify-content: space-between; align-items: center; margin: var(--avl-space-3) 0 var(--avl-space-2) 0; }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "empty") wrapper.setAttribute("title", "No voice profiles yet");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Voices";
    wrapper.appendChild(heading);

    const lifecycle = document.createElement("div");
    lifecycle.className = "lifecycle";
    lifecycle.setAttribute("role", "list");
    lifecycle.setAttribute("aria-label", "Voice production lifecycle");
    for (const step of LIFECYCLE) {
      const el = document.createElement("span");
      el.className = "step";
      el.dataset.implemented = String(IMPLEMENTED.has(step));
      el.textContent = IMPLEMENTED.has(step) ? step : `${step} (not implemented)`;
      lifecycle.appendChild(el);
    }
    wrapper.appendChild(lifecycle);

    for (const voice of this._voices || []) {
      const header = document.createElement("div");
      header.className = "voice-header";
      const name = document.createElement("span");
      name.className = "avl-type-subheading";
      name.textContent = voice.name;
      const calibration = document.createElement("avl-status-badge");
      calibration.setAttribute("domain", "calibration");
      calibration.setAttribute("state", voice.calibrationState);
      header.append(name, calibration);
      header.addEventListener("click", () => this._selectionModel?.select("voice", voice.id, voice));
      wrapper.appendChild(header);

      const previewCard = document.createElement("avl-voice-preview-card");
      previewCard.artifact = {
        preview_id: `${voice.id}-preview-${voice.previewVersion}`,
        kind: "synthetic_fixture",
        relative_path: "previews/example.wav",
        sha256: "0".repeat(64),
        duration_seconds: 3.1,
        sample_rate: 22050,
        iteration: voice.previewVersion,
        is_synthetic: true,
      };
      wrapper.appendChild(previewCard);

      const versions = document.createElement("avl-voice-version");
      versions.previews = [{ preview_id: `${voice.id}-preview-1`, iteration: 1 }, { preview_id: `${voice.id}-preview-2`, iteration: 2 }];
      versions.acceptedPreviewId = null;
      wrapper.appendChild(versions);
    }

    const notice = document.createElement("avl-notice-banner");
    notice.setAttribute("tone", "info");
    notice.textContent = "No real voice training, embeddings, or generation exists. All voice data on this screen is synthetic.";
    wrapper.appendChild(notice);

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-voices", AvlWorkspaceVoices);
