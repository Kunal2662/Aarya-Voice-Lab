// <avl-waveform-visualization> — VL-D3 §8. An analytical visualization,
// not the only way information is communicated: every region it draws
// (speech/silence, segment boundary, overlap candidate) is also listed
// as text below the canvas, and every marker carries a text label —
// never color alone. Set `.peaks` (array of 0..1), `.durationSeconds`,
// `.segments` (state/synthetic-fixtures.js syntheticSegments() shape),
// and optionally `.overlapCandidates`.
import { AvlElement, defineComponent } from "./base-element.js";
import "./status-badge.js";

export class AvlWaveformVisualization extends AvlElement {
  set peaks(value) {
    this._peaks = Array.isArray(value) ? value : [];
    if (this.isConnected) this._render();
  }

  set durationSeconds(value) {
    this._duration = Number(value) || 0;
    if (this.isConnected) this._render();
  }

  set segments(value) {
    this._segments = Array.isArray(value) ? value : [];
    if (this.isConnected) this._render();
  }

  set overlapCandidates(value) {
    this._overlapCandidates = Array.isArray(value) ? value : [];
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._peaks = this._peaks || [];
    this._segments = this._segments || [];
    this._overlapCandidates = this._overlapCandidates || [];
    this._duration = this._duration || 0;
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .frame { position: relative; height: 6rem; background: var(--avl-color-surface-sunken); border: 1px solid var(--avl-color-border-subtle); border-radius: var(--avl-radius-sm); overflow: hidden; }
      .bars { position: absolute; inset: 0; display: flex; align-items: flex-end; gap: 1px; padding: var(--avl-space-1); }
      .bar { flex: 1; background: var(--avl-color-brand-accent); min-width: 1px; border-radius: 1px; opacity: 0.7; }
      .region { position: absolute; top: 0; bottom: 0; }
      .region.silence { background: color-mix(in srgb, var(--avl-color-text-muted) 15%, transparent); }
      .boundary { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--avl-color-border-strong); }
      .marker { position: absolute; top: 0; height: 0.4rem; background: var(--avl-color-voice-review-required); }
      .legend-list { margin-top: var(--avl-space-2); display: flex; flex-direction: column; gap: var(--avl-space-1); }
      .legend-item { display: flex; gap: var(--avl-space-2); align-items: center; font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._peaks.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No waveform data.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const frame = document.createElement("div");
    frame.className = "frame";
    frame.setAttribute("role", "img");
    frame.setAttribute(
      "aria-label",
      `Waveform with ${this._segments.length} segment(s) and ${this._overlapCandidates.length} overlap candidate(s)`,
    );

    const bars = document.createElement("div");
    bars.className = "bars";
    for (const value of this._peaks) {
      const bar = document.createElement("div");
      bar.className = "bar";
      bar.style.height = `${Math.max(4, Math.min(1, Number(value) || 0) * 100)}%`;
      bars.appendChild(bar);
    }
    frame.appendChild(bars);

    const duration = this._duration || Math.max(...this._segments.map((s) => s.end), 1);
    for (const segment of this._segments) {
      if (segment.kind === "silence") {
        const region = document.createElement("div");
        region.className = "region silence";
        region.style.left = `${(segment.start / duration) * 100}%`;
        region.style.width = `${((segment.end - segment.start) / duration) * 100}%`;
        frame.appendChild(region);
      }
      const boundary = document.createElement("div");
      boundary.className = "boundary";
      boundary.style.left = `${(segment.start / duration) * 100}%`;
      frame.appendChild(boundary);
    }

    for (const candidate of this._overlapCandidates) {
      const marker = document.createElement("div");
      marker.className = "marker";
      marker.style.left = `${(candidate.start / duration) * 100}%`;
      marker.style.width = `${((candidate.end - candidate.start) / duration) * 100}%`;
      frame.appendChild(marker);
    }

    this.shadowRoot.appendChild(frame);

    // Textual equivalent — the visualization is never the only carrier.
    const legend = document.createElement("div");
    legend.className = "legend-list";
    for (const segment of this._segments) {
      const item = document.createElement("div");
      item.className = "legend-item";
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "voice");
      badge.setAttribute("state", segment.kind === "speech" ? "processing" : "idle");
      const label = document.createElement("span");
      label.textContent = `${segment.segmentId}: ${segment.kind} ${segment.start.toFixed(2)}s–${segment.end.toFixed(2)}s`;
      item.append(badge, label);
      legend.appendChild(item);
    }
    for (const candidate of this._overlapCandidates) {
      const item = document.createElement("div");
      item.className = "legend-item";
      const badge = document.createElement("avl-status-badge");
      badge.setAttribute("domain", "overlap_status");
      badge.setAttribute("state", candidate.status);
      const label = document.createElement("span");
      label.textContent = `Overlap candidate ${candidate.start.toFixed(2)}s–${candidate.end.toFixed(2)}s — ${candidate.reason}`;
      item.append(badge, label);
      legend.appendChild(item);
    }
    this.shadowRoot.appendChild(legend);
  }
}

defineComponent("avl-waveform-visualization", AvlWaveformVisualization);
