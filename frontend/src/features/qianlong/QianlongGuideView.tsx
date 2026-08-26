import { useQuery } from "@tanstack/react-query";

import { fetchQianlongRules, type QianlongAuctionMatrix, type QianlongGapGroupStats, type QianlongTimeWindow, type QianlongWindowStats } from "@/api/qianlong";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { CopyThsConditionsButton } from "@/features/qianlong/CopyThsConditionsButton";

const GROUP_STYLES: Record<string, { badge: string; label: string }> = {
  pool: { badge: "bg-primary/15 text-primary", label: "池" },
  buy: { badge: "bg-rise/15 text-rise", label: "买" },
  sell: { badge: "bg-amber-500/15 text-amber-500", label: "卖" },
  risk: { badge: "bg-fall/15 text-fall", label: "风控" },
};

// 时段窗口表格:级别徽章样式(与实时页指挥条同色系)
const WINDOW_LEVEL_BADGE: Record<string, string> = {
  prep: "bg-primary/10 text-primary",
  gold: "bg-primary/15 text-primary font-semibold",
  fading: "bg-amber-500/15 text-amber-600",
  weak: "bg-amber-600/20 text-amber-700",
  lunch: "bg-muted text-muted-foreground",
  none: "bg-fall/15 text-fall",
  closed: "bg-muted text-muted-foreground",
};

// 竞价档判定徽章(7% 直买决策矩阵)
const AUCTION_VERDICT_BADGE: Record<string, string> = {
  best: "bg-primary/20 text-primary font-semibold",
  good: "bg-primary/10 text-primary",
  neutral: "bg-muted text-muted-foreground",
  caution: "bg-amber-500/15 text-amber-600",
  avoid: "bg-fall/15 text-fall",
};
const AUCTION_VERDICT_LABEL: Record<string, string> = {
  best: "最优", good: "可做", neutral: "看时段", caution: "谨慎", avoid: "不做",
};

