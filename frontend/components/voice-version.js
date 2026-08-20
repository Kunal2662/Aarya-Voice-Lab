// <avl-voice-version> — set `.previews` to a list of PreviewArtifact
// dicts and `.acceptedPreviewId` to preview_loop_state()'s
// accepted_preview_id. Renders the iteration history as a simple list;
// selecting one dispatches avl-version-select.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlVoiceVersion extends AvlElement {
  set previews(value) {
    this._previews = Array.isArray(value) ? value : [];
    if (this.isConnected) this._render();
  }

  get previews() {
    return this._previews || [];
  }

  set acceptedPreviewId(value) {
    this._acceptedPreviewId = value || null;
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._previews = this._previews || [];
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      ul { display: flex; flex-direction: column; gap: var(--avl-space-1); }
      li button {
        width: 100%; text-align: left; background: var(--avl-color-surface-raised);
        border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-sm);
        padding: var(--avl-space-2); cursor: pointer; color: var(--avl-color-text-primary);
        font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family);
        display: flex; justify-content: space-between;
      }
      li button[aria-current="true"] { border-color: var(--avl-color-brand-accent); background: var(--avl-color-brand-accent-subtle); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .tag { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-state-success); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._previews.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No versions yet.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const list = document.createElement("ul");
    for (const preview of this._previews) {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      const isAccepted = preview.preview_id === this._acceptedPreviewId;
      if (isAccepted) button.setAttribute("aria-current", "true");
      const label = document.createElement("span");
      label.textContent = `Iteration ${preview.iteration ?? "?"}`;
      button.appendChild(label);
      if (isAccepted) {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = "accepted";
        button.appendChild(tag);
      }
      button.addEventListener("click", () => {
        this.dispatchEvent(
          new CustomEvent("avl-version-select", {
            detail: { previewId: preview.preview_id },
            bubbles: true,
            composed: true,
          }),
        );
      });
      li.appendChild(button);
      list.appendChild(li);
    }
    this.shadowRoot.appendChild(list);
  }
}

defineComponent("avl-voice-version", AvlVoiceVersion);
