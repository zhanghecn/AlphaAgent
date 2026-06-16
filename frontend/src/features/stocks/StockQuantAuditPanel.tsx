import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import {
  fetchSymbolStrategyComparison,
  type QuantStrategyOption,
  type SymbolSignalHistoryRow,
  type SymbolStrategyComparisonItem,
} from "@/api/quant";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn, formatPct } from "@/lib/utils";

export function StockQuantAuditPanel({
  vtSymbol,
  start,
  end,
  onTraceSignalDate,
}: {
  vtSymbol: string;
  start: string;
  end?: string;
  onTraceSignalDate?: (tradeDate: string) => void;
}) {
  const comparisonQuery = useQuery({
    queryKey: ["stockQuantStrategyComparison", vtSymbol, start, end],
    queryFn: () => fetchSymbolStrategyComparison(vtSymbol, { start, end, limit: 80 }),
    enabled: Boolean(vtSymbol),
    staleTime: 30_000,
  });
  const comparison = comparisonQuery.data;
  const items = comparison?.items?.length ? comparison.items : FALLBACK_STRATEGIES.map(emptyComparisonItem);
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>("");
  const activeStrategyId = selectedStrategyId || items[0]?.strategy_id || "";
  const selectedItem = items.find((item) => item.strategy_id === activeStrategyId) ?? items[0];
  const isFetching = comparisonQuery.isFetching;
  const isReady = comparison?.status === "ready";

  return (
    <section className="rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">量化信号复核</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            当前只复核主线龙回头回踩低吸，和量化页全局研究保持同一策略口径。
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => comparisonQuery.refetch()}
          disabled={isFetching}
        >
          <Search size={14} />
          复查
        </Button>
      </div>

      {comparisonQuery.isLoading ? (
        <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
          正在复核区间信号...
        </div>
      ) : null}

      {comparisonQuery.isError ? (
        <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
          量化信号复核接口暂时不可用，请稍后重试。
        </div>
      ) : null}

      {comparison && comparison.status !== "ready" ? (
        <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
          暂无可复核信号。可能是本地区间日线不足、财报/辅助因子未落库，或该策略没有形成有效评分。
        </div>
      ) : null}

      {isReady ? (
        <div className="mt-4 space-y-4">
          <div className="flex flex-wrap gap-2">
            {items.map((item) => {
              const active = activeStrategyId === item.strategy_id;
              return (
                <Button
                  key={item.strategy_id}
                  size="sm"
                  variant={active ? "default" : "outline"}
                  onClick={() => setSelectedStrategyId(item.strategy_id)}
                >
                  {item.strategy.name}
                </Button>
              );
            })}
          </div>

          {selectedItem && <StrategySummaryCard item={selectedItem} />}

          <div className="rounded-md border bg-muted/20 p-3 text-sm leading-6">
            <div className="font-medium">财报口径</div>
            <div className="mt-2 grid gap-3 md:grid-cols-6">
              <AuditCell label="本地财报" value={`${comparison.financial_coverage?.local_report_count ?? 0} 条`} />
              <AuditCell label="回测可用" value={`${comparison.financial_coverage?.usable_report_count ?? 0} 条`} />
              <AuditCell label="披露日晚于区间" value={`${comparison.financial_coverage?.future_publish_date_count ?? 0} 条`} />
              <AuditCell label="缺披露日" value={`${comparison.financial_coverage?.missing_publish_date_count ?? 0} 条`} />
              <AuditCell label="最新披露日" value={comparison.financial_coverage?.latest_publish_date ?? "--"} />
              <AuditCell label="最近可用报告" value={comparison.financial_coverage?.latest_usable_report_date ?? "--"} />
            </div>
            <div className="mt-2 text-muted-foreground">
              {comparison.financial_coverage?.policy ??
                "股票详情页看到的是现在可查的财报；回测评分只使用本地已落库且 publish_date <= 交易日 的财报。"}
            </div>
          </div>

          {selectedItem && (
            <StrategySignalSection
              item={selectedItem}
              startDate={comparison.start_date}
              endDate={comparison.end_date}
              onTraceSignalDate={onTraceSignalDate}
            />
          )}
        </div>
      ) : null}
    </section>
  );
}

