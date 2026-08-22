import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("variables.css is not stale relative to tokens/*.json", () => {
  assert.doesNotThrow(() => {
    execFileSync("node", [path.join(frontendRoot, "tools", "build-css-variables.mjs"), "--check"], {
      stdio: "pipe",
    });
  }, "run `node frontend/tools/build-css-variables.mjs` to regenerate");
});

test("light and dark themes define the same set of color token names", () => {
  const color = JSON.parse(readFileSync(path.join(frontendRoot, "tokens", "color.json"), "utf8"));

  function flattenKeys(obj, prefix = "") {
    let keys = [];
    for (const [k, v] of Object.entries(obj)) {
      const next = prefix ? `${prefix}.${k}` : k;
      if (v !== null && typeof v === "object" && !Array.isArray(v)) {
        keys = keys.concat(flattenKeys(v, next));
      } else {
        keys.push(next);
      }
    }
    return keys.sort();
  }

  const lightKeys = flattenKeys(color.themes.light);
  const darkKeys = flattenKeys(color.themes.dark);
  assert.deepEqual(lightKeys, darkKeys);
});

test("status.json calibration domain exactly matches CalibrationState export", () => {
  const status = JSON.parse(readFileSync(path.join(frontendRoot, "tokens", "status.json"), "utf8"));
  const generated = JSON.parse(
    readFileSync(path.join(frontendRoot, "contracts", "generated", "calibration_state.json"), "utf8"),
  );
  assert.deepEqual(status.domains.calibration.states, generated.values);
});

test("status.json hardware domain exactly matches CapabilityState export", () => {
  const status = JSON.parse(readFileSync(path.join(frontendRoot, "tokens", "status.json"), "utf8"));
  const generated = JSON.parse(
    readFileSync(path.join(frontendRoot, "contracts", "generated", "capability_state.json"), "utf8"),
  );
  assert.deepEqual(status.domains.hardware.states, generated.values);
});

// Hardening milestone -- closing the frontend-contract drift gap.
//
// contracts-drift.test.mjs already proves Python enum -> generated JSON
// fidelity for all 25 files in contracts/generated/. It does not prove
// generated JSON -> status.json, which is where components actually read
// their state vocabularies from (see frontend/tokens/status.json's own
// domains object) -- a change to a backend enum could silently diverge
// from what the UI renders even while contracts-drift.test.mjs stays
// green, because that test never looks at status.json at all.
//
// This block closes that gap for every status.json domain that is
// architecturally meant to mirror a generated contract 1:1 (DOMAIN_TO_CONTRACT
// below), while explicitly documenting -- rather than silently ignoring --
// the two other legitimate cases: domains with no backend contract at all
// (frontend-only vocabularies), and generated contracts that are
// deliberately not wired into status.json (their values are hardcoded ad
// hoc in specific component files instead; see docs/FE4_FINAL_COMPLETION.md
// and the hardening-milestone report for the full per-file list). Both
// lists are asserted exhaustive against what's actually on disk, so a
// newly added, un-triaged domain or contract file fails this test instead
// of silently falling through uncovered.

const DOMAIN_TO_CONTRACT = {
  // calibration and hardware already have their own dedicated tests above;
  // included here too so the exhaustiveness check below sees every
  // contract-backed domain in one place.
  calibration: { contract: "calibration_state.json" },
  hardware: { contract: "capability_state.json" },
  hardware_calibration: { contract: "calibration_run_state.json" },
  overlap_status: { contract: "overlap_status.json" },
  candidate_review: { contract: "candidate_review_decision.json" },
  processing_status: { contract: "processing_status.json" },
  processing_decision: { contract: "processing_decision.json" },
  noise_conditioning_mode: { contract: "noise_conditioning_mode.json" },
  generation_status: { contract: "generation_status.json" },
  voice_profile_state: { contract: "voice_profile_state.json" },
  generation_backend_state: { contract: "generation_backend_state.json" },
  evaluation_completion_state: { contract: "evaluation_completion_state.json" },
  // Real Voice Model Engine milestone.
  training_job_status: { contract: "training_job_status.json" },
  training_provider_state: { contract: "training_provider_state.json" },
  model_lifecycle: { contract: "model_lifecycle_state.json" },
  // quality_decision.json's backend enum (PASS/WARNING/REVIEW/FAIL) has no
  // "no assessment done yet" member -- NOT_ANALYZED is a real, deliberate
  // frontend-only sentinel (see state/quality-summary.js's QUALITY_RANK,
  // which also carries it) for a recording nothing has measured yet, not
  // an omission from the backend export.
  quality_decision: { contract: "quality_decision.json", extraFrontendOnlyStates: ["NOT_ANALYZED"] },
};

