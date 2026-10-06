import { useMemo, useState } from "react";

import type { HprCheatRow, HprQuizQuestion } from "@/api/highRelay";
import { CheatTableRow } from "@/features/highRelay/CheatTableRow";
import { cn, formatPct, formatPrice } from "@/lib/utils";

import { QuizKlineChart } from "./QuizKlineChart";
import type { QuizAnswerRec, QuizChoice, QuizMonthSummary } from "./quizScore";
import { isWrongAnswer, judge, quizQuestionId, simulateMonth, summarize } from "./quizScore";
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

// 方案点徽标配色(强市组八条 + 弱市组K系v7.1紫系;与 HprGuideView/HprLiveView 同色系)
const POINT_BADGES: Record<string, string> = {
  A1: "bg-rise/15 text-rise",
  A2: "bg-teal-500/15 text-teal-500",
  B1: "bg-amber-500/15 text-amber-500",
  B2: "bg-yellow-500/15 text-yellow-500",
  C1: "bg-emerald-500/15 text-emerald-500",
  A3: "bg-rose-500/15 text-rose-500",
  B3: "bg-orange-500/15 text-orange-500",
  C2: "bg-primary/15 text-primary",
  C3: "bg-primary/15 text-primary",
  K2: "bg-violet-500/15 text-violet-500",
  K4: "bg-violet-500/15 text-violet-500",
  K5: "bg-violet-500/15 text-violet-500",
  K7: "bg-violet-500/15 text-violet-500",
  K9: "bg-violet-500/15 text-violet-500",
  K3: "bg-violet-500/15 text-violet-500",
};

const TIER_STYLES: Record<string, string> = {
  great: "border-rise/50 bg-rise/10 text-rise",
  good: "border-primary/50 bg-primary/10 text-primary",
  lucky: "border-amber-500/50 bg-amber-500/10 text-amber-600",
  bad: "border-fall/50 bg-fall/10 text-fall",
};

const EXIT_REASON_LABELS: Record<string, string> = {
  break_day_close: "炸板次日卖",
  next_close_fail: "次日未涨停卖",
  break_close: "断板日卖",
  max_hold_close: "15日兜底卖",
};

type Board = 2 | 3;
type Phase = "quiz" | "boardSummary" | "monthSummary";

