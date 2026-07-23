import { Database } from "lucide-react";

import type { LimitUpStrategyGuide } from "@/api/limitUp";
import { cn } from "@/lib/utils";

export function GuideDataset({
  guide,
}: {
  guide: LimitUpStrategyGuide;
}) {
  const { dataset, field_groups: groups, historical_reference: history } = guide;
  const preboard = guide.preboard_decision;
  return (
    <div>
      <section className="border-y bg-muted/20" aria-labelledby="evidence-scope-title">
        <h3 id="evidence-scope-title" className="sr-only">一套规则，两层证据</h3>
        <div className="grid sm:grid-cols-2">
          <div className="border-b px-3 py-3 sm:border-b-0 sm:border-r">
            <div className="text-xs font-medium">当前规则验证</div>
            <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
              {dataset.snapshot_count} 帧保存快照，按当时可见数据重放 v15。
            </p>
          </div>
          <div className="px-3 py-3">
            <div className="text-xs font-medium">长期历史参考</div>
            <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
              {history.trade_day_count} 个交易日的候选代理，不是另一套执行算法。
            </p>
          </div>
        </div>
      </section>

      <section className="mt-5" aria-labelledby="preboard-contract-title">
        <h3 id="preboard-contract-title" className="text-sm font-semibold">
          板前概率观察与正式买点边界
        </h3>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {preboard.quality_pool_rule}。3% 不是买点，涨幅、距离涨停、速度、加速度和资金增量只进入概率计算。
        </p>
        <div className="mt-2 overflow-x-auto border-y">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">观察激活</th>
                <th className="px-3 py-2 font-medium">动态输出</th>
                <th className="px-3 py-2 font-medium">排序顺序</th>
                <th className="px-3 py-2 font-medium">正式策略影响</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t">
                <td className="px-3 py-2 align-top tabular-nums">
                  高质量首板达到 {preboard.observation_min_change_pct}%
                </td>
                <td className="px-3 py-2 align-top">
                  {preboard.probability_outputs.join("、")}
                </td>
                <td className="px-3 py-2 align-top">
                  {preboard.ranking_order.join(" → ")}
                </td>
                <td className="px-3 py-2 align-top text-muted-foreground">
                  {preboard.formal_baseline}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] leading-4 text-muted-foreground">
          {preboard.promotion_rule}。合同：{preboard.decision_version}
        </p>
      </section>

      <section aria-labelledby="dataset-title">
        <div className="mt-5 flex items-start gap-3">
          <Database className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <h3 id="dataset-title" className="text-sm font-semibold">{dataset.name}</h3>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              把当时保存下来的行情画面，按当时的规则原样重新跑一遍，看这套规则在过去到底赚不赚钱——而不是另搞一套执行算法。
            </p>
            <p className="mt-1 break-all font-mono text-[11px] text-muted-foreground">
              数据表 {dataset.table} · 区间 {dataset.date_start} 至 {dataset.date_end}
            </p>
          </div>
        </div>

        <dl className="mt-4 grid grid-cols-2 border-y sm:grid-cols-4">
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
          <Definition
            label="两仓成交"
            value={`${history.account_trade_count} 笔 · ${formatPct(history.account_win_rate_pct, 4)}`}
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

      <section className="mt-5" aria-labelledby="portfolio-result-title">
        <h3 id="portfolio-result-title" className="text-sm font-semibold">两仓到达顺序回放</h3>
        <dl className="mt-3 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-2">
          <Definition
            label="成交"
            value={`${dataset.portfolio_trade_count} 笔，${dataset.portfolio_win_count} 胜`}
          />
          <Definition label="账户收益" value={formatSignedPct(dataset.portfolio_return_pct, 4)} />
          <Definition label="最大回撤" value={formatSignedPct(dataset.portfolio_max_drawdown_pct, 4)} />
          <Definition label="闭合截止" value={dataset.closed_through} mono />
        </dl>
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
            <dt className="shrink-0 font-medium text-foreground">板前 C 买入</dt>
            <dd className="text-muted-foreground">
              只认行动后第一条严格低于涨停价的新报价；一分钟历史代理使用下一分钟开盘价，等于涨停价或缺少报价都算未成交。
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="shrink-0 font-medium text-foreground">正式 v15 买入</dt>
            <dd className="text-muted-foreground">
              触板基线仍取信号后 20–60 秒内第一条保存报价，并加 0.1% 滑点且不超过涨停价；涨停价信号只表示可尝试排队，不保证成交。
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
          详细回测报告：{dataset.report}
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
