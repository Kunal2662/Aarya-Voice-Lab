// <avl-before-after-comparison> — VL-D4 §13. Set `.recording` and
// `.item` (a state/processing-model.js queue item — status/derivedArtifact/
// qualityBefore/qualityAfter). Shows source vs. derived: playback (never
// autoplay — reuses components/audio-player.js exactly as-is), a
// waveform per side, metadata, and a quality comparison
// (components/quality-profile.js reused for both sides — its `.assessment`
// setter already tolerates a reduced shape lacking findings/speech/
// characteristics, so no changes were needed there for VL-D4 to reuse it).
import { AvlElement, defineComponent } from "./base-element.js";
import "./audio-player.js";
import "./quality-profile.js";

export class AvlBeforeAfterComparison extends AvlElement {
  set recording(value) {
    this._recording = value || null;
    if (this.isConnected) this._render();
  }

  set item(value) {
    this._item = value || null;
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      .columns { display: grid; grid-template-columns: 1fr 1fr; gap: var(--avl-space-4); }
      h4 { margin: 0 0 var(--avl-space-2) 0; font: var(--avl-type-subheading-weight) var(--avl-type-subheading-size) / var(--avl-type-subheading-line-height) var(--avl-type-subheading-family); }
      .rows { display: flex; flex-direction: column; gap: var(--avl-space-1); margin-top: var(--avl-space-2); }
      .row { display: flex; justify-content: space-between; gap: var(--avl-space-2); padding: var(--avl-space-1) 0; border-bottom: 1px solid var(--avl-color-border-subtle); }
      .label { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); }
      .value { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._recording) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Select a recording to compare source and derived audio.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const columns = document.createElement("div");
    columns.className = "columns";

    const sourceColumn = document.createElement("div");
    sourceColumn.innerHTML = "<h4>Source</h4>";
    const sourcePlayer = document.createElement("avl-audio-player");
    sourcePlayer.setAttribute("recording-id", this._recording.id);
    sourcePlayer.setAttribute("duration-seconds", String(this._recording.durationSeconds || 3));
    sourceColumn.appendChild(sourcePlayer);
    sourceColumn.appendChild(
      this._metadataRows({
        "Sample rate": this._recording.sampleRate ? `${this._recording.sampleRate} Hz` : null,
        Channels: this._recording.channels,
        Duration: this._recording.durationSeconds ? `${this._recording.durationSeconds}s` : null,
      }),
    );
    const qualityBefore = document.createElement("avl-quality-profile");
    qualityBefore.assessment = this._item ? this._item.qualityBefore : null;
    sourceColumn.appendChild(qualityBefore);
    columns.appendChild(sourceColumn);

    const derivedColumn = document.createElement("div");
    derivedColumn.innerHTML = "<h4>Derived</h4>";
    if (this._item && this._item.derivedArtifact) {
      const derivedPlayer = document.createElement("avl-audio-player");
      // A distinguishable synthetic tone -- never the same one as
      // Source, so A/B switching is actually audible, without claiming
      // this is a real processed recording either.
      derivedPlayer.setAttribute("recording-id", `${this._recording.id}-derived`);
      const afterDuration = this._item.qualityAfter?.measurements?.durationSeconds || this._recording.durationSeconds || 3;
      derivedPlayer.setAttribute("duration-seconds", String(afterDuration));
      derivedColumn.appendChild(derivedPlayer);
      derivedColumn.appendChild(
        this._metadataRows({
          "Output path": this._item.derivedArtifact.outputPath,
          "Leading trim": `${this._item.derivedArtifact.boundary?.leadingTrimSeconds ?? "—"}s`,
          "Trailing trim": `${this._item.derivedArtifact.boundary?.trailingTrimSeconds ?? "—"}s`,
          Normalization: this._item.derivedArtifact.normalization ? "applied" : "unavailable",
        }),
      );
      const qualityAfter = document.createElement("avl-quality-profile");
      qualityAfter.assessment = this._item.qualityAfter;
      derivedColumn.appendChild(qualityAfter);
    } else {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No derived artifact yet — queue this recording for processing.";
      derivedColumn.appendChild(empty);
    }
    columns.appendChild(derivedColumn);

    this.shadowRoot.appendChild(columns);
  }

  _metadataRows(fields) {
    const rows = document.createElement("div");
    rows.className = "rows";
    for (const [label, value] of Object.entries(fields)) {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `<span class="label">${label}</span><span class="value">${value == null || value === "" ? "—" : value}</span>`;
      rows.appendChild(row);
    }
    return rows;
  }
}

defineComponent("avl-before-after-comparison", AvlBeforeAfterComparison);
