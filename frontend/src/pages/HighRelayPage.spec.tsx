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
import { visibleBarsForWidth } from "@/features/highRelay/quiz/QuizKlineChart";
import { isWrongAnswer, judge, simulateMonth, summarize, quizQuestionId } from "@/features/highRelay/quiz/quizScore";
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
    二接三阴: "二接三 · 阴地基",
    二接三阳: "二接三·阳地基",
    三接四阴: "三接四·阴地基",
    三接四阳: "三接四·阳地基",
  },
  point_labels: {
    A1: "A1 双平贴零",
    A2: "A2 一字转强",
    B1: "B1 强开系",
    B2: "B2 捡尸",
    C1: "C1 冒泡转弱",
    A3: "A3 高开低吸",
    B3: "B3 贴零温开",
    C2: "C2 四板便捷",
  },
  point_levels: { A1: "A", A2: "A", B1: "A", B2: "A", C1: "A", A3: "A", B3: "A", C2: "A" },
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
      action_hint: "今天开3~5,盘中触涨停价打",
      today_window: [[3.0, 5.0]],
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
      action_hint: null,
      today_window: [],
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
    expect(html).toContain("B1 强开系");
    expect(html).toContain("🔵候选");
    expect(html).toContain("雷达");
    expect(html).toContain("打3板");
    expect(html).toContain("打4板");
    expect(html).toContain("持有中");
    expect(html).toContain("爱仕达");
    expect(html).toContain("下影→实体");
    // 出手条件(主人定):今开列下显示「需多少」并对照今开(mock: 今开+2.1 不在窗3~5 → ✗)
    expect(html).toContain("需3~5");
    expect(html).toContain(" ✗");
    expect(html).toContain("今天开3~5,盘中触涨停价打");  // title 悬浮完整条件
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
    expect(html).toContain("断板日卖");
    expect(html).toContain("2板");
    expect(html).toContain("B1");
    expect(html).toContain("对照E0");
    expect(html).toContain("炸板次日走");
  });

  it("marks overlap trades 持仓中 and excludes them from point summary", () => {
    const html = renderToStaticMarkup(
      withProviders(
        <HprLedgerView
          caliber="测试口径"
          months={[{ month: "2026-07", count: 2, win_rate: 100, avg_ret_pct: 5.0, total_ret_pct: 5.0 }]}
          month="2026-07"
          onMonthChange={() => undefined}
          ledgerDays={[
            {
              trade_date: "2026-07-15",
              count: 2,
              win: 1,
              avg_ret_pct: 5.0,
              trades: [
                {
                  vt_symbol: "600664.SSE",
                  name: "哈药股份",
                  point: "C2",
                  level: "B",
                  group4: "三接四阴",
                  entry_price: 7.67,
                  auction_pct: 8.0,
                  sealed: true,
                  streak_h: 1,
                  exit_date: "2026-07-16",
                  exit_price: 8.05,
                  exit_reason: "break_close",
                  ret_pct: 5.0,
                  ret_e0: 5.0,
                  touch: "09:45",
                  overlap: false,
                },
                {
                  vt_symbol: "600664.SSE",
                  name: "哈药股份",
                  point: "C2",
                  level: "B",
                  group4: "三接四阴",
                  entry_price: 7.67,
                  auction_pct: 8.0,
                  sealed: true,
                  streak_h: 1,
                  exit_date: "2026-07-16",
                  exit_price: 9.1,
                  exit_reason: "break_close",
                  ret_pct: 18.7,
                  ret_e0: 18.7,
                  touch: "09:45",
                  overlap: true,  // 同票持仓中,真实买不进
                },
              ],
            },
          ]}
        />,
      ),
    );
    expect(html).toContain("持仓中");
    expect(html).toContain("opacity-50");
    expect(html).toContain("</span> 1笔 · 胜100% · 均+5.00%");  // 点汇总跳过 overlap 笔
  });
});

