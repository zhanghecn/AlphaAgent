import { RefreshCw } from "lucide-react";

import type { J12Agg, J12BacktestReport } from "@/api/firstRelay";
import { EmptyState } from "@/components/EmptyState";
import { cn } from "@/lib/utils";

const fmtSigned = (v: number | null | undefined, digits = 2) =>
  v == null ? "--" : `${v > 0 ? "+" : ""}${v.toFixed(digits)}`;

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
          <span className="text-sm font-semibold text-foreground">一接二回测</span>
          <span>区间 {report.window.start} ~ 今({report.window.main_start} 起为主窗,2021-2022 为纯样本外)</span>
          <span>规则版本 {report.rules_version}</span>
          <span>月均 {report.supply.per_month} 笔 / 覆盖 {report.supply.months} 个月</span>
        </div>
        <p>
          首板次日竞价确认打二板(涨停价买)。买入当天没封住,次日收盘卖;封住了拿到断板那天收盘卖,
          15 天兜底;昨天封板+今开≤-5% 竞价直接卖。所有数字都是按这套实打实执行的每笔收益(E3 口径)。
        </p>
      </section>

      <section className="rounded-lg border p-4">
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
          <div className="text-sm font-semibold">竞价确认两分支 · 六年合计</div>
          <div>
            <span className={cn("text-3xl font-bold font-mono tabular-nums", tone(total.e3))}>
              {fmtSigned(total.e3)}%
            </span>
            <span className="ml-1 text-sm text-muted-foreground">平均每笔</span>
          </div>
          <div className="text-sm text-muted-foreground">
            共 <span className="font-mono tabular-nums text-foreground">{total.n}</span> 次出手 ·
            胜率 <span className="font-mono tabular-nums text-foreground">{total.win}%</span> ·
            中位 <span className={cn("font-mono tabular-nums", tone(total.med))}>{fmtSigned(total.med)}%</span> ·
            最差单笔 <span className="font-mono tabular-nums text-fall">{total.worst}%</span>
          </div>
        </div>
        <div className="mt-2 text-xs text-muted-foreground">
          六年每笔平均 {yearEntries.map(([y, v]) => `${y}:${fmtSigned(v.e3)}`).join(" · ")} ——{" "}
          <span className={cn("font-medium", total.allpos ? "text-rise" : "text-fall")}>
            {total.allpos ? "每年都是正的" : "存在负年"}
          </span>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {yearEntries.map(([y, v]) => (
            <div key={y} className={cn("rounded border p-2", v.e3 >= 0 ? "border-rise/30" : "border-fall/30")}>
              <div className="text-xs text-muted-foreground">{y}</div>
              <div className="font-mono text-sm tabular-nums">{v.n}笔 {fmtSigned(v.e3)}%</div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">一年的成绩(六年,竞价确认两分支合计)</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">年</th>
                <th className="py-2 text-right font-medium">出手次数</th>
                <th className="py-2 text-right font-medium">胜率</th>
                <th className="py-2 text-right font-medium">平均每笔</th>
                <th className="py-2 text-right font-medium">中位</th>
                <th className="py-2 text-right font-medium">1万本金滚动(复利)</th>
                <th className="py-2 text-right font-medium">每次固定1万(相加)</th>
              </tr>
            </thead>
            <tbody>
              {report.yearly_totals.map((y) => (
                <tr key={y.year} className="border-b last:border-b-0">
                  <td className="py-1.5 font-mono tabular-nums">{y.year}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{y.n}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{y.win}%</td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.avg_pct))}>
                    {fmtSigned(y.avg_pct)}%
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.med))}>
                    {fmtSigned(y.med)}%
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.compound_pct))}>
                    {fmtSigned(y.compound_pct, 1)}%
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.sum_pct))}>
                    {fmtSigned(y.sum_pct, 1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          「1万本金滚动」=赚了不取走滚进下一笔(复利连乘)——要求每笔全仓押一票,
          同月多票并行时实际介于两列之间;「每次固定1万」=每笔赚的落袋,下次还是1万。
        </p>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">月度明细(69 个月,按年分组)</div>
        <div className="space-y-3">
          {groupMonthsByYear(report).map(({ year, rows, yTot }) => (
            <div key={year}>
              <div className="mb-1 flex items-baseline justify-between text-xs">
                <span className="font-semibold">{year}</span>
                <span className={cn("font-mono tabular-nums", tone(yTot.avg))}>
                  年计 {yTot.n}笔 · 平均 {fmtSigned(yTot.avg)}% · 固定1万合计 {fmtSigned(yTot.sum, 1)}%
                </span>
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
                      <th className="py-1.5 text-right font-medium">固定1万合计</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((m) => (
                      <tr key={m.month} className="border-b last:border-b-0">
                        <td className="py-1.5 font-mono tabular-nums">{m.month}</td>
                        <td className="py-1.5 text-right font-mono tabular-nums">{m.n}</td>
                        <td className="py-1.5 text-right font-mono tabular-nums">{m.win ?? "--"}%</td>
                        <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(m.e3))}>
                          {m.e3 == null ? "--" : `${fmtSigned(m.e3)}%`}
                        </td>
                        <td className="py-1.5 text-right font-mono tabular-nums text-fall">
                          {m.worst == null ? "--" : `${m.worst}%`}
                        </td>
                        <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(m.sum_pct))}>
                          {m.sum_pct == null ? "--" : `${fmtSigned(m.sum_pct, 1)}%`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <PointCard
          title="G1 阴坑满开(出手)"
          hint="阴线地基 × 今开7.5~9.5"
          toneClass="border-rise/40"
          main={report.by_point.main.G1}
          oos={report.by_point.oos.G1}
        />
        <PointCard
          title="S1 阳坑半开(观察)"
          hint="阳线地基 × 前10日<-3% × 今开7.5~8.5"
          toneClass="border-amber-500/40"
          main={report.by_point.main.S1}
          oos={report.by_point.oos.S1}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border p-4 text-sm">
          <h3 className="mb-2 font-semibold">对照组(不出手会怎样)</h3>
          <ControlRow label="全池未命中(雷达票)" agg={report.miss_control} />
          <ControlRow
            label="毒格·贴顶(命中也不买)"
            agg={{ n: report.poison.n, e3: report.poison.e3 ?? undefined }}
          />
          <p className="mt-2 text-xs text-muted-foreground">
            不挑就买是亏的——方案的价值全在精选;贴顶力竭首板三年全灭。
          </p>
        </section>
        <section className="rounded-lg border p-4 text-sm">
          <h3 className="mb-2 font-semibold">特征标签(看盘参考)</h3>
          <div className="space-y-1.5">
            {Object.entries(report.info_layer).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">{k}(G1 内)</span>
                <span className="font-mono tabular-nums">{v.n}笔 胜{v.win}% {fmtSigned(v.e3)}%</span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            仓位只有空仓和满仓:命中(且非毒格)就满仓打,死水/贴顶/顶格一律不碰。
          </p>
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <CaseList title="最好 5 笔(主窗)" rows={report.best} />
        <CaseList title="最差 5 笔(主窗)" rows={report.worst} />
      </div>
    </div>
  );
}

function PointCard({
  title, hint, toneClass, main, oos,
}: {
  title: string;
  hint: string;
  toneClass: string;
  main: J12Agg;
  oos: J12Agg;
}) {
  return (
    <section className={cn("rounded-lg border p-4", toneClass)}>
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="font-mono text-xs text-muted-foreground">{hint}</span>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <div className="rounded bg-background/60 p-2">
          <div className="text-xs text-muted-foreground">主窗 2023-01起</div>
          <div className={cn("font-mono tabular-nums", tone(main.e3))}>
            {main.n}笔 胜{main.win}% {fmtSigned(main.e3)}%
          </div>
        </div>
        <div className="rounded bg-background/60 p-2">
          <div className="text-xs text-muted-foreground">样本外 2021-2022</div>
          <div className={cn("font-mono tabular-nums", tone(oos.e3))}>
            {oos.n}笔 胜{oos.win}% {fmtSigned(oos.e3)}%
          </div>
        </div>
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        分年(主窗):{Object.entries(main.by_year ?? {}).map(([y, v]) => `${y}:${fmtSigned(v.e3)}`).join(" · ")}
      </div>
    </section>
  );
}

function ControlRow({ label, agg }: { label: string; agg: J12Agg }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("font-mono tabular-nums", tone(agg.e3))}>
        {agg.n}笔{agg.e3 != null && ` 胜${agg.win ?? "--"}% ${fmtSigned(agg.e3)}%`}
      </span>
    </div>
  );
}

function CaseList({
  title, rows,
}: { title: string; rows: { date: string; name: string; point: string; open: number; e3: number }[] }) {
  return (
    <section className="rounded-lg border p-4 text-sm">
      <h3 className="mb-2 font-semibold">{title}</h3>
      <ul className="space-y-1 font-mono text-xs tabular-nums">
        {rows.map((c) => (
          <li key={`${c.date}${c.name}`} className="flex justify-between">
            <span>
              {c.date} {c.name}
              <span className="ml-1 text-muted-foreground">{c.point}·今开{c.open > 0 ? "+" : ""}{c.open}%</span>
            </span>
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
      <button
        type="button"
        className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs hover:bg-muted/40"
        onClick={onRebuild}
        disabled={building}
      >
        <RefreshCw size={13} className={building ? "animate-spin" : ""} />
        {building ? "重算中…" : "重新计算"}
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
  return [...byYear.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([year, ms]) => {
      const n = ms.reduce((a, r) => a + r.n, 0);
      const sum = ms.reduce((a, r) => a + (r.sum_pct ?? 0), 0);
      const avg = n > 0 ? ms.reduce((a, r) => a + (r.e3 ?? 0) * r.n, 0) / n : null;
      return { year, rows: ms, yTot: { n, sum, avg } };
    });
}
