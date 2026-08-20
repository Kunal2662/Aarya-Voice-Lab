// Synthetic demo data for VL-D1 workspaces (§1, §9: "USE SYNTHETIC
// FIXTURES ONLY" for the import/batch/recording UI model). Every id here
// is prefixed `synthetic-` or `fixture-` and every record that could be
// mistaken for a real recording sets `is_synthetic: true` so it is
// impossible to confuse with real dataset content even out of context.
// Nothing in this file reads or references anything under data/ or
// source/.

import { createJob, JobStatus } from "./job-model.js";
import { createActivityEvent, ActivitySource, ActivitySeverity } from "./activity-model.js";

export function syntheticBatches() {
  return [
    {
      id: "synthetic-batch-001",
      status: "success",
      created: "2026-08-01T10:00:00Z",
      fileCount: 12,
      valid: 10,
      warning: 1,
      invalid: 1,
      blocked: 0,
      duplicates: 0,
      candidates: 9,
      reviewItems: 1,
      pipelineProgress: 1.0,
      is_synthetic: true,
    },
    {
      id: "synthetic-batch-002",
      status: "running",
      created: "2026-08-15T09:30:00Z",
      fileCount: 6,
      valid: 4,
      warning: 0,
      invalid: 0,
      blocked: 2,
      duplicates: 1,
      candidates: 3,
      reviewItems: 2,
      pipelineProgress: 0.4,
      is_synthetic: true,
    },
  ];
}

export function syntheticRecordings() {
  return [
    {
      id: "synthetic-rec-0001",
      batchId: "synthetic-batch-001",
      filename: "segment_0001.wav",
      contentAddressedId: "sha256:" + "a1".repeat(32),
      format: "wav",
      durationSeconds: 128.4,
      sampleRate: 44100,
      channels: 1,
      validation: "valid",
      quality: "acceptable",
      processingState: "candidate_manifest",
      classification: "source",
      is_synthetic: true,
    },
    {
      id: "synthetic-rec-0002",
      batchId: "synthetic-batch-001",
      filename: "segment_0002.wav",
      contentAddressedId: "sha256:" + "b2".repeat(32),
      format: "wav",
      durationSeconds: 44.9,
      sampleRate: 16000,
      channels: 1,
      validation: "warning",
      quality: "low_snr",
      processingState: "quality_analysis",
      classification: "source",
      is_synthetic: true,
    },
    {
      id: "synthetic-rec-0003",
      batchId: "synthetic-batch-002",
      filename: "segment_0003.wav",
      contentAddressedId: "sha256:" + "c3".repeat(32),
      format: "mp3",
      durationSeconds: 61.2,
      sampleRate: 22050,
      channels: 2,
      validation: "invalid",
      quality: "unacceptable",
      processingState: "normalization",
      classification: "source",
      is_synthetic: true,
    },
  ];
}

export function syntheticJobs() {
  return [
    createJob({
      id: "synthetic-job-001",
      type: "pipeline_run",
      status: JobStatus.RUNNING,
      startTime: "2026-08-20T09:00:00Z",
      progress: 0.4,
      currentStage: "segmentation",
      relatedEntity: { kind: "batch", id: "synthetic-batch-002" },
      logsRef: "synthetic-job-001.log",
    }),
    createJob({
      id: "synthetic-job-002",
      type: "pipeline_run",
      status: JobStatus.SUCCESS,
      startTime: "2026-08-19T14:00:00Z",
      endTime: "2026-08-19T14:12:00Z",
      progress: 1,
      currentStage: "candidate_manifest",
      relatedEntity: { kind: "batch", id: "synthetic-batch-001" },
      logsRef: "synthetic-job-002.log",
    }),
    createJob({
      id: "synthetic-job-003",
      type: "pipeline_run",
      status: JobStatus.FAILED,
      startTime: "2026-08-18T11:00:00Z",
      endTime: "2026-08-18T11:03:00Z",
      progress: 0.2,
      currentStage: "normalization",
      error: "StageContractError: input hash mismatch",
      relatedEntity: { kind: "batch", id: "synthetic-batch-002" },
      logsRef: "synthetic-job-003.log",
    }),
  ];
}

