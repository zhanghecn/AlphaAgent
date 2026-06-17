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
    version: "0.1.8",
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
      low_suction_buildup: "低吸蓄势不足",
      ma_convergence_too_wide_without_low_suction: "均线发散且缺少低吸蓄势",
      distribution_risk: "高位派发风险",
      risk_score: "风险分不足",
      liquidity_score: "流动性不足",
    },
    evidence_labels: {
      dragon_state: "龙回头状态",
      support_type: "承接类型",
      low_suction_days: "低吸蓄势天数",
      ma_convergence_pct: "均线收敛",
      low_suction_buildup_score: "低吸蓄势分",
      ma5_distance_pct: "MA5距离",
      ma10_distance_pct: "MA10距离",
      volume_ratio_5d_20d: "量能比",
      risk_score: "风险分",
      liquidity_score: "流动性",
    },
    primary_metric_keys: ["dragon_state", "low_suction_days", "ma_convergence_pct"],
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
            <TableHead>为什么这个分数</TableHead>
            {canTrace && <TableHead className="text-right">组合追踪</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const explanation = scoreExplanation(row, strategy);
            const action = signalRowLabel(row);
            const executable = signalRowExecutable(row);
            return (
              <TableRow key={`${title}-${row.trade_date}`}>
                <TableCell className="tabular-nums">{row.trade_date}</TableCell>
                <TableCell className={executable ? "text-rise" : "text-muted-foreground"}>
                  {action}
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
                <TableCell className="max-w-80 text-muted-foreground" title={scoreExplanationTooltip(row, strategy)}>
                  {explanation}
                </TableCell>
                {canTrace && (
                  <TableCell className="text-right">
                    {executable ? (
                      <Button size="sm" variant="outline" onClick={() => onTraceSignalDate?.(row.trade_date)}>
                        追踪
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">--</span>
                    )}
                  </TableCell>
                )}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function signalRowLabel(row: SymbolSignalHistoryRow) {
  if (row.signal_label) return row.signal_label;
  if (row.action) return row.action.toUpperCase();
  if (row.executable_entry_signal != null) return row.executable_entry_signal ? "BUY" : "WATCH";
  return row.entry_signal && !row.failed_rules?.length ? "BUY" : "WATCH";
}

function signalRowExecutable(row: SymbolSignalHistoryRow) {
  if (row.executable_entry_signal != null) return row.executable_entry_signal;
  if (row.action) return row.action.toUpperCase() === "BUY";
  return row.entry_signal && !row.failed_rules?.length;
}

function AuditCell({ label, value, valueClass }: { label: string; value?: string | number | null; valueClass?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 font-medium tabular-nums", valueClass)}>{value ?? "--"}</div>
    </div>
  );
}

function formatRatio(value?: string | number | null) {
  const number = numericEvidence(value);
  return number == null ? "--" : `${number.toFixed(2)}x`;
}

function priceClass(value?: number | null) {
  return value == null ? undefined : value > 0 ? "text-rise" : value < 0 ? "text-fall" : undefined;
}

function metricDefinitions(strategy?: QuantStrategyOption) {
  const keys = strategy?.primary_metric_keys?.length ? strategy.primary_metric_keys : ["ma5_distance_pct"];
  return keys.slice(0, 3).map((key) => ({
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
  if (typeof raw === "string" && raw) return raw;
  return typeof raw === "number" ? raw : null;
}

function metricLabel(key: string) {
  const labels: Record<string, string> = {
    dragon_state: "龙回头状态",
    support_type: "承接类型",
    low_suction_days: "低吸天数",
    support_hold_days: "支撑天数",
    ma_convergence_pct: "均线收敛",
    low_suction_buildup_score: "蓄势分",
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
  if (key === "dragon_state") return dragonStateLabel;
  if (key === "support_type") return supportTypeLabel;
  if (key.endsWith("_score")) return formatScoreMetric;
  if (key.includes("ratio")) return formatRatio;
  if (key.includes("days") || key.includes("count")) return formatNullableNumber;
  return formatPercentMetric;
}

function metricClassName(key: string) {
  if (key === "dragon_state") return dragonStateClass;
  if (key === "support_type") return () => undefined;
  if (key.endsWith("_score")) return scoreClass;
  if (key.includes("ratio")) return ratioClass;
  if (key.includes("days") || key.includes("count")) return () => undefined;
  return percentClass;
}

function formatPercentMetric(value?: string | number | null) {
  return formatPct(numericEvidence(value));
}

function percentClass(value?: string | number | null) {
  return priceClass(numericEvidence(value));
}

function formatNullableNumber(value?: string | number | null) {
  const number = numericEvidence(value);
  return number == null ? "--" : number.toFixed(0);
}

function ratioClass(value?: string | number | null) {
  const number = numericEvidence(value);
  return number == null ? undefined : number >= 1 ? "text-rise" : "text-fall";
}

function scoreExplanation(row: SymbolSignalHistoryRow, strategy?: QuantStrategyOption) {
  const evidence = row.evidence ?? {};
  const notes = evidenceArray(evidence.score_notes);
  const contributions = topScoreContributions(evidence.score_breakdown, 3);
  const parts: string[] = [];
  const state = typeof evidence.dragon_state === "string" ? evidence.dragon_state : null;
  const lowSuctionDays = numericEvidence(evidence.low_suction_days);
  const convergence = numericEvidence(evidence.ma_convergence_pct);
  const lowSuctionScore = numericEvidence(evidence.low_suction_buildup_score);
  if (state) parts.push(`状态 ${dragonStateLabel(state)}`);
  if (lowSuctionDays != null) parts.push(`低吸蓄势 ${lowSuctionDays.toFixed(0)} 天`);
  if (convergence != null) parts.push(`均线收敛 ${formatPct(convergence)}`);
  if (lowSuctionScore != null) parts.push(`低吸蓄势分 ${lowSuctionScore.toFixed(1)}`);
  if (parts.length && contributions.length) return `${parts.join("；")}；来源 ${contributions.join("、")}`;
  if (parts.length) return parts.join("；");
  if (contributions.length) return `主要来源 ${contributions.join("、")}`;
  if (notes.length) return notes.slice(0, 4).join("；");

  return failedRulesLabel(row.failed_rules, strategy?.failed_rule_labels);
}

function scoreExplanationTooltip(row: SymbolSignalHistoryRow, strategy?: QuantStrategyOption) {
  const evidence = row.evidence ?? {};
  const notes = evidenceArray(evidence.score_notes).map(readableScoreNote);
  const breakdown = Array.isArray(evidence.score_breakdown)
    ? evidence.score_breakdown
        .map((item) => {
          if (!item || typeof item !== "object") return "";
          const raw = item as Record<string, unknown>;
          const name = String(raw.name ?? "");
          const score = numericEvidence(raw.score);
          const weight = numericEvidence(raw.weight);
          const contribution = numericEvidence(raw.contribution);
          if (!name) return "";
          const scoreText = score == null ? "--" : score.toFixed(1);
          const weightText = weight == null ? "--" : `${(weight * 100).toFixed(0)}%`;
          const contributionText = contribution == null ? "--" : contribution.toFixed(2);
          return `${name}: ${scoreText} * ${weightText} = ${contributionText}`;
        })
        .filter(Boolean)
    : [];
  const failed = failedRulesLabel(row.failed_rules, strategy?.failed_rule_labels);
  return [...notes, ...breakdown, `失败规则: ${failed}`].filter(Boolean).join("\n");
}

function evidenceArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function numericEvidence(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatScoreMetric(value?: string | number | null) {
  const number = numericEvidence(value);
  return number == null ? "--" : number.toFixed(1);
}

function dragonStateLabel(value?: string | number | null) {
  const state = String(value ?? "");
  const labels: Record<string, string> = {
    TAIL_BUY_READY: "龙回头买点",
    LOW_SUCTION_BUILDUP: "低吸蓄势",
    SUPPORT_ACCEPTED: "均线承接",
    PULLBACK_OBSERVE: "回踩观察",
    STRONG_LEG_CONFIRMED: "强势确认",
    DISTRIBUTION_RISK: "派发风险",
    INVALIDATED: "破位失效",
  };
  return (labels[state] ?? state) || "--";
}

function readableScoreNote(note: string) {
  if (note.startsWith("状态 ")) return `状态 ${dragonStateLabel(note.slice(3))}`;
  if (note.startsWith("承接 ")) return `承接 ${supportTypeLabel(note.slice(3))}`;
  return note;
}

function supportTypeLabel(value?: string | number | null) {
  const support = String(value ?? "");
  const labels: Record<string, string> = {
    ma5_reclaim: "MA5承接",
    ma10_support: "MA10承接",
    ma20_support: "MA20承接",
    none: "未承接",
  };
  return (labels[support] ?? support) || "--";
}

function dragonStateClass(value?: string | number | null) {
  const state = String(value ?? "");
  if (state === "TAIL_BUY_READY" || state === "LOW_SUCTION_BUILDUP") return "text-rise";
  if (state === "DISTRIBUTION_RISK" || state === "INVALIDATED") return "text-fall";
  return undefined;
}

function scoreClass(value?: string | number | null) {
  const number = numericEvidence(value);
  if (number == null) return undefined;
  return number >= 85 ? "text-rise" : number < 60 ? "text-fall" : undefined;
}

function topScoreContributions(value: unknown, limit: number): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const row = item as Record<string, unknown>;
      const name = String(row.name ?? "");
      const contribution = numericEvidence(row.contribution);
      if (!name || contribution == null || contribution <= 0) return null;
      return { name, contribution };
    })
    .filter((item): item is { name: string; contribution: number } => Boolean(item))
    .sort((left, right) => right.contribution - left.contribution)
    .slice(0, limit)
    .map((item) => `${item.name}+${item.contribution.toFixed(2)}`);
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
    ma_convergence_too_wide_without_low_suction: "均线发散且缺少低吸蓄势",
    overheat: "短期过热",
  };
  return rules.map((rule) => labels?.[rule] ?? fallbackLabels[rule] ?? rule).join("、");
}
