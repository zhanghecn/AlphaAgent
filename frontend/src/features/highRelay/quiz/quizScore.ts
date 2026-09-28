// 高位接力答题训练 · 判分(纯函数,组件与测试共用)
// 主人定的四档矩阵:
//   决策符合口诀 × 结果配合(买对赚钱/拒对躲过) → 大加分 +10
//   决策符合口诀 × 结果不配合(买对但亏/拒对踏空) → 小加分 +3
//   决策违背口诀 × 结果配合(瞎买侥幸赚/错拒躲过) → 小加分 +2
//   决策违背口诀 × 结果不配合(买亏/踏空大涨) → 扣分 -5
// 「结果」= 该事件按 E3 卖出纪律模拟的真实收益 ret_pct。

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
    return { matchesRule, favorable, score: 2, tier: "lucky",
             text: "违背口诀,这次侥幸对了" };
  }
  return { matchesRule, favorable, score: -5, tier: "bad",
           text: "违背口诀,代价实打实" };
}

export interface QuizMonthSummary {
  total: number;
  answered: number;
  score: number;
  great: number;
  good: number;
  lucky: number;
  bad: number;
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
    total: questions.length, answered: 0, score: 0,
    great: 0, good: 0, lucky: 0, bad: 0, byPoint: [],
  };
  const pointAcc = new Map<string, { n: number; correct: number }>();
  for (const q of questions) {
    const rec = answers[quizQuestionId(q)];
    if (!rec) continue;
    out.answered += 1;
    out.score += rec.score;
    const verdict = judge(q.answer.should_buy, q.answer.ret_pct ?? 0, rec.choice);
    out[verdict.tier] += 1;
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
