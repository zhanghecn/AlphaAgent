import { useState } from "react";
import { RefreshCw } from "lucide-react";

import type {
  FbbAnchorStats,
  FbbBacktestReport,
  FbbMatrixCell,
  FbbRebuildStatus,
  FbbSplitRow,
  FbbStats,
} from "@/api/fanbao";
import { EmptyState } from "@/components/EmptyState";
import { cn, formatPct } from "@/lib/utils";

const POINTS = ["S1", "S2", "S3", "O1", "O2"] as const;
const POINT_SHORT: Record<string, string> = {
  S1: "S1 一根急杀",
  S2: "S2 四板阴断1",
  S3: "S3 五板+阳断1",
  O1: "O1 五板+阴断1",
  O2: "O2 四板阴断3",
  S级: "仅S级出手",
  all: "方案合计",
  miss: "未命中对照",
};
const POINT_TONE: Record<string, string> = {
  S1: "stroke-rise",
  S2: "stroke-amber-500",
  S3: "stroke-primary",
  O1: "stroke-violet-500",
  O2: "stroke-orange-500",
};
const SUMMARY_KEYS = [...POINTS, "S级", "all", "miss"] as const;

const GROUP6_SHORT: Record<string, string> = {
  "2板阴": "2板阴", "2板阳": "2板阳", "4板阴": "4板阴", "4板阳": "4板阳",
  "5+板阴": "5+板阴", "5+板阳": "5+板阳",
};

/** 18格中的死格(灰显;4板阴断3=O2观察格不灰) */
const DEAD_CELLS = new Set([
  "4板阳|1", "4板阳|2", "4板阳|3",
  "4板阴|2",
  "5+板阴|2", "5+板阴|3", "5+板阳|2", "5+板阳|3",
]);

