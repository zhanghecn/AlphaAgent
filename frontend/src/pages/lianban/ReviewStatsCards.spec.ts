import { describe, expect, it } from "vitest";

import type { LianbanStats } from "@/api/lianban";
import {
  buildStatCards,
  deltaTone,
  formatGroupedInt,
  formatPctPoint,
  formatRatioPct,
  formatShortDate,
  formatSignedYi,
  formatTemperature,
  formatWanYiAmount,
  highLowLabel,
  riseRatioPercent,
} from "./ReviewStatsCards";

function makeStats(overrides: Partial<LianbanStats> = {}): LianbanStats {
  return {
    limit_up: null,
    limit_up_prev: null,
    lianban: null,
    lianban_prev: null,
    max_streak: null,
    max_streak_prev: null,
    limit_down: null,
    limit_down_prev: null,
    seal_rate: null,
    seal_rate_prev: null,
    broken: null,
    broken_prev: null,
    prev_lu_avg_change: null,
    prev_lu_median_change: null,
    prev_lu_rise_ratio: null,
    sentiment_phase: null,
    sentiment_score: null,
    rise_count: null,
    fall_count: null,
    new_high_63: null,
    new_low_63: null,
    total_amount: null,
    margin_balance: null,
    margin_change: null,
    margin_date: null,
    ...overrides,
  };
}

describe("formatWanYiAmount", () => {
  it("formats 万亿 with two decimals", () => {
    expect(formatWanYiAmount(2.55e12)).toBe("2.55万亿");
    expect(formatWanYiAmount(2.6453e12)).toBe("2.65万亿");
  });

  it("falls back to 亿/万 below 万亿", () => {
    expect(formatWanYiAmount(8.5e11)).toBe("8500亿");
    expect(formatWanYiAmount(9.5e9)).toBe("95亿");
    expect(formatWanYiAmount(5e7)).toBe("5000万");
    expect(formatWanYiAmount(9999)).toBe("9999");
  });

  it("handles null, NaN and zero", () => {
    expect(formatWanYiAmount(null)).toBe("--");
    expect(formatWanYiAmount(Number.NaN)).toBe("--");
    expect(formatWanYiAmount(0)).toBe("0");
  });
});

describe("formatSignedYi", () => {
  it("formats signed 亿 changes", () => {
    expect(formatSignedYi(9.5e9)).toBe("+95亿");
    expect(formatSignedYi(-2.3e9)).toBe("-23亿");
    expect(formatSignedYi(5e6)).toBe("+500万");
  });

  it("formats 万亿 magnitudes with two decimals", () => {
    expect(formatSignedYi(1.2e12)).toBe("+1.20万亿");
    expect(formatSignedYi(-1.2e12)).toBe("-1.20万亿");
  });

  it("handles null and zero", () => {
    expect(formatSignedYi(null)).toBe("--");
    expect(formatSignedYi(0)).toBe("0亿");
  });
});

describe("formatRatioPct (0-1 比率口径)", () => {
  it("converts a ratio to a one-decimal percentage", () => {
    expect(formatRatioPct(0.621)).toBe("62.1%");
    expect(formatRatioPct(0.885)).toBe("88.5%");
    expect(formatRatioPct(0.44)).toBe("44.0%");
    expect(formatRatioPct(1)).toBe("100.0%");
    expect(formatRatioPct(0)).toBe("0.0%");
  });

  it("handles null", () => {
    expect(formatRatioPct(null)).toBe("--");
  });
});

describe("formatPctPoint (百分数数值口径)", () => {
  it("keeps the value as-is with a sign and one decimal", () => {
    expect(formatPctPoint(1.2)).toBe("+1.2%");
    expect(formatPctPoint(-1.5)).toBe("-1.5%");
    expect(formatPctPoint(0)).toBe("0.0%");
  });

  it("handles null", () => {
    expect(formatPctPoint(null)).toBe("--");
  });
});

describe("formatGroupedInt", () => {
  it("groups thousands", () => {
    expect(formatGroupedInt(4091)).toBe("4,091");
    expect(formatGroupedInt(59)).toBe("59");
    expect(formatGroupedInt(0)).toBe("0");
  });

  it("handles null", () => {
    expect(formatGroupedInt(null)).toBe("--");
  });
});

describe("formatShortDate", () => {
  it("trims an ISO date to month-day", () => {
    expect(formatShortDate("2026-08-12")).toBe("08-12");
  });

  it("passes through non-ISO input and placeholder for null", () => {
    expect(formatShortDate("08-12")).toBe("08-12");
    expect(formatShortDate(null)).toBe("--");
  });
});

describe("formatTemperature", () => {
  it("rounds the sentiment score to an integer degree", () => {
    expect(formatTemperature(40)).toBe("40°");
    expect(formatTemperature(40.4)).toBe("40°");
  });
});

describe("deltaTone", () => {
  it("positive polarity: up is red (strong), down is green", () => {
    expect(deltaTone(22, 16, "positive")).toBe("rise");
    expect(deltaTone(59, 92, "positive")).toBe("fall");
  });

  it("inverse polarity (跌停/炸板): up is green (weak), down is red", () => {
    expect(deltaTone(4, 0, "inverse")).toBe("fall");
    expect(deltaTone(12, 36, "inverse")).toBe("rise");
  });

  it("returns null for ties or missing values", () => {
    expect(deltaTone(5, 5, "positive")).toBeNull();
    expect(deltaTone(null, 5, "positive")).toBeNull();
    expect(deltaTone(5, null, "inverse")).toBeNull();
  });
});

