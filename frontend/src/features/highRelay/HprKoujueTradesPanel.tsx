import { useEffect, useMemo, useRef, useState } from "react";

import type { HprKoujueTrade, HprKoujueTradesPayload } from "@/api/highRelay";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn, formatPct, formatPrice } from "@/lib/utils";

const EXIT_REASON_LABELS: Record<string, string> = {
  break_day_close: "炸板次日卖",
  next_close_fail: "次日未涨停卖",
  break_close: "断板日卖",
  max_hold_close: "15日兜底卖",
};

const DYN_STATE_LABELS: Record<string, string> = {
  weak: "弱市月",
  strong: "强市月",
  both: "双开月",
};

export type KoujueTradeScope = "all" | "taken" | "ref";

export interface KoujueTradeSummary {
  n: number;
  nExec: number;
  win: number | null;
  avg: number | null;
  sum: number;
}

/** 过滤后的逐笔统计:同票持仓重叠行保留展示,但不计入胜率/均值/合计。 */
export function summarizeKoujueTrades(trades: HprKoujueTrade[]): KoujueTradeSummary {
  const rets = trades
    .filter((t) => t.r != null && !t.ov)
    .map((t) => t.r as number);
  const sum = rets.reduce((acc, v) => acc + v, 0);
  return {
    n: trades.length,
    nExec: rets.length,
    win: rets.length ? rets.filter((v) => v > 0).length / rets.length : null,
    avg: rets.length ? sum / rets.length : null,
    sum,
  };
}

export function filterKoujueTrades(
  trades: HprKoujueTrade[],
  {
    year,
    scope,
    keyword,
  }: { year: string; scope: KoujueTradeScope; keyword: string },
): HprKoujueTrade[] {
  const kw = keyword.trim().toLowerCase();
  return trades.filter((t) => {
    if (year !== "all" && !t.m.startsWith(year)) return false;
    if (scope === "taken" && !t.tk) return false;
    if (scope === "ref" && t.tk) return false;
    if (!kw) return true;
    return t.code.toLowerCase().includes(kw) || t.name.toLowerCase().includes(kw);
  });
}

