import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchHprKoujueCurrent, fetchHprRules, type HprKoujueHealth } from "@/api/highRelay";
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
  C3: { badge: "bg-primary/15 text-primary", label: "C3" },
  avoid: { badge: "bg-fall/15 text-fall", label: "回避" },
  time: { badge: "bg-primary/15 text-primary", label: "时间" },
  buy: { badge: "bg-rise/15 text-rise", label: "买" },
  sell: { badge: "bg-amber-500/15 text-amber-500", label: "卖" },
};

// 口诀卡顺序(主人定):阴阳分组,组内按二板开盘从低到高;与后端 RULES A/B/E 组序一致
// v7.2 补 C3:v6.11 拆C3后 RULES 口诀卡组增至 9 项,原 8 键导致第 9 张卡徽章错显示"8"
const POINT_ORDER = ["A1", "A2", "A3", "B2", "B1", "B3", "C1", "C2", "C3"] as const;

/** 规则说明:渲染自后端 /rules 契约(单一事实源,前端不维护副本;
 * 速查表也随后端 cheat_rows 下发,答题讲解卡取同一份命中行)。 */
export function HprGuideView() {
  const query = useQuery({
    queryKey: ["hprRules"],
    queryFn: fetchHprRules,
    staleTime: 300_000,
  });
  // 动态口诀组(v7.0):用户点「获取最新口诀」才拉取——数字动态计算,1分钟内不重复请求
  const [koujueOpen, setKoujueOpen] = useState(false);
  const koujue = useQuery({
    queryKey: ["hprKoujue"],
    queryFn: fetchHprKoujueCurrent,
    enabled: koujueOpen,
    staleTime: 60_000,
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
            强市组八条(A1~C3)+ 弱市组五条(K 系)——按行情自动切换,当前启用见下方「动态口诀组」
          </span>
        </div>
        <div className="mt-2 border-t pt-2 text-xs leading-5 text-muted-foreground">
          术语：<span className="font-medium text-foreground">二接三</span>＝昨 2 连板今天接第 3 板（看一板/二板）；
          <span className="font-medium text-foreground">三接四</span>＝昨 3 连板今天接第 4 板（看三板/二板）；
          <span className="font-medium text-foreground">阴/阳地基</span>＝首板前一日收阴/收阳——同诀换地基常全灭，A/B 由此分。
        </div>
      </section>

      <section className="rounded-lg border border-primary/40 p-4" aria-label="获取最新口诀">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <span className="text-sm font-semibold">动态口诀组</span>
          <span className="text-xs text-muted-foreground">
            近一年哪组口诀赚得多，就用哪组（每月末看一次；胜率收益动态计算）
          </span>
          <button
            type="button"
            onClick={() => { setKoujueOpen(true); void koujue.refetch(); }}
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
          >
            获取最新口诀
          </button>
          {koujue.data ? (
            <span className="font-mono text-[11px] text-muted-foreground">数据至 {koujue.data.asof}</span>
          ) : null}
        </div>
        {koujueOpen && koujue.isLoading ? <LoadingState rows={3} /> : null}
        {koujue.isError ? (
          <ErrorState message="动态口诀组暂时不可用" onRetry={() => void koujue.refetch()} />
        ) : null}
        {koujue.data?.status === "unavailable" ? (
          <p className="mt-2 text-xs text-muted-foreground">{koujue.data.reason ?? "回测物化未完成"}</p>
        ) : null}
        {koujue.data?.status === "ok" ? (
          <div className="mt-3 space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs text-muted-foreground">当前启用</span>
              <span className={`rounded px-2 py-1 text-sm font-bold ${
                koujue.data.current_group === "strong"
                  ? "bg-primary/15 text-primary"
                  : koujue.data.current_group === "weak"
                    ? "bg-amber-500/15 text-amber-500"
                    : "bg-muted text-foreground"
              }`}>
                {koujue.data.current_group === "strong" ? "强市组（A1~C3 八条）"
                  : koujue.data.current_group === "weak" ? "弱市组（K系五条）" : "双开"}
              </span>
              {koujue.data.switch_history.length > 0 ? (
                <span className="font-mono text-[11px] text-muted-foreground">
                  切换历史：{koujue.data.switch_history.map((s) => `${s.month.slice(2)} ${s.from}→${s.to}`).join("；")}
                </span>
              ) : null}
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              {(["weak", "strong"] as const).map((g) => {
                const gs = koujue.data!.groups[g];
                const active = koujue.data!.current_group === g;
                return (
                  <div key={g} className={`rounded-md border px-3 py-2 ${active ? "border-primary/60 bg-primary/5" : "border-muted"}`}>
                    <div className="flex items-baseline gap-2">
                      <span className="text-xs font-semibold">{gs.label}</span>
                      {active ? <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">当前</span> : null}
                      <span className="ml-auto font-mono text-xs tabular-nums">
                        近{koujue.data!.window_months}月 {gs.n}笔
                        {gs.avg != null ? <>·均{gs.avg > 0 ? "+" : ""}{gs.avg}</> : null}
                        {gs.win != null ? <>·胜{Math.round(gs.win * 100)}%</> : null}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
            <KoujueHealthList health={koujue.data.health} />
            <p className="text-[11px] leading-5 text-muted-foreground">{koujue.data.caliber}</p>
          </div>
        ) : null}
      </section>

      {/* v7.13 速查表合一(主人「精简」指令): 原「强市速查表/弱市速查表/动态组current_rows」
          三张同构表(31行,70%重复)合并为一张 13 条总表——组标题行分区, 板位看「组」列;
          动态成绩(近12月/近2年)由上方动态口诀组卡片与口诀近况承担, 表内只放定型成绩 */}
      <section className="rounded-lg border p-4" aria-label="口诀速查表">
        <div className="mb-1 text-sm font-semibold">
          口诀速查表 · 全部 13 条
          <span className="ml-2 font-mono text-xs font-normal text-primary">强市 150笔·胜77%·均+10.6</span>
          <span className="ml-1.5 font-mono text-xs font-normal text-violet-500">弱市 40笔·胜78%·均+13.2</span>
        </div>
        <div className="mb-2 text-xs text-muted-foreground">
          昨天恰好 2/3 连板、今天冲下一板——两组口诀按行情自动切换（看上方「动态口诀组」）；
          用法：看地基阴阳 → 看板位 → 对照今天开。
        </div>
        {/* v7.10 三板换手池分流总纲(阴阳分流版):第一判据=地基K线阴体阳体(K2/K5 要阴、
            K4 要阳),第二判据=今天开;阴阳各走各路(主人 2026-10-07 撞金种子酒判定冲突后定稿) */}
        <div className="mb-2 rounded-md bg-violet-500/5 px-3 py-2 text-xs leading-5 text-violet-500/90 ring-1 ring-violet-500/20">
          三板换手池的票，<span className="font-semibold">第一眼看地基K线阴阳</span>——
          阴K走 K2/K5，阳K走 K4，一票只落一条路：
          阴地基：今开 <span className="font-mono">6~9.5</span> 强开查 K2(三换10~15 × 地基要干净)或 K5(二板贴零 × 前波=0)；
          阳地基：今开 <span className="font-mono">0~3</span> 弱开查 K4(三换12~20 × 一板要放量)，今开 <span className="font-mono">3~6</span> 温开不碰(毒)。
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
            <tr className="border-b-2 border-muted/40">
              <td className="py-1 pr-3 text-[11px] font-semibold text-muted-foreground" colSpan={8}>
                强市组（A1~C3 八条，2023-26 定型验证）
              </td>
            </tr>
            {rules.cheat_rows.map((r) => (
              <CheatTableRow key={r.name} row={r} />
            ))}
            <tr className="border-b-2 border-muted/40">
              <td className="py-1 pr-3 text-[11px] font-semibold text-violet-500/80" colSpan={8}>
                弱市组（K 系五条，2020-22 弱市时代定型；2023 起参考成绩见回测页）
              </td>
            </tr>
            {rules.weak_cheat_rows.map((r) => (
              <CheatTableRow key={r.name} row={r} />
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-[11px] leading-5 text-muted-foreground">
          换手心法：二接三看二板换手（阳锁阴活），三接四先看三板换手，一板换手永远不用看；
          盘中首次触涨停价打（低吸类低开直接买），开盘≥9.5%顶格不命中；
          炸板次日走（T+1，一字跌停顺延），封住拿到断板（15日兜底）。
          不挑就买是亏的（强市对照 41%/-1.5、弱市同期 1934 笔均-1.34），其余一概不碰。
        </p>
      </section>

      <section className="rounded-lg border p-4" aria-label="地基姿态图解">
        <div className="mb-1 text-sm font-semibold">
          地基姿态图解（捡尸 B2 / 贴零温开 B3 的附加腿，v6.10）
        </div>
        <div className="mb-2 text-xs text-muted-foreground">
          看首板前一天那根K线（箭头「地基日」）与 20 日线的位置——
          站线上（最低价离线≥2%）、骑线（线穿过K线）的接；贴线（在线上&lt;2%）、掉线下（最高价也在线下）的不接。
          四张图＝真实特征票K线（地基日前12根~买入日）。
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

      </section>

      {/* v7.13 低频区折叠(主人「精简」指令): 口诀卡全文/机制逐条/留档/锚点默认收起,
          日常速查只看上方一张总表 */}
      <section className="rounded-lg border p-4" aria-label="强市组口诀卡">
        <details>
          <summary className="cursor-pointer text-sm font-semibold">
            口诀卡全文 · 八条（口诀原文 + 成绩 + 主力怎么想）
          </summary>
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
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
        </details>
      </section>

      <section className="rounded-lg border p-4" aria-label="机制逐条">
        <details>
          <summary className="cursor-pointer text-sm font-semibold">
            机制逐条（池 / 回避 / 买 / 卖，含证据）
          </summary>
        <div className="mt-3 space-y-4">
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
        </details>
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
        <details>
          <summary className="cursor-pointer text-sm font-semibold">留档未收编（防翻案）</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
            {rules.falsified_rules.map((line) => <li key={line}>{line}</li>)}
          </ul>
        </details>
      </section>

      <section className="rounded-lg border p-4" aria-label="风险声明">
        <div className="mb-2 text-sm font-semibold">风险声明</div>
        <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
          {rules.risk_notes.map((line) => <li key={line}>{line}</li>)}
        </ul>
      </section>

      <section className="rounded-lg border p-4" aria-label="验收锚点">
        <details>
          <summary className="cursor-pointer text-sm font-semibold">验收锚点与案例门禁（研究核对用）</summary>
          <div className="mt-2 grid gap-3 lg:grid-cols-2">
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
        </details>
      </section>
    </div>
  );
}

// ── v7.13 口诀近况: 13条红黄绿体检——异常优先展示, 健康项折叠(主人: 精简美观,
//    不做标签墙)。红=近24月均值<全时段25%且近12月为负 / 黄=近24月<全时段一半。 ──
const HEALTH_NOTE: Record<string, string> = {
  amber: "走弱",
  red: "衰退",
  idle: "近两年形态未出现",
};

function healthAvg(v: number | null) {
  return v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
}

function KoujueHealthList({ health }: { health: HprKoujueHealth[] }) {
  const [showOk, setShowOk] = useState(false);
  const bad = health.filter((h) => h.status !== "green");
  const ok = health.filter((h) => h.status === "green");
  const nRed = health.filter((h) => h.status === "red").length;
  const nAmber = health.filter((h) => h.status === "amber").length;
  return (
    <div className="rounded-md border border-muted px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span className="font-semibold">口诀近况</span>
        <span className="flex items-center gap-1.5 font-mono tabular-nums text-muted-foreground">
          <i className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          {ok.length} 绿
          {nAmber > 0 ? (
            <>
              <i className="ml-1 h-1.5 w-1.5 rounded-full bg-amber-500" />
              {nAmber} 黄
            </>
          ) : null}
          {nRed > 0 ? (
            <>
              <i className="ml-1 h-1.5 w-1.5 rounded-full bg-rose-500" />
              {nRed} 红
            </>
          ) : null}
          <span className="text-[10px]">（近24月 vs 全时段）</span>
        </span>
      </div>
      {bad.length > 0 ? (
        <ul className="mt-1.5 space-y-1">
          {bad.map((h) => (
            <li key={h.no} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
              <i className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                h.status === "red" ? "bg-rose-500" : h.status === "amber" ? "bg-amber-500" : "bg-muted-foreground/40"
              }`} />
              <span className="font-medium">{h.no} {h.name}</span>
              <span className={h.status === "red" ? "text-rose-500" : "text-amber-500"}>
                {HEALTH_NOTE[h.status]}
              </span>
              <span className="ml-auto font-mono tabular-nums text-muted-foreground">
                {h.n24 > 0
                  ? `近2年 ${h.n24}笔·胜${Math.round((h.win24 ?? 0) * 100)}%·均${healthAvg(h.avg24)}`
                  : "近2年无出手"}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-xs text-muted-foreground">全部健康，无走弱条目</p>
      )}
      {ok.length > 0 ? (
        <>
          <button
            type="button"
            onClick={() => setShowOk(!showOk)}
            className="mt-1 text-[11px] text-muted-foreground hover:text-foreground"
          >
            其余 {ok.length} 条健康 {showOk ? "▴" : "▾"}
          </button>
          {showOk ? (
            <ul className="mt-1 grid gap-x-6 gap-y-0.5 md:grid-cols-2">
              {ok.map((h) => (
                <li key={h.no} className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <i className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
                  <span>{h.no} {h.name}</span>
                  <span className="ml-auto font-mono tabular-nums">
                    近2年 {h.n24}笔·均{healthAvg(h.avg24)}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
