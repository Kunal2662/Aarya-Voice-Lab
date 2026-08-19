# shellcheck shell=bash
#
# Disable third-party telemetry in the ML environments.
#
#   source scripts/disable_telemetry.sh
#
# WHY THIS EXISTS
# ---------------
# A dependency audit of `nemo-toolkit[asr]` (2026-08-19) showed it pulls in
# four separate reporting stacks:
#
#   wandb                              cloud experiment tracking
#   sentry-sdk                         remote crash reporting
#   nv-one-logger-training-telemetry   NVIDIA usage telemetry
#   opentelemetry-exporter-otlp-*      OTLP trace/metric exporters
#
# None of these is required to run diarization, and every one of them is a
# potential path for information to leave the machine. For a project whose
# defining rule is that private voice material never leaves local storage,
# leaving them at their defaults is not acceptable — even though they are
# unlikely to transmit audio itself, they can transmit file paths, hostnames,
# stack traces, and run metadata.
#
# The pipeline runner sets these same variables for every stage subprocess
# (see aarya_voice_lab/pipeline/runner.py TELEMETRY_OFF_ENV). This script is
# for interactive shells.
#
# This is defence in depth, not a guarantee: verify with network monitoring
# before processing private material.

export WANDB_MODE=offline
export WANDB_DISABLED=true
export SENTRY_DSN=""
export NEMO_TELEMETRY_OPT_OUT=1
export NVIDIA_ONE_LOGGER_DISABLED=1
export OTEL_SDK_DISABLED=true
export HF_HUB_DISABLE_TELEMETRY=1
export DO_NOT_TRACK=1

# Offline mode: make model hubs fail loudly instead of silently downloading.
# Unset these deliberately when an approved phase needs to fetch weights.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

echo "Telemetry disabled and HuggingFace hubs set to offline for this shell."
echo "Unset HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE to fetch weights in an approved phase."
