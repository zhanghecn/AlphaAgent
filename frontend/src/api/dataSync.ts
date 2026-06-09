import { apiClient } from "./client";
import type { SyncCoverage } from "./types";

/** Backend returns plain arrays for these endpoints, not {items, total} wrappers. */
export function fetchSyncSources() {
  return apiClient.get<SyncSourceItem[]>("/data-sync/sources");
}

export function fetchSyncJobs() {
  return apiClient.get<SyncJobItem[]>("/data-sync/jobs");
}

export function fetchSyncRuns(limit = 20) {
  return apiClient.get<SyncRunItem[]>(`/data-sync/runs?limit=${limit}`);
}

export function fetchSyncCoverage() {
  return apiClient.get<SyncCoverage>("/data-sync/coverage");
}

export function fetchDataUsage() {
  return apiClient.get<DataUsageResponse>("/data-sync/usage");
}

export function runSyncJob(jobId: string, params: Record<string, unknown> = {}) {
  return apiClient.post<SyncRunItem>(`/data-sync/jobs/${encodeURIComponent(jobId)}/run`, params);
}

// ── Types matching actual backend responses ──

export interface SyncSourceItem {
  id: string;
  name: string;
  kind: string;
  base_url?: string;
  enabled: boolean;
  priority: number;
  status: string;
  message?: string;
  checked_at?: string;
}

export interface SyncJobItem {
  id: string;
  name: string;
  description: string;
  source_id: string;
  target_table: string;
  enabled: boolean;
  default_params: Record<string, unknown>;
  schedule_cron?: string | null;
  last_status?: string | null;
  last_run_id?: string | null;
  last_started_at?: string | null;
}

export interface SyncRunItem {
  id: string;
  job_id: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  rows_read: number;
  rows_written: number;
  error?: string | null;
}

export interface DataUsageCapability {
  name: string;
  table: string;
  description: string;
  status: string;
  count: number;
}

export interface DataUsageResponse {
  capabilities: DataUsageCapability[];
  coverage: Record<string, { count: number; last_updated?: string }>;
}
