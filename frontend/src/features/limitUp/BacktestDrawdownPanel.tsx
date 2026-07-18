import type {
  LimitUpDrawdownDiagnostics,
  LimitUpDrawdownReturnMetrics,
  LimitUpEntrySummary,
} from "@/api/limitUp";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn } from "@/lib/utils";
import {
  amountTone,
  boardStatusLabel,
  rateTone,
} from "./liveFormat";
import { limitUpLaneLabel } from "./limitUpPresentation";

export function BacktestDrawdownPanel({
  diagnostics,
}: {
  diagnostics: LimitUpDrawdownDiagnostics;
}) {
  const episode = diagnostics.maximum_drawdown_episode;
  const streak = diagnostics.longest_losing_streak;
  const attribution = diagnostics.board_outcome_attribution;

  return (
    <section className="border-b" aria-label="回撤与连亏诊断">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b bg-muted/20 px-3 py-2 sm:px-4">
        <h2 className="text-sm font-semibold">回撤与连亏诊断</h2>
        <span className="text-xs font-medium text-amber-700 dark:text-amber-300">
          账户回撤与全量推荐不是同一条曲线
        </span>
        <span className="text-xs text-muted-foreground">
          {diagnostics.scope_explanation}
        </span>
      </div>

      <dl className="grid border-b sm:grid-cols-3">
        <DiagnosticMetric
          label="两仓账户最大回撤"
          value={formatDiagnosticPct(episode.drawdown_pct)}
          tone="text-fall"
          detail={`${episode.peak_date ?? "--"} → ${episode.trough_date ?? "--"}${episode.recovery_date ? ` · ${episode.recovery_date} 修复` : " · 尚未修复"}`}
        />
        <DiagnosticMetric
          label={`连续亏损 ${streak.count} 笔`}
          value={formatDiagnosticPct(streak.compound_return_pct)}
          tone="text-fall"
          detail={`${streak.start_date ?? "--"} → ${streak.end_date ?? "--"}`}
        />
        <DiagnosticMetric
          label="炸板贡献的硬亏"
          value={`${attribution.hard_loss_failed_count} / ${attribution.hard_loss_count}`}
          tone="text-fall"
          detail={`占硬亏 ${formatDiagnosticPct(attribution.hard_loss_failed_share_pct)}`}
        />
      </dl>

      <div className="grid min-w-0 border-b lg:grid-cols-2">
        <section className="min-w-0 border-b lg:border-b-0 lg:border-r" aria-label="主要回撤交易">
          <h3 className="border-b px-3 py-2 text-xs font-semibold sm:px-4">
            最大回撤阶段的主要亏损
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-xs">
              <thead className="border-b bg-muted/20 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">落账日</th>
                  <th className="px-3 py-2 text-left">股票</th>
                  <th className="px-3 py-2 text-left">板位 / 当日结果</th>
                  <th className="px-3 py-2 text-right">净收益</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {episode.principal_losses.map((trade) => (
                  <tr key={`${trade.exit_date}:${trade.vt_symbol}`}>
                    <td className="px-3 py-2 tabular-nums">{trade.exit_date ?? trade.sell_date ?? "--"}</td>
                    <td className="px-3 py-2">
                      <StockIdentityLink name={trade.name} vtSymbol={trade.vt_symbol} />
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {limitUpLaneLabel(trade.lane)} · {boardStatusLabel(trade.d_board_status ?? "unknown")}
                    </td>
                    <td className="px-3 py-2 text-right font-semibold tabular-nums text-fall">
                      {formatDiagnosticPct(trade.return_pct)}
                    </td>
                  </tr>
                ))}
                {!episode.principal_losses.length && (
                  <tr>
                    <td colSpan={4} className="px-3 py-8 text-center text-muted-foreground">
                      当前区间没有回撤亏损交易
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="min-w-0" aria-label="连续亏损原因">
          <h3 className="border-b px-3 py-2 text-xs font-semibold sm:px-4">为什么会呈现连续性</h3>
          <ol className="divide-y">
            {diagnostics.causes.map((cause) => (
              <li key={cause.code} className="px-3 py-2.5 text-xs leading-5 sm:px-4">
                <p className="break-words font-medium text-foreground">{cause.finding}</p>
                <p className="break-words text-muted-foreground">{cause.implication}</p>
              </li>
            ))}
            {!diagnostics.causes.length && (
              <li className="px-3 py-8 text-center text-xs text-muted-foreground">
                当前样本不足以形成稳定归因
              </li>
            )}
          </ol>
        </section>
      </div>

      <CohortComparison diagnostics={diagnostics} />
      <OutcomeAndCalibration diagnostics={diagnostics} />
      <CausalExitResearch diagnostics={diagnostics} />
    </section>
  );
}

function CohortComparison({ diagnostics }: { diagnostics: LimitUpDrawdownDiagnostics }) {
  const rows = [
    {
      label: "时间验证段",
      period: `${diagnostics.execution_filter.time_validation.start} → ${diagnostics.execution_filter.time_validation.end}`,
      ...diagnostics.execution_filter.time_validation,
    },
    {
      label: "最近入场月",
      period: diagnostics.execution_filter.latest_entry_month.month ?? "--",
      ...diagnostics.execution_filter.latest_entry_month,
    },
  ];
  return (
    <section className="border-b" aria-label="成交与跳过推荐对照">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b px-3 py-2 sm:px-4">
        <h3 className="text-xs font-semibold">两仓约束隔离了哪些票</h3>
        <span className="text-xs text-muted-foreground">
          同期比较实际成交与因持仓已满跳过的 D+1 反事实结果
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-xs">
          <thead className="border-b bg-muted/20 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">样本</th>
              <th className="px-3 py-2 text-left">两仓实际成交</th>
              <th className="px-3 py-2 text-left">持仓已满跳过</th>
              <th className="px-3 py-2 text-left">结论</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((row) => (
              <tr key={row.label}>
                <td className="px-3 py-2.5">
                  <div className="font-medium">{row.label}</div>
                  <div className="tabular-nums text-muted-foreground">{row.period}</div>
                </td>
                <td className="px-3 py-2.5">
                  <CohortMetrics prefix="成交" metrics={row.executed} />
                </td>
                <td className="px-3 py-2.5">
                  <CohortMetrics prefix="跳过" metrics={row.skipped} />
                </td>
                <td className="px-3 py-2.5 text-muted-foreground">
                  {cohortConclusion(row.executed, row.skipped)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CohortMetrics({
  prefix,
  metrics,
}: {
  prefix: string;
  metrics: LimitUpDrawdownReturnMetrics;
}) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 tabular-nums">
      <span>{prefix} {metrics.count} 笔</span>
      <span className={rateTone(metrics.win_rate)}>胜率 {formatDiagnosticPct(metrics.win_rate)}</span>
      <span className={amountTone(metrics.average_return_pct)}>平均 {formatDiagnosticPct(metrics.average_return_pct)}</span>
    </div>
  );
}

function OutcomeAndCalibration({ diagnostics }: { diagnostics: LimitUpDrawdownDiagnostics }) {
  return (
    <div className="grid min-w-0 border-b lg:grid-cols-2">
      <section className="min-w-0 border-b lg:border-b-0 lg:border-r" aria-label="封板结果归因">
        <div className="border-b px-3 py-2 sm:px-4">
          <h3 className="text-xs font-semibold">封住 / 炸板的亏损归因</h3>
          <p className="mt-0.5 text-[11px] text-amber-700 dark:text-amber-300">
            收盘后归因，不能作为当天买入条件
          </p>
        </div>
        <AttributionTable diagnostics={diagnostics} />
      </section>

      <section className="min-w-0" aria-label="同股联合率校准">
        <div className="border-b px-3 py-2 sm:px-4">
          <h3 className="text-xs font-semibold">同股联合率在验证段失去单调性</h3>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            数值更高并没有带来更高胜率，暂不提高静态门槛
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[440px] text-xs">
            <thead className="border-b bg-muted/20 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">联合率</th>
                <th className="px-3 py-2 text-right">样本</th>
                <th className="px-3 py-2 text-right">胜率</th>
                <th className="px-3 py-2 text-right">平均 D+1</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {diagnostics.stock_gene_calibration.time_validation.map((bucket) => (
                <tr key={bucket.bucket}>
                  <td className="px-3 py-2">{bucket.bucket}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{bucket.count}</td>
                  <td className={cn("px-3 py-2 text-right tabular-nums", rateTone(bucket.win_rate))}>
                    {formatDiagnosticPct(bucket.win_rate)}
                  </td>
                  <td className={cn("px-3 py-2 text-right tabular-nums", amountTone(bucket.average_return_pct))}>
                    {formatDiagnosticPct(bucket.average_return_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function AttributionTable({ diagnostics }: { diagnostics: LimitUpDrawdownDiagnostics }) {
  const attribution = diagnostics.board_outcome_attribution;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[440px] text-xs">
        <thead className="border-b bg-muted/20 text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left">D 日结果</th>
            <th className="px-3 py-2 text-right">成交</th>
            <th className="px-3 py-2 text-right">胜率</th>
            <th className="px-3 py-2 text-right">平均收益</th>
            <th className="px-3 py-2 text-right">硬亏</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {attribution.groups.map((group) => (
            <tr key={group.status}>
              <td className="px-3 py-2 font-medium">{boardStatusLabel(group.status)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{group.count}</td>
              <td className={cn("px-3 py-2 text-right tabular-nums", rateTone(group.win_rate))}>{formatDiagnosticPct(group.win_rate)}</td>
              <td className={cn("px-3 py-2 text-right tabular-nums", amountTone(group.average_return_pct))}>{formatDiagnosticPct(group.average_return_pct)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-fall">{group.hard_loss_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CausalExitResearch({ diagnostics }: { diagnostics: LimitUpDrawdownDiagnostics }) {
  const research = diagnostics.exit_research;
  const withdrawn = research.withdrawn_policy;
  const benchmark = research.d0_open_benchmark;
  const precommitted = research.precommitted_limit_research;
  const postAuction = research.post_auction_research;
  const coverage = postAuction.coverage;
  return (
    <section aria-label="因果退出研究">
      <div className="border-b bg-muted/20 px-3 py-2 sm:px-4">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h3 className="text-xs font-semibold">退出研究：旧竞价影子已撤回</h3>
          <span className="text-xs font-medium text-fall">同价决策成交泄漏</span>
        </div>
        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
          09:25 看见最终开盘价后不能再按该开盘价成交；旧影子的收益、胜率和复利指标不再有效。
        </p>
      </div>
      <div className="grid min-w-0 border-b xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 border-b xl:border-b-0 xl:border-r">
          <div className="border-b px-3 py-2 text-xs font-semibold sm:px-4">撤回依据</div>
          <ul className="divide-y">
            {withdrawn.reason_codes.map((reason) => (
              <li key={reason.code} className="break-words px-3 py-2 text-xs leading-5 text-muted-foreground sm:px-4">
                {reason.detail}
              </li>
            ))}
          </ul>
        </div>
        <dl className="grid grid-cols-2 text-xs xl:grid-cols-1">
          <div className="border-b border-r px-3 py-2.5 xl:border-r-0 sm:px-4">
            <dt className="text-muted-foreground">失效状态</dt>
            <dd className="mt-1 font-medium text-fall">指标已撤回</dd>
          </div>
          <div className="border-b px-3 py-2.5 sm:px-4">
            <dt className="text-muted-foreground">正式规则</dt>
            <dd className="mt-1 font-medium">v9 · D+1 收盘退出</dd>
          </div>
        </dl>
      </div>

      <div className="border-b">
        <div className="border-b px-3 py-2 sm:px-4">
          <h3 className="text-xs font-semibold">D0 无条件开盘退出基准</h3>
          <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">
            决策在 D0 收盘后完成，不读取 D+1 价格；该基准可交易，但同时降低胜率和复利。
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-xs">
            <thead className="border-b bg-muted/20 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">方案</th>
                <th className="px-3 py-2 text-right">闭合</th>
                <th className="px-3 py-2 text-right">复利</th>
                <th className="px-3 py-2 text-right">胜率</th>
                <th className="px-3 py-2 text-right">最大回撤</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              <tr>
                <td className="px-3 py-2.5 font-medium">v9 · D+1 收盘</td>
                <SummaryCells summary={benchmark.baseline_summary} muted />
              </tr>
              <tr>
                <td className="px-3 py-2.5 font-medium">D0 承诺首板 D+1 开盘</td>
                <SummaryCells summary={benchmark.summary} />
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid min-w-0 border-b md:grid-cols-[minmax(0,1fr)_280px]">
        <div className="border-b px-3 py-2.5 md:border-b-0 md:border-r sm:px-4">
          <h3 className="text-xs font-semibold">D0 预挂条件限价单</h3>
          <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{precommitted.rule}</p>
          <p className="mt-1 text-[11px] leading-5 text-amber-700 dark:text-amber-300">
            不发布收益：{precommitted.account_performance_reason}
          </p>
        </div>
        <dl className="grid grid-cols-2 text-xs md:grid-cols-1">
          <div className="border-b border-r px-3 py-2.5 md:border-r-0 sm:px-4">
            <dt className="text-muted-foreground">竞价快照覆盖</dt>
            <dd className="mt-1 font-medium tabular-nums">
              {precommitted.coverage.snapshot_covered_pair_count} / {precommitted.coverage.required_pair_count}
            </dd>
          </div>
          <div className="px-3 py-2.5 sm:px-4">
            <dt className="text-muted-foreground">严格完整 / 未匹配量</dt>
            <dd className="mt-1 font-medium tabular-nums text-fall">
              {precommitted.coverage.strict_complete_pair_count} / {precommitted.coverage.unmatched_volume_pair_count}
            </dd>
          </div>
        </dl>
      </div>

      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b px-3 py-2 sm:px-4">
          <div>
            <h3 className="text-xs font-semibold">09:25 信号 → 09:31 成交代理</h3>
            <p className="mt-0.5 text-[11px] text-muted-foreground">仅比较有真实分钟价的基准成交，不是完整资金账户</p>
          </div>
          <div className="text-right text-xs tabular-nums">
            <div className="font-medium">覆盖 {coverage.covered_pair_count} / {coverage.required_pair_count} 笔 · {formatDiagnosticPct(coverage.coverage_pct)}</div>
            <div className="text-[11px] text-muted-foreground">门槛 {formatDiagnosticPct(coverage.minimum_coverage_pct)}</div>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-xs">
            <thead className="border-b bg-muted/20 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">09:25 开盘收益信号</th>
                <th className="px-3 py-2 text-right">触发 / 覆盖样本</th>
                <th className="px-3 py-2 text-right">样本胜率</th>
                <th className="px-3 py-2 text-right">样本平均收益</th>
                <th className="px-3 py-2 text-right">相对持有收盘</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {postAuction.threshold_rows.map((row) => (
                <tr key={row.threshold_pct}>
                  <td className="px-3 py-2 font-medium">≥ {row.threshold_pct.toFixed(1)}%</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.trigger_count} / {row.sample_count}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatDiagnosticPct(row.win_rate)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatDiagnosticPct(row.average_return_pct)}</td>
                  <td className={cn("px-3 py-2 text-right tabular-nums", amountTone(row.average_return_delta_vs_close_pct_points))}>
                    {formatDiagnosticPct(row.average_return_delta_vs_close_pct_points)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="border-t px-3 py-2 text-[11px] leading-5 text-amber-700 dark:text-amber-300 sm:px-4">
          账户复利不发布：{postAuction.account_performance_reason}
        </p>
      </div>
    </section>
  );
}

function SummaryCells({ summary, muted = false }: { summary: LimitUpEntrySummary; muted?: boolean }) {
  const tone = muted ? "text-muted-foreground" : "";
  return (
    <>
      <td className={cn("px-3 py-2.5 text-right tabular-nums", tone)}>{summary.trade_count ?? 0}</td>
      <td className={cn("px-3 py-2.5 text-right tabular-nums", tone)}>{formatDiagnosticPct(summary.total_return_pct)}</td>
      <td className={cn("px-3 py-2.5 text-right tabular-nums", tone)}>{formatDiagnosticPct(summary.win_rate)}</td>
      <td className={cn("px-3 py-2.5 text-right tabular-nums", tone)}>{formatDiagnosticPct(summary.max_drawdown_pct)}</td>
    </>
  );
}

function DiagnosticMetric({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone?: string;
}) {
  return (
    <div className="border-b px-3 py-2.5 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0 sm:px-4">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className={cn("mt-0.5 text-base font-semibold tabular-nums", tone)}>{value}</dd>
      <dd className="mt-0.5 text-[11px] tabular-nums text-muted-foreground">{detail}</dd>
    </div>
  );
}

function cohortConclusion(
  executed: LimitUpDrawdownReturnMetrics,
  skipped: LimitUpDrawdownReturnMetrics,
) {
  if (executed.average_return_pct == null || skipped.average_return_pct == null) return "样本尚未闭合";
  const delta = executed.average_return_pct - skipped.average_return_pct;
  return delta > 0
    ? `两仓到达顺序使平均收益高 ${formatDiagnosticPct(delta)}`
    : "跳过推荐没有明显更弱";
}

function formatDiagnosticPct(value?: number | null) {
  return value == null || !Number.isFinite(value) ? "--" : `${value.toFixed(4)}%`;
}
