"""Project path resolution and the canonical list of protected directories.

This module has no knowledge of any real recording or dataset content — it
only knows directory *locations* and which of them are designated as
privacy-sensitive, for use by security.source_protection and tests.
"""

from __future__ import annotations

from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    """Walk upward from `start` (default: this file) to find the repo root.

    The root is identified by the presence of a `pyproject.toml` file.
    Falls back to the current working directory if no marker is found.
    """
    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd()


PROJECT_ROOT = find_project_root()

# Directories that may (in later phases) contain private voice material,
# derived artifacts, or run outputs. These are exactly the directories
# carved out in the root .gitignore. Kept here as a single source of
# truth so tooling and tests can verify the two stay in sync.
PROTECTED_DIRECTORIES: tuple[str, ...] = (
    "source",
    "datasets",
    "models",
    "experiments",
    "benchmarks",
    "reports",
    "logs",
    "manifests",
)

# Within a protected directory, these relative paths are documentation/
# schema scaffolding and are intentionally exempt from the "must be
# git-ignored" rule.
PROTECTED_DIRECTORY_ALLOWED_FILES: tuple[str, ...] = (
    "README.md",
    "templates",
)


def protected_paths(root: Path | None = None) -> tuple[Path, ...]:
    base = root or PROJECT_ROOT
    return tuple(base / name for name in PROTECTED_DIRECTORIES)
