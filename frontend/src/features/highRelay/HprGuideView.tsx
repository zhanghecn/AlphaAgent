import { useQuery } from "@tanstack/react-query";

import { fetchHprRules } from "@/api/highRelay";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { CopyThsConditionsButton } from "@/features/qianlong/CopyThsConditionsButton";

const GROUP_STYLES: Record<string, { badge: string; label: string }> = {
  pool: { badge: "bg-primary/15 text-primary", label: "池" },
  A: { badge: "bg-rise/15 text-rise", label: "二接三阳" },
  A1: { badge: "bg-rise/15 text-rise", label: "A1" },
  A2: { badge: "bg-teal-500/15 text-teal-500", label: "A2" },
  B: { badge: "bg-amber-500/15 text-amber-500", label: "二接三阴" },
  B1: { badge: "bg-amber-500/15 text-amber-500", label: "B1" },
  B2: { badge: "bg-yellow-500/15 text-yellow-500", label: "B2" },
  B3: { badge: "bg-emerald-500/15 text-emerald-500", label: "B3" },
  B4: { badge: "bg-orange-500/15 text-orange-500", label: "B4" },
  E: { badge: "bg-primary/15 text-primary", label: "三接四" },
  E1: { badge: "bg-primary/15 text-primary", label: "E1" },
  E2: { badge: "bg-sky-500/15 text-sky-500", label: "E2" },
  E3: { badge: "bg-fuchsia-500/15 text-fuchsia-500", label: "E3" },
  avoid: { badge: "bg-fall/15 text-fall", label: "回避" },
  time: { badge: "bg-primary/15 text-primary", label: "时间" },
  buy: { badge: "bg-rise/15 text-rise", label: "买" },
  sell: { badge: "bg-amber-500/15 text-amber-500", label: "卖" },
};

const POINT_ORDER = ["A1", "A2", "B1", "B2", "B3", "B4", "E1", "E2", "E3"] as const;

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
  // 九条口诀卡数据:A/B/E 组 items 按序 flatten,与 POINT_ORDER 一一对应
  const schemeCards = rules.rules
    .filter((g) => g.group === "A" || g.group === "B" || g.group === "E")
    .flatMap((g) => g.items.map((it) => ({ ...it, group: g.group })));
  const mechanicGroups = rules.rules.filter(
    (g) => g.group !== "A" && g.group !== "B" && g.group !== "E",
  );
  return (
    <div className="space-y-4">
      <section className="rounded-lg border px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="text-sm font-semibold">高位接力 · 规则定稿 {rules.rules_version}</span>
          <span className="text-xs text-muted-foreground">
            打板口诀卡九条(hpr-v4.0 合体定稿)全市场验证(2023-03 ~ 2026-09);见 量化因子研究/高位接力/打板口诀卡.md
          </span>
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-2 text-sm font-semibold">一句话</div>
        <p className="text-sm leading-6 text-muted-foreground">
          昨天恰好 2 连板或 3 连板的票,今天冲第 N+1 板;九句口诀才出手——
          速查树只问一句「二板开在哪个档」:贴零(&lt;1)→阳打今开6~9.5锁换手(双平贴零),
          一字(≥9.5)→阳打今开7~8.5(一字转强),高开(3~7)→等今天弱开&lt;3阴阳都打(冒泡转弱),
          强开(7~8.5)→阴打今开6~9.5(冒泡转强)或温开3~5强强链(强转弱),全低链→今天也低开小仓(三低);
          打四板不用记形态:三板换手10~20+今开5~9.5直接打(四板便捷,不分阴阳),
          三板高开5~7等今天低开低吸(高开低吸),二板贴零今天温开3~6(贴零温开);
          换手心法:二接三看二板换手(阳锁阴活),三接四看三板换手,一板换手永远不用看;
          触板即打(开盘≥9.5%顶格不命中);炸板当天收盘走,封住拿到断板(15日兜底)。
          合计164笔 胜71% 均+8.13,月均3.8笔;不挑就买是亏的,其余一概不碰。
        </p>
      </section>

      <section className="rounded-lg border p-4" aria-label="九条口诀卡">
        <div className="mb-2 text-sm font-semibold">九条口诀(全文 + 成绩 + 主力怎么想)</div>
        <div className="grid gap-3 lg:grid-cols-2">
          {schemeCards.map((it, i) => {
            const pk = POINT_ORDER[i] ?? String(i);
            const style = GROUP_STYLES[pk] ?? GROUP_STYLES.pool;
            const ruleText = it.rule.replace(/^[^:]+:/, "");
            return (
              <div key={pk} className="rounded-md border px-3 py-2.5">
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${style.badge}`}>
                    {pk}
                  </span>
                  <span className="text-sm font-semibold">
                    {rules.point_names?.[pk] ?? pk}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {GROUP_STYLES[it.group]?.label}
                  </span>
                  <span className="ml-auto">
                    <CopyThsConditionsButton
                      conditions={rules.ths_pool_conditions[pk]}
                      label="复制条件"
                      className="h-6 px-2"
                    />
                  </span>
                </div>
                <p className="text-xs leading-5 text-foreground">{ruleText}</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  成绩:{it.evidence}
                </p>
                {rules.point_psycho?.[pk] ? (
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    主力怎么想:{rules.point_psycho[pk]}
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      </section>

      <section className="rounded-lg border p-4" aria-label="机制逐条">
        <div className="mb-2 text-sm font-semibold">机制逐条(池/回避/买/卖,含证据)</div>
        <div className="space-y-4">
          {mechanicGroups.map((g) => {
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

      <section className="rounded-lg border p-4">
        <details>
          <summary className="cursor-pointer text-sm font-semibold">
            附:同花顺动态板块条件串(盘前手工筛选备用,点击展开)
          </summary>
          <div className="mt-3 space-y-3">
            {POINT_ORDER.map((pk) => (
              <div key={pk}>
                <div className="mb-1 flex items-center gap-2 text-xs">
                  <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${GROUP_STYLES[pk].badge}`}>
                    {rules.point_names?.[pk] ?? rules.point_labels[pk]}
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
        </details>
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
