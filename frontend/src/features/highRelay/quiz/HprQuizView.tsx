import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  fetchHprKoujueCurrent,
  fetchHprQuizMixed,
  fetchHprQuizOverview,
  fetchHprQuizQuestions,
} from "@/api/highRelay";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { cn } from "@/lib/utils";

import { QuizRunner } from "./QuizRunner";
import type { QuizAnswerRec } from "./quizScore";
import { loadProgress, resetAll } from "./quizProgress";

/** 动态口诀组横幅样式(v7.2 答题页;与 HprLiveView 同色系) */
const DYN_GROUP_META: Record<string, { label: string; className: string }> = {
  strong: { label: "强市组(A1~C3 八条)", className: "border-primary/40 bg-primary/10 text-primary" },
  weak: { label: "弱市组(K 系六条)", className: "border-violet-500/40 bg-violet-500/10 text-violet-500" },
  both: { label: "双开(样本不足)", className: "border-muted bg-muted/30 text-muted-foreground" },
};

/**
 * 答题训练页签根:综合挑战卷(两组口诀好票+陷阱票随机混编) + 年份 chip →
 * 月份格子(题数/进度/得分) → QuizRunner。
 * 进度存 localStorage(key 含题库版本串);默认匿名,实名开关切题干显示。
 * v7.2:头部挂「当前口诀组」横幅(自动拉 koujue),年份按时代分色,抽题范围加时代维度。
 */
