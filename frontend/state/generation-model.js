// Client-side voice-generation state (VL-D5 §4-§7, §12, §13, §17-§23).
// Mirrors pipeline.generation / pipeline.voice_profile /
// pipeline.generation_models / pipeline.preview_history /
// pipeline.preview_feedback's vocabulary and append-only semantics
// exactly, but this is a session-scoped, in-memory simulation over
// state/synthetic-fixtures.js data -- there is still no execution
// transport (state/command-executor.js, unchanged since VL-D1) to
// actually run a TTS engine or write a real preview artifact into
// data/previews/. "Generating" here computes a deterministic,
// PreviewArtifact-shaped record after a short, clearly-labelled
// simulated delay -- it never claims to represent a real person's voice
// (VL-D5 §3). Playback itself is handled entirely by avl-audio-player
// (state/synthetic-tone.js), which only needs `preview_id`/
// `duration_seconds` from the artifact, not a real audio file.
//
// Field-naming convention, deliberately not the VL-D4 camelCase-only
// style: any record shaped like a backend `to_dict()` (PreviewRequest,
// GenerationItem, PreviewArtifact, VoiceProfile, GenerationModel,
// PreviewHistoryRecord, PreviewFeedback) keeps that exact snake_case
// shape, so it stays a drop-in match for the already-shipped VL-D0/D1
// components (avl-voice-player, avl-voice-feedback, avl-voice-version,
// avl-voice-comparison) that already read `artifact.preview_id`,
// `feedback.outcome`, etc. Store/class/method names stay camelCase, the
// normal JS convention for this file's own API surface.

export const GenerationBackendState = Object.freeze({
  AVAILABLE: "AVAILABLE",
  UNAVAILABLE: "UNAVAILABLE",
  NOT_CONFIGURED: "NOT_CONFIGURED",
  NOT_SUPPORTED: "NOT_SUPPORTED",
  BLOCKED: "BLOCKED",
  ERROR: "ERROR",
});

export const GenerationStatus = Object.freeze({
  QUEUED: "QUEUED",
  PREPARING: "PREPARING",
  GENERATING: "GENERATING",
  POST_PROCESSING: "POST_PROCESSING",
  READY: "READY",
  WARNING: "WARNING",
  FAILED: "FAILED",
  CANCELLED: "CANCELLED",
  BLOCKED: "BLOCKED",
});

const TERMINAL_STATUSES = new Set([
  GenerationStatus.READY,
  GenerationStatus.WARNING,
  GenerationStatus.FAILED,
  GenerationStatus.CANCELLED,
  GenerationStatus.BLOCKED,
]);

export function isTerminalGenerationStatus(status) {
  return TERMINAL_STATUSES.has(status);
}

// Mirrors pipeline.generation.GENERATION_CONTROLS exactly (VL-D5 §12). A
// control missing from a model's own `capabilities` list must render NOT
// AVAILABLE, never a fabricated default.
export const GENERATION_CONTROLS = Object.freeze([
  "voice",
  "model",
  "speed",
  "pitch",
  "style",
  "expressiveness",
  "seed",
  "output_format",
]);

// Mirrors pipeline.voice_profile.VoiceProfileState (VL-D5 §8, §9).
export const VoiceProfileState = Object.freeze({
  SYNTHETIC_PROFILE: "SYNTHETIC_PROFILE",
  UNCALIBRATED: "UNCALIBRATED",
});

// Mirrors identity.preview.PreviewFeedbackOutcome, reused directly by
// pipeline.preview_feedback (VL-D5 §21) -- the same values
// avl-voice-feedback.js already dispatches.
export const PreviewFeedbackOutcome = Object.freeze({
  ACCEPTED: "accepted",
  REJECTED: "rejected",
  REGENERATE: "regenerate",
  UNCERTAIN: "uncertain",
});

// Mirrors pipeline.preview_feedback.PreviewFeedbackCategory (VL-D5 §21).
export const PreviewFeedbackCategory = Object.freeze({
  VOICE_QUALITY: "VOICE_QUALITY",
  NATURALNESS: "NATURALNESS",
  CLARITY: "CLARITY",
  PRONUNCIATION: "PRONUNCIATION",
  PACE: "PACE",
  PITCH: "PITCH",
  PROSODY: "PROSODY",
  STYLE: "STYLE",
  ARTIFACTS: "ARTIFACTS",
  OVERALL: "OVERALL",
});

export const MAX_TEXT_LENGTH = 5000;
export const SUPPORTED_SAMPLE_RATES = Object.freeze([16000, 22050, 44100]);

