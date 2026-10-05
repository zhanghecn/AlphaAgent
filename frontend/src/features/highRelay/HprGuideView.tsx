import { Fragment } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchHprRules } from "@/api/highRelay";
import { CheatTableRow } from "@/features/highRelay/CheatTableRow";
import { PoseCaseChart } from "@/features/highRelay/PoseCaseChart";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { CopyThsConditionsButton } from "@/components/shared/CopyThsConditionsButton";

const GROUP_STYLES: Record<string, { badge: string; label: string }> = {
  pool: { badge: "bg-primary/15 text-primary", label: "池" },
  A: { badge: "bg-rise/15 text-rise", label: "阳地基" },
  A1: { badge: "bg-rise/15 text-rise", label: "A1" },
  A2: { badge: "bg-teal-500/15 text-teal-500", label: "A2" },
  A3: { badge: "bg-rose-500/15 text-rose-500", label: "A3" },
  B: { badge: "bg-amber-500/15 text-amber-500", label: "阴地基" },
  B1: { badge: "bg-amber-500/15 text-amber-500", label: "B1" },
  B2: { badge: "bg-yellow-500/15 text-yellow-500", label: "B2" },
  B3: { badge: "bg-orange-500/15 text-orange-500", label: "B3" },
  C: { badge: "bg-emerald-500/15 text-emerald-500", label: "中性·阴阳都打" },
  C1: { badge: "bg-emerald-500/15 text-emerald-500", label: "C1" },
  C2: { badge: "bg-primary/15 text-primary", label: "C2" },
  avoid: { badge: "bg-fall/15 text-fall", label: "回避" },
  time: { badge: "bg-primary/15 text-primary", label: "时间" },
  buy: { badge: "bg-rise/15 text-rise", label: "买" },
  sell: { badge: "bg-amber-500/15 text-amber-500", label: "卖" },
};

// 口诀卡顺序(主人定):阴阳分组,组内按二板开盘从低到高;与后端 RULES A/B/E 组序一致
const POINT_ORDER = ["A1", "A2", "A3", "B2", "B1", "B3", "C1", "C2"] as const;