describe("riseRatioPercent", () => {
  it("computes the red-ratio from rise/fall counts", () => {
    expect(riseRatioPercent(1100, 4091)).toBe(21);
    expect(riseRatioPercent(1, 3)).toBe(25);
  });

  it("returns null for missing counts or an empty market", () => {
    expect(riseRatioPercent(null, 4091)).toBeNull();
    expect(riseRatioPercent(1100, null)).toBeNull();
    expect(riseRatioPercent(0, 0)).toBeNull();
  });
});

describe("highLowLabel", () => {
  it("compares new highs against new lows", () => {
    expect(highLowLabel(110, 17)).toBe("新高占优");
    expect(highLowLabel(17, 110)).toBe("新低占优");
    expect(highLowLabel(10, 10)).toBe("持平");
  });
});

describe("buildStatCards", () => {
  it("builds 12 cards from a full payload with correct formats and tones", () => {
    const cards = buildStatCards(makeStats({
      limit_up: 59,
      limit_up_prev: 92,
      lianban: 22,
      lianban_prev: 16,
      max_streak: 5,
      max_streak_prev: 7,
      limit_down: 4,
      limit_down_prev: 0,
      seal_rate: 0.621,
      seal_rate_prev: 0.885,
      broken: 36,
      broken_prev: 12,
      prev_lu_avg_change: 1.2,
      prev_lu_median_change: -1.5,
      prev_lu_rise_ratio: 0.44,
      sentiment_phase: "退潮期",
      sentiment_score: 40,
      rise_count: 1100,
      fall_count: 4091,
      new_high_63: 110,
      new_low_63: 17,
      total_amount: 2.55e12,
      margin_balance: 2.65e12,
      margin_change: 9.5e9,
      margin_date: "2026-08-12",
    }));

    expect(cards).toHaveLength(12);
    const byKey = Object.fromEntries(cards.map((card) => [card.key, card]));

    expect(byKey.limit_up).toMatchObject({
      title: "涨停",
      big: "59",
      sub: [{ text: "昨 92", tone: "fall" }],
    });
    expect(byKey.lianban).toMatchObject({
      big: "22",
      sub: [{ text: "昨 16", tone: "rise" }],
    });
    expect(byKey.max_streak).toMatchObject({
      big: "5板",
      sub: [{ text: "昨 7板", tone: "fall" }],
    });
    expect(byKey.limit_down).toMatchObject({
      title: "跌停",
      big: "4",
      sub: [{ text: "昨 0", tone: "fall" }],
    });
    expect(byKey.seal_rate).toMatchObject({
      big: "62.1%",
      sub: [{ text: "昨 88.5%", tone: "fall" }],
    });
    expect(byKey.broken).toMatchObject({
      big: "36",
      sub: [{ text: "昨 12", tone: "fall" }],
    });
    expect(byKey.prev_lu_performance).toMatchObject({
      title: "昨涨停今表现",
      big: "+1.2%",
      bigTone: "rise",
      sub: [
        { text: "中位 -1.5%", tone: "fall" },
        { text: "翻红 44.0%" },
      ],
    });
    expect(byKey.sentiment).toMatchObject({
      big: "退潮期",
      sub: [{ text: "温度 40°" }],
    });
    expect(byKey.rise_fall).toMatchObject({
      big: "1,100/4,091",
      sub: [{ text: "红盘 21%" }],
    });
    expect(byKey.high_low_63).toMatchObject({
      big: "110/17",
      sub: [{ text: "新高占优" }],
    });
    expect(byKey.total_amount).toMatchObject({ big: "2.55万亿", sub: [] });
    expect(byKey.margin_balance).toMatchObject({
      big: "2.65万亿",
      sub: [{ text: "较前日 +95亿", tone: "rise" }, { text: "08-12" }],
    });
  });

  it("degrades to placeholders and drops 昨对比 when stats are null", () => {
    const cards = buildStatCards(makeStats());
    expect(cards).toHaveLength(12);
    for (const card of cards) {
      expect(card.big).toBe("--");
      expect(card.sub).toEqual([]);
    }
  });

  it("omits the 昨对比 part when only prev is missing", () => {
    const cards = buildStatCards(makeStats({ limit_up: 59 }));
    const limitUp = cards.find((card) => card.key === "limit_up");
    expect(limitUp?.big).toBe("59");
    expect(limitUp?.sub).toEqual([]);
  });

  it("keeps the margin date when the change is missing, and vice versa", () => {
    const withDateOnly = buildStatCards(
      makeStats({ margin_balance: 2.65e12, margin_date: "2026-08-12" }),
    ).find((card) => card.key === "margin_balance");
    expect(withDateOnly?.sub).toEqual([{ text: "08-12" }]);

    const withChangeOnly = buildStatCards(
      makeStats({ margin_balance: 2.65e12, margin_change: -2.3e9 }),
    ).find((card) => card.key === "margin_balance");
    expect(withChangeOnly?.sub).toEqual([{ text: "较前日 -23亿", tone: "fall" }]);
  });

  it("shows partial prev-limit-up lines when only some fields exist", () => {
    const card = buildStatCards(makeStats({ prev_lu_rise_ratio: 0.44 })).find(
      (item) => item.key === "prev_lu_performance",
    );
    expect(card?.big).toBe("--");
    expect(card?.sub).toEqual([{ text: "翻红 44.0%" }]);
  });

  it("drops the breadth sub-line when rise/fall counts are incomplete", () => {
    const card = buildStatCards(makeStats({ rise_count: 1100 })).find(
      (item) => item.key === "rise_fall",
    );
    expect(card?.big).toBe("--");
    expect(card?.sub).toEqual([]);
  });
});
