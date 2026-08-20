// Real-browser smoke test: serves frontend/ over HTTP and loads
// shell/index.html in headless Chromium (already installed in this
// environment; see /opt/pw-browsers). Verifies the shell actually
// upgrades, renders through the generated backend contracts, and throws
// no console errors — not just that the JS parses.
import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { createStaticServer } from "../tools/serve.mjs";

const PLAYWRIGHT_INDEX = "/opt/node22/lib/node_modules/playwright/index.js";
const CHROMIUM_EXECUTABLE = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

async function loadPlaywright() {
  const mod = await import(pathToFileURL(PLAYWRIGHT_INDEX).href);
  return mod.default;
}

async function withServer(fn) {
  const server = createStaticServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    await fn(`http://127.0.0.1:${port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test("shell/index.html upgrades every custom element with no console errors", { timeout: 60_000 }, async () => {
  const playwright = await loadPlaywright();
  const browser = await playwright.chromium.launch({
    executablePath: CHROMIUM_EXECUTABLE,
    args: ["--no-sandbox"],
  });
  try {
    await withServer(async (baseUrl) => {
      const page = await browser.newPage();
      const consoleErrors = [];
      page.on("console", (msg) => {
        if (msg.type() === "error") consoleErrors.push(msg.text());
      });
      page.on("pageerror", (err) => consoleErrors.push(String(err)));

      await page.goto(`${baseUrl}/shell/index.html`, { waitUntil: "networkidle" });

      // Every custom element the page references must have upgraded —
      // an un-upgraded element means its module failed to load/register.
      const tagNames = [
        "avl-app-shell",
        "avl-sidebar-nav",
        "avl-activity-bar",
        "avl-panel",
        "avl-tabs",
        "avl-theme-toggle",
        "avl-pipeline-stage-track",
        "avl-voice-preview-card",
        "avl-voice-feedback",
        "avl-voice-version",
        "avl-voice-comparison",
        "avl-calibration-panel",
        "avl-hardware-profile-card",
        "avl-accent-panel",
        "avl-claude-command-shell",
        "avl-pixel-sprite",
        "avl-error-panel",
        "avl-notice-banner",
      ];
      const upgraded = await page.evaluate(
        (tags) => tags.map((tag) => [tag, !!customElements.get(tag)]),
        tagNames,
      );
      for (const [tag, isUpgraded] of upgraded) {
        assert.ok(isUpgraded, `${tag} did not register as a custom element`);
      }

      // Pipeline track rendered one node per generated stage.
      const stageCount = await page.evaluate(() => {
        const track = document.querySelector("avl-pipeline-stage-track");
        return track.shadowRoot.querySelectorAll("avl-pipeline-stage-node").length;
      });
      assert.ok(stageCount > 0, "pipeline stage track rendered no stages");

      // Calibration panel must show the honest UNCALIBRATED default, never
      // a fabricated score, when no record has been supplied. Shadow DOM
      // encapsulates text, so collect it recursively across nested
      // shadow roots (avl-status-badge lives inside avl-calibration-panel).
      const calibrationText = await page.evaluate(() => {
        function collectText(root) {
          let text = "";
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
          let node = walker.currentNode;
          do {
            if (node.nodeType === Node.TEXT_NODE) text += node.textContent;
            if (node.shadowRoot) text += collectText(node.shadowRoot);
          } while ((node = walker.nextNode()));
          return text;
        }
        const panel = document.querySelector("avl-calibration-panel");
        return collectText(panel.shadowRoot);
      });
      assert.match(calibrationText, /Uncalibrated/i);
      assert.doesNotMatch(calibrationText, /CALIBRATED\b(?!.*Uncalibrated)/);

      // Pixel sprites are decorative: aria-hidden and not the page's only
      // status signal (a real status-bearing element also exists).
      const spriteAriaHidden = await page.evaluate(() =>
        Array.from(document.querySelectorAll("avl-pixel-sprite")).every(
          (el) => el.getAttribute("aria-hidden") === "true",
        ),
      );
      assert.ok(spriteAriaHidden, "a pixel sprite is missing aria-hidden");

      assert.deepEqual(consoleErrors, [], `console errors: ${consoleErrors.join("; ")}`);

      await page.close();
    });
  } finally {
    await browser.close();
  }
});
