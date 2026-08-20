// Dataset-level quality aggregation — VL-D3 §18. Mirrors
// pipeline.quality_summary.summarize_quality()'s shape and bucket
// boundaries exactly (see src/aarya_voice_lab/pipeline/quality_summary.py)
// so a future real backend response could replace this fixture-driven
// computation without changing dataset-quality-summary.js. Pure
// aggregation only — no new measurement, no new quality decision, no
// heavy visualization dependency (VL-D3 §18: "no heavy visualization
// libraries, minimal frontend dependencies").
import { syntheticRecordings, syntheticQualityAssessments, syntheticOverlapCandidates } from "./synthetic-fixtures.js";

const NOT_AVAILABLE = "not_available";
const DURATION_BUCKETS = [
  ["<30s", 0, 30],
  ["30-60s", 30, 60],
  ["60-120s", 60, 120],
  ["120s+", 120, Infinity],
];
const SNR_BUCKETS = [
  ["<10dB", -Infinity, 10],
  ["10-20dB", 10, 20],
  ["20-30dB", 20, 30],
  ["30dB+", 30, Infinity],
];
const RATIO_BUCKETS = [
  ["0-25%", 0, 0.25],
  ["25-50%", 0.25, 0.5],
  ["50-75%", 0.5, 0.75],
  ["75-100%", 0.75, 1.0000001],
];
const NARROWBAND_SAMPLE_RATE_HZ = 16000;
const OVERLAP_CANDIDATE_STATUSES = new Set(["POSSIBLE_OVERLAP", "OVERLAP_DETECTED"]);

function bucket(value, buckets) {
  if (value === null || value === undefined) return NOT_AVAILABLE;
  for (const [label, low, high] of buckets) {
    if (value >= low && value < high) return label;
  }
  return buckets[buckets.length - 1][0];
}

function increment(distribution, key) {
  distribution[key] = (distribution[key] || 0) + 1;
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function summarizeQuality() {
  const recordings = syntheticRecordings();
  const assessments = syntheticQualityAssessments();

  if (!recordings.length) {
    return {
      recordingCount: 0,
      averageDurationSeconds: null,
      medianDurationSeconds: null,
      decisionDistribution: {},
      sampleRateDistribution: {},
      channelDistribution: {},
      warningCodeDistribution: {},
      durationDistribution: {},
      snrDistribution: {},
      speechRatioDistribution: {},
      silenceRatioDistribution: {},
      narrowbandCount: 0,
      overlapCandidateCount: 0,
    };
  }

  const decisionDistribution = {};
  const sampleRateDistribution = {};
  const channelDistribution = {};
  const warningCodeDistribution = {};
  const durationDistribution = {};
  const snrDistribution = {};
  const speechRatioDistribution = {};
  const silenceRatioDistribution = {};
  let narrowbandCount = 0;
  let overlapCandidateCount = 0;
  const durations = [];

  for (const recording of recordings) {
    const assessment = assessments[recording.id] || null;
    const decision = assessment ? assessment.decision : "NOT_ANALYZED";
    increment(decisionDistribution, decision);

    increment(sampleRateDistribution, String(recording.sampleRate));
    if (recording.sampleRate < NARROWBAND_SAMPLE_RATE_HZ) narrowbandCount += 1;
    increment(channelDistribution, String(recording.channels));

    if (recording.durationSeconds != null) durations.push(recording.durationSeconds);
    increment(durationDistribution, bucket(recording.durationSeconds, DURATION_BUCKETS));

    if (assessment) {
      for (const finding of assessment.findings) increment(warningCodeDistribution, finding.code);
      increment(snrDistribution, bucket(assessment.measurements.estimatedSnrDb, SNR_BUCKETS));
      increment(speechRatioDistribution, bucket(assessment.speech.speechRatio, RATIO_BUCKETS));
      increment(silenceRatioDistribution, bucket(assessment.measurements.silentFrameRatio, RATIO_BUCKETS));
    } else {
      increment(snrDistribution, NOT_AVAILABLE);
      increment(speechRatioDistribution, NOT_AVAILABLE);
      increment(silenceRatioDistribution, NOT_AVAILABLE);
    }

    for (const candidate of syntheticOverlapCandidates(recording.id)) {
      if (OVERLAP_CANDIDATE_STATUSES.has(candidate.status)) overlapCandidateCount += 1;
    }
  }

  return {
    recordingCount: recordings.length,
    averageDurationSeconds: durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null,
    medianDurationSeconds: median(durations),
    decisionDistribution,
    sampleRateDistribution,
    channelDistribution,
    warningCodeDistribution,
    durationDistribution,
    snrDistribution,
    speechRatioDistribution,
    silenceRatioDistribution,
    narrowbandCount,
    overlapCandidateCount,
  };
}
