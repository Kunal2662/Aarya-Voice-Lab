// <avl-sidebar-view-toggle> — switches the sidebar between "Full view"
// (icon + label) and "Icon view" (compact, label-less), independent of
// window width. Set `.model` to a shared SidebarViewModel instance (see
// state/sidebar-view-model.js) before or at connect time, the same
// property-wiring shape every workspace component uses for `.services`.
// Owns no layout itself — app-shell.js and sidebar-nav.js are what
// actually react to the model's state; this is only the control.
import { AvlElement, defineComponent } from "./base-element.js";
import { SidebarView } from "../state/sidebar-view-model.js";

export class AvlSidebarViewToggle extends AvlElement {
  connectedCallback() {
    if (this._model) this._subscribe();
    this._render();
  }

  disconnectedCallback() {
    if (this._model && this._onChange) this._model.removeEventListener("change", this._onChange);
  }

  set model(value) {
    if (this._model && this._onChange) this._model.removeEventListener("change", this._onChange);
    this._model = value;
    if (this.isConnected) {
      this._subscribe();
      this._render();
    }
  }

  get model() {
    return this._model;
  }

  _subscribe() {
    this._onChange = () => this._render();
    this._model.addEventListener("change", this._onChange);
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
        width: 100%;
      }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._model) return; // not wired yet -- render nothing rather than a control that does nothing

    const view = this._model.get();
    const label = view === SidebarView.ICON ? "Icon view" : "Full view";
    const nextLabel = view === SidebarView.ICON ? "full" : "icon";

    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.setAttribute("aria-label", `Sidebar view, currently ${label.toLowerCase()}. Activate to switch to ${nextLabel} view.`);
    button.addEventListener("click", () => {
      this._model.toggle();
      this._announce(`Sidebar set to ${this._model.get() === SidebarView.ICON ? "icon" : "full"} view`);
    });
    this.shadowRoot.appendChild(button);
  }
}

defineComponent("avl-sidebar-view-toggle", AvlSidebarViewToggle);
