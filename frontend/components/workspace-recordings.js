// <avl-workspace-recordings> — VL-D2 §14. A real searchable, filterable,
// sortable recording explorer, technical/provenance fields only — no
// speaker identity field exists anywhere in this component or the
// synthetic fixture it renders, preserving the Phase 2 speaker boundary
// (pipeline/stages.py's SPEAKER_IDENTITY_BOUNDARY).
import { AvlElement, defineComponent } from "./base-element.js";
import { syntheticRecordings } from "../state/synthetic-fixtures.js";
import "./workspace-state.js";
import "./status-badge.js";
import "./panel.js";
import "./stat-tile.js";

const JOB_STATUS_DOMAIN = "pipeline_stage";
const VALIDATION_TO_BADGE = { valid: "success", warning: "warning", invalid: "failed" };

// FE-3 -- same 5-tone cycle every other workspace dashboard uses.
const TILE_TONES = ["blue", "teal", "green", "violet", "pink"];

const COLUMNS = [
  { key: "contentAddressedId", label: "ID" },
  { key: "filename", label: "Filename" },
  { key: "format", label: "Format" },
  { key: "durationSeconds", label: "Duration" },
  { key: "sampleRate", label: "Sample rate" },
  { key: "channels", label: "Channels" },
  { key: "validation", label: "Validation" },
  { key: "quality", label: "Quality" },
  { key: "batchId", label: "Batch" },
  { key: "processingState", label: "Status" },
];

export class AvlWorkspaceRecordings extends AvlElement {
  set selectionModel(value) {
    this._selectionModel = value;
  }

  connectedCallback() {
    this._search = this._search || "";
    this._statusFilter = this._statusFilter || "";
    this._formatFilter = this._formatFilter || "";
    this._batchFilter = this._batchFilter || "";
    this._sortKey = this._sortKey || "filename";
    this._sortDir = this._sortDir || 1;
    this._load();
  }

  async _load() {
    this._state = "loading";
    this._render();
    this._recordings = syntheticRecordings();
    this._state = this._recordings.length ? "ready" : "empty";
    this._render();
  }

  _dashboardCounts() {
    const recordings = this._recordings || [];
    return {
      Total: recordings.length,
      Valid: recordings.filter((r) => r.validation === "valid").length,
      Warning: recordings.filter((r) => r.validation === "warning").length,
      Invalid: recordings.filter((r) => r.validation === "invalid").length,
    };
  }

