import { useState } from "react";
import { RefreshCw } from "lucide-react";

import type {
  HprAnchorStats,
  HprBacktestReport,
  HprRebuildStatus,
  HprStats,
} from "@/api/highRelay";
import { EmptyState } from "@/components/EmptyState";
import { cn, formatPct } from "@/lib/utils";

const POINTS = ["A1", "A2", "B1", "B2", "B3"] as const;
const POINT_SHORT: Record<string, string> = {
  A1: "A1 修复启动",
  A2: "A2 老龙缩量",
  B1: "B1 竞价确认",
  B2: "B2 低开转强",
  B3: "B3 二波贴线",
  A级: "仅A级",
  all: "方案合计",
  miss: "未命中对照",
};
const POINT_TONE: Record<string, string> = {
  A1: "stroke-rise",
  A2: "stroke-amber-500",
  B1: "stroke-primary",
  B2: "stroke-orange-500",
  B3: "stroke-violet-500",
};
const SUMMARY_KEYS = [...POINTS, "A级", "all", "miss"] as const;

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
  const anchors = report.anchors ?? {};
  const checks = report.anchor_check ?? {};
  const exec = report.execution;
  const execAnchor = report.exec_anchor;
  return (
    <div className="space-y-4">
      <RebuildBar rebuild={rebuild} building={building} canRebuild={canRebuild}
        onRebuild={onRebuild} error={rebuildError} />

      <section className="rounded-lg border p-4 text-xs text-muted-foreground">
        <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1">
          <span className="text-sm font-semibold text-foreground">回测汇总(研究口径:持有到断板 / 产品卖出:E3)</span>
          <span>区间 {report.coverage.from} ~ {report.coverage.to}({report.coverage.months} 个月)</span>
          <span>规则版本 {report.rules_version}</span>
          <span>生成于 {formatGeneratedAt(report.generated_at)}</span>
        </div>
        <p>{report.caliber}</p>
        <p className="mt-1">E0 = 持有到首次断板日收盘(研究主算法/锚点口径);E3 = 炸板当日收盘走、封住→E0(产品卖出纪律);胜率 = 次日收盘收益&gt;0。</p>
      </section>

      <section className="grid gap-3 md:grid-cols-3">
        {SUMMARY_KEYS.map((pk) => (
          <GroupStatCard
            key={pk}
            title={POINT_SHORT[pk]}
            stats={report.summary[pk] ?? { n: 0 }}
            anchor={anchors[pk]}
            check={checks[pk]}
            radar={pk === "all" ? report.radar?.all : undefined}
          />
        ))}
      </section>

      <section className="rounded-lg border p-4" aria-label="执行口径">
        <div className="mb-2 flex flex-wrap items-center gap-x-3">
          <span className="text-sm font-semibold">执行口径:首刻过滤 × E3卖出</span>
          <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
            实盘口径
          </span>
          {execAnchor ? (
            <span className="text-xs text-muted-foreground">
              锚点 n={execAnchor.n} / E0胜 {formatPct(execAnchor.e0_win * 100)} / E3 {formatPct(execAnchor.e3_pct)} / 最差 {execAnchor.e3_worst}
            </span>
          ) : null}
        </div>
        <p className="mb-2 text-xs text-muted-foreground">{exec?.caliber}</p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">子集</th>
                <th className="py-2 text-right font-medium">笔数</th>
                <th className="py-2 text-right font-medium">E0胜率</th>
                <th className="py-2 text-right font-medium">E0均值</th>
                <th className="py-2 text-right font-medium">E3均值</th>
                <th className="py-2 text-right font-medium">E3胜率</th>
                <th className="py-2 text-right font-medium">E3单笔最差</th>
                <th className="py-2 text-left font-medium">E3分年</th>
              </tr>
            </thead>
            <tbody>
              {(exec?.subsets ?? []).map((s) => (
                <tr key={s.name} className="border-b last:border-b-0">
                  <td className="py-1.5 text-xs">{s.name}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{s.n}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">
                    {s.e0_win == null ? "--" : formatPct(s.e0_win * 100)}
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(s.e0_pct))}>
                    {s.e0_pct == null ? "--" : formatPct(s.e0_pct)}
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(s.e3_pct))}>
                    {s.e3_pct == null ? "--" : formatPct(s.e3_pct)}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums">
                    {s.e3_win == null ? "--" : formatPct(s.e3_win * 100)}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums text-fall">
                    {s.e3_worst == null ? "--" : s.e3_worst.toFixed(1)}
                  </td>
                  <td className="py-1.5 text-xs text-muted-foreground">
                    {s.yearly.map((y) => `${y.year}:${formatPct(y.e3_pct)}(n=${y.n})`).join(" ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">方案合计的一年总收益</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">年</th>
                <th className="py-2 text-right font-medium">笔数</th>
                <th className="py-2 text-right font-medium">单笔平均</th>
                <th className="py-2 text-right font-medium">年累计(每票固定1份本金相加)</th>
                <th className="py-2 text-right font-medium">年复利(满仓滚动,理论上限)</th>
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
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.sum_pct))}>
                    {formatPct(y.sum_pct)}
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(y.compound_pct))}>
                    {y.compound_pct == null ? "--" : formatPct(y.compound_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          单笔平均 = 条件准不准;年累计 = 每票固定本金一年共赚多少(同月多票并行需分仓);年复利 = 理论上限,实盘做不到。
        </p>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">逐笔等权累计收益(不复利,持有到断板口径)</div>
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
        <div className="mb-2 text-sm font-semibold">分年</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">点 / 年</th>
                <th className="py-2 text-right font-medium">笔数</th>
                <th className="py-2 text-right font-medium">封板率</th>
                <th className="py-2 text-right font-medium">次日平均每笔</th>
                <th className="py-2 text-right font-medium">胜率</th>
                <th className="py-2 text-right font-medium">持有到断板</th>
                <th className="py-2 text-right font-medium">E3</th>
              </tr>
            </thead>
            <tbody>
              {SUMMARY_KEYS.flatMap((pk) =>
                (report.yearly[pk] ?? []).map((y, i) => (
                  <tr key={`${pk}-${y.year}`} className="border-b last:border-b-0">
                    <td className="py-1.5 text-xs">
                      {i === 0 ? POINT_SHORT[pk] : ""} <span className="font-mono tabular-nums">{y.year}</span>
                    </td>
                    <StatCells stats={y} />
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          提示:五方案点分年全正;A2 的 2023 年只有 2 笔(+75.11),剔除后 2024~2026 温和全正;
          B3 去最好3笔后 2024 微负=尾部微瑕,观察级轻仓。
        </p>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 flex items-center gap-2">
          <span className="text-sm font-semibold">月度明细</span>
          <span className="flex flex-wrap gap-1">
            {SUMMARY_KEYS.map((pk) => (
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
          <table className="w-full min-w-[620px] text-sm">
            <thead className="sticky top-0 border-b bg-background text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">月份</th>
                <th className="py-2 text-right font-medium">笔数</th>
                <th className="py-2 text-right font-medium">次日平均每笔</th>
                <th className="py-2 text-right font-medium">胜率</th>
                <th className="py-2 text-right font-medium">持有到断板</th>
                <th className="py-2 text-right font-medium">E3</th>
              </tr>
            </thead>
            <tbody>
              {[...(report.monthly[monthlyPoint] ?? [])].reverse().map((m) => (
                <tr key={m.month} className="border-b last:border-b-0">
                  <td className="py-1.5 font-mono tabular-nums">{m.month}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{m.n}</td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(m.avg_pct))}>
                    {m.avg_pct == null ? "--" : formatPct(m.avg_pct)}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums">
                    {m.win == null ? "--" : formatPct(m.win * 100)}
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(m.bw_pct))}>
                    {m.bw_pct == null ? "--" : formatPct(m.bw_pct)}
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(m.e3_pct))}>
                    {m.e3_pct == null ? "--" : formatPct(m.e3_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">案例门禁与锚点自校对</div>
        <div className="grid gap-3 lg:grid-cols-2">
          <div>
            <div className="mb-1 text-xs text-muted-foreground">具名案例(验收 3)</div>
            <ul className="space-y-1 text-xs">
              {(report.case_gates ?? []).map((c) => (
                <li key={`${c.name}-${c.date}`} className="flex items-start gap-2">
                  <span className={c.pass ? "text-rise" : "text-fall"}>{c.pass ? "✓" : "✗"}</span>
                  <span>
                    <span className="font-medium">{c.name}</span>
                    <span className="font-mono tabular-nums text-muted-foreground"> {c.date}</span>
                    <span className="text-muted-foreground"> — {c.note}(实际:{c.actual_points.join("/") || "未入池"})</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="mb-1 text-xs text-muted-foreground">锚点偏差(应仅来自宇宙/数据口径微差与新增交易日)</div>
            <ul className="space-y-1 font-mono text-xs tabular-nums">
              {Object.entries(checks)
                .filter(([, v]) => typeof v === "object" && v !== null)
                .map(([key, v]) => {
                  const chk = v as { n_diff: number; bw_diff: number; win_diff: number; pass: boolean };
                  return (
                    <li key={key} className={chk.pass ? "text-muted-foreground" : "text-amber-500"}>
                      {key}: Δn {chk.n_diff} / Δ持有 {chk.bw_diff} / Δ胜 {chk.win_diff}
                      {chk.pass ? "" : " 超容差"}
                    </li>
                  );
                })}
            </ul>
          </div>
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
  anchor,
  check,
  radar,
}: {
  title: string;
  stats: HprStats;
  anchor?: HprAnchorStats;
  check?: unknown;
  radar?: { trigger_n: number; hit_n: number };
}) {
  const chk = (check ?? null) as { pass: boolean } | null;
  return (
    <div className="rounded-lg border p-4">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        {title}
        {chk ? (
          <span className={cn("rounded px-1 py-0.5 text-[10px]",
            chk.pass ? "bg-rise/15 text-rise" : "bg-amber-500/15 text-amber-500")}>
            {chk.pass ? "锚点✓" : "锚点超容差"}
          </span>
        ) : null}
      </div>
      <div className={cn("mt-1 text-xl font-semibold font-mono tabular-nums", tone(stats.bw_pct))}>
        {stats.bw_pct == null ? "--" : formatPct(stats.bw_pct)}
        <span className="ml-1 text-[11px] font-normal text-muted-foreground">持有到断板</span>
        {anchor ? (
          <span className="ml-1 text-[11px] font-normal text-muted-foreground/70">(锚 {formatPct(anchor.bw_pct)})</span>
        ) : null}
      </div>
      <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
        <div>{stats.n} 笔 · 胜率 {stats.win == null ? "--" : formatPct(stats.win * 100)} · 中位 {stats.bw_median == null ? "--" : formatPct(stats.bw_median)}</div>
        <div>
          封板率 {stats.seal == null ? "--" : formatPct(stats.seal * 100)} · E3{" "}
          <span className={cn("font-mono tabular-nums", tone(stats.e3_pct))}>
            {stats.e3_pct == null ? "--" : formatPct(stats.e3_pct)}
          </span>
        </div>
        {radar ? (
          <div>雷达触发 {radar.trigger_n} 笔 · 命中 {radar.hit_n} 笔</div>
        ) : null}
      </div>
    </div>
  );
}

function StatCells({ stats }: { stats: HprStats }) {
  return (
    <>
      <td className="py-1.5 text-right font-mono tabular-nums">{stats.n}</td>
      <td className="py-1.5 text-right font-mono tabular-nums">
        {stats.seal == null ? "--" : formatPct(stats.seal * 100)}
      </td>
      <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(stats.avg_pct))}>
        {stats.avg_pct == null ? "--" : formatPct(stats.avg_pct)}
      </td>
      <td className="py-1.5 text-right font-mono tabular-nums">
        {stats.win == null ? "--" : formatPct(stats.win * 100)}
      </td>
      <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(stats.bw_pct))}>
        {stats.bw_pct == null ? "--" : formatPct(stats.bw_pct)}
      </td>
      <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(stats.e3_pct))}>
        {stats.e3_pct == null ? "--" : formatPct(stats.e3_pct)}
      </td>
    </>
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
    <svg viewBox={`0 0 ${width} ${height}`} className="h-44 w-full" role="img" aria-label="逐笔等权累计收益曲线">
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
