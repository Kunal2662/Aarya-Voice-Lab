// <avl-import-drop-zone> — the UI interaction model for VL-D1 §9's bulk
// import: file/folder selection, drag/drop, multiple files. Dispatches
// `avl-files-selected` with a File[] array; performs NO upload, hashing,
// or filesystem write itself — a real importer (VL-D2) reads the files
// and enforces source immutability / content-addressing on the backend
// side. For VL-D1, nothing dropped here is processed beyond listing
// names — see workspace-import.js for how the demo queue is built from
// synthetic fixtures instead.
import { AvlElement, defineComponent } from "./base-element.js";

export class AvlImportDropZone extends AvlElement {
  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .zone {
        display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--avl-space-2);
        border: 2px dashed var(--avl-color-border-strong); border-radius: var(--avl-radius-md);
        padding: var(--avl-space-8) var(--avl-space-4);
        color: var(--avl-color-text-secondary);
        transition: border-color var(--avl-duration-fast) var(--avl-easing-standard), background var(--avl-duration-fast) var(--avl-easing-standard);
      }
      .zone[data-dragover="true"] { border-color: var(--avl-color-brand-accent); background: var(--avl-color-brand-accent-subtle); }
      input[type="file"] { display: none; }
      label {
        cursor: pointer; color: var(--avl-color-brand-accent);
        font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family);
      }
    `;
    this.shadowRoot.appendChild(style);

    const zone = document.createElement("div");
    zone.className = "zone";
    zone.setAttribute("role", "region");
    zone.setAttribute("aria-label", "Import drop zone");

    const text = document.createElement("span");
    text.textContent = "Drag and drop recordings, or";

    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.id = "avl-import-file-input";
    input.accept = "audio/*";

    const label = document.createElement("label");
    label.htmlFor = "avl-import-file-input";
    label.textContent = "choose files";

    const emit = (files) => {
      this.dispatchEvent(
        new CustomEvent("avl-files-selected", { detail: { files: Array.from(files) }, bubbles: true, composed: true }),
      );
    };

    input.addEventListener("change", () => emit(input.files));
    zone.addEventListener("dragover", (event) => {
      event.preventDefault();
      zone.dataset.dragover = "true";
    });
    zone.addEventListener("dragleave", () => {
      zone.dataset.dragover = "false";
    });
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.dataset.dragover = "false";
      if (event.dataTransfer?.files?.length) emit(event.dataTransfer.files);
    });

    zone.append(text, input, label);
    this.shadowRoot.appendChild(zone);
  }
}

defineComponent("avl-import-drop-zone", AvlImportDropZone);