  _filtered() {
    let rows = this._recordings || [];
    if (this._search) {
      const needle = this._search.toLowerCase();
      rows = rows.filter(
        (r) => r.filename.toLowerCase().includes(needle) || r.contentAddressedId.toLowerCase().includes(needle),
      );
    }
    if (this._statusFilter) rows = rows.filter((r) => r.validation === this._statusFilter);
    if (this._formatFilter) rows = rows.filter((r) => r.format === this._formatFilter);
    if (this._batchFilter) rows = rows.filter((r) => r.batchId === this._batchFilter);
    rows = [...rows].sort((a, b) => {
      const av = a[this._sortKey];
      const bv = b[this._sortKey];
      if (av === bv) return 0;
      return (av > bv ? 1 : -1) * this._sortDir;
    });
    return rows;
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      /* FE-3 -- input/select styling now comes from css/base.css's shared
         baseline (the same declarations this local rule used to repeat). */
      .controls { display: flex; gap: var(--avl-space-2); flex-wrap: wrap; margin-bottom: var(--avl-space-3); }
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      th button { background: none; border: none; cursor: pointer; color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); padding: 0; }
      tr[data-selectable] { cursor: pointer; }
      tr[data-selectable]:hover { background: var(--avl-color-surface-sunken); }
      .id { font: var(--avl-type-code-weight) var(--avl-type-code-size) / 1 var(--avl-type-code-family); }
      .count { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); margin-bottom: var(--avl-space-2); }
      .dashboard-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: var(--avl-space-3); margin-bottom: var(--avl-space-4); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "empty") wrapper.setAttribute("title", "No recordings in this batch");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Recordings";
    wrapper.appendChild(heading);

    if (this._state === "ready" && this._recordings) {
      const dashboard = document.createElement("avl-panel");
      dashboard.setAttribute("title", "Recording dashboard");
      const grid = document.createElement("div");
      grid.className = "dashboard-grid";
      Object.entries(this._dashboardCounts()).forEach(([label, value], i) => {
        const tile = document.createElement("avl-stat-tile");
        tile.setAttribute("label", label);
        tile.setAttribute("value", String(value));
        tile.setAttribute("tone", TILE_TONES[i % TILE_TONES.length]);
        tile.setAttribute("icon", "recordings");
        grid.appendChild(tile);
      });
      dashboard.appendChild(grid);
      wrapper.appendChild(dashboard);

      const controls = document.createElement("div");
      controls.className = "controls";

      const search = document.createElement("input");
      search.type = "search";
      search.placeholder = "Search filename or ID…";
      search.value = this._search;
      search.setAttribute("aria-label", "Search recordings");
      search.addEventListener("input", () => {
        this._search = search.value;
        this._render();
      });
      controls.appendChild(search);

      const statuses = [...new Set(this._recordings.map((r) => r.validation))];
      controls.appendChild(this._buildSelect("Validation", statuses, this._statusFilter, (v) => (this._statusFilter = v)));

      const formats = [...new Set(this._recordings.map((r) => r.format))];
      controls.appendChild(this._buildSelect("Format", formats, this._formatFilter, (v) => (this._formatFilter = v)));

      const batches = [...new Set(this._recordings.map((r) => r.batchId))];
      controls.appendChild(this._buildSelect("Batch", batches, this._batchFilter, (v) => (this._batchFilter = v)));

      wrapper.appendChild(controls);

      const filtered = this._filtered();
      const count = document.createElement("div");
      count.className = "count";
      count.textContent = `${filtered.length} of ${this._recordings.length} recording(s)`;
      wrapper.appendChild(count);

      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const headRow = document.createElement("tr");
      for (const column of COLUMNS) {
        const th = document.createElement("th");
        const button = document.createElement("button");
        button.type = "button";
        const arrow = this._sortKey === column.key ? (this._sortDir === 1 ? " ▲" : " ▼") : "";
        button.textContent = column.label + arrow;
        button.addEventListener("click", () => {
          if (this._sortKey === column.key) this._sortDir *= -1;
          else {
            this._sortKey = column.key;
            this._sortDir = 1;
          }
          this._render();
        });
        th.appendChild(button);
        headRow.appendChild(th);
      }
      thead.appendChild(headRow);

      const tbody = document.createElement("tbody");
      for (const recording of filtered) {
        const tr = document.createElement("tr");
        tr.setAttribute("data-selectable", "");
        tr.tabIndex = 0;
        tr.setAttribute("role", "button");
        const cells = [
          recording.contentAddressedId.slice(0, 18) + "…",
          recording.filename,
          recording.format,
          `${recording.durationSeconds}s`,
          `${recording.sampleRate} Hz`,
          recording.channels,
          null, // validation badge
          recording.quality,
          recording.batchId,
          null, // status badge
        ];
        cells.forEach((value, index) => {
          const td = document.createElement("td");
          if (COLUMNS[index].key === "contentAddressedId") td.className = "id";
          if (COLUMNS[index].key === "validation") {
            const badge = document.createElement("avl-status-badge");
            badge.setAttribute("domain", "core");
            badge.setAttribute("state", VALIDATION_TO_BADGE[recording.validation] === "success" ? "ready" : VALIDATION_TO_BADGE[recording.validation] === "warning" ? "attention" : "error");
            td.appendChild(badge);
          } else if (COLUMNS[index].key === "processingState") {
            const badge = document.createElement("avl-status-badge");
            badge.setAttribute("domain", JOB_STATUS_DOMAIN);
            badge.setAttribute("state", "running");
            td.appendChild(badge);
          } else {
            td.textContent = value;
          }
          tr.appendChild(td);
        });
        tr.addEventListener("click", () => this._selectionModel?.select("recording", recording.id, recording));
        tr.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            tr.click();
          }
        });
        tbody.appendChild(tr);
      }
      table.append(thead, tbody);
      wrapper.appendChild(table);
    }

    this.shadowRoot.appendChild(wrapper);
  }

  _buildSelect(label, values, current, onChange) {
    const select = document.createElement("select");
    select.setAttribute("aria-label", `Filter by ${label}`);
    const allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = `All ${label.toLowerCase()}`;
    select.appendChild(allOption);
    for (const value of values) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    }
    select.value = current;
    select.addEventListener("change", () => {
      onChange(select.value);
      this._render();
    });
    return select;
  }
}

defineComponent("avl-workspace-recordings", AvlWorkspaceRecordings);
