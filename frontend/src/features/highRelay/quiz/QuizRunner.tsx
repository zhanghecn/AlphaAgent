import { useMemo, useState } from "react";

import type { HprQuizQuestion } from "@/api/highRelay";
import { cn, formatPct, formatPrice } from "@/lib/utils";

import { QuizKlineChart } from "./QuizKlineChart";
import type { QuizAnswerRec, QuizChoice, QuizMonthSummary } from "./quizScore";
import { isWrongAnswer, judge, quizQuestionId, summarize } from "./quizScore";
import { overwriteAnswer, resetMonth, saveAnswer } from "./quizProgress";

/**
 * 单月答题流(交互核心):板位勾选(单勾打3板/打4板=分开练,两个都勾=合并混做) →
 * 题干(默认匿名不带题号) → 截断K线 → 信息面板 → 买/不买 →
 * 瞬时揭示(判定横幅 + 真实结果 + 口诀讲解卡) → 本轮总结 → 月度总结。
 *
 * 记忆加强设计(主人定,防背答案):
 * - 每次进入/切换板位题目 Fisher-Yates 乱序——破掉「第几题选什么」的位置记忆;
 * - 匿名题干不显示题号,只显示「x年x月 · 打N板」;
 * - 本轮错题(判分 lucky/bad=违背口诀的两档)可乱序重练,重练覆盖答案,
 *   答对出列、答错留池,成绩以最后一次为准。
 */

// 方案点徽标配色(与 HprGuideView/HprLiveView 同色系)
const POINT_BADGES: Record<string, string> = {
  A1: "bg-rise/15 text-rise",
  A2: "bg-teal-500/15 text-teal-500",
  B1: "bg-amber-500/15 text-amber-500",
  B2: "bg-yellow-500/15 text-yellow-500",
  B3: "bg-emerald-500/15 text-emerald-500",
  B4: "bg-orange-500/15 text-orange-500",
  E1: "bg-primary/15 text-primary",
  E2: "bg-sky-500/15 text-sky-500",
  E3: "bg-fuchsia-500/15 text-fuchsia-500",
};

const TIER_STYLES: Record<string, string> = {
  great: "border-rise/50 bg-rise/10 text-rise",
  good: "border-primary/50 bg-primary/10 text-primary",
  lucky: "border-amber-500/50 bg-amber-500/10 text-amber-600",
  bad: "border-fall/50 bg-fall/10 text-fall",
};

const EXIT_REASON_LABELS: Record<string, string> = {
  break_day_close: "炸板次日·中间价卖",
  next_close_fail: "次日未涨停·中间价卖",
  break_close: "断板日·中间价卖",
  max_hold_close: "15日兜底·中间价卖",
};

type Board = 2 | 3;
type Phase = "quiz" | "boardSummary" | "monthSummary";

interface QuizRunnerProps {
  month: string;
  questions: HprQuizQuestion[];
  rulesVersion: string;
  showName: boolean;
  answers: Record<string, QuizAnswerRec>;
  onAnswersChange: (next: Record<string, QuizAnswerRec>) => void;
  onBack: () => void;
}

