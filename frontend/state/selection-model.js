// Global selection state, driving the Inspector (VL-D1 §22). One
// selection at a time: { kind, id, data }. `kind` names which inspector
// view to render (see components/inspector-router.js); `data` is
// whatever payload the selecting workspace already has in hand, so the
// Inspector never re-fetches — it only re-renders.

export class SelectionModel extends EventTarget {
  constructor() {
    super();
    this._selection = null;
  }

  get() {
    return this._selection;
  }

  select(kind, id, data = null) {
    this._selection = { kind, id, data };
    this.dispatchEvent(new CustomEvent("change", { detail: this._selection }));
    return this._selection;
  }

  clear() {
    this._selection = null;
    this.dispatchEvent(new CustomEvent("change", { detail: null }));
  }
}