export function HprQuizView() {
  const overviewQuery = useQuery({
    queryKey: ["hprQuizOverview"],
    queryFn: fetchHprQuizOverview,
    staleTime: 300_000,
  });
  const overview = overviewQuery.data;
  const rulesVersion = overview?.rules_version ?? "unknown";
  // 动态口诀组(v7.2):做题也要知道当前启用哪组——与规则页按钮/实时推荐同一数据源
  const koujueQuery = useQuery({
    queryKey: ["hprKoujue"],
    queryFn: fetchHprKoujueCurrent,
    staleTime: 300_000,
  });
  const dynGroup =
    koujueQuery.data?.status === "ok" ? koujueQuery.data.current_group : null;

  const years = useMemo(
    () => (overview?.status === "ok" ? overview.years ?? [] : []),
    [overview],
  );
  const [year, setYear] = useState<string | null>(null);
  const [month, setMonth] = useState<string | null>(null);
  // 综合挑战卷:nonce=null 未进卷;每点一次「开始挑战」+1 → queryKey 变 →
  // 强制重新随机抽题(禁缓存,主人要每次重抽不重样);mixYear=null 全库,
  // 指定年=只在该年抽(主人定:按年份练市场环境);
  // mixEra(v7.2)=时代抽题,与年份互斥:weak=2020-22 弱市组段,strong=2023 起强市段
  const [mixYear, setMixYear] = useState<string | null>(null);
  const [mixEra, setMixEra] = useState<"weak" | "strong" | null>(null);
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
    queryKey: ["hprQuizMixed", mixedNonce, mixYear, mixEra],
    queryFn: () => fetchHprQuizMixed(
      mixEra ? { era: mixEra } : mixYear ? { year: mixYear } : undefined,
    ),
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
            dynGroup={dynGroup}
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
            dynGroup={dynGroup}
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
            判断买不买；答完看后续走势和口诀讲解。2020-2022 是弱市组题（按K系口诀判断），
            2023 起是强市组题。
          </span>
          <span className="ml-auto flex items-center gap-3">
            <label className="flex cursor-pointer items-center gap-1.5 py-2 text-xs text-muted-foreground md:py-0">
              <input
                type="checkbox"
                className="h-4 w-4 md:h-3.5 md:w-3.5"
                checked={showName}
                onChange={(e) => setShowName(e.target.checked)}
              />
              显示票名
            </label>
            <button
              type="button"
              className="py-2.5 text-xs text-muted-foreground hover:text-foreground md:py-0"
              onClick={() => setAnswers(resetAll(rulesVersion))}
            >
              重置全部进度
            </button>
          </span>
        </div>
        {dynGroup ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded-md border px-2 py-1 text-xs font-semibold",
                DYN_GROUP_META[dynGroup]?.className,
              )}
            >
              当前口诀组:{DYN_GROUP_META[dynGroup]?.label ?? dynGroup}
            </span>
            <span className="text-[11px] text-muted-foreground">
              近一年哪组口诀赚得多就用哪组（实时推荐/盘中扫描按它出手）——做题按题目所在时代的口诀组判断，两组口诀条件见「规则说明」
            </span>
          </div>
        ) : null}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-[11px] text-muted-foreground">
            紫色年份=弱市组题(K 系) · 蓝色年份=强市组题 · 渐变=当年切组(做题时看每题的组标签)
          </span>
        </div>
        <div className="mt-1 flex flex-wrap gap-2">
          {years.map((y) => {
            // v7.3 年份按该年月组状态分色(后端逐月聚合):纯弱市年紫/纯强市年蓝/
            // 切组年(如 2023:1~6月弱市·7月起强市)蓝紫渐变;旧数据兜底按日期切
            const states = y.dyn_states?.length
              ? y.dyn_states
              : y.year <= "2022" ? ["weak"] : ["strong"];
            const hasWeak = states.includes("weak");
            const hasStrong = states.includes("strong");
            const mixed = hasWeak && hasStrong;
            const weakYear = hasWeak && !hasStrong;
            const toneCls = y.year === activeYear
              ? mixed
                ? "border-violet-500/50 bg-gradient-to-r from-violet-500/15 to-primary/15 font-semibold text-foreground"
                : weakYear
                  ? "border-violet-500 bg-violet-500/10 font-semibold text-violet-500"
                  : "border-primary bg-primary/10 font-semibold text-primary"
              : weakYear || mixed
                ? "text-violet-500/80 hover:bg-violet-500/10"
                : "text-muted-foreground hover:bg-muted/40";
            return (
              <button
                key={y.year}
                type="button"
                title={mixed
                  ? "切组年:该年内动态口诀组发生切换(既有弱市组月也有强市组月)——做题时看每题的组标签"
                  : weakYear
                    ? "弱市组题:该年每月动态组=弱市组,按K系六条口诀判断"
                    : "强市组题:该年每月动态组=强市组,按A1~C3八条口诀判断"}
                className={cn("rounded-md border px-3 py-2 text-xs md:py-1", toneCls)}
                onClick={() => setYear(y.year)}
              >
                {y.year}年
              </button>
            );
          })}
        </div>
      </section>

      <section className="rounded-lg border border-primary/40 bg-primary/5 px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="text-sm font-semibold text-primary">综合挑战卷</span>
          <span className="text-xs text-muted-foreground">
            两组口诀各抽 2 道好票（强市组八条 + 弱市组六条）+ 28~35 道陷阱票
            （阴阳反串／形态接近／毒段，每卷随机）——
            每卷练全所有口诀，认熟「看着像但不能打」的票；每次进入重新随机抽题。
          </span>
          <button
            type="button"
            className="ml-auto h-11 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 md:h-8 md:text-xs"
            onClick={() => setMixedNonce((n) => (n ?? 0) + 1)}
          >
            开始挑战
          </button>
        </div>
        {/* 年份筛选(主人定):选年=只在该年抽题练该年市场环境;单年某口诀不足2道有多少抽多少;
            v7.2 时代筛选(与年份互斥):弱市时代=2020-22 只出K系好票+当时代陷阱,强市时代=2023起 */}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-[11px] text-muted-foreground">抽题范围</span>
          <MixYearChip
            label="全部年份"
            active={mixYear == null && mixEra == null}
            onClick={() => { setMixYear(null); setMixEra(null); }}
          />
          <MixYearChip
            label="弱市时代(20-22)"
            tone="violet"
            active={mixEra === "weak"}
            onClick={() => { setMixEra("weak"); setMixYear(null); }}
          />
          <MixYearChip
            label="强市时代(23起)"
            active={mixEra === "strong"}
            onClick={() => { setMixEra("strong"); setMixYear(null); }}
          />
          {years.map((y) => (
            <MixYearChip
              key={y.year}
              label={`${y.year}年`}
              active={mixEra == null && mixYear === y.year}
              onClick={() => { setMixYear(y.year); setMixEra(null); }}
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
        不出题。收益=E3卖出纪律口径：退出价=退出日收盘价（跌停顺延次日开盘），炸板次日走（T+1合规）；
        K线未复权；主力心理为事后合理解释而非实证。题库版本 {rulesVersion}。
      </p>
    </div>
  );
}

function MixYearChip({
  label,
  active,
  tone = "primary",
  onClick,
}: {
  label: string;
  active: boolean;
  tone?: "primary" | "violet";   // violet=弱市时代 chip(v7.2)
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={cn(
        "rounded-md border px-2.5 py-2 text-[11px] md:py-0.5",
        active
          ? tone === "violet"
            ? "border-violet-500 bg-violet-500/10 font-semibold text-violet-500"
            : "border-primary bg-primary/10 font-semibold text-primary"
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
