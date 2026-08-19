#!/usr/bin/env bash
#
# Full verification sweep: capability audit, per-environment checks, tests,
# lint, and the Git safety scan.
#
#   scripts/verify_all.sh
#
# Read-only. Installs nothing, downloads nothing, contacts no network service.
# Environments that are not built are reported as such rather than failing the
# run — "not built yet" is a normal state in Phase 1.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FAILURES=0

section() {
    echo
    echo "════════════════════════════════════════════════════════════"
    echo "  $1"
    echo "════════════════════════════════════════════════════════════"
}

run_step() {
    local label="$1"; shift
    if "$@"; then
        echo "[PASS] $label"
    else
        echo "[FAIL] $label (exit $?)"
        FAILURES=$((FAILURES + 1))
    fi
}

section "Capability audit"
aarya-voice env-audit || true

section "Environment verification"
for env_name in nemo-check whisperx-check tts-check; do
    echo
    echo "--- aarya-voice $env_name ---"
    # Exit 3 means a stop condition was reported, which is expected in Phase 1.
    aarya-voice "$env_name" || true
done

section "Configuration & schemas"
run_step "validate-config" aarya-voice validate-config
for template in manifests/templates/*.json; do
    run_step "validate-manifest $(basename "$template")" aarya-voice validate-manifest "$template"
done

section "Git safety"
run_step "validate-environment" aarya-voice validate-environment

section "Tests"
run_step "pytest" python -m pytest -q

section "Lint"
run_step "ruff" ruff check .

section "Summary"
if [[ "$FAILURES" -eq 0 ]]; then
    echo "All verification steps passed."
    exit 0
fi
echo "$FAILURES verification step(s) failed."
exit 1