function StrategySignalSection({
  item,
  startDate,
  endDate,
  onTraceSignalDate,
}: {
  item: SymbolStrategyComparisonItem;
  startDate?: string | null;
  endDate?: string | null;
  onTraceSignalDate?: (tradeDate: string) => void;
}) {
  if (item.status !== "ready") {
    return null;
  }
  const strategy = item.strategy;
  const recent = item.recent ?? [];
  const entries = item.entry_signals ?? [];
  const bestFit = item.best_entry_fit;
  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="grid gap-3 text-sm md:grid-cols-4">
        <AuditCell label="策略" value={strategy.name} />
        <AuditCell label="版本" value={item.strategy_version} />
        <AuditCell label="触发买入" value={`${item.entry_signal_count} 次`} valueClass={item.entry_signal_count > 0 ? "text-rise" : undefined} />
        <AuditCell label="区间" value={`${startDate ?? "--"} / ${endDate ?? "--"}`} />
      </div>
      {bestFit && <BestFitRow row={bestFit} strategy={strategy} />}
      {entries.length > 0 ? (
        <SignalTable title="历史 BUY 信号" rows={entries.slice(0, 20)} strategy={strategy} onTraceSignalDate={onTraceSignalDate} />
      ) : (
        <EmptyState message="没有 BUY 信号" description="当前策略没有形成硬入场。请看最近评分和失败规则判断是分数、位置、风险还是流动性不足。" />
      )}
      <SignalTable title="最近评分" rows={recent.slice(0, 20)} strategy={strategy} onTraceSignalDate={onTraceSignalDate} />
    </div>
  );
}

function StrategySummaryCard({
  item,
}: {
  item: SymbolStrategyComparisonItem;
}) {
  const strategy = item.strategy;
  const bestFit = item.best_entry_fit;
  return (
    <div className="rounded-md border p-3 text-sm">
      <div className="font-medium">{strategy.name}</div>
      <div className="mt-1 text-muted-foreground">{strategy.description}</div>
      <div className="mt-3 grid grid-cols-2 gap-3">
        <AuditCell label="评分日" value={item.status === "ready" ? `${item.scored_date_count} 日` : "--"} />
        <AuditCell label="BUY次数" value={item.status === "ready" ? `${item.entry_signal_count} 次` : "--"} valueClass={item.entry_signal_count > 0 ? "text-rise" : undefined} />
        <AuditCell label="WATCH天数" value={item.status === "ready" ? `${item.watch_count} 日` : "--"} />
        <AuditCell label="最接近日" value={bestFit?.trade_date ?? "--"} />
        <AuditCell label="最高匹配分" value={bestFit?.total_score == null ? "--" : bestFit.total_score.toFixed(1)} />
        <AuditCell label="失败规则" value={bestFit ? failedRulesLabel(bestFit.failed_rules, strategy.failed_rule_labels) : "--"} />
      </div>
    </div>
  );
}

function BestFitRow({ row, strategy }: { row: SymbolSignalHistoryRow; strategy?: QuantStrategyOption }) {
  return (
    <div className="rounded-md border p-3 text-sm">
      <div className="font-medium">最接近买点</div>
      <div className="mt-2 grid gap-3 md:grid-cols-5">
        <AuditCell label="日期" value={row.trade_date} />
        <AuditCell label="总分" value={row.total_score.toFixed(1)} />
        {strategyMetricCells(row, strategy).map((metric) => (
          <AuditCell key={metric.key} label={metric.label} value={metric.value} />
        ))}
        <AuditCell label="流动性" value={row.liquidity_score.toFixed(1)} />
        <AuditCell label="失败规则" value={failedRulesLabel(row.failed_rules, strategy?.failed_rule_labels)} />
      </div>
    </div>
  );
}

