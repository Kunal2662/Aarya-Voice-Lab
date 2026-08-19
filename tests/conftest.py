"""Shared synthetic fixtures.

Every fixture here is fabricated. No fixture is derived from, or refers
to, any real recording — see docs/PRIVACY.md.
"""

from __future__ import annotations

import pytest

from aarya_voice_lab.core.paths import PROJECT_ROOT


@pytest.fixture
def project_root():
    return PROJECT_ROOT


@pytest.fixture
def synthetic_segment() -> dict:
    return {
        "schema_version": "0.1.0",
        "segment_id": "seg-test-0001",
        "source_file_id": "synthetic-source-001",
        "source_start": 0.0,
        "source_end": 2.5,
        "duration": 2.5,
        "speaker_id": "spk_0",
        "target_speaker_status": "eligible",
        "diarization_source": "synthetic-diarizer",
        "diarization_confidence": 0.97,
        "independent_verification_status": "verified",
        "overlap_status": "none",
        "language": "mr",
        "transcript": "[synthetic]",
        "alignment_status": "aligned",
        "audio_quality": {"snr_db": 30.0},
        "acceptance_status": "accepted",
        "rejection_reason": None,
        "processing_version": "0.1.0",
    }


@pytest.fixture
def synthetic_manifest(synthetic_segment) -> dict:
    return {
        "schema_version": "0.1.0",
        "dataset_id": "synthetic-dataset",
        "dataset_version": "0.0.0-test",
        "created_at": "2026-01-01T00:00:00Z",
        "is_synthetic": True,
        "segments": [synthetic_segment],
    }
