// <avl-workspace-preview> — VL-D5 §10. The Voice Preview + Generation
// workspace: Generation / Voice Profile / Text Input / Generation
// Settings / Preview Queue / Generated Outputs / A-B Comparison /
// Feedback / History / Provenance, over the session-only synthetic
// generation simulation in state/generation-model.js.
//
// NOT the final Aarya voice (§3). No real speaker embeddings, no real
// target-speaker identity, no real recordings are read here — every
// generated output is a deterministic synthetic tone, always tagged
// SYNTHETIC_FIXTURE, never GENERATED_SPEECH. Selecting a voice profile
// routes through the shared selectionModel exactly like
// avl-workspace-processing, so the expanded Inspector (§20) renders its
// Preview section for whatever profile is selected.
import { AvlElement, defineComponent } from "./base-element.js";
import { GenerationStatus, buildPreviewRequest } from "../state/generation-model.js";
import "./workspace-state.js";
import "./status-badge.js";
import "./button.js";
import "./text-input.js";
import "./generation-settings.js";
import "./generation-queue.js";
import "./voice-preview-card.js";
import "./ab-comparison.js";
import "./preview-feedback-form.js";

export class AvlWorkspacePreview extends AvlElement {
  set selectionModel(value) {
    this._selectionModel = value;
  }

  set services(value) {
    this._services = value || {};
    for (const store of [
      this._services.generationQueueStore,
      this._services.voiceProfileStore,
      this._services.generationModelStore,
      this._services.previewHistoryStore,
    ]) {
      if (store) store.addEventListener("change", () => this._scheduleRender());
    }
  }

  // Several store "change" events can arrive in quick succession -- e.g.
  // a completed generation's own status-transition event, followed one
  // microtask later by previewHistoryStore.record()'s change event from
  // inside processOne()'s .then() continuation. Each would otherwise
  // trigger its own full teardown-and-rebuild of the outputs list, which
  // can tear an in-flight <audio> element out of the document mid-fetch.
  // A macrotask (not microtask) boundary is needed to coalesce across
  // that .then() continuation too, since a queueMicrotask() callback can
  // still run before a later .then() microtask is even queued.
  _scheduleRender() {
    if (this._renderScheduled) return;
    this._renderScheduled = true;
    setTimeout(() => {
      this._renderScheduled = false;
      this._render();
    }, 0);
  }

  connectedCallback() {
    this._draftText = this._draftText || "";
    this._focusedItemId = this._focusedItemId || null;
    this._compareWithItemId = this._compareWithItemId || null;

    const profileStore = this._services?.voiceProfileStore;
    if (profileStore && !profileStore.names().length) {
      profileStore.create("demo-voice", { style_controls: { pace: "moderate" } });
    }
    this._render();
  }

  _dashboardCounts() {
    const queue = this._services?.generationQueueStore;
    const items = queue ? queue.list() : [];
    const counts = queue ? queue.counts() : {};
    const durations = items.map((i) => i.generation_duration_seconds).filter((d) => d != null);
    const avgDuration = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null;
    return { total: items.length, counts, avgDuration };
  }