/** 规则页点口诀后的历史逐笔面板:年份/成交状态/搜票筛选 + 逐票明细。 */
export function HprKoujueTradesPanel({
  point,
  sub,
  label,
  data,
  isLoading,
  isError,
  onRetry,
  onClose,
}: {
  point: string;
  sub?: string;
  label: string;
  data?: HprKoujueTradesPayload;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  onClose: () => void;
}) {
  const rootRef = useRef<HTMLElement | null>(null);
  const [year, setYear] = useState("all");
  const [scope, setScope] = useState<KoujueTradeScope>("all");
  const [keyword, setKeyword] = useState("");

  // 点口诀后滚到面板顶部,避免面板在 13 行速查表下方看不见
  useEffect(() => {
    rootRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [point, sub]);

  const trades = useMemo(() => data?.trades ?? [], [data]);
  const years = useMemo(
    () => [...new Set(trades.map((t) => t.m.slice(0, 4)))].sort().reverse(),
    [trades],
  );
  const takenCount = useMemo(() => trades.filter((t) => t.tk).length, [trades]);
  const visible = useMemo(
    () => filterKoujueTrades(trades, { year, scope, keyword }),
    [trades, year, scope, keyword],
  );
  const summary = useMemo(() => summarizeKoujueTrades(visible), [visible]);
  const totalSummary = useMemo(() => summarizeKoujueTrades(trades), [trades]);

  return (
    <section
      ref={rootRef}
      aria-label={`${point} 历史票`}
      className="mt-3 scroll-mt-3 rounded-md border border-primary/30 bg-muted/10"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-3 py-2">
        <span className="text-sm font-semibold">{label}</span>
        <span className="text-xs text-muted-foreground">
          口诀 {point}
          {sub ? ` · ${sub}` : ""}
        </span>
        <span className="text-[11px] text-muted-foreground">
          历史命中的票 · 回测事件重放动态计算
        </span>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto rounded border px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          收起
        </button>
      </div>

      {isLoading && !data ? (
        <div className="p-3">
          <LoadingState rows={3} />
        </div>
      ) : null}
      {isError ? (
        <div className="p-3">
          <ErrorState message="口诀历史票暂时不可用" onRetry={onRetry} />
        </div>
      ) : null}
      {data?.status === "unavailable" ? (
        <div className="px-4 py-5 text-sm text-muted-foreground">
          {data.reason ?? "回测逐笔明细尚未生成"}
          <p className="mt-1 text-xs text-muted-foreground/80">
            到「回测」页点「重新计算」,重算完成后这里会显示这只口诀的全部历史票。
          </p>
        </div>
      ) : null}

      {data?.status === "ok" ? (
        <>
          <div className="flex flex-wrap items-end gap-2 border-b px-3 py-2">
            <label className="text-xs text-muted-foreground">
              年份
              <select
                className="mt-1 block h-8 rounded-md border bg-background px-2 text-xs text-foreground"
                value={year}
                onChange={(e) => setYear(e.target.value)}
                aria-label="选择年份"
              >
                <option value="all">全部年份</option>
                {years.map((y) => (
                  <option key={y} value={y}>
                    {y} 年 · {trades.filter((t) => t.m.startsWith(y)).length}笔
                  </option>
                ))}
              </select>
            </label>
            <span className="inline-flex border">
              {(
                [
                  ["all", `全部 ${trades.length}`],
                  ["taken", `成交 ${takenCount}`],
                  ["ref", `参考 ${trades.length - takenCount}`],
                ] as const
              ).map(([key, text]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setScope(key)}
                  className={cn(
                    "px-2.5 py-1 text-xs",
                    scope === key
                      ? "bg-primary/15 font-medium text-primary"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {text}
                </button>
              ))}
            </span>
            <label className="text-xs text-muted-foreground">
              搜票
              <input
                type="text"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="代码 / 名称"
                className="mt-1 block h-8 w-32 border bg-background px-2 text-xs text-foreground"
              />
            </label>
            <div className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-xs tabular-nums">
              <span className="text-muted-foreground">
                当前 <span className="text-foreground">{summary.n}</span> 笔
              </span>
              <span className="text-muted-foreground">
                可执行 <span className="text-foreground">{summary.nExec}</span>
              </span>
              <span className="text-muted-foreground">
                胜率{" "}
                <span className="text-foreground">
                  {summary.win == null ? "--" : `${Math.round(summary.win * 100)}%`}
                </span>
              </span>
              <span className="text-muted-foreground">
                均{" "}
                <span className={cn(summary.avg != null && tone(summary.avg))}>
                  {summary.avg == null ? "--" : formatPct(summary.avg)}
                </span>
              </span>
              <span className="text-muted-foreground">
                合计{" "}
                <span className={tone(summary.sum)}>{formatPct(summary.sum)}</span>
              </span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-3 py-1.5 text-[11px] text-muted-foreground">
            <span>
              全量 {totalSummary.n} 笔 · 成交 {takenCount} 笔 · 参考{" "}
              {totalSummary.n - takenCount} 笔
            </span>
            {summary.nExec < summary.n ? (
              <span className="text-amber-600">
                {summary.n - summary.nExec} 笔同票持仓重叠,保留展示但不计入胜率/均值
              </span>
            ) : null}
            <span>「成交」= 当月动态组启用的口诀;「参考」= 当月未启用,仅供研究</span>
            {data.built_at ? (
              <span className="ml-auto font-mono">物化 {data.built_at.slice(0, 10)}</span>
            ) : null}
          </div>

          {visible.length === 0 ? (
            <div className="p-3">
              <EmptyState message="没有匹配的历史票" description="调整年份、成交状态或搜索关键字" />
            </div>
          ) : (
            <div className="max-h-[32rem] overflow-auto">
              <table className="w-full min-w-[1320px] text-sm">
                <thead className="sticky top-0 z-10 border-b bg-background text-xs text-muted-foreground">
                  <tr>
                    <th className="px-2 py-2 text-left font-medium">买入日</th>
                    <th className="px-2 py-2 text-left font-medium">股票</th>
                    <th className="px-2 py-2 text-left font-medium">分支</th>
                    <th className="px-2 py-2 text-left font-medium">组 / 板位</th>
                    <th className="px-2 py-2 text-right font-medium">板链开%</th>
                    <th className="px-2 py-2 text-right font-medium">板链换%</th>
                    <th className="px-2 py-2 text-right font-medium">地基</th>
                    <th className="px-2 py-2 text-right font-medium">距60高</th>
                    <th className="px-2 py-2 text-right font-medium">今开</th>
                    <th className="px-2 py-2 text-right font-medium">买入</th>
                    <th className="px-2 py-2 text-left font-medium">卖出</th>
                    <th className="px-2 py-2 text-right font-medium">收益(E3)</th>
                    <th className="px-2 py-2 text-left font-medium">状态</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {visible.map((t, i) => (
                    <KoujueTradeRow key={`${t.d}-${t.code}-${t.p}-${t.s}-${i}`} trade={t} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}

function KoujueTradeRow({ trade: t }: { trade: HprKoujueTrade }) {
  const stateLabel = DYN_STATE_LABELS[t.st] ?? t.st;
  return (
    <tr className={cn("align-top", t.ov && "opacity-60")}>
      <td className="whitespace-nowrap px-2 py-2 font-mono text-xs tabular-nums text-muted-foreground">
        {t.d}
      </td>
      <td className="min-w-[124px] px-2 py-2">
        <StockIdentityLink
          name={t.name || t.code}
          vtSymbol={t.code}
          meta={t.ch ?? undefined}
        />
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">
        <div>{t.s || "—"}</div>
        <div className="text-[10px] text-muted-foreground/70">
          {t.g === "weak" ? "弱市组" : "强市组"}
        </div>
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-xs">
        <div>{t.g4}</div>
        <div className="text-[10px] text-muted-foreground">打{t.n + 1}板</div>
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-right font-mono text-[11px] tabular-nums">
        {chain([t.b1o, t.b2o, t.b3o])}
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-right font-mono text-[11px] tabular-nums">
        {chain([t.b1t, t.b2t, t.b3t])}
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-right font-mono text-[11px] tabular-nums">
        <div>{t.fc == null ? "—" : formatPct(t.fc)}</div>
        <div className="text-[10px] text-muted-foreground">{t.fp ?? "—"}</div>
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-right font-mono text-[11px] tabular-nums text-muted-foreground">
        {t.dh == null ? "—" : formatPct(t.dh)}
      </td>
      <td className={cn("whitespace-nowrap px-2 py-2 text-right font-mono tabular-nums", tone(t.ap))}>
        {t.ap == null ? "—" : formatPct(t.ap)}
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-right font-mono tabular-nums">
        {formatPrice(t.ep)}
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-xs">
        <div className="font-mono tabular-nums">{formatPrice(t.xp)}</div>
        <div className="text-[10px] text-muted-foreground">
          {t.xd ?? "—"}
          {t.xr ? ` · ${EXIT_REASON_LABELS[t.xr] ?? t.xr}` : ""}
        </div>
      </td>
      <td
        className={cn(
          "whitespace-nowrap px-2 py-2 text-right font-mono font-medium tabular-nums",
          tone(t.r),
        )}
      >
        <div>{t.r == null ? "—" : formatPct(t.r)}</div>
        <div className="text-[10px] font-normal text-muted-foreground">
          {t.sealed ? `持有${t.hold}板` : "炸板"}
        </div>
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-xs">
        <div className="flex flex-wrap items-center gap-1">
          {t.tk ? (
            <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600">
              成交
            </span>
          ) : (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
              参考
            </span>
          )}
          {t.ov ? (
            <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-medium text-amber-600">
              持仓重叠
            </span>
          ) : null}
        </div>
        <div className="mt-0.5 text-[10px] text-muted-foreground">
          {stateLabel}
          {!t.tk && t.tp ? ` · 当月走${t.tp}` : ""}
        </div>
      </td>
    </tr>
  );
}

function chain(values: (number | null)[]) {
  return values.map((v) => (v == null ? "—" : v.toFixed(2))).join(" / ");
}

function tone(value: number | null | undefined) {
  if (value == null || value === 0) return "text-muted-foreground";
  return value > 0 ? "text-rise" : "text-fall";
}
