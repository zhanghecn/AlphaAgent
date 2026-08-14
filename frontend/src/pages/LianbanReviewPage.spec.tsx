import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { LadderStock, LianbanReview, LianbanStats } from "@/api/lianban";
import {
  ArchiveNav,
  LIANBAN_LIVE_REFETCH_INTERVAL_MS,
  parseDateParam,
  reviewRefetchInterval,
} from "./LianbanReviewPage";
import {
  buildFaqItems,
  FAQ_NO_DATA,
  faqFirstBoardAnswer,
  faqThemesAnswer,
  faqTopStreakAnswer,
  ReviewFaqSection,
} from "./lianban/ReviewFaqSection";

// ===== 契约夹具（对齐 B4 payload 结构）=====

function makeStock(vtSymbol: string, name: string, count: number): LadderStock {
  return {
    vt_symbol: vtSymbol,
    name,
    limit_up_count: count,
    first_limit_time: "09:31:00",
    last_limit_time: null,
    limit_amount: null,
    break_count: null,
    limit_stat_days: null,
    limit_stat_boards: null,
    is_reverse: null,
    industry: null,
    concepts: [],
    close_price: null,
    change_pct: null,
    is_one_word: null,
    is_st: null,
    board: null,
  };
}

function makeStats(overrides: Partial<LianbanStats> = {}): LianbanStats {
  return {
    limit_up: 59,
    limit_up_prev: 63,
    lianban: 15,
    lianban_prev: 12,
    max_streak: 5,
    max_streak_prev: 4,
    limit_down: 3,
    limit_down_prev: 5,
    seal_rate: 0.621,
    seal_rate_prev: 0.6,
    broken: 36,
    broken_prev: 40,
    prev_lu_avg_change: 1.2,
    prev_lu_median_change: 0.8,
    prev_lu_rise_ratio: 0.55,
    sentiment_phase: "升温",
    sentiment_score: 62.4,
    rise_count: 2100,
    fall_count: 2900,
    new_high_63: 120,
    new_low_63: 45,
    total_amount: 1.1e12,
    margin_balance: 1.9e12,
    margin_change: 9.5e9,
    margin_date: "2026-08-12",
    ...overrides,
  };
}

function makeReview(overrides: Partial<LianbanReview> = {}): LianbanReview {
  return {
    trade_date: "2026-08-13",
    mode: "final",
    weekday: "星期四",
    indices: [],
    stats: makeStats(),
    sentiment: null,
    ladder: {
      trade_date: "2026-08-13",
      source: "pool_archive",
      tiers: [
        {
          streak: 5,
          count: 1,
          today_promotion: null,
          stocks: [makeStock("000001.SZSE", "龙头甲", 5)],
        },
        {
          streak: 1,
          count: 2,
          today_promotion: null,
          stocks: [makeStock("000002.SZSE", "首板乙", 1), makeStock("000003.SZSE", "首板丙", 1)],
        },
      ],
    },
    promotion: null,
    relay: {
      tiers: [],
      first_board: { base: 75, promoted: 12, rate: 0.16, mean: 0.163 },
    },
    broken_list: [],
    themes: [
      { name: "机器人", kind: "concept", count: 12, leader: null, stocks: [] },
      { name: "新能源汽车", kind: "concept", count: 9, leader: null, stocks: [] },
      { name: "芯片", kind: "industry", count: 7, leader: null, stocks: [] },
      { name: "医药", kind: "industry", count: 5, leader: null, stocks: [] },
    ],
    theme_strength: [],
    hot_leaders: { as_of: null, items: [] },
    data_quality: { pool_archived: true, rebuild_date: null, missing: [] },
    ...overrides,
  };
}

function nullStats(): LianbanStats {
  return makeStats({
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
  });
}

// ===== 日期参数解析 =====