  _render() {
    this.shadowRoot.innerHTML = "";
    this._linkSharedStyles();

    const style = document.createElement("style");
    style.textContent = `
      h2 { margin: 0 0 var(--avl-space-3) 0; }
      h3 { margin: var(--avl-space-4) 0 var(--avl-space-2) 0; font: var(--avl-type-subheading-weight) var(--avl-type-subheading-size) / var(--avl-type-subheading-line-height) var(--avl-type-subheading-family); }
      .dashboard { display: grid; grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr)); gap: var(--avl-space-2); margin-bottom: var(--avl-space-4); }
      .metric { border: 1px solid var(--avl-color-border-subtle); border-radius: var(--avl-radius-sm); padding: var(--avl-space-2); }
      .metric .value { font: var(--avl-type-heading-weight) var(--avl-type-heading-size) / 1 var(--avl-type-heading-family); }
      .metric .label { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); text-transform: uppercase; letter-spacing: 0.04em; }
      table { width: 100%; border-collapse: collapse; }
      th, td { text-align: left; padding: var(--avl-space-1) var(--avl-space-2); border-bottom: 1px solid var(--avl-color-border-subtle); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); }
      tr[data-selectable] { cursor: pointer; }
      tr[data-selectable]:hover { background: var(--avl-color-surface-sunken); }
      .row { display: flex; justify-content: space-between; gap: var(--avl-space-2); padding: var(--avl-space-1) 0; border-bottom: 1px solid var(--avl-color-border-subtle); }
      .rows { display: flex; flex-direction: column; }
      .label { color: var(--avl-color-text-secondary); font: var(--avl-type-caption-weight) var(--avl-type-caption-size) / 1 var(--avl-type-caption-family); }
      .value { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / 1 var(--avl-type-body-small-family); text-align: right; word-break: break-word; }
      .empty { color: var(--avl-color-text-muted); font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); }
      select { font: var(--avl-type-body-small-weight) var(--avl-type-body-small-size) / var(--avl-type-body-small-line-height) var(--avl-type-body-small-family); border: 1px solid var(--avl-color-border-default); border-radius: var(--avl-radius-sm); padding: var(--avl-space-1) var(--avl-space-2); background: var(--avl-color-surface-raised); color: var(--avl-color-text-primary); }
    `;
    this.shadowRoot.appendChild(style);

    const wrapper = document.createElement("avl-workspace-state");
    wrapper.setAttribute("state", "ready");

    const heading = document.createElement("h2");
    heading.className = "avl-type-heading";
    heading.textContent = "Voice Preview";
    wrapper.appendChild(heading);

    const stats = this._dashboardCounts();
    const dashboard = document.createElement("div");
    dashboard.className = "dashboard";
    for (const [label, value] of [
      ["Total requested", stats.total],
      ["Queued", stats.counts[GenerationStatus.QUEUED] || 0],
      [
        "Generating",
        (stats.counts[GenerationStatus.PREPARING] || 0) +
          (stats.counts[GenerationStatus.GENERATING] || 0) +
          (stats.counts[GenerationStatus.POST_PROCESSING] || 0),
      ],
      ["Ready", stats.counts[GenerationStatus.READY] || 0],
      ["Warning", stats.counts[GenerationStatus.WARNING] || 0],
      ["Failed", stats.counts[GenerationStatus.FAILED] || 0],
      ["Blocked", stats.counts[GenerationStatus.BLOCKED] || 0],
      ["Cancelled", stats.counts[GenerationStatus.CANCELLED] || 0],
      ["Avg duration", stats.avgDuration != null ? `${stats.avgDuration.toFixed(2)}s` : "—"],
    ]) {
      const metric = document.createElement("div");
      metric.className = "metric";
      metric.innerHTML = `<div class="value">${value}</div><div class="label">${label}</div>`;
      dashboard.appendChild(metric);
    }
    wrapper.appendChild(dashboard);

    const profilesHeading = document.createElement("h3");
    profilesHeading.textContent = "Voice profiles";
    wrapper.appendChild(profilesHeading);
    wrapper.appendChild(this._buildVoiceProfilesTable());

    const generationHeading = document.createElement("h3");
    generationHeading.textContent = "Generation";
    wrapper.appendChild(generationHeading);
    wrapper.appendChild(this._buildGenerationForm());

    const queueHeading = document.createElement("h3");
    queueHeading.textContent = "Preview Queue";
    wrapper.appendChild(queueHeading);
    const queueEl = document.createElement("avl-generation-queue");
    queueEl.queue = this._services?.generationQueueStore;
    queueEl.addEventListener("avl-preview-open", (event) => {
      this._focusedItemId = event.detail.item.item_id;
      this._render();
    });
    wrapper.appendChild(queueEl);

    const outputsHeading = document.createElement("h3");
    outputsHeading.textContent = "Generated Outputs";
    wrapper.appendChild(outputsHeading);
    wrapper.appendChild(this._buildOutputsList());

    const focusedItem = this._focusedItem();
    if (focusedItem && focusedItem.artifact) {
      const feedbackHeading = document.createElement("h3");
      feedbackHeading.textContent = "Feedback";
      wrapper.appendChild(feedbackHeading);
      const feedbackForm = document.createElement("avl-preview-feedback-form");
      feedbackForm.feedbackStore = this._services?.previewFeedbackStore;
      feedbackForm.artifact = focusedItem.artifact;
      wrapper.appendChild(feedbackForm);

      const abHeading = document.createElement("h3");
      abHeading.textContent = "A / B Comparison";
      wrapper.appendChild(abHeading);
      wrapper.appendChild(this._buildAbComparisonSection(focusedItem));

      const provenanceHeading = document.createElement("h3");
      provenanceHeading.textContent = "Provenance";
      wrapper.appendChild(provenanceHeading);
      wrapper.appendChild(this._buildProvenanceRows(focusedItem));
    }

    this.shadowRoot.appendChild(wrapper);
  }