interface QuizRunnerProps {
  /** month 模式必填(显示用);mixed(综合挑战卷)跨月,标题改用各题 decision_date */
  month?: string;
  /** month=按月刷题(默认);mixed=综合挑战卷(两组口诀好票+陷阱票混编) */
  variant?: "month" | "mixed";
  questions: HprQuizQuestion[];
  rulesVersion: string;
  showName: boolean;
  /** 当前动态口诀组(weak/strong/both;v7.2 答题页自动拉,题头标注该时代口诀当前启用与否) */
  dynGroup?: string | null;
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
  dynGroup,
  answers,
  onAnswersChange,
  onBack,
}: QuizRunnerProps) {
  const mixed = variant === "mixed";
  // 范围标题:月题=x年x月;综合卷=「综合挑战卷」(进度行/总结卡共用)
  const scopeTitle = mixed
    ? "综合挑战卷"
    : `${Number((month ?? "0000-00").slice(0, 4))}年${Number((month ?? "0000-00").slice(5))}月`;
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
        scopeTitle={scopeTitle}
        unitLabel={mixed ? "本卷" : "本月"}
        summary={monthSummary}
        segments={[
          board3.length > 0 ? { label: "打3板", summary: summarize(board3, answers) } : null,
          board4.length > 0 ? { label: "打4板", summary: summarize(board4, answers) } : null,
        ].filter((s): s is { label: string; summary: QuizMonthSummary } => s != null)}
        questions={questions}
        answers={answers}
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
        scopeTitle={scopeTitle}
        unitLabel={mixed ? "本卷" : "本月"}
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
  // 匿名题干不带题号(乱序后题号无意义,防按序号背答案);时间背景取该题自己的
  // 决策日(综合卷跨月也能正确显示「x年x月」)
  // 判分红格(q32,主人「哪里不符合标红色」):miss 题判分后按 fail_fields 标红
  const failSet = new Set<string>(
    revealed && question.explain.kind === "miss"
      ? question.explain.fail_fields ?? []
      : [],
  );
  const dd = question.decision_date;
  // v7.3 逐月动态组标签:后端下发 dyn_state(该月启用哪组——月度滚动复现,无未来函数;
  // 2023 年 1~6 月=弱市组题/7 月起=强市组题;旧物化兜底按日期粗切)
  const weakEra = dd < "2023-01-01";
  const qState = question.dyn_state ?? (weakEra ? "weak" : "strong");
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
            className="py-2.5 text-xs text-muted-foreground hover:text-foreground md:py-0"
            onClick={onBack}
          >
            ← 返回
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
            本轮 {boardAnswered}/{activeQuestions.length} · {mixed ? "本卷" : "本月"}得分{" "}
            {monthSummary.score >= 0 ? "+" : ""}
            {monthSummary.score}
          </span>
          <button
            type="button"
            className="ml-auto py-2.5 text-xs text-muted-foreground hover:text-foreground md:py-0"
            onClick={handleReset}
          >
            重置{mixed ? "本卷" : "本月"}
          </button>
        </div>
      </section>

      <section className="rounded-lg border">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-3">
          <span className="text-sm font-semibold">{title}</span>
          <span
            className={cn(
              "rounded px-1.5 py-0.5 text-[10px] font-medium",
              qState === "weak"
                ? "bg-violet-500/15 text-violet-500 ring-1 ring-violet-500/40"
                : qState === "both"
                  ? "bg-muted text-muted-foreground ring-1 ring-muted-foreground/30"
                  : "bg-primary/10 text-primary",
            )}
            title={qState === "weak"
              ? "该月动态口诀组=弱市组:该买=K系命中(八条命中只是雷达)"
              : qState === "both"
                ? "该月双开(近12月样本不足的暖机期):两组任一命中即该买"
                : "该月动态口诀组=强市组:该买=A1~C3八条命中"}
          >
            {qState === "weak" ? "弱市组题" : qState === "both" ? "双开题" : "强市组题"}
          </span>
          {dynGroup ? (
            // v7.2/v7.3 联动「提取口诀」:这题所在月的口诀组,当前是否启用(实时推荐按它出手)
            (() => {
              const eraActive = qState === "both"
                ? true
                : qState === "weak"
                  ? dynGroup === "weak" || dynGroup === "both"
                  : dynGroup === "strong" || dynGroup === "both";
              return (
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[10px] font-medium",
                    eraActive
                      ? "bg-muted text-foreground"
                      : "bg-muted/50 text-muted-foreground",
                  )}
                  title="「近一年哪组口诀赚得多就用哪组」的当前判定——未启用≠口诀错了,是现在轮到另一组"
                >
                  {eraActive ? "当前启用中" : "当前未启用"}
                </span>
              );
            })()
          ) : null}
          {!showName ? (
            <span className="ml-auto text-[11px] text-muted-foreground">
              匿名模式（答完揭示票名）
            </span>
          ) : null}
        </div>

        <div className="p-2 md:p-3">
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

        <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 border-t px-4 py-3 text-xs sm:grid-cols-5 sm:gap-x-6 lg:grid-cols-11">
          {fBar ? (
            <InfoCell
              label={`地基日 ${fBar.d.slice(5)}`}
              value={fmtSigned(d.foundation_chg ?? Math.round((fBar.c / fBar.o - 1) * 1000) / 10)}
              extra={fBar.c >= fBar.o ? "阳地基" : "阴地基"}
              fail={failSet.has("地基日")}
            />
          ) : null}
          <InfoCell label="地基姿态" value={d.foundation_pose ?? "—"} fail={failSet.has("地基姿态")} />
          <InfoCell label="距前涨停高" value={fmtSigned(d.anchor_pos ?? null)} fail={failSet.has("距前涨停高")} />
          <InfoCell label="一板开" value={fmtSigned(d.b1_open)} fail={failSet.has("一板开")} />
          <InfoCell
            label="二板开"
            value={fmtSigned(d.b2_open)}
            extra={d.b2_turn != null ? `换手${d.b2_turn.toFixed(1)}` : undefined}
            fail={failSet.has("二板开")}
          />
          {question.n_board === 3 ? (
            <InfoCell
              label="三板开"
              value={fmtSigned(d.b3_open)}
              extra={d.b3_turn != null ? `换手${d.b3_turn.toFixed(1)}` : undefined}
              highlight
              fail={failSet.has("三板开")}
            />
          ) : null}
          <div
            className={cn(
              "rounded px-2 py-1.5",
              failSet.has("今开") ? "bg-fall/10 ring-1 ring-inset ring-fall/50" : "bg-primary/10",
            )}
          >
            <div className="flex items-baseline gap-1 leading-4">
              <span className="text-xs font-bold text-primary">{question.n_board + 1}</span>
              <span
                className={cn(
                  "text-xs font-bold",
                  failSet.has("阴阳")
                    ? "text-fall underline decoration-fall/60"
                    : question.group4.endsWith("阳")
                      ? "text-rise"
                      : "text-fall",
                )}
              >
                {question.group4.endsWith("阳") ? "阳" : "阴"}
              </span>
              <span className="text-[10px] text-muted-foreground">今开</span>
            </div>
            <div className={cn("font-mono text-sm tabular-nums", toneOf(fmtSigned(d.auction_pct)))}>
              {fmtSigned(d.auction_pct)}
            </div>
          </div>
          <InfoCell
            label="盘中最高"
            value={fmtSigned(d.day_high_pct)}
            extra={d.day_high_pct >= 9 ? "冲到9%+" : "未到9%"}
            highlight
          />
          <InfoCell label="首板前20日" value={fmtSigned(d.pre20_pct)} fail={failSet.has("首板前20日")} />
          <InfoCell label="首板前10日" value={fmtSigned(d.pre10_pct)} fail={failSet.has("首板前10日")} />
          {d.b1_turn != null ? (
            // v7.1 弱市组判定格(仅2020-22题下发):K4/K7 一板放量实体板腿(换手≥5)
            <InfoCell label="一板换手" value={`${d.b1_turn.toFixed(1)}`} fail={failSet.has("一板换手")} />
          ) : null}
          {d.prev_wave60 != null ? (
            // K5 命根:前波=0(60日没炒过);来过波的是二波残局
            <InfoCell
              label="前波60日"
              value={`${d.prev_wave60}板`}
              extra={d.prev_wave60 === 0 ? "没炒过" : "来过波"}
              fail={failSet.has("前波60日")}
            />
          ) : null}
          {d.dist_h60 != null ? (
            // K3 贴顶腿:距60日新高≥-8(套牢盘已消化)
            <InfoCell label="距新高" value={fmtSigned(d.dist_h60)} fail={failSet.has("距新高")} />
          ) : null}
          <InfoCell label="板型链" value={d.chain ?? "--"} plain />
        </div>

        {!revealed ? (
          <div className="border-t px-4 py-4">
            <div className="flex items-center justify-center gap-3 md:gap-4">
              <button
                type="button"
                className="h-11 flex-1 rounded-md bg-rise text-base font-semibold text-white hover:bg-rise/90 md:w-40 md:flex-none md:text-sm"
                onClick={() => handleAnswer("buy")}
              >
                买入
              </button>
              <button
                type="button"
                className="h-11 flex-1 rounded-md border text-base font-semibold text-muted-foreground hover:bg-muted/40 md:w-40 md:flex-none md:text-sm"
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
        "rounded-md border px-2.5 py-2 text-xs tabular-nums md:py-1",
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
            className="py-2.5 text-xs text-muted-foreground hover:text-foreground md:py-0"
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
            className="h-11 rounded-md bg-amber-500 px-4 text-sm font-semibold text-white hover:bg-amber-500/90 md:h-9"
            onClick={onRetry}
          >
            乱序重练本轮错题（{wrongCount}题）
          </button>
        ) : (
          <span className="text-xs text-muted-foreground">本轮无错题（违背口诀的题）</span>
        )}
        <button
          type="button"
          className="h-11 rounded-md border px-4 text-sm font-semibold text-muted-foreground hover:bg-muted/40 md:h-9"
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

