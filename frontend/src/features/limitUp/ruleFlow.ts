import type { LimitUpStrategyGuide } from "@/api/limitUp";

export interface RuleThreshold {
  label: string;
  value: string;
}

export type RuleStage = "gate" | "filter" | "radar" | "momentum" | "sector" | "rank" | "fill";

export interface RuleFlowNode {
  id: string;
  stage: RuleStage;
  badge: string;
  title: string;
  /** 这一步想干什么（一句话） */
  purpose: string;
  /** 成立的详细条件 */
  condition: string;
  /** 关键数字门槛 */
  thresholds: RuleThreshold[];
  /** 用到的数据（人话） */
  dataNote: string;
  /** 对应后端字段组 */
  dataGroupKeys: ("intraday" | "prior" | "outcome")[];
  /** 不通过会怎样 */
  failHint?: string;
}

export const STAGE_META: Record<RuleStage, { label: string; tone: string }> = {
  gate: { label: "市场门禁", tone: "border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-300" },
  filter: { label: "范围筛选", tone: "border-primary/50 bg-primary/10 text-primary" },
  radar: { label: "雷达采集", tone: "border-primary/50 bg-primary/10 text-primary" },
  momentum: { label: "动能确认", tone: "border-rise/50 bg-rise/10 text-rise" },
  sector: { label: "板块确认", tone: "border-rise/50 bg-rise/10 text-rise" },
  rank: { label: "排序优先", tone: "border-foreground/30 bg-muted/60 text-foreground" },
  fill: { label: "成交结算", tone: "border-foreground/30 bg-muted/60 text-foreground" },
};

/**
 * 打板选股流程的可读化重建。
 *
 * 文案基于后端 `alphaagent/server/services/limit_up/` 的真实规则代码
 * （市场门、板位分类、雷达契约、动能分、板块路径、历史胜率、现金结算）。
 * 后端 `strategy_guide.py` 返回的是审计契约文档，保留精确英文术语；
 * 这里把它翻译成给用户看的人话，每步讲清"卡什么、用什么数据、为什么"。
 */