export function syntheticActivity() {
  return [
    createActivityEvent({
      id: "synthetic-activity-001",
      timestamp: "2026-08-20T09:05:00Z",
      severity: ActivitySeverity.INFO,
      source: ActivitySource.SEGMENTATION,
      status: "running",
      summary: "Segmentation running on synthetic-batch-002",
    }),
    createActivityEvent({
      id: "synthetic-activity-002",
      timestamp: "2026-08-19T14:12:00Z",
      severity: ActivitySeverity.SUCCESS,
      source: ActivitySource.REVIEW,
      status: "success",
      summary: "Candidate manifest completed for synthetic-batch-001",
    }),
    createActivityEvent({
      id: "synthetic-activity-003",
      timestamp: "2026-08-18T11:03:00Z",
      severity: ActivitySeverity.DANGER,
      source: ActivitySource.ERROR,
      status: "failed",
      summary: "Normalization failed on synthetic-batch-002: input hash mismatch",
    }),
    createActivityEvent({
      id: "synthetic-activity-004",
      timestamp: "2026-08-17T08:00:00Z",
      severity: ActivitySeverity.WARNING,
      source: ActivitySource.QUALITY,
      status: "warning",
      summary: "Low SNR flagged on synthetic-rec-0002",
    }),
    // VL-D3 §23 — Dataset Review activity kinds. Session-only example
    // entries, same as the four above: nothing here is a live pipeline
    // trigger yet, only what such an event looks like once one exists.
    createActivityEvent({
      id: "synthetic-activity-005",
      timestamp: "2026-08-20T09:02:00Z",
      severity: ActivitySeverity.INFO,
      source: ActivitySource.QUALITY,
      status: "completed",
      summary: "Quality analysis completed for synthetic-rec-0001 (PASS)",
    }),
    createActivityEvent({
      id: "synthetic-activity-006",
      timestamp: "2026-08-19T15:00:00Z",
      severity: ActivitySeverity.SUCCESS,
      source: ActivitySource.SEGMENTATION,
      status: "completed",
      summary: "Segmentation completed for synthetic-rec-0001 (5 segments)",
    }),
    createActivityEvent({
      id: "synthetic-activity-007",
      timestamp: "2026-08-19T15:01:00Z",
      severity: ActivitySeverity.WARNING,
      source: ActivitySource.QUALITY,
      status: "overlap_candidate_detected",
      summary: "Overlap candidate detected in synthetic-rec-0001 (seg-0001-05, POSSIBLE_OVERLAP)",
    }),
    createActivityEvent({
      id: "synthetic-activity-008",
      timestamp: "2026-08-19T14:15:00Z",
      severity: ActivitySeverity.SUCCESS,
      source: ActivitySource.REVIEW,
      status: "batch_review_completed",
      summary: "Batch review completed for synthetic-batch-001",
    }),
  ];
}

export function syntheticVoices() {
  return [
    {
      id: "synthetic-voice-default",
      name: "Default Voice (example)",
      version: 1,
      previewVersion: 2,
      feedback: "regenerate",
      calibrationState: "UNCALIBRATED",
      speakerVerificationState: "not_run",
      is_synthetic: true,
    },
  ];
}

