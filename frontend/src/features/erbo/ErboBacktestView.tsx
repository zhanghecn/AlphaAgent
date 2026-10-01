import { cn } from "@/lib/utils";

import type { ErboBacktestReport, ErboRebuildStatus, ErboStats } from "@/api/erbo";

const KEYS = ["A", "B", "all", "miss"] as const;
const KEY_LABELS: Record<string, string> = {
  A: "A档 平开企稳", B: "B档 深低开杀透", all: "合计(A+B)", miss: "死格对照",
};

export function ErboBacktestView({
  report,
  rebuild,
  building,
  canRebuild,
  onRebuild,
  rebuildError,
}: {
  report: ErboBacktestReport;
  rebuild: ErboRebuildStatus;
  building: boolean;
  canRebuild: boolean;
  onRebuild: () => void;
  rebuildError: string | null;
}) {
  const anchorOk = Object.values(report.anchor_check ?? {})
    .filter((v): v is { n_diff: number; bw_diff: number; pass: boolean } => typeof v === "object")
    .every((v) => v.pass);
  const caseOk = (report.case_gates ?? []).filter((c) => c.pass).length;
  return (
    <div className="space-y-4">
      <section className="rounded-lg border px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
          <span className="text-sm font-semibold text-foreground">回测汇总(42笔定稿,T+1口径)</span>
          <span>
            {report.coverage.from} ~ {report.coverage.to} · {report.coverage.months} 个月 · {report.rules_version}
          </span>
          <span className={cn("rounded px-1.5 py-0.5", anchorOk ? "bg-rise/10 text-rise" : "bg-fall/10 text-fall")}>
            锚点{anchorOk ? "全过" : "漂移"}
          </span>
          <span className={cn("rounded px-1.5 py-0.5", caseOk === (report.case_gates ?? []).length ? "bg-rise/10 text-rise" : "bg-amber-500/10 text-amber-600")}>
            案例门禁 {caseOk}/{report.case_gates?.length ?? 0}
          </span>
          <span className="ml-auto flex items-center gap-3">
            {building ? (
              <span className="text-amber-600">重算中… {rebuild.stage ?? ""}</span>
            ) : (
              <button
                type="button"
                className="h-8 rounded-md border px-3 text-xs font-semibold text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
                disabled={!canRebuild}
                onClick={onRebuild}
              >
                全量重算
              </button>
            )}
          </span>
        </div>
        {rebuildError ? (
          <p className="mt-1 text-xs text-fall">{rebuildError}</p>
        ) : null}
        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{report.caliber}</p>
      </section>

      <section className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {KEYS.map((k) => (
          <StatCard key={k} label={KEY_LABELS[k]} stats={report.summary?.[k]} highlight={k !== "miss"} />
        ))}
      </section>

      <section className="rounded-lg border px-4 py-3">
        <div className="mb-2 text-xs font-semibold">分年(持有到断板均值)</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-1.5 text-left font-medium">档</th>
                {["2023", "2024", "2025", "2026"].map((y) => (
                  <th key={y} className="px-3 py-1.5 text-right font-medium">{y}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {["A", "B", "all"].map((k) => (
                <tr key={k}>
                  <td className="px-3 py-1.5 text-xs">{KEY_LABELS[k]}</td>
                  {(report.yearly?.[k] ?? []).map((row) => (
                    <td key={row.year} className={cn("px-3 py-1.5 text-right font-mono text-xs tabular-nums",
                      (row.bw_pct ?? 0) >= 0 ? "text-rise" : "text-fall")}>
                      {row.bw_pct != null ? `${row.bw_pct >= 0 ? "+" : ""}${row.bw_pct}` : "--"}
                      <span className="ml-1 text-[10px] text-muted-foreground">n{row.n}</span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg border px-4 py-3">
        <div className="mb-2 text-xs font-semibold">月度信号日历</div>
        <div className="flex flex-wrap gap-1">
          {(report.monthly?.all ?? []).map((m) => (
            <span
              key={m.month}
              title={`${m.month}: ${m.n}笔 均${m.bw_pct}`}
              className={cn(
                "rounded px-1.5 py-0.5 font-mono text-[10px] tabular-nums",
                m.bw_pct >= 0 ? "bg-rise/10 text-rise" : "bg-fall/10 text-fall",
              )}
            >
              {m.month.slice(2)}·{m.n}笔
            </span>
          ))}
        </div>
      </section>
    </div>
  );
}

function StatCard({ label, stats, highlight }: { label: string; stats?: ErboStats; highlight?: boolean }) {
  const empty = !stats || !stats.n;
  return (
    <div className={cn("rounded-lg border px-3 py-2.5", highlight && "border-primary/30 bg-primary/[0.03]")}>
      <div className="text-xs text-muted-foreground">{label}</div>
      {empty ? (
        <div className="mt-1 text-xs text-muted-foreground">n=0</div>
      ) : (
        <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 font-mono text-xs tabular-nums">
          <span className={cn("text-base font-bold", (stats.bw_pct ?? 0) >= 0 ? "text-rise" : "text-fall")}>
            {stats.bw_pct != null ? `${stats.bw_pct >= 0 ? "+" : ""}${stats.bw_pct}` : "--"}%
          </span>
          <span className="text-muted-foreground">{stats.n}笔</span>
          <span className="text-muted-foreground">胜{stats.win != null ? Math.round(stats.win * 100) : "--"}%</span>
          <span className="text-muted-foreground">炸{stats.seal_fail != null ? Math.round(stats.seal_fail * 100) : "--"}%</span>
        </div>
      )}
    </div>
  );
}
