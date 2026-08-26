// Manual icon-view/full-view override for the sidebar, independent of
// app-shell.js's/sidebar-nav.js's own existing narrow-desktop responsive
// collapse (which stays unchanged). "full" (the default) leaves that
// responsive behavior exactly as it was; "icon" forces the compact,
// label-less rail at any width. A single shared instance (see
// app/main.js) keeps app-shell.js's grid column and sidebar-nav.js's
// label visibility in sync without either component needing a direct
// reference to the other -- the same decoupling avl-theme-toggle already
// gets from CSS custom-property inheritance, done here via a shared
// EventTarget instead since a layout change can't be expressed as a
// single inherited CSS variable.
//
// Persisted like avl-theme-toggle's own preference: localStorage only,
// no network, no account. A storage failure falls back to the in-memory
// default rather than crashing anything that touches it (same honest-
// degradation rule state/session-persistence.js established).
const STORAGE_KEY = "avl-sidebar-view-preference";

export const SidebarView = Object.freeze({
  FULL: "full",
  ICON: "icon",
});

function readStored() {
  try {
    return localStorage.getItem(STORAGE_KEY) === SidebarView.ICON ? SidebarView.ICON : SidebarView.FULL;
  } catch {
    return SidebarView.FULL;
  }
}

function writeStored(view) {
  try {
    localStorage.setItem(STORAGE_KEY, view);
  } catch {
    // Storage unavailable -- the in-memory preference for this page load
    // still applies via the "change" event below, it just won't survive
    // a reload.
  }
}

export class SidebarViewModel extends EventTarget {
  constructor() {
    super();
    this._view = readStored();
  }

  get() {
    return this._view;
  }

  toggle() {
    this.set(this._view === SidebarView.ICON ? SidebarView.FULL : SidebarView.ICON);
  }

  set(view) {
    const next = view === SidebarView.ICON ? SidebarView.ICON : SidebarView.FULL;
    if (next === this._view) return;
    this._view = next;
    writeStored(next);
    this.dispatchEvent(new CustomEvent("change", { detail: { view: next } }));
  }
}
