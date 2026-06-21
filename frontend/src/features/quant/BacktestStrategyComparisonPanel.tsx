import { RefreshCw, Scale } from "lucide-react";
import type {
  BacktestStrategyCandidatePhaseBucket,
  BacktestStrategyComparison,
  BacktestStrategyComparisonRow,
  BacktestStrategyPhaseBucket,
} from "@/api/quant";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn, formatAmount, formatPct, priceColorClass } from "@/lib/utils";

export function BacktestStrategyComparisonPanel({
  comparison,
  isLoading,
  error,
  onRun,
}: {
  comparison?: BacktestStrategyComparison;
  isLoading: boolean;
  error?: unknown;
  onRun: () => void;
}) {
  return (
    <section className="rounded-lg border p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-medium">
            <Scale size={15} />
            策略同口径对比
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            用当前日线回测参数非持久化重跑已注册策略，比较 BUY、成交、拒单、收益和回撤。
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={onRun} disabled={isLoading}>
          {isLoading ? <RefreshCw size={15} className="animate-spin" /> : <Scale size={15} />}
          运行策略对比
        </Button>
      </div>

      {error ? (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-2 text-sm text-fall dark:border-red-500/30 dark:bg-red-500/10">
          {error instanceof Error ? error.message : "策略对比失败"}
        </div>
      ) : null}

      {comparison ? (
        <div className="mt-3 space-y-3">
          {comparison.summary ? (
            <div className="grid gap-3 text-sm md:grid-cols-5">
              <InfoCell label="策略数" value={`${comparison.summary.ready_count ?? 0}/${comparison.summary.strategy_count ?? 0}`} />
              <InfoCell label="收益排序最优" value={comparison.summary.best_strategy_id ?? "--"} />
              <InfoCell
                label="收益排序"
                value={formatPct(comparison.summary.best_total_return_pct)}
                valueClass={priceColorClass(comparison.summary.best_total_return_pct)}
              />
              <InfoCell label="日线最优" value={comparison.summary.best_verifiable_strategy_id ?? "--"} />
              <InfoCell label="完成策略数" value={`${comparison.summary.ready_count ?? comparison.summary.complete_strict_count ?? 0} 个`} />
            </div>
          ) : null}

          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>策略</TableHead>
                  <TableHead>质量</TableHead>
                  <TableHead className="text-right">收益</TableHead>
                  <TableHead className="text-right">回撤</TableHead>
                  <TableHead className="text-right">期末权益</TableHead>
                  <TableHead className="text-right">BUY信号</TableHead>
                  <TableHead className="text-right">买入</TableHead>
                  <TableHead className="text-right">拒单</TableHead>
                  <TableHead className="text-right">成交行</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {comparison.rows.map((row) => (
                  <TableRow key={row.strategy_id}>
                    <TableCell>
                      <div className="font-medium">{row.strategy_name ?? row.strategy_id}</div>
                      <div className="text-xs text-muted-foreground">{row.strategy_id} / {row.strategy_version ?? "--"}</div>
                    </TableCell>
                    <TableCell>
                      <div className={cn("text-sm font-medium", qualityColorClass(row.quality_status))}>
                        {row.quality_label ?? "--"}
                      </div>
                      {row.quality_warning ? (
                        <div className="max-w-64 text-xs text-muted-foreground">{row.quality_warning}</div>
                      ) : null}
                    </TableCell>
                    <TableCell className={cn("text-right tabular-nums", priceColorClass(row.total_return_pct))}>
                      {formatPct(row.total_return_pct)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatAmount(row.final_equity)}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.buy_signal_count ?? "--"}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.buy_count ?? "--"}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.rejected_order_count ?? "--"}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.total_trade_rows ?? "--"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <StrategyPhaseMatrix rows={comparison.rows} />
          <CandidatePhaseMatrix rows={comparison.rows} />
          <div className="text-xs text-muted-foreground">
            {comparison.summary?.message ?? comparison.note ?? "策略对比不替代多年全 A、walk-forward 和参数敏感性验证。"}
          </div>
        </div>
      ) : null}
    </section>
  );
}

const PHASE_COLUMNS = [
  { id: "uptrend", label: "主升" },
  { id: "rotation", label: "震荡" },
  { id: "retreat", label: "退潮" },
  { id: "warming", label: "回暖" },
];

