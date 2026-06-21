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

export function fetchTailWorkflowStatus() {
  return apiClient.get<TailWorkflowStatus>("/data-sync/tail-workflow");
}

export function runTailPrepare() {
  return apiClient.post<SyncBatchStatus>("/data-sync/tail-workflow/prepare");
}

export function fetchDataUsage() {
  return apiClient.get<DataUsageResponse>("/data-sync/usage");
}

export function runSyncJob(jobId: string, params: Record<string, unknown> = {}) {
  return apiClient.post<SyncRunItem>(`/data-sync/jobs/${encodeURIComponent(jobId)}/run`, params);
}

export function runAllSyncJobs(payload: { profile?: "core" | "all"; params?: Record<string, unknown> } = {}) {
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

export function importMinuteBarsCsv(payload: {
  csv_text?: string;
  file_path?: string;
  interval?: string;
  source?: string;
  dry_run?: boolean;
}) {
  return apiClient.post<MinuteBarsImportResult>("/data-sync/imports/minute-bars", payload);
}

export function auditMinuteGapCsv(payload: {
  backtest_id?: number | string;
  gap_csv_text?: string;
  file_path?: string;
  interval?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
  min_tail_bars?: number;
}) {
  return apiClient.post<MinuteGapAuditResult>("/data-sync/imports/minute-bars/audit-gaps", payload);
}

export function importMinuteGapsFromTushare(payload: {
  backtest_id?: number | string;
  gap_csv_text?: string;
  gap_file_path?: string;
  interval?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
  dry_run?: boolean;
  max_gaps?: number;
}) {
  return apiClient.post<MinuteGapProviderImportResult>("/data-sync/imports/minute-bars/tushare-gaps", payload);
}

export function importMinuteGapsFromTdx(payload: {
  backtest_id?: number | string;
  gap_csv_text?: string;
  gap_file_path?: string;
  interval?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
  dry_run?: boolean;
  max_gaps?: number;
  max_pages_per_symbol?: number;
  timeout_seconds?: number;
}) {
  return apiClient.post<MinuteGapProviderImportResult>("/data-sync/imports/minute-bars/tdx-gaps", payload);
}

export function importMinuteGapsFromAkshare(payload: {
  backtest_id?: number | string;
  gap_csv_text?: string;
  gap_file_path?: string;
  interval?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
  dry_run?: boolean;
  max_gaps?: number;
}) {
  return apiClient.post<MinuteGapProviderImportResult>("/data-sync/imports/minute-bars/akshare-gaps", payload);
}

export function fetchMinuteGapVendorManifest(payload: {
  backtest_id?: number | string;
  gap_csv_text?: string;
  gap_file_path?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
  sample_limit?: number;
}) {
  return apiClient.post<MinuteGapVendorManifest>("/data-sync/imports/minute-bars/vendor-manifest", payload);
}

export async function fetchMinuteGapVendorManifestCsv(payload: {
  backtest_id?: number | string;
  gap_csv_text?: string;
  gap_file_path?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
}) {
  const response = await authFetch("/data-sync/imports/minute-bars/vendor-manifest.csv", {
    method: "POST",
    headers: { Accept: "text/csv" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`);
  }
  return response.text();
}

export async function fetchMinuteGapImportTemplate(payload: {
  backtest_id?: number | string;
  gap_csv_text?: string;
  sample_limit?: number;
}) {
  const response = await authFetch("/data-sync/imports/minute-bars/gap-template.csv", {
    method: "POST",
    headers: { Accept: "text/csv" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`);
  }
  return response.text();
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
  action?: "sync" | "quant_research" | "tail_preview" | string;
  job_ids: string[];
  enabled: boolean;
  concurrency: number;
  last_status?: string | null;
  last_started_at?: string | null;
  last_finished_at?: string | null;
  last_message?: string | null;
}

export interface TailWorkflowStatus {
  status: "ready" | "unavailable" | string;
  daily_bar_latest_date?: string | null;
  daily_bar_latest_complete_date?: string | null;
  daily_bar_updated_at?: string | null;
  intraday_snapshot_updated_at?: string | null;
  intraday_snapshot_trade_time?: string | null;
  minute_latest_date?: string | null;
  minute_latest_time?: string | null;
  candidate_latest_date?: string | null;
  candidate_updated_at?: string | null;
  latest_research_run?: TailResearchRun | null;
  tail_prepare_schedule?: BatchSchedule | null;
  tail_quant_schedule?: BatchSchedule | null;
  eod_schedule?: BatchSchedule | null;
  tail_prepare_ready?: boolean;
  tail_preview?: {
    status?: string;
    trade_date?: string | null;
    data_source?: string | null;
    temporary_bar?: boolean;
    base_daily_date?: string | null;
    cached_trade_date?: string | null;
    cached_generated_at?: string | null;
    cached_recommendation_count?: number;
    cached_total?: number;
    snapshot_updated_at?: string | null;
    latest_intraday_date?: string | null;
    minute_latest_date?: string | null;
    message?: string | null;
  } | null;
  message?: string | null;
}

export interface TailResearchRun {
  id?: string;
  status?: string;
  stage?: string;
  message?: string | null;
  created_at?: string;
  started_at?: string;
  finished_at?: string | null;
  progress_current?: number;
  progress_total?: number;
  progress_pct?: number;
  backtest_id?: number | null;
}

export interface MinuteBarsImportResult {
  status: string;
  interval?: string;
  source?: string;
  dry_run?: boolean;
  rows_read: number;
  rows_written: number;
  rows_skipped: number;
  symbol_count?: number;
  errors?: string[];
  required_columns?: string[];
  file_path?: string;
  message?: string;
}

export interface MinuteGapAuditRow {
  vt_symbol: string;
  trade_date: string;
  reference_date?: string | null;
  ma5?: number | null;
  window?: string;
  minute_bar_count: number;
  required_tail_bars: number;
  missing_reason?: string;
}

export interface MinuteGapAuditResult {
  status: "ready" | "incomplete" | "empty" | "unavailable" | string;
  interval?: string;
  tail_entry_window?: string;
  required_tail_bars?: number;
  rows_read?: number;
  rows_skipped?: number;
  gap_count?: number;
  covered_count?: number;
  missing_count?: number;
  coverage_pct?: number;
  symbol_count?: number;
  date_count?: number;
  missing_symbol_count?: number;
  missing_date_count?: number;
  missing_symbols?: string[];
  missing_dates?: string[];
  covered_examples?: MinuteGapAuditRow[];
  missing_examples?: MinuteGapAuditRow[];
  errors?: string[];
  next_action?: string;
  file_path?: string;
  message?: string;
}

export interface MinuteGapProviderImportResult {
  status: string;
  interval?: string;
  dry_run?: boolean;
  tail_entry_window?: string;
  gap_count?: number;
  processed_gap_count?: number;
  unprocessed_gap_count?: number;
  symbol_count?: number;
  date_count?: number;
  rows_read?: number;
  rows_written?: number;
  empty_request_count?: number;
  remote_rows_scanned?: number;
  preview_covered_gap_count?: number;
  rows_skipped?: number;
  wrong_date_row_count?: number;
  errors?: string[];
  audit_after?: {
    status: string;
    gap_count?: number;
    covered_count?: number;
    missing_count?: number;
    coverage_pct?: number;
  };
  source?: string;
  message?: string;
  note?: string;
}

export interface MinuteGapVendorRow {
  vt_symbol: string;
  symbol: string;
  exchange: string;
  tushare_ts_code: string;
  trade_date: string;
  tail_start: string;
  tail_end: string;
  start_datetime: string;
  end_datetime: string;
  reference_date?: string | null;
  ma5?: number | null;
}

export interface MinuteGapVendorManifest {
  status: string;
  rows_read?: number;
  rows_skipped?: number;
  errors?: string[];
  request_count?: number;
  symbol_count?: number;
  date_count?: number;
  tail_entry_window?: string;
  start_date?: string | null;
  end_date?: string | null;
  symbols?: string[];
  dates?: string[];
  sample_rows?: MinuteGapVendorRow[];
  required_import_columns?: string[];
  provider_notes?: string[];
}
