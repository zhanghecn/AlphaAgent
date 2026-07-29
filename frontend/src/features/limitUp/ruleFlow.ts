import type { LimitUpStrategyGuide } from "@/api/limitUp";

export interface RuleThreshold {
  label: string;
  value: string;
}

export type RuleStage = "gate" | "filter" | "radar" | "preboard" | "momentum" | "sector" | "rank" | "fill";

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
  preboard: { label: "板前观察", tone: "border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-300" },
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
      purpose: "历史回测和实时推荐执行同一套 A+B+C 规则。",
      condition:
        `唯一正式合同是 ${core.contract_version}。历史和实时都按同一字段时点与阈值计算，任何必需字段缺失都失败关闭。`,
      thresholds: [
        { label: "正式合同", value: core.contract_version },
        { label: "正式范围", value: "首板 + 二进三" },
        { label: "缺失字段", value: "失败关闭" },
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
      purpose: "先建立高质量 A/B 基座，再限定 C 只能覆盖三个指定排除原因。",
      condition:
        "只保留合格沪深主板的首板和二进三，使用当时已经披露的正确财报，并检查低位结构、风险、盘中支撑和对应板位质量。首板还必须通过同股历史盈利门。",
      thresholds: [
        { label: "同股D+1样本", value: "≥ 5 笔" },
        { label: "封板×D+1联合率", value: "≥ 30%" },
        { label: "股票范围", value: "合格沪深主板" },
      ],
      dataNote: "信号日之前已收盘的日线、已闭合 D+1 结果和当时已经披露的财务信息。",
      dataGroupKeys: ["prior"],
      failHint: "不属于 C 可覆盖原因或不满足交叉条件时只观察。",
    },
    {
      id: "radar",
      stage: "radar",
      badge: "③",
      title: "建立 A/B 辨识度基座",
      purpose: "A/B 保留已有市场记忆、但尚未过度炒作的股票。",
      condition:
        `信号日前 ${core.prior_limit_window_days} 个交易日内，涨停次数必须在 ${core.minimum_prior_limit_count} 到 ${core.maximum_prior_limit_count} 次之间。少于下限缺少辨识度，超过上限可能已经过度交易。`,
      thresholds: [
        { label: "统计窗口", value: `${core.prior_limit_window_days} 个交易日` },
        { label: "最少涨停", value: `${core.minimum_prior_limit_count} 次` },
        { label: "最多涨停", value: `${core.maximum_prior_limit_count} 次` },
      ],
      dataNote: "只统计信号日前已完成交易日，不把信号日后发生的涨停倒填进来。",
      dataGroupKeys: ["prior"],
      failHint: "A/B 不在 2 到 6 次区间时失败；超过 6 次只可能由 C 的完整交叉覆盖。",
    },
    {
      id: "preboard",
      stage: "preboard",
      badge: "④",
      title: "触板前进入可靠候选",
      purpose: "在还可以买到时展示，但不降低触板后的正式质量标准。",
      condition:
        "涨幅达到 3% 后持续评估。只有 A/B/C 正式质量、D+1 预期、lane 验证、执行时点和非触板条件全部通过，且实时快照未过期，才公开为板前候选；唯一允许缺少的正式条件是真实触板。",
      thresholds: [
        { label: "发现起点", value: "涨幅 ≥ 3%" },
        { label: "质量与时点", value: "必须全部通过" },
        { label: "允许缺少", value: "仅真实触板" },
        { label: "快照", value: "≤ 20 秒" },
      ],
      dataNote: "当前价、A/C/B 层级、点时 D+1 质量估计、lane 验证和实时阻断状态。",
      dataGroupKeys: ["intraday", "prior"],
      failHint: "时点未到、验证失败、有其他阻断或快照过期时不进入可靠板前榜。",
    },
    {
      id: "momentum",
      stage: "momentum",
      badge: "⑤",
      title: "真实触板后复核正式买点",
      purpose: "真实首次触板或回封后重新执行完整公共质量门。",
      condition:
        `A/C 首板与二进三真实触板或回封后，只在 ${windows.join("、")} 行动；B 首板要求 ${core.b_first_board_minimum_time} 后首次触板或回封。二进三 9:35-10:00 只观察。`,
      thresholds: [
        { label: "A/C 与二进三", value: windows.join("、") },
        { label: "B 首板", value: `${core.b_first_board_minimum_time} 后` },
        { label: "快照", value: "必须新鲜" },
        { label: "正式触发", value: "真实触板或回封" },
      ],
      dataNote: "真实触板时点、当前价、涨停价、已完成的盘中支撑证据和完整公共质量结果。",
      dataGroupKeys: ["intraday"],
      failHint: "未真实触板、时间窗不符、行情过期或公共质量失败时只观察，不执行。",
    },
    {
      id: "sector",
      stage: "sector",
      badge: "⑥",
      title: "形成 A/C/B 三层",
      purpose: "A/B 是质量基座，C 用资金与概念扩散补足被严格门遗漏的情绪机会。",
      condition:
        `D-1 行业量比达标的基座票为 A，否则为 B。C 只在此前无 A/B 时，满足混合期回撤、行业资金覆盖或细分概念已有 2-4 只先行封板且最高至少二板之一。${core.priority_rule}。`,
      thresholds: [
        { label: "A 级", value: `行业量比 ≥ ${core.a_tier_industry_turnover_ratio_5d.toFixed(1)}` },
        { label: "C 级", value: `每天最多 ${core.c_daily_limit} 笔` },
        { label: "B 级", value: "未扩张或不可用" },
        { label: "B 可交易", value: core.b_tier_is_actionable ? "是" : "否" },
      ],
      dataNote: "D-1 行业成交额和此前 5 日基准，二者在信号产生前都已知。",
      dataGroupKeys: ["prior"],
    },
    {
      id: "rank",
      stage: "rank",
      badge: "⑦",
      title: "输出全部 A+B+C 买点",
      purpose: "正式推荐输出所有合格信号；回测账户再单独按一仓或两仓容量执行。",
      condition:
        "同一时点按 A、C、B 排序，跨时点按真实到达顺序，不用后来 A 替换已成交票。两仓尚无 A 时最多使用一个非 A 仓，为稍后 A 保留一仓。",
      thresholds: [
        { label: "全量列表", value: "A/B 不限，C 每日 1 笔" },
        { label: "同刻顺序", value: "A > C > B" },
        { label: "回测两仓", value: "无 A 时保留 1 仓" },
      ],
      dataNote: "A/C/B 等级、真实触发时间、板位、同股历史盈利证据和概念扩散证据。",
      dataGroupKeys: ["prior", "intraday"],
    },
    {
      id: "fill",
      stage: "fill",
      badge: "⑧",
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
