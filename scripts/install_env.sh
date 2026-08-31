#!/usr/bin/env bash
#
# Build one isolated AARYA Voice Lab environment.
#
#   scripts/install_env.sh <base|env-nemo|env-whisperx|env-tts> [--cuda|--cpu]
#
# This script NEVER runs automatically and NEVER downloads model weights.
# It creates a venv under .envs/<name>, installs torch from the wheel
# index matching the requested accelerator, then installs the layered
# requirements file.
#
# It deliberately refuses env-whisperx without an explicit acknowledgement
# flag, because that environment carries a real, unresolved stop condition
# (a third-party account + a gated, contact-sharing-agreement model). See
# docs/COMPATIBILITY.md and docs/WHISPERX.md.
#
# env-tts's own former approval gate ("no TTS model has been selected")
# was retired once AI4Bharat IndicF5 was selected and verified end-to-end
# -- see docs/INDICF5_INSTALLER.md. env-tts still needs a HuggingFace
# token before the model itself can be downloaded (IndicF5's repository
# is gated), but that is a separate, later step this script does not
# perform -- this script only builds the venv and installs dependencies,
# and never downloads model weights for any environment.

set -euo pipefail

# On a fresh Windows machine, `python3` frequently resolves to a
# non-functional Windows Store "app execution alias" stub (prints
# "Python was not found; run without arguments to install from the
# Microsoft Store..." and exits non-zero) even when a real interpreter
# is installed and on PATH as plain `python` -- confirmed directly on
# this project's own reference machine. Detect a genuinely working
# interpreter rather than assuming `python3` is it.
if python3 --version >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif python --version >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "ERROR: no working Python interpreter found on PATH (tried python3, python)." >&2
    echo "Install Python 3.12 first (see docs/ENVIRONMENT.md)." >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${1:-}"
ACCEL="${2:---cpu}"
ACK="${3:-}"

usage() {
    cat <<'EOF'
Usage: scripts/install_env.sh <environment> [--cpu|--cuda] [--i-have-approval]

Environments:
  base           Core tooling only (no ML). Safe to build any time.
  env-nemo       NeMo / Sortformer diarization. No credentials needed.
  env-whisperx   WhisperX transcription. REQUIRES APPROVAL (gated deps).
  env-tts        AI4Bharat IndicF5 TTS. Approved and verified; the model
                 itself (gated on HuggingFace) is fetched separately.

Accelerator:
  --cpu          CPU-only wheels (default; works everywhere).
  --cuda         CUDA wheels. Only use if `aarya-voice env-audit` reports a GPU.
EOF
}

if [[ -z "$ENV_NAME" || "$ENV_NAME" == "-h" || "$ENV_NAME" == "--help" ]]; then
    usage
    exit 0
fi

case "$ENV_NAME" in
    base)         REQ="requirements/base.txt" ;;
    env-nemo)     REQ="requirements/diarization.txt" ;;
    env-whisperx) REQ="requirements/transcription.txt" ;;
    env-tts)      REQ="requirements/tts.txt" ;;
    *)
        echo "ERROR: unknown environment '$ENV_NAME'" >&2
        usage
        exit 2
        ;;
esac

# --- Stop conditions -------------------------------------------------------
if [[ "$ENV_NAME" == "env-whisperx" && "$ACK" != "--i-have-approval" ]]; then
    cat >&2 <<'EOF'
STOP: env-whisperx requires explicit approval before installation.

Installing whisperx transitively installs pyannote.audio AND pyannoteai-sdk
(a commercial API client). pyannote's diarization pipeline is a GATED
HuggingFace model: it requires an access token and acceptance of an
agreement that shares your contact information.

No credentials will be configured automatically.

If this has been approved, re-run with --i-have-approval as the 3rd argument.
See docs/WHISPERX.md.
EOF
    exit 3
fi

cd "$REPO_ROOT"
ENV_DIR=".envs/$ENV_NAME"

if [[ -d "$ENV_DIR" ]]; then
    echo "ERROR: $ENV_DIR already exists. Remove it deliberately before rebuilding." >&2
    exit 1