/** 规则说明:渲染自后端 /rules 契约(单一事实源,前端不维护副本)。 */
export function QianlongGuideView() {
  const query = useQuery({
    queryKey: ["qianlongRules"],
    queryFn: fetchQianlongRules,
    staleTime: 300_000,
  });
  if (query.isLoading && !query.data) return <LoadingState rows={6} />;
  if (query.isError || !query.data) {
    return <ErrorState message="规则契约暂时不可用" onRetry={() => void query.refetch()} />;
  }
  const rules = query.data;
  return (
    <div className="space-y-4">
      <section className="rounded-lg border px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="text-sm font-semibold">潜龙首板 · 规则定稿 {rules.rules_version}</span>
          <span className="text-xs text-muted-foreground">
            全部条件经消融实验 + 双段验证 + Welch t 检验;每条都是做或不做的死规则
          </span>
          <span className="ml-auto flex items-center gap-2">
            <CopyThsConditionsButton conditions={rules.ths_pool_conditions} label="复制A板块(全新急建仓)" />
            <CopyThsConditionsButton conditions={rules.ths_pool_conditions_b} label="复制B板块(小阳建仓)" />
          </span>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">同花顺动态板块条件(盘前池 = A板块 ∪ B板块,分别建)</div>
        <div className="space-y-2">
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">板块 A · 全新急建仓(近60日无涨停 + 趋势年龄小)</div>
            <pre className="whitespace-pre-wrap rounded-md bg-muted/40 p-3 font-mono text-xs leading-6">
              {rules.ths_pool_conditions}
            </pre>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">板块 B · 小阳建仓(10日7阳慢建仓)</div>
            <pre className="whitespace-pre-wrap rounded-md bg-muted/40 p-3 font-mono text-xs leading-6">
              {rules.ths_pool_conditions_b}
            </pre>
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{rules.ths_pool_note}</p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
          {rules.intraday_playbook.map((line) => <li key={line}>{line}</li>)}
        </ol>
      </section>

      {rules.intraday_windows?.length ? (
        <IntradayWindowsTable windows={rules.intraday_windows} note={rules.intraday_windows_note} />
      ) : null}

      {rules.auction_matrix ? <AuctionMatrixSection matrix={rules.auction_matrix} /> : null}

      {rules.rules.map((group) => {
        const style = GROUP_STYLES[group.group] ?? GROUP_STYLES.pool;
        return (
          <section key={group.group} className="rounded-lg border p-4">
            <div className="mb-3 flex items-center gap-2">
              <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${style.badge}`}>
                {style.label}
              </span>
              <span className="text-sm font-semibold">{group.title}</span>
            </div>
            <div className="space-y-2.5">
              {group.items.map((item) => (
                <div key={item.no} className="flex gap-3 text-sm">
                  <span className="w-6 shrink-0 text-right font-mono tabular-nums text-muted-foreground">
                    {item.no}
                  </span>
                  <div className="min-w-0">
                    <div>{item.rule}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">{item.evidence}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        );
      })}

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">已证伪清单(不要加回来)</div>
        <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
          {rules.falsified_rules.map((line) => <li key={line}>{line}</li>)}
        </ul>
      </section>

      <section className="rounded-lg border border-amber-500/30 p-4">
        <div className="mb-2 text-sm font-semibold text-amber-500">风险声明(使用前必读)</div>
        <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
          {rules.risk_notes.map((line) => <li key={line}>{line}</li>)}
        </ul>
      </section>
    </div>
  );
}

/** 什么时候操作:时段质量分层表(数据来自 /rules 契约 intraday_windows,分钟研究)。 */
export function IntradayWindowsTable({
  windows,
  note,
}: {
  windows: QianlongTimeWindow[];
  note?: string;
}) {
  return (
    <section className="rounded-lg border p-4">
      <div className="mb-1 text-sm font-semibold">什么时候操作 · 时段质量分层</div>
      <div className="mb-3 text-xs text-muted-foreground">
        死规则窗口仍是 09:30~11:30;下表是分钟研究给出的质量分层——同日多信号优先做早盘触发。
        A/B 数据为分钟级窗口统计(笔数 · 均笔收益 · 触板率)。
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] text-sm">
          <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">时间窗</th>
              <th className="px-3 py-2 text-left font-medium">级别</th>
              <th className="px-3 py-2 text-left font-medium">A类(全新急建仓)</th>
              <th className="px-3 py-2 text-left font-medium">B类(小阳建仓)</th>
              <th className="px-3 py-2 text-left font-medium">操作要点</th>
            </tr>
          </thead>
          <tbody>
            {windows.map((w) => (
              <tr key={`${w.start}-${w.end}`} className="border-b last:border-b-0">
                <td className="whitespace-nowrap px-3 py-2.5 font-mono tabular-nums">
                  {w.start}~{w.end}
                </td>
                <td className="whitespace-nowrap px-3 py-2.5">
                  <span
                    className={`rounded px-1.5 py-0.5 text-xs ${WINDOW_LEVEL_BADGE[w.level] ?? WINDOW_LEVEL_BADGE.closed}`}
                  >
                    {w.label}
                  </span>
                </td>
                <WindowStatsCell stats={w.stats?.a} />
                <WindowStatsCell stats={w.stats?.b} />
                <td className="px-3 py-2.5 text-xs text-muted-foreground">{w.advice}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {note ? <p className="mt-2 text-xs text-muted-foreground">{note}</p> : null}
    </section>
  );
}

function WindowStatsCell({ stats }: { stats?: QianlongWindowStats }) {
  if (!stats) {
    return <td className="whitespace-nowrap px-3 py-2.5 text-xs text-muted-foreground/50">--</td>;
  }
  return (
    <td className="whitespace-nowrap px-3 py-2.5 text-xs">
      <span className="tabular-nums text-muted-foreground">{stats.n} 笔</span>
      <span className={`ml-2 font-mono tabular-nums ${stats.ret >= 0 ? "text-rise" : "text-fall"}`}>
        {stats.ret >= 0 ? "+" : ""}{stats.ret.toFixed(2)}%
      </span>
      <span className="ml-2 tabular-nums text-muted-foreground">触板 {stats.seal.toFixed(0)}%</span>
    </td>
  );
}

/** 竞价开盘 × 时段 · 7% 直买决策矩阵(数据来自 /rules 契约 auction_matrix,A/B 分开)。 */
export function AuctionMatrixSection({ matrix }: { matrix: QianlongAuctionMatrix }) {
  return (
    <section className="rounded-lg border p-4">
      <div className="mb-1 text-sm font-semibold">竞价开盘 × 时段 · 7% 直买决策矩阵</div>
      <div className="mb-3 text-xs text-muted-foreground">{matrix.caliber}</div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1020px] text-sm">
          <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium" rowSpan={2}>竞价档</th>
              <th className="px-2 py-1 text-center font-medium" colSpan={4}>A类(全新急建仓)</th>
              <th className="px-2 py-1 text-center font-medium" colSpan={4}>B类(小阳建仓)</th>
              <th className="px-3 py-2 text-left font-medium" rowSpan={2}>判定</th>
              <th className="px-3 py-2 text-left font-medium" rowSpan={2}>操作要点</th>
            </tr>
            <tr>
              <th className="px-2 py-1 text-right font-medium">n</th>
              <th className="px-2 py-1 text-right font-medium">封板%</th>
              <th className="px-2 py-1 text-right font-medium">D+1胜%</th>
              <th className="px-2 py-1 text-right font-medium">ret</th>
              <th className="px-2 py-1 text-right font-medium">n</th>
              <th className="px-2 py-1 text-right font-medium">封板%</th>
              <th className="px-2 py-1 text-right font-medium">D+1胜%</th>
              <th className="px-2 py-1 text-right font-medium">ret</th>
            </tr>
          </thead>
          <tbody>
            {matrix.gap_rows.map((row) => (
              <tr key={row.label} className="border-b last:border-b-0 align-top">
                <td className="whitespace-nowrap px-3 py-2.5">{row.label}</td>
                <GapGroupCells g={row.a} />
                <GapGroupCells g={row.b} />
                <td className="whitespace-nowrap px-3 py-2.5">
                  <span className={`rounded px-1.5 py-0.5 text-xs ${AUCTION_VERDICT_BADGE[row.verdict] ?? AUCTION_VERDICT_BADGE.neutral}`}>
                    {AUCTION_VERDICT_LABEL[row.verdict] ?? row.verdict}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-xs text-muted-foreground">{row.advice}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mb-1 mt-4 text-xs font-medium text-muted-foreground">
        黄金窗封板率热感 09:30~09:50(列=首触 5 分钟桶;— = 样本不足 3 笔;括号=笔数)
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <HeatTable rows={matrix.gap_rows} buckets={matrix.matrix_buckets} groupKey="a" title="A类(全新急建仓)" />
        <HeatTable rows={matrix.gap_rows} buckets={matrix.matrix_buckets} groupKey="b" title="B类(小阳建仓)" />
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{matrix.note}</p>
    </section>
  );
}

function GapGroupCells({ g }: { g?: QianlongGapGroupStats }) {
  if (!g) {
    return (
      <>
        <td className="px-2 py-2.5 text-right text-xs text-muted-foreground/50">--</td>
        <td className="px-2 py-2.5 text-right text-xs text-muted-foreground/50">--</td>
        <td className="px-2 py-2.5 text-right text-xs text-muted-foreground/50">--</td>
        <td className="px-2 py-2.5 text-right text-xs text-muted-foreground/50">--</td>
      </>
    );
  }
  return (
    <>
      <td className="px-2 py-2.5 text-right font-mono tabular-nums text-xs text-muted-foreground">{g.n}</td>
      <td className="px-2 py-2.5 text-right font-mono tabular-nums text-xs">{g.seal.toFixed(0)}</td>
      <td className="px-2 py-2.5 text-right font-mono tabular-nums text-xs">{g.d1_win.toFixed(0)}</td>
      <td className={`px-2 py-2.5 text-right font-mono tabular-nums text-xs ${g.ret >= 0 ? "text-rise" : "text-fall"}`}>
        {g.ret >= 0 ? "+" : ""}{g.ret.toFixed(2)}%
      </td>
    </>
  );
}

function HeatTable({
  rows, buckets, groupKey, title,
}: {
  rows: QianlongAuctionMatrix["gap_rows"];
  buckets: string[];
  groupKey: "a" | "b";
  title: string;
}) {
  const cellsKey = groupKey === "a" ? "cells_a" : "cells_b";
  return (
    <div>
      <div className="mb-1 text-xs text-muted-foreground">{title}</div>
      <table className="w-full text-sm">
        <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
          <tr>
            <th className="px-2 py-1.5 text-left font-medium">竞价\首触</th>
            {buckets.map((b) => (
              <th key={b} className="px-2 py-1.5 text-right font-medium">{b}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const cells = (row[cellsKey] ?? []) as ({ seal: number; n: number } | null)[];
            return (
              <tr key={row.label} className="border-b last:border-b-0">
                <td className="whitespace-nowrap px-2 py-2 text-xs">{row.label}</td>
                {buckets.map((b, i) => {
                  const cell = cells[i];
                  return (
                    <td key={b} className="px-2 py-2 text-right">
                      {cell == null ? (
                        <span className="text-xs text-muted-foreground/40">—</span>
                      ) : (
                        <span className={`font-mono tabular-nums text-xs ${sealTone(cell.seal)}`}>
                          {cell.seal.toFixed(0)}%
                          <span className="ml-1 text-[10px] text-muted-foreground">({cell.n})</span>
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function sealTone(seal: number) {
  if (seal >= 60) return "bg-primary/15 px-1.5 py-0.5 rounded text-primary font-semibold";
  if (seal < 35) return "text-muted-foreground";
  return "";
}
