// <avl-workspace-calibration> — VL-D1 §19. Two distinct calibration
// concepts, shown separately and labeled clearly so they are never
// confused:
//   1. Hardware/runtime calibration ("hardware_calibration" domain) —
//      the future AI Calibration Engine (VL-D15) profiling THIS host.
//      No engine exists; always UNCALIBRATED, no fabricated numbers.
//   2. Target-speaker verification calibration ("calibration" domain,
//      identity/calibration.py's CalibrationState) — reuses the VL-D0
//      avl-calibration-panel unchanged.
import { AvlElement, defineComponent } from "./base-element.js";
import "./workspace-state.js";
import "./panel.js";
import "./status-badge.js";
import "./metric-placeholder.js";
import "./hardware-profile-card.js";
import "./calibration-panel.js";

export class AvlWorkspaceCalibration extends AvlElement {
  connectedCallback() {
    this._load();
  }

  async _load() {
    this._state = "loading";
    this._render();
    this._state = "ready";
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `h2 { margin: 0 0 var(--avl-space-3) 0; } .section { margin-bottom: var(--avl-space-4); }`;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", this._state || "loading");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Calibration";
    wrapper.appendChild(heading);

    const hardwareSection = document.createElement("div");
    hardwareSection.className = "section";
    const hardwarePanel = document.createElement("avl-panel");
    hardwarePanel.setAttribute("title", "Hardware / runtime calibration");
    const hardwareBadge = document.createElement("avl-status-badge");
    hardwareBadge.setAttribute("domain", "hardware_calibration");
    hardwareBadge.setAttribute("state", "UNCALIBRATED");
    hardwarePanel.appendChild(hardwareBadge);
    for (const label of ["CPU", "RAM", "GPU", "VRAM", "Runtime", "Backend", "Compatibility"]) {
      const metric = document.createElement("avl-metric-placeholder");
      metric.setAttribute("label", label);
      hardwarePanel.appendChild(metric);
    }
    const hardwareCard = document.createElement("avl-hardware-profile-card");
    hardwarePanel.appendChild(hardwareCard);
    hardwareSection.appendChild(hardwarePanel);
    wrapper.appendChild(hardwareSection);

    const speakerSection = document.createElement("div");
    speakerSection.className = "section";
    const speakerPanel = document.createElement("avl-panel");
    speakerPanel.setAttribute("title", "Target-speaker verification calibration");
    speakerPanel.appendChild(document.createElement("avl-calibration-panel"));
    speakerSection.appendChild(speakerPanel);
    wrapper.appendChild(speakerSection);

    this.shadowRoot.appendChild(wrapper);
  }
}

defineComponent("avl-workspace-calibration", AvlWorkspaceCalibration);
