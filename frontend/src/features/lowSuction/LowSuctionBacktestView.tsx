import { RefreshCw, RotateCw } from "lucide-react";

import type {
  LowSuctionBacktestReport,
  LowSuctionBandStats,
  LowSuctionRebuildStatus,
  LowSuctionSimSummary,
} from "@/api/lowSuction";
import { EmptyState } from "@/components/EmptyState";
import { PanelHead } from "@/components/PanelHead";
import { cn } from "@/lib/utils";

/** 低吸回测：每族前五的十槽位模拟（产品口径）+ 全量分数段统计。 */
export function LowSuctionBacktestView({
  report,
  rebuild,
  building,
  canRebuild,
  onRebuild,
  rebuildError,
}: {
  report: LowSuctionBacktestReport | null | undefined;
  rebuild: LowSuctionRebuildStatus;
  building: boolean;
  canRebuild: boolean;
  onRebuild: () => void;
  rebuildError: string | null;
}) {
  return (
    <section aria-label="低吸回测">
      <RebuildBar
        hasReport={!!report}
        rebuild={rebuild}
        building={building}
        canRebuild={canRebuild}
        onRebuild={onRebuild}
        rebuildError={rebuildError}
      />
      {!report ? (
        <EmptyState
          message={building ? "正在全量扫描计算低吸回测…" : "低吸日线回测尚未运行"}
          description={building ? "期间可切换其他页签，算完自动刷新" : "点击上方「重新计算回测」生成报告，或等待 22:30 定时自动重算"}
        />
      ) : (
        <BacktestBody report={report} />
      )}
    </section>
  );
}

function RebuildBar({
  hasReport,
  rebuild,
  building,
  canRebuild,
  onRebuild,
  rebuildError,
}: {
  hasReport: boolean;
  rebuild: LowSuctionRebuildStatus;
  building: boolean;
  canRebuild: boolean;
  onRebuild: () => void;
  rebuildError: string | null;
}) {
  const finished = rebuild.status === "ready" || rebuild.status === "failed";
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b bg-amber-500/5 px-3 py-2 text-xs sm:px-4">
      <span className="eyebrow text-amber-600">回测 BACKTEST</span>
      {hasReport && !building && (
        <span className="text-amber-600">⚠️ 历史模拟，非实盘</span>
      )}
      {building && (
        <span className="flex items-center gap-1 text-amber-600">
          <RotateCw size={12} className="animate-spin" /> 正在全量重算…
        </span>
      )}
      {finished && rebuild.status === "ready" && (
        <span className="text-emerald-600">✓ 已更新（{rebuild.trade_days} 交易日）</span>
      )}
      {finished && rebuild.status === "failed" && (
        <span className="text-red-600">✗ 重算失败：{rebuildError ?? "未知错误"}</span>
      )}
      <button
        type="button"
        onClick={onRebuild}
        disabled={!canRebuild}
        className={cn(
          "ml-auto flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
          canRebuild
            ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/20"
            : "border-muted text-muted-foreground opacity-60",
        )}
        title={building ? "正在重算…" : "全量重新计算并写库（夜间 22:30 也会自动重算）"}
      >
        <RefreshCw size={12} className={cn(building && "animate-spin")} />
        {building ? "重算中" : "重新计算回测"}
      </button>
    </div>
  );
}

