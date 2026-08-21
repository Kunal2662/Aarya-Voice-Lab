// FE-1.7 -- the single source of truth for the visual regression
// harness's scenario list, imported by both the baseline CLI
// (tools/visual-baseline.mjs) and the regression test file
// (tests/visual-regression.test.mjs), so "what a baseline was captured
// from" and "what the test compares against" can never drift apart.
//
// Determinism: every scenario captures with
// `page.emulateMedia({ reducedMotion: "reduce" })` set *before*
// navigation. This isn't a workaround specific to this harness -- it
// activates the app's own existing, already-tested global
// prefers-reduced-motion contract (css/base.css: every
// --avl-duration-* token collapses to 1ms and `animation-iteration-
// count: 1 !important` stops any infinite loop), which is what makes
// the two infinite CSS animations in this codebase (pixel-sprite.js's
// pulse, workspace-state.js's loading spinner) settle into a fixed,
// repeatable end state instead of being captured at a
// wall-clock-dependent animation frame. Combined with the app's fully
// synthetic, hardcoded fixture data (no real "now()" timestamps
// rendered anywhere), this makes an exact byte-for-byte PNG comparison
// a valid, zero-dependency determinism strategy -- no fuzzy
// pixel-diff threshold, no external image-diff package needed.
//
// Coverage: all 15 routed workspaces in their real default/ready state
// (Calibration's own honest "No calibration run yet" default already
// doubles as the required empty-state demonstration), plus one each of
// dark theme, narrow desktop, a confirmation dialog open, Inspector
// open with a real selection, and a real BLOCKED processing status.
// Two required states -- a genuine mid-flight "loading" frame and a
// forced error/exception state -- are deliberately NOT included: both
// would need either a fabricated timing race (loading) or code changes
// to force a synthetic exception (error), and either risks exactly the
// kind of flaky/fabricated capture this harness exists to avoid. See
// docs/VLD0_DESIGN_SYSTEM.md's FE-1 section for this noted as a known,
// honest gap rather than papered over.

export const VIEWPORT_NORMAL = { width: 1440, height: 900 };
export const VIEWPORT_NARROW = { width: 1100, height: 900 };

async function goTo(page, destination) {
  await page.evaluate((d) => {
    location.hash = `#/${d}`;
  }, destination);
  await page.waitForTimeout(250);
}

export const SCENARIOS = [
  { name: "01-command-center", destination: "command-center" },
  { name: "02-import", destination: "import" },
  { name: "03-batches", destination: "batches" },
  { name: "04-recordings", destination: "recordings" },
  { name: "05-dataset-review", destination: "review" },
  { name: "06-processing", destination: "processing" },
  { name: "07-preview", destination: "preview" },
  { name: "08-pipeline", destination: "pipeline" },
  { name: "09-voices", destination: "voices" },
  { name: "10-models", destination: "models" },
  // Also the honest empty-state demonstration: no calibration run yet.
  { name: "11-calibration", destination: "calibration" },
  { name: "12-feedback", destination: "feedback" },
  { name: "13-claude", destination: "claude" },
  { name: "14-activity", destination: "activity" },
  { name: "15-settings", destination: "settings" },
  {
    name: "16-command-center-dark",
    destination: "command-center",
    viewport: VIEWPORT_NORMAL,
    setup: async (page) => {
      await page.evaluate(() => {
        const toggle = document.querySelector("avl-theme-toggle");
        toggle.shadowRoot.querySelector("button").click(); // system -> light
        toggle.shadowRoot.querySelector("button").click(); // light -> dark
      });
      await page.waitForTimeout(200);
    },
  },
  {
    name: "17-command-center-narrow",
    destination: "command-center",
    viewport: VIEWPORT_NARROW,
  },
  {
    name: "18-settings-confirm-dialog",
    destination: "settings",
    setup: async (page) => {
      await page.evaluate(() => {
        const settings = document.querySelector("avl-workspace-settings");
        const buttons = [...settings.shadowRoot.querySelectorAll("button")];
        buttons.find((b) => b.textContent.trim() === "Clear session data")?.click();
      });
      await page.waitForTimeout(150);
    },
  },
  {
    name: "19-batches-inspector-open",
    destination: "batches",
    setup: async (page) => {
      await page.evaluate(() => {
        const mount = document.querySelector('avl-app-shell [slot="workspace"]').firstElementChild;
        const card = mount.shadowRoot.querySelector("avl-batch-card");
        card.shadowRoot.querySelector("avl-card").click();
      });
      await page.waitForTimeout(150);
    },
  },
  {
    name: "20-processing-blocked",
    destination: "processing",
    setup: async (page) => {
      // Triggers processing-model.js's real async stage chain
      // (PREPARING -> PROCESSING -> QUALITY_CHECK -> final status,
      // ~450ms at its default stepDelayMs). A blind fixed-length wait
      // here raced that chain under load (observed one flake in 8 full
      // harness runs) -- polling for the actual BLOCKED badge to land
      // makes the capture wait exactly as long as needed, never more,
      // never less.
      await page.evaluate(async () => {
        const ws = document.querySelector("avl-workspace-processing");
        const rows = [...ws.shadowRoot.querySelectorAll("table tbody tr")];
        const blockedRow = rows.find((r) => r.textContent.includes("0003"));
        const button = [...blockedRow.querySelectorAll("avl-button")].find((b) => b.textContent.trim() === "Queue for processing");
        button.shadowRoot.querySelector("button").click();
        const deadline = performance.now() + 5000;
        while (performance.now() < deadline) {
          const badge = blockedRow.querySelector('avl-status-badge[state="BLOCKED"]');
          if (badge) break;
          await new Promise((r) => setTimeout(r, 25));
        }
      });
      await page.waitForTimeout(150);
    },
  },
];

/** Navigates to a scenario's destination and runs its setup, on an
 * already-created page (caller owns browser/page lifecycle and the
 * reduced-motion emulation). */
export async function applyScenario(page, scenario) {
  await goTo(page, scenario.destination);
  if (scenario.setup) await scenario.setup(page);
}