describe("ShortTermResearchPage", () => {
  it("registers 高位接力 as a research tab", () => {
    const html = renderToStaticMarkup(
      withProviders(<ShortTermResearchPage />, ["/short-term?research=high-relay"]),
    );
    expect(html).toContain("高位接力");
    expect(html).not.toContain("N型补涨打板"); // 2026-10-02 终版下线
    expect(html).not.toContain("潜龙首板"); // 2026-10-02 全下线
    expect(html).not.toContain("低吸");
  });
});

// ── 答题训练 · 判分四档矩阵(主人定稿) ──
// 符合口诀×结果配合=+10 / 符合×不配合=+3 / 违背×配合=+2 / 违背×不配合=-5

describe("quizScore.judge 四档矩阵", () => {
  const cases: Array<[boolean, number, "buy" | "reject", number, string]> = [
    // [shouldBuy, retPct, choice, 期望分, 期望文案]
    [true, 12.6, "buy", 10, "口诀对,行情也对"],         // 该买买对赚钱
    [true, -4.2, "buy", 3, "口诀对,这次行情不配合"],     // 该买买对但亏
    [true, 12.6, "reject", -10, "没按口诀,这次判断错了"], // 该买不买踏空大涨(v6对称-10)
    [true, -4.2, "reject", 5, "没按口诀,但你判断对了"],  // 该买不买却躲过(v5去侥幸化+5)
    [false, -7.5, "reject", 10, "口诀对,行情也对"],      // 该拒拒对躲过
    [false, 8.8, "reject", 3, "口诀对,这次行情不配合"],  // 该拒拒对但踏空
    [false, 8.8, "buy", 5, "没按口诀,但你判断对了"],     // 不该买但自己分析判断对(v5+5)
    [false, -7.5, "buy", -10, "没按口诀,这次判断错了"],  // 不该买买了亏(v6对称-10)
    [true, 0, "buy", 10, "口诀对,行情也对"],             // 恰平算配合买(好票口径)
    [false, 0, "reject", 3, "口诀对,这次行情不配合"],    // 恰平对拒=不配合
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
        explain: { kind: "hit" as const, scheme_no: "A1", scheme_name: "A1 双平贴零·低开等强开",
                   scheme_row: null, matched_line: "" },
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
    expect(s.maxScore).toBe(20);     // 满分参照=已答2题×10
    expect(s.great).toBe(2);
    expect(s.ruleMatched).toBe(2);   // 双维:两题都与口诀一致
    expect(s.marketRight).toBe(2);   // 双维:两题方向都判断正确
    expect(s.byPoint).toEqual([{ point: "A1", n: 1, correct: 1 }]);
  });

  it("simulateMonth 本月收益测算:你的操作 vs 口诀标准操作", () => {
    const questions = [
      {  // 命中题 ret=+10,用户买了
        seq: 1, vt_symbol: "000001.SZSE", name: "平安银行", decision_date: "2024-11-01",
        n_board: 2, group4: "二接三阳" as const,
        display: {} as never, bars_before: [], bars_after: [],
        answer: { point: "A1" as const, should_buy: true, ret_pct: 10, buy_price: 10,
                  sealed: true, hold_days: 2, exit_date: "2024-11-05", exit_price: 11,
                  exit_reason: "break_close" },
        explain: { kind: "hit" as const, scheme_no: "A1", scheme_name: "A1 双平贴零·低开等强开",
                   scheme_row: null, matched_line: "" },
      },
      {  // 未命中题 ret=-5,用户也买了(口诀不会买)
        seq: 2, vt_symbol: "000002.SZSE", name: "万科A", decision_date: "2024-11-04",
        n_board: 2, group4: "二接三阳" as const,
        display: {} as never, bars_before: [], bars_after: [],
        answer: { point: "—" as const, should_buy: false, ret_pct: -5, buy_price: 10,
                  sealed: false, hold_days: 1, exit_date: "2024-11-05", exit_price: 9.5,
                  exit_reason: "break_day_close" },
        explain: { kind: "miss" as const, reasons: ["顶格"] },
      },
      {  // 未命中题 ret=+8,用户拒了(踏空;口诀也不买)
        seq: 3, vt_symbol: "000003.SZSE", name: "测试C", decision_date: "2024-11-05",
        n_board: 2, group4: "二接三阳" as const,
        display: {} as never, bars_before: [], bars_after: [],
        answer: { point: "—" as const, should_buy: false, ret_pct: 8, buy_price: 10,
                  sealed: true, hold_days: 3, exit_date: "2024-11-08", exit_price: 10.8,
                  exit_reason: "break_close" },
        explain: { kind: "miss" as const, reasons: ["x"] },
      },
    ];
    const answers = {
      [quizQuestionId(questions[0])]: { choice: "buy" as const, score: 10 },
      [quizQuestionId(questions[1])]: { choice: "buy" as const, score: -10 },
      [quizQuestionId(questions[2])]: { choice: "reject" as const, score: 3 },
    };
    const pnl = simulateMonth(questions, answers);
    expect(pnl.mine).toEqual({ trades: 2, win: 50, ret: 5 });   // 10 + (-5)
    expect(pnl.rule).toEqual({ trades: 1, win: 100, ret: 10 }); // 口诀只买命中题
  });
});

