// VL-D2 client-side import engine.
//
// The browser has no execution transport to the backend (see
// state/command-executor.js — still true in VL-D2, see
// docs/VLD2_DATASET_WORKSPACE.md). It cannot write into `data/source/`,
// cannot see other batches, and cannot invoke
// `aarya_voice_lab.pipeline.import_intake`. What it CAN do for real,
// using only Web platform APIs (no dependency added):
//
//   * read a dropped/selected File's header bytes and classify its
//     container by content — the exact same signature table as
//     `audio/filetype.py`'s `_identify()`, ported faithfully so the two
//     never disagree about what a WAV or MP3 header looks like;
//   * compute a REAL SHA-256 over the file content via SubtleCrypto —
//     genuine content-addressed identity, not a placeholder;
//   * detect zero-byte files and within-queue duplicates;
//   * run the same closed state machine
//     (queued/scanning/hashing/validating/accepted/warning/invalid/
//     blocked/duplicate/failed/cancelled) the backend ImportQueue uses,
//     with the same per-item failure isolation.
//
// What it honestly can NOT do: write an accepted file into `source/`,
// detect a duplicate against a batch from a previous session, or create
// a persisted Batch record. `exportImportPlan()` produces a JSON summary
// shaped closely enough to `ImportQueue.to_manifest()` that an operator
// can hand it to `python -m aarya_voice_lab.cli.main import ...` (or
// just re-select the same files there) to actually commit the batch —
// the same "UI validates, CLI executes" bridge the Claude Command Center
// uses via NullCommandExecutor, not a fabricated write.
//
// Also honest: SubtleCrypto's digest() is one-shot over a full buffer,
// not incremental. For VL-D2's synthetic fixtures this is fine; a real
// large-file import would need either the File System Access API (a
// user-directory-picker permission grant, not drag/drop) or a real
// backend transport to stream-hash without holding the whole file in
// memory. That optimisation is not implemented here — see "Known
// limitations" in docs/VLD2_DATASET_WORKSPACE.md.

export const ImportItemStatus = Object.freeze({
  QUEUED: "queued",
  SCANNING: "scanning",
  HASHING: "hashing",
  VALIDATING: "validating",
  ACCEPTED: "accepted",
  WARNING: "warning",
  INVALID: "invalid",
  BLOCKED: "blocked",
  DUPLICATE: "duplicate",
  FAILED: "failed",
  CANCELLED: "cancelled",
});

const RETRYABLE_STATUSES = new Set([ImportItemStatus.FAILED, ImportItemStatus.INVALID, ImportItemStatus.BLOCKED]);

// VL-D9 -- items in one of these statuses are the only ones safe/useful
// to persist and restore. QUEUED/SCANNING/HASHING/VALIDATING items are
// mid-flight (an active _processOne() await chain over a live File
// object) and cannot be resumed after a reload regardless of storage
// design -- a browser File object cannot survive JSON serialization, so
// restoring an in-flight item would only freeze a spinner on screen
// forever. See ImportQueue.hydrate() below and
// docs/VLD9_SESSION_PERSISTENCE.md.
const TERMINAL_IMPORT_STATUSES = new Set([
  ImportItemStatus.ACCEPTED,
  ImportItemStatus.WARNING,
  ImportItemStatus.INVALID,
  ImportItemStatus.BLOCKED,
  ImportItemStatus.DUPLICATE,
  ImportItemStatus.FAILED,
  ImportItemStatus.CANCELLED,
]);

const HEADER_BYTES = 16;

// Ported 1:1 from audio/filetype.py's ContainerFormat + _identify(). Any
// change there must be mirrored here — frontend/tests/import-engine.test.mjs
// asserts the two agree on every fixture the Python suite uses.
function identifyContainer(header) {
  if (!header || header.length === 0) return "empty";
  const bytes = new Uint8Array(header);
  const ascii = (start, end) => String.fromCharCode(...bytes.slice(start, Math.min(end, bytes.length)));

  if (ascii(0, 4) === "RIFF" && ascii(8, 12) === "WAVE") return "wav";
  if (ascii(0, 4) === "fLaC") return "flac";
  if (ascii(0, 4) === "OggS") return "ogg";
  if (ascii(4, 8) === "ftyp") return "mp4";
  if (ascii(0, 4) === "FORM" && ["AIFF", "AIFC"].includes(ascii(8, 12))) return "aiff";
  if (ascii(0, 4) === "caff") return "caf";
  if (bytes.length >= 4 && bytes[0] === 0x1a && bytes[1] === 0x45 && bytes[2] === 0xdf && bytes[3] === 0xa3) return "matroska";
  if (ascii(0, 6) === "#!AMR\n") return "amr";
  if (ascii(0, 3) === "ID3") return "mp3";
  if (bytes.length >= 2 && bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0) return "mp3";
  return "unknown";
}

