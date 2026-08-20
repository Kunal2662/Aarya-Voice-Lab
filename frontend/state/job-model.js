// Frontend job/task state model (VL-D1 §7). Renders through the
// "pipeline_stage" status-vocabulary domain (frontend/tokens/status.json)
// — that domain's not_started/queued/running/success/warning/failed/
// blocked/paused/cancelled lifecycle already covers everything a job
// needs, so a job's status is a job's status through the same badge and
// the same colors a pipeline stage uses, rather than a second vocabulary
// meaning the same thing.
//
// This module owns no execution. It is a client-side record of jobs the
// backend (or, for VL-D1, a synthetic fixture) reports — never a queue
// that runs anything itself.

export const JOB_STATUS_DOMAIN = "pipeline_stage";

export const JobStatus = Object.freeze({
  QUEUED: "queued",
  RUNNING: "running",
  PAUSED: "paused",
  SUCCESS: "success",
  WARNING: "warning",
  FAILED: "failed",
  BLOCKED: "blocked",
  CANCELLED: "cancelled",
});

const TERMINAL = new Set([JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.CANCELLED]);

/** @typedef {{id:string,type:string,status:string,startTime:string|null,endTime:string|null,progress:number|null,currentStage:string|null,error:string|null,relatedEntity:{kind:string,id:string}|null,logsRef:string|null}} Job */

/**
 * @param {Partial<Job> & {id:string,type:string}} fields
 * @returns {Job}
 */
export function createJob(fields) {
  if (!fields.id || !fields.type) {
    throw new Error("createJob requires at least { id, type }");
  }
  return {
    id: fields.id,
    type: fields.type,
    status: fields.status || JobStatus.QUEUED,
    startTime: fields.startTime ?? null,
    endTime: fields.endTime ?? null,
    progress: fields.progress ?? null,
    currentStage: fields.currentStage ?? null,
    error: fields.error ?? null,
    relatedEntity: fields.relatedEntity ?? null,
    logsRef: fields.logsRef ?? null,
  };
}

export function isTerminal(status) {
  return TERMINAL.has(status);
}

/** In-memory, event-based job store. No persistence, no network, no execution. */
export class JobStore extends EventTarget {
  constructor(initialJobs = []) {
    super();
    /** @type {Map<string, Job>} */
    this._jobs = new Map(initialJobs.map((job) => [job.id, job]));
  }

  list() {
    return Array.from(this._jobs.values());
  }

  get(id) {
    return this._jobs.get(id) || null;
  }

  upsert(job) {
    this._jobs.set(job.id, job);
    this.dispatchEvent(new CustomEvent("change", { detail: { job } }));
    return job;
  }

  current() {
    return this.list().filter((job) => !isTerminal(job.status));
  }

  recent(limit = 20) {
    return this.list()
      .filter((job) => isTerminal(job.status))
      .sort((a, b) => (b.endTime || "").localeCompare(a.endTime || ""))
      .slice(0, limit);
  }

  failed() {
    return this.list().filter((job) => job.status === JobStatus.FAILED);
  }
}