// VL-D3 — quality/segment/overlap fixtures, keyed by recording id. Shapes
// mirror pipeline.quality.QualityAssessment.to_dict() /
// pipeline.overlap.OverlapAssessment.to_dict() closely enough that a
// real backend response could be dropped in without changing any
// component, but nothing here is computed — it's fixed example data.
export function syntheticQualityAssessments() {
  return {
    "synthetic-rec-0001": {
      sourceFileId: "src-a1a1a1a1",
      decision: "PASS",
      findings: [],
      measurements: {
        durationSeconds: 128.4,
        sampleRate: 44100,
        peakDbfs: -3.2,
        rmsDbfs: -18.4,
        crestFactorDb: 15.2,
        noiseFloorDbfs: -52.1,
        estimatedSnrDb: 33.7,
        silentFrameRatio: 0.12,
        clippingRatio: 0.0,
        dcOffset: 0.001,
      },
      speech: { speechRatio: 0.81, totalSpeechSeconds: 104.0, speechRegionCount: 6, longPauseCount: 1 },
      characteristics: [],
    },
    "synthetic-rec-0002": {
      sourceFileId: "src-b2b2b2b2",
      decision: "REVIEW",
      findings: [
        { code: "low_snr", message: "estimated SNR 5.8 dB is low; flagged for review rather than rejected", decision: "REVIEW" },
      ],
      measurements: {
        durationSeconds: 44.9,
        sampleRate: 16000,
        peakDbfs: -6.1,
        rmsDbfs: -24.9,
        crestFactorDb: 18.8,
        noiseFloorDbfs: -30.6,
        estimatedSnrDb: 5.8,
        silentFrameRatio: 0.34,
        clippingRatio: 0.0,
        dcOffset: 0.004,
      },
      speech: { speechRatio: 0.58, totalSpeechSeconds: 26.0, speechRegionCount: 4, longPauseCount: 2 },
      characteristics: ["narrowband_16000hz (typical of telephone/call recordings; recorded, not penalised)"],
    },
    "synthetic-rec-0003": {
      sourceFileId: "src-c3c3c3c3",
      decision: "FAIL",
      findings: [
        { code: "severe_clipping", message: "6.20% of samples are clipped", decision: "FAIL" },
      ],
      measurements: {
        durationSeconds: 61.2,
        sampleRate: 22050,
        peakDbfs: 0.0,
        rmsDbfs: -9.1,
        crestFactorDb: 9.1,
        noiseFloorDbfs: -40.2,
        estimatedSnrDb: 31.1,
        silentFrameRatio: 0.05,
        clippingRatio: 0.062,
        dcOffset: 0.02,
      },
      speech: { speechRatio: 0.91, totalSpeechSeconds: 55.7, speechRegionCount: 3, longPauseCount: 0 },
      characteristics: [],
    },
  };
}

export function syntheticSegments(recordingId) {
  const bySegmentRecording = {
    "synthetic-rec-0001": [
      { segmentId: "seg-0001-01", start: 0.0, end: 12.4, kind: "speech", qualityState: "PASS", candidateState: "ACCEPTED" },
      { segmentId: "seg-0001-02", start: 12.4, end: 13.1, kind: "silence", qualityState: null, candidateState: null },
      { segmentId: "seg-0001-03", start: 13.1, end: 41.9, kind: "speech", qualityState: "PASS", candidateState: "PENDING" },
      { segmentId: "seg-0001-04", start: 41.9, end: 44.2, kind: "silence", qualityState: null, candidateState: null },
      { segmentId: "seg-0001-05", start: 44.2, end: 78.6, kind: "speech", qualityState: "WARNING", candidateState: "NEEDS_REVIEW" },
    ],
    "synthetic-rec-0002": [
      { segmentId: "seg-0002-01", start: 0.0, end: 8.2, kind: "speech", qualityState: "REVIEW", candidateState: "NEEDS_REVIEW" },
      { segmentId: "seg-0002-02", start: 8.2, end: 11.0, kind: "silence", qualityState: null, candidateState: null },
      { segmentId: "seg-0002-03", start: 11.0, end: 26.0, kind: "speech", qualityState: "REVIEW", candidateState: "PENDING" },
    ],
    "synthetic-rec-0003": [
      { segmentId: "seg-0003-01", start: 0.0, end: 61.2, kind: "speech", qualityState: "FAIL", candidateState: "REJECTED" },
    ],
  };
  return bySegmentRecording[recordingId] || [];
}

export function syntheticOverlapCandidates(recordingId) {
  const byRecording = {
    "synthetic-rec-0001": [
      {
        segmentId: "seg-0001-05",
        start: 60.0,
        end: 61.5,
        duration: 1.5,
        status: "POSSIBLE_OVERLAP",
        confidence: 0.41,
        reason: "elevated zero-crossing-rate instability over a sustained span",
      },
    ],
  };
  return byRecording[recordingId] || [];
}

