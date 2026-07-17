import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type {
  LimitUpMembershipImportResult,
  LimitUpMembershipImportStatus,
} from "@/api/dataSync";
import { HistoricalMembershipBackfillView } from "./HistoricalMembershipBackfillPanel";

function status(): LimitUpMembershipImportStatus {
  return {
    status: "ready",
    provider: {
      id: "tushare",
      configured: false,
      api_url: "https://api.tushare.pro",
      token_exposed: false,
      apis: ["index_classify", "index_member_all"],
    },
    dataset: {
      label: "申万二级逐日行业成员",
      minimum_coverage_pct: 90,
      coverage: {
        raw_snapshot_trade_days: 28,
        raw_rows: 95_000,
        industry_snapshot_trade_days: 12,
        industry_rows: 40_800,
        concept_snapshot_trade_days: 28,
        concept_rows: 54_200,
        point_in_time_trade_days: 10,
        rows: 34_000,
        minimum_daily_symbols: 3_000,
        minimum_coverage_pct: 90,
      },
    },
    limitations: ["覆盖不足90%的日期整日拒绝写入，旧行业快照保持不变。"],
  };
}

function result(): LimitUpMembershipImportResult {
  return {
    status: "partial",
    dataset: "industry_memberships",
    provider: "tushare",
    dry_run: false,
    date_count: 2,
    accepted_date_count: 1,
    rows_read: 3_500,
    rows_accepted: 3_450,
    expanded_rows: 6_800,
    rows_written: 3_410,
    conflict_count: 2,
    date_results: [
      {
        trade_date: "2024-01-15",
        status: "ready",
        rows_accepted: 3_410,
        rows_written: 3_410,
        expected_count: 3_400,
        covered_count: 3_380,
        coverage_pct: 99.4118,
      },
      {
        trade_date: "2024-01-16",
        status: "coverage_incomplete",
        rows_accepted: 2_000,
        rows_written: 0,
        expected_count: 3_400,
        covered_count: 2_000,
        coverage_pct: 58.8235,
        reason: "行业覆盖低于90%",
      },
    ],
    errors: [],
  };
}

const handlers = {
  onStartDateChange: () => undefined,
  onEndDateChange: () => undefined,
  onMaxDatesChange: () => undefined,
  onDryRunChange: () => undefined,
  onOnlyMissingChange: () => undefined,
  onRunTushare: () => undefined,
};

describe("HistoricalMembershipBackfillView", () => {
  it("shows separate raw, industry, concept and qualified coverage", () => {
    const html = renderToStaticMarkup(
      <HistoricalMembershipBackfillView
        {...handlers}
        status={status()}
        result={undefined}
        startDate="2024-01-15"
        endDate="2026-07-10"
        maxDates={20}
        dryRun
        onlyMissing
        isRunning={false}
      />,
    );

    expect(html).toContain("逐日行业成员");
    expect(html).toContain("Tushare 未配置");
    expect(html).toContain("原始快照");
    expect(html).toContain("28 日");
    expect(html).toContain("行业快照");
    expect(html).toContain("12 日");
    expect(html).toContain("概念快照");
    expect(html).toContain("门禁合格");
    expect(html).toContain("10 日");
    expect(html).toContain("仅缺失或覆盖不足日期");
    expect(html).not.toContain("区间 CSV 文件");
    expect(html).not.toContain("下载模板");
  });

  it("shows per-date audit without treating rejected dates as writes", () => {
    const html = renderToStaticMarkup(
      <HistoricalMembershipBackfillView
        {...handlers}
        status={status()}
        result={result()}
        startDate="2024-01-15"
        endDate="2024-01-16"
        maxDates={20}
        dryRun={false}
        onlyMissing={false}
        isRunning={false}
      />,
    );

    expect(html).toContain("逐日成员审计");
    expect(html).toContain("冲突 2");
    expect(html).toContain("2024-01-15");
    expect(html).toContain("3380 / 3400");
    expect(html).toContain("写入 3410");
    expect(html).toContain("2024-01-16");
    expect(html).toContain("2000 / 3400");
    expect(html).toContain("覆盖不足");
    expect(html).toContain("未写入");
  });
});
