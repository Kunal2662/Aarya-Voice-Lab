// <avl-processing-profile-editor> — VL-D4 §6, §22. Set `.profileStore`
// to a state/processing-model.js ProcessingProfileStore. Lists every
// named profile's latest version, with view/create/duplicate/version/
// set-default actions. There is deliberately no "edit in place" control
// — changing a field always goes through createVersion(), which appends
// a new, independently addressable version rather than mutating the one
// before it (mirrors ProcessingProfileStore's own guarantee).
import { AvlElement, defineComponent } from "./base-element.js";
import { NoiseConditioningMode } from "../state/processing-model.js";
import "./status-badge.js";
import "./button.js";

export class AvlProcessingProfileEditor extends AvlElement {
  set profileStore(value) {
    if (this._profileStore) this._profileStore.removeEventListener("change", this._onChange);
    this._profileStore = value;
    if (value) {
      this._onChange = () => this._render();
      value.addEventListener("change", this._onChange);
    }
    if (this.isConnected) this._render();
  }

  connectedCallback() {
    this._render();
  }

  disconnectedCallback() {
    if (this._profileStore) this._profileStore.removeEventListener("change", this._onChange);
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      table { width: 100%; border-collapse: collapse; margin-bottom: var(--avl-space-3); }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      th { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; }
      .actions { display: flex; gap: var(--avl-space-1); flex-wrap: wrap; }
      form { display: flex; gap: var(--avl-space-2); align-items: flex-end; flex-wrap: wrap; }
      label { display: flex; flex-direction: column; gap: var(--avl-space-1); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); color: var(--avl-color-text-secondary); }
      input, select { padding: var(--avl-space-1) var(--avl-space-2); border-radius: var(--avl-radius-sm); border: 1px solid var(--avl-color-border-default); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      .default-marker { color: var(--avl-color-state-success); }
    `;
    this.shadowRoot.appendChild(style);

    if (!this._profileStore) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No profile store attached.";
      this.shadowRoot.appendChild(empty);
      return;
    }

    const names = this._profileStore.names();
    const defaultProfile = this._profileStore.default();

    if (names.length) {
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      thead.innerHTML = "<tr><th>Name</th><th>Version</th><th>Noise mode</th><th>Default</th><th>Actions</th></tr>";
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      for (const name of names) {
        const profile = this._profileStore.latest(name);
        const row = document.createElement("tr");
        row.innerHTML = `
          <td>${profile.name}</td>
          <td>v${profile.version}</td>
        `;
        const noiseCell = document.createElement("td");
        const noiseBadge = document.createElement("avl-status-badge");
        noiseBadge.setAttribute("domain", "noise_conditioning_mode");
        noiseBadge.setAttribute("state", profile.noiseConditioningMode || NoiseConditioningMode.MEASURE_ONLY);
        noiseCell.appendChild(noiseBadge);
        row.appendChild(noiseCell);

        const defaultCell = document.createElement("td");
        defaultCell.className = "default-marker";
        defaultCell.textContent = defaultProfile && defaultProfile.name === name ? "✓" : "";
        row.appendChild(defaultCell);

        const actionsCell = document.createElement("td");
        actionsCell.className = "actions";

        const versionButton = document.createElement("avl-button");
        versionButton.setAttribute("variant", "secondary");
        versionButton.textContent = "New version";
        versionButton.addEventListener("click", () => {
          this._profileStore.createVersion(name, { notes: `Version created ${new Date().toISOString()}` });
        });
        actionsCell.appendChild(versionButton);

        const duplicateButton = document.createElement("avl-button");
        duplicateButton.setAttribute("variant", "secondary");
        duplicateButton.textContent = "Duplicate";
        duplicateButton.addEventListener("click", () => {
          const newName = `${name}-copy-${Date.now().toString(36)}`;
          this._profileStore.duplicate(name, newName);
        });
        actionsCell.appendChild(duplicateButton);

        const setDefaultButton = document.createElement("avl-button");
        setDefaultButton.setAttribute("variant", "secondary");
        setDefaultButton.textContent = "Set default";
        setDefaultButton.addEventListener("click", () => this._profileStore.setDefault(name));
        actionsCell.appendChild(setDefaultButton);

        row.appendChild(actionsCell);
        tbody.appendChild(row);
      }
      table.appendChild(tbody);
      this.shadowRoot.appendChild(table);
    } else {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No processing profiles yet.";
      this.shadowRoot.appendChild(empty);
    }

    const form = document.createElement("form");
    const nameLabel = document.createElement("label");
    nameLabel.textContent = "New profile name";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.placeholder = "e.g. conservative";
    nameLabel.appendChild(nameInput);
    form.appendChild(nameLabel);

    const noiseLabel = document.createElement("label");
    noiseLabel.textContent = "Noise conditioning";
    const noiseSelect = document.createElement("select");
    for (const mode of Object.values(NoiseConditioningMode)) {
      const option = document.createElement("option");
      option.value = mode;
      option.textContent = mode;
      noiseSelect.appendChild(option);
    }
    noiseSelect.value = NoiseConditioningMode.MEASURE_ONLY;
    noiseLabel.appendChild(noiseSelect);
    form.appendChild(noiseLabel);

    const createButton = document.createElement("avl-button");
    createButton.setAttribute("variant", "primary");
    createButton.setAttribute("type", "button");
    createButton.textContent = "Create profile";
    createButton.addEventListener("click", () => {
      const name = nameInput.value.trim();
      if (!name) return;
      try {
        this._profileStore.create(name, { noiseConditioningMode: noiseSelect.value, notes: null });
        nameInput.value = "";
      } catch (err) {
        this._announce(err.message);
      }
    });
    form.appendChild(createButton);
    this.shadowRoot.appendChild(form);
  }
}

defineComponent("avl-processing-profile-editor", AvlProcessingProfileEditor);
