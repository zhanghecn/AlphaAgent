import { useQuery } from "@tanstack/react-query";

import { fetchW2sRules, type W2sGroupKey } from "@/api/weakToStrong";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { CopyThsConditionsButton } from "@/features/qianlong/CopyThsConditionsButton";

const GROUP_STYLES: Record<string, { badge: string; label: string }> = {
  pool: { badge: "bg-primary/15 text-primary", label: "池" },
  a1: { badge: "bg-primary/15 text-primary", label: "A1" },
  a2: { badge: "bg-rise/15 text-rise", label: "A2" },
  b: { badge: "bg-amber-500/15 text-amber-500", label: "B" },
  buy: { badge: "bg-rise/15 text-rise", label: "买" },
  sell: { badge: "bg-amber-500/15 text-amber-500", label: "卖" },
};

const GROUP_ORDER: W2sGroupKey[] = ["a1", "a2", "b"];

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