// ── 答题训练 · QuizRunner(SSR 静态断言;图表在 useEffect 不执行) ──

const QUIZ_HIT_Q: HprQuizQuestion = {
  seq: 1, vt_symbol: "000797.SZSE", name: "粤桂股份", decision_date: "2024-11-13",
  n_board: 2, group4: "二接三阴",
  display: {
    board_label: "打3板", b1_open: 8.4, b2_open: 10.0, b3_open: null,
    b2_turn: 28.8, b3_turn: null, pre20_pct: 20.0, pre10_pct: null,
    foundation_chg: 2.6, foundation_pose: "站线上" as const, foundation_ma20: 8.6, anchor_pos: 2.1, auction_pct: 4.16,
    prev_close: 15.0, limit_price: 16.5, decision_open: 15.62, day_high_pct: 9.98,
    chain: "实体→一字",
  },
  bars_before: [
    { d: "2024-11-08", o: 13.2, h: 13.5, l: 12.9, c: 13.0, v: 800 },  // 地基日 阴(c<o)
    { d: "2024-11-11", o: 13.0, h: 14.3, l: 12.9, c: 14.3, v: 1500 },  // 一板
    { d: "2024-11-12", o: 14, h: 15, l: 13.5, c: 15, v: 1000 },        // 二板
  ],
  bars_after: [{ d: "2024-11-13", o: 15.62, h: 16.5, l: 15.3, c: 16.5, v: 3000 }],
  answer: {
    point: "B1", should_buy: true, ret_pct: 93.07, buy_price: 16.5,
    sealed: true, hold_days: 6, exit_date: "2024-11-21", exit_price: 31.9,
    exit_reason: "break_close",
  },
  explain: {
    kind: "hit", scheme_no: "B1", scheme_name: "B1 强开系·转温",
    scheme_row: {
      no: "B1", sub: "转温", name: "B1 强开系·转温",
      yang: "阴·打3板", b1: "≥7", b2: "≥7·换手≥5", b3: "—",
      today: "温开3~5", ground: "—", stat: "9笔·胜100%·均+23.2",
    },
    matched_line: "一板开+8.4 × 二板开+10.0(换手28.8) → 今开+4.2 落在窗3~5",
  },
};