function BacktestBody({ report }: { report: LowSuctionBacktestReport }) {
  const sim = report.position_sim;
  const selection = report.selection;
  return (
    <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-3 py-2 text-xs text-muted-foreground sm:px-4">
        <span>{report.label_convention}</span>
        <span className="ml-auto">
          {report.coverage.calendar_start} ~ {report.coverage.calendar_end} · {report.coverage.trade_days} 个交易日 ·{" "}
          {report.coverage.labeled.toLocaleString()} 个带标签候选
        </span>
      </div>

      <PanelHead
        no="01"
        zh="带仓位回测"
        en="TOP-5 X 2"
        note={`每日趋势/超跌各取最高分前 ${selection.picks_per_family} 只；每票 ${selection.allocation_per_pick_pct.toFixed(0)}%，未满 ${selection.max_positions} 槽位留现金`}
      />
      <div className="grid grid-cols-2 gap-px border-b bg-border sm:grid-cols-4">
        <SimCard
          title={`十票组合（最多${selection.max_positions}票）`}
          compound={sim.combined.compound_pct}
          rows={[
            ["日均收益", fmtPct(sim.combined.mean_pct)],
            ["日胜率", fmtPct(sim.combined.win_rate_pct)],
            ["最大回撤", fmtPct(sim.combined.max_drawdown_pct)],
            ["平均持仓", `${fmtNumber(sim.combined.average_positions_per_day)} / ${selection.max_positions}`],
          ]}
          highlight
        />
        <SimCard
          title={`趋势低吸（最高${selection.picks_per_family}票）`}
          compound={sim.trend_pullback.compound_pct}
          rows={[
            ["均票收益", fmtPct(sim.trend_pullback.mean_pct)],
            ["胜率", fmtPct(sim.trend_pullback.win_rate_pct)],
            ["选票数", `${sim.trend_pullback.trades ?? "--"}`],
          ]}
        />
        <SimCard
          title={`超跌低吸（最高${selection.picks_per_family}票）`}
          compound={sim.oversold_rebound.compound_pct}
          rows={[
            ["均票收益", fmtPct(sim.oversold_rebound.mean_pct)],
            ["胜率", fmtPct(sim.oversold_rebound.win_rate_pct)],
            ["选票数", `${sim.oversold_rebound.trades ?? "--"}`],
          ]}
        />
        <div className="bg-card px-3 py-3 sm:px-4">
          <div className="mb-1 text-xs text-muted-foreground">十槽位权益曲线</div>
          <EquitySpark points={sim.equity_curve} />
          <div className="mt-1 flex justify-between text-[10px] tabular-nums text-muted-foreground">
            <span>{sim.equity_curve[0]?.date.slice(2) ?? ""}</span>
            <span>{sim.equity_curve[sim.equity_curve.length - 1]?.date.slice(2) ?? ""}</span>
          </div>
        </div>
      </div>

      <EvaluationTables report={report} />

      <PanelHead no="03" zh="全量回测 · 分数段统计" en="SCORE BANDS" note="推荐区间 = validation+holdout 双段为正（与正式验收门同口径）" />
      <div className="grid gap-px bg-border xl:grid-cols-2">
        <BandTable
          title="上升趋势低吸"
          en="TREND"
          total={report.families.trend_pullback.total}
          bands={report.families.trend_pullback.bands}
        />
        <BandTable
          title="超跌反弹低吸"
          en="OVERSOLD"
          total={report.families.oversold_rebound.total}
          bands={report.families.oversold_rebound.bands}
        />
      </div>
    </>
  );
}

function EvaluationTables({ report }: { report: LowSuctionBacktestReport }) {
  const timeRows = ["development", "embargo", "validation", "holdout"].map((key) => {
    const range = report.time_split[key];
    return {
      label: key === "development" ? "开发样本" : key === "embargo" ? "隔离期" : key === "validation" ? "验证样本" : "保留样本",
      range: range?.start && range?.end ? `${range.start.slice(2)} ~ ${range.end.slice(2)}` : "--",
      summary: report.position_sim.time_segments[key],
    };
  });
  const regimeRows = ["above_ma20", "below_ma20", "unclassified"].map((key) => ({
    label: report.market_regime.labels[key] ?? key,
    range: "",
    summary: report.position_sim.market_regimes[key],
  }));
  return (
    <>
      <PanelHead
        no="02"
        zh="样本外与市况复核"
        en="ROBUSTNESS"
        note="只验证固定规则和固定前五排序；不按这两张表回调分数"
      />
      <div className="grid gap-px border-b bg-border xl:grid-cols-2">
        <EvaluationTable title="时间顺序" subtitle="开发 / 验证 / 保留互不重叠" rows={timeRows} />
        <EvaluationTable title="行情环境" subtitle={report.market_regime.definition} rows={regimeRows} />
      </div>
    </>
  );
}

