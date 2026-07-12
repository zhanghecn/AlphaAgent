import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type {
  LimitUpEvidenceImportResult,
  LimitUpEvidenceImportStatus,
  SyncBatchStatus,
} from "@/api/dataSync";
import { LimitUpEvidenceBackfillView } from "./LimitUpEvidenceBackfillPanel";

function status(): LimitUpEvidenceImportStatus {
  return {
    status: "ready",
    provider: {
      id: "tushare",
      configured: false,
      api_url: "https://api.tushare.pro",
      token_exposed: false,
    },
    ths_provider: {
      id: "ths",
      configured: true,
      history_trade_days: 252,
      minimum_coverage_pct: 90,
      pools: ["limit_up_pool", "open_limit_pool"],
    },
    datasets: {
      events: {
        label: "涨停/炸板路径",
        api_name: "limit_list_d",
        provider_start: "2020-01-01",
        minimum_coverage_pct: 90,
        coverage: { start: "2026-06-12", end: "2026-07-10", trade_days: 22, rows: 6044 },
      },
      auction: {
        label: "开盘集合竞价",
        api_name: "stk_auction",
        provider_start: "2025-01-01",
        minimum_coverage_pct: 95,
        coverage: { trade_days: 0, strict_trade_days: 0, rows: 0 },
      },
    },
    csv_import_available: true,
    limitations: ["Tushare竞价没有未匹配量，只能形成部分竞价证据。"],
  };
}

function result(): LimitUpEvidenceImportResult {
  return {
    status: "partial",
    dataset: "events",
    provider: "csv",
    dry_run: false,
    date_count: 2,
    accepted_date_count: 1,
    rows_read: 132,
    rows_accepted: 128,
    rows_written: 75,
    provider_error_count: 0,
    errors: ["row 4: invalid ts_code"],
    date_results: [
      {
        trade_date: "2026-07-09",
        status: "ready",
        rows_read: 75,
        rows_accepted: 75,
        rows_written: 75,
        expected_count: 74,
        covered_count: 74,
        coverage_pct: 100,
      },
      {
        trade_date: "2026-07-10",
        status: "coverage_incomplete",
        rows_read: 57,
        rows_accepted: 53,
        rows_written: 0,
        expected_count: 74,
        covered_count: 53,
        coverage_pct: 71.6216,
        missing_symbols: ["600001.SSE"],
      },
    ],
  };
}

function thsBatch(): SyncBatchStatus {
  return {
    id: "ths-batch-1",
    profile: "custom",
    status: "running",
    created_at: "2026-07-12T02:00:00Z",
    total_jobs: 1,
    completed_jobs: 0,
    succeeded_jobs: 0,
    failed_jobs: 0,
    rows_read: 1320,
    rows_written: 1200,
    progress_pct: 46.03,
    jobs: [
      {
        job_id: "sync_limit_up_ths_evidence",
        status: "running",
        rows_read: 1320,
        rows_written: 1200,
        progress_current: 110,
        progress_total: 239,
        progress_pct: 46.03,
        stage: "审计并写入同花顺证据",
        current_label: "2025-12-11 · 通过",
      },
    ],
  };
}