  _focusedItem() {
    if (!this._focusedItemId || !this._services?.generationQueueStore) return null;
    return this._services.generationQueueStore.get(this._focusedItemId);
  }

  _completedItems() {
    const queue = this._services?.generationQueueStore;
    return queue ? queue.list().filter((i) => i.artifact) : [];
  }

  _buildVoiceProfilesTable() {
    const profileStore = this._services?.voiceProfileStore;
    const profiles = profileStore ? profileStore.allLatest() : [];

    const wrapper = document.createElement("div");
    if (!profiles.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No voice profiles yet.";
      wrapper.appendChild(empty);
      return wrapper;
    }

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Name</th><th>Version</th><th>State</th></tr>";
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const profile of profiles) {
      const row = document.createElement("tr");
      row.setAttribute("data-selectable", "");
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.innerHTML = `<td>${profile.name}</td><td>${profile.version}</td><td>${profile.state}</td>`;
      row.addEventListener("click", () => {
        this._selectionModel?.select("voice-profile", profile.profile_id, profile);
      });
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          row.click();
        }
      });
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    wrapper.appendChild(table);
    return wrapper;
  }

  _buildGenerationForm() {
    const wrapper = document.createElement("div");

    const textInput = document.createElement("avl-text-input");
    textInput.value = this._draftText;
    textInput.addEventListener("avl-text-change", (event) => {
      this._draftText = event.detail.text;
    });
    wrapper.appendChild(textInput);

    const settings = document.createElement("avl-generation-settings");
    settings.voiceProfileStore = this._services?.voiceProfileStore;
    settings.modelStore = this._services?.generationModelStore;
    settings.addEventListener("avl-generation-settings-change", (event) => {
      this._settingsSelection = event.detail;
      const modelStore = this._services?.generationModelStore;
      textInput.capabilities = modelStore ? modelStore.capabilitiesFor(event.detail.modelId) : null;
    });
    wrapper.appendChild(settings);

    const generateButton = document.createElement("avl-button");
    generateButton.setAttribute("variant", "primary");
    generateButton.textContent = "Generate preview";
    generateButton.addEventListener("click", () => this._generate(settings));
    wrapper.appendChild(generateButton);

    return wrapper;
  }

  _generate(settingsEl) {
    const queueStore = this._services?.generationQueueStore;
    const profileStore = this._services?.voiceProfileStore;
    if (!queueStore || !profileStore) return;

    const selection = settingsEl.selection();
    if (!selection.voiceProfileName || !selection.modelId) return;
    const profile = profileStore.latest(selection.voiceProfileName);

    const request = buildPreviewRequest({
      text: this._draftText,
      voiceProfileId: profile.profile_id,
      modelId: selection.modelId,
      sampleRate: selection.sampleRate,
      outputFormat: selection.outputFormat,
      seed: selection.seed,
      controls: selection.controls,
    });
    const item = queueStore.enqueue(request);
    this._focusedItemId = item.item_id;
    // No explicit _render() here after processOne resolves: enqueue()'s
    // and processOne()'s own status transitions, and
    // previewHistoryStore.record()'s own "change" event, already reach
    // this component through the coalesced _scheduleRender() listeners
    // wired in `set services()` above.
    queueStore.processOne(item.item_id).then((result) => {
      if (this._services.previewHistoryStore) {
        this._services.previewHistoryStore.record(result, { voiceProfileId: profile.profile_id });
      }
    });
    this._render();
  }

  _buildOutputsList() {
    const items = this._completedItems();
    const wrapper = document.createElement("div");
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No generated outputs yet.";
      wrapper.appendChild(empty);
      return wrapper;
    }

    for (const item of items) {
      const card = document.createElement("avl-voice-preview-card");
      card.artifact = item.artifact;
      const feedbackStore = this._services?.previewFeedbackStore;
      const feedback = feedbackStore ? feedbackStore.feedbackFor(item.artifact.preview_id) : [];
      card.feedback = feedback.length ? feedback[feedback.length - 1] : null;
      card.style.display = "block";
      card.style.marginBottom = "var(--avl-space-2)";
      card.addEventListener("click", (event) => {
        // A click on the card's own embedded playback controls (Play/
        // Pause/Stop/Seek/Volume/Speed) bubbles here too -- composed
        // click events cross every shadow boundary. Treating that as
        // "focus this card" would immediately tear down and rebuild the
        // whole outputs list, destroying the very <audio> element whose
        // button was just pressed while its blob fetch is still in
        // flight. Only focus on a genuine click on the card chrome
        // itself, not on an interactive control inside it.
        const interactive = event.composedPath().some((el) => el.tagName === "BUTTON" || el.tagName === "SELECT" || el.tagName === "INPUT");
        if (interactive) return;
        this._focusedItemId = item.item_id;
        this._render();
      });
      wrapper.appendChild(card);
    }
    return wrapper;
  }

  _buildAbComparisonSection(focusedItem) {
    const wrapper = document.createElement("div");
    const others = this._completedItems().filter((i) => i.item_id !== focusedItem.item_id);

    const select = document.createElement("select");
    select.setAttribute("aria-label", "Compare with");
    const noneOption = document.createElement("option");
    noneOption.value = "";
    noneOption.textContent = "Select an output to compare with…";
    select.appendChild(noneOption);
    for (const other of others) {
      const option = document.createElement("option");
      option.value = other.item_id;
      option.textContent = other.request.text.slice(0, 40);
      if (this._compareWithItemId === other.item_id) option.selected = true;
      select.appendChild(option);
    }
    select.addEventListener("change", () => {
      this._compareWithItemId = select.value || null;
      this._render();
    });
    wrapper.appendChild(select);

    const compareWith = this._compareWithItemId
      ? this._services.generationQueueStore.get(this._compareWithItemId)
      : null;
    if (compareWith && compareWith.artifact) {
      const ab = document.createElement("avl-ab-comparison");
      ab.feedbackStore = this._services?.previewFeedbackStore;
      ab.labels = ["Focused", "Compare"];
      ab.left = focusedItem.artifact;
      ab.right = compareWith.artifact;
      wrapper.appendChild(ab);
    }
    return wrapper;
  }

  _buildProvenanceRows(item) {
    const rows = document.createElement("div");
    rows.className = "rows";
    for (const [label, value] of [
      ["Request ID", item.request.request_id],
      ["Output ID", item.artifact.preview_id],
      ["Config hash", item.request.config_hash],
      ["Output SHA-256", item.artifact.sha256],
      ["Artifact ID", item.artifact.artifact_id],
      ["Model", `${item.artifact.model_name} v${item.artifact.model_version}`],
      ["Kind", item.artifact.kind],
      ["Synthetic", String(item.artifact.is_synthetic)],
    ]) {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `<span class="label">${label}</span><span class="value">${value == null || value === "" ? "—" : value}</span>`;
      rows.appendChild(row);
    }
    return rows;
  }
}

defineComponent("avl-workspace-preview", AvlWorkspacePreview);
