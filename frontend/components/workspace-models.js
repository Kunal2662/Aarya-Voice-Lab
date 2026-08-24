// <avl-workspace-models> — VL-D1 §18. Model/runtime explorer.
// Vendor-neutral: the list of supported backends comes from
// frontend/contracts/generated/compute_backend.json (exported from
// identity/runtime.py's ComputeBackend) so NVIDIA is never privileged
// over AMD/Intel/CPU-only in this UI.
import { AvlElement, defineComponent } from "./base-element.js";
import { syntheticModels } from "../state/synthetic-fixtures.js";
import { fetchModelRegistrySnapshot } from "../state/model-registry-snapshot.js";
import "./workspace-state.js";
import "./model-card.js";
import "./panel.js";
import "./stat-tile.js";
import "./status-badge.js";

// VL-D17 -- appends a caption sub-line with `text` if `text` is a
// non-empty string, otherwise appends nothing. Used for the voice
// engine capability payload's `detail`/`missing_requirements` fields,
// which were already fetched into `this._engineCapabilities` but never
// rendered. A non-string (malformed backend value) is treated the same
// as absent -- never coerced into a fabricated-looking string.
function appendCaptionLine(container, text) {
  if (typeof text !== "string" || text.length === 0) return;
  const line = document.createElement("p");
  line.className = "avl-type-caption";
  line.textContent = text;
  container.appendChild(line);
}

// VL-D17 -- formats training_provider.missing_requirements (a real list
// of package names the provider itself reported) as one honest
// sentence. Returns null for anything that isn't a non-empty array, so
// an empty or malformed value renders nothing rather than an invented
// "no missing requirements" or "missing: " sentence.
function formatMissingRequirements(value) {
  if (!Array.isArray(value) || value.length === 0) return null;
  return `Missing requirements: ${value.map((item) => String(item)).join(", ")}.`;
}

// FE-3 -- same 5-tone cycle every other workspace dashboard uses.
const TILE_TONES = ["blue", "teal", "green", "violet", "pink"];

export class AvlWorkspaceModels extends AvlElement {
  set selectionModel(value) {
    this._selectionModel = value;
  }

  connectedCallback() {
    this._load();
  }