describe("LimitUpEvidenceBackfillView", () => {
  it("keeps CSV available when Tushare is not configured", () => {
    const html = renderToStaticMarkup(
      <LimitUpEvidenceBackfillView
        status={status()}
        result={undefined}
        dataset="events"
        startDate="2024-01-15"
        endDate="2026-07-10"
        maxDates={20}
        dryRun
        onlyMissing
        fileName=""
        isRunning={false}
        thsBatch={undefined}
        onDatasetChange={() => undefined}
        onStartDateChange={() => undefined}
        onEndDateChange={() => undefined}
        onMaxDatesChange={() => undefined}
        onDryRunChange={() => undefined}
        onOnlyMissingChange={() => undefined}
        onRunTushare={() => undefined}
        onRunThs={() => undefined}
        onFileChange={() => undefined}
        onRunCsv={() => undefined}
        onDownloadTemplate={() => undefined}
      />,
    );

    expect(html).toContain("打板历史证据");
    expect(html).toContain("Tushare 未配置");
    expect(html).toContain("CSV 文件");
    expect(html).toContain("涨停/炸板路径");
    expect(html).toContain("22 日");
    expect(html).toContain("下载模板");
    expect(html).toContain("同花顺近252日");
    expect(html).toContain("Tushare竞价没有未匹配量");
  });

  it("shows date-level coverage and refuses incomplete dates", () => {
    const html = renderToStaticMarkup(
      <LimitUpEvidenceBackfillView
        status={status()}
        result={result()}
        dataset="events"
        startDate="2024-01-15"
        endDate="2026-07-10"
        maxDates={20}
        dryRun={false}
        onlyMissing
        fileName="limit_list_d.csv"
        isRunning={false}
        thsBatch={undefined}
        onDatasetChange={() => undefined}
        onStartDateChange={() => undefined}
        onEndDateChange={() => undefined}
        onMaxDatesChange={() => undefined}
        onDryRunChange={() => undefined}
        onOnlyMissingChange={() => undefined}
        onRunTushare={() => undefined}
        onRunThs={() => undefined}
        onFileChange={() => undefined}
        onRunCsv={() => undefined}
        onDownloadTemplate={() => undefined}
      />,
    );

    expect(html).toContain("逐日导入审计");
    expect(html).toContain("2026-07-09");
    expect(html).toContain("74 / 74");
    expect(html).toContain("写入 75");
    expect(html).toContain("2026-07-10");
    expect(html).toContain("53 / 74");
    expect(html).toContain("覆盖不足");
    expect(html).toContain("未写入");
    expect(html).toContain("600001.SSE");
  });

  it("shows the background Tonghuashun batch progress", () => {
    const html = renderToStaticMarkup(
      <LimitUpEvidenceBackfillView
        status={status()}
        result={undefined}
        dataset="events"
        startDate="2024-01-15"
        endDate="2026-07-10"
        maxDates={20}
        dryRun
        onlyMissing
        fileName=""
        isRunning
        thsBatch={thsBatch()}
        onDatasetChange={() => undefined}
        onStartDateChange={() => undefined}
        onEndDateChange={() => undefined}
        onMaxDatesChange={() => undefined}
        onDryRunChange={() => undefined}
        onOnlyMissingChange={() => undefined}
        onRunTushare={() => undefined}
        onRunThs={() => undefined}
        onFileChange={() => undefined}
        onRunCsv={() => undefined}
        onDownloadTemplate={() => undefined}
      />,
    );

    expect(html).toContain("2025-12-11 · 通过");
    expect(html).toContain("110/239 · 46%");
    expect(html).toContain("width:46.03%");
  });

  it("shows the terminal import message instead of an empty counter", () => {
    const batch = thsBatch();
    batch.status = "succeeded";
    batch.completed_jobs = 1;
    batch.succeeded_jobs = 1;
    batch.rows_written = 0;
    batch.jobs[0] = {
      ...batch.jobs[0],
      status: "succeeded",
      progress_current: 0,
      progress_total: 0,
      progress_pct: 100,
      rows_written: 0,
      current_label: "",
      stage: "完成",
      message: "同花顺近252个交易日证据已覆盖，无缺失日期",
    };
    const html = renderToStaticMarkup(
      <LimitUpEvidenceBackfillView
        status={status()}
        result={undefined}
        dataset="events"
        startDate="2024-01-15"
        endDate="2026-07-10"
        maxDates={20}
        dryRun
        onlyMissing
        fileName=""
        isRunning={false}
        thsBatch={batch}
        onDatasetChange={() => undefined}
        onStartDateChange={() => undefined}
        onEndDateChange={() => undefined}
        onMaxDatesChange={() => undefined}
        onDryRunChange={() => undefined}
        onOnlyMissingChange={() => undefined}
        onRunTushare={() => undefined}
        onRunThs={() => undefined}
        onFileChange={() => undefined}
        onRunCsv={() => undefined}
        onDownloadTemplate={() => undefined}
      />,
    );

    expect(html).toContain("同花顺近252个交易日证据已覆盖，无缺失日期");
    expect(html).toContain("写入 0 · 100%");
  });
});