function StrategyPhaseMatrix({ rows }: { rows: BacktestStrategyComparisonRow[] }) {
  const readyRows = rows.filter((row) => (row.phase_summary?.by_phase ?? []).length > 0);
  if (!readyRows.length) return null;

  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2">
        <div className="text-sm font-medium">按行情阶段评审</div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          按真实闭合成交的买入日行情聚合，只读审计，不参与默认信号、排序、卖点或仓位。
        </div>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>策略</TableHead>
            {PHASE_COLUMNS.map((phase) => (
              <TableHead key={phase.id} className="text-right">{phase.label}</TableHead>
            ))}
            <TableHead className="text-right">适配提示</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {readyRows.map((row) => (
            <TableRow key={`phase-${row.strategy_id}`}>
              <TableCell>
                <div className="font-medium">{row.strategy_name ?? row.strategy_id}</div>
                <div className="text-xs text-muted-foreground">闭合 {row.phase_summary?.trade_count ?? 0} 笔</div>
              </TableCell>
              {PHASE_COLUMNS.map((phase) => (
                <TableCell key={phase.id} className="text-right">
                  <PhaseCell bucket={phaseBucket(row, phase.id)} />
                </TableCell>
              ))}
              <TableCell className="text-right text-xs text-muted-foreground">
                {row.phase_rank_hint?.best_phase_label
                  ? `${row.phase_rank_hint.best_phase_label} 相对占优`
                  : "--"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CandidatePhaseMatrix({ rows }: { rows: BacktestStrategyComparisonRow[] }) {
  const readyRows = rows.filter((row) => (row.candidate_phase_summary?.by_phase ?? []).length > 0);
  if (!readyRows.length) return null;

  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2">
        <div className="text-sm font-medium">候选 Top-N 按行情评审</div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          按理论买入候选信号日聚合，收益是后验审计，只用于判断候选质量和行情适配，不参与实盘信号。
        </div>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>策略</TableHead>
            {PHASE_COLUMNS.map((phase) => (
              <TableHead key={phase.id} className="text-right">{phase.label}</TableHead>
            ))}
            <TableHead className="text-right">样本</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {readyRows.map((row) => (
            <TableRow key={`candidate-phase-${row.strategy_id}`}>
              <TableCell>
                <div className="font-medium">{row.strategy_name ?? row.strategy_id}</div>
                <div className="text-xs text-muted-foreground">
                  Top {row.candidate_phase_summary?.top_limit ?? "--"} / 候选 {row.candidate_phase_summary?.signal_count ?? 0}
                </div>
              </TableCell>
              {PHASE_COLUMNS.map((phase) => (
                <TableCell key={phase.id} className="text-right">
                  <CandidatePhaseCell bucket={candidatePhaseBucket(row, phase.id)} />
                </TableCell>
              ))}
              <TableCell className="text-right text-xs text-muted-foreground">
                已评 {row.candidate_phase_summary?.evaluated_count ?? 0}
                {row.candidate_phase_summary?.not_triggered_count ? ` / 未触发 ${row.candidate_phase_summary.not_triggered_count}` : ""}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function PhaseCell({ bucket }: { bucket?: BacktestStrategyPhaseBucket }) {
  if (!bucket || !bucket.trade_count) {
    return <span className="text-xs text-muted-foreground">无成交</span>;
  }
  return (
    <div className="space-y-0.5 text-xs">
      <div className="font-medium tabular-nums">{bucket.trade_count} 笔</div>
      <div className={cn("tabular-nums", priceColorClass(bucket.avg_return_pct))}>
        胜 {formatPct(bucket.win_rate_pct)} / 均 {formatPct(bucket.avg_return_pct)}
      </div>
      {bucket.support_stop_count ? (
        <div className="text-muted-foreground">止损 {bucket.support_stop_count}</div>
      ) : null}
    </div>
  );
}

function CandidatePhaseCell({ bucket }: { bucket?: BacktestStrategyCandidatePhaseBucket }) {
  if (!bucket || !bucket.signal_count) {
    return <span className="text-xs text-muted-foreground">无候选</span>;
  }
  return (
    <div className="space-y-0.5 text-xs">
      <div className="font-medium tabular-nums">{bucket.signal_count} 个</div>
      <div className={cn("tabular-nums", priceColorClass(bucket.avg_return_pct))}>
        胜 {formatPct(bucket.win_rate_pct)} / 均 {formatPct(bucket.avg_return_pct)}
      </div>
      <div className="text-muted-foreground">
        评 {bucket.evaluated_count ?? 0}
        {bucket.not_triggered_count ? ` / 未触发 ${bucket.not_triggered_count}` : ""}
      </div>
    </div>
  );
}

function phaseBucket(row: BacktestStrategyComparisonRow, phase: string) {
  return (row.phase_summary?.by_phase ?? []).find((item) => item.phase === phase);
}

function candidatePhaseBucket(row: BacktestStrategyComparisonRow, phase: string) {
  return (row.candidate_phase_summary?.by_phase ?? []).find((item) => item.phase === phase);
}

function InfoCell({ label, value, valueClass }: { label: string; value?: string | number | null; valueClass?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 font-medium tabular-nums", valueClass)}>{value ?? "--"}</div>
    </div>
  );
}

function qualityColorClass(status?: string | null) {
  if (status === "complete_strict") return "text-rise";
  if (status === "strict_condition_rejections") return "text-amber-600 dark:text-amber-400";
  if (status === "missing_snapshots" || status === "uses_daily_close_proxy") return "text-fall";
  if (status === "no_fills") return "text-muted-foreground";
  return "";
}
