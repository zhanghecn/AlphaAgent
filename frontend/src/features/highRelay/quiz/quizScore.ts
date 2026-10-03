// 高位接力答题训练 · 判分(纯函数,组件与测试共用)
// 主人定的四档矩阵(v6 对称化:全对+10则全错-10,主人:「口诀错了收益错了才-5?」):
//   决策符合口诀 × 结果配合(买对赚钱/拒对躲过) → 满分 +10
//   决策符合口诀 × 结果不配合(买对但亏/拒对踏空) → 小加分 +3(决策对,不怪你)
//   没按口诀 × 结果配合(自己分析判断对了) → 中加分 +5(主人:不是侥幸,是真实能力)
//   没按口诀 × 结果不配合(双错) → 扣分 -10(与全对对称)
// 「结果」= 该事件按 E3 卖出纪律模拟的真实收益 ret_pct(v6.5:纯收盘价+跌停顺延)。

import type { HprQuizQuestion } from "@/api/highRelay";

export type QuizChoice = "buy" | "reject";
export type QuizTier = "great" | "good" | "lucky" | "bad";

export interface QuizVerdict {
  matchesRule: boolean;  // 决策与口诀一致
  favorable: boolean;    // 结果配合(买则涨/拒则跌;恰平算配合买,对齐好票口径)
  score: number;         // +10/+3/+2/-5
  tier: QuizTier;
  text: string;          // 判定横幅文案
}

export function judge(
  shouldBuy: boolean,
  retPct: number,
  choice: QuizChoice,
): QuizVerdict {
  const matchesRule = (choice === "buy") === shouldBuy;
  const favorable = choice === "buy" ? retPct >= 0 : retPct < 0;
  if (matchesRule && favorable) {
    return { matchesRule, favorable, score: 10, tier: "great",
             text: "口诀对,行情也对" };
  }
  if (matchesRule) {
    return { matchesRule, favorable, score: 3, tier: "good",
             text: "口诀对,这次行情不配合" };
  }
  if (favorable) {
    return { matchesRule, favorable, score: 5, tier: "lucky",
             text: "没按口诀,但你判断对了" };
  }
  return { matchesRule, favorable, score: -10, tier: "bad",
           text: "没按口诀,这次判断错了" };
}

export interface QuizMonthSummary {
  total: number;
  answered: number;
  score: number;
  maxScore: number;      // 满分参照 = 已答题数 × 10(全部双对;主人要的整体满分锚点)
  great: number;
  good: number;
  lucky: number;
  bad: number;
  // 双维度统计(主人v5):口诀维度=你的选择与口诀一致;市场维度=你的选择方向与真实走势一致
  ruleMatched: number;   // 与口诀一致的题数
  marketRight: number;   // 市场判断正确的题数(favorable:买则涨/拒则跌)
  // 按口诀分组的对错(只统计命中题): [{point, n, correct}]
  byPoint: { point: string; n: number; correct: number }[];
}

export interface QuizAnswerRec {
  choice: QuizChoice;
  score: number;
}

export function summarize(
  questions: HprQuizQuestion[],
  answers: Record<string, QuizAnswerRec>,
): QuizMonthSummary {
  const out: QuizMonthSummary = {
    total: questions.length, answered: 0, score: 0, maxScore: 0,
    great: 0, good: 0, lucky: 0, bad: 0,
    ruleMatched: 0, marketRight: 0, byPoint: [],
  };
  const pointAcc = new Map<string, { n: number; correct: number }>();
  for (const q of questions) {
    const rec = answers[quizQuestionId(q)];
    if (!rec) continue;
    out.answered += 1;
    // 分值按当前矩阵现算(不用存储的历史分——判分规则升级后旧进度自动按新规则计)
    const verdict = judge(q.answer.should_buy, q.answer.ret_pct ?? 0, rec.choice);
    out.score += verdict.score;
    out.maxScore += 10;
    out[verdict.tier] += 1;
    if (verdict.matchesRule) out.ruleMatched += 1;
    if (verdict.favorable) out.marketRight += 1;
    if (q.answer.point !== "—") {
      const acc = pointAcc.get(q.answer.point) ?? { n: 0, correct: 0 };
      acc.n += 1;
      if (verdict.matchesRule) acc.correct += 1;
      pointAcc.set(q.answer.point, acc);
    }
  }
  out.byPoint = [...pointAcc.entries()]
    .map(([point, v]) => ({ point, ...v }))
    .sort((a, b) => a.point.localeCompare(b.point));
  return out;
}

export function quizQuestionId(q: Pick<HprQuizQuestion, "decision_date" | "vt_symbol">) {
  return `${q.decision_date}|${q.vt_symbol}`;
}

/** 错题判定(错题重练的入选条件):当前答案判分落在违背口诀的两档(lucky 侥幸对 / bad 实打实错)。
 *  答对的题(great/good)不重练——记忆加强的逻辑是让错题反复出现直到答对。 */
export function isWrongAnswer(
  q: HprQuizQuestion,
  rec: QuizAnswerRec | undefined,
): boolean {
  if (!rec) return false;
  const v = judge(q.answer.should_buy, q.answer.ret_pct ?? 0, rec.choice);
  return v.tier === "lucky" || v.tier === "bad";
}

export interface QuizMonthPnl {
  trades: number;   // 出手笔数
  win: number;      // 胜率%
  ret: number;      // 合计收益%(每票等权一份,固定本金不复利)
}

/** 本月收益测算(主人要的「答完看这个月赚多少」):你的操作=答买入的题按E3收益计,
 *  口诀标准操作=命中题全买、未命中全拒——两者并列,直接看你与口诀的差距。 */
export function simulateMonth(
  questions: HprQuizQuestion[],
  answers: Record<string, QuizAnswerRec>,
): { mine: QuizMonthPnl; rule: QuizMonthPnl } {
  const mine: QuizMonthPnl = { trades: 0, win: 0, ret: 0 };
  const rule: QuizMonthPnl = { trades: 0, win: 0, ret: 0 };
  for (const q of questions) {
    const ret = q.answer.ret_pct ?? 0;
    if (q.answer.should_buy) {
      rule.trades += 1;
      rule.ret += ret;
      if (ret >= 0) rule.win += 1;
    }
    const rec = answers[quizQuestionId(q)];
    if (rec?.choice === "buy") {
      mine.trades += 1;
      mine.ret += ret;
      if (ret >= 0) mine.win += 1;
    }
  }
  mine.win = mine.trades > 0 ? Math.round((mine.win / mine.trades) * 100) : 0;
  rule.win = rule.trades > 0 ? Math.round((rule.win / rule.trades) * 100) : 0;
  mine.ret = Math.round(mine.ret * 10) / 10;
  rule.ret = Math.round(rule.ret * 10) / 10;
  return { mine, rule };
}