describe("parseDateParam", () => {
  it("passes a valid ISO trade date through", () => {
    expect(parseDateParam("2026-08-13")).toBe("2026-08-13");
    expect(parseDateParam("2026-01-05")).toBe("2026-01-05");
  });

  it("falls back to latest review when the param is missing or empty", () => {
    expect(parseDateParam(null)).toBeUndefined();
    expect(parseDateParam("")).toBeUndefined();
  });

  it("rejects garbage so it never reaches the API", () => {
    expect(parseDateParam("foobar")).toBeUndefined();
    expect(parseDateParam("2026/08/13")).toBeUndefined();
    expect(parseDateParam("2026-8-13")).toBeUndefined();
    expect(parseDateParam("2026-13-01")).toBeUndefined();
    expect(parseDateParam("2026-08-32")).toBeUndefined();
    expect(parseDateParam("2026-08-13T00:00:00")).toBeUndefined();
  });
});

// ===== live 轮询条件 =====

describe("reviewRefetchInterval", () => {
  it("polls only in live mode", () => {
    expect(reviewRefetchInterval(makeReview({ mode: "live" }))).toBe(
      LIANBAN_LIVE_REFETCH_INTERVAL_MS,
    );
    expect(LIANBAN_LIVE_REFETCH_INTERVAL_MS).toBe(30_000);
  });

  it("does not poll final/rebuild archives or before the first payload", () => {
    expect(reviewRefetchInterval(makeReview({ mode: "final" }))).toBe(false);
    expect(reviewRefetchInterval(makeReview({ mode: "rebuild" }))).toBe(false);
    expect(reviewRefetchInterval(undefined)).toBe(false);
  });
});

// ===== FAQ 派生 =====

describe("buildFaqItems", () => {
  it("builds seven dated questions plus a static provenance answer", () => {
    const items = buildFaqItems(makeReview());
    expect(items).toHaveLength(7);
    expect(items[0].question).toBe("2026年8月13日 A股涨停多少家？");
    // 口径/免责题为静态文案，不带日期
    expect(items[6].question).toBe("复盘数据从哪来、什么时候定版？");
    expect(items[6].answer).toContain("19:00");
    expect(items[6].answer).toContain("不构成投资建议");
  });

  it("answers the limit-up question with all stat clauses", () => {
    const answer = buildFaqItems(makeReview())[0].answer;
    expect(answer).toContain("涨停 59 家");
    expect(answer).toContain("连板 15 家");
    expect(answer).toContain("最高 5 板");
    expect(answer).toContain("跌停 3 家");
    expect(answer).toContain("炸板 36 家");
    expect(answer).toContain("封板率 62.1%");
  });

  it("answers sentiment, prev-limit-up and first-board questions from the payload", () => {
    const items = buildFaqItems(makeReview());
    expect(items[1].answer).toContain("升温");
    expect(items[1].answer).toContain("62°");
    expect(items[2].answer).toContain("+1.2%");
    expect(items[2].answer).toContain("连板梯队接力");
    expect(items[3].answer).toContain("75");
    expect(items[3].answer).toContain("12");
    expect(items[3].answer).toContain("16%");
    expect(items[3].answer).toContain("16.3%");
  });

  it("names the top-streak stocks and the top three themes", () => {
    const items = buildFaqItems(makeReview());
    expect(items[4].answer).toContain("最高 5 板");
    expect(items[4].answer).toContain("龙头甲");
    expect(items[5].answer).toContain("机器人 12 家");
    expect(items[5].answer).toContain("新能源汽车 9 家");
    expect(items[5].answer).toContain("芯片 7 家");
    // 只答前 3 组，第 4 组不出现
    expect(items[5].answer).not.toContain("医药");
  });

  it("degrades every data question to 暂无数据 when stats are null", () => {
    const review = makeReview({
      stats: nullStats(),
      ladder: null,
      themes: [],
      relay: { tiers: [], first_board: { base: 0, promoted: 0, rate: null, mean: null } },
    });
    const items = buildFaqItems(review);
    expect(items[0].answer).toBe(FAQ_NO_DATA);
    expect(items[1].answer).toBe(FAQ_NO_DATA);
    expect(items[2].answer).toBe(FAQ_NO_DATA);
    expect(items[4].answer).toBe(FAQ_NO_DATA);
    expect(items[5].answer).toBe(FAQ_NO_DATA);
    // 静态题不受数据影响
    expect(items[6].answer).not.toBe(FAQ_NO_DATA);
  });
});

