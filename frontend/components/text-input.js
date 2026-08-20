// <avl-text-input> — VL-D5 §11. Set `.value` (the text to synthesize)
// and optionally `.capabilities` (a GenerationCapabilities-shaped
// object, see state/generation-model.js) to show the backend's own
// duration estimate. Character/word counts are always exact; the
// duration is always labelled a heuristic estimate, never claimed exact
// unless a real backend eventually reports one.
import { AvlElement, defineComponent } from "./base-element.js";
import { MAX_TEXT_LENGTH, estimateGenerationRequirements } from "../state/generation-model.js";

export class AvlTextInput extends AvlElement {
  set value(value) {
    this._value = value || "";
    if (this.isConnected) this._render();
  }

  get value() {
    return this._value || "";
  }

  set capabilities(value) {
    this._capabilities = value || null;
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._value = this._value || "";
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      textarea {
        width: 100%; min-height: 6rem; resize: vertical;
        font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family);
        border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-sm);
        padding: var(--avl-space-2); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary);
      }
      textarea.over-limit { border-color: var(--avl-color-state-danger); }
      .counts { display: flex; gap: var(--avl-space-3); margin-top: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      .counts .over-limit { color: var(--avl-color-state-danger); }
      .estimate { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); margin-top: var(--avl-space-1); }
    `;
    this.shadowRoot.appendChild(style);

    const textarea = document.createElement("textarea");
    textarea.setAttribute("aria-label", "Text to generate");
    textarea.value = this._value || "";
    textarea.placeholder = "Enter the text to preview...";
    const overLimit = textarea.value.length > MAX_TEXT_LENGTH;
    if (overLimit) textarea.classList.add("over-limit");
    textarea.addEventListener("input", () => {
      this._value = textarea.value;
      this.dispatchEvent(new CustomEvent("avl-text-change", { detail: { text: this._value }, bubbles: true, composed: true }));
      this._render();
    });
    this.shadowRoot.appendChild(textarea);

    const text = this._value || "";
    const charCount = text.length;
    const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;

    const counts = document.createElement("div");
    counts.className = "counts";
    const charSpan = document.createElement("span");
    charSpan.className = overLimit ? "over-limit" : "";
    charSpan.textContent = `${charCount} / ${MAX_TEXT_LENGTH} characters`;
    const wordSpan = document.createElement("span");
    wordSpan.textContent = `${wordCount} word(s)`;
    counts.append(charSpan, wordSpan);
    this.shadowRoot.appendChild(counts);

    const estimate = document.createElement("div");
    estimate.className = "estimate";
    if (this._capabilities) {
      const info = estimateGenerationRequirements({ text }, this._capabilities);
      estimate.textContent =
        info.estimated_duration_seconds != null
          ? `Estimated duration: ~${info.estimated_duration_seconds}s (${info.estimate_basis})`
          : info.estimate_basis;
    } else {
      estimate.textContent = "Select a voice profile and model to see a duration estimate.";
    }
    this.shadowRoot.appendChild(estimate);
  }
}

defineComponent("avl-text-input", AvlTextInput);
