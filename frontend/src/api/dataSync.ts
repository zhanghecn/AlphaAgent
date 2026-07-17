import { apiClient, authFetch } from "./client";
import type { SyncCoverage } from "./types";

/** Backend returns plain arrays for these endpoints, not {items, total} wrappers. */
type ListResponse<T> = T[] | { items?: T[] };

function unwrapItems<T>(payload: ListResponse<T>): T[] {
  return Array.isArray(payload) ? payload : payload.items ?? [];
}

export async function fetchSyncSources() {
  return unwrapItems(await apiClient.get<ListResponse<SyncSourceItem>>("/data-sync/sources"));
}

export async function fetchSyncJobs() {
  return unwrapItems(await apiClient.get<ListResponse<SyncJobItem>>("/data-sync/jobs"));
}

export async function fetchSyncRuns(limit = 20) {
  return unwrapItems(await apiClient.get<ListResponse<SyncRunItem>>(`/data-sync/runs?limit=${limit}`));
}

export function fetchSyncCoverage() {
  return apiClient.get<SyncCoverage>("/data-sync/coverage");
}

export function fetchDataUsage() {
  return apiClient.get<DataUsageResponse>("/data-sync/usage");
}

export function fetchDataHealth() {
  return apiClient.get<DataHealth>("/data-sync/health");
}

export function runSyncJob(jobId: string, params: Record<string, unknown> = {}) {
  return apiClient.post<SyncRunItem>(`/data-sync/jobs/${encodeURIComponent(jobId)}/run`, params);
}

export function runAllSyncJobs(
  payload: { profile?: "core" | "all"; job_ids?: string[]; params?: Record<string, unknown> } = {},
) {
  return apiClient.post<SyncBatchStatus>("/data-sync/batches/run-all", payload);
}

// ── Batch schedules (unified incremental sync slots) ──

export function fetchSyncSchedules() {
  return apiClient.get<BatchSchedule[]>("/data-sync/schedules");
}

export function createSyncSchedule(payload: Partial<BatchSchedule>) {
  return apiClient.post<BatchSchedule>("/data-sync/schedules", payload);
}

export function updateSyncSchedule(id: string, payload: Partial<BatchSchedule>) {
  return apiClient.patch<BatchSchedule>(`/data-sync/schedules/${encodeURIComponent(id)}`, payload);
}

export function deleteSyncSchedule(id: string) {
  return apiClient.del<{ id: string }>(`/data-sync/schedules/${encodeURIComponent(id)}`);
}

export function runSyncSchedule(id: string) {
  return apiClient.post<SyncBatchStatus>(`/data-sync/schedules/${encodeURIComponent(id)}/run`);
}

