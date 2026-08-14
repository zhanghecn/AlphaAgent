import { describe, expect, it } from "vitest";

import type { LianbanReview } from "@/api/lianban";
import {
  isThemeCollapsible,
  isThemeLeader,
  sortThemeStocks,
  sortThemes,
  THEME_COLLAPSE_COUNT,
  themeStreakText,
  visibleThemes,
} from "./ThemeGroupsSection";

type Theme = LianbanReview["themes"][number];
type ThemeStock = Theme["stocks"][number];

function makeStock(overrides: Partial<ThemeStock> = {}): ThemeStock {
  return {
    vt_symbol: "600000.SSE",
    name: "测试股",
    limit_up_count: 1,
    first_limit_time: "09:36:00",
    is_reverse: null,
    ...overrides,
  };
}

function makeTheme(
  name: string,
  count: number,
  stocks: ThemeStock[] = [],
  kind: Theme["kind"] = "industry",
): Theme {
  return { name, count, kind, leader: null, stocks };
}

describe("sortThemes（count 降序，防御性重排）", () => {
  it("sorts by count desc then name, without mutating the input", () => {
    const input = [makeTheme("汽车零部", 4), makeTheme("医疗服务", 6), makeTheme("物流", 4)];
    const sorted = sortThemes(input);
    expect(sorted.map((theme) => theme.name)).toEqual(["医疗服务", "汽车零部", "物流"]);
    expect(input.map((theme) => theme.name)).toEqual(["汽车零部", "医疗服务", "物流"]);
  });
});

describe("题材分组折叠（默认前 8 组）", () => {
  it("visibleThemes truncates to THEME_COLLAPSE_COUNT when collapsed", () => {
    const themes = Array.from({ length: 12 }, (_, index) => makeTheme(`题材${index}`, 1));
    expect(THEME_COLLAPSE_COUNT).toBe(8);
    expect(visibleThemes(themes, false)).toHaveLength(8);
    expect(visibleThemes(themes, true)).toHaveLength(12);
  });

  it("isThemeCollapsible only above the threshold", () => {
    expect(isThemeCollapsible(9)).toBe(true);
    expect(isThemeCollapsible(8)).toBe(false);
    expect(isThemeCollapsible(1)).toBe(false);
  });
});

describe("sortThemeStocks（组内按首封时间升序，null 最后）", () => {
  it("orders by first_limit_time ascending with nulls last, without mutating", () => {
    const input = [
      makeStock({ name: "尾盘", first_limit_time: "14:30:00" }),
      makeStock({ name: "无时间", first_limit_time: null }),
      makeStock({ name: "早盘", first_limit_time: "09:25:03" }),
    ];
    const sorted = sortThemeStocks(input);
    expect(sorted.map((stock) => stock.name)).toEqual(["早盘", "尾盘", "无时间"]);
    expect(input.map((stock) => stock.name)).toEqual(["尾盘", "无时间", "早盘"]);
  });
});

describe("themeStreakText（连板文案）", () => {
  it("n>1 → N连板；n==1 → 首板", () => {
    expect(themeStreakText(3)).toBe("3连板");
    expect(themeStreakText(2)).toBe("2连板");
    expect(themeStreakText(1)).toBe("首板");
  });

  it("0/null → null（不显示徽标）", () => {
    expect(themeStreakText(0)).toBeNull();
    expect(themeStreakText(null)).toBeNull();
  });
});

describe("isThemeLeader（题材龙头 ★ 判定）", () => {
  it("matches by leader.vt_symbol", () => {
    const theme: Theme = {
      ...makeTheme("医疗服务", 6),
      leader: { vt_symbol: "002172.SZSE", name: "澳洋健康", limit_up_count: 2 },
    };
    expect(isThemeLeader(theme, makeStock({ vt_symbol: "002172.SZSE" }))).toBe(true);
    expect(isThemeLeader(theme, makeStock({ vt_symbol: "600000.SSE" }))).toBe(false);
  });

  it("returns false when leader is null", () => {
    expect(isThemeLeader(makeTheme("其他", 3), makeStock())).toBe(false);
  });
});