const QUIZ_MISS_Q: HprQuizQuestion = {
  seq: 2, vt_symbol: "600398.SH", name: "齐心集团", decision_date: "2024-11-29",
  n_board: 3, group4: "三接四阳",
  display: {
    board_label: "打4板", b1_open: 1.3, b2_open: -3.1, b3_open: 10.0,
    b2_turn: 10.1, b3_turn: 1.1, pre20_pct: 4.4, pre10_pct: null,
    foundation_chg: 3.7, foundation_pose: "骑线" as const, foundation_ma20: 6.2, anchor_pos: null, auction_pct: 9.98,
    prev_close: 20.0, limit_price: 22.0, decision_open: 22.0, day_high_pct: 10.0,
    chain: "实体→一字→一字",
  },
  bars_before: [
    { d: "2024-11-25", o: 16.0, h: 16.8, l: 15.9, c: 16.6, v: 900 },   // 地基日 阳(c>o)
    { d: "2024-11-26", o: 16.6, h: 18.3, l: 16.5, c: 18.3, v: 1400 },  // 一板
    { d: "2024-11-27", o: 18.0, h: 20.0, l: 17.8, c: 20.0, v: 1800 },  // 二板
    { d: "2024-11-28", o: 18, h: 20, l: 17.5, c: 20, v: 2000 },        // 三板
  ],
  bars_after: [{ d: "2024-11-29", o: 22.0, h: 22.0, l: 21.5, c: 21.13, v: 5000 }],
  answer: {
    point: "—", should_buy: false, ret_pct: -5.64, buy_price: 22.0,
    sealed: false, hold_days: null, exit_date: "2024-11-29", exit_price: 20.76,
    exit_reason: "break_day_close",
  },
  explain: { kind: "miss", reasons: ["今开+10.0顶格:排队也买不到,口诀一律不打(硬规则)"], fail_fields: ["今开"] },
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
    expect(html).toContain("盘中最高");               // 第二决策信息(主人v5)
    expect(html).toContain("冲到9%+");
    expect(html).toContain("买入");
    expect(html).toContain("不买");
    // 阴阳组判定依据亮出:地基日格 + 徽标写全「·阴地基」(主人点名:阴阳不像正常逻辑)
    expect(html).toContain("打3板");
    expect(html).toContain("地基");
    expect(html).toContain("地基日 11-08");
    expect(html).toContain("阴地基");
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
    expect(html).toContain("B1 强开系·转温");     // 口诀子项全名(q31:与规则页速查表统一)
    expect(html).toContain("落在窗3~5");           // matched_line
    expect(html).toContain("温开3~5");             // 速查表行·今天开列(表格化讲解)
    expect(html).toContain("9笔·胜100%·均+23.2");  // 速查表行·成绩列
    expect(html).not.toContain("主力怎么想");       // 话术字段已删(q31)
    expect(html).not.toContain("典型样例");
    expect(html).toContain("断板日卖");              // 退出原因(v4.3:max(收盘,中间价))
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

  it("没按口诀买入:扣分横幅(v6对称-10)", () => {
    const html = renderRunner({
      questions: [QUIZ_MISS_Q],
      answers: { [quizQuestionId(QUIZ_MISS_Q)]: { choice: "buy", score: -10 } },
    });
    // miss 票 ret=-5.64,没按口诀买入亏损 → 横幅按当前矩阵现算 -10
    expect(html).toContain("没按口诀,这次判断错了");
    expect(html).toContain("-10");
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

// ── 手机适配(2026-10-01):手机类与桌面恢复位并存;fbb 侧逐字同款断言=双份同步防呆 ──

describe("QuizRunner 手机适配", () => {
  it("作答态:买/不买手机撑满一行(text-base 大字),桌面恢复 w-40 定宽", () => {
    const html = renderRunner();
    expect(html).toContain(
      "h-11 flex-1 rounded-md bg-rise text-base font-semibold text-white hover:bg-rise/90 md:w-40 md:flex-none md:text-sm",
    );
    expect(html).toContain(
      "h-11 flex-1 rounded-md border text-base font-semibold text-muted-foreground hover:bg-muted/40 md:w-40 md:flex-none md:text-sm",
    );
    // 信息面板:手机 2 列收紧列距,sm+ 恢复桌面列距(v6.8 加锚位/地基距格后 5 列·lg 10 列)
    expect(html).toContain("gap-x-3 gap-y-1.5 border-t px-4 py-3 text-xs sm:grid-cols-5 sm:gap-x-6");
    // 今开徽章(数字/阴阳字)不被适配破坏(v6.8 信息格重排后为 text-xs font-bold)
    expect(html).toContain("text-xs font-bold text-fall");
  });

  it("揭示态:下一题手机撑满,桌面恢复右对齐小钮", () => {
    const html = renderRunner({
      answers: { [quizQuestionId(QUIZ_HIT_Q)]: { choice: "buy", score: 10 } },
    });
    expect(html).toContain(
      "h-11 w-full rounded-md bg-primary text-base font-semibold text-primary-foreground hover:bg-primary/90 md:h-9 md:w-auto md:px-6 md:text-sm",
    );
    expect(html).toContain("flex md:justify-end");
  });

  it("深链 ?view=quiz 直达答题训练页签(刷新/书签不丢页签)", () => {
    const html = renderToStaticMarkup(
      withProviders(<ShortTermResearchPage />, ["/short-term?research=high-relay&view=quiz"]),
    );
    expect(html).toContain('id="hpr-view-quiz" type="button" role="tab" aria-selected="true"');
  });
});

describe("QuizKlineChart.visibleBarsForWidth 显示窗按容器宽分档", () => {
  it("375px 手机绘图区→32根,桌面→48根封顶,极窄下限24", () => {
    expect(visibleBarsForWidth(261)).toBe(32);   // 375px 机扣价格轴后的绘图区
    expect(visibleBarsForWidth(400)).toBe(48);   // 400/8=50 → 封顶 48
    expect(visibleBarsForWidth(936)).toBe(48);   // 桌面
    expect(visibleBarsForWidth(100)).toBe(24);   // 下限兜底
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

// ── 综合挑战卷(variant="mixed"):七条口诀好票+陷阱票跨月混编(主人定) ──
describe("QuizRunner 综合挑战卷(mixed)", () => {
  // 跨月题:decision_date=2025-03,与 QUIZ_HIT_Q(2024-11)混编——
  // 题干时间背景必须取各题自己的决策日(综合卷没有单一月份)
  const CROSS_MONTH_Q: HprQuizQuestion = {
    ...QUIZ_MISS_Q,
    vt_symbol: "603569.SSE",
    name: "长久物流",
    decision_date: "2025-03-12",
    n_board: 2,
    display: { ...QUIZ_MISS_Q.display, board_label: "打3板" },
    explain: {
      kind: "miss",
      trap_kind: "yin_yang",
      reasons: ["链形是口诀【A2 一字转强】的形态,但那条只在阳地基成立——这题是阴地基,阴阳反了不能打(跨阴阳铁律)"],
    },
  };

  function renderMixed(answers?: Record<string, { choice: "buy" | "reject"; score: number }>) {
    return renderToStaticMarkup(
      withProviders(
        <QuizRunner
          variant="mixed"
          questions={[CROSS_MONTH_Q]}
          rulesVersion="hpr-v4.4·q10"
          showName={false}
          answers={answers ?? {}}
          onAnswersChange={() => undefined}
          onBack={() => undefined}
        />,
      ),
    );
  }

  it("进度行与按钮用「本卷」口径,匿名题干取各题自己的决策年月", () => {
    const html = renderMixed();
    expect(html).toContain("本卷得分");
    expect(html).toContain("重置本卷");
    expect(html).toContain("← 返回");
    // mixed 无 month prop:题干显示 2025年3月 证明取的是该题 decision_date(跨月混编各自正确)
    expect(html).toContain("2025年3月 · 打3板");
  });

  it("已答跨月陷阱题:讲解含阴阳反串说明", () => {
    const html = renderMixed({
      [quizQuestionId(CROSS_MONTH_Q)]: { choice: "reject", score: 10 },
    });
    expect(html).toContain("阴阳反了不能打");
    expect(html).toContain("跨阴阳铁律");
  });
});