// Deterministic peak arrays for the waveform visualisation — not derived
// from any audio, just a fixed shape to render (real peak extraction
// belongs to a future real-audio decode path).
export function syntheticWaveformPeaks(recordingId) {
  const seed = recordingId.split("").reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  const peaks = [];
  for (let i = 0; i < 60; i++) {
    peaks.push(Math.abs(Math.sin((i + seed) * 0.35)) * 0.6 + Math.abs(Math.sin((i + seed) * 1.7)) * 0.3);
  }
  return peaks;
}

// VL-D4 — processing profile / queue / history fixtures. Shapes mirror
// pipeline.processing_profile.ProcessingProfile.to_dict() /
// pipeline.processing.ProcessingItem.to_dict() /
// pipeline.processing_history.ProcessingHistoryRecord.to_dict() closely
// enough that a real backend response could be dropped in without
// changing any component, but nothing here is computed -- it's fixed
// example data, same as every other synthetic-fixtures.js export.
export function syntheticProcessingProfiles() {
  return [
    {
      profileId: "conservative-v1",
      name: "conservative",
      version: 1,
      normalization: {
        targetSampleRate: 16000,
        targetChannels: 1,
        targetBitDepth: 16,
        applyLoudnessNormalization: false,
        targetLoudnessLufs: -23.0,
      },
      boundary: { trimLeadingSilence: true, trimTrailingSilence: true, minTrimSeconds: 0.1, padSeconds: 0.05 },
      noiseConditioningMode: "MEASURE_ONLY",
      notes: "Gentle defaults -- minimal alteration.",
      createdAt: "2026-08-10T09:00:00Z",
      is_synthetic: true,
    },
    {
      profileId: "standard-v1",
      name: "standard",
      version: 1,
      normalization: {
        targetSampleRate: 16000,
        targetChannels: 1,
        targetBitDepth: 16,
        applyLoudnessNormalization: false,
        targetLoudnessLufs: -23.0,
      },
      boundary: { trimLeadingSilence: true, trimTrailingSilence: true, minTrimSeconds: 0.1, padSeconds: 0.05 },
      noiseConditioningMode: "MEASURE_ONLY",
      notes: "Default processing profile.",
      createdAt: "2026-08-12T09:00:00Z",
      is_synthetic: true,
    },
    {
      profileId: "standard-v2",
      name: "standard",
      version: 2,
      normalization: {
        targetSampleRate: 22050,
        targetChannels: 1,
        targetBitDepth: 16,
        applyLoudnessNormalization: false,
        targetLoudnessLufs: -23.0,
      },
      boundary: { trimLeadingSilence: true, trimTrailingSilence: true, minTrimSeconds: 0.15, padSeconds: 0.05 },
      noiseConditioningMode: "MEASURE_ONLY",
      notes: "Bumped target sample rate for TTS-oriented derivation.",
      createdAt: "2026-08-18T09:00:00Z",
      is_synthetic: true,
    },
  ];
}

