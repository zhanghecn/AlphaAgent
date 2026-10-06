import { useState } from "react";
import { RefreshCw } from "lucide-react";

import type {
  HprBacktestReport,
  HprRebuildStatus,
  HprStats,
} from "@/api/highRelay";
import { EmptyState } from "@/components/EmptyState";
import { cn, formatPct } from "@/lib/utils";

const POINTS = ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"] as const;
const POINT_SHORT: Record<string, string> = {
  A1: "A1 双平贴零",
  A2: "A2 一字转强",
  B1: "B1 强开系",
  B2: "B2 捡尸",
  C1: "C1 冒泡转弱",
  A3: "A3 高开低吸",
  B3: "B3 贴零温开",
  C2: "C2 四板换手",
  C3: "C3 一字换手",
  all: "方案合计",
};
// C3 曲线色 v6.11 拆分时漏配(POINTS 有 C3、TONE 没有),曲线图例 .replace 直接崩页——
// 2026-10-06 主人开回测页暴露,补上(与 C2 同蓝)
const POINT_TONE: Record<string, string> = {
  A1: "stroke-rise",
  A2: "stroke-teal-500",
  B1: "stroke-amber-500",
  B2: "stroke-yellow-500",
  C1: "stroke-emerald-500",
  A3: "stroke-rose-500",
  B3: "stroke-orange-500",
  C2: "stroke-primary",
  C3: "stroke-primary",
};
// 弱市组 K 系(v7.1):成绩卡片区展示(summary 有 2023+ 段锚定数字)
const WEAK_POINTS = ["K2", "K4", "K5", "K7", "K9", "K3"] as const;
const WEAK_POINT_SHORT: Record<string, string> = {
  K2: "K2 三板换手强开",
  K4: "K4 换足弱开捡",
  K5: "K5 贴零强开",
  K7: "K7 贴零弱开捡",
  K9: "K9 洗后温推",
  K3: "K3 双洗温推贴顶",
};

