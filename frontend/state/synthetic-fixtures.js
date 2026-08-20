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
