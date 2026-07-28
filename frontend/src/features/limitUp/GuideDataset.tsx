import type { LimitUpStrategyGuide } from "@/api/limitUp";
import { cn } from "@/lib/utils";

export function GuideDataset({
  guide,
}: {
  guide: LimitUpStrategyGuide;
}) {
  const groups = guide.field_groups;
  const core = guide.core_quality;
  const evidence = core.frozen_evidence;
  const forward = core.forward_status;
  return (
    <div>
      <section className="border-y bg-muted/20" aria-labelledby="evidence-scope-title">
        <h3 id="evidence-scope-title" className="sr-only">历史证据与自然前向</h3>
        <div className="grid sm:grid-cols-2">
          <div className="border-b px-3 py-3 sm:border-b-0 sm:border-r">
            <div className="text-xs font-medium">当前 A+B+C 冻结证据</div>
            <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
              {evidence.date_start} 至 {evidence.date_end}，{evidence.closed_count} 笔闭合独立交易。
            </p>
          </div>
          <div className="px-3 py-3">
            <div className="text-xs font-medium">自然前向验证</div>
            <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
              {forward.start_date} 起只接收当前正式合同产生并完成 D+1 结算的新交易。
            </p>
          </div>
        </div>
      </section>

      <section className="mt-5" aria-labelledby="core-contract-title">
        <h3 id="core-contract-title" className="text-sm font-semibold">
          唯一正式 A+B+C 质量合同
        </h3>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {core.contract_version}：A/B 使用 {core.prior_limit_window_days} 日 {core.minimum_prior_limit_count} 到
          {core.maximum_prior_limit_count} 次辨识度基座；C 只按冻结交叉每天补一笔。
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
                <td className="px-3 py-2 align-top font-medium">C · 补位</td>
                <td className="px-3 py-2 align-top">资金/回撤/早期概念扩散交叉</td>
                <td className="px-3 py-2 align-top">每天最多 1 笔</td>
                <td className="px-3 py-2 align-top tabular-nums">
                  {evidence.c_tier.win_count}/{evidence.c_tier.closed_count} · {formatPct(evidence.c_tier.win_rate_pct, 4)}
                </td>
              </tr>
              <tr className="border-t">
                <td className="px-3 py-2 align-top font-medium">B · 保留</td>
                <td className="px-3 py-2 align-top">未扩张或不可用</td>
                <td className="px-3 py-2 align-top">{core.b_first_board_minimum_time} 后首触/回封</td>
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
        <dl className="mt-3 grid grid-cols-2 border-y sm:grid-cols-4">
          <DatasetMetric label="单仓成交" value={`${evidence.single_position.closed_count} 笔`} />
          <DatasetMetric label="单仓复利" value={formatSignedPct(evidence.single_position.total_return_pct, 4)} positive />
          <DatasetMetric label="两仓成交" value={`${evidence.two_positions.closed_count} 笔`} />
          <DatasetMetric label="两仓复利" value={formatSignedPct(evidence.two_positions.total_return_pct, 4)} positive />
        </dl>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 text-xs sm:grid-cols-4">
          <Definition label="最大回撤" value={formatSignedPct(evidence.max_drawdown_pct, 4)} />
          <Definition label="硬亏率" value={formatPct(evidence.hard_loss_rate_pct, 4)} />
          <Definition label="起始" value={evidence.date_start} mono />
          <Definition label="截止" value={evidence.date_end} mono />
        </dl>
        <p className="mt-3 border-l-2 border-amber-500 px-3 text-xs leading-5 text-muted-foreground">
          C 的早期概念成员含历史幸存者代理，冻结结果还不是实盘等价证明。自然前向当前闭合 {forward.closed_count} 笔，
          {forward.win_count} 胜，胜率 {formatNullablePct(forward.win_rate_pct)}；至少积累
          {forward.minimum_trade_days} 个新交易日和 {forward.minimum_closed_count} 笔闭合交易后再验收。
        </p>
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
            <dt className="shrink-0 font-medium text-foreground">正式 A+B+C 买入</dt>
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

function formatNullablePct(value: number | null) {
  return value === null ? "待产生样本" : formatPct(value, 2);
}
