import { useQuery } from "@tanstack/react-query";

import { fetchW2sRules, type W2sGroupKey } from "@/api/weakToStrong";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { CopyThsConditionsButton } from "@/features/qianlong/CopyThsConditionsButton";
import { cn } from "@/lib/utils";

const GROUP_STYLES: Record<string, { badge: string; label: string }> = {
  pool: { badge: "bg-primary/15 text-primary", label: "池" },
  yin2: { badge: "bg-primary/15 text-primary", label: "2板阴" },
  yang2a: { badge: "bg-rise/15 text-rise", label: "首阳" },
  yang2b: { badge: "bg-orange-500/15 text-orange-500", label: "纠缠" },
  yin4: { badge: "bg-violet-500/15 text-violet-500", label: "4+阴" },
  yang4: { badge: "bg-amber-500/15 text-amber-500", label: "4+阳" },
  buy: { badge: "bg-rise/15 text-rise", label: "买" },
  sell: { badge: "bg-amber-500/15 text-amber-500", label: "卖" },
};

const GROUP_ORDER: W2sGroupKey[] = ["yin2", "yang2a", "yang2b", "yin4", "yang4"];

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
          <span className="text-sm font-semibold">N型补涨打板 · 规则定稿 {rules.rules_version}</span>
          <span className="text-xs text-muted-foreground">
            洗盘坑统一模型×均线形态×夹层结构全市场验证(2023-04 ~ 2026-08);每条件都有分桶证据,见研究文档
          </span>
          <span className="ml-auto flex items-center gap-2">
            {GROUP_ORDER.map((gk) => (
              <CopyThsConditionsButton
                key={gk}
                conditions={rules.ths_pool_conditions[gk]}
                label={`复制${GROUP_STYLES[gk].label}条件`}
              />
            ))}
          </span>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">同花顺动态板块条件(盘前池 × 四组五条件)</div>
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

      <section className="rounded-lg border p-4" aria-label="首触板时间观察">
        <div className="mb-1 flex items-center gap-2">
          <span className="text-sm font-semibold">首触板时间观察 · 各组最佳区间</span>
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-400">
            观察参考 · 非规则
          </span>
        </div>
        <p className="mb-3 text-xs text-muted-foreground">{rules.touch_time_windows.meta}</p>
        <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-2">
          {rules.touch_time_windows.class_hints.map((h) => (
            <div key={h.cls} className="flex items-baseline gap-2 rounded-md border border-primary/20 bg-primary/5 px-3 py-2">
              <span className="shrink-0 font-mono text-sm font-semibold text-primary">{h.label}</span>
              <span className="text-xs leading-5 text-muted-foreground">{h.hint}</span>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {rules.touch_time_windows.groups.map((tw) => {
            const style = GROUP_STYLES[tw.group === "yang2" ? "yang2a" : tw.group];
            return (
              <div key={tw.group} className="rounded-lg border bg-muted/20 p-3">
                <div className="mb-2 flex items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${style.badge}`}>
                    {tw.label}
                  </span>
                </div>
                <div className="font-mono text-lg font-semibold text-foreground">
                  {tw.primary.window}
                  <span className="ml-1.5 align-middle text-[11px] font-normal text-muted-foreground">
                    主 n={tw.primary.n}　+{tw.primary.ret.toFixed(2)}% / {tw.primary.win}%
                  </span>
                </div>
                <div className="mt-1 font-mono text-sm text-muted-foreground">
                  {tw.secondary.window}
                  <span className="ml-1.5 align-middle text-[11px]">
                    次 n={tw.secondary.n}　+{tw.secondary.ret.toFixed(2)}% / {tw.secondary.win}%
                  </span>
                </div>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">{tw.note}</p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="rounded-lg border p-4" aria-label="连板延续去留决策">
        <div className="mb-1 flex items-center gap-2">
          <span className="text-sm font-semibold">连板延续 · 去留决策(什么时刻可以多拿一天)</span>
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-400">
            观察参考 · 持有规则仍=板留断走
          </span>
        </div>
        <p className="mb-3 text-xs text-muted-foreground">{rules.streak_hold.meta}</p>

        <div className="mb-2 text-xs font-semibold text-foreground">
          ① {rules.streak_hold.first_night.title}
          <span className="ml-2 font-normal text-muted-foreground">{rules.streak_hold.first_night.baseline}</span>
        </div>
        <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-2">
          <div className="flex items-baseline gap-2 rounded-md border border-rise/20 bg-rise/5 px-3 py-2">
            <span className="shrink-0 text-xs font-semibold text-rise">黄金格</span>
            <span className="text-xs leading-5 text-muted-foreground">{rules.streak_hold.first_night.golden_rule}</span>
          </div>
          <div className="flex items-baseline gap-2 rounded-md border border-fall/20 bg-fall/5 px-3 py-2">
            <span className="shrink-0 text-xs font-semibold text-fall">避雷</span>
            <span className="text-xs leading-5 text-muted-foreground">{rules.streak_hold.first_night.avoid_rule}</span>
          </div>
        </div>
        <div className="mb-4 overflow-x-auto">
          <table className="w-full min-w-[680px] text-xs">
            <thead className="border-b bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">组</th>
                <th className="px-3 py-2 text-right font-medium">黄金格n</th>
                <th className="px-3 py-2 text-right font-medium">封板率</th>
                <th className="px-3 py-2 text-right font-medium">多拿一天</th>
                <th className="px-3 py-2 text-left font-medium">说明</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rules.streak_hold.first_night.groups.map((g) => {
                const style = GROUP_STYLES[g.group === "yang2" ? "yang2a" : g.group];
                return (
                  <tr key={g.group}>
                    <td className="px-3 py-2">
                      <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${style.badge}`}>{g.label}</span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">{g.n}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {g.golden ? `${g.golden.seal}%` : "--"}
                    </td>
                    <td className={cn(
                      "px-3 py-2 text-right font-mono font-semibold tabular-nums",
                      g.golden ? "text-rise" : "text-muted-foreground",
                    )}>
                      {g.golden ? `${g.golden.win}%` : "不适用"}
                    </td>
                    <td className="px-3 py-2 leading-5 text-muted-foreground">{g.note}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="mb-2 text-xs font-semibold text-foreground">
          ② {rules.streak_hold.second_night.title}
        </div>
        <div className="mb-2 rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-xs leading-5 text-muted-foreground">
          {rules.streak_hold.second_night.structure}
        </div>
        <div className="mb-3 flex items-baseline gap-2 rounded-md border border-amber-500/25 bg-amber-500/5 px-3 py-2">
          <span className="shrink-0 text-xs font-semibold text-amber-600 dark:text-amber-400">核心判别</span>
          <span className="text-xs leading-5 text-muted-foreground">{rules.streak_hold.second_night.key_rule}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-xs">
            <thead className="border-b bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">组</th>
                <th className="px-3 py-2 text-right font-medium">2板在手</th>
                <th className="px-3 py-2 text-right font-medium">2进3率</th>
                <th className="px-3 py-2 text-left font-medium">默认动作</th>
                <th className="px-3 py-2 text-left font-medium">继续拿信号(接力率/增量)</th>
                <th className="px-3 py-2 text-left font-medium">落袋信号</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rules.streak_hold.second_night.groups.map((g) => {
                const style = GROUP_STYLES[g.group === "yang2" ? "yang2a" : g.group];
                return (
                  <tr key={g.group} className="align-top">
                    <td className="px-3 py-2.5">
                      <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${style.badge}`}>{g.label}</span>
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono tabular-nums">{g.n}</td>
                    <td className="px-3 py-2.5 text-right font-mono tabular-nums">{g.relay}%</td>
                    <td className="px-3 py-2.5 font-medium">{g.default}</td>
                    <td className="px-3 py-2.5">
                      {g.holds.length ? (
                        <ul className="space-y-1">
                          {g.holds.map((h) => (
                            <li key={h.cond} className="font-mono tabular-nums text-rise">
                              {h.cond}　{h.relay}% / +{h.edge.toFixed(1)}%
                              <span className="font-normal text-muted-foreground"> (n={h.n})</span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <span className="text-muted-foreground">无稳定信号</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 leading-5 text-muted-foreground">
                      <ul className="space-y-1">
                        {g.runs.map((r) => <li key={r}>{r}</li>)}
                      </ul>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{rules.streak_hold.second_night.small_sample}</p>
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
          与本产品的 N型补涨打板(断板后再启动首板板上买、板留断走)不是同一打法,两套条件互不通用。
        </p>
      </section>
    </div>
  );
}
