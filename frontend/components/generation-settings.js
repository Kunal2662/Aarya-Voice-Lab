// <avl-generation-settings> — VL-D5 §12. Set `.voiceProfileStore` and
// `.modelStore`. Renders the required Voice profile / Model selects plus
// the optional GENERATION_CONTROLS surface (speed/pitch/style/
// expressiveness/seed/output_format) -- but only the controls the
// selected model's own `capabilities` list actually supports. A control
// outside that list renders "NOT AVAILABLE for this model", never a
// fabricated default. Emits `avl-generation-settings-change` with the
// current selection on every change.
import { AvlElement, defineComponent } from "./base-element.js";
import { GENERATION_CONTROLS, SUPPORTED_SAMPLE_RATES } from "../state/generation-model.js";
import "./status-badge.js";

const CONTROL_LABELS = {
  speed: "Speed",
  pitch: "Pitch",
  style: "Style",
  expressiveness: "Expressiveness",
  seed: "Seed",
  output_format: "Output format",
};

// Controls covered by GENERATION_CONTROLS beyond the always-present
// voice/model selects -- each rendered only if the selected model
// supports it.
const OPTIONAL_CONTROLS = GENERATION_CONTROLS.filter((c) => c !== "voice" && c !== "model");

export class AvlGenerationSettings extends AvlElement {
  set voiceProfileStore(value) {
    this._voiceProfileStore = value;
    if (this.isConnected) this._render();
  }

  set modelStore(value) {
    this._modelStore = value;
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._selection = this._selection || {
      voiceProfileName: null,
      modelId: null,
      controls: {},
      seed: null,
      outputFormat: "wav",
      sampleRate: 16000,
    };
    this._render();
  }

  selection() {
    return { ...this._selection, controls: { ...this._selection.controls } };
  }

  _emit() {
    this.dispatchEvent(
      new CustomEvent("avl-generation-settings-change", { detail: this.selection(), bubbles: true, composed: true }),
    );
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      form { display: flex; flex-direction: column; gap: var(--avl-space-2); }
      label { display: flex; flex-direction: column; gap: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      select, input { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-sm); padding: var(--avl-space-1) var(--avl-space-2); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); }
      .unavailable { color: var(--avl-color-text-muted); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / var(--avl-type-caption-line-height) var(--avl-type-caption-family); }
      .backend { display: flex; align-items: center; gap: var(--avl-space-2); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._voiceProfileStore || !this._modelStore) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No voice profile / model store attached.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const form = document.createElement("form");
    form.addEventListener("submit", (e) => e.preventDefault());

    const profiles = this._voiceProfileStore.allLatest();
    const profileLabel = document.createElement("label");
    profileLabel.textContent = "Voice profile";
    const profileSelect = document.createElement("select");
    profileSelect.setAttribute("aria-label", "Voice profile");
    if (!profiles.length) {
      const option = document.createElement("option");
      option.textContent = "No voice profiles yet";
      option.disabled = true;
      profileSelect.appendChild(option);
    }
    for (const profile of profiles) {
      const option = document.createElement("option");
      option.value = profile.name;
      option.textContent = `${profile.name} (v${profile.version}, ${profile.state})`;
      if (this._selection.voiceProfileName === profile.name) option.selected = true;
      profileSelect.appendChild(option);
    }
    if (!this._selection.voiceProfileName && profiles.length) this._selection.voiceProfileName = profiles[0].name;
    profileSelect.addEventListener("change", () => {
      this._selection.voiceProfileName = profileSelect.value;
      this._emit();
    });
    profileLabel.appendChild(profileSelect);
    form.appendChild(profileLabel);

    const models = this._modelStore.list();
    const modelLabel = document.createElement("label");
    modelLabel.textContent = "Generation model / backend";
    const modelSelect = document.createElement("select");
    modelSelect.setAttribute("aria-label", "Generation model");
    for (const model of models) {
      const option = document.createElement("option");
      option.value = model.model_id;
      option.textContent = `${model.name} (${model.status})`;
      if (this._selection.modelId === model.model_id) option.selected = true;
      modelSelect.appendChild(option);
    }
    if (!this._selection.modelId && models.length) this._selection.modelId = models[0].model_id;
    modelSelect.addEventListener("change", () => {
      this._selection.modelId = modelSelect.value;
      this._selection.controls = {};
      this._render();
      this._emit();
    });
    modelLabel.appendChild(modelSelect);
    form.appendChild(modelLabel);

    const selectedModel = this._modelStore.get(this._selection.modelId);
    const backendRow = document.createElement("div");
    backendRow.className = "backend";
    const backendBadge = document.createElement("avl-status-badge");
    backendBadge.setAttribute("domain", "generation_backend_state");
    backendBadge.setAttribute("state", selectedModel ? selectedModel.status : "NOT_CONFIGURED");
    backendRow.appendChild(backendBadge);
    form.appendChild(backendRow);

    const supported = selectedModel ? selectedModel.capabilities || [] : [];
    for (const control of OPTIONAL_CONTROLS) {
      const label = document.createElement("label");
      label.textContent = CONTROL_LABELS[control] || control;
      if (!supported.includes(control)) {
        const note = document.createElement("span");
        note.className = "unavailable";
        note.textContent = "NOT AVAILABLE for this model";
        label.appendChild(note);
        form.appendChild(label);
        continue;
      }

      if (control === "output_format") {
        const select = document.createElement("select");
        select.setAttribute("aria-label", "Output format");
        for (const fmt of ["wav"]) {
          const option = document.createElement("option");
          option.value = fmt;
          option.textContent = fmt;
          if (this._selection.outputFormat === fmt) option.selected = true;
          select.appendChild(option);
        }
        select.addEventListener("change", () => {
          this._selection.outputFormat = select.value;
          this._emit();
        });
        label.appendChild(select);
      } else if (control === "seed") {
        const input = document.createElement("input");
        input.type = "number";
        input.setAttribute("aria-label", "Seed");
        input.placeholder = "(random if blank)";
        if (this._selection.seed != null) input.value = String(this._selection.seed);
        input.addEventListener("input", () => {
          this._selection.seed = input.value === "" ? null : Number(input.value);
          this._emit();
        });
        label.appendChild(input);
      } else {
        const input = document.createElement("input");
        input.type = "text";
        input.setAttribute("aria-label", CONTROL_LABELS[control] || control);
        input.value = this._selection.controls[control] || "";
        input.addEventListener("input", () => {
          if (input.value) this._selection.controls[control] = input.value;
          else delete this._selection.controls[control];
          this._emit();
        });
        label.appendChild(input);
      }
      form.appendChild(label);
    }

    const rateLabel = document.createElement("label");
    rateLabel.textContent = "Sample rate";
    const rateSelect = document.createElement("select");
    rateSelect.setAttribute("aria-label", "Sample rate");
    for (const rate of SUPPORTED_SAMPLE_RATES) {
      const option = document.createElement("option");
      option.value = String(rate);
      option.textContent = `${rate} Hz`;
      if (this._selection.sampleRate === rate) option.selected = true;
      rateSelect.appendChild(option);
    }
    rateSelect.addEventListener("change", () => {
      this._selection.sampleRate = Number(rateSelect.value);
      this._emit();
    });
    rateLabel.appendChild(rateSelect);
    form.appendChild(rateLabel);

    this.shadowRoot.appendChild(form);
  }
}

defineComponent("avl-generation-settings", AvlGenerationSettings);
