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

export function syntheticRecordings(batchId = "synthetic-batch-001") {
  return [
    {
      id: "synthetic-rec-0001",
      batchId,
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
      batchId,
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
