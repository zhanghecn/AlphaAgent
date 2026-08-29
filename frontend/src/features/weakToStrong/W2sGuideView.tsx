import { useQuery } from "@tanstack/react-query";

import { fetchW2sRules, type W2sGroupKey, type W2sRulesPayload } from "@/api/weakToStrong";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { CopyThsConditionsButton } from "@/features/qianlong/CopyThsConditionsButton";
import { cn } from "@/lib/utils";

const GROUP_STYLES: Record<string, { badge: string; label: string }> = {
  pool: { badge: "bg-primary/15 text-primary", label: "池" },
  a1: { badge: "bg-primary/15 text-primary", label: "A1" },
  a2: { badge: "bg-rise/15 text-rise", label: "A2" },
  b: { badge: "bg-amber-500/15 text-amber-500", label: "B" },
  buy: { badge: "bg-rise/15 text-rise", label: "买" },
  sell: { badge: "bg-amber-500/15 text-amber-500", label: "卖" },
};

const GROUP_ORDER: W2sGroupKey[] = ["a1", "a2", "b"];

function pctTone(value: number) {
  return value >= 0 ? "text-rise" : "text-fall";
}

const SESSION_TABLE_COLS = ["组", "时段", "n", "封板%", "D+1均%", "D+1胜%", "再板%", "收益均%", "收益胜%"];

