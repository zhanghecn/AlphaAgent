import { describe, expect, it } from "vitest";

import type { LianbanReview } from "@/api/lianban";
import {
  formatHotAsOf,
  HOT_LEADERS_TOP_N,
  hotStreakBadge,
  topHotItems,
  visibleKeywords,
} from "./HotLeadersSection";

type HotItem = LianbanReview["hot_leaders"]["items"][number];

function makeItem(overrides: Partial<HotItem> = {}): HotItem {
  return {
    rank: 1,
    vt_symbol: "600667.SSE",
    name: "太极实业",
    hot_score: 98.5,
    limit_up_count: null,
    change_pct: 4.7,
    keywords: ["存储芯片", "先进封装"],
    ...overrides,
  };
}

describe("hotStreakBadge（连板徽标阈值）", () => {
  it("n>=2 → N板", () => {
    expect(hotStreakBadge(7)).toBe("7板");
    expect(hotStreakBadge(2)).toBe("2板");
  });

  it("n==1 → 首板", () => {
    expect(hotStreakBadge(1)).toBe("首板");
  });

  it("0/null → null（不显示徽标）", () => {
    expect(hotStreakBadge(0)).toBeNull();
    expect(hotStreakBadge(null)).toBeNull();
  });
});

describe("visibleKeywords（关键词截断前 2 个）", () => {
  it("keeps at most two keywords", () => {
    expect(visibleKeywords(["存储芯片", "先进封装", "国企改革"])).toEqual([
      "存储芯片",
      "先进封装",
    ]);
    expect(visibleKeywords(["青蒿素"])).toEqual(["青蒿素"]);
  });

  it("drops empty entries and tolerates null/undefined", () => {
    expect(visibleKeywords(["", "  ", "肝炎概念"])).toEqual(["肝炎概念"]);
    expect(visibleKeywords([])).toEqual([]);
    expect(visibleKeywords(null)).toEqual([]);
    expect(visibleKeywords(undefined)).toEqual([]);
  });
});

describe("topHotItems（rank 升序 + Top10 截断）", () => {
  it("sorts by rank ascending (nulls last) and truncates to Top10, without mutating", () => {
    const items = Array.from({ length: 12 }, (_, index) =>
      makeItem({ rank: 12 - index, name: `股${12 - index}` }),
    );
    const top = topHotItems(items);
    expect(HOT_LEADERS_TOP_N).toBe(10);
    expect(top).toHaveLength(10);
    expect(top[0]?.rank).toBe(1);
    expect(top[9]?.rank).toBe(10);
    expect(items[0]?.rank).toBe(12);
  });

  it("places null ranks after numbered ones", () => {
    const top = topHotItems([
      makeItem({ rank: null, name: "无榜次" }),
      makeItem({ rank: 2, name: "榜二" }),
    ]);
    expect(top.map((item) => item.name)).toEqual(["榜二", "无榜次"]);
  });

  it("keeps short lists intact", () => {
    const items = [makeItem({ rank: 2 }), makeItem({ rank: 1 })];
    expect(topHotItems(items).map((item) => item.rank)).toEqual([1, 2]);
  });
});

describe("formatHotAsOf（人气榜快照时间）", () => {
  it("formats ISO timestamps in Asia/Shanghai as MM-dd HH:mm", () => {
    expect(formatHotAsOf("2026-08-13T06:30:17Z")).toBe("08-13 14:30");
  });

  it("repairs the truncated timezone suffix（后端 rank_time 截断串，按 UTC 解析）", () => {
    // 真实形态：30 字符截断串 "2026-08-13T06:30:17.195234+00:"（尾部时区被截断），
    // new Date() 直解为 Invalid Date → 回退前 19 位 + "Z" 按 UTC 解析。
    expect(formatHotAsOf("2026-08-13T06:30:17.195234+00:")).toBe("08-13 14:30");
  });

  it("returns null for null/empty input（头部省略小字）", () => {
    expect(formatHotAsOf(null)).toBeNull();
    expect(formatHotAsOf("")).toBeNull();
  });

  it("passes fully non-ISO values through verbatim", () => {
    expect(formatHotAsOf("盘中")).toBe("盘中");
  });
});