/** Mirrors pipeline.preview_feedback.UnlistenedFeedbackError: "no
 * generated result should be treated as final without a previewable
 * output" (VL-D5 §15) is enforced here, not left to the caller. */
export class UnlistenedFeedbackError extends Error {}

/** Mirrors pipeline.generation.GenerationBlockedError -- the request
 * could not be generated at all, distinct from an unexpected failure. */
export class GenerationBlockedError extends Error {}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// A small, fast, non-cryptographic hash expanded to a sha256-shaped 64
// hex character string -- reproducible for identical inputs (VL-D5 §6's
// "same request/config should reproduce the same output where
// practical"), never presented as a real digest of any audio bytes.
function deterministicHex64(seedString) {
  let h = 0x811c9dc5;
  for (let i = 0; i < seedString.length; i++) {
    h ^= seedString.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  const hex = (h >>> 0).toString(16).padStart(8, "0");
  return hex.repeat(8).slice(0, 64);
}

function stableStringify(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(value[k])}`).join(",")}}`;
}

function computeConfigHash({ voiceProfileId, generationProfileId, modelId, sampleRate, outputFormat, seed, controls }) {
  return deterministicHex64(
    stableStringify({
      voice_profile_id: voiceProfileId,
      generation_profile_id: generationProfileId,
      model_id: modelId,
      sample_rate: sampleRate,
      output_format: outputFormat,
      seed,
      controls,
    }),
  );
}

let _requestCounter = 0;

/** Mirrors pipeline.generation.build_preview_request: a versioned
 * generation request, `request_id` a sequential id, never dependent on a
 * timestamp (§7). */
export function buildPreviewRequest({
  text,
  voiceProfileId,
  modelId,
  generationProfileId = null,
  sampleRate = 16000,
  outputFormat = "wav",
  seed = null,
  controls = {},
}) {
  _requestCounter += 1;
  const controlsCopy = { ...controls };
  return {
    request_id: `preview-req-${String(_requestCounter).padStart(5, "0")}`,
    text,
    voice_profile_id: voiceProfileId,
    generation_profile_id: generationProfileId,
    model_id: modelId,
    sample_rate: sampleRate,
    output_format: outputFormat,
    seed,
    controls: controlsCopy,
    config_hash: computeConfigHash({
      voiceProfileId,
      generationProfileId,
      modelId,
      sampleRate,
      outputFormat,
      seed,
      controls: controlsCopy,
    }),
  };
}

/** Mirrors pipeline.generation.SyntheticVoiceGenerator.validate_request /
 * UnavailableVoiceGenerator.validate_request, generalised over any
 * `capabilities`-shaped record (see GenerationModelStore). Returns an
 * empty list when the request is valid. */
export function validateGenerationRequest(request, capabilities) {
  const errors = [];
  if (!capabilities || capabilities.backend_state !== GenerationBackendState.AVAILABLE) {
    const state = capabilities ? capabilities.backend_state : GenerationBackendState.NOT_CONFIGURED;
    errors.push(`backend is ${String(state).toLowerCase()}`);
    return errors;
  }
  const text = request.text || "";
  if (!text.trim()) {
    errors.push("text must not be empty");
  } else if (text.length > MAX_TEXT_LENGTH) {
    errors.push(`text exceeds ${MAX_TEXT_LENGTH} characters`);
  }
  if (!SUPPORTED_SAMPLE_RATES.includes(request.sample_rate)) {
    errors.push(`sample_rate must be one of ${SUPPORTED_SAMPLE_RATES.join(", ")}`);
  }
  const controls = request.controls || {};
  const supported = capabilities.supported_controls || [];
  const unsupported = Object.keys(controls).filter((c) => !supported.includes(c));
  if (unsupported.length) {
    errors.push(`unsupported control(s): ${unsupported.slice().sort().join(", ")}`);
  }
  return errors;
}

/** Mirrors pipeline.generation.SyntheticVoiceGenerator.estimate_requirements
 * / UnavailableVoiceGenerator.estimate_requirements -- an honest
 * estimate, never a guarantee (§11: never claim exact duration unless
 * backend-verified). */
export function estimateGenerationRequirements(request, capabilities) {
  if (!capabilities || capabilities.backend_state !== GenerationBackendState.AVAILABLE) {
    const state = capabilities ? capabilities.backend_state : GenerationBackendState.NOT_CONFIGURED;
    return { estimate_basis: `not available -- backend is ${String(state).toLowerCase()}` };
  }
  const text = (request.text || "").trim();
  const wordCount = text ? text.split(/\s+/).length : 0;
  const estimatedDurationSeconds = wordCount ? Math.round((wordCount / 2.5) * 100) / 100 : 0;
  return {
    word_count: wordCount,
    character_count: (request.text || "").length,
    estimated_duration_seconds: estimatedDurationSeconds,
    estimate_basis: "heuristic word-rate estimate, not measured",
  };
}

