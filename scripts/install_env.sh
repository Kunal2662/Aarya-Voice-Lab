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
# It deliberately refuses env-whisperx and env-tts without an explicit
# acknowledgement flag, because those environments carry stop conditions
# (gated models / credentials / undecided model choice). See
# docs/COMPATIBILITY.md and docs/WHISPERX.md.

set -euo pipefail

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
  env-tts        TTS experimentation. REQUIRES a model decision first.

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

if [[ "$ENV_NAME" == "env-tts" && "$ACK" != "--i-have-approval" ]]; then
    cat >&2 <<'EOF'
STOP: no TTS model has been selected.

requirements/tts.txt intentionally installs nothing. Building this
environment before a model decision would install an arbitrary candidate.
Review docs/TTS_MODELS.md (`aarya-voice tts-candidates`) first.
EOF
    exit 3
fi

cd "$REPO_ROOT"
ENV_DIR=".envs/$ENV_NAME"

if [[ -d "$ENV_DIR" ]]; then
    echo "ERROR: $ENV_DIR already exists. Remove it deliberately before rebuilding." >&2
    exit 1
fi

echo "==> Creating virtualenv at $ENV_DIR"
python3 -m venv "$ENV_DIR"
PY="$ENV_DIR/bin/python"

echo "==> Upgrading pip"
"$PY" -m pip install --quiet --upgrade pip

# torch must be installed FIRST from the correct index; otherwise pip
# resolves a default (often CUDA) build and silently pulls gigabytes of
# NVIDIA wheels onto a CPU-only machine.
if [[ "$ENV_NAME" != "base" ]]; then
    case "$ENV_NAME:$ACCEL" in
        env-nemo:--cpu)      TORCH_SPEC="torch==2.13.0"; INDEX="https://download.pytorch.org/whl/cpu" ;;
        env-nemo:--cuda)     TORCH_SPEC="torch==2.13.0"; INDEX="https://download.pytorch.org/whl/cu130" ;;
        env-whisperx:--cpu)  TORCH_SPEC="torch==2.8.0";  INDEX="https://download.pytorch.org/whl/cpu" ;;
        env-whisperx:--cuda) TORCH_SPEC="torch==2.8.0";  INDEX="https://download.pytorch.org/whl/cu126" ;;
        env-tts:--cpu)       TORCH_SPEC="torch";         INDEX="https://download.pytorch.org/whl/cpu" ;;
        env-tts:--cuda)      TORCH_SPEC="torch";         INDEX="https://download.pytorch.org/whl/cu130" ;;
        *) echo "ERROR: unknown accelerator '$ACCEL'" >&2; exit 2 ;;
    esac
    echo "==> Installing $TORCH_SPEC from $INDEX"
    "$PY" -m pip install "$TORCH_SPEC" --index-url "$INDEX"
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
echo "NOTE: no model weights were downloaded. Fetch them explicitly in an"
echo "approved phase. Disable ML telemetry with: source scripts/disable_telemetry.sh"
