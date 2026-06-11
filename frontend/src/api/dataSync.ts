import { apiClient, apiUrl } from "./client";
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

export function fetchMinuteGapVendorManifest(payload: {
  gap_csv_text?: string;
  gap_file_path?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
  sample_limit?: number;
}) {
  return apiClient.post<MinuteGapVendorManifest>("/data-sync/imports/minute-bars/vendor-manifest", payload);
}

export async function fetchMinuteGapVendorManifestCsv(payload: {
  gap_csv_text?: string;
  gap_file_path?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
}) {
  const response = await fetch(apiUrl("/data-sync/imports/minute-bars/vendor-manifest.csv"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/csv" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`请求失败: ${response.status} ${response.statusText}`);
  }
  return response.text();
}

export async function fetchMinuteGapImportTemplate(payload: {
  gap_csv_text: string;
  sample_limit?: number;
}) {
  const response = await fetch(apiUrl("/data-sync/imports/minute-bars/gap-template.csv"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/csv" },
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
