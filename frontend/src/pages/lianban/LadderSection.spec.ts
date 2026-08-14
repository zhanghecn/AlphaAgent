import { describe, expect, it } from "vitest";

import type { LadderStock, LadderTier, LianbanReview } from "@/api/lianban";
import {
  COLLAPSED_STOCK_COUNT,
  formatTodayRate,
  isEarlySeal,
  isTierCollapsible,
  ladderSourceBadge,
  promotionRateFor,
  relayTierLabel,
  reverseBadgeText,
  shortSealTime,
  sortTiersDesc,
  todayPromotionText,
  tomorrowPromotionText,
  visibleStocks,
} from "./LadderSection";

type Promotion = NonNullable<LianbanReview["promotion"]>;
type ByStreakRow = Promotion["by_streak"][number];

function makePromotion(byStreak: ByStreakRow[]): Promotion {
  return {
    trade_date: "2026-08-13",
    lookback_days: 250,
    sample_start: "2025-08-14",
    sample_end: "2026-08-13",
    by_streak: byStreak,
    first_board_today: { base: 0, promoted: 0, rate: null },
    first_board_mean: null,
    relay_5d: [],
  };
}

/** 2026-08-13 实测口径：1-5 板历史晋级率。 */
function makeRealPromotion(): Promotion {
  return makePromotion([
    { streak: 1, samples: 800, promoted: 121, rate: 0.151 },
    { streak: 2, samples: 200, promoted: 61, rate: 0.306 },
    { streak: 3, samples: 80, promoted: 35, rate: 0.443 },
    { streak: 4, samples: 40, promoted: 16, rate: 0.41 },
    { streak: 5, samples: 20, promoted: 9, rate: 0.451 },
    { streak: 6, samples: 8, promoted: 3, rate: null },
    { streak: 7, samples: 3, promoted: 1, rate: null },
    { streak: "8+", samples: 2, promoted: 1, rate: 0.5 },
  ]);
}

function makeStock(overrides: Partial<LadderStock> = {}): LadderStock {
  return {
    vt_symbol: "601279.SSE",
    name: "秦安股份",
    limit_up_count: 5,
    first_limit_time: "09:25:03",
    last_limit_time: "09:25:03",
    limit_amount: null,
    break_count: 0,
    limit_stat_days: null,
    limit_stat_boards: null,
    is_reverse: null,
    industry: "汽车零部",
    concepts: [],
    close_price: null,
    change_pct: null,
    is_one_word: null,
    is_st: null,
    board: null,
    ...overrides,
  };
}

function makeTier(
  streak: number,
  stockCount = 0,
  todayPromotion: LadderTier["today_promotion"] = null,
): LadderTier {
  const stocks = Array.from({ length: stockCount }, (_, index) =>
    makeStock({ vt_symbol: `6000${String(index).padStart(2, "0")}.SSE`, name: `股${index}` }),
  );
  return { streak, count: stockCount, today_promotion: todayPromotion, stocks };
}

describe("promotionRateFor（明日晋级率查表）", () => {
  it("matches numeric streak keys 1-7", () => {
    const promotion = makeRealPromotion();
    expect(promotionRateFor(promotion, 1)).toBe(0.151);
    expect(promotionRateFor(promotion, 5)).toBe(0.451);
  });

  it("routes streak >= 8 to the merged \"8+\" bucket", () => {
    const promotion = makeRealPromotion();
    expect(promotionRateFor(promotion, 8)).toBe(0.5);
    expect(promotionRateFor(promotion, 9)).toBe(0.5);
    expect(promotionRateFor(promotion, 13)).toBe(0.5);
  });

  it("tolerates backend serializing numeric streak as string", () => {
    const promotion = makePromotion([
      { streak: "5", samples: 20, promoted: 9, rate: 0.451 },
    ]);
    expect(promotionRateFor(promotion, 5)).toBe(0.451);
  });

  it("returns null for a missing tier, a null rate, or null promotion", () => {
    const promotion = makeRealPromotion();
    expect(promotionRateFor(promotion, 6)).toBeNull(); // rate 本身为 null
    expect(promotionRateFor(makePromotion([]), 3)).toBeNull(); // 档位缺失
    expect(promotionRateFor(null, 3)).toBeNull();
  });
});

describe("tomorrowPromotionText", () => {
  it("formats the historical rate with one decimal", () => {
    expect(tomorrowPromotionText(makeRealPromotion(), 1)).toBe("明日晋级率 ≈15.1%");
    expect(tomorrowPromotionText(makeRealPromotion(), 4)).toBe("明日晋级率 ≈41.0%");
  });

  it("degrades to -- when the rate is unavailable", () => {
    expect(tomorrowPromotionText(makeRealPromotion(), 6)).toBe("明日晋级率 --");
    expect(tomorrowPromotionText(null, 2)).toBe("明日晋级率 --");
  });
});

describe("reverseBadgeText（反包徽标）", () => {
  it("builds 反·N天M板 when reverse with full stats", () => {
    expect(
      reverseBadgeText(makeStock({ is_reverse: true, limit_stat_days: 13, limit_stat_boards: 9 })),
    ).toBe("反·13天9板");
  });

  it("returns null when not a reverse board", () => {
    expect(reverseBadgeText(makeStock({ is_reverse: false, limit_stat_days: 13, limit_stat_boards: 9 }))).toBeNull();
    expect(reverseBadgeText(makeStock({ is_reverse: null }))).toBeNull();
  });

  it("returns null when reverse stats are incomplete", () => {
    expect(reverseBadgeText(makeStock({ is_reverse: true, limit_stat_days: null, limit_stat_boards: 9 }))).toBeNull();
    expect(reverseBadgeText(makeStock({ is_reverse: true, limit_stat_days: 13, limit_stat_boards: null }))).toBeNull();
  });
});