export function QuizRunner({
  month,
  questions,
  rulesVersion,
  showName,
  answers,
  onAnswersChange,
  onBack,
}: QuizRunnerProps) {
  // 打3板(昨日2连板,n_board=2)与打4板(n_board=3):板位可勾选——
  // 单勾=分开练(A/B组与E组口诀体系不同),两个都勾=合并混做(主人定的交互)
  const board3 = useMemo(() => questions.filter((q) => q.n_board === 2), [questions]);
  const board4 = useMemo(() => questions.filter((q) => q.n_board === 3), [questions]);

  const [sel, setSel] = useState<{ b2: boolean; b3: boolean }>(() => ({
    b2: board3.length > 0,
    b3: board3.length === 0, // 打3板无题的月份默认落到打4板
  }));
  const activeQuestions = useMemo(() => {
    const out: HprQuizQuestion[] = [];
    if (sel.b2) out.push(...board3);
    if (sel.b3) out.push(...board4);
    return out;
  }, [sel, board3, board4]);

  const [order, setOrder] = useState<number[]>(() =>
    shuffled((board3.length > 0 ? board3 : board4).length),
  );
  const [idx, setIdx] = useState(0);
  const [phase, setPhase] = useState<Phase>("quiz");
  const [retry, setRetry] = useState(false);
  const [submitted, setSubmitted] = useState(false); // 重练模式:本题本轮是否已提交

  const monthSummary = useMemo(() => summarize(questions, answers), [questions, answers]);
  const boardSummary = useMemo(
    () => summarize(activeQuestions, answers),
    [activeQuestions, answers],
  );
  const wrongCount = useMemo(
    () =>
      activeQuestions.filter((q) => isWrongAnswer(q, answers[quizQuestionId(q)])).length,
    [activeQuestions, answers],
  );

  if (questions.length === 0 || activeQuestions.length === 0) return null;

  const question = activeQuestions[order[Math.min(idx, order.length - 1)]];
  const qid = quizQuestionId(question);
  const answered = answers[qid] ?? null;
  // 首答:已答即揭示(回看);重练:错题都有旧答案,只看本轮是否重新提交
  const revealed = retry ? submitted : answered != null;
  const verdict = revealed
    ? judge(question.answer.should_buy, question.answer.ret_pct ?? 0, answers[qid]!.choice)
    : null;

  const toggleBoard = (b: Board) => {
    const next = b === 2 ? { ...sel, b2: !sel.b2 } : { ...sel, b3: !sel.b3 };
    if (!next.b2 && !next.b3) return; // 至少保留一个板位
    setSel(next);
    const qs = [...(next.b2 ? board3 : []), ...(next.b3 ? board4 : [])];
    setOrder(shuffled(qs.length));
    setIdx(0);
    setPhase("quiz");
    setRetry(false);
    setSubmitted(false);
  };

  const startRetry = () => {
    const wrongIdxs = activeQuestions
      .map((q, i) => ({ q, i }))
      .filter(({ q }) => isWrongAnswer(q, answers[quizQuestionId(q)]))
      .map(({ i }) => i);
    setOrder(shuffleArr(wrongIdxs));
    setIdx(0);
    setPhase("quiz");
    setRetry(true);
    setSubmitted(false);
  };

  const handleAnswer = (choice: QuizChoice) => {
    if (revealed) return;
    const v = judge(question.answer.should_buy, question.answer.ret_pct ?? 0, choice);
    const rec = { choice, score: v.score };
    onAnswersChange(
      retry
        ? overwriteAnswer(rulesVersion, qid, rec) // 重练允许覆盖(错题出列/留池)
        : saveAnswer(rulesVersion, qid, rec),
    );
    if (retry) setSubmitted(true);
  };

  const goNext = () => {
    setSubmitted(false);
    if (idx + 1 < order.length) {
      setIdx(idx + 1);
    } else {
      setPhase("boardSummary");
    }
  };

  const handleReset = () => {
    onAnswersChange(resetMonth(rulesVersion, questions));
    setOrder(shuffled(activeQuestions.length));
    setIdx(0);
    setPhase("quiz");
    setRetry(false);
    setSubmitted(false);
  };

  if (phase === "monthSummary") {
    return (
      <MonthSummary
        month={month}
        summary={monthSummary}
        segments={[
          board3.length > 0 ? { label: "打3板", summary: summarize(board3, answers) } : null,
          board4.length > 0 ? { label: "打4板", summary: summarize(board4, answers) } : null,
        ].filter((s): s is { label: string; summary: QuizMonthSummary } => s != null)}
        onRestart={handleReset}
        onBack={onBack}
      />
    );
  }

  if (phase === "boardSummary") {
    const scopeLabel =
      sel.b2 && sel.b3 ? "打3板+打4板" : sel.b2 ? "打3板" : "打4板";
    return (
      <BoardSummaryCard
        month={month}
        scopeLabel={scopeLabel}
        total={activeQuestions.length}
        summary={boardSummary}
        wrongCount={wrongCount}
        onRetry={startRetry}
        onMonthSummary={() => setPhase("monthSummary")}
        onBack={onBack}
      />
    );
  }

  const d = question.display;
  const a = question.answer;
  // 地基日 = 首板前一天(bars_before 倒数第 n_board+1 根):阴阳组的判定依据——
  // 阴地基=启动前还在跌/洗盘,阳地基=前一天已在涨的顺势加速;亮出来对照K线(主人点名)
  const fBar =
    question.bars_before.length > question.n_board
      ? question.bars_before[question.bars_before.length - (question.n_board + 1)]
      : null;
  // 匿名题干不带题号(乱序后题号无意义,防按序号背答案)
  const title = showName
    ? `${question.name} ${question.vt_symbol.split(".")[0]}`
    : `${Number(month.slice(0, 4))}年${Number(month.slice(5))}月 · ${d.board_label}`;
  const boardAnswered = activeQuestions.filter(
    (q) => answers[quizQuestionId(q)] != null,
  ).length;

  return (
    <div className="space-y-4">
      <section className="rounded-lg border px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <button
            type="button"
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={onBack}
          >
            ← 返回月份
          </button>
          <span className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">板位</span>
            {board3.length > 0 ? (
              <BoardChip
                label="打3板"
                selected={sel.b2}
                answered={board3.filter((q) => answers[quizQuestionId(q)] != null).length}
                total={board3.length}
                onClick={() => toggleBoard(2)}
              />
            ) : null}
            {board4.length > 0 ? (
              <BoardChip
                label="打4板"
                selected={sel.b3}
                answered={board4.filter((q) => answers[quizQuestionId(q)] != null).length}
                total={board4.length}
                onClick={() => toggleBoard(3)}
              />
            ) : null}
          </span>
          <span className="text-sm font-semibold tabular-nums">
            {retry ? (
              <span className="text-amber-600">错题重练 {idx + 1}/{order.length}</span>
            ) : (
              <>第 {idx + 1}/{order.length} 题</>
            )}
          </span>
          <span className="text-xs text-muted-foreground tabular-nums">
            本轮 {boardAnswered}/{activeQuestions.length} · 本月得分{" "}
            {monthSummary.score >= 0 ? "+" : ""}
            {monthSummary.score}
          </span>
          <button
            type="button"
            className="ml-auto text-xs text-muted-foreground hover:text-foreground"
            onClick={handleReset}
          >
            重置本月
          </button>
        </div>
      </section>

      <section className="rounded-lg border">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-3">
          <span className="text-sm font-semibold">{title}</span>
          <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[11px] font-medium text-primary">
            {d.board_label}
          </span>
          <span className="text-xs text-muted-foreground">
            {question.group4.replace(/(阴|阳)$/, "·$1地基")}
          </span>
          {!showName ? (
            <span className="ml-auto text-[11px] text-muted-foreground">
              匿名模式（答完揭示票名）
            </span>
          ) : null}
        </div>

        <div className="p-3">
          <QuizKlineChart
            barsBefore={question.bars_before}
            decisionDate={question.decision_date}
            decisionOpen={d.decision_open}
            auctionPct={d.auction_pct}
            revealed={revealed}
            barsAfter={question.bars_after}
            buyPrice={a.buy_price}
            exitDate={a.exit_date}
            exitPrice={a.exit_price}
            retPct={a.ret_pct}
          />
        </div>

        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 border-t px-4 py-3 text-xs sm:grid-cols-4 lg:grid-cols-8">
          {fBar ? (
            <InfoCell
              label={`地基日 ${fBar.d.slice(5)}`}
              value={fmtSigned(Math.round((fBar.c / fBar.o - 1) * 1000) / 10)}
              extra={fBar.c >= fBar.o ? "阳地基" : "阴地基"}
            />
          ) : null}
          <InfoCell label="一板开" value={fmtSigned(d.b1_open)} />
          <InfoCell
            label="二板开"
            value={fmtSigned(d.b2_open)}
            extra={d.b2_turn != null ? `换手${d.b2_turn.toFixed(1)}` : undefined}
          />
          {question.n_board === 3 ? (
            <InfoCell
              label="三板开"
              value={fmtSigned(d.b3_open)}
              extra={d.b3_turn != null ? `换手${d.b3_turn.toFixed(1)}` : undefined}
              highlight
            />
          ) : null}
          <InfoCell label="今开" value={fmtSigned(d.auction_pct)} highlight />
          <InfoCell
            label="盘中最高"
            value={fmtSigned(d.day_high_pct)}
            extra={d.day_high_pct >= 9 ? "冲到9%+" : "未到9%"}
            highlight
          />
          <InfoCell label="首板前20日" value={fmtSigned(d.pre20_pct)} />
          <InfoCell label="板型链" value={d.chain ?? "--"} plain />
        </div>

        {!revealed ? (
          <div className="border-t px-4 py-4">
            <div className="flex items-center justify-center gap-4">
              <button
                type="button"
                className="h-11 w-40 rounded-md bg-rise text-sm font-semibold text-white hover:bg-rise/90"
                onClick={() => handleAnswer("buy")}
              >
                买入
              </button>
              <button
                type="button"
                className="h-11 w-40 rounded-md border text-sm font-semibold text-muted-foreground hover:bg-muted/40"
                onClick={() => handleAnswer("reject")}
              >
                不买
              </button>
            </div>
            <p className="mt-2 text-center text-[11px] text-muted-foreground">
              打板类=触涨停价买；低吸类=低开直接买（收益统一按触板价口径）
            </p>
          </div>
        ) : (
          <RevealSection
            question={question}
            choice={answers[qid]!.choice}
            verdictText={verdict!.text}
            verdictTier={verdict!.tier}
            verdictScore={verdict!.score}
            onNext={goNext}
            isLast={idx + 1 >= order.length}
          />
        )}
      </section>
    </div>
  );
}

