# Aarya Voice Lab — Frontend

`app/index.html` is the real, routable application (all 15 workspaces,
VL-D1 through VL-D10); `shell/index.html` remains the original VL-D0
layout wireframe, kept for its own test coverage rather than as the
app entry point. See `docs/VLD0_DESIGN_SYSTEM.md` at the repo root for
the design-system rationale and `docs/FE1_FRONTEND_POLISH.md` for the
FE-1 frontend polish pass (responsive shell, icon system, shared CSS
utilities, visual regression harness, accessibility audit); this file
just covers how to run things.

## Why zero dependencies

This repo's hard invariant is local-first / no cloud dependency. The
frontend honours the same spirit at the tooling level: no framework, no
bundler, no `npm install` against a registry. Everything here runs with
plain `node` (22+) and, for the one real-browser test, the Chromium this
environment already has installed. See "Why no framework" in
`docs/VLD0_DESIGN_SYSTEM.md` for the full reasoning.

## Layout

```
frontend/
  tokens/       JSON source of truth: color, typography, spacing, motion, status
  tools/        build-css-variables.mjs (tokens -> css/variables.css), serve.mjs (test-only static server),
                visual-baseline.mjs (visual regression baseline CLI, see FE1_FRONTEND_POLISH.md)
  css/          generated variables.css + hand-written reset.css / base.css
  components/   vanilla Web Components (Shadow DOM, no framework)
  contracts/    generated/ (exported from backend enums) + claude-context-model.json (interface only)
  state/        client-side stores: job/activity/selection models, per-workspace state, session persistence
  app/          index.html + main.js — the real, routable application
  shell/        index.html — the original VL-D0 layout wireframe (not the app entry point)
  tests/        node:test files, one Playwright browser smoke test, visual-baselines/*.png (committed)
```

## Commands

```sh
node tools/build-css-variables.mjs          # regenerate css/variables.css from tokens/*.json
node tools/build-css-variables.mjs --check  # verify it's not stale (used by tests/css-variables.test.mjs)
node tools/serve.mjs                 # serve frontend/ at http://127.0.0.1:4310/ (manual viewing)
node --test tests/*.test.mjs         # run all frontend tests
node tools/visual-baseline.mjs               # compare the app against committed visual-regression baselines
node tools/visual-baseline.mjs --update      # (re)write those baselines from the current app
```

Backend contract exports live in `contracts/generated/` and are produced
by `python scripts/export_frontend_contracts.py` at the repo root (not a
frontend/ tool, since it imports the Python package).