describe("faqFirstBoardAnswer", () => {
  it("explains an empty first-board sample instead of a fake rate", () => {
    const answer = faqFirstBoardAnswer({
      tiers: [],
      first_board: { base: 0, promoted: 0, rate: null, mean: null },
    });
    expect(answer).toContain("昨日无首板");
  });

  it("degrades missing rate to -- and drops the mean clause when mean is null", () => {
    const answer = faqFirstBoardAnswer({
      tiers: [],
      first_board: { base: 40, promoted: 8, rate: null, mean: null },
    });
    expect(answer).toContain("晋级率 --");
    expect(answer).not.toContain("历史均值");
  });
});

describe("faqTopStreakAnswer", () => {
  it("answers with the streak count only when the ladder is missing", () => {
    expect(faqTopStreakAnswer(makeStats(), null)).toBe("最高 5 板。");
  });

  it("caps the name list and summarizes the remainder", () => {
    const stocks = Array.from({ length: 7 }, (_, index) =>
      makeStock(`00000${index}.SZSE`, `股${index}`, 5),
    );
    const ladder = {
      trade_date: "2026-08-13",
      source: "pool_archive" as const,
      tiers: [{ streak: 5, count: 7, today_promotion: null, stocks }],
    };
    const answer = faqTopStreakAnswer(makeStats(), ladder);
    expect(answer).toContain("股4");
    expect(answer).not.toContain("股5");
    expect(answer).toContain("等 7 只");
  });
});

describe("faqThemesAnswer", () => {
  it("returns null for an empty theme list", () => {
    expect(faqThemesAnswer([])).toBeNull();
  });
});

// ===== 组件渲染（SSR 静态标记，零交互环境）=====

describe("ReviewFaqSection", () => {
  it("renders all questions with only the first answer expanded by default", () => {
    const html = renderToStaticMarkup(<ReviewFaqSection review={makeReview()} />);
    expect(html).toContain("常见问题");
    expect(html).toContain("2026年8月13日 A股涨停多少家？");
    expect(html).toContain("2026年8月13日 主线题材是什么？");
    expect(html).toContain("复盘数据从哪来、什么时候定版？");
    // 默认展开第一条：第一题答案上屏，第二题答案折叠
    expect(html).toContain("涨停 59 家");
    expect(html).not.toContain("市场情绪处于「升温」阶段");
    expect(html).toContain('aria-expanded="true"');
  });
});

describe("ArchiveNav", () => {
  const dates = ["2026-08-13", "2026-08-12", "2026-08-11"];

  it("links to the previous and next archived reviews", () => {
    const html = renderToStaticMarkup(
      <ArchiveNav dates={dates} currentDate="2026-08-12" onDateChange={() => undefined} />,
    );
    expect(html).toContain("2026-08-11 复盘");
    expect(html).toContain("2026-08-13 复盘");
  });

  it("disables the next link on the latest review", () => {
    const html = renderToStaticMarkup(
      <ArchiveNav dates={dates} currentDate="2026-08-13" onDateChange={() => undefined} />,
    );
    expect(html).toContain("已是最新");
    expect(html).toContain("2026-08-12 复盘");
  });

  it("disables the prev link on the oldest review", () => {
    const html = renderToStaticMarkup(
      <ArchiveNav dates={dates} currentDate="2026-08-11" onDateChange={() => undefined} />,
    );
    expect(html).toContain("无更早复盘");
    expect(html).toContain("2026-08-12 复盘");
  });

  it("navigates from a live date that is not archived yet", () => {
    const html = renderToStaticMarkup(
      <ArchiveNav dates={dates} currentDate="2026-08-14" onDateChange={() => undefined} />,
    );
    expect(html).toContain("2026-08-13 复盘");
    expect(html).toContain("已是最新");
  });
});