export function syntheticProcessingItems() {
  return {
    "synthetic-rec-0001": {
      itemId: "proc-0000-synthetic-rec-0001",
      recordingId: "synthetic-rec-0001",
      profileId: "standard-v1",
      status: "SUCCESS",
      progress: 1.0,
      currentOperation: null,
      warnings: [],
      errors: [],
      decision: "NO_PROCESSING",
      processingDurationSeconds: 1.82,
      derivedArtifact: {
        artifactId: "af1" + "af1af1af1af1af1af1af1af1af1af1af1af1af1af1".slice(0, 61),
        outputPath: "proc-0000-synthetic-rec-0001.normalized.wav",
        outputSha256: "d1".repeat(32),
        boundary: { leadingTrimSeconds: 0.42, trailingTrimSeconds: 0.3, note: null },
        normalization: { tool: "ffmpeg", toolVersion: "6.1.1", status: "completed" },
        noiseConditioning: {
          mode: "MEASURE_ONLY",
          outcome: "measured_only",
          note: "Noise floor and estimated SNR are already reported by quality measurements; audio is unchanged.",
        },
      },
      qualityBefore: { decision: "PASS", measurements: { estimatedSnrDb: 33.7, durationSeconds: 128.4 } },
      qualityAfter: { decision: "PASS", measurements: { estimatedSnrDb: 34.1, durationSeconds: 127.68 } },
    },
    "synthetic-rec-0002": {
      itemId: "proc-0001-synthetic-rec-0002",
      recordingId: "synthetic-rec-0002",
      profileId: "standard-v1",
      status: "WARNING",
      progress: 1.0,
      currentOperation: null,
      warnings: [
        "normalization unavailable: FFmpeg is not installed, so audio cannot be normalized. The original " +
          "was not read, converted, or modified. Install FFmpeg and re-run; no substitute tool will be used.",
      ],
      errors: [],
      decision: "STANDARD_CONDITIONING",
      processingDurationSeconds: 0.61,
      derivedArtifact: {
        artifactId: "b2".repeat(32),
        outputPath: "proc-0001-synthetic-rec-0002.boundary.wav",
        outputSha256: "b2".repeat(32),
        boundary: { leadingTrimSeconds: 0.0, trailingTrimSeconds: 0.0, note: null },
        normalization: null,
        noiseConditioning: {
          mode: "MEASURE_ONLY",
          outcome: "measured_only",
          note: "Noise floor and estimated SNR are already reported by quality measurements; audio is unchanged.",
        },
      },
      qualityBefore: { decision: "REVIEW", measurements: { estimatedSnrDb: 5.8, durationSeconds: 44.9 } },
      qualityAfter: { decision: "REVIEW", measurements: { estimatedSnrDb: 5.8, durationSeconds: 44.9 } },
    },
    "synthetic-rec-0003": {
      itemId: "proc-0002-synthetic-rec-0003",
      recordingId: "synthetic-rec-0003",
      profileId: "standard-v1",
      status: "BLOCKED",
      progress: 1.0,
      currentOperation: null,
      warnings: [],
      errors: [
        "source hash mismatch for synthetic-rec-0003: expected c3c3c3…, found 000000…. " +
          "Source recordings are immutable; processing stopped.",
      ],
      decision: null,
      processingDurationSeconds: 0.02,
      derivedArtifact: null,
      qualityBefore: null,
      qualityAfter: null,
    },
  };
}

export function syntheticProcessingHistory(recordingId) {
  const byRecording = {
    "synthetic-rec-0001": [
      {
        recordId: "proc-hist-00001",
        recordingId: "synthetic-rec-0001",
        artifactId: "aa1" + "aa1aa1aa1aa1aa1aa1aa1aa1aa1aa1aa1aa1aa1aa1".slice(0, 61),
        outputSha256: "aa".repeat(32),
        profileId: "standard-v1",
        profileName: "standard",
        profileVersion: 1,
        status: "SUCCESS",
        toolVersion: "6.1.1",
        supersedes: null,
        isRollback: false,
        recordedAt: "2026-08-15T10:00:00Z",
      },
      {
        recordId: "proc-hist-00002",
        recordingId: "synthetic-rec-0001",
        artifactId: "af1" + "af1af1af1af1af1af1af1af1af1af1af1af1af1af1".slice(0, 61),
        outputSha256: "d1".repeat(32),
        profileId: "standard-v2",
        profileName: "standard",
        profileVersion: 2,
        status: "SUCCESS",
        toolVersion: "6.1.1",
        supersedes: "proc-hist-00001",
        isRollback: false,
        recordedAt: "2026-08-18T10:00:00Z",
      },
    ],
  };
  return byRecording[recordingId] || [];
}

