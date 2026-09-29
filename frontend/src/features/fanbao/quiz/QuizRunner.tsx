import { useMemo, useState } from "react";

import type { FbbQuizQuestion } from "@/api/fanbao";
import { cn, formatPct, formatPrice } from "@/lib/utils";

import { QuizKlineChart } from "./QuizKlineChart";
import type { QuizAnswerRec, QuizChoice, QuizMonthSummary } from "./quizScore";
import { isWrongAnswer, judge, quizQuestionId, simulateMonth, summarize } from "./quizScore";
import { overwriteAnswer, resetMonth, saveAnswer } from "./quizProgress";

/**
 * 单月答题流(交互核心):高度段勾选(单勾2板/4板/5+板=分开练,多勾=合并混做) →
 * 题干(默认匿名不带题号) → 截断K线(前波连板+断板期) → 信息面板 → 买/不买 →
 * 瞬时揭示(判定横幅 + 真实结果 + 口诀讲解卡) → 本轮总结 → 月度总结。
 *
 * 记忆加强设计(对齐 hpr,防背答案):
 * - 每次进入/切换高度段题目 Fisher-Yates 乱序——破掉「第几题选什么」的位置记忆;
 * - 匿名题干不显示题号,只显示「x年x月 · N板断X天」;
 * - 本轮错题(判分 lucky/bad=违背口诀的两档)可乱序重练,重练覆盖答案,
 *   答对出列、答错留池,成绩以最后一次为准。
 */

// 方案点徽标配色(S1/S2/S3;与 FbbGuideView/FbbLiveView 同色系)
const POINT_BADGES: Record<string, string> = {
  S1: "bg-rise/15 text-rise",
  S2: "bg-amber-500/15 text-amber-500",
  S3: "bg-primary/15 text-primary",
};

const TIER_STYLES: Record<string, string> = {
  great: "border-rise/50 bg-rise/10 text-rise",
  good: "border-primary/50 bg-primary/10 text-primary",
  lucky: "border-amber-500/50 bg-amber-500/10 text-amber-600",
  bad: "border-fall/50 bg-fall/10 text-fall",
};

const EXIT_REASON_LABELS: Record<string, string> = {
  break_day_close: "炸板次日卖(一字跌停顺延)",
  next_close_fail: "次日断板卖",
  break_close: "断板日卖",
  max_hold_close: "15日兜底卖",
};

type SegKey = "s2" | "s4" | "s5";
type Phase = "quiz" | "boardSummary" | "monthSummary";

interface QuizRunnerProps {
  /** month 模式必填(显示用);mixed(综合挑战卷)跨月,标题改用各题 decision_date */
  month?: string;
  /** month=按月刷题(默认);mixed=综合挑战卷(三条口诀好票+陷阱票混编) */
  variant?: "month" | "mixed";
  questions: FbbQuizQuestion[];
  rulesVersion: string;
  showName: boolean;
  answers: Record<string, QuizAnswerRec>;
  onAnswersChange: (next: Record<string, QuizAnswerRec>) => void;
  onBack: () => void;
}

