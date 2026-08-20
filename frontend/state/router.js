// Minimal hash-based router (VL-D1 §5). No framework, no history-API
// server requirement — `#/destination` works from a plain file:// or
// static-file:// load with no server-side routing config needed, which
// matters for a local-first app that may eventually run from a bundled
// desktop shell rather than a conventional web server.

export const DESTINATIONS = Object.freeze([
  "command-center",
  "import",
  "batches",
  "recordings",
  "review",
  "processing",
  "preview",
  "feedback",
  "pipeline",
  "voices",
  "models",
  "calibration",
  "claude",
  "activity",
  "settings",
]);

const DEFAULT_DESTINATION = "command-center";

function parseHash(hash) {
  const raw = (hash || "").replace(/^#\/?/, "");
  return DESTINATIONS.includes(raw) ? raw : DEFAULT_DESTINATION;
}

export class Router extends EventTarget {
  constructor(win = window) {
    super();
    this._win = win;
    this._current = parseHash(win.location.hash);
    win.addEventListener("hashchange", () => {
      const next = parseHash(win.location.hash);
      if (next !== this._current) {
        this._current = next;
        this.dispatchEvent(new CustomEvent("change", { detail: { destination: next } }));
      }
    });
  }

  current() {
    return this._current;
  }

  navigate(destination) {
    const target = DESTINATIONS.includes(destination) ? destination : DEFAULT_DESTINATION;
    if (this._win.location.hash !== `#/${target}`) {
      this._win.location.hash = `#/${target}`;
    } else if (target !== this._current) {
      this._current = target;
      this.dispatchEvent(new CustomEvent("change", { detail: { destination: target } }));
    }
  }
}