function EvaluationTable({
  title,
  subtitle,
  rows,
}: {
  title: string;
  subtitle: string;
  rows: { label: string; range: string; summary: LowSuctionSimSummary | undefined }[];
}) {
  return (
    <div className="min-w-0 bg-card">
      <div className="border-b px-3 py-2 sm:px-4">
        <div className="text-sm font-semibold">{title}</div>
        <div className="mt-0.5 text-[11px] text-muted-foreground">{subtitle}</div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] text-xs tabular-nums">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="px-3 py-1.5 font-medium">分组</th>
              <th className="py-1.5 font-medium">区间</th>
              <th className="py-1.5 text-right font-medium">交易日</th>
              <th className="py-1.5 text-right font-medium">平均持仓</th>
              <th className="py-1.5 text-right font-medium">日均收益</th>
              <th className="py-1.5 text-right font-medium">胜率</th>
              <th className="py-1.5 text-right font-medium">复利</th>
              <th className="px-3 py-1.5 text-right font-medium">最大回撤</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ label, range, summary }) => (
              <tr key={label} className="border-b last:border-0">
                <td className="whitespace-nowrap px-3 py-1.5 font-medium">{label}</td>
                <td className="whitespace-nowrap py-1.5 text-muted-foreground">{range || "--"}</td>
                <td className="py-1.5 text-right">{summary?.days ?? 0}</td>
                <td className="py-1.5 text-right">{fmtNumber(summary?.average_positions_per_day)}</td>
                <td className={cn("py-1.5 text-right font-medium", tone(summary?.mean_pct))}>{fmtSigned(summary?.mean_pct)}</td>
                <td className="py-1.5 text-right">{fmtPct(summary?.win_rate_pct)}</td>
                <td className={cn("py-1.5 text-right", tone(summary?.compound_pct))}>{fmtSigned(summary?.compound_pct)}</td>
                <td className="px-3 py-1.5 text-right">{fmtPct(summary?.max_drawdown_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SimCard({
  title,
  compound,
  rows,
  highlight = false,
}: {
  title: string;
  compound: number;
  rows: [string, string][];
  highlight?: boolean;
}) {
  return (
    <div className={cn("bg-card px-3 py-3 sm:px-4", highlight && "bg-primary/5")}>
      <div className="text-xs text-muted-foreground">{title}</div>
      <div className={cn("mt-0.5 font-mono text-xl font-bold tabular-nums", compound >= 0 ? "text-red-500" : "text-emerald-600")}>
        {compound >= 0 ? "+" : ""}
        {compound.toFixed(1)}%
      </div>
      <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1 text-xs tabular-nums">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-2">
            <span className="text-muted-foreground">{label}</span>
            <span className="font-medium">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function BandTable({
  title,
  en,
  total,
  bands,
}: {
  title: string;
  en: string;
  total: { n: number; win_rate_pct: number | null; mean_pct: number | null };
  bands: Record<string, LowSuctionBandStats>;
}) {
  const entries = Object.entries(bands);
  return (
    <div className="min-w-0 bg-card">
      <div className="flex items-baseline gap-2 border-b px-3 py-2 sm:px-4">
        <span className="text-sm font-semibold">{title}</span>
        <span className="eyebrow">{en}</span>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          全部候选 {total.n.toLocaleString()} · 胜率 {fmtPct(total.win_rate_pct)} · 均值 {fmtSigned(total.mean_pct)}
        </span>
      </div>
      {entries.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground">样本不足</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-xs tabular-nums">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="px-3 py-1.5 font-medium">分数段</th>
                <th className="py-1.5 text-right font-medium">样本</th>
                <th className="py-1.5 text-right font-medium">胜率</th>
                <th className="py-1.5 text-right font-medium">D+1均值</th>
                <th className="py-1.5 text-right font-medium">中位</th>
                <th className="py-1.5 text-right font-medium">日复利</th>
                <th className="py-1.5 text-right font-medium">验证段</th>
                <th className="px-3 py-1.5 text-right font-medium">保留段</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([band, stats]) => (
                <tr key={band} className={cn("border-b last:border-0", stats.recommended && "bg-primary/[0.06]")}>
                  <td className="px-3 py-1.5 font-mono font-semibold">
                    {band}
                    {stats.recommended && (
                      <span className="ml-1.5 rounded-full bg-primary/15 px-1.5 py-px text-[10px] font-medium text-primary">
                        推荐
                      </span>
                    )}
                  </td>
                  <td className="py-1.5 text-right">{stats.n.toLocaleString()}</td>
                  <td className="py-1.5 text-right">{fmtPct(stats.win_rate_pct)}</td>
                  <td className={cn("py-1.5 text-right font-medium", tone(stats.mean_pct))}>{fmtSigned(stats.mean_pct)}</td>
                  <td className="py-1.5 text-right">{fmtSigned(stats.median_pct)}</td>
                  <td className={cn("py-1.5 text-right", tone(stats.compound_pct))}>{fmtSigned(stats.compound_pct)}</td>
                  <td className="py-1.5 text-right">{fmtSigned(stats.segments?.validation?.mean_pct ?? null)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtSigned(stats.segments?.holdout?.mean_pct ?? null)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** 内联 SVG 权益曲线（零依赖小图，不动 lightweight-charts）。 */
function EquitySpark({ points }: { points: { date: string; equity: number }[] }) {
  if (points.length < 2) return <div className="h-16" />;
  const values = points.map((p) => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 220;
  const h = 56;
  const step = w / (points.length - 1);
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - ((p.equity - min) / span) * (h - 6) - 3).toFixed(1)}`)
    .join(" ");
  const last = values[values.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-14 w-full" role="img" aria-label="十槽位权益曲线">
      <path d={path} fill="none" strokeWidth="1.5" className={last >= 1 ? "stroke-red-500" : "stroke-emerald-600"} />
      {/* 成本线 1.0 */}
      {min < 1 && max > 1 && (
        <line
          x1="0"
          x2={w}
          y1={h - ((1 - min) / span) * (h - 6) - 3}
          y2={h - ((1 - min) / span) * (h - 6) - 3}
          strokeDasharray="3 3"
          strokeWidth="0.75"
          className="stroke-muted-foreground/50"
        />
      )}
    </svg>
  );
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "--";
  return `${v.toFixed(1)}%`;
}

function fmtSigned(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "--";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function fmtNumber(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "--";
  return v.toFixed(1);
}

function tone(v: number | null | undefined): string {
  if (v == null) return "";
  return v > 0 ? "text-red-500" : v < 0 ? "text-emerald-600" : "";
}