export function QuizRunner({
  month,
  variant = "month",
  questions,
  rulesVersion,
  showName,
  answers,
  onAnswersChange,
  onBack,
}: QuizRunnerProps) {
  const mixed = variant === "mixed";
  // 范围标题:月题=x年x月;综合卷=「综合挑战卷」(进度行/总结卡共用)
  const scopeTitle = mixed
    ? "综合挑战卷"
    : `${Number((month ?? "0000-00").slice(0, 4))}年${Number((month ?? "0000-00").slice(5))}月`;
  // 高度段(2板/4板/5+板)勾选——单勾=分开练(三段口诀体系不同),多勾=合并混做
  const seg2 = useMemo(() => questions.filter((q) => q.n_board === 2), [questions]);
  const seg4 = useMemo(() => questions.filter((q) => q.n_board === 4), [questions]);
  const seg5 = useMemo(() => questions.filter((q) => q.n_board >= 5), [questions]);
  const segDefs: { key: SegKey; label: string; qs: FbbQuizQuestion[] }[] = [
    { key: "s2", label: "2板反包", qs: seg2 },
    { key: "s4", label: "4板反包", qs: seg4 },
    { key: "s5", label: "5+板反包", qs: seg5 },
  ];
  const firstSeg = segDefs.find((s) => s.qs.length > 0) ?? segDefs[0];

  const [sel, setSel] = useState<Record<SegKey, boolean>>(() => {
    const init = { s2: false, s4: false, s5: false };
    init[firstSeg.key] = true; // 默认只勾第一段有题的
    return init;
  });
  const activeQuestions = useMemo(() => {
    const out: FbbQuizQuestion[] = [];
    for (const def of segDefs) {
      if (sel[def.key]) out.push(...def.qs);
    }
    return out;
  }, [sel, seg2, seg4, seg5]);

  const [order, setOrder] = useState<number[]>(() => shuffled(firstSeg.qs.length));
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

  const toggleSeg = (key: SegKey) => {
    const next = { ...sel, [key]: !sel[key] };
    if (!next.s2 && !next.s4 && !next.s5) return; // 至少保留一个高度段
    setSel(next);
    const qs = segDefs.flatMap((def) => (next[def.key] ? def.qs : []));
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
        scopeTitle={scopeTitle}
        unitLabel={mixed ? "本卷" : "本月"}
        summary={monthSummary}
        segments={segDefs
          .filter((s) => s.qs.length > 0)
          .map((s) => ({ label: s.label, summary: summarize(s.qs, answers) }))}
        questions={questions}
        answers={answers}
        onRestart={handleReset}
        onBack={onBack}
      />
    );
  }

  if (phase === "boardSummary") {
    const onLabels = segDefs.filter((def) => sel[def.key]).map((def) => def.label);
    return (
      <BoardSummaryCard
        scopeTitle={scopeTitle}
        unitLabel={mixed ? "本卷" : "本月"}
        scopeLabel={onLabels.join("+")}
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
  // 匿名题干不带题号(乱序后题号无意义,防按序号背答案);时间背景取该题自己的
  // 决策日(综合卷跨月也能正确显示「x年x月」)
  const dd = question.decision_date;
  const title = showName
    ? `${question.name} ${question.vt_symbol.split(".")[0]}`
    : `${Number(dd.slice(0, 4))}年${Number(dd.slice(5, 7))}月 · ${d.board_label}`;
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
            ← 返回
          </button>
          <span className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">高度段</span>
            {segDefs
              .filter((def) => def.qs.length > 0)
              .map((def) => (
                <SegChip
                  key={def.key}
                  label={def.label}
                  selected={sel[def.key]}
                  answered={def.qs.filter((q) => answers[quizQuestionId(q)] != null).length}
                  total={def.qs.length}
                  onClick={() => toggleSeg(def.key)}
                />
              ))}
          </span>
          <span className="text-sm font-semibold tabular-nums">
            {retry ? (
              <span className="text-amber-600">错题重练 {idx + 1}/{order.length}</span>
            ) : (
              <>第 {idx + 1}/{order.length} 题</>
            )}
          </span>
          <span className="text-xs text-muted-foreground tabular-nums">
            本轮 {boardAnswered}/{activeQuestions.length} · {mixed ? "本卷" : "本月"}得分{" "}
            {monthSummary.score >= 0 ? "+" : ""}
            {monthSummary.score}
          </span>
          <button
            type="button"
            className="ml-auto text-xs text-muted-foreground hover:text-foreground"
            onClick={handleReset}
          >
            重置{mixed ? "本卷" : "本月"}
          </button>
        </div>
      </section>

      <section className="rounded-lg border">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-3">
          <span className="text-sm font-semibold">{title}</span>
          <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[11px] font-medium text-primary">
            {d.board_label}
          </span>
          <span className="text-xs text-muted-foreground">{d.group6_label}</span>
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
            auctionPct={d.today_open_pct}
            revealed={revealed}
            barsAfter={question.bars_after}
            buyPrice={a.buy_price}
            exitDate={a.exit_date}
            exitPrice={a.exit_price}
            retPct={a.ret_pct}
          />
        </div>

        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 border-t px-4 py-3 text-xs sm:grid-cols-4 lg:grid-cols-8">
          <InfoCell
            label="断板累计跌"
            value={fmtSigned(d.break_drop_pct)}
            extra={dropBand(d.break_drop_pct)}
          />
          <InfoCell
            label="断板期阴线"
            value={`${d.break_yin_count}根`}
            plain
          />
          <InfoCell
            label="末日开盘"
            value={fmtSigned(d.last_open_pct)}
            extra={d.last_open_pct != null && d.last_open_pct <= 0 ? "低/平开" : undefined}
          />
          <InfoCell label="末日实体" value={d.last_entity ?? "--"} plain />
          <InfoCell label="今开" value={fmtSigned(d.today_open_pct)} highlight />
          <InfoCell
            label="盘中最高"
            value={fmtSigned(d.day_high_pct)}
            extra="已触板"
            highlight
          />
          <InfoCell label="涨停价" value={d.limit_price != null ? formatPrice(d.limit_price) : "--"} plain />
          <InfoCell label="昨收" value={formatPrice(d.prev_close)} plain />
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
              现在就是触板瞬间：盘中已冲到涨停价——一般 8% 以上就该准备好，碰到涨停价按涨停价买，不等确认不分早晚
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

/** 断板累计跌幅的分档注记(口诀带:8~15=S1洗盘带) */
function dropBand(v: number | null): string | undefined {
  if (v == null) return undefined;
  if (v <= -15) return "跌过头";
  if (v <= -8) return "洗盘带";
  if (v >= 0) return "没跌";
  return undefined;
}

function SegChip({
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
  // 勾选式多选(chip 形态,checkbox 语义):选中打勾高亮,可多个都勾=合并混做
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
  scopeTitle,
  unitLabel,
  scopeLabel,
  total,
  summary,
  wrongCount,
  onRetry,
  onMonthSummary,
  onBack,
}: {
  scopeTitle: string;
  unitLabel: string;
  scopeLabel: string;
  total: number;
  summary: QuizMonthSummary;
  wrongCount: number;
  onRetry: () => void;
  onMonthSummary: () => void;
  onBack: () => void;
}) {
  const pct = summary.maxScore > 0
    ? Math.round((summary.score / summary.maxScore) * 100)
    : 0;
  return (
    <section className="rounded-lg border px-4 py-4">
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-sm font-semibold">
          {scopeTitle} · {scopeLabel} · 本轮总结
        </span>
        <span className="font-mono text-lg font-bold tabular-nums text-primary">
          得分 {summary.score >= 0 ? "+" : ""}
          {summary.score}
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">
          已答 {summary.answered}/{total} · 满分 {summary.maxScore}（达成 {pct}%）
        </span>
        <span className="ml-auto flex gap-3">
          <button
            type="button"
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={onBack}
          >
            ← 返回
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
          看{unitLabel}总结
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
  question: FbbQuizQuestion;
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
          <p className="whitespace-pre-line text-sm leading-6 text-foreground">{ex.scheme_desc}</p>
          {ex.case_note ? (
            <p className="mt-1 text-xs leading-5 text-primary">典型样例：{ex.case_note}</p>
          ) : null}
          {ex.high_var ? (
            <p className="mt-1 text-xs leading-5 text-amber-600">
              ⚠顶格开：末日开盘接近涨停价再砸下来，赢面五五开——赢了肉大输了-10%，
              要买就减半仓（S2 最大赢家日上集团就是顶格开，所以不剔除）。
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
            <li>未命中的断板票是雷达，只看不做。</li>
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
  scopeTitle,
  unitLabel,
  summary,
  segments,
  questions,
  answers,
  onRestart,
  onBack,
}: {
  scopeTitle: string;
  unitLabel: string;
  summary: QuizMonthSummary;
  segments: { label: string; summary: QuizMonthSummary }[];
  questions: FbbQuizQuestion[];
  answers: Record<string, QuizAnswerRec>;
  onRestart: () => void;
  onBack: () => void;
}) {
  const pnl = simulateMonth(questions, answers);
  const pct = summary.maxScore > 0
    ? Math.round((summary.score / summary.maxScore) * 100)
    : 0;
  return (
    <section className="rounded-lg border px-4 py-4">
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-sm font-semibold">
          {scopeTitle} · {unitLabel}总结
        </span>
        <span className="font-mono text-lg font-bold tabular-nums text-primary">
          总得分 {summary.score >= 0 ? "+" : ""}
          {summary.score}
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">
          已答 {summary.answered}/{summary.total} · 满分 {summary.maxScore}（达成 {pct}%）
        </span>
        <span className="ml-auto flex gap-3">
          <button
            type="button"
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={onBack}
          >
            ← 返回
          </button>
          <button
            type="button"
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={onRestart}
          >
            重新作答{unitLabel}
          </button>
        </span>
      </div>
      {summary.answered > 0 ? (
        <div className="mb-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
          <div className="rounded-md border px-3 py-2">
            <div className="mb-0.5 font-semibold">你的操作（答「买入」的票按持有到断板%计）</div>
            <div className="tabular-nums text-muted-foreground">
              出手 {pnl.mine.trades} 笔 · 胜率 {pnl.mine.win}% · {unitLabel}收益{" "}
              <span className={cn("font-mono font-semibold", pnl.mine.ret >= 0 ? "text-rise" : "text-fall")}>
                {pnl.mine.ret >= 0 ? "+" : ""}{pnl.mine.ret}%
              </span>
            </div>
          </div>
          <div className="rounded-md border px-3 py-2">
            <div className="mb-0.5 font-semibold">口诀标准操作（命中全买·未命中全拒）</div>
            <div className="tabular-nums text-muted-foreground">
              出手 {pnl.rule.trades} 笔 · 胜率 {pnl.rule.win}% · {unitLabel}收益{" "}
              <span className={cn("font-mono font-semibold", pnl.rule.ret >= 0 ? "text-rise" : "text-fall")}>
                {pnl.rule.ret >= 0 ? "+" : ""}{pnl.rule.ret}%
              </span>
            </div>
          </div>
        </div>
      ) : null}
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
