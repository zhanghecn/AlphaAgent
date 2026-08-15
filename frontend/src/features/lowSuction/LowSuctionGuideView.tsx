import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp } from "lucide-react";

import { fetchLowSuctionGuideCases } from "@/api/lowSuction";
import { PanelHead } from "@/components/PanelHead";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn, formatPct, priceColorClass } from "@/lib/utils";

import { GuideCaseChart } from "./guide/GuideCaseChart";
import { GuideFlowChart } from "./guide/GuideFlowChart";
import { GuideRulePanel } from "./guide/GuideRulePanel";
import {
  buildGuideStages,
  buildRuleNodes,
  buildScoreTable,
  mergeCasesIntoRules,
  type GuideCase,
  type GuideFamilyKey,
} from "./guide/guideContent";

/** 默认选中：P1 分段支撑（案例最多、验证最充分的超跌产品规则）。 */
const DEFAULT_RULE_KEY = "staged_ma10_support_before_ma30_convergence_shrink";
/** 02 节分量表「代表案例」入口跳转的各族旗舰规则。 */
const FAMILY_FLAGSHIP_RULE: Record<GuideFamilyKey, string> = {
  trend_pullback: "ma5_low_touch_stable_trend_volume_shrink",
  oversold_rebound: DEFAULT_RULE_KEY,
};

/**
 * 低吸规则说明书：01 因子流程图（点节点看经典案例 K 线）+ 02 评分体系
 * + 03 口径与边界。案例数据来自后端策展清单（PERSONAL_CASES 真实历史
 * 股票），K 线窗口只显示「底盘 + 信号 + 信号后效果」段。
 */