const FALLBACK_STRATEGIES: QuantStrategyOption[] = [
  {
    id: "mainline_dragon_pullback",
    version: "0.1.1",
    name: "主线龙回头回踩低吸",
    description: "使用日线可见数据识别主线强势股第一波启动后的缩量回踩、均线承接和弱转强机会。",
    default_min_entry_score: 76,
    entry_action_label: "买入",
    watch_action_label: "观察",
    failed_rule_labels: {
      total_score: "分数不足",
      strong_leg: "第一波强度不足",
      pullback_structure: "回踩结构不足",
      support_acceptance: "均线承接不足",
      reclaim_confirmation: "弱转强确认不足",
      distribution_risk: "高位派发风险",
      risk_score: "风险分不足",
      liquidity_score: "流动性不足",
    },
    evidence_labels: {
      dragon_state: "龙回头状态",
      support_type: "承接类型",
      ma5_distance_pct: "MA5距离",
      ma10_distance_pct: "MA10距离",
      volume_ratio_5d_20d: "量能比",
      risk_score: "风险分",
      liquidity_score: "流动性",
    },
    primary_metric_keys: ["dragon_state", "support_type", "ma5_distance_pct"],
  },
];

function emptyComparisonItem(strategy: QuantStrategyOption): SymbolStrategyComparisonItem {
  return {
    strategy,
    status: "empty",
    strategy_id: strategy.id,
    strategy_version: strategy.version,
    scored_date_count: 0,
    entry_signal_count: 0,
    watch_count: 0,
    best_total_score: null,
    best_entry_fit: null,
    entry_signals: [],
    recent: [],
    rule: {},
  };
}

