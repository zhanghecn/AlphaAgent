import { RefreshCw } from "lucide-react";

import type {
  QianlongBacktestReport,
  QianlongRebuildStatus,
  QianlongSimSummary,
  QianlongStats,
} from "@/api/qianlong";
import { EmptyState } from "@/components/EmptyState";
import { cn, formatPct } from "@/lib/utils";

export function QianlongBacktestView({
  report,
  rebuild,
  building,
  canRebuild,
  onRebuild,
  rebuildError,
}: {
  report: QianlongBacktestReport | undefined;
  rebuild: QianlongRebuildStatus;
  building: boolean;
  canRebuild: boolean;
  onRebuild: () => void;
  rebuildError: string | null;
}) {
  if (!report) {
    return (
      <div className="space-y-3">
        <RebuildBar
          rebuild={rebuild}
          building={building}
          canRebuild={canRebuild}
          onRebuild={onRebuild}
          error={rebuildError}
        />
        <EmptyState message="回测尚未运行——点击「重新计算」生成首份报告" />
      </div>
    );
  }
  const sim = report.simulation;
  return (
    <div className="space-y-4">
      <RebuildBar
        rebuild={rebuild}
        building={building}
        canRebuild={canRebuild}
        onRebuild={onRebuild}
        error={rebuildError}
      />
      <section className="rounded-lg border p-4 text-xs text-muted-foreground">
        <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1">
          <span className="text-sm font-semibold text-foreground">回测汇总</span>
          <span>区间 {report.coverage.from} ~ {report.coverage.to}({report.coverage.months} 个月)</span>
          <span>规则版本 {report.rules_version}</span>
          <span>生成于 {formatGeneratedAt(report.generated_at)}</span>
        </div>
        <p>{report.caliber}</p>
        <p className="mt-1">模拟仓口径:{sim.note}</p>
      </section>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatCard title="全样本信号" stats={report.summary} />
        <StatCard title="A类 · 全新急建仓" stats={report.chassis_a_subset} />
        <StatCard title="B类 · 小阳建仓" stats={report.chassis_b_subset} />
        <SimCard title="三槽模拟仓" sim={sim.plain} />
        <SimCard title="叠加月度熔断(-5% 停手)" sim={sim.with_circuit_breaker} />
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">净值曲线(退出日实现盈亏)</div>
        <EquityCurve plain={sim.plain} breaker={sim.with_circuit_breaker} />
        <div className="mt-1 flex gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <i className="inline-block h-0.5 w-4 bg-primary" /> 三槽模拟仓
          </span>
          <span className="flex items-center gap-1">
            <i className="inline-block h-0.5 w-4 bg-rise" /> 叠加月度熔断
          </span>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">分段对照</div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">分段</th>
                <th className="py-2 text-right font-medium">笔数</th>
                <th className="py-2 text-right font-medium">平均每笔</th>
                <th className="py-2 text-right font-medium">胜率</th>
                <th className="py-2 text-right font-medium">封板率</th>
                <th className="py-2 text-right font-medium">连板率</th>
              </tr>
            </thead>
            <tbody>
              <SegmentRow label="训练段 2023-01 ~ 2025-06" stats={report.segments.train_202301_202506} />
              <SegmentRow label="验证段 2025-07 起(v6: 14/14 个月全正)" stats={report.segments.valid_202507_now} />
              <SegmentRow label="剔除 2024-09 疯牛月" stats={report.segments.ex_202409} />
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">月度明细</div>
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="sticky top-0 border-b bg-background text-xs text-muted-foreground">
              <tr>
                <th className="py-2 text-left font-medium">月份</th>
                <th className="py-2 text-right font-medium">笔数</th>
                <th className="py-2 text-right font-medium">平均每笔</th>
                <th className="py-2 text-right font-medium">胜率</th>
                <th className="py-2 text-right font-medium">连板率</th>
              </tr>
            </thead>
            <tbody>
              {[...report.monthly].reverse().map((m) => (
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
  rebuild: QianlongRebuildStatus;
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

function StatCard({ title, stats }: { title: string; stats: QianlongStats }) {
  return (
    <div className="rounded-lg border p-4">
      <div className="text-xs text-muted-foreground">{title}</div>
      <div className={cn("mt-1 text-xl font-semibold font-mono tabular-nums", tone(stats.avg_pct))}>
        {stats.avg_pct == null ? "--" : formatPct(stats.avg_pct)}
      </div>
      <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
        <div>{stats.n} 笔 · 胜率 {stats.win == null ? "--" : formatPct(stats.win * 100)}</div>
        <div>
          封板率 {stats.seal == null ? "--" : formatPct(stats.seal * 100)} · 连板率{" "}
          {stats.streak2 == null ? "--" : formatPct(stats.streak2 * 100)}
        </div>
      </div>
    </div>
  );
}

function SimCard({ title, sim }: { title: string; sim: QianlongSimSummary }) {
  return (
    <div className="rounded-lg border p-4">
      <div className="text-xs text-muted-foreground">{title}</div>
      <div className={cn("mt-1 text-xl font-semibold font-mono tabular-nums", tone(sim.total_return_pct))}>
        {formatPct(sim.total_return_pct)}
      </div>
      <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
        <div>{sim.trades} 笔 · 胜率 {sim.win_rate_pct == null ? "--" : formatPct(sim.win_rate_pct)}</div>
        <div>最大回撤 {formatPct(sim.max_drawdown_pct)}</div>
      </div>
    </div>
  );
}

function SegmentRow({ label, stats }: { label: string; stats?: QianlongStats }) {
  if (!stats) return null;
  return (
    <tr className="border-b last:border-b-0">
      <td className="py-1.5 pr-3 text-xs">{label}</td>
      <td className="py-1.5 text-right font-mono tabular-nums">{stats.n}</td>
      <td className={cn("py-1.5 text-right font-mono tabular-nums", tone(stats.avg_pct))}>
        {stats.avg_pct == null ? "--" : formatPct(stats.avg_pct)}
      </td>
      <td className="py-1.5 text-right font-mono tabular-nums">
        {stats.win == null ? "--" : formatPct(stats.win * 100)}
      </td>
      <td className="py-1.5 text-right font-mono tabular-nums">
        {stats.seal == null ? "--" : formatPct(stats.seal * 100)}
      </td>
      <td className="py-1.5 text-right font-mono tabular-nums">
        {stats.streak2 == null ? "--" : formatPct(stats.streak2 * 100)}
      </td>
    </tr>
  );
}

function EquityCurve({ plain, breaker }: { plain: QianlongSimSummary; breaker: QianlongSimSummary }) {
  const width = 720;
  const height = 180;
  const all = [...plain.curve.map((p) => p.equity), ...breaker.curve.map((p) => p.equity)];
  if (all.length < 2) return <EmptyState message="净值数据不足" />;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const toPoints = (curve: { equity: number }[]) =>
    curve
      .map((p, i) => {
        const x = (i / (curve.length - 1)) * width;
        const y = height - ((p.equity - min) / span) * (height - 12) - 6;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-44 w-full" role="img" aria-label="净值曲线">
      <line x1="0" x2={width} y1={height - ((1 - min) / span) * (height - 12) - 6}
        y2={height - ((1 - min) / span) * (height - 12) - 6}
        className="stroke-muted-foreground/30" strokeDasharray="4 3" strokeWidth="1" />
      <polyline points={toPoints(plain.curve)} className="stroke-primary" fill="none" strokeWidth="1.5" />
      <polyline points={toPoints(breaker.curve)} className="stroke-rise" fill="none" strokeWidth="1.5" />
      <text x="4" y="12" className="fill-muted-foreground" fontSize="10">{max.toFixed(2)}</text>
      <text x="4" y={height - 2} className="fill-muted-foreground" fontSize="10">{min.toFixed(2)}</text>
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
