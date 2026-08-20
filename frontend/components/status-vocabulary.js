// Runtime access to frontend/tokens/status.json — the single closed-set
// status vocabulary every domain (core/pipeline/voice/calibration/
// hardware) must render from. Components must never invent a label or
// color for a state outside this file.

let _cache = null;

export async function loadStatusVocabulary() {
  if (_cache) return _cache;
  const url = new URL("../tokens/status.json", import.meta.url);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`status vocabulary fetch failed: ${response.status}`);
  }
  _cache = await response.json();
  return _cache;
}

/** "not_started" -> "Not started", "UNCALIBRATED" -> "Uncalibrated". */
export function labelFor(state) {
  const words = String(state).toLowerCase().replace(/[_-]+/g, " ").trim();
  if (!words) return "";
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "state.success" -> "--avl-color-state-success" */
export function tokenPathToCssVar(tokenPath) {
  return `--avl-color-${tokenPath.split(".").join("-")}`;
}
