# Aarya Voice Lab — Frontend (VL-D0)

The design-system foundation only. **Not the application.** See
`docs/VLD0_DESIGN_SYSTEM.md` at the repo root for the full design
rationale; this file just covers how to run things.

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
  tools/        build-css-variables.mjs (tokens -> css/variables.css), serve.mjs (test-only static server)
  css/          generated variables.css + hand-written reset.css / base.css
  components/   vanilla Web Components (Shadow DOM, no framework)
  contracts/    generated/ (exported from backend enums) + claude-context-model.json (interface only)
  shell/        index.html — the VL-D0 layout wireframe
  tests/        node:test files + one Playwright browser smoke test
```

## Commands

```sh
node tools/build-css-variables.mjs          # regenerate css/variables.css from tokens/*.json
node tools/build-css-variables.mjs --check  # verify it's not stale (used by tests/css-variables.test.mjs)
node tools/serve.mjs                 # serve frontend/ at http://127.0.0.1:4310/ (manual viewing)
node --test tests/*.test.mjs         # run all frontend tests
```

Backend contract exports live in `contracts/generated/` and are produced
by `python scripts/export_frontend_contracts.py` at the repo root (not a
frontend/ tool, since it imports the Python package).