function SignalTable({
  title,
  rows,
  strategy,
  onTraceSignalDate,
}: {
  title: string;
  rows: SymbolSignalHistoryRow[];
  strategy?: QuantStrategyOption;
  onTraceSignalDate?: (tradeDate: string) => void;
}) {
  if (rows.length === 0) return null;
  const metrics = metricDefinitions(strategy);
  const canTrace = Boolean(onTraceSignalDate);
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>日期</TableHead>
            <TableHead>动作</TableHead>
            <TableHead className="text-right">总分</TableHead>
            {metrics.map((metric) => (
              <TableHead key={metric.key} className="text-right">{metric.label}</TableHead>
            ))}
            <TableHead className="text-right">流动性</TableHead>
            <TableHead>失败规则</TableHead>
            {canTrace && <TableHead className="text-right">组合追踪</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={`${title}-${row.trade_date}`}>
              <TableCell className="tabular-nums">{row.trade_date}</TableCell>
              <TableCell className={row.entry_signal ? "text-rise" : "text-muted-foreground"}>
                {row.entry_signal ? "BUY" : "WATCH"}
              </TableCell>
              <TableCell className="text-right tabular-nums">{row.total_score.toFixed(1)}</TableCell>
              {metrics.map((metric) => {
                const value = metricValue(row, metric.key);
                return (
                  <TableCell key={metric.key} className={cn("text-right tabular-nums", metric.className(value))}>
                    {metric.format(value)}
                  </TableCell>
                );
              })}
              <TableCell className="text-right tabular-nums">{row.liquidity_score.toFixed(1)}</TableCell>
              <TableCell className="text-muted-foreground">{failedRulesLabel(row.failed_rules, strategy?.failed_rule_labels)}</TableCell>
              {canTrace && (
                <TableCell className="text-right">
                  {row.entry_signal ? (
                    <Button size="sm" variant="outline" onClick={() => onTraceSignalDate?.(row.trade_date)}>
                      追踪
                    </Button>
                  ) : (
                    <span className="text-xs text-muted-foreground">--</span>
                  )}
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function AuditCell({ label, value, valueClass }: { label: string; value?: string | number | null; valueClass?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 font-medium tabular-nums", valueClass)}>{value ?? "--"}</div>
    </div>
  );
}

function formatNullablePct(value?: number | null) {
  return value == null ? "--" : formatPct(value);
}

function formatRatio(value?: number | null) {
  return value == null ? "--" : `${value.toFixed(2)}x`;
}

function priceClass(value?: number | null) {
  return value == null ? undefined : value > 0 ? "text-rise" : value < 0 ? "text-fall" : undefined;
}

function metricDefinitions(strategy?: QuantStrategyOption) {
  const keys = strategy?.primary_metric_keys?.length ? strategy.primary_metric_keys : ["ma5_distance_pct"];
  return keys.slice(0, 2).map((key) => ({
    key,
    label: strategy?.evidence_labels?.[key] ?? metricLabel(key),
    format: metricFormatter(key),
    className: metricClassName(key),
  }));
}

function strategyMetricCells(row: SymbolSignalHistoryRow, strategy?: QuantStrategyOption) {
  return metricDefinitions(strategy).map((metric) => {
    const value = metricValue(row, metric.key);
    return {
      key: metric.key,
      label: metric.label,
      value: metric.format(value),
    };
  });
}

function metricValue(row: SymbolSignalHistoryRow, key: string) {
  if (key === "ma5_distance_pct") return row.ma5_distance_pct;
  if (key === "trend_quality_score") return row.trend_quality_score;
  const raw = row.evidence?.[key];
  return typeof raw === "number" ? raw : null;
}

function metricLabel(key: string) {
  const labels: Record<string, string> = {
    ma5_distance_pct: "MA5距离",
    ma20_distance_pct: "MA20距离",
    close_to_prior_high_pct: "距60日高点",
    volume_ratio_5d_20d: "量能比",
    days_since_limit_up: "距涨停天数",
    limit_up_count_20d: "20日涨停数",
    return_5d: "5日涨跌",
    return_20d: "20日涨跌",
    return_60d: "60日涨跌",
    trend_quality_score: "趋势质量",
  };
  return labels[key] ?? key;
}

function metricFormatter(key: string) {
  if (key.includes("ratio")) return formatRatio;
  if (key.includes("days") || key.includes("count")) return formatNullableNumber;
  return formatNullablePct;
}

function metricClassName(key: string) {
  if (key.includes("ratio")) return ratioClass;
  if (key.includes("days") || key.includes("count")) return () => undefined;
  return priceClass;
}

function formatNullableNumber(value?: number | null) {
  return value == null ? "--" : value.toFixed(0);
}

function ratioClass(value?: number | null) {
  return value == null ? undefined : value >= 1 ? "text-rise" : "text-fall";
}

function failedRulesLabel(rules?: string[], labels?: Record<string, string>) {
  if (!rules?.length) return "通过";
  const fallbackLabels: Record<string, string> = {
    total_score: "分数不足",
    ma5_distance: "不在MA5低吸区",
    risk_score: "风险分不足",
    liquidity_score: "流动性不足",
    breakout_distance: "未接近60日高点",
    volume_confirmation: "量能确认不足",
    trend_quality: "趋势质量不足",
    limit_up_presence: "近20日无涨停",
    limit_up_recency: "涨停后时间不合适",
    pullback_position: "回踩位置不合适",
    ma20_support: "跌破MA20支撑",
    trend_return: "阶段强度不足",
    recent_acceleration: "短期加速不合适",
    ma_alignment: "均线多头不足",
    ma5_position: "偏离MA5不合适",
    ma20_position: "趋势位置不合适",
    volume_acceleration: "量能加速不合适",
    overheat: "短期过热",
  };
  return rules.map((rule) => labels?.[rule] ?? fallbackLabels[rule] ?? rule).join("、");
}
