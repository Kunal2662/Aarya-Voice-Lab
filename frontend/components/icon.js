// <avl-icon name="command-center" size="1rem" label="...">
// FE-1.3 -- a central, inline-SVG icon catalogue, closing the gap the
// FE-1 audit found: sidebar-nav.js's entire "icon system" was
// `icon.textContent = item.getAttribute("icon") || "•"`, a single
// Unicode glyph. Every icon here is hand-authored geometry (circles,
// lines, simple paths) -- no external icon package, no emoji, matching
// a plain, technical, line-icon language appropriate for a voice/AI
// engineering research tool rather than a decorative one.
//
// - Color is `currentColor`: the icon inherits whatever color rule
//   already governs its container (e.g. sidebar-nav.js's
//   `.item`/`.item[aria-current="page"]`/`.item[disabled]` rules), so
//   no new color token was needed -- it already tracks the existing
//   token-driven text color automatically.
// - Size defaults to the existing `--avl-space-4` token (1rem), reusing
//   the spacing scale rather than inventing a new size-token category;
//   an explicit `size` attribute (any CSS length) overrides it.
// - `aria-hidden="true"` by default, exactly like the existing
//   pixel-art system (pixel-sprite.js): an icon here is always paired
//   with real visible text (the sidebar label), never its sole carrier
//   of information, per VLD0's own accessibility contract. The rare
//   case of an icon used *without* adjacent text (independently
//   interactive) should set a `label` attribute, which switches the
//   rendered <svg> to `role="img"` with an `aria-label` instead of
//   being hidden.
import { AvlElement, defineComponent } from "./base-element.js";

// Every entry is the *inner* markup of a 24x24 viewBox line icon:
// stroke="currentColor", fill="none", 1.75 stroke width, round caps/
// joins -- applied once on the <svg> itself, not repeated per icon.
const ICONS = {
  "command-center": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  import: '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M4 19h16"/>',
  batches: '<rect x="3" y="4" width="18" height="4" rx="1"/><rect x="3" y="10" width="18" height="4" rx="1"/><rect x="3" y="16" width="18" height="4" rx="1"/>',
  recordings: '<line x1="4" y1="10" x2="4" y2="14"/><line x1="8" y1="6" x2="8" y2="18"/><line x1="12" y1="3" x2="12" y2="21"/><line x1="16" y1="6" x2="16" y2="18"/><line x1="20" y1="10" x2="20" y2="14"/>',
  review: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  processing: '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>',
  preview: '<circle cx="12" cy="12" r="9"/><path d="M10 8l6 4-6 4V8z"/>',
  feedback: '<path d="M12 3l2.6 5.6 6.2.5-4.7 4.1 1.4 6.1L12 16.9 6.5 19.3l1.4-6.1-4.7-4.1 6.2-.5L12 3z"/>',
  pipeline: '<circle cx="4" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="20" cy="12" r="2"/><line x1="6" y1="12" x2="10" y2="12"/><line x1="14" y1="12" x2="18" y2="12"/>',
  voices: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><line x1="12" y1="18" x2="12" y2="21"/><line x1="8" y1="21" x2="16" y2="21"/>',
  models: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M4 7.5l8 4.5 8-4.5"/><line x1="12" y1="12" x2="12" y2="21"/>',
  calibration: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.6" fill="currentColor" stroke="none"/>',
  claude: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3"/><line x1="12" y1="15" x2="16" y2="15"/>',
  activity: '<path d="M3 12h4l2-7 4 14 2-7h6"/>',
  settings: '<circle cx="12" cy="12" r="3"/><line x1="12" y1="2" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="4.2" y1="4.2" x2="6.3" y2="6.3"/><line x1="17.7" y1="17.7" x2="19.8" y2="19.8"/><line x1="2" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="22" y2="12"/><line x1="4.2" y1="19.8" x2="6.3" y2="17.7"/><line x1="17.7" y1="6.3" x2="19.8" y2="4.2"/>',
  // FE-1.6 -- added for notice-banner.js's dismiss control, replacing a
  // raw "✕" Unicode character with a real icon, completing FE-1.3's own
  // "no random Unicode symbols as final icons" principle for the one
  // other spot in the app it still applied to.
  close: '<line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/>',
  // Added when shell/index.html's own sidebar markup was found still
  // passing raw Unicode characters ("▣", "✎") as icon="..." values --
  // this catalogue's "no random Unicode symbols" principle was applied
  // to the sidebar-nav.js *component* (FE-1.3) but the wireframe's own
  // markup was never migrated off the pre-FE-1.3 glyphs, so every
  // unmapped name silently fell through to this file's own "unknown
  // icon" fallback ("?").
  hardware: '<rect x="6" y="6" width="12" height="12" rx="1"/><line x1="9" y1="3" x2="9" y2="6"/><line x1="15" y1="3" x2="15" y2="6"/><line x1="9" y1="18" x2="9" y2="21"/><line x1="15" y1="18" x2="15" y2="21"/><line x1="3" y1="9" x2="6" y2="9"/><line x1="3" y1="15" x2="6" y2="15"/><line x1="18" y1="9" x2="21" y2="9"/><line x1="18" y1="15" x2="21" y2="15"/>',
  accent: '<path d="M3 21l3.5-1 11-11-2.5-2.5-11 11-1 3.5z"/><path d="M14 5.5l2.5 2.5"/>',
};

export class AvlIcon extends AvlElement {
  static get observedAttributes() {
    return ["name", "size", "label"];
  }

  connectedCallback() {
    this._render();
  }

  attributeChangedCallback() {
    if (this.isConnected) this._render();
  }

  _render() {
    const name = this.getAttribute("name") || "";
    const size = this.getAttribute("size") || "var(--avl-space-4)";
    const label = this.getAttribute("label");
    const inner = ICONS[name];

    this.shadowRoot.innerHTML = "";
    const style = document.createElement("style");
    style.textContent = `
      :host { display: inline-flex; align-items: center; justify-content: center; line-height: 0; }
      svg { display: block; width: ${size}; height: ${size}; }
    `;
    this.shadowRoot.appendChild(style);

    if (!inner) {
      // An unrecognised icon name renders visibly as unrecognised
      // (VLD0's own status-vocabulary rule extended here), never a
      // silent blank -- a wrong or stale caller should be obvious.
      const fallback = document.createElement("span");
      fallback.textContent = "?";
      fallback.title = `avl-icon: unknown icon name "${name}"`;
      this.shadowRoot.appendChild(fallback);
      return;
    }

    const svgNs = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNs, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.75");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    if (label) {
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", label);
    } else {
      svg.setAttribute("aria-hidden", "true");
    }
    svg.innerHTML = inner;
    this.shadowRoot.appendChild(svg);
  }
}

defineComponent("avl-icon", AvlIcon);

export const ICON_NAMES = Object.freeze(Object.keys(ICONS));
