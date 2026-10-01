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
        <div className="mb-2 text-xs font-semibold">分年成绩（均值/中位/好票率/笔数）</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-1.5 text-left font-medium">档</th>
                {["2023", "2024", "2025", "2026"].map((y) => (
                  <th key={y} className="px-3 py-1.5 text-right font-medium">{y}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {(["A", "B", "all"] as const).map((k) => {
                const byYear = new Map(
                  (report.yearly?.[k] ?? []).map((row) => [row.year, row]),
                );
                return (
                  <tr key={k}>
                    <td className="px-3 py-1.5 text-xs">{KEY_LABELS[k]}</td>
                    {["2023", "2024", "2025", "2026"].map((y) => {
                      const row = byYear.get(y);
                      if (!row || !row.n) {
                        return <td key={y} className="px-3 py-1.5 text-right font-mono text-xs text-muted-foreground/40">—</td>;
                      }
                      const v = row.bw_pct ?? 0;
                      return (
                        <td key={y} className="px-3 py-1.5 text-right">
                          <span className={cn("font-mono text-xs font-semibold tabular-nums", v >= 0 ? "text-rise" : "text-fall")}>
                            {v >= 0 ? "+" : ""}{v}
                          </span>
                          <span className="ml-1.5 font-mono text-[10px] tabular-nums text-muted-foreground">
                            中{row.bw_median != null ? signed(row.bw_median) : "--"} · 胜{row.win != null ? Math.round(row.win * 100) : "--"}% · n{row.n}
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg border px-4 py-3">
        <div className="mb-2 text-xs font-semibold">
          月度明细（合计口径；格内=笔数·均值，空月=无信号，负月红）
        </div>
        <div className="space-y-1.5">
          {(report.monthly?.all ?? []).length === 0 ? (
            <div className="py-3 text-center text-xs text-muted-foreground">无月度数据</div>
          ) : (
            <YearCalendars monthly={report.monthly?.all ?? []} />
          )}
        </div>
      </section>
    </div>
  );
}

/** 按年分块的 12 格月历:每格 月/n笔/均值,负月红 正月绿 空月灰 */
function YearCalendars({ monthly }: { monthly: { month: string; n: number; bw_pct: number }[] }) {
  const byMonth = new Map(monthly.map((m) => [m.month, m]));
  const years = [...new Set(monthly.map((m) => m.month.slice(0, 4)))].sort();
  return (
    <>
      {years.map((year) => (
        <div key={year} className="flex items-stretch gap-2">
          <div className="flex w-10 shrink-0 items-center font-mono text-xs font-semibold text-muted-foreground">
            {year}
          </div>
          <div className="grid flex-1 grid-cols-6 gap-1 sm:grid-cols-12">
            {Array.from({ length: 12 }, (_, i) => {
              const key = `${year}-${String(i + 1).padStart(2, "0")}`;
              const m = byMonth.get(key);
              if (!m) {
                return (
                  <div key={key} className="rounded bg-muted/30 px-1 py-1 text-center">
                    <div className="text-[10px] text-muted-foreground/50">{i + 1}月</div>
                    <div className="font-mono text-[10px] text-muted-foreground/30">—</div>
                  </div>
                );
              }
              const v = m.bw_pct;
              return (
                <div
                  key={key}
                  title={`${key}：${m.n}笔 均值${signed(v)}`}
                  className={cn(
                    "rounded px-1 py-1 text-center",
                    v >= 0 ? "bg-rise/10" : "bg-fall/10",
                  )}
                >
                  <div className="text-[10px] text-muted-foreground">{i + 1}月</div>
                  <div className="font-mono text-[10px] leading-tight text-muted-foreground">{m.n}笔</div>
                  <div className={cn("font-mono text-[11px] font-semibold leading-tight tabular-nums",
                    v >= 0 ? "text-rise" : "text-fall")}>
                    {signed(v)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </>
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
            {signed(stats.bw_pct ?? 0)}%
          </span>
          <span className="text-muted-foreground">{stats.n}笔</span>
          <span className="text-muted-foreground">中位{signed(stats.bw_median ?? 0)}</span>
          <span className="text-muted-foreground">胜{stats.win != null ? Math.round(stats.win * 100) : "--"}%</span>
          <span className="text-muted-foreground">炸{stats.seal_fail != null ? Math.round(stats.seal_fail * 100) : "--"}%</span>
        </div>
      )}
    </div>
  );
}

function signed(v: number): string {
  return `${v >= 0 ? "+" : ""}${v}`;
}
