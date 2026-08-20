// Shared base class for every Aarya Voice Lab component. Vanilla Web
// Components, no framework, no build step required to run in a browser —
// see docs/VLD0_DESIGN_SYSTEM.md "Why no framework" for the reasoning.
//
// Every component:
//   * renders into a Shadow DOM root so its styles can never leak into,
//     or be overridden by, the host page — token values are the only
//     styling contract
//   * links the shared variables.css + base.css into that root, so a
//     component never hardcodes a color/size that isn't a token
//   * is defined idempotently, so re-importing a module twice (which
//     happens naturally with multiple entry HTML files) never throws

const SHARED_STYLE_HREFS = ["../css/variables.css", "../css/base.css"];

export class AvlElement extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  /** Call once from a subclass's connectedCallback/constructor render step. */
  _linkSharedStyles() {
    for (const href of SHARED_STYLE_HREFS) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = new URL(href, import.meta.url).href;
      this.shadowRoot.appendChild(link);
    }
  }

  /** Announce a status change to assistive tech without stealing focus. */
  _announce(text) {
    let region = this.shadowRoot.querySelector("[data-avl-live-region]");
    if (!region) {
      region = document.createElement("span");
      region.setAttribute("data-avl-live-region", "");
      region.setAttribute("role", "status");
      region.setAttribute("aria-live", "polite");
      region.className = "avl-sr-only";
      this.shadowRoot.appendChild(region);
    }
    region.textContent = text;
  }
}

/** Define a custom element only if the tag isn't already registered. */
export function defineComponent(tagName, elementClass) {
  if (!customElements.get(tagName)) {
    customElements.define(tagName, elementClass);
  }
}
