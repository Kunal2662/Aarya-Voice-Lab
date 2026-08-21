// Real-browser (headless Chromium) tests for FE-1.1's shared
// <avl-confirm-action> dialog primitive: dialog semantics (role="dialog",
// aria-modal, labelledby/describedby), Escape-to-cancel, focus moving
// into the dialog on open and returning to the trigger on close, the Tab
// focus trap, backdrop-click cancel, and the recommended <avl-button>
// usage pattern. Mounted directly (not through app routing) since this
// is a standalone primitive, not tied to any one workspace -- its
// integration into workspace-settings.js is covered separately by the
// existing, untouched session.test.mjs #4/#5/#6.
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

async function withPage(fn) {
  const playwright = await loadPlaywright();
  const browser = await playwright.chromium.launch({ executablePath: CHROMIUM_EXECUTABLE, args: ["--no-sandbox"] });
  const server = createStaticServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => consoleErrors.push(String(err)));
    await page.goto(`http://127.0.0.1:${port}/app/index.html`, { waitUntil: "networkidle" });
    await fn(page);
    assert.deepEqual(consoleErrors, [], `unexpected console errors: ${JSON.stringify(consoleErrors)}`);
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

/** Mounts a fresh <avl-confirm-action> with two <avl-button> actions (the
 * primitive's own recommended usage pattern) plus a real trigger <button>
 * elsewhere on the page, and opens it. Returns nothing; state is read via
 * further page.evaluate calls in each test. */
async function mountAndOpen(page) {
  await page.evaluate(async () => {
    await import("/components/confirm-action.js");
    document.body.innerHTML = "";

    const trigger = document.createElement("button");
    trigger.id = "trigger";
    trigger.type = "button";
    trigger.textContent = "Open dialog";
    document.body.appendChild(trigger);

    const dialog = document.createElement("avl-confirm-action");
    dialog.id = "dialog";
    dialog.setAttribute("dialog-title", "Delete this thing?");
    dialog.setAttribute("description", "This cannot be undone.");
    dialog.setAttribute("variant", "danger");

    const cancel = document.createElement("avl-button");
    cancel.setAttribute("slot", "actions");
    cancel.setAttribute("variant", "secondary");
    cancel.textContent = "Cancel";
    const confirm = document.createElement("avl-button");
    confirm.setAttribute("slot", "actions");
    confirm.setAttribute("variant", "danger");
    confirm.textContent = "Delete";
    dialog.append(cancel, confirm);
    document.body.appendChild(dialog);

    window.__avlTestLog = [];
    dialog.addEventListener("avl-dialog-cancel", () => window.__avlTestLog.push("cancel-event"));

    trigger.focus();
    dialog.setAttribute("open", "");
  });
  await page.waitForTimeout(50);
}

test("1. dialog role/aria-modal/labelledby/describedby are present when open", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await mountAndOpen(page);
    const attrs = await page.evaluate(() => {
      // aria-labelledby/describedby IDREFs resolve within the same
      // shadow tree scope, not the main document -- look them up via
      // the dialog's own shadowRoot, not document.getElementById.
      const shadowRoot = document.getElementById("dialog").shadowRoot;
      const panel = shadowRoot.querySelector('[role="dialog"]');
      return {
        role: panel.getAttribute("role"),
        ariaModal: panel.getAttribute("aria-modal"),
        labelledby: !!panel.getAttribute("aria-labelledby"),
        describedby: !!panel.getAttribute("aria-describedby"),
        titleText: shadowRoot.getElementById(panel.getAttribute("aria-labelledby")).textContent,
        descText: shadowRoot.getElementById(panel.getAttribute("aria-describedby")).textContent,
      };
    });
    assert.equal(attrs.role, "dialog");
    assert.equal(attrs.ariaModal, "true");
    assert.equal(attrs.labelledby, true);
    assert.equal(attrs.describedby, true);
    assert.equal(attrs.titleText, "Delete this thing?");
    assert.equal(attrs.descText, "This cannot be undone.");
  });
});

test("2. closed dialog renders no dialog role at all (not just visually hidden)", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    const hasDialog = await page.evaluate(async () => {
      await import("/components/confirm-action.js");
      document.body.innerHTML = "";
      const dialog = document.createElement("avl-confirm-action");
      dialog.setAttribute("dialog-title", "Not open");
      document.body.appendChild(dialog);
      return !!dialog.shadowRoot.querySelector('[role="dialog"]');
    });
    assert.equal(hasDialog, false, "an unopened avl-confirm-action must not render dialog chrome at all");
  });
});

test("3. focus moves into the dialog panel when it opens", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await mountAndOpen(page);
    const focused = await page.evaluate(() => {
      const panel = document.getElementById("dialog").shadowRoot.querySelector(".panel");
      return document.activeElement.tagName === "AVL-CONFIRM-ACTION" && document.activeElement.shadowRoot.activeElement === panel;
    });
    assert.equal(focused, true, "focus must move to the dialog panel on open");
  });
});