function BoardChip({
  label,
  selected,
  answered,
  total,
  onClick,
}: {
  label: string;
  selected: boolean;
  answered: number;
  total: number;
  onClick: () => void;
}) {
  // 勾选式多选(chip 形态,checkbox 语义):选中打勾高亮,可两个都勾=合并混做
  return (
    <button
      type="button"
      className={cn(
        "rounded-md border px-2.5 py-1 text-xs tabular-nums",
        selected
          ? "border-primary bg-primary/10 font-semibold text-primary"
          : "text-muted-foreground hover:bg-muted/40",
      )}
      onClick={onClick}
    >
      {selected ? "✓ " : ""}
      {label} {answered}/{total}
    </button>
  );
}

function BoardSummaryCard({
  month,
  scopeLabel,
  total,
  summary,
  wrongCount,
  onRetry,
  onMonthSummary,
  onBack,
}: {
  month: string;
  scopeLabel: string;
  total: number;
  summary: QuizMonthSummary;
  wrongCount: number;
  onRetry: () => void;
  onMonthSummary: () => void;
  onBack: () => void;
}) {
  return (
    <section className="rounded-lg border px-4 py-4">
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-sm font-semibold">
          {Number(month.slice(0, 4))}年{Number(month.slice(5))}月 · {scopeLabel} · 本轮总结
        </span>
        <span className="font-mono text-lg font-bold tabular-nums text-primary">
          得分 {summary.score >= 0 ? "+" : ""}
          {summary.score}
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">
          已答 {summary.answered}/{total}
        </span>
        <span className="ml-auto flex gap-3">
          <button
            type="button"
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={onBack}
          >
            ← 返回月份
          </button>
        </span>
      </div>
      <TierGrid summary={summary} />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        {wrongCount > 0 ? (
          <button
            type="button"
            className="h-9 rounded-md bg-amber-500 px-4 text-sm font-semibold text-white hover:bg-amber-500/90"
            onClick={onRetry}
          >
            乱序重练本轮错题（{wrongCount}题）
          </button>
        ) : (
          <span className="text-xs text-muted-foreground">本轮无错题（违背口诀的题）</span>
        )}
        <button
          type="button"
          className="h-9 rounded-md border px-4 text-sm font-semibold text-muted-foreground hover:bg-muted/40"
          onClick={onMonthSummary}
        >
          看月度总结
        </button>
      </div>
    </section>
  );
}

