"""Voice Lab's local model manager -- Task 2 of the Phase 4 autonomous
execution plan.

This is Voice Lab's own local model-artifact lifecycle tool: install,
remove, verify, and check the status of model artifacts in this
project's own `ArtifactStore`/`ModelRegistry`. It is **not** AARYA
Core's Voice Package Manager -- Core's own importer/installer is a
separate system this repository does not implement (see
docs/VOICE_PACKAGE_SPEC.md and ARCHITECTURE.md's scope boundaries).

Models are never downloaded by this module. "Install" means: take an
already-present local `.arya-voice` package (a directory containing
`manifest.json` plus a model file, or a zip-format archive of the same)
-- how it got onto disk is outside this module's concern -- verify its
manifest, checksum, and package-entry allowlist, check it against this
machine's known providers/formats, and only then register it in the
local artifact store and model registry. A package that fails any check
is refused; nothing is installed partially.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aarya_voice_lab.core.data_root import DataRoot
from aarya_voice_lab.pipeline.model_artifact import (
    ArtifactIntegrityError,
    ArtifactStore,
    ModelArtifact,
    ModelArtifactFormat,
    ModelArtifactType,
)
from aarya_voice_lab.pipeline.model_lifecycle import ModelLifecycleState
from aarya_voice_lab.pipeline.voice_package import check_entry_sizes, validate_package_entries
from aarya_voice_lab.registry.model_registry import ModelRegistry
from aarya_voice_lab.schemas.base import SchemaName, ValidationError, validate
from aarya_voice_lab.schemas.records import build_model_registry_entry

#: Providers this Voice Lab checkout actually knows how to run something
#: against. Deliberately small and explicit -- "compatible" is a real
#: claim about what this machine can do, never inferred from a package
#: merely naming a provider. A caller may widen this via
#: `ModelManager.install_from_directory(..., known_providers=...)`.
DEFAULT_KNOWN_PROVIDERS: frozenset[str] = frozenset({"local", "nvidia-nemo"})

#: model_format values this ArtifactStore can actually store -- matches
#: ModelArtifactFormat exactly, so "runtime compatibility" is a real
#: check against this project's own storage layer, not a duplicate of
#: the manifest schema's own enum validation.
_SUPPORTED_MODEL_FORMATS: frozenset[str] = frozenset(f.value for f in ModelArtifactFormat)


class ModelManagerError(RuntimeError):
    """Raised when a package cannot be installed, verified, or found."""


@dataclass(frozen=True)
class CompatibilityReport:
    compatible: bool
    problems: tuple[str, ...]


@dataclass(frozen=True)
class ModelStatus:
    model_name: str
    version: str
    lifecycle_state: str
    artifact_id: str | None
    artifact_present: bool
    checksum_valid: bool | None  # None when artifact_present is False


def check_compatibility(
    manifest: dict[str, Any], *, known_providers: frozenset[str] = DEFAULT_KNOWN_PROVIDERS
) -> CompatibilityReport:
    """Runtime and provider compatibility, as two distinct, named checks."""
    problems: list[str] = []
    model_format = manifest.get("model_format")
    if model_format not in _SUPPORTED_MODEL_FORMATS:
        problems.append(f"runtime incompatible: model_format {model_format!r} is not one this store can hold")
    provider = manifest.get("provider")
    if provider not in known_providers:
        problems.append(
            f"provider incompatible: {provider!r} is not in the known-providers set {sorted(known_providers)}"
        )
    return CompatibilityReport(compatible=not problems, problems=tuple(problems))


def _read_manifest(package_dir: Path) -> dict[str, Any]:
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ModelManagerError(f"no manifest.json found in {package_dir}")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ModelManagerError(f"manifest.json in {package_dir} is not valid JSON: {exc}") from exc


def _locate_model_file(package_dir: Path, manifest: dict[str, Any]) -> Path:
    model_format = manifest.get("model_format", "")
    extension_by_format = {
        "onnx": ".onnx",
        "safetensors": ".safetensors",
        "pytorch_state_dict": ".pt",
        "nemo_checkpoint": ".nemo",
        "raw_audio_wav": ".wav",
        "json_metadata": ".json",
    }
    suffix = extension_by_format.get(model_format)
    candidates = [
        p
        for p in package_dir.iterdir()
        if p.name != "manifest.json" and (suffix is None or p.suffix == suffix)
    ]
    if not candidates:
        raise ModelManagerError(f"no model file with extension {suffix!r} found in {package_dir}")
    if len(candidates) > 1:
        raise ModelManagerError(f"ambiguous package: multiple candidate model files in {package_dir}: {candidates}")
    return candidates[0]


class ModelManager:
    def __init__(self, data_root: DataRoot, *, model_registry: ModelRegistry | None = None):
        self.data_root = data_root
        self.artifact_store = ArtifactStore(data_root)
        self.model_registry = model_registry or ModelRegistry()

    def install_from_directory(
        self,
        package_dir: Path,
        *,
        known_providers: frozenset[str] = DEFAULT_KNOWN_PROVIDERS,
    ) -> ModelArtifact:
        """Install a package whose contents are already extracted onto
        disk. Every check below runs before anything is written; a
        failure at any step installs nothing."""
        manifest = _read_manifest(package_dir)

        # 1. verify manifest -- real schema validation, not a shape guess.
        try:
            validate(manifest, SchemaName.VOICE_PACKAGE_MANIFEST)
        except ValidationError as exc:
            raise ModelManagerError(f"manifest failed schema validation: {exc}") from exc

        # 2. package-entry allowlist -- reuses Task 6's contract exactly.
        entry_problems = validate_package_entries([p.name for p in package_dir.iterdir()])
        if entry_problems:
            raise ModelManagerError(f"package contains disallowed entries: {entry_problems}")

        # 3. runtime + provider compatibility.
        compatibility = check_compatibility(manifest, known_providers=known_providers)
        if not compatibility.compatible:
            raise ModelManagerError(f"incompatible package: {list(compatibility.problems)}")

        # 4. verify checksum -- recompute from the real bytes, compare to
        #    what the manifest declares. A mismatch means corruption or
        #    tampering and must refuse, never warn-and-continue.
        model_file = _locate_model_file(package_dir, manifest)
        payload = model_file.read_bytes()
        actual_checksum = hashlib.sha256(payload).hexdigest()
        declared_checksum = manifest["integrity"]["checksum_sha256"]
        if actual_checksum != declared_checksum:
            raise ModelManagerError(
                f"checksum mismatch for {model_file.name}: manifest declares {declared_checksum}, "
                f"actual is {actual_checksum} -- refusing to install"
            )

        # 5. install: ArtifactStore also independently recomputes and
        #    dedupes by checksum -- this is not redundant with step 4,
        #    which checked the *manifest's claim*; this checks storage
        #    identity.
        artifact = self.artifact_store.save(
            payload,
            artifact_format=ModelArtifactFormat(manifest["model_format"]),
            artifact_type=ModelArtifactType.GENERATION_MODEL_WEIGHTS,
            model_name=manifest["voice_id"],
            model_version=manifest["version"],
            provider_name=manifest["provider"],
            lifecycle_state=ModelLifecycleState.AVAILABLE,
        )
        self.model_registry.add(
            build_model_registry_entry(
                model_name=manifest["voice_id"],
                version=manifest["version"],
                provider=manifest["provider"],
                model_type=manifest["type"],
                status="approved",
                language_capability=manifest.get("languages", []),
                license=manifest.get("license"),
                architecture=manifest.get("model_format"),
                lifecycle_state=ModelLifecycleState.AVAILABLE.value,
                artifact_checksum=artifact.checksum_sha256,
            )
        )
        return artifact

    def install_from_archive(
        self,
        archive_path: Path,
        *,
        extract_to: Path,
        known_providers: frozenset[str] = DEFAULT_KNOWN_PROVIDERS,
    ) -> ModelArtifact:
        """Install from a zip-format `.arya-voice` archive. Entries are
        validated against the allowlist and a declared-size limit
        *before* extraction -- the size check closes a zip-bomb vector
        (extractall() decompresses proportional to the attacker-declared
        size, not the file's real size on disk) -- and `zipfile`'s own
        path-traversal protection (Python 3.6+) is relied on for the
        extraction itself, belt and suspenders, not a replacement for
        the allowlist check."""
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            entry_problems = validate_package_entries(names)
            if entry_problems:
                raise ModelManagerError(f"archive {archive_path} contains disallowed entries: {entry_problems}")
            size_problems = check_entry_sizes(archive)
            if size_problems:
                raise ModelManagerError(f"archive {archive_path} failed size checks: {size_problems}")
            extract_to.mkdir(parents=True, exist_ok=True)
            archive.extractall(extract_to)
        return self.install_from_directory(extract_to, known_providers=known_providers)

    def remove(self, artifact_id: str) -> bool:
        """Delete the artifact's stored bytes and metadata. The model
        registry entry is never mutated or deleted -- registries in this
        project are append-only, permanent history, exactly like every
        other registry here; `status()` correctly reports a removed
        model as artifact_present=False rather than pretending the
        registry entry never existed."""
        return self.artifact_store.delete(artifact_id)

    def verify(self, artifact_id: str) -> bool:
        """Re-verify a currently-installed artifact's integrity. True
        only if the stored bytes still match their recorded checksum."""
        if not self.artifact_store.exists(artifact_id):
            raise ModelManagerError(f"artifact {artifact_id!r} is not installed")
        try:
            self.artifact_store.load_bytes(artifact_id)
        except ArtifactIntegrityError:
            return False
        return True

    def status(self, artifact_id: str) -> ModelStatus:
        artifact_present = self.artifact_store.exists(artifact_id)
        checksum_valid: bool | None = None
        model_name = ""
        version = ""
        lifecycle_state = ModelLifecycleState.DRAFT.value
        if artifact_present:
            metadata = self.artifact_store.load_metadata(artifact_id)
            model_name = metadata.model_name
            version = metadata.model_version
            lifecycle_state = metadata.lifecycle_state.value
            try:
                self.artifact_store.load_bytes(artifact_id)
                checksum_valid = True
            except ArtifactIntegrityError:
                checksum_valid = False
        return ModelStatus(
            model_name=model_name,
            version=version,
            lifecycle_state=lifecycle_state,
            artifact_id=artifact_id if artifact_present else None,
            artifact_present=artifact_present,
            checksum_valid=checksum_valid,
        )

    def list_installed(self) -> list[str]:
        return self.artifact_store.list_ids()