test("4. Escape dispatches avl-dialog-cancel", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await mountAndOpen(page);
    await page.evaluate(() => {
      const panel = document.getElementById("dialog").shadowRoot.querySelector(".panel");
      panel.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, composed: true }));
    });
    await page.waitForTimeout(50);
    const log = await page.evaluate(() => window.__avlTestLog);
    assert.ok(log.includes("cancel-event"), "Escape must dispatch avl-dialog-cancel");
  });
});

test("5. focus returns to the triggering element once closed", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await mountAndOpen(page);
    await page.evaluate(() => {
      document.getElementById("dialog").removeAttribute("open");
    });
    await page.waitForTimeout(50);
    const focusedId = await page.evaluate(() => document.activeElement.id);
    assert.equal(focusedId, "trigger", "focus must return to the element that opened the dialog");
  });
});

test("6. Tab from the last action wraps to the first (focus trap)", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await mountAndOpen(page);
    const wrapped = await page.evaluate(() => {
      const dialog = document.getElementById("dialog");
      const actions = [...dialog.querySelectorAll('[slot="actions"]')];
      const last = actions[actions.length - 1];
      // <avl-button> hosts have no tabindex of their own -- the real
      // focus target is the native <button> inside their shadow root.
      const lastTarget = last.shadowRoot ? last.shadowRoot.querySelector("button") : last;
      lastTarget.focus();
      const event = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, composed: true, cancelable: true });
      lastTarget.dispatchEvent(event);
      // document.activeElement retargets to the outer host once shadow
      // encapsulation is crossed, so compare against the host here.
      return document.activeElement === actions[0];
    });
    assert.equal(wrapped, true, "Tab on the last action must wrap focus to the first");
  });
});

test("7. Shift+Tab from the first action wraps to the last (focus trap)", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await mountAndOpen(page);
    const wrapped = await page.evaluate(() => {
      const dialog = document.getElementById("dialog");
      const actions = [...dialog.querySelectorAll('[slot="actions"]')];
      const first = actions[0];
      const firstTarget = first.shadowRoot ? first.shadowRoot.querySelector("button") : first;
      firstTarget.focus();
      const event = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, composed: true, cancelable: true });
      firstTarget.dispatchEvent(event);
      return document.activeElement === actions[actions.length - 1];
    });
    assert.equal(wrapped, true, "Shift+Tab on the first action must wrap focus to the last");
  });
});

test("8. clicking the backdrop dispatches avl-dialog-cancel; clicking inside the panel does not", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await mountAndOpen(page);
    await page.evaluate(() => {
      const dialog = document.getElementById("dialog");
      dialog.shadowRoot.querySelector(".panel").click();
    });
    await page.waitForTimeout(30);
    const afterPanelClick = await page.evaluate(() => window.__avlTestLog.length);
    assert.equal(afterPanelClick, 0, "clicking inside the panel must not cancel the dialog");

    await page.evaluate(() => {
      const dialog = document.getElementById("dialog");
      dialog.shadowRoot.querySelector(".backdrop").click();
    });
    await page.waitForTimeout(30);
    const log = await page.evaluate(() => window.__avlTestLog);
    assert.ok(log.includes("cancel-event"), "clicking the backdrop must dispatch avl-dialog-cancel");
  });
});

test("9. the recommended avl-button actions are real, clickable buttons", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await mountAndOpen(page);
    const confirmed = await page.evaluate(() => {
      const dialog = document.getElementById("dialog");
      const confirmButton = [...dialog.querySelectorAll('avl-button[slot="actions"]')].find((b) => b.textContent === "Delete");
      let fired = false;
      confirmButton.addEventListener("click", () => {
        fired = true;
      });
      confirmButton.shadowRoot.querySelector("button").click();
      return fired;
    });
    assert.equal(confirmed, true, "clicking the internal <button> of a slotted avl-button action must fire its click listener");
  });
});

test("10. variant=\"danger\" applies the existing danger token, not a new color system", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await mountAndOpen(page);
    const styleText = await page.evaluate(() => document.getElementById("dialog").shadowRoot.querySelector("style").textContent);
    assert.match(styleText, /--avl-color-state-danger/, "danger variant must reuse the existing danger token, not a new palette");
    assert.doesNotMatch(styleText, /#[0-9a-fA-F]{3,8}\b/, "no raw hex color literal belongs in a token-driven component");
  });
});

test("11. non-danger (default) variant does not use the danger token for its border", { timeout: 30_000 }, async () => {
  await withPage(async (page) => {
    await page.evaluate(async () => {
      await import("/components/confirm-action.js");
      document.body.innerHTML = "";
      const dialog = document.createElement("avl-confirm-action");
      dialog.id = "dialog";
      dialog.setAttribute("dialog-title", "Neutral dialog");
      document.body.appendChild(dialog);
      dialog.setAttribute("open", "");
    });
    await page.waitForTimeout(50);
    const styleText = await page.evaluate(() => document.getElementById("dialog").shadowRoot.querySelector("style").textContent);
    // FE-3 -- the dialog panel is now the app's highest glass surface (see
    // css/base.css's .avl-glass--elevated), so its non-danger border uses
    // the glass border token rather than the plain default border.
    assert.match(styleText, /--avl-color-glass-border/);
    assert.doesNotMatch(styleText, /border:\s*1px solid var\(--avl-color-state-danger\)/, "non-danger variant must not use the danger border token");
  });
});