/** 时段/竞价共用统计表; matchWindow 时按时段列标出手期, tag=avoid 标回避。 */
function SessionStatTable({
  rows,
  columns,
  column2Label,
  groupLabels,
  matchWindowRows,
}: {
  rows: NonNullable<W2sRulesPayload["session_window"]>["table_rows"];
  columns: string[];
  column2Label: string;
  groupLabels: Record<W2sGroupKey, string>;
  matchWindowRows?: { group: W2sGroupKey; window: string }[];
}) {
  if (!rows?.length) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] text-sm">
        <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
          <tr>
            {columns.map((col, idx) => (
              <th
                key={col}
                className={cn(
                  "px-3 py-2 font-medium",
                  idx < 2 ? "text-left" : "text-right",
                )}
              >
                {idx === 1 ? column2Label : col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isAll = row.bucket === "全部";
            const style = GROUP_STYLES[row.group] ?? GROUP_STYLES.pool;
            const winRow = matchWindowRows?.find((r) => r.group === row.group);
            const isWindow = matchWindowRows && !isAll && winRow?.window === row.bucket;
            const isAvoid = row.tag === "avoid";
            return (
              <tr
                key={`${row.group}-${row.bucket}`}
                className={cn(
                  "border-b last:border-b-0",
                  isAll && "bg-muted/20 font-medium",
                  isWindow && "border-l-2 border-l-rise bg-rise/5",
                  isAvoid && "border-l-2 border-l-fall bg-fall/5",
                  !isAll && !isWindow && !isAvoid && "hover:bg-muted/30",
                )}
              >
                <td className="px-3 py-2">
                  {isAll ? (
                    <span className="text-xs text-foreground">{groupLabels[row.group]}</span>
                  ) : (
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${style.badge}`}
                    >
                      {style.label}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 font-mono text-xs tabular-nums">
                  {row.bucket}
                  {isWindow ? (
                    <span className="ml-2 rounded bg-rise/15 px-1.5 py-0.5 font-sans text-[10px] font-medium text-rise">
                      出手期
                    </span>
                  ) : null}
                  {isAvoid ? (
                    <span className="ml-2 rounded bg-fall/15 px-1.5 py-0.5 font-sans text-[10px] font-medium text-fall">
                      回避
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{row.n}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {row.seal.toFixed(1)}
                </td>
                <td className={cn("px-3 py-2 text-right font-mono tabular-nums", pctTone(row.d1))}>
                  {row.d1 >= 0 ? "+" : ""}{row.d1.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {row.d1_win.toFixed(1)}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {row.n2_lim.toFixed(1)}
                </td>
                <td className={cn("px-3 py-2 text-right font-mono tabular-nums", pctTone(row.ret))}>
                  {row.ret >= 0 ? "+" : ""}{row.ret.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {row.ret_win.toFixed(1)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** 规则说明:渲染自后端 /rules 契约(单一事实源,前端不维护副本)。 */
export function W2sGuideView() {
  const query = useQuery({
    queryKey: ["w2sRules"],
    queryFn: fetchW2sRules,
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
          <span className="text-sm font-semibold">趋势弱转强 · 规则定稿 {rules.rules_version}</span>
          <span className="text-xs text-muted-foreground">
            十一轮全市场验证(2023-04 ~ 2026-08,41 个月);每个条件都有分桶证据,见研究文档
          </span>
          <span className="ml-auto flex items-center gap-2">
            {GROUP_ORDER.map((gk) => (
              <CopyThsConditionsButton
                key={gk}
                conditions={rules.ths_pool_conditions[gk]}
                label={`复制${rules.group_labels[gk].split(" ")[0]}条件`}
              />
            ))}
          </span>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">同花顺动态板块条件(盘前池 × 3 组)</div>
        <div className="space-y-3">
          {GROUP_ORDER.map((gk) => (
            <div key={gk}>
              <div className="mb-1 flex items-center gap-2 text-xs">
                <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${GROUP_STYLES[gk].badge}`}>
                  {rules.group_labels[gk]}
                </span>
                <CopyThsConditionsButton
                  conditions={rules.ths_pool_conditions[gk]}
                  label="复制"
                  className="h-6 px-2"
                />
              </div>
              <pre className="whitespace-pre-wrap rounded-md bg-muted/40 p-3 font-mono text-xs leading-6">
                {rules.ths_pool_conditions[gk]}
              </pre>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{rules.ths_pool_note}</p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
          {rules.intraday_playbook.map((line) => <li key={line}>{line}</li>)}
        </ol>
      </section>

      {rules.session_window ? (
        <section className="rounded-lg border border-amber-500/30 p-4">
          <div className="mb-1 text-sm font-semibold text-amber-600">
            什么时候打 · 时段窗口(分钟级首触 +7% 半小时分桶研究)
          </div>
          <p className="mb-3 text-xs text-muted-foreground">{rules.session_window.headline}</p>
          <SessionStatTable
            rows={rules.session_window.table_rows}
            columns={SESSION_TABLE_COLS}
            column2Label="时段"
            groupLabels={rules.group_labels}
            matchWindowRows={rules.session_window.rows}
          />
          <p className="mt-1.5 text-[11px] text-muted-foreground/80">
            绿色标记行 = 该组出手期(黄金窗口);其余时段仅作对照——警示条所列晚到时段应回避。
            口径:D+1均% = 次日开盘/买入价-1(隔夜溢价,不持有);收益均% = 产品实际卖出
            (A2未封当日尾盘卖,封板票及A1/B板留断走)——封板票连板肥尾只在收益列,
            故 B 组 D+1 为负而收益为正是正常的(钱在板留里,不在隔夜里)。
          </p>
          <div className="mt-4 mb-1 text-xs font-semibold text-foreground">
            竞价档 × 组(开盘高低开与打板结果;A1/A2 门禁 0~4%,B 全域)
          </div>
          <SessionStatTable
            rows={rules.session_window.auction_rows}
            columns={SESSION_TABLE_COLS}
            column2Label="竞价"
            groupLabels={rules.group_labels}
          />
          {rules.session_window.auction_note ? (
            <p className="mt-1.5 text-[11px] text-muted-foreground/80">
              {rules.session_window.auction_note}
            </p>
          ) : null}
          <div className="mt-3 space-y-1.5">
            {rules.session_window.rows.map((row) => (
              <div key={row.group} className="flex gap-2 text-xs">
                <span
                  className={cn(
                    "h-fit shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium",
                    GROUP_STYLES[row.group]?.badge,
                  )}
                >
                  {rules.group_labels[row.group]}
                </span>
                <span className="text-muted-foreground">{row.note}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 rounded-md bg-fall/10 px-3 py-2 text-xs text-fall">
            {rules.session_window.warning}
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground/80">
            研究警示:{rules.session_window.research_note}
          </p>
        </section>
      ) : null}

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
        <div className="mb-2 text-sm font-semibold">已删除与证伪清单(不要加回来)</div>
        <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
          {rules.falsified_rules.map((line) => <li key={line}>{line}</li>)}
        </ul>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">案例锚点(产品行为与研究结论一致)</div>
        <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
          {rules.case_gates.map((c) => (
            <li key={`${c.name}-${c.date}`}>
              <span className="font-medium text-foreground">{c.name}</span>
              <span className="font-mono tabular-nums"> {c.date}</span> — {c.note}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted-foreground">
          回测页「案例门禁与锚点自校对」实时校验以上案例的池归属。
        </p>
      </section>

      <section className="rounded-lg border border-amber-500/30 p-4">
        <div className="mb-2 text-sm font-semibold text-amber-500">风险声明(使用前必读)</div>
        <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
          {rules.risk_notes.map((line) => <li key={line}>{line}</li>)}
        </ul>
        <p className="mt-2 text-xs text-muted-foreground">
          注意区分:低吸页趋势族的「B 涨停弱转强 P1.5」是低吸持有打法(收盘买入、D+1/3/5 评估),
          与本产品的二板反包打板(盘中 +7% 触发、不板必走)不是同一打法,两套条件互不通用的。
        </p>
      </section>
    </div>
  );
}