function TierGrid({ summary }: { summary: QuizMonthSummary }) {
  return (
    <div>
      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div className={cn("rounded-md border px-3 py-2", TIER_STYLES.great)}>
          口诀对行情也对 <span className="font-mono font-semibold">{summary.great}</span> 题
        </div>
        <div className={cn("rounded-md border px-3 py-2", TIER_STYLES.good)}>
          口诀对行情不配合 <span className="font-mono font-semibold">{summary.good}</span> 题
        </div>
        <div className={cn("rounded-md border px-3 py-2", TIER_STYLES.lucky)}>
          没按口诀但判断对 <span className="font-mono font-semibold">{summary.lucky}</span> 题
        </div>
        <div className={cn("rounded-md border px-3 py-2", TIER_STYLES.bad)}>
          没按口诀判断错了 <span className="font-mono font-semibold">{summary.bad}</span> 题
        </div>
      </div>
      {summary.answered > 0 ? (
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs tabular-nums text-muted-foreground">
          <span>
            口诀维度·与口诀一致{" "}
            <span className="font-semibold text-foreground">
              {summary.ruleMatched}/{summary.answered}
            </span>
          </span>
          <span>
            市场维度·方向判断正确{" "}
            <span className="font-semibold text-foreground">
              {summary.marketRight}/{summary.answered}
            </span>
          </span>
        </div>
      ) : null}
    </div>
  );
}

