import { useQuery } from "@tanstack/react-query";

import { fetchFbbRules } from "@/api/fanbao";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { CopyThsConditionsButton } from "@/features/qianlong/CopyThsConditionsButton";

const GROUP_STYLES: Record<string, { badge: string; label: string }> = {
  pool: { badge: "bg-primary/15 text-primary", label: "池" },
  S1: { badge: "bg-rise/15 text-rise", label: "S1" },
  S2: { badge: "bg-amber-500/15 text-amber-500", label: "S2" },
  S3: { badge: "bg-primary/15 text-primary", label: "S3" },
  O1: { badge: "bg-violet-500/15 text-violet-500", label: "O1" },
  O2: { badge: "bg-orange-500/15 text-orange-500", label: "O2" },
  dead: { badge: "bg-fall/15 text-fall", label: "死格" },
  buy: { badge: "bg-rise/15 text-rise", label: "买" },
  sell: { badge: "bg-amber-500/15 text-amber-500", label: "卖" },
};

const POINT_ORDER = ["S1", "S2", "S3", "O1", "O2"] as const;

/** 规则说明:渲染自后端 /rules 契约(单一事实源,前端不维护副本)。 */
export function FbbGuideView() {
  const query = useQuery({
    queryKey: ["fbbRules"],
    queryFn: fetchFbbRules,
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
          <span className="text-sm font-semibold">断板反包 · 规则定稿 {rules.rules_version}</span>
          <span className="text-xs text-muted-foreground">
            六组×五方案点 全市场验证(2023-01 ~ 2026-09,7978笔事件);每条件都有分年证据,见研究文档
          </span>
          <span className="ml-auto flex items-center gap-2">
            {POINT_ORDER.map((pk) => (
              <CopyThsConditionsButton
                key={pk}
                conditions={rules.ths_pool_conditions[pk]}
                label={`复制${pk}条件`}
              />
            ))}
          </span>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">一句话</div>
        <p className="text-sm leading-6 text-muted-foreground">
          连板断了一两天后又涨停的票,买三种「洗过盘」的:
          <span className="font-medium text-foreground">2板是砸出大阴线急杀过的(低开直接砸最干净)</span>、
          <span className="font-medium text-foreground">4板是高开出完货砸下来的</span>、
          <span className="font-medium text-foreground">5板以上是跌不动的(筹码全锁死)</span>。
          碰到涨停价就买;当天没封住收盘就卖,封住了拿到不涨停那天。
          其他的别碰——不挑就买是亏的。
        </p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <div className="rounded-md bg-rise/10 px-3 py-2">
            <div className="text-xs font-semibold text-rise">S1 · 2板低开急杀</div>
            <div className="mt-0.5 text-xs text-muted-foreground">断板总共跌8~15%,只有1根阴线,那天低开或平开直接砸</div>
          </div>
          <div className="rounded-md bg-amber-500/10 px-3 py-2">
            <div className="text-xs font-semibold text-amber-600">S2 · 4板高开洗透</div>
            <div className="mt-0.5 text-xs text-muted-foreground">断1天,昨天高开2%以上然后走低收阴——货出干净了</div>
          </div>
          <div className="rounded-md bg-primary/10 px-3 py-2">
            <div className="text-xs font-semibold text-primary">S3 · 5板+扛住</div>
            <div className="mt-0.5 text-xs text-muted-foreground">断1天,昨天没跌——大资金没跑,反包直接走大肉</div>
          </div>
        </div>
        <p className="mt-2 rounded-md bg-amber-500/10 px-3 py-2 text-xs text-amber-600">
          ⚠️ 两个容易搞混的「阴」:分组看的阴阳是<span className="font-semibold">昨天收盘比前天低不高</span>;
          阴线数看的是<span className="font-semibold">那根K线收盘比开盘低(真阴线)</span>。
          两把尺子长得像但不是一回事,别混着用。
        </p>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">同花顺动态板块条件(盘前池 × 五方案点)</div>
        <div className="space-y-3">
          {POINT_ORDER.map((pk) => (
            <div key={pk}>
              <div className="mb-1 flex items-center gap-2 text-xs">
                <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${GROUP_STYLES[pk].badge}`}>
                  {rules.point_labels[pk]}
                  {rules.point_levels[pk] === "S" ? " · 出手级" : " · 观察级"}
                </span>
                <span className="text-muted-foreground">{rules.point_desc[pk]}</span>
                <CopyThsConditionsButton
                  conditions={rules.ths_pool_conditions[pk]}
                  label="复制"
                  className="h-6 px-2"
                />
              </div>
              <pre className="whitespace-pre-wrap rounded-md bg-muted/40 p-3 font-mono text-xs leading-6">
                {rules.ths_pool_conditions[pk]}
              </pre>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{rules.ths_pool_note}</p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
          {rules.intraday_playbook.map((line) => <li key={line}>{line}</li>)}
        </ol>
      </section>

      <section className="rounded-lg border p-4" aria-label="规则逐条">
        <div className="mb-2 text-sm font-semibold">规则逐条(含证据)</div>
        <div className="space-y-4">
          {rules.rules.map((g) => {
            const style = GROUP_STYLES[g.group] ?? GROUP_STYLES.pool;
            return (
              <div key={g.title}>
                <div className="mb-1 flex items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${style.badge}`}>
                    {style.label}
                  </span>
                  <span className="text-xs font-medium">{g.title}</span>
                </div>
                <ul className="space-y-1.5">
                  {g.items.map((it) => (
                    <li key={it.no} className="text-xs leading-5">
                      <span className="font-mono text-muted-foreground">{it.no}.</span> {it.rule}
                      <span className="block pl-5 text-muted-foreground">依据:{it.evidence}</span>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </section>

      <section className="rounded-lg border p-4" aria-label="留档未收编">
        <div className="mb-2 text-sm font-semibold">留档未收编(防翻案)</div>
        <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
          {rules.falsified_rules.map((line) => <li key={line}>{line}</li>)}
        </ul>
      </section>

      <section className="rounded-lg border p-4" aria-label="风险声明">
        <div className="mb-2 text-sm font-semibold">风险声明</div>
        <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
          {rules.risk_notes.map((line) => <li key={line}>{line}</li>)}
        </ul>
      </section>

      <section className="rounded-lg border p-4" aria-label="验收锚点">
        <div className="mb-2 text-sm font-semibold">验收锚点与案例门禁</div>
        <div className="grid gap-3 lg:grid-cols-2">
          <div>
            <div className="mb-1 text-xs text-muted-foreground">研究定稿数字(回测对账基准)</div>
            <ul className="space-y-0.5 font-mono text-xs tabular-nums text-muted-foreground">
              {Object.entries(rules.anchors).map(([k, v]) => (
                <li key={k}>
                  {k}: n={v.n} / 持有{v.bw_pct > 0 ? "+" : ""}{v.bw_pct} / 胜率{(v.bw_win * 100).toFixed(0)}%
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="mb-1 text-xs text-muted-foreground">具名案例(回测页有逐条对账结果)</div>
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              {rules.case_gates.map((c) => (
                <li key={`${c.name}-${c.date}`}>
                  {c.name} {c.date} — {c.note}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}