const SUPPORTED_CONTAINERS = new Set(["wav", "mp3", "flac", "ogg", "mp4", "aiff", "amr", "matroska", "caf"]);

const EXTENSION_MAP = {
  wav: [".wav", ".wave"],
  mp3: [".mp3"],
  flac: [".flac"],
  ogg: [".ogg", ".oga", ".opus"],
  mp4: [".mp4", ".m4a", ".aac", ".mov"],
  aiff: [".aiff", ".aif", ".aifc"],
  amr: [".amr"],
  matroska: [".mkv", ".webm"],
  caf: [".caf"],
};

function declaredExtension(filename) {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot).toLowerCase() : null;
}

export async function detectType(file) {
  const headerBuffer = await file.slice(0, HEADER_BYTES).arrayBuffer();
  const container = identifyContainer(headerBuffer);
  const extension = declaredExtension(file.name);
  const expected = EXTENSION_MAP[container] || [];
  const extensionMismatch = Boolean(
    extension && container !== "unknown" && container !== "empty" && !expected.includes(extension),
  );
  return { container, extensionMismatch, declaredExtension: extension };
}

export async function sha256Hex(file) {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** @typedef {{itemId:string,originalFilename:string,declaredExtension:string|null,sizeBytes:number|null,detectedContainer:string|null,sha256:string|null,contentId:string|null,status:string,warnings:string[],errors:string[],duplicateOf:string|null}} ImportEngineItem */

export class ImportQueue extends EventTarget {
  constructor({ batchId, source }) {
    super();
    this.batchId = batchId;
    this.source = source; // "local_files" | "local_folder"
    /** @type {Map<string, ImportEngineItem>} */
    this.items = new Map();
    this._files = new Map();
  }

  enqueue(file) {
    const itemId = `import-${String(this.items.size + 1).padStart(4, "0")}`;
    const item = {
      itemId,
      originalFilename: file.name,
      declaredExtension: declaredExtension(file.name),
      sizeBytes: null,
      detectedContainer: null,
      sha256: null,
      contentId: null,
      status: ImportItemStatus.QUEUED,
      warnings: [],
      errors: [],
      duplicateOf: null,
    };
    this.items.set(itemId, item);
    this._files.set(itemId, file);
    this._emit(item);
    return item;
  }

  cancel(itemId) {
    const item = this.items.get(itemId);
    if (!item || item.status !== ImportItemStatus.QUEUED) return false;
    item.status = ImportItemStatus.CANCELLED;
    this._emit(item);
    return true;
  }

  async retry(itemId) {
    const item = this.items.get(itemId);
    if (!item || !RETRYABLE_STATUSES.has(item.status)) return false;
    if (!this._files.has(itemId)) {
      // A restored item (see hydrate()) has no backing File -- a browser
      // File object cannot survive a page reload, so this is an honest
      // refusal, not a fabricated retry.
      item.errors.push("cannot retry a restored item — the original file is not available after a session reload");
      this._emit(item);
      return false;
    }
    item.status = ImportItemStatus.QUEUED;
    item.errors = [];
    item.warnings = [];
    item.duplicateOf = null;
    await this._processOne(itemId);
    return true;
  }

  async processAll() {
    for (const itemId of this.items.keys()) {
      const item = this.items.get(itemId);
      if (item.status === ImportItemStatus.QUEUED) {
        await this._processOne(itemId);
      }
    }
  }

  async _processOne(itemId) {
    const item = this.items.get(itemId);
    const file = this._files.get(itemId);
    try {
      item.status = ImportItemStatus.SCANNING;
      this._emit(item);
      item.sizeBytes = file.size;
      if (file.size === 0) {
        item.status = ImportItemStatus.BLOCKED;
        item.errors.push("zero-byte file");
        this._emit(item);
        return;
      }

      item.status = ImportItemStatus.HASHING;
      this._emit(item);
      const digest = await sha256Hex(file);
      item.sha256 = digest;
      item.contentId = `src-${digest.slice(0, 16)}`;

      item.status = ImportItemStatus.VALIDATING;
      this._emit(item);
      const detected = await detectType(file);
      item.detectedContainer = detected.container;
      if (detected.extensionMismatch) {
        item.warnings.push(
          `extension ${detected.declaredExtension} does not match detected container ${detected.container} — extension is display-only, never trusted for identity or routing`,
        );
      }

      if (detected.container === "unknown") {
        item.status = ImportItemStatus.INVALID;
        item.errors.push("content does not match a known audio container");
        this._emit(item);
        return;
      }
      if (!SUPPORTED_CONTAINERS.has(detected.container)) {
        item.status = ImportItemStatus.BLOCKED;
        item.errors.push(`container ${detected.container} is not supported`);
        this._emit(item);
        return;
      }

      const duplicateOf = [...this.items.values()].find(
        (other) => other.itemId !== itemId && other.sha256 === digest && other.contentId,
      );
      if (duplicateOf) {
        item.status = ImportItemStatus.DUPLICATE;
        item.duplicateOf = duplicateOf.contentId;
        this._emit(item);
        return;
      }

      item.status = item.warnings.length ? ImportItemStatus.WARNING : ImportItemStatus.ACCEPTED;
      this._emit(item);
    } catch (err) {
      item.status = ImportItemStatus.FAILED;
      item.errors.push(`${err.name || "Error"}: ${err.message || String(err)}`);
      this._emit(item);
    }
  }

  _emit(item) {
    this.dispatchEvent(new CustomEvent("change", { detail: { item } }));
  }

  list() {
    return [...this.items.values()];
  }

  counts() {
    const counts = Object.fromEntries(Object.values(ImportItemStatus).map((s) => [s, 0]));
    for (const item of this.items.values()) counts[item.status] += 1;
    return counts;
  }

  /** VL-D9 -- restores a previously exportImportPlan()'d payload as a
   * read-only validation summary: original_filename (a browser-exposed
   * basename only -- the File API never exposes a full local filesystem
   * path, so this is not the banned "arbitrary filesystem path"),
   * declared_extension, size_bytes, detected_container, sha256,
   * content_id, status, warnings, errors, duplicate_of. Only items in a
   * terminal status are restored (see TERMINAL_IMPORT_STATUSES above);
   * an item missing item_id or in a non-terminal status is dropped.
   * Restored items carry no backing File (`this._files` stays empty for
   * them), so retry()/processAll() correctly refuse to act on them
   * rather than throwing. Also restores batch_id/source when present, so
   * the restored queue still identifies which batch it summarizes.
   * Returns true only if at least one item was restored. */
  hydrate(plan) {
    if (!plan || !Array.isArray(plan.items)) return false;
    const restored = plan.items.filter(
      (raw) => raw && typeof raw.item_id === "string" && TERMINAL_IMPORT_STATUSES.has(raw.status),
    );
    if (!restored.length) return false;

    this.items.clear();
    this._files.clear();
    if (typeof plan.batch_id === "string") this.batchId = plan.batch_id;
    if (typeof plan.source === "string") this.source = plan.source;

    for (const raw of restored) {
      const item = {
        itemId: raw.item_id,
        originalFilename: typeof raw.original_filename === "string" ? raw.original_filename : null,
        declaredExtension: typeof raw.declared_extension === "string" ? raw.declared_extension : null,
        sizeBytes: typeof raw.size_bytes === "number" ? raw.size_bytes : null,
        detectedContainer: typeof raw.detected_container === "string" ? raw.detected_container : null,
        sha256: typeof raw.sha256 === "string" ? raw.sha256 : null,
        contentId: typeof raw.content_id === "string" ? raw.content_id : null,
        status: raw.status,
        warnings: Array.isArray(raw.warnings) ? [...raw.warnings] : [],
        errors: Array.isArray(raw.errors) ? [...raw.errors] : [],
        duplicateOf: typeof raw.duplicate_of === "string" ? raw.duplicate_of : null,
        restored: true,
      };
      this.items.set(item.itemId, item);
    }
    return true;
  }

  /** VL-D9 -- clears this queue in place (same object identity) and
   * announces a detail-less "change" so mounted UI re-renders
   * immediately. Backs the explicit "Clear session data" control -- never
   * called automatically. */
  reset() {
    this.items.clear();
    this._files.clear();
    this.dispatchEvent(new CustomEvent("change", { detail: {} }));
  }
}

/**
 * A client-side-validated import plan, shaped closely to
 * ImportQueue.to_manifest() on the backend, for an operator to hand to
 * the real CLI importer. Never claims a file was written anywhere — no
 * `stored_relative_path` field exists here, because this queue never
 * writes one.
 */
export function exportImportPlan(queue) {
  return {
    batch_id: queue.batchId,
    source: queue.source,
    is_synthetic: true,
    generated_by: "frontend client-side import engine (validation preview only, not authoritative)",
    items: queue.list().map((item) => ({
      item_id: item.itemId,
      original_filename: item.originalFilename,
      declared_extension: item.declaredExtension,
      size_bytes: item.sizeBytes,
      detected_container: item.detectedContainer,
      sha256: item.sha256,
      content_id: item.contentId,
      status: item.status,
      warnings: item.warnings,
      errors: item.errors,
      duplicate_of: item.duplicateOf,
    })),
    counts: queue.counts(),
  };
}