function InfoCell({
  label,
  value,
  extra,
  highlight,
  plain,
}: {
  label: string;
  value: string;
  extra?: string;
  highlight?: boolean;
  plain?: boolean;
}) {
  return (
    <div className={cn("rounded px-2 py-1.5", highlight && "bg-primary/10")}>
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={cn("font-mono text-sm tabular-nums", !plain && toneOf(value))}>
        {value}
        {extra ? (
          <span className="ml-1 text-[10px] text-muted-foreground">{extra}</span>
        ) : null}
      </div>
    </div>
  );
}

function RevealSection({
  question,
  choice,
  verdictText,
  verdictTier,
  verdictScore,
  onNext,
  isLast,
}: {
  question: HprQuizQuestion;
  choice: QuizChoice;
  verdictText: string;
  verdictTier: string;
  verdictScore: number;
  onNext: () => void;
  isLast: boolean;
}) {
  const a = question.answer;
  const ex = question.explain;
  return (
    <div className="space-y-3 border-t px-4 py-4">
      <div
        className={cn(
          "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2",
          TIER_STYLES[verdictTier],
        )}
      >
        <span className="font-mono text-lg font-bold tabular-nums">
          {verdictScore >= 0 ? "+" : ""}
          {verdictScore}
        </span>
        <span className="text-sm font-semibold">{verdictText}</span>
        <span className="text-xs">
          你选了「{choice === "buy" ? "买入" : "不买"}」· 标准答案「
          {a.should_buy ? "买入" : "不买"}」
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs tabular-nums">
        <span className="font-semibold text-foreground">
          {question.name}
          <span className="ml-1 font-mono text-muted-foreground">{question.vt_symbol}</span>
        </span>
        <span className="text-muted-foreground">{question.decision_date}</span>
        <span>买价 {formatPrice(a.buy_price)}</span>
        <span>
          {a.exit_date} {EXIT_REASON_LABELS[a.exit_reason ?? ""] ?? "卖出"}
          {a.exit_price != null ? ` ${formatPrice(a.exit_price)}` : ""}
        </span>
        {a.hold_days != null ? <span>持有 {a.hold_days} 天</span> : null}
        <span
          className={cn(
            "font-mono font-semibold",
            a.ret_pct != null && a.ret_pct >= 0 ? "text-rise" : "text-fall",
          )}
        >
          收益 {a.ret_pct != null ? formatPct(a.ret_pct) : "--"}
        </span>
        {!a.sealed ? <span className="text-muted-foreground">（当天炸板）</span> : null}
      </div>

      {ex.kind === "hit" ? (
        <div className="rounded-md border px-3 py-2.5">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[11px] font-medium",
                POINT_BADGES[ex.scheme_no],
              )}
            >
              {ex.scheme_name}
            </span>
            <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
              {ex.matched_line}
            </span>
          </div>
          <p className="text-xs leading-5 text-foreground">{ex.scheme_desc}</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            主力怎么想：{ex.psycho}
          </p>
          {ex.case_note ? (
            <p className="mt-1 text-xs leading-5 text-primary">典型样例：{ex.case_note}</p>
          ) : null}
          {ex.half_mountain ? (
            <p className="mt-1 text-xs leading-5 text-amber-600">
              注记：这题首板前20日涨幅在5~15半山腰毒档，口诀命中但背景打折，仓位要轻。
            </p>
          ) : null}
        </div>
      ) : (
        <div className="rounded-md border px-3 py-2.5">
          <div className="mb-1 text-xs font-semibold">为什么不买（对照口诀）</div>
          <ul className="list-disc space-y-1 pl-5 text-xs leading-5 text-muted-foreground">
            {ex.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
            <li>未命中的连板票是雷达，只看不做。</li>
          </ul>
        </div>
      )}

      <div className="flex justify-end">
        <button
          type="button"
          className="h-9 rounded-md bg-primary px-6 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
          onClick={onNext}
        >
          {isLast ? "看本段总结" : "下一题"}
        </button>
      </div>
    </div>
  );
}