/** 规则说明:渲染自后端 /rules 契约(单一事实源,前端不维护副本;
 * 速查表也随后端 cheat_rows 下发,答题讲解卡取同一份命中行)。 */
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
  // 七条口诀卡数据:A/B/C/E 组 items 按序 flatten,与 POINT_ORDER 一一对应
  const schemeCards = rules.rules
    .filter((g) => g.group === "A" || g.group === "B" || g.group === "C")
    .flatMap((g) => g.items.map((it) => ({ ...it, group: g.group })));
  const mechanicGroups = rules.rules.filter(
    (g) => g.group !== "A" && g.group !== "B" && g.group !== "C",
  );
  return (
    <div className="space-y-4">
      <section className="rounded-lg border px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="text-sm font-semibold">高位接力 · 规则定稿 {rules.rules_version}</span>
          <span className="text-xs text-muted-foreground">
            打板口诀卡七条(hpr-v6.10:A=阳B=阴C=中性,字母语义跨板位统一)全市场验证(2023-01 ~ 2026-09);见 量化因子研究/高位接力/打板口诀卡.md
          </span>
        </div>
        <div className="mt-2 border-t pt-2 text-xs leading-5 text-muted-foreground">
          术语：<span className="font-medium text-foreground">二接三</span>＝昨天已经 2 连板、今天接第 3 板
          （<span className="font-medium text-foreground">打3板</span>，买点看一板/二板的形态与换手）；
          <span className="font-medium text-foreground">三接四</span>＝昨天已经 3 连板、今天接第 4 板
          （<span className="font-medium text-foreground">打4板</span>，买点看三板或二板的形态/换手）。
          <span className="font-medium text-foreground">阴/阳地基</span>＝首板前一天 K 线收阴/收阳——
          同一条口诀放在另一个地基常常全灭，所以字母 A/B 就是这么分的。
        </div>
      </section>

      <section className="rounded-lg border p-4">
        <div className="mb-1 text-sm font-semibold">
          一句话：昨天恰好 2/3 连板的票，今天冲下一板——只对这七句口诀出手
          <span className="ml-2 font-mono text-xs font-normal text-primary">
            合计 150笔·E3胜77%·均+10.6·月均3.3笔
          </span>
        </div>
        <div className="mb-2 text-xs text-muted-foreground">
          用法：看地基阴阳 → 看板位（打3板看二板开/打4板各条看自己的判别腿）→ 对照今天开（与 contracts.RULES 同步）；
          各条成绩见速查表「成绩」列（E3 口径=产品卖出纪律）
        </div>
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="py-1.5 pr-3 font-medium">口诀</th>
              <th className="py-1.5 pr-3 font-medium">组</th>
              <th className="py-1.5 pr-3 font-medium">一板</th>
              <th className="py-1.5 pr-3 font-medium">二板</th>
              <th className="py-1.5 pr-3 font-medium">三板</th>
              <th className="py-1.5 pr-3 font-medium">今天开</th>
              <th className="py-1.5 pr-3 font-medium">地基日</th>
              <th className="py-1.5 font-medium">成绩(E3)</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rules.cheat_rows.map((r, i) => (
              <Fragment key={r.name}>
                {i === 0 || r.yang.replace(/^.*·/, "") !== rules.cheat_rows[i - 1].yang.replace(/^.*·/, "") ? (
                  <tr className="border-b-2 border-muted/40">
                    <td className="py-1 pr-3 text-[11px] font-semibold text-muted-foreground" colSpan={8}>
                      {r.yang.replace(/^.*·/, "") === "打3板" ? "打3板（二接三）" : "打4板（三接四）"}
                    </td>
                  </tr>
                ) : null}
                <CheatTableRow row={r} />
              </Fragment>
            ))}
            <tr className="border-t-2 border-muted/60">
              <td className="py-1.5 pr-3 font-semibold" colSpan={5}>合计(八条·去重)</td>
              <td className="py-1.5 pr-3" colSpan={2} />
              <td className="py-1.5 font-mono text-[11px] font-semibold">150笔·胜77%·均+10.6</td>
            </tr>
          </tbody>
        </table>
        <p className="mt-3 text-[11px] leading-5 text-muted-foreground">
          换手心法：二接三看二板换手（阳锁阴活），三接四看三板换手，一板换手永远不用看；
          盘中首次触涨停价打（低吸类低开直接买），开盘≥9.5%顶格不命中；
          炸板次日走（T+1，一字跌停顺延），封住拿到断板（15日兜底）。
          合计150笔 月均3.3笔（hpr-v6.11）；不挑就买是亏的（对照 41%/-1.5），其余一概不碰。
        </p>
      </section>

      <section className="rounded-lg border p-4" aria-label="地基姿态图解">
        <div className="mb-1 text-sm font-semibold">
          地基姿态图解（捡尸 B2 / 贴零温开 B3 的附加腿，v6.10）
        </div>
        <div className="mb-2 text-xs text-muted-foreground">
          看首板前一天那根K线（箭头「地基日」）和 20日线（蓝线）的位置——
          站线上、骑线的，接；贴线的、掉线下的，不接。四张图=真实特征票K线（地基日前12根~买入日）。
        </div>
        {rules.pose_cases && rules.pose_cases.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2">
            {rules.pose_cases.map((c) => (
              <div key={`${c.name}-${c.date}`} className="rounded-md border p-2">
                <div className="mb-1 flex items-baseline gap-2">
                  <span className="text-xs font-semibold">
                    {c.pose}{c.pose === "站线上" || c.pose === "骑线" ? "（✅接）" : "（❌不接）"}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {c.name} {c.date.slice(2)} {c.e3 != null ? `${c.e3 > 0 ? "+" : ""}${c.e3.toFixed(1)}%` : ""}
                  </span>
                </div>
                <PoseCaseChart c={c} />
                <p className="mt-1 text-[11px] leading-4 text-muted-foreground">{c.note}</p>
              </div>
            ))}
          </div>
        ) : (
          <pre className="overflow-x-auto rounded-md bg-muted/40 p-3 font-mono text-xs leading-5">{`   ①站线上(有人扛)    ②骑线(有人争)     ③贴线(死水)      ④掉线下(没人救)
                          ┃
      ┃                   ┃                ┃
      ┃                   ┃                ┃
      ┃                   ┃                ┃
 ═════╧═══ MA20     ═════╪═══ MA20    ═════╧═══ MA20   ═══════════ MA20
                          ┃                                 ┃
                          ┃                                 ┃
 最低价离线≥2%        线拦腰穿过K线      最低价贴线<2%      最高价也在线下
      ✅接                ✅接              ❌不接             ❌不接`}</pre>
        )}
        <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
          数字口径：最低价距20日线≥2%＝站线上；最低价在线下且最高价在线上＝骑线；
          最低价在线上但离线&lt;2%＝贴线；最高价也在线下＝掉线下。
        </p>
      </section>

      <section className="rounded-lg border p-4" aria-label="七条口诀卡">
        <div className="mb-2 text-sm font-semibold">七条口诀(全文 + 成绩 + 主力怎么想)</div>
        <div className="grid gap-3 lg:grid-cols-2">
          {schemeCards.map((it, i) => {
            const pk = POINT_ORDER[i] ?? String(i);
            const style = GROUP_STYLES[pk] ?? GROUP_STYLES.pool;
            const ruleText = it.rule.replace(/^[^:]+:\s*/, "");
            return (
              <div key={pk} className="rounded-md border px-3 py-2.5">
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${style.badge}`}>
                    {pk}
                  </span>
                  <span className="text-sm font-semibold">
                    {rules.point_names?.[pk] ?? pk}
                  </span>
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium text-foreground">
                    {rules.point_boards?.[pk]}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {GROUP_STYLES[it.group]?.label}
                    {rules.point_boards?.[pk] === "打4板" ? "·三接四" : "·二接三"}
                  </span>
                  <span className="ml-1 font-mono text-[11px] text-primary">
                    {rules.point_stats?.[pk]}
                  </span>
                  <span className="ml-auto">
                    <CopyThsConditionsButton
                      conditions={rules.ths_pool_conditions[pk]}
                      label="复制条件"
                      className="h-6 px-2"
                    />
                  </span>
                </div>
                <p className="whitespace-pre-line font-mono text-sm leading-6 text-foreground">{ruleText}</p>
                <div className="mt-1 text-xs leading-5">
                  <span className="text-muted-foreground">成绩:</span>
                  {it.evidence.split("\n").map((ln, j) => (
                    <div key={j} className={j === 0 ? "font-medium text-foreground" : "pl-3 text-muted-foreground"}>
                      {ln}
                    </div>
                  ))}
                </div>
                {rules.point_psycho?.[pk] ? (
                  <p className="mt-1 whitespace-pre-line text-xs leading-5 text-muted-foreground">
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
                    <li key={it.no} className="whitespace-pre-line text-xs leading-5">
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