/** 讲解卡速查表(hit=命中行/miss=最接近口诀行+红列,q34 主人「错误的口诀也给出表格,
 *  错误的某一列标红」);表头与规则页速查表一致(去掉口诀列——徽章已显示全名)。 */
function SchemeRowTable({ row, failCols }: { row: HprCheatRow | null; failCols?: string[] }) {
  if (!row) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-[11px]">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-1 pr-3 font-medium">组</th>
            <th className="py-1 pr-3 font-medium">一板</th>
            <th className="py-1 pr-3 font-medium">二板</th>
            <th className="py-1 pr-3 font-medium">三板</th>
            <th className="py-1 pr-3 font-medium">今天开</th>
            <th className="py-1 pr-3 font-medium">地基日</th>
            <th className="py-1 font-medium">成绩(E3)</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          <CheatTableRow row={row} showName={false} failCols={failCols} />
        </tbody>
      </table>
    </div>
  );
}

function InfoCell({
  label,
  value,
  extra,
  highlight,
  plain,
  fail,
}: {
  label: string;
  value: string;
  extra?: string;
  highlight?: boolean;
  plain?: boolean;
  fail?: boolean;   // 判分红格(q32):这格对应的腿不符合口诀,判分后标红
}) {
  return (
    <div
      className={cn(
        "rounded px-2 py-1.5",
        highlight && !fail && "bg-primary/10",
        fail && "bg-fall/10 ring-1 ring-inset ring-fall/50",
      )}
    >
      <div className={cn("text-[10px]", fail ? "font-semibold text-fall" : "text-muted-foreground")}>
        {label}
      </div>
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
          <SchemeRowTable row={ex.scheme_row} />
        </div>
      ) : (
        <div className="rounded-md border px-3 py-2.5">
          <div className="mb-1 text-xs font-semibold">为什么不买（对照口诀）</div>
          {ex.scheme_row ? (
            <div className="mb-2">
              <SchemeRowTable row={ex.scheme_row} failCols={ex.row_fails} />
            </div>
          ) : null}
          <ul className="list-disc space-y-1 pl-5 text-xs leading-5 text-muted-foreground">
            {ex.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
            <li>未命中的连板票是雷达，只看不做。</li>
          </ul>
        </div>
      )}

      <div className="flex md:justify-end">
        <button
          type="button"
          className="h-11 w-full rounded-md bg-primary text-base font-semibold text-primary-foreground hover:bg-primary/90 md:h-9 md:w-auto md:px-6 md:text-sm"
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
  questions: HprQuizQuestion[];
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
            className="py-2.5 text-xs text-muted-foreground hover:text-foreground md:py-0"
            onClick={onBack}
          >
            ← 返回
          </button>
          <button
            type="button"
            className="py-2.5 text-xs text-muted-foreground hover:text-foreground md:py-0"
            onClick={onRestart}
          >
            重新作答{unitLabel}
          </button>
        </span>
      </div>
      {summary.answered > 0 ? (
        <div className="mb-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
          <div className="rounded-md border px-3 py-2">
            <div className="mb-0.5 font-semibold">你的操作（答「买入」的票按E3收益计）</div>
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