// status.json domains that are intentionally frontend-only vocabularies
// with no backend-generated contract to mirror: `core` and `activity_severity`
// are generic UI-chrome states never derived from a Python enum; `voice`
// is the input-widget's own idle/recording/playback vocabulary, not a
// pipeline domain; `pipeline_stage` collides in name only with
// contracts/generated/pipeline_stage.json, whose "stages" array is the
// list of pipeline STAGE IDENTITIES (e.g. "segmentation"), a completely
// different vocabulary from this domain's job-style run states (queued,
// running, ...) -- there is no generated run-state contract for it.
const FRONTEND_ONLY_DOMAINS = ["core", "voice", "activity_severity", "pipeline_stage"];

// contracts/generated/*.json files that are deliberately NOT wired into
// status.json: their values are hardcoded directly in the one or two
// component files that render them (e.g. command_risk in
// claude-task-status.js) rather than routed through the shared status
// vocabulary, because they aren't rendered as a generic status badge.
const CONTRACTS_NOT_IN_STATUS_JSON = [
  "ab_decision.json",
  "calibration_strategy.json",
  "candidate_review_reason.json",
  "command_risk.json",
  "compute_backend.json",
  "feedback_type.json",
  "pipeline_stage.json",
  "preview_feedback_category.json",
  "preview_feedback_outcome.json",
  "preview_kind.json",
  "processing_feedback_category.json",
  "voice_quality_dimension.json",
  // Real Voice Model Engine milestone -- a reason code (mirrors
  // candidate_review_reason.json's pattern above) and two artifact
  // metadata vocabularies never rendered as a generic status badge.
  "training_failure_reason.json",
  "model_artifact_format.json",
  "model_artifact_type.json",
];

test("every status.json domain backed by a generated contract exactly matches it (minus documented frontend-only sentinels)", () => {
  const status = JSON.parse(readFileSync(path.join(frontendRoot, "tokens", "status.json"), "utf8"));
  for (const [domainName, { contract, extraFrontendOnlyStates = [] }] of Object.entries(DOMAIN_TO_CONTRACT)) {
    assert.ok(status.domains[domainName], `status.json is missing the ${domainName} domain`);
    const generated = JSON.parse(readFileSync(path.join(frontendRoot, "contracts", "generated", contract), "utf8"));
    const rendered = status.domains[domainName].states.filter((s) => !extraFrontendOnlyStates.includes(s));
    assert.deepEqual(
      rendered,
      generated.values,
      `status.json domain "${domainName}" has drifted from contracts/generated/${contract} -- ` +
        `run scripts/export_frontend_contracts.py and update tokens/status.json to match`,
    );
    for (const extra of extraFrontendOnlyStates) {
      assert.ok(
        status.domains[domainName].states.includes(extra),
        `documented frontend-only sentinel "${extra}" is missing from status.json domain "${domainName}"`,
      );
    }
  }
});

test("every status.json domain is either contract-backed or a documented frontend-only vocabulary", () => {
  const status = JSON.parse(readFileSync(path.join(frontendRoot, "tokens", "status.json"), "utf8"));
  const covered = new Set([...Object.keys(DOMAIN_TO_CONTRACT), ...FRONTEND_ONLY_DOMAINS]);
  const actual = new Set(Object.keys(status.domains));
  assert.deepEqual(
    [...actual].sort(),
    [...covered].sort(),
    "a status.json domain was added or removed without updating DOMAIN_TO_CONTRACT or " +
      "FRONTEND_ONLY_DOMAINS in css-variables.test.mjs -- classify it explicitly",
  );
});

test("every generated contract is either wired into a status.json domain or a documented exception", () => {
  const onDisk = readdirSync(path.join(frontendRoot, "contracts", "generated")).filter((f) => f.endsWith(".json"));
  const wired = new Set(Object.values(DOMAIN_TO_CONTRACT).map((d) => d.contract));
  const documented = new Set(CONTRACTS_NOT_IN_STATUS_JSON);
  const accountedFor = new Set([...wired, ...documented]);
  assert.deepEqual(
    [...onDisk].sort(),
    [...accountedFor].sort(),
    "a contract file was added to or removed from contracts/generated/ without updating " +
      "DOMAIN_TO_CONTRACT or CONTRACTS_NOT_IN_STATUS_JSON in css-variables.test.mjs -- classify it explicitly",
  );
});

test("every status domain state has a color_token entry", () => {
  const status = JSON.parse(readFileSync(path.join(frontendRoot, "tokens", "status.json"), "utf8"));
  for (const [domainName, domain] of Object.entries(status.domains)) {
    for (const state of domain.states) {
      assert.ok(
        Object.prototype.hasOwnProperty.call(domain.color_token, state),
        `${domainName}.${state} missing a color_token mapping`,
      );
    }
  }
});
