# Build one isolated AARYA Voice Lab environment -- native Windows/PowerShell
# port of install_env.sh, for the Windows installer (installer/AaryaVoiceLab.iss),
# which cannot assume Git Bash is present on a fresh end-user machine.
#
#   scripts/install_env.ps1 -EnvName <base|env-nemo|env-whisperx|env-tts> [-Accel cpu|cuda] [-Approved]
#
# Mirrors install_env.sh's logic 1:1 -- same environment names, same
# requirements files, same torch index URLs, same version pins, same
# Scripts/python.exe convention. requirements/*.txt remain the single
# source of truth for what gets installed; this script does not
# duplicate that decision, only the shell it runs in. See
# docs/INDICF5_INSTALLER.md for why env-tts's own approval gate was
# retired and env-whisperx's was not.
#
# This script NEVER runs automatically and NEVER downloads model weights.

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("base", "env-nemo", "env-whisperx", "env-tts")]
    [string]$EnvName,

    [ValidateSet("cpu", "cuda")]
    [string]$Accel = "cpu",

    [switch]$Approved
)

# NOT "Stop": in Windows PowerShell 5.1, a native command's stderr output
# (e.g. pip's own retry-warning lines during a transient network hiccup --
# a normal, non-fatal, self-recovering event, confirmed live during Phase 8
# real-machine validation) is wrapped in a NativeCommandError and would
# abort the script here before pip's own retry logic even finishes,
# misreporting a successful retry as a hard failure. Every external command
# below already checks $LASTEXITCODE explicitly and throws on a REAL
# failure -- that is the sole source of truth for success/failure here,
# not stderr chatter.
$ErrorActionPreference = "Continue"

function Find-Python {
    # Prefer the py launcher's 3.12 (matches EnvironmentSpec.python_version
    # for env-nemo/env-whisperx/env-tts), then fall back to plain `python`
    # on PATH -- mirrors install_env.sh's python3-then-python fallback,
    # adapted for Windows where the `py` launcher is the more reliable
    # multi-version entry point.
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            & py -3.12 --version *> $null
            if ($LASTEXITCODE -eq 0) { return @("py", "-3.12") }
        } catch {}
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        try {
            & python --version *> $null
            if ($LASTEXITCODE -eq 0) { return @("python") }
        } catch {}
    }
    throw "No working Python interpreter found (tried 'py -3.12', 'python'). Install Python 3.12 first -- see docs/ENVIRONMENT.md."
}

$RepoRoot = Split-Path -Parent $PSScriptRoot

switch ($EnvName) {
    "base"         { $Req = "requirements/base.txt" }
    "env-nemo"     { $Req = "requirements/diarization.txt" }
    "env-whisperx" { $Req = "requirements/transcription.txt" }
    "env-tts"      { $Req = "requirements/tts.txt" }
}

if ($EnvName -eq "env-whisperx" -and -not $Approved) {
    Write-Error @"
STOP: env-whisperx requires explicit approval before installation.

Installing whisperx transitively installs pyannote.audio AND pyannoteai-sdk
(a commercial API client). pyannote's diarization pipeline is a GATED
HuggingFace model: it requires an access token and acceptance of an
agreement that shares your contact information.

No credentials will be configured automatically.

If this has been approved, re-run with -Approved. See docs/WHISPERX.md.
"@
    exit 3
}

Set-Location $RepoRoot
$EnvDir = ".envs/$EnvName"

if (Test-Path $EnvDir) {
    Write-Error "$EnvDir already exists. Remove it deliberately before rebuilding."
    exit 1
}

$PythonCmd = Find-Python
Write-Host "==> Creating virtualenv at $EnvDir (using $($PythonCmd -join ' '))"
& $PythonCmd[0] $PythonCmd[1..($PythonCmd.Length - 1)] -m venv $EnvDir
if ($LASTEXITCODE -ne 0) { throw "venv creation failed (exit $LASTEXITCODE)" }

# venv always writes Scripts/python.exe on native Windows -- no bin/python
# fallback needed here (unlike install_env.sh, which must also support
# POSIX), but the path is still resolved explicitly rather than assumed,
# matching pipeline.runner.EnvironmentPaths.python's own convention.
$Py = Join-Path $EnvDir "Scripts\python.exe"
if (-not (Test-Path $Py)) {
    throw "venv created but $Py is missing -- unexpected venv layout"
}

Write-Host "==> Upgrading pip"
& $Py -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed (exit $LASTEXITCODE)" }

# torch (and, for env-tts, torchaudio alongside it) must be installed
# FIRST from the correct index -- see install_env.sh's identical comment
# for why. env-tts's pins are the exact combination verified end-to-end
# (real CUDA generation, human-confirmed intelligible speech).
if ($EnvName -ne "base") {
    $Key = "${EnvName}:${Accel}"
    switch ($Key) {
        "env-nemo:cpu"      { $TorchSpec = @("torch==2.13.0");                    $Index = "https://download.pytorch.org/whl/cpu" }
        "env-nemo:cuda"     { $TorchSpec = @("torch==2.13.0");                    $Index = "https://download.pytorch.org/whl/cu130" }
        "env-whisperx:cpu"  { $TorchSpec = @("torch==2.8.0");                     $Index = "https://download.pytorch.org/whl/cpu" }
        "env-whisperx:cuda" { $TorchSpec = @("torch==2.8.0");                     $Index = "https://download.pytorch.org/whl/cu126" }
        "env-tts:cpu"       { $TorchSpec = @("torch==2.13.0", "torchaudio==2.11.0"); $Index = "https://download.pytorch.org/whl/cpu" }
        "env-tts:cuda"      { $TorchSpec = @("torch==2.13.0", "torchaudio==2.11.0"); $Index = "https://download.pytorch.org/whl/cu126" }
        default             { throw "unknown environment/accelerator combination: $Key" }
    }
    Write-Host "==> Installing $($TorchSpec -join ' ') from $Index"
    & $Py -m pip install @TorchSpec --index-url $Index
    if ($LASTEXITCODE -ne 0) { throw "torch install failed (exit $LASTEXITCODE)" }
}

Write-Host "==> Installing $Req"
& $Py -m pip install -r $Req
if ($LASTEXITCODE -ne 0) { throw "dependency install failed (exit $LASTEXITCODE)" }

Write-Host "==> Installing aarya_voice_lab (for the verification CLI)"
& $Py -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "editable install failed (exit $LASTEXITCODE)" }

Write-Host ""
Write-Host "==> Built $EnvDir"
Write-Host "NOTE: no model weights were downloaded by this script."
if ($EnvName -eq "env-tts") {
    Write-Host ""
    Write-Host "IndicF5's checkpoint is GATED on HuggingFace -- fetching it requires"
    Write-Host "an authenticated, access-approved account. See docs/INDICF5_INSTALLER.md"
    Write-Host "for the credential flow. This environment already has the exact"
    Write-Host "vendored (non-PyPI) IndicF5 runtime it needs at"
    Write-Host "scripts/ml_workers/vendor/indicf5_f5tts/ -- do not pip install f5-tts."
}
