import { describe, expect, it } from "vitest";

import type { LianbanReview } from "@/api/lianban";
import {
  firstBoardText,
  relayLianbanTiers,
  relayStatusBadge,
  relaySummary,
} from "./RelaySection";

type Relay = LianbanReview["relay"];
type RelayTier = Relay["tiers"][number];
type RelayStock = RelayTier["stocks"][number];
type FirstBoard = Relay["first_board"];

function makeStock(overrides: Partial<RelayStock> = {}): RelayStock {
  return {
    vt_symbol: "600000.SSE",
    name: "测试股",
    today_change_pct: 1.2,
    status: "open",
    today_streak: null,
    ...overrides,
  };
}

function makeTier(prevStreak: number, stocks: RelayStock[]): RelayTier {
  return { prev_streak: prevStreak, stocks };
}

function makeRelay(tiers: RelayTier[], firstBoard?: Partial<FirstBoard>): Relay {
  return {
    tiers,
    first_board: { base: 0, promoted: 0, rate: null, mean: null, ...firstBoard },
  };
}

describe("relaySummary（晋级 x/y 派生）", () => {
  it("counts promoted/total across 连板档（prev_streak>=2，1板档由 first_board 块表达）", () => {
    const relay = makeRelay([
      makeTier(3, [
        makeStock({ status: "promoted", today_streak: 4 }),
        makeStock({ status: "open" }),
        makeStock({ status: "broken" }),
      ]),
      makeTier(2, [makeStock({ status: "promoted", today_streak: 3 })]),
      // 1板档 75 只不计入「连板股今日表现」口径
      makeTier(1, [
        makeStock({ status: "promoted", today_streak: 2 }),
        makeStock({ status: "open" }),
      ]),
    ]);
    expect(relaySummary(relay)).toEqual({ promoted: 2, total: 4 });
  });

  it("handles empty tiers", () => {
    expect(relaySummary(makeRelay([]))).toEqual({ promoted: 0, total: 0 });
  });
});

describe("relayLianbanTiers（连板档过滤 + prev_streak 降序）", () => {
  it("drops the prev_streak=1 tier and sorts descending without mutating", () => {
    const input = [
      makeTier(1, [makeStock()]),
      makeTier(3, [makeStock()]),
      makeTier(2, [makeStock()]),
    ];
    const relay = makeRelay(input);
    const tiers = relayLianbanTiers(relay);
    expect(tiers.map((tier) => tier.prev_streak)).toEqual([3, 2]);
    expect(input.map((tier) => tier.prev_streak)).toEqual([1, 3, 2]);
  });

  it("returns empty when only the 1板档 exists", () => {
    expect(relayLianbanTiers(makeRelay([makeTier(1, [makeStock()])]))).toEqual([]);
  });
});

describe("firstBoardText（首板晋级 1进2 文案）", () => {
  it("combines rate / promoted/base / historical mean（对齐 lianban 口径）", () => {
    expect(firstBoardText({ base: 75, promoted: 12, rate: 0.16, mean: 0.163 })).toBe(
      "首板晋级(1进2) 16%(12/75,历史均值 16.3%)",
    );
  });

  it("omits the mean clause when mean is null", () => {
    expect(firstBoardText({ base: 75, promoted: 12, rate: 0.16, mean: null })).toBe(
      "首板晋级(1进2) 16%(12/75)",
    );
  });

  it("degrades rate to -- when null", () => {
    expect(firstBoardText({ base: 37, promoted: 0, rate: null, mean: 0.151 })).toBe(
      "首板晋级(1进2) --(0/37,历史均值 15.1%)",
    );
  });

  it("returns null for the empty shape or null input（无首板样本不显示该行）", () => {
    expect(firstBoardText({ base: 0, promoted: 0, rate: null, mean: null })).toBeNull();
    expect(firstBoardText(null)).toBeNull();
    expect(firstBoardText(undefined)).toBeNull();
  });
});

describe("relayStatusBadge（状态徽标映射）", () => {
  it("promoted → 晋N板（暖色强势）", () => {
    const badge = relayStatusBadge(makeStock({ status: "promoted", today_streak: 4 }));
    expect(badge?.label).toBe("晋4板");
    expect(badge?.className).toContain("text-rise");
  });

  it("promoted with null today_streak → 晋级（防御降级）", () => {
    expect(relayStatusBadge(makeStock({ status: "promoted", today_streak: null }))?.label).toBe(
      "晋级",
    );
  });

  it("broken → 炸板（冷色走弱）", () => {
    const badge = relayStatusBadge(makeStock({ status: "broken" }));
    expect(badge?.label).toBe("炸板");
    expect(badge?.className).toContain("text-fall");
  });

  it("open → null（行内只显示涨幅）", () => {
    expect(relayStatusBadge(makeStock({ status: "open" }))).toBeNull();
  });
});
