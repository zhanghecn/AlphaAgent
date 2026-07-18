import { Database } from "lucide-react";

import type {
  LimitUpRadarValidation,
  LimitUpStrategyGuide,
} from "@/api/limitUp";
import { cn } from "@/lib/utils";

export function GuideDataset({
  guide,
  radarValidation,
  radarValidationLoading = false,
  radarValidationError = null,
}: {
  guide: LimitUpStrategyGuide;
  radarValidation?: LimitUpRadarValidation;
  radarValidationLoading?: boolean;
  radarValidationError?: string | null;
}) {
  const { dataset, field_groups: groups, historical_reference: history } = guide;
  const radar = {
    ...guide.radar_evidence,
    status: radarValidation?.status ?? guide.radar_evidence.status,
    complete_trade_days:
      radarValidation?.coverage.complete_trade_days
      ?? guide.radar_evidence.complete_trade_days,
    minute_coverage_pct:
      radarValidation?.coverage.minute_pair_coverage_pct
      ?? guide.radar_evidence.minute_coverage_pct,
    selected_contract:
      radarValidation?.acceptance.selected_contract
      ?? guide.radar_evidence.selected_contract,
    recommended_contract:
      radarValidation?.acceptance.recommended_contract
      ?? guide.radar_evidence.selected_contract,
    activation_required:
      radarValidation?.acceptance.activation_required ?? false,
    production_contract_mismatch:
      radarValidation?.acceptance.production_contract_mismatch ?? false,
  };
  const radarUnavailable = Boolean(radarValidationError) && !radarValidation;
  const radarPending = radarValidationLoading && !radarValidation;
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

      <section className="mt-5" aria-labelledby="radar-validation-title">
        <h3 id="radar-validation-title" className="text-sm font-semibold">
          采集与正式推荐的边界：3% 开始盯、5% 才推荐
        </h3>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {radar.selected_contract === "formal_5pct"
            ? "股票涨到 3% 系统就开始盯上它并保存研究证据，但只有涨到 5% 才会出现在正式推荐里。在积累到足够样本并正式发布前，页面上只有 5% 起的推荐。"
            : "3% 起的同规则已经正式发布，页面上只有一套正式推荐和一套执行口径。"}
        </p>
        <div className="mt-2 overflow-x-auto border-y">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">采集边界</th>
                <th className="px-3 py-2 font-medium">正式边界</th>
                <th className="px-3 py-2 font-medium">完整交易日</th>
                <th className="px-3 py-2 font-medium">分钟覆盖</th>
                <th className="px-3 py-2 font-medium">当前合同</th>
                <th className="px-3 py-2 font-medium">验收建议</th>
                <th className="px-3 py-2 font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t">
                <td className="px-3 py-2 tabular-nums">
                  {radar.capture_min_change_pct}% 开始采集
                </td>
                <td className="px-3 py-2 tabular-nums">
                  {radar.formal_min_change_pct}% 正式推荐
                </td>
                <td className="px-3 py-2 tabular-nums">
                  {radarUnavailable
                    ? `-- / ${radar.target_trade_days} 日`
                    : radarPending
                      ? "读取中"
                      : `${radar.complete_trade_days} / ${radar.target_trade_days} 日`}
                </td>
                <td className="px-3 py-2 tabular-nums">
                  {radarUnavailable
                    ? "读取失败"
                    : radarPending
                      ? "读取中"
                      : radar.minute_coverage_pct == null
                      ? "待补齐"
                      : formatPct(radar.minute_coverage_pct, 4)}
                </td>
                <td className="px-3 py-2">
                  {radar.selected_contract === "formal_5pct"
                    ? "5%正式合同"
                    : "3%同规则合同"}
                </td>
                <td className="px-3 py-2">
                  {radar.recommended_contract === "early_3pct_same_rules"
                    ? "建议3%合同"
                    : "保持5%合同"}
                </td>
                <td className="px-3 py-2 text-muted-foreground">
                  {radarUnavailable
                    ? "读取失败"
                    : radarPending
                      ? "读取中"
                      : radarStatusLabel(
                          radar.status,
                          radar.activation_required,
                          radar.production_contract_mismatch,
                        )}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] leading-4 text-muted-foreground">
          {`完整分钟分母：${radar.minute_sessions.join("、")}，共 ${radar.minute_slot_count} 个去重分钟槽位；成交报价只认${radar.entry_fill_same_window ? "同一买入窗口内 " : ""}${radar.entry_fill_delay_seconds[0]}-${radar.entry_fill_delay_seconds[1]} 秒。`}
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
            <dt className="shrink-0 font-medium text-foreground">买入价</dt>
            <dd className="text-muted-foreground">
              取信号触发后 20–60 秒内的第一条保存报价，再在这个价格上加上 0.1% 的滑点（模拟实际买入会买贵一点点），且不超过涨停价。
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

function radarStatusLabel(
  status: LimitUpStrategyGuide["radar_evidence"]["status"],
  activationRequired: boolean,
  productionMismatch: boolean,
) {
  if (status === "accepted" && activationRequired) return "已通过，待发布";
  if (productionMismatch) return "生产与验收不一致";
  if (status === "accepted") return "已通过";
  if (status === "rejected") return "未通过";
  if (status === "ready_for_review") return "待最终复核";
  if (status === "process_ready") return "过程检查可用";
  return "采集中";
}

function formatPct(value: number, digits = 2) {
  return `${value.toFixed(digits)}%`;
}

function formatSignedPct(value: number, digits = 2) {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}
