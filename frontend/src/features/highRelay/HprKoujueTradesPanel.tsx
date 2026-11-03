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

export type KoujueTradeScope = "all" | "taken" | "shared" | "off";

export type KoujueTradeMode = "taken" | "shared" | "off";

/** 逐笔三态(口诀存在共用区,区分「让位」与「未启用」):
 * taken=本口诀执行;shared=本口诀当月有出手资格,但同票还命中其它启用口诀、
 * 按纪律走了那条(如通用组 K5 优先)——共用票不是本口诀的错,也不是它的肉;
 * off=当月动态组未启用本口诀所在组(强市口诀在弱市月/弱市口诀在强市月),时代参考。
 * 常开通用组(K5/B1·转温)任何月都有资格,由 alwaysOn 名单(后端单源)判定。 */
export function koujueTradeMode(
  t: HprKoujueTrade,
  alwaysOn: string[] = [],
): KoujueTradeMode {
  if (t.tk) return "taken";
  const common =
    alwaysOn.includes(t.p) || (t.s ? alwaysOn.includes(`${t.p}·${t.s}`) : false);
  const eligible =
    common || (t.g === "weak" ? t.st !== "strong" : t.st !== "weak");
  return eligible && t.tp && t.tp !== t.p ? "shared" : "off";
}

export interface KoujueTradeSummary {
  n: number;
  win: number | null;
  avg: number | null;
  sum: number;
}

/** 过滤后的逐笔统计:成交口径,与规则页/物化 stat_rows 同源(重叠也计)。 */
export function summarizeKoujueTrades(trades: HprKoujueTrade[]): KoujueTradeSummary {
  const rets = trades
    .filter((t) => t.r != null)
    .map((t) => t.r as number);
  const sum = rets.reduce((acc, v) => acc + v, 0);
  return {
    n: trades.length,
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
    alwaysOn,
  }: {
    year: string;
    scope: KoujueTradeScope;
    keyword: string;
    alwaysOn?: string[];
  },
): HprKoujueTrade[] {
  const kw = keyword.trim().toLowerCase();
  return trades.filter((t) => {
    if (year !== "all" && !t.m.startsWith(year)) return false;
    if (scope !== "all" && koujueTradeMode(t, alwaysOn) !== scope) return false;
    if (!kw) return true;
    return t.code.toLowerCase().includes(kw) || t.name.toLowerCase().includes(kw);
  });
}

/** 规则页点口诀后的历史逐笔面板:年份/三态(成交/共用/未启用)/搜票筛选 + 逐票明细。 */
export function HprKoujueTradesPanel({
  point,
  sub,
  label,
  data,
  isLoading,
  isError,
  onRetry,
  onClose,
  alwaysOn = [],
}: {
  point: string;
  sub?: string;
  label: string;
  data?: HprKoujueTradesPayload;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  onClose: () => void;
  alwaysOn?: string[];
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
  const modeCounts = useMemo(() => {
    const out = { taken: 0, shared: 0, off: 0 };
    for (const t of trades) out[koujueTradeMode(t, alwaysOn)] += 1;
    return out;
  }, [trades, alwaysOn]);
  const visible = useMemo(
    () => filterKoujueTrades(trades, { year, scope, keyword, alwaysOn }),
    [trades, year, scope, keyword, alwaysOn],
  );
  const takenTrades = useMemo(
    () => trades.filter((t) => koujueTradeMode(t, alwaysOn) === "taken"),
    [trades, alwaysOn],
  );
  const sharedTrades = useMemo(
    () => trades.filter((t) => koujueTradeMode(t, alwaysOn) === "shared"),
    [trades, alwaysOn],
  );
  // 头部只报本口诀真实成交:共用票的收益归执行口诀,不计入本口诀(否则会被别条赢家抬高)
  const execSummary = useMemo(() => summarizeKoujueTrades(takenTrades), [takenTrades]);
  const sharedSummary = useMemo(() => summarizeKoujueTrades(sharedTrades), [sharedTrades]);

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
                  ["taken", `成交 ${modeCounts.taken}`],
                  ["shared", `共用 ${modeCounts.shared}`],
                  ["off", `未启用 ${modeCounts.off}`],
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
                成交 <span className="text-foreground">{execSummary.n}</span> 笔
              </span>
              <span className="text-muted-foreground">
                胜率{" "}
                <span className="text-foreground">
                  {execSummary.win == null ? "--" : `${Math.round(execSummary.win * 100)}%`}
                </span>
              </span>
              <span className="text-muted-foreground">
                均{" "}
                <span className={cn(execSummary.avg != null && tone(execSummary.avg))}>
                  {execSummary.avg == null ? "--" : formatPct(execSummary.avg)}
                </span>
              </span>
              <span className="text-muted-foreground">
                合计{" "}
                <span className={tone(execSummary.sum)}>{formatPct(execSummary.sum)}</span>
              </span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-3 py-1.5 text-[11px] text-muted-foreground">
            <span>
              全量 {trades.length} 笔 · 成交 {modeCounts.taken} · 共用{" "}
              {modeCounts.shared} · 未启用 {modeCounts.off} · 当前筛选 {visible.length}
            </span>
            {sharedSummary.n > 0 ? (
              <span className="text-amber-600">
                共用 {sharedSummary.n} 笔 均{" "}
                {sharedSummary.avg == null ? "--" : formatPct(sharedSummary.avg)}
                (收益归执行口诀,不计入本口诀)
              </span>
            ) : null}
            <span>
              「成交」=本口诀执行;「共用」=同票命中多条口诀按纪律走了别条(收益归执行口诀,
              非本口诀独立可买);「未启用」=当月动态组未启用本口诀所在组
            </span>
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
                    <KoujueTradeRow
                      key={`${t.d}-${t.code}-${t.p}-${t.s}-${i}`}
                      trade={t}
                      alwaysOn={alwaysOn}
                    />
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

function KoujueTradeRow({
  trade: t,
  alwaysOn,
}: {
  trade: HprKoujueTrade;
  alwaysOn?: string[];
}) {
  const stateLabel = DYN_STATE_LABELS[t.st] ?? t.st;
  const mode = koujueTradeMode(t, alwaysOn);
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
          {mode === "taken" ? (
            <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600">
              成交
            </span>
          ) : mode === "shared" ? (
            <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
              共用·走{t.tp}
            </span>
          ) : (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
              未启用
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
          {mode === "off" && t.tp ? ` · 当月走${t.tp}` : ""}
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