  async _load() {
    this._state = "loading";
    this._render();
    try {
      const response = await fetch(new URL("../contracts/generated/compute_backend.json", import.meta.url));
      this._backends = (await response.json()).values;
      this._models = syntheticModels();
      this._state = "ready";
    } catch (err) {
      this._state = "error";
      this._errorDetail = String(err);
    }
    // Real Voice Model Engine milestone -- a live, gitignored capability
    // snapshot (frontend/contracts/live/voice_engine_capabilities.json,
    // same pattern as dataset_gate_status.json/command_center_snapshot.json).
    // A 404 here is expected and honest in a fresh clone that hasn't run
    // `python scripts/export_voice_engine_capabilities.py` yet -- it must
    // never be treated as a real "unavailable" capability state.
    try {
      const response = await fetch(new URL("../contracts/live/voice_engine_capabilities.json", import.meta.url));
      this._engineCapabilities = response.ok ? await response.json() : null;
    } catch {
      this._engineCapabilities = null;
    }
    // VL-D12 -- the real model registry (private_voice entries always
    // excluded at the source, see registry.ModelRegistry.
    // list_non_private_models() and its own docstring). A missing/
    // malformed snapshot resolves to null and renders an honest
    // "not fetched" state, same as every other live snapshot here.
    this._registrySnapshot = await fetchModelRegistrySnapshot(
      new URL("../contracts/live/model_registry_snapshot.json", import.meta.url),
    );
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      .list { display: flex; flex-direction: column; gap: var(--avl-space-3); }
      .backend-list { display: flex; flex-wrap: wrap; gap: var(--avl-space-1); }
      .backend { font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); padding: var(--avl-space-1) var(--avl-space-2); border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-pill); color: var(--avl-color-text-secondary); }
      .dashboard-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: var(--avl-space-3); margin-bottom: var(--avl-space-4); }
      .engine-list { display: flex; flex-direction: column; gap: var(--avl-space-2); }
      .engine-row { display: flex; align-items: center; justify-content: space-between; gap: var(--avl-space-2); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");
    if (this._state === "error") wrapper.setAttribute("detail", this._errorDetail || "");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Models";
    wrapper.appendChild(heading);

    if (this._state === "ready" && this._models) {
      const dashboard = document.createElement("avl-panel");
      dashboard.setAttribute("title", "Model dashboard");
      const grid = document.createElement("div");
      grid.className = "dashboard-grid";
      const counts = {
        "Total models": this._models.length,
        "Backends supported": (this._backends || []).length,
        Installed: this._models.filter((m) => m.runtime === "installed").length,
        "Not installed": this._models.filter((m) => m.runtime !== "installed").length,
      };
      Object.entries(counts).forEach(([label, value], i) => {
        const tile = document.createElement("avl-stat-tile");
        tile.setAttribute("label", label);
        tile.setAttribute("value", String(value));
        tile.setAttribute("tone", TILE_TONES[i % TILE_TONES.length]);
        tile.setAttribute("icon", "models");
        grid.appendChild(tile);
      });
      dashboard.appendChild(grid);
      wrapper.appendChild(dashboard);
    }

    if (this._state === "ready") {
      const enginePanel = document.createElement("avl-panel");
      enginePanel.setAttribute("title", "Voice Model Engine — provider capability");
      const engineList = document.createElement("div");
      engineList.className = "engine-list";
      const capabilities = this._engineCapabilities;
      if (!capabilities) {
        const notice = document.createElement("p");
        notice.className = "avl-type-caption";
        notice.textContent =
          "No live capability snapshot fetched yet — run `python scripts/export_voice_engine_capabilities.py` " +
          "and reload. This is an honest \"not fetched\" state, never treated as NOT_CONFIGURED.";
        engineList.appendChild(notice);
      } else {
        for (const provider of capabilities.embedding_providers) {
          const row = document.createElement("div");
          row.className = "engine-row";
          const label = document.createElement("span");
          label.textContent = `Embedding: ${provider.name}`;
          row.appendChild(label);
          if (provider.is_synthetic) {
            const note = document.createElement("span");
            note.className = "avl-type-caption";
            note.textContent = "SYNTHETIC — deterministic test provider, never a real identity conclusion";
            row.appendChild(note);
          } else {
            const badge = document.createElement("avl-status-badge");
            badge.setAttribute("domain", "training_provider_state");
            badge.setAttribute("state", provider.state);
            row.appendChild(badge);
          }
          engineList.appendChild(row);
          // VL-D17 -- provider.detail was already fetched here alongside
          // .name/.state, but never rendered. Real, generic setup/timing/
          // exception text (see identity.embeddings' capability_state()
          // implementations) -- never a filesystem path, credential, or
          // private identifier.
          appendCaptionLine(engineList, provider.detail);
        }

        const generationRow = document.createElement("div");
        generationRow.className = "engine-row";
        const generationLabel = document.createElement("span");
        generationLabel.textContent = `Generation: ${capabilities.generation_provider.name}`;
        generationRow.appendChild(generationLabel);
        const generationBadge = document.createElement("avl-status-badge");
        generationBadge.setAttribute("domain", "generation_backend_state");
        generationBadge.setAttribute("state", capabilities.generation_provider.backend_state);
        generationRow.appendChild(generationBadge);
        engineList.appendChild(generationRow);

        const trainingRow = document.createElement("div");
        trainingRow.className = "engine-row";
        const trainingLabel = document.createElement("span");
        trainingLabel.textContent = `Training: ${capabilities.training_provider.name}`;
        trainingRow.appendChild(trainingLabel);
        const trainingBadge = document.createElement("avl-status-badge");
        trainingBadge.setAttribute("domain", "training_provider_state");
        trainingBadge.setAttribute("state", capabilities.training_provider.state);
        trainingRow.appendChild(trainingBadge);
        engineList.appendChild(trainingRow);
        // VL-D17 -- training_provider.detail/.missing_requirements were
        // already fetched here alongside .state, but never rendered.
        // This is the real, honest explanation of *why* training is
        // NOT_CONFIGURED (e.g. which packages are missing) -- it does not
        // change or replace the existing state badge above, and an empty
        // missing_requirements array renders nothing, never an invented
        // "no missing requirements" sentence.
        appendCaptionLine(engineList, capabilities.training_provider.detail);
        appendCaptionLine(engineList, formatMissingRequirements(capabilities.training_provider.missing_requirements));
      }
      enginePanel.appendChild(engineList);
      wrapper.appendChild(enginePanel);
    }

    if (this._state === "ready") {
      const registryPanel = document.createElement("avl-panel");
      registryPanel.setAttribute("title", "Model registry (real, checksum-addressed entries)");
      const registryList = document.createElement("div");
      registryList.className = "engine-list";
      const snapshot = this._registrySnapshot;
      if (!snapshot) {
        const notice = document.createElement("p");
        notice.className = "avl-type-caption";
        notice.textContent =
          "No live model registry snapshot fetched yet — run `python scripts/export_model_registry_snapshot.py` " +
          "and reload. This is an honest \"not fetched\" state, never a fabricated model list.";
        registryList.appendChild(notice);
      } else if (snapshot.models.length === 0) {
        const notice = document.createElement("p");
        notice.className = "avl-type-caption";
        notice.textContent = "No real (non-private) model is registered yet.";
        registryList.appendChild(notice);
      } else {
        for (const model of snapshot.models) {
          const row = document.createElement("div");
          row.className = "engine-row";
          const label = document.createElement("span");
          label.textContent = `${model.model_name} (${model.version}) — ${model.provider}`;
          row.appendChild(label);
          // model.lifecycle_state is null for registry entries created
          // before the Real Voice Model Engine milestone (schema note) --
          // that is a real absence, never fabricated into a specific badge.
          if (model.lifecycle_state) {
            const badge = document.createElement("avl-status-badge");
            badge.setAttribute("domain", "model_lifecycle");
            badge.setAttribute("state", model.lifecycle_state);
            row.appendChild(badge);
          } else {
            const note = document.createElement("span");
            note.className = "avl-type-caption";
            note.textContent = "no lifecycle state recorded";
            row.appendChild(note);
          }
          registryList.appendChild(row);
        }
      }
      registryPanel.appendChild(registryList);
      wrapper.appendChild(registryPanel);
    }

    if (this._backends) {
      const panel = document.createElement("avl-panel");
      panel.setAttribute("title", "Supported compute backends");
      const list = document.createElement("div");
      list.className = "backend-list";
      for (const backend of this._backends) {
        const el = document.createElement("span");
        el.className = "backend";
        el.textContent = backend;
        list.appendChild(el);
      }
      panel.appendChild(list);
      wrapper.appendChild(panel);
    }

    const list = document.createElement("div");
    list.className = "list";
    for (const model of this._models || []) {
      const card = document.createElement("avl-model-card");
      card.model = model;
      card.addEventListener("click", () => this._selectionModel?.select("model", model.id, model));
      list.appendChild(card);
    }
    wrapper.appendChild(list);

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-models", AvlWorkspaceModels);
