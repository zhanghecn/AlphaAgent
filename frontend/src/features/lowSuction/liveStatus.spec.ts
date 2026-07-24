import { describe, expect, it } from "vitest";

import type { LowSuctionStrategyOverview } from "@/api/lowSuction";
import { blockingReasonLabel, deriveLiveStatus, liveRefetchIntervalMs } from "./liveStatus";

function strategyWith(session: Record<string, unknown>): LowSuctionStrategyOverview {
  return { session } as unknown as LowSuctionStrategyOverview;
}

describe("deriveLiveStatus", () => {
  it("surfaces blocked runs with a translated reason instead of silence", () => {
    const status = deriveLiveStatus(
      strategyWith({
        status: "blocked",
        phases: {
          signal_preview: {
            status: "blocked",
            blocking_reasons: ["future_or_outcome_columns_prohibited"],
          },
        },
      }),
    );
    expect(status.tone).toBe("stop");
    expect(status.label).toBe("信号计算受阻");
    expect(status.detail).toBe("输入校验未通过（防未来函数守护）");
  });

  it("joins multiple blocking reasons and falls back to the raw code", () => {
    const status = deriveLiveStatus(
      strategyWith({
        status: "blocked",
        phases: {
          signal_1450: {
            status: "blocked",
            blocking_reasons: ["d_minus_one_top3_missing", "some_unknown_code"],
          },
        },
      }),
    );
    expect(status.detail).toBe("缺少 D-1 龙头榜数据 · some_unknown_code");
  });

  it("dedupes the same reason raised by multiple phases", () => {
    const status = deriveLiveStatus(
      strategyWith({
        status: "blocked",
        phases: {
          signal_preview: {
            status: "blocked",
            blocking_reasons: ["future_or_outcome_columns_prohibited"],
          },
          signal_1450: {
            status: "blocked",
            blocking_reasons: ["future_or_outcome_columns_prohibited"],
          },
          entry_1455: {
            status: "blocked",
            blocking_reasons: ["signal_capture_not_ready"],
          },
        },
      }),
    );
    expect(status.detail).toBe("输入校验未通过（防未来函数守护） · 尾盘信号尚未冻结");
  });

  it("maps each known session status to a human label and tone", () => {
    const cases: Array<[string, string, string]> = [
      ["paper_account_active", "go", "纸面买入已记录"],
      ["signal_frozen", "go", "尾盘信号已确认"],
      ["preview_ready", "info", "盘中预警已更新"],
      ["awaiting_signal_window", "wait", "等待扫描窗口"],
      ["not_run", "muted", "今日尚未计算"],
      ["market_closed", "muted", "休市"],
    ];
    for (const [value, tone, label] of cases) {
      const status = deriveLiveStatus(strategyWith({ status: value }));
      expect(status.tone, value).toBe(tone);
      expect(status.label, value).toBe(label);
    }
  });

  it("never leaks a raw english enum for unknown statuses", () => {
    const status = deriveLiveStatus(strategyWith({ status: "brand_new_status" }));
    expect(status.label).toBe("状态未知");
    expect(status.tone).toBe("muted");
  });
});

describe("blockingReasonLabel", () => {
  it("translates known codes", () => {
    expect(blockingReasonLabel("intraday_stock_quotes_stale")).toBe("盘中行情快照过期");
    expect(blockingReasonLabel("signal_capture_not_ready")).toBe("尾盘信号尚未冻结");
  });

  it("falls back to the raw code for unknown reasons", () => {
    expect(blockingReasonLabel("mystery_reason")).toBe("mystery_reason");
  });
});

describe("liveRefetchIntervalMs", () => {
  it("uses the backend auto refresh cadence when present", () => {
    expect(liveRefetchIntervalMs(strategyWith({ auto_refresh_seconds: 830 }))).toBe(830_000);
    expect(liveRefetchIntervalMs(strategyWith({ auto_refresh_seconds: 30 }))).toBe(30_000);
  });

  it("falls back to 60 seconds when missing or invalid", () => {
    expect(liveRefetchIntervalMs(strategyWith({}))).toBe(60_000);
    expect(liveRefetchIntervalMs(strategyWith({ auto_refresh_seconds: 0 }))).toBe(60_000);
    expect(liveRefetchIntervalMs(strategyWith({ auto_refresh_seconds: -5 }))).toBe(60_000);
  });
});
