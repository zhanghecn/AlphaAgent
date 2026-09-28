import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ThemeProvider } from "@/theme/ThemeProvider";
import { ShortTermResearchPage } from "./ShortTermResearchPage";
import { HPR_LIVE_REFRESH_INTERVAL_MS } from "./HighRelayPage";
import type { HprLivePayload, HprQuizQuestion } from "@/api/highRelay";
import { HprLedgerView } from "@/features/highRelay/HprLedgerView";
import { HprLiveView } from "@/features/highRelay/HprLiveView";
import { QuizRunner } from "@/features/highRelay/quiz/QuizRunner";
import { isWrongAnswer, judge, summarize, quizQuestionId } from "@/features/highRelay/quiz/quizScore";
import { overwriteAnswer, saveAnswer } from "@/features/highRelay/quiz/quizProgress";

function withProviders(node: React.ReactElement, routerEntries: string[] = ["/"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={routerEntries}>{node}</MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

const LIVE_PAYLOAD: HprLivePayload = {
  status: "ok",
  trade_date: "2026-09-04",
  stale: false,
  session_stage: "first_window",
  rules_version: "hpr-v2.0",
  counts: {
    pool: 2,
    actionable: 1,
    signals: 1,
    by_group: { 二接三阴: 1, 三接四阳: 1 },
    by_point: { B1: 1 },
    by_status: { watching: 1, holding: 1 },
  },
  mkt_lim_tm1: 38,
  group4_labels: {
    二接三阴: "二接三·阴地基",
    二接三阳: "二接三·阳地基",
    三接四阴: "三接四·阴地基",
    三接四阳: "三接四·阳地基",
  },
  point_labels: {
    A1: "A1 双平贴零",
    A2: "A2 一字转强",
    B1: "B1 强转弱",
    B2: "B2 三低",
    B3: "B3 冒泡转弱",
    B4: "B4 冒泡转强",
    E1: "E1 四板便捷",
    E2: "E2 高开低吸",
    E3: "E3 贴零温开",
  },
  point_levels: { A1: "A", A2: "A", B1: "A", B2: "A", B3: "A", B4: "A", E1: "A", E2: "A", E3: "A" },
  last_scan: null,
  entries: [
    {
      vt_symbol: "002403.SZSE",
      name: "爱仕达",
      group4: "二接三阴",
      n_board: 2,
      point: "B1",
      level: "B",
      actionable: true,
      avoid_static: null,
      auction_gate: null,
      prev_close: 15.0,
      limit_price: 16.5,
      foundation_yang: false,
      foundation_chg: -1.2,
      dist_h60: -20.9,
      ma_state: "++-",
      dist_ma10: -3.1,
      prior_height: null,
      prev_wave60: 0,
      prev_wave120: 0,
      chain: "下影→实体",
      b1_open: 1.1,
      b2_open: 7.2,
      b1_turn: 5.0,
      b2_turn: 6.5,
      turn_grad: 1.5,
      status: "holding",
      auction_pct: 2.1,
      opened: null,
      touched_at: "2026-09-04T09:41:00+08:00",
      entry_price: 16.5,
      entry_time: "2026-09-04T09:41:00+08:00",
      last_price: 16.5,
      change_pct: 10.0,
      sealed: true,
      streak_h: 1,
      exit_date: null,
      exit_price: null,
      exit_reason: null,
      ret_pct: null,
    },
    {
      vt_symbol: "605398.SSE",
      name: "新炬网络",
      group4: "三接四阳",
      n_board: 3,
      point: "—",
      level: "—",
      actionable: false,
      avoid_static: null,
      auction_gate: null,
      prev_close: 20.0,
      limit_price: 22.0,
      foundation_yang: true,
      foundation_chg: 2.2,
      dist_h60: -16.1,
      ma_state: "+++",
      dist_ma10: 6.5,
      prior_height: null,
      prev_wave60: 0,
      prev_wave120: 0,
      chain: "实体→实体→下影",
      b1_open: 0.5,
      b2_open: 1.2,
      b1_turn: 4.0,
      b2_turn: 5.4,
      turn_grad: 1.4,
      status: "watching",
      auction_pct: 0.8,
      opened: null,
      touched_at: null,
      entry_price: null,
      entry_time: null,
      last_price: 20.4,
      change_pct: 2.0,
      sealed: null,
      streak_h: null,
      exit_date: null,
      exit_price: null,
      exit_reason: null,
      ret_pct: null,
    },
  ],
};

describe("HighRelayPage live refresh cadence", () => {
  it("polls the persisted pool snapshot every 30s during the session", () => {
    expect(HPR_LIVE_REFRESH_INTERVAL_MS).toBe(30 * 1000);
  });
});

describe("HprLiveView", () => {
  it("renders point badges, level marks and relay-specific status labels", () => {
    const html = renderToStaticMarkup(
      withProviders(
        <HprLiveView
          payload={LIVE_PAYLOAD}
          availableDates={["2026-09-04"]}
          selectedDate={null}
          onDateChange={() => undefined}
        />,
      ),
    );
    expect(html).toContain("高位接力 · 实时推荐");
    expect(html).toContain("早盘(09:30~09:45)");
    expect(html).toContain("B1 强转弱");
    expect(html).toContain("🔵候选");
    expect(html).toContain("雷达");
    expect(html).toContain("打3板");
    expect(html).toContain("打4板");
    expect(html).toContain("持有中");
    expect(html).toContain("爱仕达");
    expect(html).toContain("下影→实体");
  });
});

describe("HprLedgerView", () => {
  it("renders E3 exit reason labels and E0 comparison column", () => {
    const html = renderToStaticMarkup(
      withProviders(
        <HprLedgerView
          caliber="测试口径"
          months={[{ month: "2026-09", count: 1, win_rate: 100, avg_ret_pct: 12.6, total_ret_pct: 12.6 }]}
          month="2026-09"
          onMonthChange={() => undefined}
          ledgerDays={[
            {
              trade_date: "2026-09-03",
              count: 1,
              win: 1,
              avg_ret_pct: 12.6,
              trades: [
                {
                  vt_symbol: "002403.SZSE",
                  name: "爱仕达",
                  point: "B1",
                  level: "B",
                  group4: "二接三阴",
                  entry_price: 16.5,
                  auction_pct: 2.1,
                  sealed: true,
                  streak_h: 2,
                  exit_date: "2026-09-05",
                  exit_price: 18.58,
                  exit_reason: "break_close",
                  ret_pct: 12.6,
                  ret_e0: 12.6,
                  touch: "09:45",
                },
              ],
            },
          ]}
        />,
      ),
    );
    expect(html).toContain("断板日收盘卖");
    expect(html).toContain("2板");
    expect(html).toContain("B1");
    expect(html).toContain("对照E0");
    expect(html).toContain("炸板当日收盘走");
  });
});

describe("ShortTermResearchPage", () => {
  it("registers 高位接力 as a research tab", () => {
    const html = renderToStaticMarkup(
      withProviders(<ShortTermResearchPage />, ["/short-term?research=high-relay"]),
    );
    expect(html).toContain("高位接力");
    expect(html).toContain("N型补涨打板");
    expect(html).toContain("潜龙首板");
    expect(html).toContain("低吸");
  });
});

// ── 答题训练 · 判分四档矩阵(主人定稿) ──
// 符合口诀×结果配合=+10 / 符合×不配合=+3 / 违背×配合=+2 / 违背×不配合=-5

describe("quizScore.judge 四档矩阵", () => {
  const cases: Array<[boolean, number, "buy" | "reject", number, string]> = [
    // [shouldBuy, retPct, choice, 期望分, 期望文案]
    [true, 12.6, "buy", 10, "口诀对,行情也对"],        // 该买买对赚钱
    [true, -4.2, "buy", 3, "口诀对,这次行情不配合"],    // 该买买对但亏
    [true, 12.6, "reject", -5, "违背口诀,代价实打实"],  // 该买不买踏空大涨
    [true, -4.2, "reject", 2, "违背口诀,这次侥幸对了"], // 该买不买却躲过
    [false, -7.5, "reject", 10, "口诀对,行情也对"],     // 该拒拒对躲过
    [false, 8.8, "reject", 3, "口诀对,这次行情不配合"], // 该拒拒对但踏空
    [false, 8.8, "buy", 2, "违背口诀,这次侥幸对了"],    // 不该买瞎买侥幸赚
    [false, -7.5, "buy", -5, "违背口诀,代价实打实"],    // 不该买买了亏
    [true, 0, "buy", 10, "口诀对,行情也对"],            // 恰平算配合买(好票口径)
    [false, 0, "reject", 3, "口诀对,这次行情不配合"],   // 恰平对拒=不配合
  ];
  it.each(cases)(
    "shouldBuy=%s ret=%s choice=%s → %s分",
    (shouldBuy, retPct, choice, score, text) => {
      const v = judge(shouldBuy, retPct, choice);
      expect(v.score).toBe(score);
      expect(v.text).toBe(text);
    },
  );
});

describe("quizScore.summarize 月度统计", () => {
  it("汇总四档计数与按口诀分组对错", () => {
    const questions = [
      {
        seq: 1, vt_symbol: "000001.SZSE", name: "平安银行", decision_date: "2024-11-01",
        n_board: 2, group4: "二接三阳" as const,
        display: {} as never, bars_before: [], bars_after: [],
        answer: { point: "A1" as const, should_buy: true, ret_pct: 10, buy_price: 10,
                  sealed: true, hold_days: 2, exit_date: "2024-11-05", exit_price: 11,
                  exit_reason: "break_close" },
        explain: { kind: "hit" as const, scheme_no: "A1", scheme_name: "A1 双平贴零",
                   scheme_desc: "", psycho: "", today_window: [6, 9.5] as [number, number],
                   matched_line: "", case_note: null, half_mountain: false },
      },
      {
        seq: 2, vt_symbol: "000002.SZSE", name: "万科A", decision_date: "2024-11-04",
        n_board: 2, group4: "二接三阳" as const,
        display: {} as never, bars_before: [], bars_after: [],
        answer: { point: "—" as const, should_buy: false, ret_pct: -5, buy_price: 10,
                  sealed: false, hold_days: null, exit_date: "2024-11-04", exit_price: 9.5,
                  exit_reason: "break_day_close" },
        explain: { kind: "miss" as const, reasons: ["顶格"] },
      },
    ];
    const answers = {
      [quizQuestionId(questions[0])]: { choice: "buy" as const, score: 10 },
      [quizQuestionId(questions[1])]: { choice: "reject" as const, score: 10 },
    };
    const s = summarize(questions, answers);
    expect(s.answered).toBe(2);
    expect(s.score).toBe(20);
    expect(s.great).toBe(2);
    expect(s.byPoint).toEqual([{ point: "A1", n: 1, correct: 1 }]);
  });
});

// ── 答题训练 · QuizRunner(SSR 静态断言;图表在 useEffect 不执行) ──

const QUIZ_HIT_Q: HprQuizQuestion = {
  seq: 1, vt_symbol: "000797.SZSE", name: "粤桂股份", decision_date: "2024-11-13",
  n_board: 2, group4: "二接三阴",
  display: {
    board_label: "打3板", b1_open: 8.4, b2_open: 10.0, b3_open: null,
    b2_turn: 28.8, b3_turn: null, pre20_pct: 20.0, auction_pct: 4.16,
    prev_close: 15.0, limit_price: 16.5, decision_open: 15.62, chain: "实体→一字",
  },
  bars_before: [{ d: "2024-11-12", o: 14, h: 15, l: 13.5, c: 15, v: 1000 }],
  bars_after: [{ d: "2024-11-13", o: 15.62, h: 16.5, l: 15.3, c: 16.5, v: 3000 }],
  answer: {
    point: "B1", should_buy: true, ret_pct: 93.07, buy_price: 16.5,
    sealed: true, hold_days: 6, exit_date: "2024-11-21", exit_price: 31.9,
    exit_reason: "break_close",
  },
  explain: {
    kind: "hit", scheme_no: "B1", scheme_name: "B1 强转弱",
    scheme_desc: "一板二板都强开(各≥7),二板换手要活(≥5),今天温开3~5",
    psycho: "弱势票连开两天强开,人气已经聚起来了……",
    today_window: [3, 5],
    matched_line: "一板开+8.4 × 二板开+10.0(换手28.8) → 今开+4.2 落在窗3~5",
    case_note: "B1最大赢家锚点:强强链换手28.8≥5,今天开4.16,+93.1(收益之王)",
    half_mountain: false,
  },
};

const QUIZ_MISS_Q: HprQuizQuestion = {
  seq: 2, vt_symbol: "600398.SH", name: "齐心集团", decision_date: "2024-11-29",
  n_board: 3, group4: "三接四阳",
  display: {
    board_label: "打4板", b1_open: 1.3, b2_open: -3.1, b3_open: 10.0,
    b2_turn: 10.1, b3_turn: 1.1, pre20_pct: 4.4, auction_pct: 9.98,
    prev_close: 20.0, limit_price: 22.0, decision_open: 22.0, chain: "实体→一字→一字",
  },
  bars_before: [{ d: "2024-11-28", o: 18, h: 20, l: 17.5, c: 20, v: 2000 }],
  bars_after: [{ d: "2024-11-29", o: 22.0, h: 22.0, l: 21.5, c: 21.13, v: 5000 }],
  answer: {
    point: "—", should_buy: false, ret_pct: -5.64, buy_price: 22.0,
    sealed: false, hold_days: null, exit_date: "2024-11-29", exit_price: 20.76,
    exit_reason: "break_day_close",
  },
  explain: { kind: "miss", reasons: ["今开+10.0顶格:排队也买不到,口诀一律不打(硬规则)"] },
};

function renderRunner(props?: {
  showName?: boolean;
  answers?: Record<string, { choice: "buy" | "reject"; score: number }>;
  questions?: HprQuizQuestion[];
}) {
  return renderToStaticMarkup(
    withProviders(
      <QuizRunner
        month="2024-11"
        questions={props?.questions ?? [QUIZ_HIT_Q, QUIZ_MISS_Q]}
        rulesVersion="hpr-v4.0·q1"
        showName={props?.showName ?? false}
        answers={props?.answers ?? {}}
        onAnswersChange={() => undefined}
        onBack={() => undefined}
      />,
    ),
  );
}

describe("QuizRunner 答题流", () => {
  it("默认匿名题干(不带题号)+信息面板+买/不买按钮", () => {
    const html = renderRunner();
    // 乱序后题干只显示「x年x月 · 打N板」,不显示题号(防背答案)
    expect(html).toContain("2024年11月 · 打3板");
    expect(html).not.toContain("粤桂股份");
    expect(html).toContain("打3板");
    expect(html).toContain("一板开");
    expect(html).toContain("+8.4");
    expect(html).toContain("换手28.8");
    expect(html).toContain("今开");
    expect(html).toContain("+4.2");
    expect(html).toContain("买入");
    expect(html).toContain("不买");
    // 板位勾选:默认只勾打3板(本轮1题),打4板 chip 未选中可勾
    expect(html).toContain("第 1/1 题");
    expect(html).toContain("✓ 打3板 0/1");
    expect(html).toContain("打4板 0/1");
    // 打4板的题不在本轮范围
    expect(html).not.toContain("22.0");
  });

  it("打3板无题的月份默认落到打4板(单段只显一个chip)", () => {
    const onlyB4 = renderRunner({ questions: [QUIZ_MISS_Q] });
    expect(onlyB4).toContain("✓ 打4板 0/1");
    expect(onlyB4).not.toContain("打3板 0/1");
  });

  it("实名开关下题干直接显示票名", () => {
    const html = renderRunner({ showName: true });
    expect(html).toContain("粤桂股份");
  });

  it("已答命中题:判定横幅+口诀讲解卡+票名揭示", () => {
    const html = renderRunner({
      answers: { [quizQuestionId(QUIZ_HIT_Q)]: { choice: "buy", score: 10 } },
    });
    expect(html).toContain("口诀对,行情也对");
    expect(html).toContain("+10");
    expect(html).toContain("粤桂股份");          // 答完揭示票名
    expect(html).toContain("B1 强转弱");           // 口诀卡
    expect(html).toContain("主力怎么想");
    expect(html).toContain("典型样例");            // case_note
    expect(html).toContain("落在窗3~5");           // matched_line
    expect(html).toContain("断板日收盘卖");        // 退出原因
  });

  it("已答未命中题(拒对):避免理由列表+段末入口", () => {
    const html = renderRunner({
      questions: [QUIZ_MISS_Q],
      answers: { [quizQuestionId(QUIZ_MISS_Q)]: { choice: "reject", score: 10 } },
    });
    expect(html).toContain("口诀对,行情也对");
    expect(html).toContain("为什么不买");
    expect(html).toContain("顶格");
    expect(html).toContain("只看不做");
    expect(html).toContain("打4板");
    expect(html).toContain("看本段总结");          // 最后一题揭示后的入口
  });

  it("违背口诀买入:扣分横幅", () => {
    const html = renderRunner({
      questions: [QUIZ_MISS_Q],
      answers: { [quizQuestionId(QUIZ_MISS_Q)]: { choice: "buy", score: -5 } },
    });
    // miss 票 ret=-5.64,违背口诀买入亏损 → -5
    expect(html).toContain("违背口诀,代价实打实");
    expect(html).toContain("-5");
    expect(html).toContain("标准答案");
  });
});

describe("quizScore.isWrongAnswer 错题判定(重练入选条件)", () => {
  it("违背口诀两档(lucky/bad)算错题,符合口诀两档不算,未答不算", () => {
    // QUIZ_MISS_Q: should_buy=false, ret=-5.64
    expect(isWrongAnswer(QUIZ_MISS_Q, { choice: "buy", score: -5 })).toBe(true);   // bad
    expect(isWrongAnswer(QUIZ_MISS_Q, { choice: "reject", score: 10 })).toBe(false); // great
    // QUIZ_HIT_Q: should_buy=true, ret=+93.07
    expect(isWrongAnswer(QUIZ_HIT_Q, { choice: "reject", score: -5 })).toBe(true);  // bad 踏空
    expect(isWrongAnswer(QUIZ_HIT_Q, { choice: "buy", score: 10 })).toBe(false);   // great
    expect(isWrongAnswer(QUIZ_HIT_Q, undefined)).toBe(false);                      // 未答
  });
});

describe("quizProgress 首答不改/重练覆盖", () => {
  it("saveAnswer 已答不改,overwriteAnswer 允许覆盖", () => {
    const ver = `test-${Date.now()}`;
    const qid = "2024-11-13|000797.SZSE";
    let all = saveAnswer(ver, qid, { choice: "buy", score: 10 });
    expect(all[qid].score).toBe(10);
    all = saveAnswer(ver, qid, { choice: "reject", score: -5 }); // 已答不改
    expect(all[qid].choice).toBe("buy");
    all = overwriteAnswer(ver, qid, { choice: "reject", score: -5 }); // 重练覆盖
    expect(all[qid].choice).toBe("reject");
    expect(all[qid].score).toBe(-5);
  });
});