function buildSyntheticArtifact(request, model) {
  const text = (request.text || "").trim();
  const wordCount = text ? text.split(/\s+/).length : 0;
  const durationSeconds = Math.min(Math.max(wordCount / 2.5, 0.5), 10.0);
  const generatorName = model ? model.name : "synthetic-tone";
  const generatorVersion = model ? model.version : "0.1.0";
  return {
    preview_id: `${request.request_id}-preview`,
    kind: "synthetic_fixture",
    relative_path: `previews/${request.request_id}.wav`,
    sha256: deterministicHex64(`${request.text}|${request.config_hash}|${request.seed ?? ""}`),
    duration_seconds: Math.round(durationSeconds * 1e6) / 1e6,
    sample_rate: request.sample_rate,
    iteration: 1,
    origin_id: request.request_id,
    model_name: generatorName,
    model_version: generatorVersion,
    is_synthetic: true,
    created_at: new Date().toISOString(),
    artifact_id: deterministicHex64(`fingerprint|${request.config_hash}|${request.text}`),
  };
}

/** Mirrors pipeline.generation.build_ab_comparison (VL-D5 §16):
 * metadata-only, never claims acoustic similarity. */
export function buildAbComparison(artifactA, artifactB) {
  const durationA = artifactA ? artifactA.duration_seconds : null;
  const durationB = artifactB ? artifactB.duration_seconds : null;
  return {
    duration_diff_seconds:
      durationA != null && durationB != null ? Math.round(Math.abs(durationA - durationB) * 1e6) / 1e6 : null,
    sample_rate_match: Boolean(artifactA) && Boolean(artifactB) && artifactA.sample_rate === artifactB.sample_rate,
    kind_match: Boolean(artifactA) && Boolean(artifactB) && artifactA.kind === artifactB.kind,
    both_synthetic: Boolean(artifactA && artifactA.is_synthetic) && Boolean(artifactB && artifactB.is_synthetic),
    note: "Metadata comparison only -- no acoustic similarity claim is made.",
  };
}

/** Versioned, named voice profiles (VL-D5 §8, §9). Mirrors
 * pipeline.voice_profile.VoiceProfileRegistry exactly: create() refuses
 * a duplicate name, every later change goes through createVersion(),
 * which always appends. Carries no speaker/accent/pronunciation/prosody
 * field -- see pipeline/voice_profile.py's module docstring for why. */
export class VoiceProfileStore extends EventTarget {
  constructor() {
    super();
    /** @type {Map<string, object[]>} */
    this._versions = new Map();
  }

  create(name, fields = {}) {
    if (this._versions.has(name)) {
      throw new Error(`voice profile ${name} already exists; use createVersion() to change it`);
    }
    const profile = {
      profile_id: `${name}-v1`,
      name,
      version: 1,
      state: VoiceProfileState.SYNTHETIC_PROFILE,
      style_controls: {},
      generation_preferences: {},
      notes: null,
      created_at: new Date().toISOString(),
      ...fields,
    };
    this._versions.set(name, [profile]);
    this._announce(profile);
    return profile;
  }

  createVersion(name, overrides = {}) {
    const versions = this._versions.get(name);
    if (!versions) throw new Error(`no voice profile named ${name}`);
    const base = versions[versions.length - 1];
    const nextVersion = base.version + 1;
    const profile = {
      ...base,
      ...overrides,
      profile_id: `${name}-v${nextVersion}`,
      name,
      version: nextVersion,
      created_at: new Date().toISOString(),
    };
    versions.push(profile);
    this._announce(profile);
    return profile;
  }

  latest(name) {
    const versions = this._versions.get(name);
    if (!versions) throw new Error(`no voice profile named ${name}`);
    return versions[versions.length - 1];
  }

  history(name) {
    return [...(this._versions.get(name) || [])];
  }

  names() {
    return [...this._versions.keys()];
  }

  allLatest() {
    return this.names().map((name) => this.latest(name));
  }

  _announce(profile) {
    this.dispatchEvent(new CustomEvent("change", { detail: { profile } }));
  }
}

/** Runtime-discoverable generation backends/models (VL-D5 §26, §27).
 * Mirrors pipeline.generation_models.GenerationModelRegistry -- an
 * in-memory registry, not a persisted audit log (that stays
 * registry/model_registry.py's separate concern; see the module
 * docstring on the Python side for why they're not the same thing).
 * `status` doubles as this model's GenerationBackendState -- honest
 * capability reporting, never a fabricated AVAILABLE. */
