import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchHprQuizMixed, fetchHprQuizOverview, fetchHprQuizQuestions } from "@/api/highRelay";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { cn } from "@/lib/utils";

import { QuizRunner } from "./QuizRunner";
import type { QuizAnswerRec } from "./quizScore";
import { loadProgress, resetAll } from "./quizProgress";

/**
 * 答题训练页签根:综合挑战卷(七条口诀好票+陷阱票随机混编) + 年份 chip →
 * 月份格子(题数/进度/得分) → QuizRunner。
 * 进度存 localStorage(key 含题库版本串);默认匿名,实名开关切题干显示。
 */
export function HprQuizView() {
  const overviewQuery = useQuery({
    queryKey: ["hprQuizOverview"],
    queryFn: fetchHprQuizOverview,
    staleTime: 300_000,
  });
  const overview = overviewQuery.data;
  const rulesVersion = overview?.rules_version ?? "unknown";

  const years = useMemo(
    () => (overview?.status === "ok" ? overview.years ?? [] : []),
    [overview],
  );
  const [year, setYear] = useState<string | null>(null);
  const [month, setMonth] = useState<string | null>(null);
  // 综合挑战卷:nonce=null 未进卷;每点一次「开始挑战」+1 → queryKey 变 →
  // 强制重新随机抽题(禁缓存,主人要每次重抽不重样);mixYear=null 全库,
  // 指定年=只在该年抽(主人定:按年份练市场环境)
  const [mixYear, setMixYear] = useState<string | null>(null);
  const [mixedNonce, setMixedNonce] = useState<number | null>(null);
  const [showName, setShowName] = useState(false);
  const [answers, setAnswers] = useState<Record<string, QuizAnswerRec>>({});
  const [progressLoaded, setProgressLoaded] = useState(false);

  // 题库版本到位后加载本地进度(版本变→key 变→旧进度自然作废)
  if (overview?.status === "ok" && !progressLoaded) {
    setAnswers(loadProgress(rulesVersion));
    setProgressLoaded(true);
  }

  const activeYear = year ?? years[years.length - 1]?.year ?? null;
  const activeMonths = years.find((y) => y.year === activeYear)?.months ?? [];

  const questionsQuery = useQuery({
    queryKey: ["hprQuizQuestions", month],
    queryFn: () => fetchHprQuizQuestions(month!),
    enabled: month != null,
    staleTime: 600_000,
  });

  const mixedQuery = useQuery({
    queryKey: ["hprQuizMixed", mixedNonce, mixYear],
    queryFn: () => fetchHprQuizMixed(mixYear ?? undefined),
    enabled: mixedNonce != null,
    staleTime: 0,
    gcTime: 0,
  });

  if (overviewQuery.isLoading && !overview) return <LoadingState rows={6} />;
  if (overviewQuery.isError || !overview) {
    return <ErrorState message="答题题库暂时不可用" onRetry={() => void overviewQuery.refetch()} />;
  }
  if (overview.status !== "ok") {
    return (
      <EmptyState
        message="答题题库尚未生成"
        description="题库随回测一起重建——请到「回测」页签触发一次重算，完成后回来即可做题。"
      />
    );
  }

  if (mixedNonce != null) {
    const questions = mixedQuery.data?.questions ?? [];
    return (
      <div>
        {mixedQuery.isLoading && !mixedQuery.data ? (
          <LoadingState rows={6} />
        ) : mixedQuery.isError || !mixedQuery.data ? (
          <ErrorState message="综合挑战卷加载失败" onRetry={() => void mixedQuery.refetch()} />
        ) : (
          <QuizRunner
            variant="mixed"
            questions={questions}
            rulesVersion={rulesVersion}
            showName={showName}
            answers={answers}
            onAnswersChange={setAnswers}
            onBack={() => setMixedNonce(null)}
          />
        )}
      </div>
    );
  }

  if (month != null) {
    const questions = questionsQuery.data?.questions ?? [];
    return (
      <div>
        {questionsQuery.isLoading && !questionsQuery.data ? (
          <LoadingState rows={6} />
        ) : questionsQuery.isError || !questionsQuery.data ? (
          <ErrorState message="题目加载失败" onRetry={() => void questionsQuery.refetch()} />
        ) : (
          <QuizRunner
            month={month}
            questions={questions}
            rulesVersion={rulesVersion}
            showName={showName}
            answers={answers}
            onAnswersChange={setAnswers}
            onBack={() => setMonth(null)}
          />
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <section className="rounded-lg border px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="text-sm font-semibold">高位接力 · 答题训练</span>
          <span className="text-xs text-muted-foreground">
            全历史 {overview.total} 题（命中口诀的该买，未命中的该拒）——看截断K线和今开，
            判断买不买；答完看后续走势和口诀讲解。
          </span>
          <span className="ml-auto flex items-center gap-3">
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                className="h-3.5 w-3.5"
                checked={showName}
                onChange={(e) => setShowName(e.target.checked)}
              />
              显示票名
            </label>
            <button
              type="button"
              className="text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setAnswers(resetAll(rulesVersion))}
            >
              重置全部进度
            </button>
          </span>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {years.map((y) => (
            <button
              key={y.year}
              type="button"
              className={cn(
                "rounded-md border px-3 py-1 text-xs",
                y.year === activeYear
                  ? "border-primary bg-primary/10 font-semibold text-primary"
                  : "text-muted-foreground hover:bg-muted/40",
              )}
              onClick={() => setYear(y.year)}
            >
              {y.year}年
            </button>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-primary/40 bg-primary/5 px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="text-sm font-semibold text-primary">综合挑战卷</span>
          <span className="text-xs text-muted-foreground">
            七条口诀各抽 2 道好票 + 28~35 道陷阱票（阴阳反串／形态接近／毒段，每卷随机）——
            每卷练全所有口诀，认熟「看着像但不能打」的票；每次进入重新随机抽题。
          </span>
          <button
            type="button"
            className="ml-auto h-8 rounded-md bg-primary px-4 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
            onClick={() => setMixedNonce((n) => (n ?? 0) + 1)}
          >
            开始挑战
          </button>
        </div>
        {/* 年份筛选(主人定):选年=只在该年抽题练该年市场环境;单年某口诀不足2道有多少抽多少 */}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-[11px] text-muted-foreground">抽题范围</span>
          <MixYearChip label="全部年份" active={mixYear == null} onClick={() => setMixYear(null)} />
          {years.map((y) => (
            <MixYearChip
              key={y.year}
              label={`${y.year}年`}
              active={mixYear === y.year}
              onClick={() => setMixYear(y.year)}
            />
          ))}
        </div>
      </section>

      <section className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {activeMonths.map((m) => (
          <MonthCell
            key={m.month}
            month={m.month}
            total={m.total}
            buyCount={m.buy_count}
            rejectCount={m.reject_count}
            answers={answers}
            onOpen={() => setMonth(m.month)}
          />
        ))}
      </section>

      <p className="text-[11px] leading-5 text-muted-foreground">
        判分（主人四档·对称版）：口诀对×行情对 +10 ／ 口诀对×行情不配合 +3 ／ 没按口诀但你判断对了 +5 ／
        没按口诀判断错了 -10；总结有满分参照（每题满分10）和本月收益测算（你的操作 vs 口诀标准操作）。
        月内分「打3板」「打4板」两段，题目每次进入乱序（防背答案）；
        答错的题（没按口诀的）可在段末反复乱序重练直到答对。综合挑战卷与月题共享进度（同一题只答一次）。
        今开≥9.5顶格票开盘即涨停买不到，
        不出题。收益=E3卖出纪律口径：退出价=max(收盘价, (最高+最低)/2)，炸板次日走（T+1合规）；
        K线未复权；主力心理为事后合理解释而非实证。题库版本 {rulesVersion}。
      </p>
    </div>
  );
}

function MixYearChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={cn(
        "rounded-md border px-2.5 py-0.5 text-[11px]",
        active
          ? "border-primary bg-primary/10 font-semibold text-primary"
          : "text-muted-foreground hover:bg-muted/40",
      )}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

function MonthCell({
  month,
  total,
  buyCount,
  rejectCount,
  answers,
  onOpen,
}: {
  month: string;
  total: number;
  buyCount: number;
  rejectCount: number;
  answers: Record<string, QuizAnswerRec>;
  onOpen: () => void;
}) {
  // 该月已答进度:题 id 前缀 = YYYY-MM(answers key 形如 "2024-11-13|000001.SZSE")
  const prefix = `${month}-`;
  let answered = 0;
  let score = 0;
  for (const [k, v] of Object.entries(answers)) {
    if (k.startsWith(prefix)) {
      answered += 1;
      score += v.score;
    }
  }
  const done = answered >= total && total > 0;
  return (
    <button
      type="button"
      className={cn(
        "rounded-lg border px-3 py-2.5 text-left hover:bg-muted/30",
        done && "border-primary/50 bg-primary/5",
      )}
      onClick={onOpen}
    >
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-semibold tabular-nums">
          {Number(month.slice(5))}月
        </span>
        <span className="text-[11px] text-muted-foreground tabular-nums">{total}题</span>
      </div>
      <div className="mt-1 flex items-baseline justify-between text-[11px] tabular-nums">
        <span className="text-muted-foreground">
          买{buyCount} 拒{rejectCount}
        </span>
        {answered > 0 ? (
          <span className={cn(done ? "text-primary" : "text-muted-foreground")}>
            {done ? "✓ " : ""}{answered}/{total}
            <span className={cn("ml-1 font-mono", score >= 0 ? "text-rise" : "text-fall")}>
              {score >= 0 ? "+" : ""}{score}
            </span>
          </span>
        ) : (
          <span className="text-muted-foreground/60">未开始</span>
        )}
      </div>
    </button>
  );
}
