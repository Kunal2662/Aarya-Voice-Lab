// <avl-status-badge domain="calibration" state="PROVISIONAL">
//
// The single shared status indicator every domain uses. Never
// color-only: a dot carries the color, but the text label is always
// present, so the state is legible without color vision and without a
// screen reader inferring meaning from a color name.
import { AvlElement, defineComponent } from "./base-element.js";
import { loadStatusVocabulary, labelFor, tokenPathToCssVar } from "./status-vocabulary.js";

export class AvlStatusBadge extends AvlElement {
  static get observedAttributes() {
    return ["domain", "state"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  async _render() {
    const domain = this.getAttribute("domain") || "core";
    const state = this.getAttribute("state") || "";

    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      :host { display: inline-flex; }
      .badge {
        display: inline-flex; align-items: center; gap: var(--avl-space-1);
        padding: var(--avl-space-1) var(--avl-space-2);
        border-radius: var(--avl-radius-pill);
        font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family);
        background: var(--avl-color-surface-sunken);
        color: var(--avl-color-text-primary);
        border: 1px solid var(--avl-color-border-default);
        white-space: nowrap;
      }
      .dot {
        width: 0.5rem; height: 0.5rem; border-radius: 999px; flex: none;
        background: var(--avl-dot-color, var(--avl-color-text-muted));
      }
      .unrecognised { font-style: italic; color: var(--avl-color-text-muted); }
    `;
    this.shadowRoot.appendChild(style);

    const badge = document.createElement("span");
    badge.className = "badge";
    badge.setAttribute("role", "status");
    badge.dataset.domain = domain;
    badge.dataset.state = state;

    const dot = document.createElement("span");
    dot.className = "dot";
    dot.setAttribute("aria-hidden", "true");

    const text = document.createElement("span");
    text.className = "label";

    let label = labelFor(state) || "Unknown";
    try {
      const vocab = await loadStatusVocabulary();
      const domainDef = vocab.domains[domain];
      if (domainDef && domainDef.states.includes(state)) {
        const varName = tokenPathToCssVar(domainDef.color_token[state]);
        dot.style.setProperty("--avl-dot-color", `var(${varName})`);
      } else {
        badge.classList.add("unrecognised");
        label = domainDef
          ? `${label} (not a recognised ${domain} state)`
          : `${label} (unknown domain: ${domain})`;
      }
    } catch {
      badge.classList.add("unrecognised");
      label = `${label} (status vocabulary unavailable)`;
    }

    text.textContent = label;
    badge.append(dot, text);
    this.shadowRoot.appendChild(badge);
  }
}

defineComponent("avl-status-badge", AvlStatusBadge);
