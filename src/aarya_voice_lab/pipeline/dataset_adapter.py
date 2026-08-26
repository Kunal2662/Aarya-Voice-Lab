"""Dataset adapter interface: normalizes a public/third-party dataset's
own record format into one project-wide shape before it reaches the
training pipeline.

See docs/DATA_POLICY.md for the public-licensed-data track this serves.
An adapter reads one dataset's own on-disk/manifest format and yields
NormalizedRecord instances -- it never writes, modifies, or deletes
source content, and never fabricates a field (transcript, speaker_id,
...) the underlying dataset does not actually provide. Not every public
dataset exposes speaker identity, and this module never infers one that
isn't already present in the dataset's own metadata.

This is a separate, upstream concept from schemas/segment.schema.json:
segment records describe candidate slices of the project's own private
recordings after diarization/verification. A NormalizedRecord describes
one already-segmented utterance from a third-party dataset, before it
ever enters that private pipeline.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class NormalizedRecord:
    """One utterance/sample from a public dataset, in this project's
    common shape. Carries a reference to audio (a path or dataset-native
    identifier), never the audio bytes themselves."""

    dataset_id: str
    record_id: str
    audio_ref: str
    language: str
    license: str
    transcript: str | None = None
    speaker_id: str | None = None
    sample_rate: int | None = None
    duration_seconds: float | None = None
    provenance: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "record_id": self.record_id,
            "audio_ref": self.audio_ref,
            "language": self.language,
            "license": self.license,
            "transcript": self.transcript,
            "speaker_id": self.speaker_id,
            "sample_rate": self.sample_rate,
            "duration_seconds": self.duration_seconds,
            "provenance": self.provenance,
            "metadata": self.metadata,
        }


class DatasetAdapter(ABC):
    """Contract every public-dataset adapter satisfies."""

    dataset_id: str

    @abstractmethod
    def iter_records(self) -> Iterator[NormalizedRecord]:
        """Yield every record this dataset provides, normalized."""

    def record_count(self) -> int:
        """Convenience default; an adapter with a cheap/known count
        should override rather than materializing iter_records() just to
        count it."""
        return sum(1 for _ in self.iter_records())


class DatasetAdapterError(ValueError):
    """Raised when a dataset's own on-disk content cannot be normalized."""


class FixtureDatasetAdapter(DatasetAdapter):
    """Reference adapter for a repository-controlled JSON Lines fixture
    manifest -- one JSON object per line, each describing one record.

    This is the adapter used by this project's own tests and by any
    pipeline-validation work that must not depend on downloading a real
    external dataset (see docs/DATA_POLICY.md and TASK 4 of the
    autonomous execution record). It never reaches the network; it only
    reads a local file the caller already has.
    """

    def __init__(self, manifest_path: Path, *, dataset_id: str, license: str):
        self.manifest_path = manifest_path
        self.dataset_id = dataset_id
        self.license = license

    def iter_records(self) -> Iterator[NormalizedRecord]:
        if not self.manifest_path.is_file():
            raise DatasetAdapterError(f"fixture manifest not found: {self.manifest_path}")
        with self.manifest_path.open("r", encoding="utf-8") as fh:
            for line_number, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise DatasetAdapterError(f"{self.manifest_path}:{line_number}: invalid JSON: {exc}") from exc
                yield self._normalize(raw, line_number)

    def _normalize(self, raw: dict[str, Any], line_number: int) -> NormalizedRecord:
        missing = [key for key in ("record_id", "audio_ref", "language") if key not in raw]
        if missing:
            raise DatasetAdapterError(
                f"{self.manifest_path}:{line_number}: missing required field(s): {missing}"
            )
        return NormalizedRecord(
            dataset_id=self.dataset_id,
            record_id=raw["record_id"],
            audio_ref=raw["audio_ref"],
            language=raw["language"],
            license=self.license,
            transcript=raw.get("transcript"),
            speaker_id=raw.get("speaker_id"),
            sample_rate=raw.get("sample_rate"),
            duration_seconds=raw.get("duration_seconds"),
            provenance=raw.get("provenance"),
            metadata=raw.get("metadata"),
        )


class LibriSpeechDatasetAdapter(DatasetAdapter):
    """Adapter for the real LibriSpeech ASR corpus on-disk layout
    (https://www.openslr.org/12/):
    `<root>/<speaker_id>/<chapter_id>/<speaker_id>-<chapter_id>-<utterance>.flac`,
    with transcripts in a sibling `<speaker_id>-<chapter_id>.trans.txt`
    (one `<utterance_id> <TRANSCRIPT>` line per utterance).

    Never infers a transcript, speaker id, sample rate, or duration this
    dataset's own on-disk files do not literally contain -- an utterance
    whose id is absent from its chapter's `.trans.txt` yields
    `transcript=None` rather than a guess, and `speaker_id` is exactly the
    reader directory name LibriSpeech itself assigned. Reads only; never
    writes, converts, or deletes anything under `root`.
    """

    def __init__(self, root: Path, *, dataset_id: str, license: str = "CC BY 4.0", language: str = "en"):
        self.root = root
        self.dataset_id = dataset_id
        self.license = license
        self.language = language

    def iter_records(self) -> Iterator[NormalizedRecord]:
        if not self.root.is_dir():
            raise DatasetAdapterError(f"LibriSpeech root not found: {self.root}")
        for speaker_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            speaker_id = speaker_dir.name
            for chapter_dir in sorted(p for p in speaker_dir.iterdir() if p.is_dir()):
                chapter_id = chapter_dir.name
                transcripts = self._read_transcripts(chapter_dir, speaker_id, chapter_id)
                for flac_path in sorted(chapter_dir.glob("*.flac")):
                    utterance_id = flac_path.stem
                    yield NormalizedRecord(
                        dataset_id=self.dataset_id,
                        record_id=utterance_id,
                        audio_ref=str(flac_path),
                        language=self.language,
                        license=self.license,
                        transcript=transcripts.get(utterance_id),
                        speaker_id=speaker_id,
                        sample_rate=None,
                        duration_seconds=None,
                        provenance=f"LibriSpeech {self.dataset_id}, speaker={speaker_id}, chapter={chapter_id}",
                        metadata={"chapter_id": chapter_id},
                    )

    def _read_transcripts(self, chapter_dir: Path, speaker_id: str, chapter_id: str) -> dict[str, str]:
        trans_path = chapter_dir / f"{speaker_id}-{chapter_id}.trans.txt"
        if not trans_path.is_file():
            return {}
        transcripts: dict[str, str] = {}
        for line in trans_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            utterance_id, _, text = line.partition(" ")
            if utterance_id:
                transcripts[utterance_id] = text
        return transcripts
