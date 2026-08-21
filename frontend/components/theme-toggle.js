// <avl-theme-toggle> — cycles document theme: system -> light -> dark.
// Persists the explicit choice to localStorage only (local-first: no
// network call, no account, no cloud sync of a UI preference). "system"
// means no data-theme attribute is set, so prefers-color-scheme decides.
import { AvlElement, defineComponent } from "./base-element.js";

const STORAGE_KEY = "avl-theme-preference";
const ORDER = ["system", "light", "dark"];

function applyTheme(preference) {
  const root = document.documentElement;
  if (preference === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", preference);
  }
}

// VL-D9 -- a real browser can have a localStorage object that exists but
// throws on every use (private browsing in some engines, storage
// disabled by policy). This was never guarded before VL-D9's
// persistence-unavailable testing surfaced it; the fix follows the same
// honest-degradation rule state/session-persistence.js established: a
// storage failure falls back to the safe default, it never crashes the
// UI that touched it.
function readStoredTheme() {
  try {
    return localStorage.getItem(STORAGE_KEY) || "system";
  } catch {
    return "system";
  }
}

function writeStoredTheme(preference) {
  try {
    localStorage.setItem(STORAGE_KEY, preference);
  } catch {
    // Storage unavailable -- the in-memory preference for this page load
    // still applies via applyTheme(), it just won't survive a reload.
  }
}

export class AvlThemeToggle extends AvlElement {
  connectedCallback() {
    this._preference = readStoredTheme();
    applyTheme(this._preference);
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      button {
        background: var(--avl-color-surface-raised);
        border: 1px solid var(--avl-color-border-default);
        border-radius: var(--avl-radius-md);
        padding: var(--avl-space-1) var(--avl-space-2);
        cursor: pointer;
        color: var(--avl-color-text-primary);
        font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family);
      }
    `;
    this.shadowRoot.appendChild(style);

    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `Theme: ${this._preference}`;
    button.setAttribute("aria-label", `Theme preference, currently ${this._preference}. Activate to change.`);
    button.addEventListener("click", () => {
      const next = ORDER[(ORDER.indexOf(this._preference) + 1) % ORDER.length];
      this._preference = next;
      writeStoredTheme(next);
      applyTheme(next);
      button.textContent = `Theme: ${next}`;
      button.setAttribute("aria-label", `Theme preference, currently ${next}. Activate to change.`);
      this._announce(`Theme set to ${next}`);
    });

    this.shadowRoot.appendChild(button);
  }
}

defineComponent("avl-theme-toggle", AvlThemeToggle);
