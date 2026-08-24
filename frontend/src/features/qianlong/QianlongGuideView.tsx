import { useQuery } from "@tanstack/react-query";

import { fetchQianlongRules } from "@/api/qianlong";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { CopyThsConditionsButton } from "@/features/qianlong/CopyThsConditionsButton";

const GROUP_STYLES: Record<string, { badge: string; label: string }> = {
  pool: { badge: "bg-primary/15 text-primary", label: "池" },
  buy: { badge: "bg-rise/15 text-rise", label: "买" },
  sell: { badge: "bg-amber-500/15 text-amber-500", label: "卖" },
  risk: { badge: "bg-fall/15 text-fall", label: "风控" },
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
