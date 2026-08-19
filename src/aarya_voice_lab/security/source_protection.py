"""Static checks that private voice material can't accidentally reach Git.

These functions never open, read, or inspect audio content — they only
look at *paths* (extensions, directory names) and at what Git currently
has staged/tracked. Used by `aarya-voice validate-environment`, by the
test suite, and as a pre-commit sanity check (see docs/SECURITY.md).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
        ".aiff", ".aif", ".au", ".amr", ".3gp", ".webm", ".mp4", ".mov", ".mkv",
    }
)

MODEL_ARTIFACT_EXTENSIONS: frozenset[str] = frozenset(
    {".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".pb", ".h5", ".bin", ".npy", ".npz"}
)

SENSITIVE_NAME_FRAGMENTS: frozenset[str] = frozenset(
    {"secret", "credential", "password", "token", "api_key", "apikey"}
)

SUSPICIOUS_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        "recordings", "raw_audio", "processed_audio", "private_audio",
        "private_dataset", "private_datasets", "voice_samples", "generated_samples",
    }
)


@dataclass
class ProtectionViolation:
    path: str
    reason: str


@dataclass
class ProtectionScanResult:
    violations: list[ProtectionViolation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def __bool__(self) -> bool:
        return self.ok


def classify_path(path: Path) -> str | None:
    """Return a violation reason for `path`, or None if it looks safe."""
    name_lower = path.name.lower()
    suffix_lower = path.suffix.lower()

    if suffix_lower in AUDIO_EXTENSIONS:
        return f"audio file extension {suffix_lower!r}"
    if suffix_lower in MODEL_ARTIFACT_EXTENSIONS:
        return f"model/embedding artifact extension {suffix_lower!r}"
    if any(fragment in name_lower for fragment in SENSITIVE_NAME_FRAGMENTS):
        return "filename suggests a secret/credential"
    if any(part.lower() in SUSPICIOUS_DIRECTORY_NAMES for part in path.parts):
        return "path passes through a directory reserved for private audio material"
    return None


def scan_paths(paths: list[Path]) -> ProtectionScanResult:
    result = ProtectionScanResult()
    for path in paths:
        reason = classify_path(path)
        if reason:
            result.violations.append(ProtectionViolation(path=str(path), reason=reason))
    return result


def git_tracked_files(root: Path) -> list[Path]:
    """Return paths Git currently tracks or has staged, relative to `root`."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        staged = [line for line in result.stdout.splitlines() if line]

        result = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        tracked = [line for line in result.stdout.splitlines() if line]
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    seen = dict.fromkeys(staged + tracked)
    return [Path(p) for p in seen]


def scan_git_repo(root: Path) -> ProtectionScanResult:
    """Scan every file Git tracks or has staged in `root` for violations."""
    return scan_paths(git_tracked_files(root))