// VL-D5 — voice profile / generation model / preview generation
// fixtures. Shapes mirror pipeline.voice_profile.VoiceProfile.to_dict() /
// pipeline.generation_models.GenerationModel.to_dict() /
// pipeline.generation.PreviewRequest.to_dict() /
// pipeline.generation.GenerationItem.to_dict() /
// identity.preview.PreviewArtifact.to_dict() /
// pipeline.preview_history.PreviewHistoryRecord.to_dict() /
// identity.preview.PreviewFeedback.to_dict() closely enough that a real
// backend response could be dropped in without changing any component --
// nothing here is computed, it's fixed example data, same as every other
// synthetic-fixtures.js export.
export function syntheticVoiceProfiles() {
  return [
    {
      profile_id: "demo-voice-v1",
      name: "demo-voice",
      version: 1,
      state: "SYNTHETIC_PROFILE",
      style_controls: { pace: "moderate" },
      generation_preferences: { output_format: "wav" },
      notes: "Example profile for the VL-D5 demo -- carries no speaker characteristics.",
      created_at: "2026-08-10T09:00:00Z",
      is_synthetic: true,
    },
  ];
}

export function syntheticGenerationModels() {
  return [
    {
      model_id: "synthetic-tone-v1",
      name: "Synthetic Tone (demo backend)",
      version: "0.1.0",
      backend: "cpu",
      capabilities: ["speed", "seed", "output_format"],
      requirements: null,
      status: "AVAILABLE",
      is_synthetic: true,
    },
    {
      model_id: "unavailable-model-v1",
      name: "Example Unavailable Backend",
      version: "0.0.0",
      backend: "cpu",
      capabilities: [],
      requirements: null,
      status: "UNAVAILABLE",
      is_synthetic: true,
    },
  ];
}

export function syntheticPreviewRequests() {
  return [
    {
      request_id: "preview-req-example-001",
      text: "This is an example line of preview text for the Voice Preview workspace.",
      voice_profile_id: "demo-voice-v1",
      generation_profile_id: null,
      model_id: "synthetic-tone-v1",
      sample_rate: 16000,
      output_format: "wav",
      seed: 42,
      controls: { speed: "1.0" },
      config_hash: "e1".repeat(32),
    },
  ];
}

export function syntheticPreviewItems() {
  return [
    {
      item_id: "gen-0000-preview-req-example-001",
      request: syntheticPreviewRequests()[0],
      status: "READY",
      progress: 1,
      current_operation: null,
      warnings: [],
      errors: [],
      artifact: {
        preview_id: "preview-req-example-001-preview",
        kind: "synthetic_fixture",
        relative_path: "previews/preview-req-example-001.wav",
        sha256: "f1".repeat(32),
        duration_seconds: 4.4,
        sample_rate: 16000,
        iteration: 1,
        origin_id: "preview-req-example-001",
        model_name: "synthetic-tone",
        model_version: "0.1.0",
        is_synthetic: true,
        created_at: "2026-08-19T09:00:00Z",
        artifact_id: "aa1".repeat(22).slice(0, 64),
      },
      generation_duration_seconds: 0.42,
    },
  ];
}

export function syntheticPreviewHistory() {
  return {
    "demo-voice-v1": [
      {
        record_id: "preview-hist-00001",
        voice_profile_id: "demo-voice-v1",
        request_id: "preview-req-example-001",
        output_id: "preview-req-example-001-preview",
        model_id: "synthetic-tone-v1",
        config_hash: "e1".repeat(32),
        status: "READY",
        output_sha256: "f1".repeat(32),
        tool_version: "0.1.0",
        supersedes: null,
        recorded_at: "2026-08-19T09:00:05Z",
      },
    ],
  };
}

export function syntheticPreviewFeedback() {
  return [
    {
      feedback_id: "preview-feedback-00001",
      preview_id: "preview-req-example-001-preview",
      listener: "operator",
      outcome: "accepted",
      listened: true,
      listen_duration_seconds: 4.4,
      comment: "Sounds clear.",
      attributes: { category: "VOICE_QUALITY", rating: "4" },
      requests_regeneration: false,
      created_at: "2026-08-19T09:01:00Z",
    },
  ];
}

export function syntheticModels() {
  return [
    {
      id: "synthetic-model-001",
      name: "example-tts-candidate",
      version: "0.0.0-synthetic",
      runtime: "not_installed",
      backend: "cpu",
      hardwareCompatible: "unknown",
      status: "not_available",
      sizeBytes: null,
      calibrationState: "UNCALIBRATED",
      is_synthetic: true,
    },
  ];
}
