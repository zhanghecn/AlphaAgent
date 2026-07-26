import { Database } from "lucide-react";

import type { LimitUpStrategyGuide } from "@/api/limitUp";
import { cn } from "@/lib/utils";

export function GuideDataset({
  guide,
}: {
  guide: LimitUpStrategyGuide;
}) {
  const { dataset, field_groups: groups, historical_reference: history } = guide;
  const core = guide.core_quality;
  const evidence = core.frozen_evidence;
  const recent = core.recent_snapshot_check;
  return (
    <div>
      <section className="border-y bg-muted/20" aria-labelledby="evidence-scope-title">
        <h3 id="evidence-scope-title" className="sr-only">一套规则，两层证据</h3>
        <div className="grid sm:grid-cols-2">
          <div className="border-b px-3 py-3 sm:border-b-0 sm:border-r">
            <div className="text-xs font-medium">当前 A+B 冻结证据</div>
            <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
              {evidence.date_start} 至 {evidence.date_end}，{evidence.closed_count} 笔闭合独立交易。
            </p>
          </div>
          <div className="px-3 py-3">
            <div className="text-xs font-medium">旧合同只读审计</div>
            <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
              旧快照和旧财报修复母池只解释研究过程，不参与当前推荐或回退。
            </p>
          </div>
        </div>
      </section>

      <section className="mt-5" aria-labelledby="core-contract-title">
        <h3 id="core-contract-title" className="text-sm font-semibold">
          唯一正式核心质量门
        </h3>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {core.contract_version}：基础质量门通过后，过去 {core.prior_limit_window_days} 个交易日涨停次数必须在
          {core.minimum_prior_limit_count} 到 {core.maximum_prior_limit_count} 次之间。
        </p>
        <div className="mt-2 overflow-x-auto border-y">
          <table className="w-full min-w-[680px] text-left text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">层级</th>
                <th className="px-3 py-2 font-medium">D-1 行业量能</th>
                <th className="px-3 py-2 font-medium">正式动作</th>
                <th className="px-3 py-2 font-medium">冻结结果</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t">
                <td className="px-3 py-2 align-top font-medium">A · 优先</td>
                <td className="px-3 py-2 align-top tabular-nums">5 日量比 ≥ {core.a_tier_industry_turnover_ratio_5d.toFixed(1)}</td>
                <td className="px-3 py-2 align-top">可交易</td>
                <td className="px-3 py-2 align-top tabular-nums">
                  {evidence.a_tier.win_count}/{evidence.a_tier.closed_count} · {formatPct(evidence.a_tier.win_rate_pct, 4)}
                </td>
              </tr>
              <tr className="border-t">
                <td className="px-3 py-2 align-top font-medium">B · 保留</td>
                <td className="px-3 py-2 align-top">未扩张或不可用</td>
                <td className="px-3 py-2 align-top">{core.b_tier_is_actionable ? "可交易" : "只观察"}</td>
                <td className="px-3 py-2 align-top tabular-nums">
                  {evidence.b_tier.win_count}/{evidence.b_tier.closed_count} · {formatPct(evidence.b_tier.win_rate_pct, 4)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] leading-4 text-muted-foreground">
          {core.priority_rule}。股票名、行业名和概念名都不写死。
        </p>
        <dl className="mt-4 grid grid-cols-2 border-y sm:grid-cols-4">
          <DatasetMetric label="闭合交易" value={`${evidence.closed_count} 笔`} />
          <DatasetMetric label="胜负" value={`${evidence.win_count} 胜 · ${evidence.closed_count - evidence.win_count} 负`} />
          <DatasetMetric label="全量胜率" value={formatPct(evidence.win_rate_pct, 4)} positive />
          <DatasetMetric label="平均净收益" value={formatSignedPct(evidence.average_net_return_pct, 4)} positive />
        </dl>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 text-xs sm:grid-cols-4">
          <Definition label="最大回撤" value={formatSignedPct(evidence.max_drawdown_pct, 4)} />
          <Definition label="硬亏率" value={formatPct(evidence.hard_loss_rate_pct, 4)} />
          <Definition label="起始" value={evidence.date_start} mono />
          <Definition label="截止" value={evidence.date_end} mono />
        </dl>
        <p className="mt-3 border-l-2 border-amber-500 px-3 text-xs leading-5 text-muted-foreground">
          历史候选代理通过，但还不是实盘等价证明。最近保存快照 {recent.date_start} 至 {recent.date_end}
          共 {recent.closed_count} 笔闭合，{recent.win_count} 胜，胜率 {formatPct(recent.win_rate_pct, 2)}，
          平均 {formatSignedPct(recent.average_net_return_pct, 4)}；尚未通过 60% 自然前向门。
        </p>
      </section>

      <section className="mt-5 border-t pt-4" aria-labelledby="dataset-title">
        <div className="mt-5 flex items-start gap-3">
          <Database className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <h3 id="dataset-title" className="text-sm font-semibold">{dataset.name}</h3>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              这是旧版本当时保存下来的行情画面，只用于核对研究过程；不代表当前 A+B 合同，也不会被系统自动采用。
            </p>
            <p className="mt-1 break-all font-mono text-[11px] text-muted-foreground">
              数据表 {dataset.table} · 区间 {dataset.date_start} 至 {dataset.date_end}
            </p>
          </div>
        </div>

        <dl className="mt-4 grid grid-cols-2 border-y opacity-75 sm:grid-cols-4">
          <DatasetMetric label="保存的行情画面" value={`${dataset.snapshot_count} 帧`} />
          <DatasetMetric
            label="已闭合信号"
            value={`${dataset.closed_signal_count} 只 · ${dataset.win_count} 胜`}
          />
          <DatasetMetric label="胜率" value={formatPct(dataset.win_rate_pct, 4)} positive />
          <DatasetMetric
            label="平均净收益"
            value={formatSignedPct(dataset.average_net_return_pct, 4)}
            positive
          />
        </dl>
      </section>

      <section className="mt-5 border-t pt-4" aria-labelledby="history-reference-title">
        <h3 id="history-reference-title" className="text-sm font-semibold">{history.name}</h3>
        <p className="mt-1 break-all font-mono text-[11px] text-muted-foreground">
          {history.tables.join(" + ")} · {history.date_start}..{history.date_end}
        </p>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 text-xs sm:grid-cols-4">
          <Definition label="交易日" value={`${history.trade_day_count} 日`} />
          <Definition label="合格信号" value={`${history.qualified_signal_count} 只`} />
          <Definition
            label="全推荐闭合"
            value={`${history.closed_recommendation_count} 只 · ${formatPct(history.recommendation_win_rate_pct, 4)}`}
          />
        </dl>
        <p className="mt-3 text-xs leading-5 text-muted-foreground">用途：{history.purpose}。</p>
        <p className="mt-2 border-l-2 border-amber-500 px-3 text-xs leading-5 text-muted-foreground">
          {history.limitation}
        </p>
      </section>

      <section className="mt-5" aria-labelledby="daily-coverage-title">
        <h3 id="daily-coverage-title" className="text-sm font-semibold">快照覆盖</h3>
        <div className="mt-2 overflow-x-auto border-y">
          <table className="w-full min-w-[420px] text-left text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">交易日</th>
                <th className="px-3 py-2 text-right font-medium">快照</th>
                <th className="px-3 py-2 font-medium">结果状态</th>
              </tr>
            </thead>
            <tbody>
              {dataset.daily_snapshot_counts.map((row) => (
                <tr key={row.trade_date} className="border-t">
                  <td className="px-3 py-2 font-mono tabular-nums">{row.trade_date}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.snapshot_count}</td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {row.trade_date <= dataset.closed_through ? "D+1已闭合" : "未使用盘中价替代"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-5" aria-labelledby="field-timing-title">
        <h3 id="field-timing-title" className="text-sm font-semibold">字段时点</h3>
        <div className="mt-2 overflow-x-auto border-y">
          <table className="w-full min-w-[640px] text-left text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="w-36 px-3 py-2 font-medium">字段组</th>
                <th className="w-28 px-3 py-2 font-medium">参与选股</th>
                <th className="px-3 py-2 font-medium">字段</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => (
                <tr key={group.key} className="border-t align-top">
                  <td className="px-3 py-3 font-medium">{group.label}</td>
                  <td className={cn(
                    "px-3 py-3",
                    group.selection_allowed ? "text-rise" : "text-muted-foreground",
                  )}>
                    {group.selection_allowed ? "允许" : "禁止"}
                  </td>
                  <td className="px-3 py-3 leading-5 text-muted-foreground">
                    {group.fields.join("；")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-5 border-t pt-4 text-xs leading-5" aria-labelledby="execution-contract-title">
        <h3 id="execution-contract-title" className="text-sm font-semibold">怎么算买入价、卖出价和费用</h3>
        <dl className="mt-2 space-y-2">
          <div className="flex gap-2">
            <dt className="shrink-0 font-medium text-foreground">正式 A+B 买入</dt>
            <dd className="text-muted-foreground">
              使用正式触发时保存的价格代理，并加 0.1% 滑点且不超过涨停价；涨停价信号只表示可尝试排队，不保证成交。
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="shrink-0 font-medium text-foreground">卖出价</dt>
            <dd className="text-muted-foreground">
              次日（D+1）的官方日线收盘价，再扣掉 0.1% 的滑点。没有收盘价的票直接剔除，不用盘中价凑数。
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="shrink-0 font-medium text-foreground">费用</dt>
            <dd className="text-muted-foreground">
              佣金万分之三（每笔最低 5 元）、过户费万分之一（买卖都收）、卖出时另收印花税万分之五。
            </dd>
          </div>
        </dl>
        <p className="mt-2 break-all font-mono text-[11px] text-muted-foreground">
          A+B 冻结研究报告：{evidence.report}
        </p>
        <ul className="mt-3 space-y-1 text-muted-foreground">
          {dataset.limitations.map((item) => <li key={item}>· {item}</li>)}
        </ul>
        <p className="mt-3 border-l-2 border-amber-500 px-3 text-muted-foreground">
          次日收盘价是「结果」，必须等选股全部完成后才能确定，绝不反过来参与当天的选股。
        </p>
      </section>
    </div>
  );
}

function Definition({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={cn("mt-1 leading-5 text-foreground", mono && "font-mono text-[11px]")}>{value}</dd>
    </div>
  );
}

function DatasetMetric({
  label,
  value,
  positive = false,
}: {
  label: string;
  value: string;
  positive?: boolean;
}) {
  return (
    <div className="min-w-0 border-b border-r px-3 py-3 even:border-r-0 sm:border-b-0 sm:even:border-r sm:last:border-r-0">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className={cn("mt-1 text-sm font-semibold tabular-nums", positive && "text-rise")}>{value}</dd>
    </div>
  );
}

function formatPct(value: number, digits = 2) {
  return `${value.toFixed(digits)}%`;
}

function formatSignedPct(value: number, digits = 2) {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}
