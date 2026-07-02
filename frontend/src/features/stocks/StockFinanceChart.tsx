/**
 * StockFinanceChart — 一体化财务面板。
 *
 * 布局 (三区联动):
 * 1. Zone A — 核心指标卡片 (营业总收入/归母净利润/毛利率/ROE/EPS/经营现金流)
 * 2. Zone B — 统一趋势图 (点击任意表格行切换)
 * 3. Zone C — 统一Tab (核心指标 | 利润表 | 资产负债表 | 现金流量表)
 *
 * 数据来源:
 * - /research/stocks/{vt}/finance/quarterly → 季度关键指标
 * - /research/stocks/{vt}/finance/statements → 三大报表原始科目
 */
import { Fragment, useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import {
  fetchQuarterlyFinance,
  fetchFinancialStatement,
} from "@/api/finance";
import { CardSkeleton } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { formatAmount, formatPct, priceColorClass } from "@/lib/utils";
import { useChartColors } from "@/lib/chart-theme";
import type {
  FinancialStatementResponse,
  QuarterlyFinanceItem,
} from "@/types/finance";

// ── Props ──

interface StockFinanceChartProps {
  vtSymbol: string;
}

// ── AkShare English field codes ──

const AK = {
  operateIncome: "OPERATE_INCOME",
  operateIncomeYoy: "OPERATE_INCOME_QOQ",
  operateCost: "OPERATE_COST",
  totalOperateIncome: "TOTAL_OPERATE_INCOME",
  totalOperateIncomeYoy: "TOTAL_OPERATE_INCOME_QOQ",
  totalOperateCost: "TOTAL_OPERATE_COST",
  totalOperateCostYoy: "TOTAL_OPERATE_COST_QOQ",
  operateProfit: "OPERATE_PROFIT",
  operateProfitYoy: "OPERATE_PROFIT_QOQ",
  totalProfit: "TOTAL_PROFIT",
  totalProfitYoy: "TOTAL_PROFIT_QOQ",
  netprofit: "NETPROFIT",
  netprofitYoy: "NETPROFIT_QOQ",
  parentNetprofit: "PARENT_NETPROFIT",
  parentNetprofitYoy: "PARENT_NETPROFIT_QOQ",
  deductedNetprofit: "DEDUCT_PARENT_NETPROFIT",
  deductedNetprofitYoy: "DEDUCT_PARENT_NETPROFIT_QOQ",
  basicEps: "BASIC_EPS",
  dilutedEps: "DILUTED_EPS",
  saleExpense: "SALE_EXPENSE",
  manageExpense: "MANAGE_EXPENSE",
  financeExpense: "FINANCE_EXPENSE",
  researchExpense: "RESEARCH_EXPENSE",
  incomeTax: "INCOME_TAX",
  reportDate: "REPORT_DATE",
  reportDateName: "REPORT_DATE_NAME",
  netcashOperate: "NETCASH_OPERATE",
  netcashInvest: "NETCASH_INVEST",
  netcashFinance: "NETCASH_FINANCE",
  totalAssets: "TOTAL_ASSETS",
  totalLiab: "TOTAL_LIABILITIES",
  totalEquity: "TOTAL_PARENT_EQUITY",
} as const;

// ── Helpers ──

type RawRecord = Record<string, unknown>;

function rawNum(raw: RawRecord | undefined, key: string): number | null {
  if (!raw) return null;
  return toNum(raw[key]);
}

function toNum(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

/**
 * Normalize REPORT_DATE_NAME variants to consistent "x季报/中报/年报" suffix.
 * Quarterly API returns "2026一季度" → "2026一季报"
 * Statement API returns "2026一季报" → already correct
 */
function normalizeReportName(name: string): string {
  const map: Record<string, string> = {
    "一季度": "一季报", "二季度": "中报",
    "三季度": "三季报", "四季度": "年报",
    "一季报": "一季报", "中报": "中报",
    "三季报": "三季报", "年报": "年报",
  };
  for (const [suffix, mappedSuffix] of Object.entries(map)) {
    if (name.endsWith(suffix)) {
      return name.slice(0, -suffix.length) + mappedSuffix;
    }
  }
  return name;
}

/**
 * 报告期中文标签 — 统一为 "2026一季报" 格式。
 * 优先使用 API 返回的 REPORT_DATE_NAME，
 * 退化为日期推算（03→一季报, 06→中报, 09→三季报, 12→年报）。
 */
function reportPeriodLabel(
  dateStr: string,
  raw?: Record<string, unknown>,
): string {
  if (raw) {
    const name = raw[AK.reportDateName];
    if (typeof name === "string" && name.trim()) {
      return normalizeReportName(name.trim());
    }
  }
  const d = dateStr.slice(0, 10);
  const year = d.slice(0, 4);
  const month = d.slice(5, 7);
  const label =
    month === "03" ? "一季报"
    : month === "06" ? "中报"
    : month === "09" ? "三季报"
    : "年报";
  return `${year}${label}`;
}

/** Short label for chart X-axis: compact "25Q3" format */
function reportPeriodShort(dateStr: string): string {
  const d = dateStr.slice(0, 10);
  const year = d.slice(2, 4);
  const month = d.slice(5, 7);
  const label =
    month === "03" ? "Q1"
    : month === "06" ? "H1"
    : month === "09" ? "Q3"
    : "FY";
  return `${year}${label}`;
}

/**
 * 从报表 StatementItem 中提取中文报告期标签。
 * StatementItem 是 Record<string, string|number|null>，包含 REPORT_DATE_NAME。
 */
function statementPeriodLabel(item: Record<string, string | number | null>): string {
  const name = item[AK.reportDateName];
  if (typeof name === "string" && name.trim()) return normalizeReportName(name.trim());
  const dateStr = String(item[AK.reportDate] ?? "");
  return reportPeriodLabel(dateStr);
}

/** Smart number formatter: 亿/万 for amounts, fixed for percentages/ratios */
function fmtValue(v: number | null | undefined, fmt: "amount" | "pct" | "ratio"): string {
  if (v == null) return "--";
  if (fmt === "amount") return formatAmount(v);
  if (fmt === "pct") return formatPct(v);
  return v.toFixed(2);
}

// ── Metrics table definition ──

type MetricDef = {
  key: string;
  label: string;
  fmt: "amount" | "pct" | "ratio";
  /** Extract value from a QuarterlyFinanceItem + its raw data */
  extract: (item: QuarterlyFinanceItem) => number | null | undefined;
  /** Whether to apply rise/fall color */
  colorize?: boolean;
};

interface MetricGroup {
  title: string;
  metrics: MetricDef[];
}

const METRIC_GROUPS: MetricGroup[] = [
  {
    title: "每股指标",
    metrics: [
      {
        key: "eps",
        label: "基本每股收益(元)",
        fmt: "ratio",
        extract: (item) => item.eps ?? rawNum(item.raw, AK.basicEps),
        colorize: true,
      },
      {
        key: "diluted_eps",
        label: "稀释每股收益(元)",
        fmt: "ratio",
        extract: (item) => rawNum(item.raw, AK.dilutedEps),
        colorize: true,
      },
    ],
  },
  {
    title: "盈利能力",
    metrics: [
      {
        key: "revenue",
        label: "营业总收入",
        fmt: "amount",
        extract: (item) =>
          item.revenue ?? rawNum(item.raw, AK.operateIncome) ?? rawNum(item.raw, AK.totalOperateIncome),
      },
      {
        key: "revenue_yoy",
        label: "同比增长(%)",
        fmt: "pct",
        extract: (item) =>
          item.revenue_yoy ?? rawNum(item.raw, AK.operateIncomeYoy) ?? rawNum(item.raw, AK.totalOperateIncomeYoy),
        colorize: true,
      },
      {
        key: "operate_cost",
        label: "营业成本",
        fmt: "amount",
        extract: (item) => rawNum(item.raw, AK.operateCost),
      },
      {
        key: "total_operate_cost",
        label: "营业总成本",
        fmt: "amount",
        extract: (item) => rawNum(item.raw, AK.totalOperateCost),
      },
      {
        key: "operate_profit",
        label: "营业利润",
        fmt: "amount",
        extract: (item) => rawNum(item.raw, AK.operateProfit),
        colorize: true,
      },
      {
        key: "operate_profit_yoy",
        label: "同比增长(%)",
        fmt: "pct",
        extract: (item) => rawNum(item.raw, AK.operateProfitYoy),
        colorize: true,
      },
      {
        key: "total_profit",
        label: "利润总额",
        fmt: "amount",
        extract: (item) => rawNum(item.raw, AK.totalProfit),
        colorize: true,
      },
      {
        key: "total_profit_yoy",
        label: "同比增长(%)",
        fmt: "pct",
        extract: (item) => rawNum(item.raw, AK.totalProfitYoy),
        colorize: true,
      },
      {
        key: "net_profit",
        label: "净利润",
        fmt: "amount",
        extract: (item) => item.net_profit ?? rawNum(item.raw, AK.netprofit),
        colorize: true,
      },
      {
        key: "net_profit_yoy",
        label: "同比增长(%)",
        fmt: "pct",
        extract: (item) => item.net_profit_yoy ?? rawNum(item.raw, AK.netprofitYoy),
        colorize: true,
      },
      {
        key: "parent_net_profit",
        label: "归母净利润",
        fmt: "amount",
        extract: (item) => rawNum(item.raw, AK.parentNetprofit),
        colorize: true,
      },
      {
        key: "parent_net_profit_yoy",
        label: "同比增长(%)",
        fmt: "pct",
        extract: (item) => rawNum(item.raw, AK.parentNetprofitYoy),
        colorize: true,
      },
      {
        key: "deducted_net_profit",
        label: "扣非净利润",
        fmt: "amount",
        extract: (item) => item.deducted_net_profit ?? rawNum(item.raw, AK.deductedNetprofit),
        colorize: true,
      },
      {
        key: "deducted_net_profit_yoy",
        label: "同比增长(%)",
        fmt: "pct",
        extract: (item) => rawNum(item.raw, AK.deductedNetprofitYoy),
        colorize: true,
      },
      {
        key: "gross_margin",
        label: "毛利率(%)",
        fmt: "pct",
        extract: (item) => {
          if (item.gross_margin != null) return item.gross_margin;
          const income = rawNum(item.raw, AK.operateIncome);
          const cost = rawNum(item.raw, AK.operateCost);
          if (income && cost != null) return ((income - cost) / income) * 100;
          return null;
        },
        colorize: true,
      },
      {
        key: "net_margin",
        label: "净利率(%)",
        fmt: "pct",
        extract: (item) => {
          if (item.net_margin != null) return item.net_margin;
          const np = rawNum(item.raw, AK.netprofit);
          const rev = rawNum(item.raw, AK.totalOperateIncome) ?? rawNum(item.raw, AK.operateIncome);
          if (np != null && rev) return (np / rev) * 100;
          return null;
        },
        colorize: true,
      },
    ],
  },
  {
    title: "期间费用",
    metrics: [
      {
        key: "sale_expense",
        label: "销售费用",
        fmt: "amount",
        extract: (item) => rawNum(item.raw, AK.saleExpense),
      },
      {
        key: "manage_expense",
        label: "管理费用",
        fmt: "amount",
        extract: (item) => rawNum(item.raw, AK.manageExpense),
      },
      {
        key: "finance_expense",
        label: "财务费用",
        fmt: "amount",
        extract: (item) => rawNum(item.raw, AK.financeExpense),
        colorize: true,
      },
      {
        key: "research_expense",
        label: "研发费用",
        fmt: "amount",
        extract: (item) => rawNum(item.raw, AK.researchExpense),
      },
    ],
  },
  {
    title: "盈利质量",
    metrics: [
      {
        key: "roe",
        label: "ROE(%)",
        fmt: "pct",
        extract: (item) => item.roe,
        colorize: true,
      },
      {
        key: "operating_cash_flow",
        label: "经营现金流净额",
        fmt: "amount",
        extract: (item) => item.operating_cash_flow ?? rawNum(item.raw, AK.netcashOperate),
        colorize: true,
      },
    ],
  },
  {
    title: "偿债能力",
    metrics: [
      {
        key: "debt_asset_ratio",
        label: "资产负债率(%)",
        fmt: "pct",
        extract: (item) => item.debt_asset_ratio,
      },
      {
        key: "total_assets",
        label: "总资产",
        fmt: "amount",
        extract: (item) => rawNum(item.raw, AK.totalAssets),
      },
    ],
  },
];

// ── Period columns extraction ──

interface PeriodCol {
  key: string;       // ISO date for React key
  label: string;     // e.g. "2025三季报" (full Chinese)
  short: string;     // e.g. "25Q3" (compact for chart)
  fullDate: string;  // e.g. "2024-09-30"
}

function getPeriodColumns(items: QuarterlyFinanceItem[], maxCols = 8): PeriodCol[] {
  return items.slice(0, maxCols).map((item) => {
    const d = item.report_date.slice(0, 10);
    return {
      key: d,
      label: reportPeriodLabel(item.report_date, item.raw as Record<string, unknown> | undefined),
      short: reportPeriodShort(item.report_date),
      fullDate: d,
    };
  });
}

// ── Metric chart helpers ──

/** All chartable metrics as a flat map for O(1) lookup */
const CHART_METRICS = new Map(
  METRIC_GROUPS.flatMap((g) => g.metrics.map((m) => [m.key, m])),
);

/** Find the group title for a metric key */
function metricGroupLabel(key: string): string {
  for (const g of METRIC_GROUPS) {
    if (g.metrics.some((m) => m.key === key)) return g.title;
  }
  return "";
}

// ── Zone A: Summary Metric Cards ──

interface SummaryCardDef {
  key: string;
  label: string;
  fmt: "amount" | "pct" | "ratio";
  extract: (item: QuarterlyFinanceItem) => number | null | undefined;
  yoyExtract?: (item: QuarterlyFinanceItem) => number | null;
  colorize?: boolean;
}

const SUMMARY_CARDS: SummaryCardDef[] = [
  {
    key: "revenue",
    label: "营业总收入",
    fmt: "amount",
    extract: (item) =>
      item.revenue ?? rawNum(item.raw, AK.operateIncome) ?? rawNum(item.raw, AK.totalOperateIncome),
    yoyExtract: (item) =>
      item.revenue_yoy ?? rawNum(item.raw, AK.operateIncomeYoy) ?? rawNum(item.raw, AK.totalOperateIncomeYoy),
  },
  {
    key: "parent_net_profit",
    label: "归母净利润",
    fmt: "amount",
    extract: (item) => rawNum(item.raw, AK.parentNetprofit),
    yoyExtract: (item) => rawNum(item.raw, AK.parentNetprofitYoy),
    colorize: true,
  },
  {
    key: "gross_margin",
    label: "毛利率",
    fmt: "pct",
    extract: (item) => {
      if (item.gross_margin != null) return item.gross_margin;
      const income = rawNum(item.raw, AK.operateIncome);
      const cost = rawNum(item.raw, AK.operateCost);
      if (income && cost != null) return ((income - cost) / income) * 100;
      return null;
    },
    colorize: true,
  },
  {
    key: "roe",
    label: "ROE",
    fmt: "pct",
    extract: (item) => item.roe,
    colorize: true,
  },
  {
    key: "eps",
    label: "每股收益",
    fmt: "ratio",
    extract: (item) => item.eps ?? rawNum(item.raw, AK.basicEps),
    colorize: true,
  },
  {
    key: "operating_cash_flow",
    label: "经营现金流",
    fmt: "amount",
    extract: (item) => item.operating_cash_flow ?? rawNum(item.raw, AK.netcashOperate),
    colorize: true,
  },
];

function SummaryCard({ def, item, selected, onClick }: {
  def: SummaryCardDef; item: QuarterlyFinanceItem; selected: boolean; onClick: () => void;
}) {
  const value = def.extract(item);
  const yoy = def.yoyExtract?.(item);

  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg border p-3 space-y-1 text-left transition-colors cursor-pointer ${
        selected
          ? "bg-primary/10 border-primary/40 ring-1 ring-primary/20"
          : "bg-card hover:bg-accent/30"
      }`}
    >
      <p className="text-xs text-muted-foreground truncate">{def.label}</p>
      <p className={`text-lg font-bold tabular-nums ${def.colorize ? priceColorClass(value) : "text-foreground"}`}>
        {fmtValue(value, def.fmt)}
      </p>
      {yoy != null && (
        <div className="flex items-center gap-1">
          <span className={`text-xs font-medium tabular-nums ${priceColorClass(yoy)}`}>
            {formatPct(yoy)}
          </span>
          <span className="text-xs text-muted-foreground">同比</span>
        </div>
      )}
    </button>
  );
}

function SummaryCardGrid({ item, selectedKey, onSelect }: {
  item: QuarterlyFinanceItem; selectedKey: string; onSelect: (key: string) => void;
}) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {SUMMARY_CARDS.map((def) => (
        <SummaryCard
          key={def.key}
          def={def}
          item={item}
          selected={def.key === selectedKey}
          onClick={() => onSelect(def.key)}
        />
      ))}
    </div>
  );
}

// ── Zone B: Unified Trend Chart ──

type ChartSource =
  | { type: "metric"; metric: MetricDef; items: QuarterlyFinanceItem[]; periods: PeriodCol[] }
  | { type: "statement"; fieldKey: string; items: Record<string, string | number | null>[]; dates: string[]; labels: string[] };

function UnifiedTrendChart({ source }: { source: ChartSource | null }) {
  const palette = useChartColors();
  const option = useMemo(() => {
    if (!source) return null;

    // Build data arrays
    let categories: string[] = [];
    let values: (number | null)[] = [];
    let fmt: "amount" | "pct" | "ratio" = "amount";
    let doColorize = false;

    if (source.type === "metric") {
      const visible = source.items.slice(0, source.periods.length);
      const reversed = [...visible].reverse();
      categories = reversed.map((_, i) => source.periods[visible.length - 1 - i]?.label ?? "");
      values = reversed.map((item) => source.metric.extract(item) ?? null);
      fmt = source.metric.fmt;
      doColorize = source.metric.colorize ?? false;
    } else {
      const reversed = [...source.items].reverse();
      const reversedLabels = [...source.labels].reverse();
      categories = reversedLabels;
      values = reversed.map((item) => toNum(item[source.fieldKey]));
      doColorize = true;
    }

    if (!values.some((v) => v != null)) return null;

    const isPct = fmt === "pct";

    // Color palette: positive = warm red (#E8564A), negative = teal (#2EAA6E)
    const POS_COLOR = "#E8564A";
    const NEG_COLOR = "#2EAA6E";
    const NEUTRAL_COLOR = "#6B8A9E";
    const PRIMARY_COLOR = palette.brand;

    // Build per-bar color array
    const barColors = values.map((v) => {
      if (!doColorize && !isPct) return PRIMARY_COLOR;
      if (v == null) return NEUTRAL_COLOR;
      if (v > 0) return POS_COLOR;
      if (v < 0) return NEG_COLOR;
      return NEUTRAL_COLOR;
    });

    // Gradient decoration: top bars get a subtle gradient for polish
    const seriesData = values.map((v, i) => ({
      value: v ?? "-",
      itemStyle: {
        color: barColors[i],
        borderRadius: [3, 3, 0, 0],
      },
    }));

    return {
      grid: { top: 36, right: 20, bottom: 24, left: 68, containLabel: false },
      tooltip: {
        trigger: "axis" as const,
        backgroundColor: palette.tooltipBg,
        borderColor: palette.tooltipBorder,
        borderWidth: 1,
        borderRadius: 6,
        padding: [8, 12],
        textStyle: { color: palette.tooltipText, fontSize: 12 },
        formatter: (params: Array<{ name: string; value: number | string }>) => {
          const p = params[0];
          const val = typeof p.value === "number" ? p.value : null;
          return `<b>${p.name}</b><br/><span style="font-weight:600">${fmtValue(val, fmt)}</span>`;
        },
      },
      xAxis: {
        type: "category" as const,
        data: categories,
        axisLine: { lineStyle: { color: palette.axis } },
        axisTick: { show: false },
        axisLabel: {
          color: palette.text,
          fontSize: 11,
          interval: 0,
          rotate: categories.length > 6 ? 25 : 0,
        },
      },
      yAxis: {
        type: "value" as const,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: palette.grid, type: "dashed" } },
        axisLabel: {
          color: palette.text,
          fontSize: 11,
          formatter: (v: number) =>
            fmt === "amount"
              ? formatAmount(v)
              : isPct
                ? `${v.toFixed(0)}%`
                : v.toFixed(2),
        },
      },
      series: [
        {
          type: "bar" as const,
          data: seriesData,
          barMaxWidth: 36,
          label: {
            show: true,
            position: "top",
            color: palette.text,
            fontSize: 10,
            formatter: (params: { value: number | string }) => {
              const v = typeof params.value === "number" ? params.value : null;
              return fmtValue(v, fmt);
            },
          },
          emphasis: {
            itemStyle: {
              shadowBlur: 10,
              shadowColor: "rgba(0,0,0,0.12)",
            },
          },
          animationDuration: 600,
          animationEasing: "cubicOut" as const,
        },
      ],
    };
  }, [source, palette]);

  if (!option) {
    return (
      <div className="flex h-[200px] items-center justify-center text-sm text-muted-foreground">
        暂无数据
      </div>
    );
  }

  return (
    <div className="h-[280px] w-full">
      <ReactECharts option={option} style={{ height: "100%", width: "100%" }} opts={{ renderer: "canvas" }} />
    </div>
  );
}

// ── Metrics table component (同花顺 F10 风格: 可点击选择指标) ──

interface MetricsTableProps {
  items: QuarterlyFinanceItem[];
  selectedKey: string;
  onSelect: (key: string) => void;
}

function MetricsTable({ items, selectedKey, onSelect }: MetricsTableProps) {
  const periods = useMemo(() => getPeriodColumns(items), [items]);
  const visibleItems = items.slice(0, periods.length);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/20">
            <th className="sticky left-0 z-10 min-w-[140px] bg-muted/20 px-3 py-2.5 text-left text-xs font-semibold text-muted-foreground">
              报告期
            </th>
            {periods.map((p) => (
              <th
                key={p.key}
                className="min-w-[100px] px-3 py-2.5 text-right text-xs font-semibold text-muted-foreground whitespace-nowrap"
              >
                {p.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {METRIC_GROUPS.map((group) => (
            <Fragment key={group.title}>
              {/* Group header row */}
              <tr className="border-b bg-muted/40">
                <td
                  colSpan={periods.length + 1}
                  className="px-3 py-1.5 text-xs font-bold text-foreground/90 tracking-wide"
                >
                  {group.title}
                </td>
              </tr>
              {/* Metric rows */}
              {group.metrics.map((metric) => {
                const isSelected = metric.key === selectedKey;
                return (
                  <tr
                    key={metric.key}
                    className={`border-b cursor-pointer transition-colors ${
                      isSelected
                        ? "bg-primary/8 hover:bg-primary/12"
                        : "hover:bg-muted/25"
                    }`}
                    onClick={() => onSelect(metric.key)}
                  >
                    <td
                      className={`sticky left-0 z-10 px-3 py-2 text-xs whitespace-nowrap ${
                        isSelected
                          ? "bg-primary/8 font-semibold text-primary"
                          : "bg-background text-muted-foreground"
                      }`}
                    >
                      {metric.label}
                    </td>
                    {visibleItems.map((item, i) => {
                      const val = metric.extract(item);
                      return (
                        <td
                          key={periods[i].key}
                          className={`px-3 py-2 text-right tabular-nums text-xs ${
                            isSelected
                              ? "text-primary font-medium"
                              : metric.colorize ? priceColorClass(val) : "text-foreground"
                          }`}
                        >
                          {fmtValue(val, metric.fmt)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Statement Table (三大报表) ──

const METADATA_KEYS = new Set([
  "SECUCODE", "SECURITY_CODE", "SECURITY_NAME_ABBR", "ORG_CODE", "ORG_TYPE",
  "REPORT_DATE", "REPORT_TYPE", "REPORT_DATE_NAME", "SECURITY_TYPE_CODE",
  "NOTICE_DATE", "UPDATE_DATE", "CURRENCY",
]);

const STATEMENT_TABS = [
  { value: "core_metrics", label: "核心指标" },
  { value: "profit_sheet", label: "利润表" },
  { value: "balance_sheet", label: "资产负债表" },
  { value: "cash_flow", label: "现金流量表" },
] as const;

/**
 * AkShare field code → Chinese label (comprehensive, covers all 3 statements).
 * Fields not listed here will show the raw code as fallback.
 */
const FIELD_LABELS: Record<string, string> = {
  // ── 利润表 (Profit Sheet) ──
  TOTAL_OPERATE_INCOME: "营业总收入",
  OPERATE_INCOME: "营业收入",
  TOTAL_OPERATE_COST: "营业总成本",
  OPERATE_COST: "营业成本",
  OPERATE_TAX_ADD: "税金及附加",
  SALE_EXPENSE: "销售费用",
  MANAGE_EXPENSE: "管理费用",
  RESEARCH_EXPENSE: "研发费用",
  FINANCE_EXPENSE: "财务费用",
  FE_INTEREST_EXPENSE: "利息费用",
  FE_INTEREST_INCOME: "利息收入",
  OTHER_INCOME: "其他收益",
  INVEST_INCOME: "投资收益",
  INVEST_JOINT_INCOME: "对联营/合营企业投资收益",
  FAIRVALUE_CHANGE_INCOME: "公允价值变动收益",
  ASSET_DISPOSAL_INCOME: "资产处置收益",
  ASSET_IMPAIRMENT_INCOME: "资产减值损失",
  CREDIT_IMPAIRMENT_INCOME: "信用减值损失",
  OPERATE_PROFIT: "营业利润",
  NONBUSINESS_INCOME: "营业外收入",
  NONBUSINESS_EXPENSE: "营业外支出",
  TOTAL_PROFIT: "利润总额",
  INCOME_TAX: "所得税费用",
  NETPROFIT: "净利润",
  CONTINUED_NETPROFIT: "持续经营净利润",
  PARENT_NETPROFIT: "归母净利润",
  MINORITY_INTEREST: "少数股东损益",
  DEDUCT_PARENT_NETPROFIT: "扣非归母净利润",
  BASIC_EPS: "基本每股收益",
  DILUTED_EPS: "稀释每股收益",
  OTHER_COMPRE_INCOME: "其他综合收益",
  PARENT_OCI: "归母其他综合收益",
  UNABLE_OCI: "不可重分类进损益的其他综合收益",
  ABLE_OCI: "可重分类进损益的其他综合收益",
  CASHFLOW_HEDGE_VALID: "现金流量套期",
  CONVERT_DIFF: "外币报表折算差额",
  TOTAL_COMPRE_INCOME: "综合收益总额",
  PARENT_TCI: "归母综合收益总额",
  MINORITY_TCI: "少数股东综合收益总额",
  OTHERRIGHT_FAIRVALUE_CHANGE: "其他权益工具公允价值变动",
  SETUP_PROFIT_CHANGE: "设定受益计划变动",

  // ── 资产负债表 (Balance Sheet) ──
  // 流动资产
  TOTAL_CURRENT_ASSETS: "流动资产合计",
  MONETARYFUNDS: "货币资金",
  NOTE_ACCOUNTS_RECE: "应收票据及应收账款",
  ACCOUNTS_RECE: "应收账款",
  NOTE_RECE: "应收票据",
  PREPAYMENT: "预付款项",
  OTHER_CURRENT_ASSET: "其他流动资产",
  INVENTORY: "存货",
  CONTRACT_LIAB: "合同负债",
  FINANCE_RECE: "应收款项融资",
  TRADE_FINASSET_NOTFVTPL: "以摊余成本计量的金融资产",
  // 非流动资产
  TOTAL_NONCURRENT_ASSETS: "非流动资产合计",
  LONG_EQUITY_INVEST: "长期股权投资",
  OTHER_EQUITY_INVEST: "其他权益工具投资",
  FIXED_ASSET: "固定资产",
  CIP: "在建工程",
  INVEST_REALESTATE: "投资性房地产",
  INTANGIBLE_ASSET: "无形资产",
  GOODWILL: "商誉",
  LONG_RECE: "长期应收款",
  DEVELOP_EXPENSE: "开发支出",
  LONG_PREPAID_EXPENSE: "长期待摊费用",
  DEFER_TAX_ASSET: "递延所得税资产",
  OTHER_NONCURRENT_ASSET: "其他非流动资产",
  USERIGHT_ASSET: "使用权资产",
  // 资产合计
  TOTAL_ASSETS: "资产总计",
  // 流动负债
  TOTAL_CURRENT_LIAB: "流动负债合计",
  SHORT_LOAN: "短期借款",
  NOTE_ACCOUNTS_PAYABLE: "应付票据及应付账款",
  ACCOUNTS_PAYABLE: "应付账款",
  NOTE_PAYABLE: "应付票据",
  STAFF_SALARY_PAYABLE: "应付职工薪酬",
  TAX_PAYABLE: "应交税费",
  OTHER_CURRENT_LIAB: "其他流动负债",
  TOTAL_OTHER_PAYABLE: "其他应付款",
  NONCURRENT_LIAB_1YEAR: "一年内到期的非流动负债",
  // 非流动负债
  TOTAL_NONCURRENT_LIAB: "非流动负债合计",
  LONG_LOAN: "长期借款",
  LONG_PAYABLE: "长期应付款",
  LONG_STAFFSALARY_PAYABLE: "长期应付职工薪酬",
  LEASE_LIAB: "租赁负债",
  DEFER_INCOME: "递延收益",
  DEFER_TAX_LIAB: "递延所得税负债",
  PREDICT_LIAB: "预计负债",
  TRADE_FINLIAB_NOTFVTPL: "以摊余成本计量的金融负债",
  // 负债合计
  TOTAL_LIABILITIES: "负债合计",
  // 所有者权益
  TOTAL_EQUITY: "所有者权益合计",
  SHARE_CAPITAL: "股本",
  CAPITAL_RESERVE: "资本公积",
  TREASURY_SHARES: "库存股",
  SURPLUS_RESERVE: "盈余公积",
  UNASSIGN_RPOFIT: "未分配利润",
  TOTAL_PARENT_EQUITY: "归母所有者权益",
  MINORITY_EQUITY: "少数股东权益",
  TOTAL_LIAB_EQUITY: "负债和所有者权益总计",

  // ── 现金流量表 (Cash Flow Statement) ──
  // 经营活动
  SALES_SERVICES: "销售商品、提供劳务收到的现金",
  RECEIVE_TAX_REFUND: "收到的税费返还",
  RECEIVE_OTHER_OPERATE: "收到其他与经营活动有关的现金",
  TOTAL_OPERATE_INFLOW: "经营活动现金流入小计",
  BUY_SERVICES: "购买商品、接受劳务支付的现金",
  PAY_STAFF_CASH: "支付给职工的现金",
  PAY_ALL_TAX: "支付的各项税费",
  PAY_OTHER_OPERATE: "支付其他与经营活动有关的现金",
  TOTAL_OPERATE_OUTFLOW: "经营活动现金流出小计",
  NETCASH_OPERATE: "经营活动现金流净额",
  // 投资活动
  WITHDRAW_INVEST: "收回投资收到的现金",
  RECEIVE_INVEST_INCOME: "取得投资收益收到的现金",
  DISPOSAL_LONG_ASSET: "处置固定资产等收回的现金",
  DISPOSAL_SUBSIDIARY_OTHER: "处置子公司收到的现金净额",
  RECEIVE_OTHER_INVEST: "收到其他与投资活动有关的现金",
  TOTAL_INVEST_INFLOW: "投资活动现金流入小计",
  CONSTRUCT_LONG_ASSET: "购建固定资产等支付的现金",
  INVEST_PAY_CASH: "投资支付的现金",
  OBTAIN_SUBSIDIARY_OTHER: "取得子公司支付的现金净额",
  PAY_OTHER_INVEST: "支付其他与投资活动有关的现金",
  TOTAL_INVEST_OUTFLOW: "投资活动现金流出小计",
  NETCASH_INVEST: "投资活动现金流净额",
  // 筹资活动
  ACCEPT_INVEST_CASH: "吸收投资收到的现金",
  SUBSIDIARY_ACCEPT_INVEST: "子公司吸收少数股东投资收到的现金",
  RECEIVE_LOAN_CASH: "取得借款收到的现金",
  RECEIVE_OTHER_FINANCE: "收到其他与筹资活动有关的现金",
  TOTAL_FINANCE_INFLOW: "筹资活动现金流入小计",
  PAY_DEBT_CASH: "偿还债务支付的现金",
  ASSIGN_DIVIDEND_PORFIT: "分配股利、利润或偿付利息支付的现金",
  PAY_OTHER_FINANCE: "支付其他与筹资活动有关的现金",
  TOTAL_FINANCE_OUTFLOW: "筹资活动现金流出小计",
  NETCASH_FINANCE: "筹资活动现金流净额",
  // 汇率及现金变动
  RATE_CHANGE_EFFECT: "汇率变动对现金的影响",
  CCE_ADD: "现金及等价物净增加额",
  BEGIN_CCE: "期初现金及等价物余额",
  END_CCE: "期末现金及等价物余额",
  // 补充资料（净利润调节）
  ASSET_IMPAIRMENT: "资产减值准备",
  FA_IR_DEPR: "固定资产折旧",
  OILGAS_BIOLOGY_DEPR: "油气资产折耗",
  IA_AMORTIZE: "无形资产摊销",
  LPE_AMORTIZE: "长期待摊费用摊销",
  DISPOSAL_LONGASSET_LOSS: "处置固定资产等损失",
  FA_SCRAP_LOSS: "固定资产报废损失",
  FAIRVALUE_CHANGE_LOSS: "公允价值变动损失",
  INVEST_LOSS: "投资损失",
  DEFER_TAX: "递延税款",
  DT_ASSET_REDUCE: "递延所得税资产减少",
  DT_LIAB_ADD: "递延所得税负债增加",
  INVENTORY_REDUCE: "存货的减少",
  OPERATE_RECE_REDUCE: "经营性应收项目的减少",
  OPERATE_PAYABLE_ADD: "经营性应付项目的增加",
  OTHER: "其他",
  USERIGHT_ASSET_AMORTIZE: "使用权资产摊销",
};

/** Fields to hide: reconciliation balances, metadata, duplicate note fields */
const NOISE_KEYS = new Set([
  "OPINION_TYPE", "LISTING_STATE",
  "NETCASH_OPERATENOTE", "OPERATE_NETCASH_BALANCENOTE",
  "CCE_ADDNOTE", "END_CASH", "BEGIN_CASH",
]);

function filterStatementKeys(keys: string[]): string[] {
  return keys.filter((k) => {
    if (METADATA_KEYS.has(k)) return false;
    if (NOISE_KEYS.has(k)) return false;
    if (k.startsWith("_")) return false;
    if (k.endsWith("_YOY") || k.endsWith("_QOQ")) return false;
    if (k.endsWith("_BALANCE")) return false;  // reconciliation difference rows
    return true;
  });
}

// ── Statement layout definitions (同花顺 F10 style grouping) ──

interface StatementSection {
  title: string;
  fields: string[];
}

const PROFIT_SHEET_LAYOUT: StatementSection[] = [
  {
    title: "营业收支",
    fields: [
      "TOTAL_OPERATE_INCOME", "OPERATE_INCOME",
      "TOTAL_OPERATE_COST", "OPERATE_COST",
      "OPERATE_TAX_ADD", "SALE_EXPENSE", "MANAGE_EXPENSE",
      "RESEARCH_EXPENSE", "FINANCE_EXPENSE",
      "FE_INTEREST_EXPENSE", "FE_INTEREST_INCOME",
    ],
  },
  {
    title: "其他经营损益",
    fields: [
      "OTHER_INCOME", "INVEST_INCOME", "INVEST_JOINT_INCOME",
      "FAIRVALUE_CHANGE_INCOME", "ASSET_DISPOSAL_INCOME",
      "ASSET_IMPAIRMENT_INCOME", "CREDIT_IMPAIRMENT_INCOME",
    ],
  },
  {
    title: "利润",
    fields: [
      "OPERATE_PROFIT", "NONBUSINESS_INCOME", "NONBUSINESS_EXPENSE",
      "TOTAL_PROFIT", "INCOME_TAX",
      "NETPROFIT", "CONTINUED_NETPROFIT",
      "PARENT_NETPROFIT", "MINORITY_INTEREST",
      "DEDUCT_PARENT_NETPROFIT",
    ],
  },
  { title: "每股收益", fields: ["BASIC_EPS", "DILUTED_EPS"] },
  {
    title: "其他综合收益",
    fields: [
      "OTHER_COMPRE_INCOME", "PARENT_OCI", "ABLE_OCI",
      "CASHFLOW_HEDGE_VALID", "CONVERT_DIFF", "UNABLE_OCI",
      "TOTAL_COMPRE_INCOME", "PARENT_TCI", "MINORITY_TCI",
    ],
  },
];

const BALANCE_SHEET_LAYOUT: StatementSection[] = [
  {
    title: "流动资产",
    fields: [
      "TOTAL_CURRENT_ASSETS", "MONETARYFUNDS", "NOTE_ACCOUNTS_RECE",
      "ACCOUNTS_RECE", "NOTE_RECE", "PREPAYMENT", "FINANCE_RECE",
      "INVENTORY", "CONTRACT_LIAB", "TRADE_FINASSET_NOTFVTPL",
      "OTHER_CURRENT_ASSET",
    ],
  },
  {
    title: "非流动资产",
    fields: [
      "TOTAL_NONCURRENT_ASSETS", "LONG_EQUITY_INVEST", "OTHER_EQUITY_INVEST",
      "FIXED_ASSET", "CIP", "INVEST_REALESTATE", "INTANGIBLE_ASSET",
      "GOODWILL", "LONG_RECE", "DEVELOP_EXPENSE", "LONG_PREPAID_EXPENSE",
      "DEFER_TAX_ASSET", "USERIGHT_ASSET", "OTHER_NONCURRENT_ASSET",
    ],
  },
  { title: "资产总计", fields: ["TOTAL_ASSETS"] },
  {
    title: "流动负债",
    fields: [
      "TOTAL_CURRENT_LIAB", "SHORT_LOAN", "NOTE_ACCOUNTS_PAYABLE",
      "ACCOUNTS_PAYABLE", "NOTE_PAYABLE", "CONTRACT_LIAB",
      "STAFF_SALARY_PAYABLE", "TAX_PAYABLE", "OTHER_CURRENT_LIAB",
      "TOTAL_OTHER_PAYABLE", "NONCURRENT_LIAB_1YEAR",
    ],
  },
  {
    title: "非流动负债",
    fields: [
      "TOTAL_NONCURRENT_LIAB", "LONG_LOAN", "LONG_PAYABLE",
      "LONG_STAFFSALARY_PAYABLE", "LEASE_LIAB", "DEFER_INCOME",
      "DEFER_TAX_LIAB", "PREDICT_LIAB", "TRADE_FINLIAB_NOTFVTPL",
    ],
  },
  { title: "负债合计", fields: ["TOTAL_LIABILITIES"] },
  {
    title: "所有者权益",
    fields: [
      "TOTAL_EQUITY", "SHARE_CAPITAL", "CAPITAL_RESERVE",
      "TREASURY_SHARES", "SURPLUS_RESERVE", "UNASSIGN_RPOFIT",
      "TOTAL_PARENT_EQUITY", "MINORITY_EQUITY", "OTHER_COMPRE_INCOME",
    ],
  },
  { title: "负债和权益总计", fields: ["TOTAL_LIAB_EQUITY"] },
];

const CASH_FLOW_LAYOUT: StatementSection[] = [
  {
    title: "经营活动",
    fields: [
      "SALES_SERVICES", "RECEIVE_TAX_REFUND", "RECEIVE_OTHER_OPERATE",
      "TOTAL_OPERATE_INFLOW", "BUY_SERVICES", "PAY_STAFF_CASH",
      "PAY_ALL_TAX", "PAY_OTHER_OPERATE", "TOTAL_OPERATE_OUTFLOW",
      "NETCASH_OPERATE",
    ],
  },
  {
    title: "投资活动",
    fields: [
      "WITHDRAW_INVEST", "RECEIVE_INVEST_INCOME",
      "DISPOSAL_LONG_ASSET", "DISPOSAL_SUBSIDIARY_OTHER",
      "RECEIVE_OTHER_INVEST", "TOTAL_INVEST_INFLOW",
      "CONSTRUCT_LONG_ASSET", "INVEST_PAY_CASH",
      "OBTAIN_SUBSIDIARY_OTHER", "PAY_OTHER_INVEST",
      "TOTAL_INVEST_OUTFLOW", "NETCASH_INVEST",
    ],
  },
  {
    title: "筹资活动",
    fields: [
      "ACCEPT_INVEST_CASH", "SUBSIDIARY_ACCEPT_INVEST",
      "RECEIVE_LOAN_CASH", "RECEIVE_OTHER_FINANCE",
      "TOTAL_FINANCE_INFLOW", "PAY_DEBT_CASH",
      "ASSIGN_DIVIDEND_PORFIT", "PAY_OTHER_FINANCE",
      "TOTAL_FINANCE_OUTFLOW", "NETCASH_FINANCE",
    ],
  },
  {
    title: "汇率及现金变动",
    fields: ["RATE_CHANGE_EFFECT", "CCE_ADD", "BEGIN_CCE", "END_CCE"],
  },
  {
    title: "净利润调节",
    fields: [
      "NETPROFIT", "ASSET_IMPAIRMENT", "FA_IR_DEPR", "IA_AMORTIZE",
      "LPE_AMORTIZE", "USERIGHT_ASSET_AMORTIZE",
      "DISPOSAL_LONGASSET_LOSS", "FA_SCRAP_LOSS",
      "FAIRVALUE_CHANGE_LOSS", "FINANCE_EXPENSE", "INVEST_LOSS",
      "DEFER_TAX", "DT_ASSET_REDUCE", "DT_LIAB_ADD",
      "INVENTORY_REDUCE", "OPERATE_RECE_REDUCE",
      "OPERATE_PAYABLE_ADD", "OTHER",
    ],
  },
];

/** Map statement_type → layout definition */
const STATEMENT_LAYOUTS: Record<string, StatementSection[]> = {
  profit_sheet: PROFIT_SHEET_LAYOUT,
  balance_sheet: BALANCE_SHEET_LAYOUT,
  cash_flow: CASH_FLOW_LAYOUT,
};

/**
 * Resolve display keys from a layout, preserving section order.
 * Fields not in the layout are appended under "其他" section.
 */
function buildDisplaySections(
  layout: StatementSection[],
  availableKeys: Set<string>,
): StatementSection[] {
  const seen = new Set<string>();
  const result: StatementSection[] = [];

  for (const section of layout) {
    const fields = section.fields.filter((f) => availableKeys.has(f));
    if (fields.length === 0) continue;
    fields.forEach((f) => seen.add(f));
    result.push({ title: section.title, fields });
  }

  // Append any remaining keys not covered by the layout
  const remaining = [...availableKeys].filter((k) => !seen.has(k));
  if (remaining.length > 0) {
    result.push({ title: "其他", fields: remaining });
  }

  return result;
}

// ── Zone C: Statement Table (pure table, chart is in Zone B) ──

/** Key fields that represent totals/summaries — rendered bold */
const BOLD_FIELDS = new Set([
  // 利润表
  "TOTAL_OPERATE_INCOME", "TOTAL_OPERATE_COST", "OPERATE_PROFIT",
  "TOTAL_PROFIT", "NETPROFIT", "PARENT_NETPROFIT", "DEDUCT_PARENT_NETPROFIT",
  "TOTAL_COMPRE_INCOME", "PARENT_TCI",
  // 资产负债表
  "TOTAL_CURRENT_ASSETS", "TOTAL_NONCURRENT_ASSETS", "TOTAL_ASSETS",
  "TOTAL_CURRENT_LIAB", "TOTAL_NONCURRENT_LIAB", "TOTAL_LIABILITIES",
  "TOTAL_EQUITY", "TOTAL_PARENT_EQUITY", "TOTAL_LIAB_EQUITY",
  // 现金流量表
  "TOTAL_OPERATE_INFLOW", "TOTAL_OPERATE_OUTFLOW", "NETCASH_OPERATE",
  "TOTAL_INVEST_INFLOW", "TOTAL_INVEST_OUTFLOW", "NETCASH_INVEST",
  "TOTAL_FINANCE_INFLOW", "TOTAL_FINANCE_OUTFLOW", "NETCASH_FINANCE",
  "CCE_ADD", "END_CCE",
]);

/** Format statement value: negative shown as (xxx) for cleaner financial look */
function fmtStatementValue(val: number | null): string {
  if (val == null) return "--";
  const abs = Math.abs(val);
  let formatted: string;
  if (abs >= 1e8) formatted = `${(abs / 1e8).toFixed(2)}亿`;
  else if (abs >= 1e4) formatted = `${(abs / 1e4).toFixed(2)}万`;
  else formatted = abs.toFixed(2);
  return val < 0 ? `-${formatted}` : formatted;
}

interface StatementTableProps {
  data: FinancialStatementResponse;
  selectedKey: string;
  onSelect: (key: string) => void;
}

function StatementTable({ data, selectedKey, onSelect }: StatementTableProps) {
  const items = data.items ?? [];

  if (items.length === 0) {
    return <div className="py-4 text-sm text-muted-foreground">暂无数据</div>;
  }

  // Build available keys (non-null, non-noise)
  const allKeys = Object.keys(items[0]);
  const availableSet = new Set(
    filterStatementKeys(allKeys).filter((k) =>
      items.some((item) => item[k] != null),
    ),
  );

  // Resolve layout sections
  const layout = STATEMENT_LAYOUTS[data.statement_type] ?? [];
  const sections = useMemo(
    () => buildDisplaySections(layout, availableSet),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layout, items],
  );

  const visibleItems = items.slice(0, 8);
  const periodLabels = visibleItems.map((item) => statementPeriodLabel(item));

  return (
    <div className="rounded-md border overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th className="sticky left-0 z-10 min-w-[160px] bg-background px-3 py-2 text-left text-xs font-medium text-muted-foreground">
              科目
            </th>
            {periodLabels.map((label, i) => (
              <th key={i} className="min-w-[100px] px-3 py-2 text-right text-xs font-medium text-muted-foreground whitespace-nowrap">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sections.map((section) => (
            <Fragment key={section.title}>
              {/* Section header */}
              <tr className="border-b bg-muted/40">
                <td
                  colSpan={periodLabels.length + 1}
                  className="px-3 py-1.5 text-xs font-bold text-foreground/90 tracking-wide"
                >
                  {section.title}
                </td>
              </tr>
              {/* Data rows */}
              {section.fields.map((key) => {
                const isSelected = key === selectedKey;
                const isBold = BOLD_FIELDS.has(key);
                return (
                  <tr
                    key={key}
                    className={`border-b cursor-pointer transition-colors ${
                      isSelected
                        ? "bg-primary/8 hover:bg-primary/12"
                        : isBold
                          ? "bg-muted/15 hover:bg-muted/30"
                          : "hover:bg-muted/20"
                    }`}
                    onClick={() => onSelect(key)}
                  >
                    <td
                      className={`sticky left-0 z-10 px-3 py-2 text-xs whitespace-nowrap ${
                        isSelected
                          ? "bg-primary/8 text-primary font-semibold"
                          : isBold
                            ? "bg-background text-foreground font-semibold"
                            : "bg-background text-muted-foreground"
                      }`}
                    >
                      {FIELD_LABELS[key] ?? key}
                    </td>
                    {visibleItems.map((item, i) => {
                      const val = toNum(item[key]);
                      return (
                        <td
                          key={i}
                          className={`px-3 py-2 text-right tabular-nums text-xs ${
                            isBold ? "font-semibold" : ""
                          } ${isSelected ? "text-primary" : priceColorClass(val)}`}
                        >
                          {fmtStatementValue(val)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main Component ──

type FinanceTab = "core_metrics" | "profit_sheet" | "balance_sheet" | "cash_flow";

export function StockFinanceChart({ vtSymbol }: StockFinanceChartProps) {
  const [activeTab, setActiveTab] = useState<FinanceTab>("core_metrics");
  const [selectedChartKey, setSelectedChartKey] = useState("revenue");

  // Always fetch quarterly data (summary cards + core metrics tab)
  const quarterlyQuery = useQuery({
    queryKey: ["stock-finance-quarterly", vtSymbol],
    queryFn: () => fetchQuarterlyFinance(vtSymbol, 16),
    staleTime: 5 * 60 * 1000,
    enabled: !!vtSymbol,
  });

  // Fetch statement data only when on a statement tab
  const activeStatementType = activeTab !== "core_metrics" ? activeTab : null;
  const statementQuery = useQuery({
    queryKey: ["stock-finance-statement", vtSymbol, activeStatementType],
    queryFn: () =>
      fetchFinancialStatement(
        vtSymbol,
        activeStatementType as "balance_sheet" | "profit_sheet" | "cash_flow",
      ),
    staleTime: 5 * 60 * 1000,
    enabled: !!vtSymbol && !!activeStatementType,
  });

  const handleSelectKey = useCallback((key: string) => {
    setSelectedChartKey(key);
  }, []);

  const items = quarterlyQuery.data?.items ?? [];
  const periods = useMemo(() => getPeriodColumns(items), [items]);

  // ── Resolve chart data source ──
  const chartSource: ChartSource | null = useMemo(() => {
    const metric = CHART_METRICS.get(selectedChartKey);
    if (metric) {
      return { type: "metric", metric, items, periods };
    }
    const stmtItems = statementQuery.data?.items;
    if (stmtItems && stmtItems.length > 0) {
      const sliced = stmtItems.slice(0, 8);
      const dates = sliced.map((item) =>
        String(item[AK.reportDate] ?? "").slice(0, 10),
      );
      const labels = sliced.map((item) => statementPeriodLabel(item));
      return { type: "statement", fieldKey: selectedChartKey, items: sliced, dates, labels };
    }
    return null;
  }, [selectedChartKey, items, periods, statementQuery.data?.items]);

  // ── Chart label ──
  const chartLabel = useMemo(() => {
    const metric = CHART_METRICS.get(selectedChartKey);
    if (metric) {
      const group = metricGroupLabel(selectedChartKey);
      return group ? `${group} › ${metric.label}` : metric.label;
    }
    return FIELD_LABELS[selectedChartKey] ?? selectedChartKey;
  }, [selectedChartKey]);

  if (quarterlyQuery.isLoading) {
    return (
      <div className="space-y-4">
        <CardSkeleton />
        <CardSkeleton />
      </div>
    );
  }

  if (quarterlyQuery.isError) {
    return (
      <ErrorState
        message={quarterlyQuery.error instanceof Error ? quarterlyQuery.error.message : "财报加载失败"}
        onRetry={() => quarterlyQuery.refetch()}
      />
    );
  }

  if (items.length === 0) {
    return <EmptyState message="暂无财报数据" description="该股票暂无历史财报记录" />;
  }

  return (
    <div className="space-y-4">
      {/* Zone A: Summary metric cards (clickable → switch trend chart) */}
      {items[0] && (
        <SummaryCardGrid
          item={items[0]}
          selectedKey={selectedChartKey}
          onSelect={handleSelectKey}
        />
      )}

      {/* Zone B: Unified interactive trend chart */}
      <div className="rounded-md border">
        <div className="flex items-center justify-between border-b px-4 py-2">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-foreground">
              {chartLabel}
            </span>
            <span className="text-xs text-muted-foreground">
              季度趋势
            </span>
          </div>
          <span className="text-xs text-muted-foreground">
            点击上方卡片或下方表格行切换指标
          </span>
        </div>
        <div className="px-2 py-2">
          <UnifiedTrendChart source={chartSource} />
        </div>
      </div>

      {/* Zone C: Unified tabs */}
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as FinanceTab)}>
        <TabsList>
          {STATEMENT_TABS.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {/* Core metrics tab */}
        <TabsContent value="core_metrics">
          <div className="rounded-md border">
            <MetricsTable
              items={items}
              selectedKey={selectedChartKey}
              onSelect={handleSelectKey}
            />
          </div>
        </TabsContent>

        {/* Statement tabs */}
        {STATEMENT_TABS.filter((t) => t.value !== "core_metrics").map((tab) => (
          <TabsContent key={tab.value} value={tab.value}>
            {statementQuery.isLoading && activeTab === tab.value ? (
              <div className="py-4">
                <CardSkeleton />
              </div>
            ) : statementQuery.data ? (
              <StatementTable
                data={statementQuery.data}
                selectedKey={selectedChartKey}
                onSelect={handleSelectKey}
              />
            ) : (
              <div className="py-4 text-sm text-muted-foreground">
                {statementQuery.isError ? "加载失败" : "暂无数据"}
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
