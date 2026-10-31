import { RefreshCw } from "lucide-react";

import type { J12Agg, J12BacktestReport, J12RulePoint, J12TailGroup } from "@/api/firstRelay";
import { EmptyState } from "@/components/EmptyState";
import { cn } from "@/lib/utils";

const RULE_IDS: J12RulePoint[] = ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10"];
const fmtSigned = (v: number | null | undefined, digits = 2) =>
  v == null ? "--" : `${v > 0 ? "+" : ""}${v.toFixed(digits)}`;
const fmtWin = (v: number | null | undefined) => v == null ? "--" : `${v.toFixed(1)}%`;

function tone(v: number | null | undefined) {
  if (v == null) return "";
  return v >= 0 ? "text-rise" : "text-fall";
}

export function J12BacktestView({
  report,
  building,
  onRebuild,
}: {
  report: J12BacktestReport | undefined;
  building: boolean;
  onRebuild: () => void;
}) {
  if (!report) {
    return (
      <div className="space-y-3">
        <RebuildBar building={building} onRebuild={onRebuild} />
        <EmptyState message="回测尚未运行——点击「重新计算」生成首份报告" />
      </div>
    );
  }
  const total = report.total;
  const yearEntries = Object.entries(total.by_year ?? {});
  return (
    <div className="space-y-4">
      <RebuildBar building={building} onRebuild={onRebuild} />

      <section className="rounded-lg border p-4 text-xs text-muted-foreground">
        <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1">
          <span className="text-sm font-semibold text-foreground">一接二综合最终版</span>
          <span>区间 {report.window.start} ~ 今({report.window.main_start} 起为主窗,2021-2022 为回放段)</span>
          <span>规则版本 {report.rules_version}</span>
          <span>月均 {report.supply.per_month} 笔 / 覆盖 {report.supply.months} 个月</span>
        </div>
        <p>
          昨日孤立首板，二板开盘非涨停，日线最高严格突破 +9% 才买；开盘更高则按开盘价。
          买入日未封则次日尾盘卖，封住则持有到断板尾盘；一字跌停顺延，15 个交易日兜底。
          同票同日只计一笔，报告中的 E3% 兼容字段在 v2 表示上述纯尾盘收益。
        </p>
      </section>

      <section className="rounded-lg border p-4">
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
          <div className="text-sm font-semibold">F1~F10 综合去重总账</div>
          <div>
            <span className={cn("text-3xl font-bold font-mono tabular-nums", tone(total.e3))}>{fmtSigned(total.e3)}%</span>
            <span className="ml-1 text-sm text-muted-foreground">平均每笔</span>
          </div>
          <div className="text-sm text-muted-foreground">
            共 <span className="font-mono tabular-nums text-foreground">{total.n}</span> 次出手 ·
            胜率 <span className="font-mono tabular-nums text-foreground">{fmtWin(total.win)}</span> ·
            中位 <span className={cn("font-mono tabular-nums", tone(total.med))}>{fmtSigned(total.med)}%</span> ·
            去最好3笔 <span className={cn("font-mono tabular-nums", tone(total.trim3))}>{fmtSigned(total.trim3)}%</span>
          </div>
        </div>
        <div className="mt-2 text-xs text-muted-foreground">
          六年每笔平均 {yearEntries.map(([y, v]) => `${y}:${fmtSigned(v.e3)}`).join(" · ")} ——{" "}
          <span className={cn("font-medium", total.allpos ? "text-rise" : "text-fall")}>{total.allpos ? "每年都是正的" : "存在负年"}</span>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {yearEntries.map(([y, v]) => (
            <div key={y} className={cn("rounded border p-2", (v.e3 ?? 0) >= 0 ? "border-rise/30" : "border-fall/30")}>
              <div className="text-xs text-muted-foreground">{y}</div>
              <div className="font-mono text-sm tabular-nums">{v.n}笔 {fmtSigned(v.e3)}%</div>
              <div className="font-mono text-xs tabular-nums text-muted-foreground">trim3 {fmtSigned(v.trim3)}%</div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">分年成绩（固定一份等权逐笔口径）</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">年</th>
                <th className="py-2 text-right font-medium">出手次数</th>
                <th className="py-2 text-right font-medium">胜率</th>
                <th className="py-2 text-right font-medium">平均每笔</th>
                <th className="py-2 text-right font-medium">中位</th>
                <th className="py-2 text-right font-medium">去最好3笔</th>
                <th className="py-2 text-right font-medium">逐笔收益合计</th>
              </tr>
            </thead>
            <tbody>
              {report.yearly_totals.map((y) => (
                <tr key={y.year} className="border-b last:border-b-0">
                  <td className="py-1.5 font-mono tabular-nums">{y.year}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{y.n}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{fmtWin(y.win)}</td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.avg_pct))}>{fmtSigned(y.avg_pct)}%</td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.med))}>{fmtSigned(y.med)}%</td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.trim3))}>{fmtSigned(y.trim3)}%</td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.sum_pct))}>{fmtSigned(y.sum_pct, 1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">收益合计是逐笔百分比相加，不是考虑同月并行持仓后的组合净值。</p>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">月度明细({report.supply.months} 个月,按年分组)</div>
        <div className="space-y-3">
          {groupMonthsByYear(report).map(({ year, rows, yTot }) => (
            <div key={year}>
              <div className="mb-1 flex items-baseline justify-between text-xs">
                <span className="font-semibold">{year}</span>
                <span className={cn("font-mono tabular-nums", tone(yTot.avg))}>年计 {yTot.n}笔 · 平均 {fmtSigned(yTot.avg)}% · 合计 {fmtSigned(yTot.sum, 1)}%</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] text-xs">
                  <thead className="border-b text-muted-foreground">
                    <tr>
                      <th className="py-1.5 text-left font-medium">月</th>
                      <th className="py-1.5 text-right font-medium">笔数</th>
                      <th className="py-1.5 text-right font-medium">胜率</th>
                      <th className="py-1.5 text-right font-medium">平均每笔</th>
                      <th className="py-1.5 text-right font-medium">最差单笔</th>
                      <th className="py-1.5 text-right font-medium">收益合计</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((m) => (
                      <tr key={m.month} className="border-b last:border-b-0">
                        <td className="py-1.5 font-mono tabular-nums">{m.month}</td>
                        <td className="py-1.5 text-right font-mono tabular-nums">{m.n}</td>
                        <td className="py-1.5 text-right font-mono tabular-nums">{fmtWin(m.win)}</td>
                        <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(m.e3))}>{fmtSigned(m.e3)}%</td>
                        <td className="py-1.5 text-right font-mono tabular-nums text-fall">{m.worst == null ? "--" : `${m.worst}%`}</td>
                        <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(m.sum_pct))}>{fmtSigned(m.sum_pct, 1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      </section>

      <RuleStatsTable report={report} />

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border p-4 text-sm">
          <h3 className="mb-2 font-semibold">未命中对照</h3>
          <ControlRow label="清洗后全池未命中" agg={report.miss_control} />
          <p className="mt-2 text-xs text-muted-foreground">总账只统计综合规则命中且同票同日去重后的事件。</p>
        </section>
        <TailStructureTable rows={report.tail_structure.all} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <CaseList title="最好 5 笔(主窗)" rows={report.best} />
        <CaseList title="最差 5 笔(主窗)" rows={report.worst} />
      </div>
    </div>
  );
}

function RuleStatsTable({ report }: { report: J12BacktestReport }) {
  return (
    <section className="rounded-lg border p-4">
      <h3 className="mb-1 text-sm font-semibold">十条规则分别统计</h3>
      <p className="mb-3 text-xs text-muted-foreground">重叠票可进入多条规则明细，但上方综合总账始终只计一笔。</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-xs">
          <thead className="border-b text-muted-foreground">
            <tr>
              <th className="py-2 text-left font-medium">规则</th>
              <th className="py-2 text-right font-medium">主窗笔数</th>
              <th className="py-2 text-right font-medium">主窗胜率</th>
              <th className="py-2 text-right font-medium">主窗均值</th>
              <th className="py-2 text-right font-medium">主窗trim3</th>
              <th className="py-2 text-right font-medium">回放笔数</th>
              <th className="py-2 text-right font-medium">回放胜率</th>
              <th className="py-2 text-right font-medium">回放均值</th>
            </tr>
          </thead>
          <tbody>
            {RULE_IDS.map((id) => {
              const main = report.by_point.main[id];
              const oos = report.by_point.oos[id];
              return (
                <tr key={id} className="border-b last:border-b-0">
                  <td className="py-1.5 font-mono font-medium">{id}</td>
                  <td className="py-1.5 text-right font-mono">{main.n}</td>
                  <td className="py-1.5 text-right font-mono">{fmtWin(main.win)}</td>
                  <td className={cn("py-1.5 text-right font-mono", tone(main.e3))}>{fmtSigned(main.e3)}%</td>
                  <td className={cn("py-1.5 text-right font-mono", tone(main.trim3))}>{fmtSigned(main.trim3)}%</td>
                  <td className="py-1.5 text-right font-mono">{oos.n}</td>
                  <td className="py-1.5 text-right font-mono">{fmtWin(oos.win)}</td>
                  <td className={cn("py-1.5 text-right font-mono", tone(oos.e3))}>{fmtSigned(oos.e3)}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TailStructureTable({ rows }: { rows: Record<"未封" | "次日断" | "连板尾", J12TailGroup> }) {
  return (
    <section className="rounded-lg border p-4 text-sm">
      <h3 className="mb-2 font-semibold">收益结构（仅作解释）</h3>
      <table className="w-full text-xs">
        <thead className="border-b text-muted-foreground">
          <tr><th className="py-1.5 text-left">结构</th><th className="py-1.5 text-right">笔数</th><th className="py-1.5 text-right">占比</th><th className="py-1.5 text-right">胜率</th><th className="py-1.5 text-right">均值</th></tr>
        </thead>
        <tbody>
          {Object.entries(rows).map(([label, row]) => (
            <tr key={label} className="border-b last:border-b-0">
              <td className="py-1.5">{label}</td><td className="py-1.5 text-right font-mono">{row.n}</td><td className="py-1.5 text-right font-mono">{row.share}%</td><td className="py-1.5 text-right font-mono">{fmtWin(row.win)}</td><td className={cn("py-1.5 text-right font-mono", tone(row.e3))}>{fmtSigned(row.e3)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ControlRow({ label, agg }: { label: string; agg: J12Agg }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("font-mono tabular-nums", tone(agg.e3))}>{agg.n}笔{agg.e3 != null && ` 胜${fmtWin(agg.win)} ${fmtSigned(agg.e3)}%`}</span>
    </div>
  );
}

function CaseList({ title, rows }: { title: string; rows: { date: string; name: string; point: string; open: number; e3: number }[] }) {
  return (
    <section className="rounded-lg border p-4 text-sm">
      <h3 className="mb-2 font-semibold">{title}</h3>
      <ul className="space-y-1 font-mono text-xs tabular-nums">
        {rows.map((c) => (
          <li key={`${c.date}${c.name}`} className="flex justify-between">
            <span>{c.date} {c.name}<span className="ml-1 text-muted-foreground">{c.point}·今开{c.open > 0 ? "+" : ""}{c.open}%</span></span>
            <span className={tone(c.e3)}>{fmtSigned(c.e3)}%</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RebuildBar({ building, onRebuild }: { building: boolean; onRebuild: () => void }) {
  return (
    <div className="flex items-center justify-end">
      <button type="button" className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs hover:bg-muted/40" onClick={onRebuild} disabled={building}>
        <RefreshCw size={13} className={building ? "animate-spin" : ""} />{building ? "重算中…" : "重新计算"}
      </button>
    </div>
  );
}

type MonthRow = { month: string; n: number; win: number | null; e3: number | null; sum_pct: number | null; worst: number | null };

function groupMonthsByYear(report: J12BacktestReport) {
  const rows: MonthRow[] = (report as unknown as { ledger_days?: MonthRow[] }).ledger_days ?? [];
  const byYear = new Map<string, MonthRow[]>();
  for (const r of rows) {
    const y = r.month.slice(0, 4);
    if (!byYear.has(y)) byYear.set(y, []);
    byYear.get(y)!.push(r);
  }
  return [...byYear.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([year, ms]) => {
    const n = ms.reduce((a, r) => a + r.n, 0);
    const sum = ms.reduce((a, r) => a + (r.sum_pct ?? 0), 0);
    const avg = n > 0 ? ms.reduce((a, r) => a + (r.e3 ?? 0) * r.n, 0) / n : null;
    return { year, rows: ms, yTot: { n, sum, avg } };
  });
}