describe("isEarlySeal（早盘强势封板，10:00:00 含）", () => {
  it("marks times at or before the cutoff as early", () => {
    expect(isEarlySeal("09:25:00")).toBe(true);
    expect(isEarlySeal("10:00:00")).toBe(true);
  });

  it("marks later times as not early", () => {
    expect(isEarlySeal("10:00:01")).toBe(false);
    expect(isEarlySeal("13:00:00")).toBe(false);
  });

  it("handles null/undefined (rebuild 口径无盘口时间)", () => {
    expect(isEarlySeal(null)).toBe(false);
    expect(isEarlySeal(undefined)).toBe(false);
  });
});

describe("todayPromotionText（今日 X 进 Y）", () => {
  it("formats 2板档 as 今日1进2 with integer percent", () => {
    const tier = makeTier(2, 13, { base: 37, promoted: 6, rate: 0.16 });
    expect(todayPromotionText(tier)).toBe("今日1进2 16%");
  });

  it("rounds the rate to integer percent", () => {
    const tier = makeTier(4, 6, { base: 7, promoted: 6, rate: 0.857 });
    expect(todayPromotionText(tier)).toBe("今日3进4 86%");
  });

  it("returns null for the 1板档（规格：1板档没有今日 X 进 Y）", () => {
    const tier = makeTier(1, 37, { base: 100, promoted: 37, rate: 0.37 });
    expect(todayPromotionText(tier)).toBeNull();
  });

  it("degrades to -- when rate or today_promotion is null", () => {
    expect(todayPromotionText(makeTier(2, 13, { base: 0, promoted: 0, rate: null }))).toBe("今日1进2 --");
    expect(todayPromotionText(makeTier(5, 1, null))).toBe("今日4进5 --");
  });
});

describe("formatTodayRate", () => {
  it("converts a 0-1 ratio to a rounded integer percent", () => {
    expect(formatTodayRate(0.16)).toBe("16%");
    expect(formatTodayRate(0.306)).toBe("31%");
    expect(formatTodayRate(1)).toBe("100%");
    expect(formatTodayRate(0)).toBe("0%");
  });

  it("handles null and non-finite values", () => {
    expect(formatTodayRate(null)).toBe("--");
    expect(formatTodayRate(undefined)).toBe("--");
    expect(formatTodayRate(Number.NaN)).toBe("--");
  });
});

describe("折叠逻辑（1板档默认折叠）", () => {
  it("visibleStocks truncates to COLLAPSED_STOCK_COUNT when collapsed", () => {
    const tier = makeTier(1, 37);
    expect(visibleStocks(tier, false)).toHaveLength(COLLAPSED_STOCK_COUNT);
    expect(COLLAPSED_STOCK_COUNT).toBe(20);
  });

  it("visibleStocks returns everything when expanded", () => {
    const tier = makeTier(1, 37);
    expect(visibleStocks(tier, true)).toHaveLength(37);
  });

  it("does not truncate tiers at or below the threshold", () => {
    expect(visibleStocks(makeTier(2, 13), false)).toHaveLength(13);
    expect(visibleStocks(makeTier(1, 20), false)).toHaveLength(20);
  });

  it("isTierCollapsible only above the threshold（不足 20 不显示按钮）", () => {
    expect(isTierCollapsible(37)).toBe(true);
    expect(isTierCollapsible(21)).toBe(true);
    expect(isTierCollapsible(20)).toBe(false);
    expect(isTierCollapsible(13)).toBe(false);
  });
});

describe("sortTiersDesc（档位 streak 降序）", () => {
  it("sorts tiers by streak descending without mutating the input", () => {
    const input = [makeTier(1, 37), makeTier(4, 6), makeTier(2, 13), makeTier(5, 1)];
    const sorted = sortTiersDesc(input);
    expect(sorted.map((tier) => tier.streak)).toEqual([5, 4, 2, 1]);
    expect(input.map((tier) => tier.streak)).toEqual([1, 4, 2, 5]);
  });
});

describe("ladderSourceBadge（数据源口径徽标）", () => {
  it("labels each ladder source", () => {
    expect(ladderSourceBadge("pool_archive").label).toBe("东财盘口");
    expect(ladderSourceBadge("daily_rebuild").label).toBe("日线口径");
    expect(ladderSourceBadge("live_pool").label).toBe("实时盘口");
  });

  it("explains the rebuild caveat via title", () => {
    expect(ladderSourceBadge("daily_rebuild").title).toContain("盘口字段");
  });
});

describe("relay 小助手", () => {
  it("relayTierLabel appends 板", () => {
    expect(relayTierLabel("6+")).toBe("6+板");
    expect(relayTierLabel("1")).toBe("1板");
  });

  it("shortSealTime trims HH:MM:SS to HH:MM and passes null through", () => {
    expect(shortSealTime("09:25:03")).toBe("09:25");
    expect(shortSealTime("13:00:00")).toBe("13:00");
    expect(shortSealTime(null)).toBeNull();
  });
});