export function buildRuleFlow(guide: LimitUpStrategyGuide): RuleFlowNode[] {
  const windows = guide.strategy.entry_windows;
  const core = guide.core_quality;

  return [
    {
      id: "gate",
      stage: "gate",
      badge: "①",
      title: "锁定唯一正式合同",
      purpose: "历史回测和实时推荐执行同一套 A+B 规则。",
      condition:
        `唯一正式合同是 ${core.contract_version}。旧版本只保留为只读审计，不参与准入、排序，也不会在新规则缺数据时自动回退。`,
      thresholds: [
        { label: "正式合同", value: core.contract_version },
        { label: "正式范围", value: "首板 + 二进三" },
        { label: "旧规则回退", value: "关闭" },
      ],
      dataNote:
        "合同版本、规则阈值和字段时点在历史与实时两端保持一致。",
      dataGroupKeys: ["prior", "outcome"],
    },
    {
      id: "filter",
      stage: "filter",
      badge: "②",
      title: "通过原基础质量门",
      purpose: "先排除财务、风险、板位和承接结构不合格的股票。",
      condition:
        "只保留合格沪深主板的首板和二进三，使用当时已经披露的正确财报，并检查低位结构、风险、盘中支撑和对应板位质量。首板还必须通过同股历史盈利门。",
      thresholds: [
        { label: "同股D+1样本", value: "≥ 5 笔" },
        { label: "封板×D+1联合率", value: "≥ 30%" },
        { label: "股票范围", value: "合格沪深主板" },
      ],
      dataNote: "信号日之前已收盘的日线、已闭合 D+1 结果和当时已经披露的财务信息。",
      dataGroupKeys: ["prior"],
      failHint: "基础质量门失败时只观察，不进入正式买点。",
    },
    {
      id: "radar",
      stage: "radar",
      badge: "③",
      title: "检查 126 日市场辨识度",
      purpose: "保留已有市场记忆、但尚未过度炒作的股票。",
      condition:
        `信号日前 ${core.prior_limit_window_days} 个交易日内，涨停次数必须在 ${core.minimum_prior_limit_count} 到 ${core.maximum_prior_limit_count} 次之间。少于下限缺少辨识度，超过上限可能已经过度交易。`,
      thresholds: [
        { label: "统计窗口", value: `${core.prior_limit_window_days} 个交易日` },
        { label: "最少涨停", value: `${core.minimum_prior_limit_count} 次` },
        { label: "最多涨停", value: `${core.maximum_prior_limit_count} 次` },
      ],
      dataNote: "只统计信号日前已完成交易日，不把信号日后发生的涨停倒填进来。",
      dataGroupKeys: ["prior"],
      failHint: "不在 2 到 6 次区间内，或该字段不可用，均不执行。",
    },
    {
      id: "momentum",
      stage: "momentum",
      badge: "④",
      title: "等待正式盘中触发",
      purpose: "只有原盘中支撑、触发状态和交易时间都有效时才给买点。",
      condition:
        `候选必须在 ${windows.join("、")} 内通过原盘中支撑、报价新鲜度和正式触发状态。3% 板前观察和触板概率目前只是研究，不会生成正式买点。`,
      thresholds: [
        { label: "买入窗口", value: windows.join("、") },
        { label: "快照", value: "必须新鲜" },
        { label: "板前概率", value: "研究观察" },
      ],
      dataNote: "当前价、涨停价、已完成的盘中支撑证据和正式触发状态。",
      dataGroupKeys: ["intraday"],
      failHint: "时间窗、行情新鲜度或触发条件失败时只观察，不执行。",
    },
    {
      id: "sector",
      stage: "sector",
      badge: "⑤",
      title: "按行业资金分 A/B",
      purpose: "资金扩张用于优先排序，不把仍合格的 B 级股票强行剔除。",
      condition:
        `D-1 所属行业成交额不低于此前 5 日基准的候选为 A；未扩张或数据不可用为 B。${core.priority_rule}。行业和概念都按当时数据动态计算，不写死名称。`,
      thresholds: [
        { label: "A 级", value: `行业量比 ≥ ${core.a_tier_industry_turnover_ratio_5d.toFixed(1)}` },
        { label: "B 级", value: "未扩张或不可用" },
        { label: "B 可交易", value: core.b_tier_is_actionable ? "是" : "否" },
      ],
      dataNote: "D-1 行业成交额和此前 5 日基准，二者在信号产生前都已知。",
      dataGroupKeys: ["prior"],
    },
    {
      id: "rank",
      stage: "rank",
      badge: "⑥",
      title: "输出全部 A+B 买点",
      purpose: "评价规则质量时统计全部合格信号，不人为限制每天一笔。",
      condition:
        "同一交易日可以出现多笔正式推荐。A 排在 B 前面；同级内再沿用首板或二进三的原排序。全量胜率按每笔独立闭合交易统计。",
      thresholds: [
        { label: "日内笔数", value: "不设 1 笔上限" },
        { label: "第一优先", value: "A 级" },
        { label: "第二优先", value: "B 级" },
      ],
      dataNote: "A/B 等级、板位、同股历史盈利证据和原排名分。",
      dataGroupKeys: ["prior", "intraday"],
    },
    {
      id: "fill",
      stage: "fill",
      badge: "⑦",
      title: "按统一口径成交和退出",
      purpose: "历史和实时采用同一买入、费用与 D+1 退出合同。",
      condition:
        "正式触发使用保存的买入价格代理，并计入滑点、佣金、过户费和印花税；D+1 按官方日线收盘价退出。没有真实涨停价排队回报时，只能说明可尝试排队，不能假设必然成交。",
      thresholds: [
        { label: "买入窗口", value: windows.join("、") },
        { label: "卖出", value: "D+1 官方收盘价" },
        { label: "收益", value: "扣除正式费用" },
      ],
      dataNote: "点时买入价格代理、正式费用和 D+1 官方日线。",
      dataGroupKeys: ["intraday", "outcome"],
    },
  ];
}

export const DATA_GROUP_LABELS: Record<string, string> = {
  intraday: "盘中实时",
  prior: "信号前已知",
  outcome: "事后结果",
};