export class GenerationModelStore extends EventTarget {
  constructor() {
    super();
    /** @type {Map<string, object>} */
    this._models = new Map();
  }

  register(model) {
    this._models.set(model.model_id, model);
    this._announce(model);
    return model;
  }

  get(modelId) {
    return this._models.get(modelId) || null;
  }

  /** The GenerationCapabilities-shaped view of a registered model, for
   * validateGenerationRequest()/estimateGenerationRequirements(). */
  capabilitiesFor(modelId) {
    const model = this.get(modelId);
    if (!model) return { backend_state: GenerationBackendState.NOT_CONFIGURED, compute_backend: "cpu", supported_controls: [] };
    return {
      backend_state: model.status,
      compute_backend: model.backend,
      supported_controls: model.capabilities || [],
    };
  }

  list() {
    return [...this._models.values()];
  }

  listByBackend(backend) {
    return this.list().filter((m) => m.backend === backend);
  }

  _announce(model) {
    this.dispatchEvent(new CustomEvent("change", { detail: { model } }));
  }
}

let _itemCounter = 0;

/** Session-only generation queue (VL-D5 §13). See module docstring for
 * exactly what "generating" means here. One item's failure never stops
 * the rest of the queue, mirroring pipeline.generation.GenerationQueue's
 * one broad catch per item. */
export class GenerationQueueStore extends EventTarget {
  constructor({ modelStore }) {
    super();
    this._modelStore = modelStore;
    /** @type {object[]} */
    this._items = [];
  }

  enqueue(request) {
    _itemCounter += 1;
    const itemId = `gen-${String(_itemCounter - 1).padStart(4, "0")}-${request.request_id}`;
    const item = {
      item_id: itemId,
      request,
      status: GenerationStatus.QUEUED,
      progress: 0,
      current_operation: null,
      warnings: [],
      errors: [],
      artifact: null,
      generation_duration_seconds: null,
    };
    this._items.push(item);
    this._announce(item);
    return item;
  }

  cancel(itemId) {
    const item = this.get(itemId);
    if (item && item.status === GenerationStatus.QUEUED) {
      item.status = GenerationStatus.CANCELLED;
      this._announce(item);
    }
    return item;
  }

  retry(itemId) {
    const item = this.get(itemId);
    if (!item) return item;
    item.status = GenerationStatus.QUEUED;
    item.warnings = [];
    item.errors = [];
    item.artifact = null;
    this._announce(item);
    return this.processOne(itemId);
  }

  async processOne(itemId, { stepDelayMs = 120 } = {}) {
    const item = this.get(itemId);
    if (!item || item.status === GenerationStatus.CANCELLED) return item;

    const started = performance.now();
    const model = this._modelStore.get(item.request.model_id);
    const capabilities = this._modelStore.capabilitiesFor(item.request.model_id);
    try {
      item.status = GenerationStatus.PREPARING;
      item.current_operation = "validating request";
      this._announce(item);
      await delay(stepDelayMs);

      const errors = validateGenerationRequest(item.request, capabilities);
      if (errors.length) {
        item.status = GenerationStatus.BLOCKED;
        item.errors.push(...errors);
        return item;
      }

      item.status = GenerationStatus.GENERATING;
      item.current_operation = "generating audio";
      item.progress = 0.5;
      this._announce(item);
      await delay(stepDelayMs);

      item.status = GenerationStatus.POST_PROCESSING;
      item.current_operation = "finalizing artifact";
      item.progress = 0.9;
      this._announce(item);
      await delay(stepDelayMs);

      item.artifact = buildSyntheticArtifact(item.request, model);
      item.status = item.warnings.length ? GenerationStatus.WARNING : GenerationStatus.READY;
    } catch (err) {
      item.status = GenerationStatus.FAILED;
      item.errors.push(String((err && err.message) || err));
    } finally {
      item.current_operation = null;
      item.progress = 1;
      item.generation_duration_seconds = (performance.now() - started) / 1000;
      this._announce(item);
    }
    return item;
  }

  async processAll() {
    const results = [];
    for (const item of [...this._items]) {
      if (item.status === GenerationStatus.QUEUED) results.push(await this.processOne(item.item_id));
    }
    return results;
  }

  list() {
    return [...this._items];
  }

  get(itemId) {
    return this._items.find((i) => i.item_id === itemId) || null;
  }

  counts() {
    const counts = Object.fromEntries(Object.values(GenerationStatus).map((s) => [s, 0]));
    for (const item of this._items) counts[item.status] += 1;
    return counts;
  }