export function HprBacktestView({
  report,
  rebuild,
  building,
  canRebuild,
  onRebuild,
  rebuildError,
}: {
  report: HprBacktestReport | undefined;
  rebuild: HprRebuildStatus;
  building: boolean;
  canRebuild: boolean;
  onRebuild: () => void;
  rebuildError: string | null;
}) {
  const [monthlyPoint, setMonthlyPoint] = useState<string>("all");
  if (!report) {
    return (
      <div className="space-y-3">
        <RebuildBar rebuild={rebuild} building={building} canRebuild={canRebuild}
          onRebuild={onRebuild} error={rebuildError} />
        <EmptyState message="回测尚未运行——点击「重新计算」生成首份报告" />
      </div>
    );
  }
  const exec = report.execution;
  const exeRow = exec?.subsets?.find((s) => s.name.includes("E3") && s.name.includes("可执行"));
  return (
    <div className="space-y-4">
      <RebuildBar rebuild={rebuild} building={building} canRebuild={canRebuild}
        onRebuild={onRebuild} error={rebuildError} />

      <section className="rounded-lg border p-4 text-xs text-muted-foreground">
        <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1">
          <span className="text-sm font-semibold text-foreground">高位接力回测</span>
          <span>区间 {report.coverage.from} ~ {report.coverage.to}({report.coverage.months} 个月)</span>
          <span>规则版本 {report.rules_version}</span>
          <span>生成于 {formatGeneratedAt(report.generated_at)}</span>
        </div>
        <p>
          按口诀打板(涨停价买,一字买不进不打)。买入当天没封住,次日收盘卖;封住了继续拿,
          拿到断板当天收盘卖;跌停卖不出,顺延到次日开盘卖。所有数字都是按这套实打实执行的每笔收益。
        </p>
      </section>

      <section className="rounded-lg border p-4">
        {(() => {
          const s = report.summary["all"];
          if (!s || !s.n) return <div className="text-sm text-muted-foreground">无样本</div>;
          const total = (report.yearly_totals ?? []).reduce((a, y) => a + (y.sum_pct ?? 0), 0);
          return (
            <>
              <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
                <div>
                  <span className={cn("text-3xl font-bold font-mono tabular-nums", tone(s.e3_pct))}>
                    {formatPct(s.e3_pct ?? 0)}
                  </span>
                  <span className="ml-1 text-sm text-muted-foreground">平均每笔</span>
                </div>
                <div className="text-sm text-muted-foreground">
                  共 <span className="font-mono tabular-nums text-foreground">{s.n}</span> 次出手 ·
                  胜率 <span className="font-mono tabular-nums text-foreground">{formatPct((s.e3_win ?? 0) * 100)}</span> ·
                  三年多累计 <span className={cn("font-mono tabular-nums", tone(total))}>{formatPct(total)}</span>
                  (每次固定 1 份相加)
                </div>
              </div>
              <div className="mt-2 text-xs text-muted-foreground">
                四年每笔平均 {report.yearly_totals.map((y) =>
                  `${y.year}:${y.avg_pct == null ? "--" : formatPct(y.avg_pct)}`).join(" · ")} —— 每年都是正的
                {report.radar?.all ? ` · 候选 ${report.radar.all.trigger_n} 个,口诀命中 ${report.radar.all.hit_n} 次` : ""}
              </div>
            </>
          );
        })()}
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">一年的成绩</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">年</th>
                <th className="py-2 text-right font-medium">出手次数</th>
                <th className="py-2 text-right font-medium">平均每笔</th>
                <th className="py-2 text-right font-medium">1万本金滚动(复利)</th>
                <th className="py-2 text-right font-medium">每次固定1万(相加)</th>
              </tr>
            </thead>
            <tbody>
              {(report.yearly_totals ?? []).map((y) => (
                <tr key={y.year} className="border-b last:border-b-0">
                  <td className="py-1.5 font-mono tabular-nums">{y.year}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{y.n}</td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.avg_pct))}>
                    {y.avg_pct == null ? "--" : formatPct(y.avg_pct)}
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.compound_pct))}>
                    {y.compound_pct == null ? "--" : formatPct(y.compound_pct)}
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.sum_pct))}>
                    {formatPct(y.sum_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {exeRow ? (
          <p className="mt-2 text-xs text-muted-foreground">
            「1万本金滚动」=赚了不取走滚进下一笔(复利,1万×1.05×…连乘)——但要求每笔全仓押一票,
            同月多票并行时实际介于两列之间;「每次固定1万」=每笔赚的落袋,下次还是1万。
            同一只票拿着没卖出时不会重复买:可成交 {exeRow.n} 笔 · 平均{" "}
            <span className={cn("font-mono tabular-nums", tone(exeRow.e3_pct))}>
              {formatPct(exeRow.e3_pct ?? 0)}
            </span>
            。
          </p>
        ) : null}
      </section>

      <section className="grid gap-3 md:grid-cols-3">
        {[...POINTS, "all"].map((pk) => (
          <GroupStatCard
            key={pk}
            title={POINT_SHORT[pk]}
            stats={report.summary[pk] ?? { n: 0 }}
          />
        ))}
      </section>

      {report.summary["weak_era"]?.n ? (
        <section className="rounded-lg border border-violet-500/30 p-4">
          <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="text-sm font-semibold text-violet-500">弱市组 · K 系六条</span>
            <span className="text-xs text-muted-foreground">
              定型于 2020-22(时代段 {report.summary["weak_era"]?.n ?? 0} 笔 ·
              均 {formatPct(report.summary["weak_era"]?.e3_pct ?? 0)} ·
              胜 {formatPct((report.summary["weak_era"]?.e3_win ?? 0) * 100)});
              下排为 2023 起强市时代的参考成绩——哪组启用看「获取最新口诀」
            </span>
          </div>
          <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
            {WEAK_POINTS.map((pk) => (
              <GroupStatCard
                key={pk}
                title={WEAK_POINT_SHORT[pk]}
                stats={report.summary[pk] ?? { n: 0 }}
              />
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">累计收益(每笔固定1份,不复利)</div>
        <PointCurves report={report} />
        <div className="mt-1 flex flex-wrap gap-4 text-xs text-muted-foreground">
          {POINTS.map((pk) => (
            <span key={pk} className="flex items-center gap-1">
              <i className={cn("inline-block h-0.5 w-4", POINT_TONE[pk].replace("stroke-", "bg-"))} />
              {POINT_SHORT[pk]}
            </span>
          ))}
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">分年明细(格 = 平均每笔 · 小字 = 笔数·胜率)</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">口诀</th>
                {(report.yearly["all"] ?? []).map((y) => (
                  <th key={y.year} className="py-2 text-right font-medium">{y.year}</th>
                ))}
                <th className="py-2 text-right font-medium">全部</th>
              </tr>
            </thead>
            <tbody>
              {[...POINTS, "all"].map((pk) => {
                const byYear = new Map(
                  (report.yearly[pk] ?? []).map((y) => [y.year, y]));
                const total = report.summary[pk];
                return (
                  <tr key={pk} className={cn("border-b last:border-b-0", pk === "all" && "bg-muted/40")}>
                    <td className="py-1.5 text-xs">{POINT_SHORT[pk]}</td>
                    {(report.yearly["all"] ?? []).map((yy) => {
                      const y = byYear.get(yy.year);
                      return (
                        <td key={yy.year} className="py-1.5 text-right align-top">
                          {y && y.n ? (
                            <>
                              <div className={cn("font-mono tabular-nums", tone(y.e3_pct))}>
                                {y.e3_pct == null ? "--" : formatPct(y.e3_pct)}
                              </div>
                              <div className="text-[10px] text-muted-foreground">
                                {y.n}笔 · {y.e3_win == null ? "--" : formatPct(y.e3_win * 100)}
                              </div>
                            </>
                          ) : (
                            <span className="text-muted-foreground/50">--</span>
                          )}
                        </td>
                      );
                    })}
                    <td className="py-1.5 text-right align-top">
                      {total && total.n ? (
                        <>
                          <div className={cn("font-mono tabular-nums", tone(total.e3_pct))}>
                            {total.e3_pct == null ? "--" : formatPct(total.e3_pct)}
                          </div>
                          <div className="text-[10px] text-muted-foreground">
                            {total.n}笔 · {total.e3_win == null ? "--" : formatPct(total.e3_win * 100)}
                          </div>
                        </>
                      ) : (
                        <span className="text-muted-foreground/50">--</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold">月度明细</span>
          <span className="flex flex-wrap gap-1">
            {[...POINTS, "all"].map((pk) => (
              <button
                key={pk}
                type="button"
                onClick={() => setMonthlyPoint(pk)}
                className={cn(
                  "rounded-md border px-2 py-1 text-xs",
                  monthlyPoint === pk
                    ? "border-primary bg-primary/10 text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {POINT_SHORT[pk]}
              </button>
            ))}
          </span>
        </div>
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full min-w-[420px] text-sm">
            <thead className="sticky top-0 border-b bg-background text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">月份</th>
                <th className="py-2 text-right font-medium">笔数</th>
                <th className="py-2 text-right font-medium">平均每笔</th>
                <th className="py-2 text-right font-medium">胜率</th>
              </tr>
            </thead>
            <tbody>
              {[...(report.monthly[monthlyPoint] ?? [])].reverse().map((m) => (
                <tr key={m.month} className="border-b last:border-b-0">
                  <td className="py-1.5 font-mono tabular-nums">{m.month}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{m.n}</td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(m.e3_pct))}>
                    {m.e3_pct == null ? "--" : formatPct(m.e3_pct)}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums">
                    {m.e3_win == null ? "--" : formatPct(m.e3_win * 100)}
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

function RebuildBar({
  rebuild,
  building,
  canRebuild,
  onRebuild,
  error,
}: {
  rebuild: HprRebuildStatus;
  building: boolean;
  canRebuild: boolean;
  onRebuild: () => void;
  error: string | null;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3 text-xs text-muted-foreground">
      <button
        type="button"
        disabled={!canRebuild}
        onClick={onRebuild}
        className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-50"
      >
        <RefreshCw size={13} className={cn(building && "animate-spin")} />
        {building ? `重算中(${rebuild.stage ?? "…"})` : "重新计算"}
      </button>
      <span>
        状态:{rebuild.status ?? "idle"}
        {rebuild.message ? ` · ${rebuild.message}` : ""}
      </span>
      {error ? <span className="text-fall">{error}</span> : null}
    </div>
  );
}

function GroupStatCard({
  title,
  stats,
}: {
  title: string;
  stats: HprStats;
}) {
  return (
    <div className="rounded-lg border p-4">
      <div className="text-xs text-muted-foreground">{title}</div>
      <div className={cn("mt-1 text-xl font-semibold font-mono tabular-nums", tone(stats.e3_pct))}>
        {stats.e3_pct == null ? "--" : formatPct(stats.e3_pct)}
        <span className="ml-1 text-[11px] font-normal text-muted-foreground">平均每笔</span>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        {stats.n} 笔 · 胜率 {stats.e3_win == null ? "--" : formatPct(stats.e3_win * 100)}
      </div>
    </div>
  );
}

function PointCurves({ report }: { report: HprBacktestReport }) {
  const width = 720;
  const height = 180;
  const curves = POINTS.map((pk) => report.curves[pk] ?? []);
  const all = curves.flat().map((p) => p.cum_pct);
  if (all.length < 2) return <EmptyState message="净值数据不足" />;
  const min = Math.min(...all, 0);
  const max = Math.max(...all, 1);
  const span = max - min || 1;
  const toPoints = (curve: { cum_pct: number }[]) =>
    curve
      .map((p, i) => {
        const x = (i / Math.max(curve.length - 1, 1)) * width;
        const y = height - ((p.cum_pct - min) / span) * (height - 12) - 6;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-44 w-full" role="img" aria-label="逐笔累计收益曲线">
      <line x1="0" x2={width} y1={height - ((0 - min) / span) * (height - 12) - 6}
        y2={height - ((0 - min) / span) * (height - 12) - 6}
        className="stroke-muted-foreground/30" strokeDasharray="4 3" strokeWidth="1" />
      {POINTS.map((pk, i) => (
        <polyline key={pk} points={toPoints(curves[i])} className={POINT_TONE[pk]}
          fill="none" strokeWidth="1.5" />
      ))}
      <text x="4" y="12" className="fill-muted-foreground" fontSize="10">{max.toFixed(0)}%</text>
      <text x="4" y={height - 2} className="fill-muted-foreground" fontSize="10">{min.toFixed(0)}%</text>
    </svg>
  );
}

function tone(value: number | null | undefined) {
  if (value == null) return "";
  return value >= 0 ? "text-rise" : "text-fall";
}

function formatGeneratedAt(value: string) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(d);
}