export function FbbBacktestView({
  report,
  rebuild,
  building,
  canRebuild,
  onRebuild,
  rebuildError,
}: {
  report: FbbBacktestReport | undefined;
  rebuild: FbbRebuildStatus;
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
  const matrixChecks = report.matrix_anchor_check ?? {};
  return (
    <div className="space-y-4">
      <RebuildBar rebuild={rebuild} building={building} canRebuild={canRebuild}
        onRebuild={onRebuild} error={rebuildError} />

      <section className="rounded-lg border p-4 text-xs text-muted-foreground">
        <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1">
          <span className="text-sm font-semibold text-foreground">回测汇总(单一收益口径:炸板当日走/封住持有到断板)</span>
          <span>区间 {report.coverage.from} ~ {report.coverage.to}({report.coverage.months} 个月)</span>
          <span>规则版本 {report.rules_version}</span>
          <span>生成于 {formatGeneratedAt(report.generated_at)}</span>
        </div>
        <p>{report.caliber}</p>
        <p className="mt-1">胜率 = 好票率(次日收盘≥买价,炸板但第二天涨回来的算好票);⚠️ 双口径铁律:阴阳=跌幅口径(分组),阴线数=实体口径(S1条件)。</p>
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

      <section className="rounded-lg border p-4" aria-label="18格矩阵">
        <div className="mb-2 flex flex-wrap items-center gap-x-3">
          <span className="text-sm font-semibold">18格总表(六组 × 断1/2/3天)</span>
          <span className="text-xs text-muted-foreground">灰格=死格不出手;蓝格=观察级</span>
          {Object.keys(matrixChecks).length ? (
            <span className="text-xs text-muted-foreground">
              抽格锚点:
              {Object.entries(matrixChecks)
                .filter(([, v]) => typeof v === "object" && v !== null)
                .map(([key, v]) => {
                  const chk = v as { pass: boolean };
                  return (
                    <span key={key} className={chk.pass ? "text-rise" : "text-amber-500"}>
                      {" "}{key.split("|")[0]}断{key.split("|")[1]}{chk.pass ? "✓" : "✗"}
                    </span>
                  );
                })}
            </span>
          ) : null}
        </div>
        <MatrixTable cells={report.matrix18 ?? []} />
        <p className="mt-2 text-xs text-muted-foreground">
          再连板率分母=封住的票;后续板分布=反包日起连板数(0板=炸板);与 量化因子研究/反包/汇总/基础矩阵.md 对账。
        </p>
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
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">点 / 年</th>
                <th className="py-2 text-right font-medium">笔数</th>
                <th className="py-2 text-right font-medium">封板率</th>
                <th className="py-2 text-right font-medium">次日平均每笔</th>
                <th className="py-2 text-right font-medium">胜率</th>
                <th className="py-2 text-right font-medium">持有到断板</th>
                <th className="py-2 text-right font-medium">再连板率</th>
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
          提示:S1 四年全正(+5.93/+3.94/+1.96/+5.19);S2 三年正(2023仅5笔);S3 的 2023 只有 2 笔不计,2024~2026 = +13.19/+7.78/+1.41。
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
          <table className="w-full min-w-[560px] text-sm">
            <thead className="sticky top-0 border-b bg-background text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">月份</th>
                <th className="py-2 text-right font-medium">笔数</th>
                <th className="py-2 text-right font-medium">次日平均每笔</th>
                <th className="py-2 text-right font-medium">胜率</th>
                <th className="py-2 text-right font-medium">持有到断板</th>
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">参考行与切分(3板删除/断4~5天/阴线数/坑深)</div>
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <div className="mb-1 text-xs text-muted-foreground">参考行(只统计不进实时池)</div>
            <table className="w-full text-sm">
              <thead className="border-b text-xs text-muted-foreground">
                <tr>
                  <th className="py-1.5 text-left font-medium">分组</th>
                  <th className="py-1.5 text-right font-medium">n</th>
                  <th className="py-1.5 text-right font-medium">胜率</th>
                  <th className="py-1.5 text-right font-medium">持有到断板</th>
                </tr>
              </thead>
              <tbody>
                {(report.ref_rows ?? []).map((r) => (
                  <tr key={r.label} className="border-b last:border-b-0 text-muted-foreground">
                    <td className="py-1 text-xs">{r.label}</td>
                    <td className="py-1 text-right font-mono tabular-nums">{r.n}</td>
                    <td className="py-1 text-right font-mono tabular-nums">
                      {r.win == null ? "--" : formatPct(r.win * 100)}
                    </td>
                    <td className={cn("py-1 text-right font-mono tabular-nums", tone(r.bw_pct))}>
                      {r.bw_pct == null ? "--" : formatPct(r.bw_pct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="space-y-3">
            <div>
              <div className="mb-1 text-xs text-muted-foreground">断板期阴线数切分(实体口径,段合并)</div>
              <SplitTable rows={report.yin_split ?? []} labelKey="yin" />
            </div>
            <div>
              <div className="mb-1 text-xs text-muted-foreground">坑深切分(断板期最低收盘距末板收盘)</div>
              <SplitTable rows={report.pit_split ?? []} labelKey="pit" />
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">案例门禁与锚点自校对</div>
        <div className="grid gap-3 lg:grid-cols-2">
          <div>
            <div className="mb-1 text-xs text-muted-foreground">具名案例(验收)</div>
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

function MatrixTable({ cells }: { cells: FbbMatrixCell[] }) {
  const groups = ["2板阴", "2板阳", "4板阴", "4板阳", "5+板阴", "5+板阳"];
  const byKey = new Map(cells.map((c) => [`${c.group6}|${c.gap}`, c]));
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[880px] text-sm">
        <thead className="border-b text-xs text-muted-foreground">
          <tr>
            <th className="py-2 text-left font-medium">组</th>
            <th className="py-2 text-right font-medium">n</th>
            <th className="py-2 text-right font-medium">胜率</th>
            <th className="py-2 text-right font-medium">炸板</th>
            <th className="py-2 text-right font-medium">次日收</th>
            <th className="py-2 text-right font-medium">持有到断板</th>
            <th className="py-2 text-right font-medium">再连板</th>
            <th className="py-2 text-right font-medium">后续0/1/2/3+板</th>
          </tr>
        </thead>
        <tbody>
          {groups.flatMap((g6) =>
            [1, 2, 3].map((gap) => {
              const cell = byKey.get(`${g6}|${gap}`);
              const key = `${g6}|${gap}`;
              const dead = DEAD_CELLS.has(key);
              const watch = key === "4板阴|3" || key === "5+板阴|1";
              return (
                <tr key={key} className={cn("border-b last:border-b-0", dead && "opacity-45")}>
                  <td className="py-1.5 text-xs">
                    <span className="font-medium">{GROUP6_SHORT[g6]}</span>
                    <span className="text-muted-foreground"> · 断{gap}天</span>
                    {dead ? (
                      <span className="ml-1.5 rounded bg-muted px-1 text-[10px] text-muted-foreground">死格</span>
                    ) : watch ? (
                      <span className="ml-1.5 rounded bg-primary/10 px-1 text-[10px] text-primary">观察</span>
                    ) : null}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{cell?.n ?? "--"}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">
                    {cell?.win == null ? "--" : formatPct(cell.win * 100)}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                    {cell?.seal_fail == null ? "--" : formatPct(cell.seal_fail * 100)}
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(cell?.avg_pct))}>
                    {cell?.avg_pct == null ? "--" : formatPct(cell.avg_pct)}
                  </td>
                  <td className={cn("py-1.5 text-right font-mono tabular-nums font-medium", tone(cell?.bw_pct))}>
                    {cell?.bw_pct == null ? "--" : formatPct(cell.bw_pct)}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                    {cell?.re_limit == null ? "--" : formatPct(cell.re_limit * 100)}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums text-[11px] text-muted-foreground">
                    {[cell?.follow0, cell?.follow1, cell?.follow2, cell?.follow3plus]
                      .map((v) => (v == null ? "--" : `${Math.round(v * 100)}`)).join("/")}
                  </td>
                </tr>
              );
            }),
          )}
        </tbody>
      </table>
    </div>
  );
}

function SplitTable({ rows, labelKey }: { rows: FbbSplitRow[]; labelKey: "yin" | "pit" }) {
  return (
    <table className="w-full text-sm">
      <thead className="border-b text-xs text-muted-foreground">
        <tr>
          <th className="py-1.5 text-left font-medium">段</th>
          <th className="py-1.5 text-left font-medium">切分</th>
          <th className="py-1.5 text-right font-medium">n</th>
          <th className="py-1.5 text-right font-medium">胜率</th>
          <th className="py-1.5 text-right font-medium">持有到断板</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.seg}-${r[labelKey]}-${i}`} className="border-b last:border-b-0">
            <td className="py-1 text-xs text-muted-foreground">{r.seg}</td>
            <td className="py-1 text-xs">{r[labelKey] ?? ""}</td>
            <td className="py-1 text-right font-mono tabular-nums">{r.n}</td>
            <td className="py-1 text-right font-mono tabular-nums">
              {r.win == null ? "--" : formatPct(r.win * 100)}
            </td>
            <td className={cn("py-1 text-right font-mono tabular-nums", tone(r.bw_pct))}>
              {r.bw_pct == null ? "--" : formatPct(r.bw_pct)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RebuildBar({
  rebuild,
  building,
  canRebuild,
  onRebuild,
  error,
}: {
  rebuild: FbbRebuildStatus;
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
  stats: FbbStats;
  anchor?: FbbAnchorStats;
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
          炸板 {stats.seal_fail == null ? "--" : formatPct(stats.seal_fail * 100)} · 再连板{" "}
          <span className="font-mono tabular-nums">
            {stats.re_limit == null ? "--" : formatPct(stats.re_limit * 100)}
          </span>
        </div>
        {radar ? (
          <div>雷达触发 {radar.trigger_n} 笔 · 命中 {radar.hit_n} 笔</div>
        ) : null}
      </div>
    </div>
  );
}

function StatCells({ stats }: { stats: FbbStats }) {
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
      <td className="py-1.5 text-right font-mono tabular-nums text-muted-foreground">
        {stats.re_limit == null ? "--" : formatPct(stats.re_limit * 100)}
      </td>
    </>
  );
}

function PointCurves({ report }: { report: FbbBacktestReport }) {
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