  _announce(item) {
    this.dispatchEvent(new CustomEvent("change", { detail: { item } }));
  }
}

let _historyCounter = 0;

/** Append-only preview generation history (VL-D5 §17-§20). Mirrors
 * pipeline.preview_history: regeneration never overwrites, it appends a
 * new record chained via `supersedes`, grouped by `voice_profile_id`
 * (the stable "lineage" a sequence of generations belongs to). */
export class PreviewHistoryStore extends EventTarget {
  constructor() {
    super();
    /** @type {object[]} */
    this._records = [];
  }

  record(item, { voiceProfileId }) {
    _historyCounter += 1;
    const artifact = item.artifact || {};
    const active = this.current(voiceProfileId);
    const record = {
      record_id: `preview-hist-${String(_historyCounter).padStart(5, "0")}`,
      voice_profile_id: voiceProfileId,
      request_id: item.request.request_id,
      output_id: artifact.preview_id || "",
      model_id: item.request.model_id,
      config_hash: item.request.config_hash,
      status: item.status,
      output_sha256: artifact.sha256 || null,
      tool_version: artifact.model_version || null,
      supersedes: active ? active.record_id : null,
      recorded_at: new Date().toISOString(),
    };
    this._records.push(record);
    this._announce(record);
    return record;
  }

  history(voiceProfileId) {
    return this._records.filter((r) => r.voice_profile_id === voiceProfileId);
  }

  current(voiceProfileId) {
    const records = this.history(voiceProfileId);
    return records.length ? records[records.length - 1] : null;
  }

  /** Every record after the first counts as a regeneration. */
  regenerationCount(voiceProfileId) {
    return Math.max(0, this.history(voiceProfileId).length - 1);
  }

  all() {
    return [...this._records];
  }

  _announce(record) {
    this.dispatchEvent(new CustomEvent("change", { detail: { record } }));
  }
}

let _feedbackCounter = 0;

/** Preview feedback persistence (VL-D5 §21, §22). A dedicated store --
 * not the generic FeedbackStore in state/review-model.js -- because
 * PreviewFeedback carries `listened` and its listened-before-decision
 * enforcement is specific to this record type, mirroring
 * pipeline.preview_feedback.record_preview_feedback() exactly, including
 * refusing an ACCEPTED/REJECTED outcome recorded without listening. */
export class PreviewFeedbackStore extends EventTarget {
  constructor() {
    super();
    /** @type {object[]} */
    this._records = [];
  }

  record({ preview_id: previewId, listener, outcome, listened, category = null, rating = null, comment = null }) {
    if (!listened && (outcome === PreviewFeedbackOutcome.ACCEPTED || outcome === PreviewFeedbackOutcome.REJECTED)) {
      throw new UnlistenedFeedbackError(
        `cannot record ${outcome} for ${previewId} — the preview must be listened to first`,
      );
    }
    if (category !== null && !Object.values(PreviewFeedbackCategory).includes(category)) {
      throw new Error(`unknown PreviewFeedbackCategory: ${category}`);
    }

    const attributes = {};
    if (category !== null) attributes.category = category;
    if (rating !== null) attributes.rating = String(rating);

    _feedbackCounter += 1;
    const record = {
      feedback_id: `preview-feedback-${String(_feedbackCounter).padStart(5, "0")}`,
      preview_id: previewId,
      listener,
      outcome,
      listened,
      listen_duration_seconds: null,
      comment: comment || null,
      attributes,
      requests_regeneration: outcome === PreviewFeedbackOutcome.REGENERATE,
      created_at: new Date().toISOString(),
    };
    this._records.push(record);
    this._announce(record);
    return record;
  }

  feedbackFor(previewId) {
    return this._records.filter((r) => r.preview_id === previewId);
  }

  countsByOutcome() {
    const counts = Object.fromEntries(Object.values(PreviewFeedbackOutcome).map((o) => [o, 0]));
    for (const record of this._records) counts[record.outcome] += 1;
    return counts;
  }

  countsByCategory() {
    const counts = {};
    for (const record of this._records) {
      const category = record.attributes && record.attributes.category;
      if (category) counts[category] = (counts[category] || 0) + 1;
    }
    return counts;
  }

  all() {
    return [...this._records];
  }

  _announce(record) {
    this.dispatchEvent(new CustomEvent("change", { detail: { record } }));
  }
}

export function exportGenerationPlan(queueStore, historyStore, feedbackStore) {
  return {
    is_synthetic: true,
    generated_by: "frontend client-side generation model (session-only, not authoritative)",
    generation_items: queueStore.list(),
    preview_history: historyStore.all(),
    preview_feedback: feedbackStore.all(),
  };
}
