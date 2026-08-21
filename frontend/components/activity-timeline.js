// <avl-activity-timeline> — set `.events` to an array of ActivityEvent
// objects (state/activity-model.js). Renders newest-first through the
// "activity_severity" status domain; each item's source is shown as
// plain text (a closed, documented list — see ActivitySource) rather
// than through a second badge, keeping one color signal per row.
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";

export class AvlActivityTimeline extends AvlElement {
  set events(value) {
    this._events = Array.isArray(value) ? value : [];
    if (this.isConnected) this._render();
  }

  get events() {
    return this._events || [];
  }

  connectedCallback() {
    this._events = this._events || [];
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      ul { display: flex; flex-direction: column; gap: var(--avl-space-2); }
      li {
        display: flex; flex-direction: column; gap: var(--avl-space-1);
        padding: var(--avl-space-2) var(--avl-space-3);
        border-left: 2px solid var(--avl-color-border-default);
      }
      /* FE-3 -- .row replaced by the shared avl-cluster utility (css/base.css). */
      .source { text-transform: uppercase; letter-spacing: 0.03em; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-muted); }
      .timestamp { margin-left: auto; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-muted); }
      .summary { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._events.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No activity.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const list = document.createElement("ul");
    list.setAttribute("role", "feed");
    list.setAttribute("aria-label", "Activity timeline");

    for (const event of this._events) {
      const li = document.createElement("li");

      const row = document.createElement("div");
      row.className = "avl-cluster";
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "activity_severity");
      badge.setAttribute("state", event.severity);
      const source = document.createElement("span");
      source.className = "source";
      source.textContent = event.source.replace(/_/g, " ");
      const timestamp = document.createElement("time");
      timestamp.className = "timestamp";
      timestamp.dateTime = event.timestamp;
      timestamp.textContent = event.timestamp;
      row.append(badge, source, timestamp);

      const summary = document.createElement("div");
      summary.className = "summary";
      summary.textContent = event.summary;

      li.append(row, summary);
      list.appendChild(li);
    }

    this.shadowRoot.appendChild(list);
  }
}

defineComponent("avl-activity-timeline", AvlActivityTimeline);
