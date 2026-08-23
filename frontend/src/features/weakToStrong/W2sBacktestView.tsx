import { useState } from "react";
import { RefreshCw } from "lucide-react";

import type {
  W2sAnchorStats,
  W2sBacktestReport,
  W2sGroupKey,
  W2sRebuildStatus,
  W2sStats,
} from "@/api/weakToStrong";
import { EmptyState } from "@/components/EmptyState";
import { cn, formatPct } from "@/lib/utils";

const GROUPS: W2sGroupKey[] = ["a1", "a2", "b"];
const GROUP_SHORT: Record<W2sGroupKey, string> = {
  a1: "A1 恐慌出清",
  a2: "A2 强势整理",
  b: "B 高位弱转强",
};
const GROUP_TONE: Record<W2sGroupKey, string> = {
  a1: "stroke-primary",
  a2: "stroke-rise",
  b: "stroke-amber-500",
};

export function W2sBacktestView({
  report,
  rebuild,
  building,
  canRebuild,
  onRebuild,
  rebuildError,
}: {
  report: W2sBacktestReport | undefined;
  rebuild: W2sRebuildStatus;
  building: boolean;
  canRebuild: boolean;
  onRebuild: () => void;
  rebuildError: string | null;
}) {
  const [monthlyGroup, setMonthlyGroup] = useState<W2sGroupKey>("a1");
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
  return (
    <div className="space-y-4">
      <RebuildBar rebuild={rebuild} building={building} canRebuild={canRebuild}
        onRebuild={onRebuild} error={rebuildError} />

      <section className="rounded-lg border p-4 text-xs text-muted-foreground">
        <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1">
          <span className="text-sm font-semibold text-foreground">回测汇总(产品口径:含盘中规则)</span>
          <span>区间 {report.coverage.from} ~ {report.coverage.to}({report.coverage.months} 个月)</span>
          <span>规则版本 {report.rules_version}</span>
          <span>生成于 {formatGeneratedAt(report.generated_at)}</span>
        </div>
        <p>{report.caliber}</p>
        <p className="mt-1">D+1 = 买入次日收盘卖(研究口径);板留断走 = T+1 起首个未涨停日收盘卖(产品执行口径)。</p>
      </section>

      <section className="grid gap-3 md:grid-cols-3">
        {GROUPS.map((gk) => (
          <GroupStatCard
            key={gk}
            title={GROUP_SHORT[gk]}
            stats={report.summary[`${gk}_product`] ?? { n: 0 }}
            anchor={anchors[`${gk}_product`]}
            check={checks[`${gk}_product`]}
          />
        ))}
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">终版对照(无盘中规则的研究口径)</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">组</th>
                <th className="py-2 text-right font-medium">笔数</th>
                <th className="py-2 text-right font-medium">封板率</th>
                <th className="py-2 text-right font-medium">D+1 平均每笔</th>
                <th className="py-2 text-right font-medium">胜率</th>
                <th className="py-2 text-right font-medium">连板率</th>
                <th className="py-2 text-right font-medium">板留断走</th>
              </tr>
            </thead>
            <tbody>
              {GROUPS.map((gk) => (
                <tr key={gk} className="border-b last:border-b-0">
                  <td className="py-1.5 text-xs">{GROUP_SHORT[gk]}</td>
                  <StatCells stats={report.summary[gk] ?? { n: 0 }} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">逐笔等权累计收益(产品口径,不复利)</div>
        <GroupCurves report={report} />
        <div className="mt-1 flex gap-4 text-xs text-muted-foreground">
          {GROUPS.map((gk) => (
            <span key={gk} className="flex items-center gap-1">
              <i className={cn("inline-block h-0.5 w-4", GROUP_TONE[gk].replace("stroke-", "bg-"))} />
              {GROUP_SHORT[gk]}
            </span>
          ))}
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">分年(产品口径)</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">组 / 年</th>
                <th className="py-2 text-right font-medium">笔数</th>
                <th className="py-2 text-right font-medium">封板率</th>
                <th className="py-2 text-right font-medium">D+1 平均每笔</th>
                <th className="py-2 text-right font-medium">胜率</th>
                <th className="py-2 text-right font-medium">连板率</th>
                <th className="py-2 text-right font-medium">板留断走</th>
              </tr>
            </thead>
            <tbody>
              {GROUPS.flatMap((gk) =>
                (report.yearly[gk] ?? []).map((y, i) => (
                  <tr key={`${gk}-${y.year}`} className="border-b last:border-b-0">
                    <td className="py-1.5 text-xs">
                      {i === 0 ? GROUP_SHORT[gk] : ""} <span className="font-mono tabular-nums">{y.year}</span>
                    </td>
                    <StatCells stats={y} />
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          提示:B 组 2023 年样本仅 16 笔、收益最薄;2026 年反包生态整体走弱(A1 仍正但变薄)。
        </p>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 flex items-center gap-2">
          <span className="text-sm font-semibold">月度明细</span>
          <span className="flex gap-1">
            {GROUPS.map((gk) => (
              <button
                key={gk}
                type="button"
                onClick={() => setMonthlyGroup(gk)}
                className={cn(
                  "rounded-md border px-2 py-1 text-xs",
                  monthlyGroup === gk
                    ? "border-primary bg-primary/10 text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {GROUP_SHORT[gk]}
              </button>
            ))}
          </span>
        </div>
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="sticky top-0 border-b bg-background text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">月份</th>
                <th className="py-2 text-right font-medium">笔数</th>
                <th className="py-2 text-right font-medium">D+1 平均每笔</th>
                <th className="py-2 text-right font-medium">胜率</th>
                <th className="py-2 text-right font-medium">连板率</th>
                <th className="py-2 text-right font-medium">板留断走</th>
              </tr>
            </thead>
            <tbody>
              {[...(report.monthly[monthlyGroup] ?? [])].reverse().map((m) => (
                <tr key={m.month} className="border-b last:border-b-0">
                  <td className="py-1.5 font-mono tabular-nums">{m.month}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{m.n}</td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(m.avg_pct))}>
                    {m.avg_pct == null ? "--" : formatPct(m.avg_pct)}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums">
                    {m.win == null ? "--" : formatPct(m.win * 100)}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums">
                    {m.streak2 == null ? "--" : formatPct(m.streak2 * 100)}
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(m.bw_pct))}>
                    {m.bw_pct == null ? "--" : formatPct(m.bw_pct)}
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
                    <span className="text-muted-foreground"> — {c.note}(实际:{c.actual_groups.join("/") || "未入池"})</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="mb-1 text-xs text-muted-foreground">锚点偏差(应仅来自新增交易日)</div>
            <ul className="space-y-1 font-mono text-xs tabular-nums">
              {Object.entries(checks)
                .filter(([, v]) => typeof v === "object" && v !== null)
                .map(([key, v]) => {
                  const chk = v as { n_diff: number; avg_diff: number; win_diff: number; pass: boolean };
                  return (
                    <li key={key} className={chk.pass ? "text-muted-foreground" : "text-amber-500"}>
                      {key}: Δn {chk.n_diff} / Δ均 {chk.avg_diff} / Δ胜 {chk.win_diff}
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
  rebuild: W2sRebuildStatus;
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
}: {
  title: string;
  stats: W2sStats;
  anchor?: W2sAnchorStats;
  check?: unknown;
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
      <div className={cn("mt-1 text-xl font-semibold font-mono tabular-nums", tone(stats.avg_pct))}>
        {stats.avg_pct == null ? "--" : formatPct(stats.avg_pct)}
        <span className="ml-1 text-[11px] font-normal text-muted-foreground">D+1</span>
      </div>
      <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
        <div>{stats.n} 笔 · 胜率 {stats.win == null ? "--" : formatPct(stats.win * 100)}</div>
        <div>
          封板率 {stats.seal == null ? "--" : formatPct(stats.seal * 100)} · 连板率{" "}
          {stats.streak2 == null ? "--" : formatPct(stats.streak2 * 100)}
        </div>
        <div>
          板留断走 <span className={cn("font-mono tabular-nums", tone(stats.bw_pct))}>
            {stats.bw_pct == null ? "--" : formatPct(stats.bw_pct)}
          </span>
          {anchor ? (
            <span className="text-muted-foreground/70">(锚 {formatPct(anchor.bw_pct)})</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function StatCells({ stats }: { stats: W2sStats }) {
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
      <td className="py-1.5 text-right font-mono tabular-nums">
        {stats.streak2 == null ? "--" : formatPct(stats.streak2 * 100)}
      </td>
      <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(stats.bw_pct))}>
        {stats.bw_pct == null ? "--" : formatPct(stats.bw_pct)}
      </td>
    </>
  );
}

function GroupCurves({ report }: { report: W2sBacktestReport }) {
  const width = 720;
  const height = 180;
  const curves = GROUPS.map((gk) => report.curves[gk] ?? []);
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
      {GROUPS.map((gk, i) => (
        <polyline key={gk} points={toPoints(curves[i])} className={GROUP_TONE[gk]}
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
