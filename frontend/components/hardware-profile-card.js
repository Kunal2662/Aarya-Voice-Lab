// <avl-hardware-profile-card> — set `.capabilities` to an array shaped
// like aarya_voice_lab.core.capability.Capability instances
// ({name, state, detail, version}). Renders generic capability rows —
// CPU/GPU/RAM/backend labels only, driven entirely by what the backend
// reports. No vendor name, product name, or specific device is ever
// hardcoded here; whatever the backend names is shown verbatim, and
// nothing is assumed about which machine this runs on.
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";
import "./card.js";

export class AvlHardwareProfileCard extends AvlElement {
  set capabilities(value) {
    this._capabilities = Array.isArray(value) ? value : [];
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._capabilities = this._capabilities || [];
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .title { font: var(--avl-type-subheading-weight) var(--avl-type-subheading-size) / var(--avl-type-subheading-line-height) var(--avl-type-subheading-family); }
      .row { display: flex; justify-content: space-between; align-items: center; gap: var(--avl-space-2); padding: var(--avl-space-1) 0; border-bottom: 1px solid var(--avl-color-border-subtle); }
      .row:last-child { border-bottom: none; }
      .name { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      .detail { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    const card = document.createElement("avl-card");
    const header = document.createElement("span");
    header.slot = "header";
    header.className = "title";
    header.textContent = "Runtime capabilities";
    card.appendChild(header);

    if (!this._capabilities.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No capability report loaded. This host has not been probed yet.";
      card.appendChild(empty);
    } else {
      for (const cap of this._capabilities) {
        const row = document.createElement("div");
        row.className = "row";
        const name = document.createElement("span");
        name.className = "name";
        name.textContent = cap.name || "unknown component";
        const right = document.createElement("div");
        const badge = document.createElement("avl-status-badge");
        badge.setAttribute("domain", "hardware");
        badge.setAttribute("state", cap.state || "UNKNOWN");
        right.appendChild(badge);
        row.append(name, right);
        card.appendChild(row);
        if (cap.detail) {
          const detail = document.createElement("div");
          detail.className = "detail";
          detail.textContent = cap.detail;
          card.appendChild(detail);
        }
      }
    }

    this.shadowRoot.appendChild(card);
  }
}

defineComponent("avl-hardware-profile-card", AvlHardwareProfileCard);