export function LowSuctionGuideView() {
  const stages = useMemo(buildGuideStages, []);
  const baseNodes = useMemo(buildRuleNodes, []);
  const [selectedRuleKey, setSelectedRuleKey] =
    useState<string>(DEFAULT_RULE_KEY);
  const panelRef = useRef<HTMLDivElement>(null);

  const casesQuery = useQuery({
    queryKey: ["low-suction", "guide-cases"],
    queryFn: fetchLowSuctionGuideCases,
    staleTime: 60_000,
  });
  const merged = useMemo(
    () =>
      casesQuery.data
        ? mergeCasesIntoRules(baseNodes, casesQuery.data)
        : { nodes: baseNodes.map((node) => ({ ...node, cases: [] })), orphanCases: [] },
    [baseNodes, casesQuery.data],
  );
  const selectedNode =
    merged.nodes.find((node) => node.ruleKey === selectedRuleKey) ?? null;

  const selectRuleAndScroll = (ruleKey: string) => {
    setSelectedRuleKey(ruleKey);
    // 移动端面板在流程图下方，选择后滚动到位；桌面端右列 sticky 不需要。
    if (window.matchMedia("(max-width: 1023px)").matches) {
      panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  return (
    <section aria-label="低吸规则说明" className="text-sm">
      <PanelHead
        no="01"
        zh="因子流程"
        en="FACTOR PIPELINE"
        note="点击阶段卡看每步细节 · 点击规则节点看真实历史股票的经典案例 K 线"
      />
      <div className="border-b lg:grid lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0">
          <GuideFlowChart
            stages={stages}
            nodes={merged.nodes}
            selectedRuleKey={selectedRuleKey}
            onSelectRule={setSelectedRuleKey}
          />
          <p className="px-3 pb-3 text-[10px] text-muted-foreground/80 sm:px-4">
            虚线节点为研究锚点（只审计、不进实时推荐与回测仓位）；节点角标为关联案例数。
            {casesQuery.data?.status === "partial" && (
              <span className="text-amber-600">
                {" "}
                部分案例历史数据缺失，对应收益显示为 --。
              </span>
            )}
            {casesQuery.isError && (
              <span className="text-amber-600">
                {" "}
                案例收益数据暂时不可用，K 线与流程图不受影响。
              </span>
            )}
          </p>
          {merged.orphanCases.length > 0 && (
            <OrphanCasesGroup cases={merged.orphanCases} />
          )}
        </div>
        <div
          ref={panelRef}
          className="border-t px-3 py-4 sm:px-4 lg:border-l lg:border-t-0"
        >
          <div className="lg:sticky lg:top-3 lg:max-h-[calc(100vh-120px)] lg:overflow-y-auto lg:pr-1">
            <GuideRulePanel node={selectedNode} />
          </div>
        </div>
      </div>

      <PanelHead
        no="02"
        zh="评分体系"
        en="SCORING"
        note="评分独立于准入：规则决定谁能入池，评分只在池内排先后；分数不是收益概率，两族量纲不同不可横比"
      />
      <div className="space-y-4 border-b px-3 py-4 sm:px-4">
        <ScoreFamilySection
          family="trend_pullback"
          title="上升趋势低吸评分（9 分量直加）"
          onShowFlagship={() =>
            selectRuleAndScroll(FAMILY_FLAGSHIP_RULE.trend_pullback)
          }
        />
        <ScoreFamilySection
          family="oversold_rebound"
          title="超跌反弹低吸评分（门禁 + 折算）"
          onShowFlagship={() =>
            selectRuleAndScroll(FAMILY_FLAGSHIP_RULE.oversold_rebound)
          }
        />
      </div>

      <PanelHead no="03" zh="口径与边界" en="CONVENTION" note="诚实边界，不外推" />
      <div className="space-y-2 px-3 py-4 text-muted-foreground sm:px-4">
        <ul className="ml-4 list-disc space-y-0.5">
          <li>数据口径：raw_unadjusted 不复权日线（探索级，除权日有已知污染）；D 日收盘买入、D+1 收盘结算，未扣费。它是收盘集合竞价成交假设，不等同于次日开盘可成交收益。</li>
          <li>回测执行：每日趋势/超跌各取阶段优先级与同层决胜键最高的前 5 只，单票固定 10%，不足 10 只的槽位留现金；具体结果以「回测」页最新物化报告为准</li>
          <li>回测解读：只看当前评分版本、固定规则和固定前五排序的结果；页面分数段用于复核，不构成收益承诺</li>
          <li>并列决胜：P1.5 先按诊断分、同分再以换手率接近 3% 决胜；P1 按诊断分、连续小 K 线数和换手率决胜。回测与实时推荐使用同一决胜键。</li>
          <li>行情主导一切：两族人口均值仅接近打平，本产品按综合分排序取最高，不做全池买入</li>
          <li>实时推荐：交易日内每分钟用现货快照合成当日虚拟 K 线重算（未定型），收盘后以日线同步确认为准；实时组不含 ST 股</li>
          <li>说明书案例：来自策展经典案例库（真实历史股票），收益为信号日收盘起 D+1/D+3/D+5 收盘口径，遇除权跳变按诚实边界显示 --；案例用于理解因子形态，不代表未来收益</li>
        </ul>
        <div className="rounded border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-600">
          ⚠️ 全部内容为历史回测与研究结论，非投资建议；样本外有效性不保证，极端行情下 D+1 仍可能大幅亏损。
        </div>
      </div>
    </section>
  );
}

/** 单族评分分量表：门禁行置顶，折算分量带标注。 */
function ScoreFamilySection({
  family,
  title,
  onShowFlagship,
}: {
  family: GuideFamilyKey;
  title: string;
  onShowFlagship: () => void;
}) {
  const table = buildScoreTable(family);
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center gap-x-2">
        <span className="text-xs font-semibold">{title}</span>
        <span className="text-[11px] tabular-nums text-muted-foreground">
          满分口径 {table.maxScoreText}
        </span>
        <button
          type="button"
          onClick={onShowFlagship}
          className="rounded border px-1.5 py-px text-[10px] text-primary hover:bg-muted"
        >
          看代表案例 →
        </button>
      </div>
      <p className="mb-1.5 text-[11px] text-muted-foreground">{table.formula}</p>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-muted/30 text-left text-[11px] text-muted-foreground">
              <th className="px-2 py-1.5 font-medium">分量</th>
              <th className="px-2 py-1.5 font-medium">上限</th>
              <th className="px-2 py-1.5 font-medium">梯度口径</th>
              <th className="px-2 py-1.5 font-medium">设计依据</th>
            </tr>
          </thead>
          <tbody>
            {table.components.map((component) => (
              <tr
                key={component.key}
                className={cn(
                  "border-b last:border-0",
                  component.kind === "gate" && "bg-amber-500/[0.04]",
                )}
              >
                <td className="whitespace-nowrap px-2 py-1.5 font-medium">
                  {component.label}
                  {component.kind === "gate" && (
                    <span className="ml-1 rounded border border-amber-500/40 px-1 text-[9px] text-amber-600">
                      门禁
                    </span>
                  )}
                  {component.scaled === true && (
                    <span className="ml-1 text-[9px] text-muted-foreground">
                      ×0.4
                    </span>
                  )}
                  {component.scaled === false && component.kind === "bonus" && (
                    <span className="ml-1 text-[9px] text-muted-foreground">
                      不折算
                    </span>
                  )}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-muted-foreground">
                  {component.kind === "gate" ? "—" : component.maxPoints}
                </td>
                <td className="px-2 py-1.5 text-muted-foreground">
                  {component.gradient}
                </td>
                <td className="px-2 py-1.5 text-muted-foreground">
                  {component.rationale}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** 未成规则的观察个案组（无 rule_key 的 research_pending 案例，诚实单列）。 */
function OrphanCasesGroup({ cases }: { cases: GuideCase[] }) {
  return (
    <div className="border-t px-3 pb-4 pt-2 sm:px-4">
      <p className="mb-1 text-[11px] font-medium text-muted-foreground">
        未成规则的观察个案（待验证）
      </p>
      <p className="mb-1.5 text-[10px] leading-relaxed text-muted-foreground/80">
        这是复盘时觉得有意思、但还没总结出明确条件的走势个案——条件定不下来就写不成规则，所以它不属于上面
        16 条规则，也不会出现在实时推荐里。留在说明书中是给后续研究留参照：未来验证这类形态有效，才会补上条件升级成正式规则（立新能源/京投发展/传智教育/百花医药已在两轮升级中转正）。
      </p>
      <div className="grid gap-1.5 xl:grid-cols-2">
        {cases.map((caseItem) => (
          <OrphanCaseCard key={caseItem.caseId} caseItem={caseItem} />
        ))}
      </div>
    </div>
  );
}

function OrphanCaseCard({ caseItem }: { caseItem: GuideCase }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-dashed">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-xs hover:bg-muted/50"
      >
        <span className="flex min-w-0 items-center gap-2">
          <StockIdentityLink name={caseItem.name} vtSymbol={caseItem.vtSymbol} />
          <span className="shrink-0 tabular-nums text-[10px] text-muted-foreground">
            {caseItem.signalDate}
          </span>
          {caseItem.returns.d5 != null && (
            <span
              className={cn(
                "shrink-0 tabular-nums text-[10px]",
                priceColorClass(caseItem.returns.d5),
              )}
            >
              D+5 {formatPct(caseItem.returns.d5)}
            </span>
          )}
        </span>
        {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>
      {open && (
        <div className="border-t px-2.5 py-2">
          <GuideCaseChart caseItem={caseItem} />
        </div>
      )}
    </div>
  );
}
