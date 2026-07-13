import type {
  LimitUpSectorWarmupComparison,
  LimitUpSectorWarmupReport,
} from "@/api/limitUp";
import { cn } from "@/lib/utils";

interface Props {
  report?: LimitUpSectorWarmupReport;
  loading: boolean;
  error?: string | null;
}

export function SectorWarmupResearchPanel({ report, loading, error }: Props) {
  if (loading && !report) {
    return <div className="border-b px-4 py-4 text-sm text-muted-foreground">板块预热研究计算中</div>;
  }
  if (error && !report) {
    return <div className="border-b px-4 py-3 text-sm text-fall">板块预热研究暂不可用：{error}</div>;
  }
  if (!report) return null;
  const coverage = report.data_coverage;
  const holdoutRows = report.phase_summaries.locked_holdout ?? [];
  const holdoutBaseline = holdoutRows.find((row) => row.variant === "baseline");
  const holdoutGate = holdoutRows.find((row) => row.variant === "warmup_gate");
  return (
    <section className="border-b" aria-label="板块预热研究">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b bg-muted/20 px-3 py-2 text-xs sm:px-4">
        <span className="font-semibold text-foreground">板块预热研究</span>
        <span className={report.acceptance.passed ? "text-rise" : "text-amber-700 dark:text-amber-300"}>
          {report.acceptance.passed ? "样本外门槛通过" : "代理研究，未接入实时动作"}
        </span>
        <span className="text-muted-foreground">
          {report.event_start ?? "--"} 至 {report.event_end ?? "--"} · D+1开盘 · 成本 {formatPct(report.round_trip_cost_pct, false)}
        </span>
        <span className="ml-auto text-muted-foreground">
          概念日线 {coverage.concept_daily_bar_days ?? 0} 日 · 历史成员 {coverage.membership_snapshot_days ?? 0} 日 · 盘中资金 {coverage.intraday_fund_snapshot_days ?? 0} 日
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] text-sm">
          <thead className="border-b bg-muted/10 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left sm:px-4">方案</th>
              <th className="px-3 py-2 text-right">交易</th>
              <th className="px-3 py-2 text-right">封板率</th>
              <th className="px-3 py-2 text-right">D+1胜率</th>
              <th className="px-3 py-2 text-right">平均净收益</th>
              <th className="px-3 py-2 text-right">复利</th>
              <th className="px-3 py-2 text-right">最大回撤</th>
              <th className="px-3 py-2 text-right sm:pr-4">10万期末</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {report.comparisons.map((row) => <ComparisonRow key={row.variant} row={row} />)}
          </tbody>
        </table>
      </div>
      {holdoutBaseline && holdoutGate && (
        <div className="flex flex-wrap gap-x-5 gap-y-1 border-t px-3 py-2 text-xs tabular-nums sm:px-4">
          <span className="font-medium text-foreground">锁定留出</span>
          <span className="text-muted-foreground">
            基线 {holdoutBaseline.trade_count} 笔 · 平均 {formatPct(holdoutBaseline.average_net_return_pct)} · 复利 {formatPct(holdoutBaseline.total_return_pct)} · 期末 {formatCurrency(holdoutBaseline.final_equity)}
          </span>
          <span className={amountTone(holdoutGate.average_net_return_pct)}>
            预热准入 {holdoutGate.trade_count} 笔 · 胜率 {formatPct(holdoutGate.win_rate, false)} · 平均 {formatPct(holdoutGate.average_net_return_pct)} · 复利 {formatPct(holdoutGate.total_return_pct)} · 期末 {formatCurrency(holdoutGate.final_equity)}
          </span>
        </div>
      )}
      {!report.formal_concept_backtest_ready && (
        <div className="border-t px-3 py-2 text-xs text-muted-foreground sm:px-4">
          历史概念成员和盘中资金覆盖未达正式门槛；当前改善只作为首板因子研究，不改变推荐动作。
        </div>
      )}
    </section>
  );
}

function ComparisonRow({ row }: { row: LimitUpSectorWarmupComparison }) {
  return (
    <tr>
      <td className="px-3 py-3 sm:px-4">
        <div className="font-medium text-foreground">{row.label}</div>
        {row.variant === "warmup_leader_proxy" && (
          <div className="text-xs text-muted-foreground">昨日龙头代理，不代表盘中动态龙头</div>
        )}
      </td>
      <td className="px-3 py-3 text-right tabular-nums">{row.trade_count}</td>
      <td className="px-3 py-3 text-right tabular-nums">{formatPct(row.seal_rate, false)}</td>
      <td className={cn("px-3 py-3 text-right tabular-nums", rateTone(row.win_rate))}>{formatPct(row.win_rate, false)}</td>
      <td className={cn("px-3 py-3 text-right tabular-nums", amountTone(row.average_net_return_pct))}>{formatPct(row.average_net_return_pct)}</td>
      <td className={cn("px-3 py-3 text-right tabular-nums", amountTone(row.total_return_pct))}>{formatPct(row.total_return_pct)}</td>
      <td className="px-3 py-3 text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</td>
      <td className="px-3 py-3 text-right font-medium tabular-nums sm:pr-4">{formatCurrency(row.final_equity)}</td>
    </tr>
  );
}

function formatPct(value?: number | null, sign = true) {
  if (value == null || !Number.isFinite(value)) return "--";
  const prefix = sign && value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(2)}%`;
}

function formatCurrency(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "--";
  return `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function amountTone(value?: number | null) {
  if (value == null) return "text-muted-foreground";
  return value >= 0 ? "text-rise" : "text-fall";
}

function rateTone(value?: number | null) {
  if (value == null) return "text-muted-foreground";
  return value >= 50 ? "text-rise" : "text-fall";
}