export async function fetchLatestSyncBatch() {
  const response = await authFetch("/data-sync/batches/latest");
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`);
  }
  const body = await response.json();
  if (!body.success) {
    throw new Error(body.error?.message ?? "同步批次状态读取失败");
  }
  return (body.data ?? null) as SyncBatchStatus | null;
}

export function fetchSyncBatch(batchId: string) {
  return apiClient.get<SyncBatchStatus>(`/data-sync/batches/${encodeURIComponent(batchId)}`);
}

export function fetchLimitUpEvidenceImportStatus() {
  return apiClient.get<LimitUpEvidenceImportStatus>(
    "/data-sync/imports/limit-up-evidence/status",
  );
}

export function importLimitUpEvidenceFromTushare(payload: {
  dataset: LimitUpEvidenceDataset;
  start_date: string;
  end_date: string;
  dry_run: boolean;
  max_dates: number;
  only_missing: boolean;
}) {
  return apiClient.post<LimitUpEvidenceImportResult>(
    "/data-sync/imports/limit-up-evidence/tushare",
    payload,
  );
}

export function startLimitUpThsEvidenceImport(payload: {
  max_dates?: number;
  only_missing?: boolean;
} = {}) {
  return apiClient.post<SyncBatchStatus>(
    "/data-sync/imports/limit-up-evidence/ths/start",
    payload,
  );
}

export function fetchLimitUpThsEvidenceBatch(batchId: string) {
  return apiClient.get<SyncBatchStatus>(
    `/data-sync/imports/limit-up-evidence/ths/batches/${encodeURIComponent(batchId)}`,
  );
}

export function fetchLimitUpMembershipImportStatus() {
  return apiClient.get<LimitUpMembershipImportStatus>(
    "/data-sync/imports/limit-up-memberships/status",
  );
}

export function importLimitUpMembershipsFromTushare(payload: LimitUpMembershipImportPayload) {
  return apiClient.post<LimitUpMembershipImportResult>(
    "/data-sync/imports/limit-up-memberships/tushare",
    payload,
  );
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
  message?: string;
}

export interface SyncRunItem {
  id?: string | number;
  run_id?: string | number;
  job_id: string;
  status: string;
  params?: Record<string, unknown>;
  started_at: string;
  finished_at?: string | null;
  rows_read: number;
  rows_written: number;
  message?: string | null;
  error?: string | null;
  error_type?: string | null;
}

export interface DataUsageCapability {
  name: string;
  table: string;
  description: string;
  status: string;
  count: number;
  message?: string;
}

export interface DataUsageResponse {
  capabilities: DataUsageCapability[];
  coverage: Record<string, { count: number; last_updated?: string }>;
}

export interface SyncBatchJobStatus {
  job_id: string;
  status: "pending" | "running" | "succeeded" | "failed" | string;
  started_at?: string | null;
  finished_at?: string | null;
  rows_read: number;
  rows_written: number;
  progress_current?: number;
  progress_total?: number;
  progress_pct?: number;
  stage?: string;
  current_label?: string;
  sample_items?: SyncProgressSample[];
  message?: string;
  run_id?: string | number | null;
  error_type?: string;
}

export type SyncProgressSample = Record<string, string | number | boolean | string[] | null | undefined>;

export interface SyncBatchStatus {
  id: string;
  profile: "core" | "all" | string;
  source?: string;
  schedule_id?: string | null;
  concurrency?: number;
  status: "running" | "succeeded" | "failed" | string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  current_job_id?: string | null;
  total_jobs: number;
  completed_jobs: number;
  succeeded_jobs: number;
  failed_jobs: number;
  rows_read: number;
  rows_written: number;
  progress_pct: number;
  message?: string;
  jobs: SyncBatchJobStatus[];
}

/** A unified incremental sync slot (replaces per-job crons). */
export interface BatchSchedule {
  id: string;
  name: string;
  cron: string;
  action?: "sync" | "limit_up_live_scan" | "limit_up_concept_scan" | string;
  job_ids: string[];
  enabled: boolean;
  concurrency: number;
  last_status?: string | null;
  last_started_at?: string | null;
  last_finished_at?: string | null;
  last_message?: string | null;
}

export type DataHealthSeverity = "fresh" | "stale" | "empty" | "future" | "unknown" | string;
export type DataHealthLevel = "green" | "yellow" | "red" | string;

export interface DataHealthJob {
  job_id: string;
  name: string;
  cadence: string;
  category: string;
  is_stale: boolean;
  severity: DataHealthSeverity;
  local_latest?: string | null;
  staleness_days: number;
  reason: string;
  recommended: boolean;
}

export interface DataHealthCategory {
  key: string;
  label: string;
  health: DataHealthLevel;
  jobs: DataHealthJob[];
}

export interface DataHealth {
  generated_at: string;
  overall: {
    health: DataHealthLevel;
    summary: string;
    is_empty_database: boolean;
    empty_core_tables: string[];
    stale_count: number;
    fresh_count: number;
    recommended_count: number;
  };
  market_context: {
    now: string;
    latest_trade_date?: string | null;
    latest_daily_trade_date?: string | null;
    latest_complete_trade_date?: string | null;
    latest_trade_date_symbol_count?: number | null;
    min_complete_daily_symbol_count?: number;
    is_disclosure_season: boolean;
    trade_calendar_source: string;
  };
  categories: DataHealthCategory[];
  recommended: {
    job_ids: string[];
    count: number;
    rationale: string;
  };
  bootstrap: {
    needed: boolean;
    core_profile_job_ids: string[];
    message: string | null;
  };
}

export type LimitUpEvidenceDataset = "events" | "auction";

export interface LimitUpEvidenceCoverage {
  start?: string | null;
  end?: string | null;
  trade_days?: number;
  strict_trade_days?: number;
  rows?: number;
  strict_rows?: number;
  mode?: string;
}

export interface LimitUpEvidenceDatasetStatus {
  label: string;
  api_name: string;
  provider_start: string;
  minimum_coverage_pct: number;
  coverage: LimitUpEvidenceCoverage;
}

export interface LimitUpEvidenceImportStatus {
  status: string;
  provider: {
    id: "tushare";
    configured: boolean;
    api_url: string;
    token_exposed: false;
  };
  ths_provider?: {
    id: "ths";
    configured: boolean;
    history_trade_days: number;
    minimum_coverage_pct: number;
    pools: string[];
  };
  datasets: Record<LimitUpEvidenceDataset, LimitUpEvidenceDatasetStatus>;
  limitations: string[];
}

export interface LimitUpEvidenceDateResult {
  trade_date: string;
  status: string;
  reason?: string;
  rows_read?: number;
  rows_accepted?: number;
  rows_written?: number;
  skipped_count?: number;
  error_count?: number;
  expected_count?: number;
  covered_count?: number;
  coverage_pct?: number;
  missing_symbols?: string[];
}

export interface LimitUpEvidenceImportResult {
  status: string;
  dataset: LimitUpEvidenceDataset;
  provider: string;
  dry_run: boolean;
  message?: string;
  requested_start?: string;
  requested_end?: string;
  candidate_date_count?: number;
  date_count: number;
  accepted_date_count?: number;
  provider_error_count?: number;
  rows_read: number;
  rows_accepted?: number;
  rows_written: number;
  date_results: LimitUpEvidenceDateResult[];
  errors: string[];
}

export interface LimitUpMembershipCoverage extends LimitUpEvidenceCoverage {
  raw_start?: string | null;
  raw_end?: string | null;
  raw_snapshot_trade_days?: number;
  raw_rows?: number;
  industry_start?: string | null;
  industry_end?: string | null;
  industry_snapshot_trade_days?: number;
  industry_rows?: number;
  concept_start?: string | null;
  concept_end?: string | null;
  concept_snapshot_trade_days?: number;
  concept_rows?: number;
  point_in_time_trade_days?: number;
  minimum_daily_symbols?: number;
  minimum_coverage_pct?: number;
}

export interface LimitUpMembershipImportStatus {
  status: string;
  provider: {
    id: "tushare";
    configured: boolean;
    api_url: string;
    token_exposed: false;
    apis: string[];
  };
  dataset: {
    label: string;
    minimum_coverage_pct: number;
    coverage: LimitUpMembershipCoverage;
  };
  limitations: string[];
}

export interface LimitUpMembershipImportPayload {
  start_date: string;
  end_date: string;
  dry_run: boolean;
  max_dates: number;
  only_missing: boolean;
}

export interface LimitUpMembershipDateResult extends LimitUpEvidenceDateResult {
  conflict_count?: number;
}

export interface LimitUpMembershipConflict {
  trade_date: string;
  vt_symbol: string;
  candidate_sector_ids: string[];
  selected_sector_id: string;
}

export interface LimitUpMembershipImportResult {
  status: string;
  dataset: "industry_memberships";
  provider: string;
  dry_run: boolean;
  message?: string;
  requested_start?: string;
  requested_end?: string;
  candidate_date_count?: number;
  date_count: number;
  accepted_date_count?: number;
  rows_read: number;
  rows_accepted?: number;
  expanded_rows?: number;
  rows_written: number;
  skipped_count?: number;
  duplicate_count?: number;
  conflict_count?: number;
  conflicts?: LimitUpMembershipConflict[];
  date_results: LimitUpMembershipDateResult[];
  errors: string[];
}