function MonthSummary({
  month,
  summary,
  segments,
  onRestart,
  onBack,
}: {
  month: string;
  summary: QuizMonthSummary;
  segments: { label: string; summary: QuizMonthSummary }[];
  onRestart: () => void;
  onBack: () => void;
}) {
  return (
    <section className="rounded-lg border px-4 py-4">
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-sm font-semibold">
          {Number(month.slice(0, 4))}年{Number(month.slice(5))}月 · 本月总结
        </span>
        <span className="font-mono text-lg font-bold tabular-nums text-primary">
          总得分 {summary.score >= 0 ? "+" : ""}
          {summary.score}
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">
          已答 {summary.answered}/{summary.total}
        </span>
        <span className="ml-auto flex gap-3">
          <button
            type="button"
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={onBack}
          >
            ← 返回月份
          </button>
          <button
            type="button"
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={onRestart}
          >
            重新作答本月
          </button>
        </span>
      </div>
      {segments.length > 1 ? (
        <div className="mb-3 flex flex-wrap gap-3 text-xs tabular-nums text-muted-foreground">
          {segments.map((seg) => (
            <span key={seg.label} className="rounded bg-muted/40 px-2 py-1">
              {seg.label}：得分 {seg.summary.score >= 0 ? "+" : ""}
              {seg.summary.score} · 已答 {seg.summary.answered}/{seg.summary.total}
            </span>
          ))}
        </div>
      ) : null}
      <TierGrid summary={summary} />
      {summary.byPoint.length > 0 ? (
        <div className="mt-3">
          <div className="mb-1 text-xs font-semibold">按口诀分组（你答「与口诀一致」的比例）</div>
          <div className="flex flex-wrap gap-2">
            {summary.byPoint.map((row) => (
              <span
                key={row.point}
                className={cn(
                  "rounded px-2 py-1 text-[11px] tabular-nums",
                  POINT_BADGES[row.point] ?? "bg-muted/40",
                )}
              >
                {row.point} {row.correct}/{row.n}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

/** Fisher-Yates 洗牌(每次进段/重练调用——题目顺序不固定,防背答案) */
function shuffleArr<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function shuffled(n: number): number[] {
  return shuffleArr(Array.from({ length: n }, (_, i) => i));
}

function fmtSigned(v: number | null): string {
  if (v == null) return "--";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}`;
}

function toneOf(value: string): string {
  if (value.startsWith("+")) return "text-rise";
  if (value.startsWith("-")) return "text-fall";
  return "";
}