fi

echo "==> Creating virtualenv at $ENV_DIR (using $PYTHON_BIN)"
"$PYTHON_BIN" -m venv "$ENV_DIR"

# `venv` writes Scripts/python.exe on native Windows, bin/python on
# POSIX -- mirrors pipeline.runner.EnvironmentPaths.python's exact same
# fallback (Windows checked first) so this script and that module never
# disagree about where an environment's interpreter lives. This script
# previously hardcoded bin/python unconditionally, which is why it had
# never actually been run to completion on native Windows before.
if [[ -f "$ENV_DIR/Scripts/python.exe" ]]; then
    PY="$ENV_DIR/Scripts/python.exe"
else
    PY="$ENV_DIR/bin/python"
fi

echo "==> Upgrading pip"
"$PY" -m pip install --quiet --upgrade pip

# torch (and, for env-tts, torchaudio alongside it) must be installed
# FIRST from the correct index; otherwise pip resolves a default (often
# CUDA) build and silently pulls gigabytes of NVIDIA wheels onto a
# CPU-only machine. env-tts's pins are the EXACT combination verified
# end-to-end (real CUDA generation, human-confirmed intelligible speech
# -- see docs/INDICF5_INSTALLER.md), including cu126 rather than cu130
# (PyTorch 2.13's own default index) -- cu130 has never been tested
# against this model.
if [[ "$ENV_NAME" != "base" ]]; then
    case "$ENV_NAME:$ACCEL" in
        env-nemo:--cpu)      TORCH_SPEC="torch==2.13.0"; INDEX="https://download.pytorch.org/whl/cpu" ;;
        env-nemo:--cuda)     TORCH_SPEC="torch==2.13.0"; INDEX="https://download.pytorch.org/whl/cu130" ;;
        env-whisperx:--cpu)  TORCH_SPEC="torch==2.8.0";  INDEX="https://download.pytorch.org/whl/cpu" ;;
        env-whisperx:--cuda) TORCH_SPEC="torch==2.8.0";  INDEX="https://download.pytorch.org/whl/cu126" ;;
        env-tts:--cpu)       TORCH_SPEC="torch==2.13.0 torchaudio==2.11.0"; INDEX="https://download.pytorch.org/whl/cpu" ;;
        env-tts:--cuda)      TORCH_SPEC="torch==2.13.0 torchaudio==2.11.0"; INDEX="https://download.pytorch.org/whl/cu126" ;;
        *) echo "ERROR: unknown accelerator '$ACCEL'" >&2; exit 2 ;;
    esac
    echo "==> Installing $TORCH_SPEC from $INDEX"
    "$PY" -m pip install $TORCH_SPEC --index-url "$INDEX"
fi

echo "==> Installing $REQ"
"$PY" -m pip install -r "$REQ"

echo "==> Installing aarya_voice_lab (for the verification CLI)"
"$PY" -m pip install -e .

echo
echo "==> Built $ENV_DIR"
echo "Verify it with:"
case "$ENV_NAME" in
    env-nemo)     echo "  $PY -m aarya_voice_lab.cli.main nemo-check" ;;
    env-whisperx) echo "  $PY -m aarya_voice_lab.cli.main whisperx-check" ;;
    env-tts)      echo "  $PY -m aarya_voice_lab.cli.main tts-check" ;;
    *)            echo "  $PY -m aarya_voice_lab.cli.main env-audit" ;;
esac
echo
echo "NOTE: no model weights were downloaded by this script. Disable ML"
echo "telemetry with: source scripts/disable_telemetry.sh"
if [[ "$ENV_NAME" == "env-tts" ]]; then
    echo
    echo "IndicF5's checkpoint is GATED on HuggingFace -- fetching it requires"
    echo "an authenticated, access-approved account. See docs/INDICF5_INSTALLER.md"
    echo "for the credential flow. This environment already has the exact"
    echo "vendored (non-PyPI) IndicF5 runtime it needs at"
    echo "scripts/ml_workers/vendor/indicf5_f5tts/ -- do not pip install f5-tts."
fi
