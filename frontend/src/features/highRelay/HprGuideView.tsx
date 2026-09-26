import { useQuery } from "@tanstack/react-query";

import { fetchHprRules } from "@/api/highRelay";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { CopyThsConditionsButton } from "@/features/qianlong/CopyThsConditionsButton";

const GROUP_STYLES: Record<string, { badge: string; label: string }> = {
  pool: { badge: "bg-primary/15 text-primary", label: "池" },
  A1: { badge: "bg-rise/15 text-rise", label: "A1" },
  A2: { badge: "bg-emerald-500/15 text-emerald-500", label: "A2" },
  A3: { badge: "bg-teal-500/15 text-teal-500", label: "A3" },
  B1: { badge: "bg-amber-500/15 text-amber-500", label: "B1" },
  B2: { badge: "bg-yellow-500/15 text-yellow-500", label: "B2" },
  C1: { badge: "bg-primary/15 text-primary", label: "C1" },
  C2: { badge: "bg-sky-500/15 text-sky-500", label: "C2" },
  D1: { badge: "bg-orange-500/15 text-orange-500", label: "D1" },
  D2: { badge: "bg-violet-500/15 text-violet-500", label: "D2" },
  D3: { badge: "bg-fuchsia-500/15 text-fuchsia-500", label: "D3" },
  avoid: { badge: "bg-fall/15 text-fall", label: "回避" },
  time: { badge: "bg-primary/15 text-primary", label: "时间" },
  buy: { badge: "bg-rise/15 text-rise", label: "买" },
  sell: { badge: "bg-amber-500/15 text-amber-500", label: "卖" },
};

const POINT_ORDER = ["A1", "A2", "A3", "B1", "B2", "C1", "C2", "D1", "D2", "D3"] as const;

/** 规则说明:渲染自后端 /rules 契约(单一事实源,前端不维护副本)。 */
export function HprGuideView() {
  const query = useQuery({
    queryKey: ["hprRules"],
    queryFn: fetchHprRules,
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
          <span className="text-sm font-semibold">高位接力 · 规则定稿 {rules.rules_version}</span>
          <span className="text-xs text-muted-foreground">
            连板链十方案(A1~D3)全市场验证(2023-03 ~ 2026-09);每条件都有分年证据,见研究文档
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
          昨天恰好 2 连板或 3 连板的票,今天冲第 N+1 板时按涨停价打板买入;
          十种链式形态才出手:A1双低贴零、A2平启贴零、A3一字急锁缓启(二接三阳),
          B1强强活跃温开、B2低洗走强(二接三阴),C1放量高板低吸、C2双一字确认(三接四阳),
          D1低板转强、D2低洗平推、D3贴零温开(三接四阴);
          链条件收盘后可知,今天开档竞价定型对照,触板即打(开盘≥9.5%顶格不命中);
          炸板当天收盘走,封住拿到断板(15日兜底)。不挑就买是亏的(对照 -1.33),其余一概不碰。
        </p>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">同花顺动态板块条件(盘前池 × 链式十方案)</div>
        <div className="space-y-3">
          {POINT_ORDER.map((pk) => (
            <div key={pk}>
              <div className="mb-1 flex items-center gap-2 text-xs">
                <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${GROUP_STYLES[pk].badge}`}>
                  {rules.point_labels[pk]}
                  
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
