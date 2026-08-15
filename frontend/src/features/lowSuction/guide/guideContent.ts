import type {
  GuideCaseItem,
  GuideCasesPayload,
} from "@/api/lowSuction";

/**
 * 低吸说明书内容模型：流程阶段、规则节点、评分分量表与案例合并。
 * 全部纯函数，内容手工转录自后端权威源码（注释注明位置），由
 * guideContent.spec.ts 的完整性断言防止与规则清单漂移。
 */

export type GuideFamilyKey = "trend_pullback" | "oversold_rebound";
export type GuideStageKey =
  | "filter"
  | "admission"
  | "scoring"
  | "ranking"
  | "portfolio";

/** 流程图阶段（管道骨架）。 */
export interface GuideStage {
  key: GuideStageKey;
  no: string;
  zh: string;
  en: string;
  note: string;
  bullets: string[];
}

/** 规则节点：内容与后端 DISCOVERY_RULES 的 rule_key 一一对应。 */
export interface GuideRuleNode {
  ruleKey: string;
  family: GuideFamilyKey;
  shortLabel: string;
  tier: "product" | "research";
  productTier?: "P1.5" | "P1";
  /** 准入条件（说明书语言，含阈值）。 */
  conditions: string[];
  /** 全量验证/案例证据摘句。 */
  evidence: string;
  /** 该因子在 K 线图上的看点提示（展示在案例图上方）。 */
  chartHint: string;
}

/** 评分分量（转录自 daily_picks_scoring.py）。 */
export interface GuideScoreComponent {
  key: string;
  label: string;
  maxPoints: number;
  kind: "gate" | "bonus";
  /** true = 计入基础分按 0.4 折算（仅超跌族有此概念）。 */
  scaled?: boolean;
  gradient: string;
  rationale: string;
}

export interface GuideScoreTable {
  family: GuideFamilyKey;
  components: GuideScoreComponent[];
  /** 满分口径文本：趋势 "100"，超跌 "≈70"。 */
  maxScoreText: string;
  /** 折算/门禁公式说明。 */
  formula: string;
}

/** 后端案例 payload 的前端视图模型（驼峰化 + 收益字段简化）。 */
export interface GuideCase {
  caseId: string;
  name: string;
  vtSymbol: string;
  signalDate: string;
  setupType: GuideFamilyKey;
  narrativeStartDate: string | null;
  expectedLaunchDate: string | null;
  narrativeStatus: string;
  returns: { d1: number | null; d3: number | null; d5: number | null; status: string };
}

export interface GuideRuleNodeWithCases extends GuideRuleNode {
  cases: GuideCase[];
}

export interface MergedGuideRules {
  nodes: GuideRuleNodeWithCases[];
  orphanCases: GuideCase[];
}

export function buildGuideStages(): GuideStage[] {
  return [
    {
      key: "filter",
      no: "01",
      zh: "硬过滤",
      en: "HARD FILTER",
      note: "先砍掉不能碰的票，再谈形态",
      bullets: [
        "主板限定：600/601/603/605 + 000/001/002/003（北交所、科创板、创业板 20cm 票不做）",
        "剔除当前 ST 股（名称含 ST 即排）",
        "信号日收于涨停的主板票直接剔除——涨停价买不到，低吸语境也不成立",
      ],
    },
    {
      key: "admission",
      no: "02",
      zh: "规则准入",
      en: "RULE ADMISSION",
      note: "形态规则决定能否入池，评分无权抬票",
      bullets: [
        "只有命中研究形态规则的股票才进入候选池；没命中的票，其他分项分数再高也不会出现在列表里",
        "超跌族放行 6 条跨窗口验证过的产品规则：P1.5 首段两线包裹 + P1.5 上穿前价格先行两子型（X 弱市加速 / Y 价格先行强攻）+ P1.5 三线包裹链（W 缩量底盘 / Z 次日上沿确认）+ P1 分段支撑，其余 3 条留在研究层审计",
        "趋势族 7 条规则全部产品化，覆盖稳定回踩、过伸回踩、早期回踩与超跌转趋势四类语境",
      ],
    },
    {
      key: "scoring",
      no: "03",
      zh: "诊断评分",
      en: "DIAGNOSTIC SCORE",
      note: "同族同层内比较形态完整度，不是收益概率",
      bullets: [
        "趋势族：9 个梯度分量直加，满分 100",
        "超跌族：基础分量 ×0.4 + 路径附加分（P1 两条 / X/Y 攻击强度投票 / W 安静包裹 / Z 链式确认，不折算），满值约 70，与趋势分不同量纲、不可直接横比",
        "换手率 ≥8% 触发超跌门禁：不改变规则命中，但诊断分封顶 39，避免高换手派发占据前列",
      ],
    },
    {
      key: "ranking",
      no: "04",
      zh: "排序决胜",
      en: "RANKING",
      note: "先阶段层级，再诊断分，再决胜键",
      bullets: [
        "阶段优先级：P1.5（20）> P1（10）> 其他（0）——层级始终压过分数",
        "同层按诊断分降序；P1.5 同分时以换手率接近 3% 决胜（中等活跃承接最佳）",
        "再并列依次比：连续小 K 线根数 → 换手率（低优先）→ 股票代码",
      ],
    },
    {
      key: "portfolio",
      no: "05",
      zh: "组合构建",
      en: "PORTFOLIO",
      note: "分散 + 现金兜底，不孤注一掷",
      bullets: [
        "每日两族各取排名前 5，共 10 个槽位",
        "单票固定 10% 仓位；当日不足 10 只的槽位留现金",
        "D 日收盘买入、D+1 收盘结算（收盘集合竞价假设，未扣费）",
      ],
    },
  ];
}

export function buildRuleNodes(): GuideRuleNode[] {
  return [...TREND_RULE_NODES, ...OVERSOLD_RULE_NODES];
}

/**
 * 趋势族 7 条产品规则。谓词转录自
 * daily_factor_extended_discovery.py process_rule_predicates（3767-3854 行）。
 */
const TREND_RULE_NODES: GuideRuleNode[] = [
  {
    ruleKey: "ma5_low_touch_stable_trend",
    family: "trend_pullback",
    shortLabel: "稳定多头 MA5 回踩",
    tier: "product",
    conditions: [
      "多头排列：MA5 > MA10 > MA20 > MA30，且 MA10/MA20/MA30 斜率全部向上",
      "多头排列已稳定持续 ≥5 日，且 MA5 走势规律（MA5 > MA10）",
      "D 日低点回踩 MA5：低点距线 -4% ~ +1.5%，收盘不破 -1.5%",
      "D 日涨幅 ≤3%（不追大阳线）",
    ],
    evidence:
      "最纯的趋势回踩形态；8/8 个人案例零误伤，官方案例门禁 15/15。代表案例：华电辽能 3-5。",
    chartHint: "看 D 日下影线如何贴住琥珀色 MA5 后收回，且此前均线已多头排列",
  },
  {
    ruleKey: "ma5_low_touch_stable_trend_volume_shrink",
    family: "trend_pullback",
    shortLabel: "稳定多头 MA5 回踩缩量",
    tier: "product",
    conditions: [
      "在「稳定多头 MA5 回踩」全部条件之上，追加：D 日成交量低于前一日",
      "缩量回踩 = 抛压衰竭，分歧小，是回踩质量最高的变体",
    ],
    evidence:
      "缩量变体是回踩质量信号；代表案例：华电辽能 3-13（D+5 +61.34%，三连板）。",
    chartHint: "对比 D 日量柱与前几日的量能高度——回踩当天明显缩量",
  },
  {
    ruleKey: "ma10_low_touch_after_ma5_extension",
    family: "trend_pullback",
    shortLabel: "MA5 过伸后回踩 MA10",
    tier: "product",
    conditions: [
      "稳定多头排列（同 MA5 回踩族前置）",
      "前一日收盘偏离 MA5 ≥1.5%（短线过伸）且昨日没有上涨（分歧已开始释放）",
      "D 日低点回踩更深的 MA10 获支撑",
    ],
    evidence:
      "过伸后的首次深回踩比贴 MA5 的浅回踩更安全；代表案例：中南文化 2-12。",
    chartHint: "看紫色 MA10 如何接住从 MA5 上方回落的价格",
  },
  {
    ruleKey: "ma5_low_touch_after_disordered_trend_rebuild",
    family: "trend_pullback",
    shortLabel: "混乱重建后 MA5 回踩",
    tier: "product",
    conditions: [
      "均线曾经混乱（多头排列被打断），新近重新恢复多头排列",
      "恢复后的早期阶段，D 日低点以更宽的容差回踩 MA5",
    ],
    evidence:
      "趋势重建初期的第一次回踩是右侧确认点；代表案例：华电辽能 4-30。",
    chartHint: "看均线从缠绕混乱到重新发散多头排列的过程，回踩发生在新趋势确认后",
  },
  {
    ruleKey: "ma5_low_touch_early_trend",
    family: "trend_pullback",
    shortLabel: "多头早期 MA5 回踩",
    tier: "product",
    conditions: [
      "多头排列形成早期（3~20 日），三线斜率全部向上",
      "D 日低点回踩 MA5",
    ],
    evidence:
      "早期趋势的回踩弹性最大；代表案例：华建集团 2025-09-18 起连续五次命中。",
    chartHint: "看多头排列刚形成不久（均线开口还小）时的首次贴线",
  },
  {
    ruleKey: "ma5_low_touch_early_trend_prior_touch",
    family: "trend_pullback",
    shortLabel: "早期连续 MA5 回踩",
    tier: "product",
    conditions: [
      "多头排列早期（3~20 日），且前一日低点已触及 MA5",
      "D 日再次回踩 MA5——连续两天贴线，支撑被反复验证",
    ],
    evidence:
      "华建集团 2025-09-19 ~ 09-24 连续命中该变体，5 日区间涨幅 +44%。",
    chartHint: "看连续两根 K 线的下影线都打在 MA5 上——「踩着均线上楼」",
  },
  {
    ruleKey: "oversold_to_trend_after_ma10_dual_cross_near_ma20_ma30",
    family: "trend_pullback",
    shortLabel: "超跌转趋势双穿",
    tier: "product",
    conditions: [
      "前期长期空头排列 ≥10 日",
      "MA10 在 7 个交易日内依次上穿 MA20、MA30（双穿）",
      "双穿后回撤：MA20/MA30 紧贴（距离 ≤0.25%），MA10/MA20 斜率向上",
      "D 日小阳线（0 < 涨幅 ≤3%）",
    ],
    evidence:
      "趋势族里唯一从超跌语境长出来的规则，是两族的交接棒；代表案例：一鸣食品 7-27（D+5 +61.07%）。",
    chartHint: "看紫色 MA10 如何先后上穿蓝色 MA20 与青色 MA30，回撤时两线几乎贴合",
  },
];

/**
 * 超跌族 9 条规则：P1.5/P1 产品放行，其余研究层。谓词转录自
 * daily_factor_extended_discovery.py process_rule_predicates 与
 * _pre_cross_price_lead_base_predicates（常量区 102-133 行）。
 */
const OVERSOLD_RULE_NODES: GuideRuleNode[] = [
  {
    ruleKey: "first_leg_two_ma_body_wrap_before_ma30",
    family: "oversold_rebound",
    shortLabel: "首段两线包裹（成熟底盘）",
    tier: "product",
    productTier: "P1.5",
    conditions: [
      "前期长期空头排列 ≥10 日，当前仍是 MA10 < MA20 < MA30 全空头",
      "D 日阳线实体包裹 MA10/MA20：开盘低于两线低者、收盘高于两线高者，但收盘仍在 MA30 下方",
      "信号日未封涨停（涨停买不到）",
      "成熟底盘资格门：攻击前 15 日为逐级支撑或释放后受控回踩相位，底盘枢轴年龄 ≥9 日",
      "MA10/MA20 平稳收敛：5 日收敛效率 ≥0.156 且 3 日缩差在 1.32%~4%（排除不收敛与大阳硬拉）",
      "不追高：收盘距 MA10 ≤3%，D 日涨幅 ≤5%，收盘脱离日内低点 ≥3.22%",
    ],
    evidence:
      "MA10 准备上穿 MA20 的第一段攻击，不是已完成的趋势；跨窗口验证后放行。代表案例：百花医药 7-14（D+1 +10.03%）。",
    chartHint: "看 D 日红色实体如何一口吞掉紫 MA10 与蓝 MA20 两线，且收盘仍压在青色 MA30 之下",
  },
  {
    ruleKey: "pre_cross_acceleration_weak_market",
    family: "oversold_rebound",
    shortLabel: "弱市上穿前加速（X）",
    tier: "product",
    productTier: "P1.5",
    conditions: [
      "共用底盘：长期空头 ≥10 日，MA10 仍低于 MA20 不超过 4%（或刚上穿 3 日内），3 日缩差 ≥1%、MA10→MA30 5 日缩差 ≥3%",
      "价格先行：收盘已在 MA10 上方 1.4%~10%，低点回踩 MA10/MA20 获撑，收盘脱离低点 ≥2.5%",
      "D 日小阳（0 < 涨幅 ≤3%），换手 ≤3%，收盘未远离 MA30（≤3%），信号日未封涨停",
      "攻击强度：四轴投票 ≥2 票（5 日缩差 ≥7% / 单日放量 >80% / MA10 两日加速 >1.5% / 均线开口 ≥5%），或 MA10 加速 + 量比 <1.1 的替代路径",
      "弱市门（产品层）：信号日（或最近已确认）指数收盘位于 MA20 下方才入场——该形态在弱市中才具备定价权",
    ],
    evidence:
      "立新能源型。半年回测（2026-02~08）单独样本 82：胜率 68.3%、D+1 均值 +1.10%；剔除案例后 67.9% / +1.00 不降。代表案例：立新能源 7-15（D+5 +60.96%）。",
    chartHint: "看紫 MA10 如何向蓝 MA20 加速收口，价格已先一步站上 MA10，且 D 日下影线获均线支撑",
  },
  {
    ruleKey: "price_first_strong_attack",
    family: "oversold_rebound",
    shortLabel: "价格先行强攻（Y）",
    tier: "product",
    productTier: "P1.5",
    conditions: [
      "共用底盘：同「弱市上穿前加速」的收敛/低点获撑/小阳/换手门槛",
      "价格先行幅度更大：收盘领先 MA10 达 6%~10%",
      "MA10 两日内加速上行（斜率 >1.5%）——均线被价格拖着走",
      "全 regime 放行（强弱市均可），无需弱市门",
    ],
    evidence:
      "京投发展型。半年回测单独样本 39：胜率 71.8%、D+1 均值 +1.85%；剔除案例后 71.1% / +1.63。代表案例：京投发展 8-7（D+3 +33.07%）。",
    chartHint: "看 K 线实体如何整体浮在紫 MA10 上方 6-10%，而 MA10 本身正在拐头加速上翘",
  },
  {
    ruleKey: "staged_ma10_support_before_ma30_convergence_shrink",
    family: "oversold_rebound",
    shortLabel: "分段支撑缩量收敛",
    tier: "product",
    productTier: "P1",
    conditions: [
      "前期空头排列 ≥5 日，D 日涨幅在 -10% ~ +3% 之间",
      "MA10 已在 15 个交易日内上穿 MA20，且 MA10 > MA20、MA10 仍在 MA30 下方",
      "D 日低点回踩 MA10 获支撑，收盘贴近 MA10",
      "MA10 与 MA30 的距离持续缩小：5 日缩差 ≥5%",
      "量能呈阶梯式收缩（staircase_shrink），6 日单调缩量度 ≥0.8",
    ],
    evidence:
      "「先过 MA20、再准备过 MA30」的地基阶段；传智教育 7-22、7-24 属于该路径（7-24 D+5 +61.06%）。",
    chartHint: "看紫 MA10 与青 MA30 之间的口子如何越收越窄，同时下方量柱一级一级往下缩",
  },
  {
    ruleKey: "research_oversold_three_ma_wrap_stable_base",
    family: "oversold_rebound",
    shortLabel: "三线收敛阳线包裹",
    tier: "product",
    productTier: "P1.5",
    conditions: [
      "长期空头排列 ≥10 日，且 MA10 已在 15 个交易日内上穿 MA20",
      "D 日阳线实体同时包裹 MA10/MA20/MA30 三线，换手 ≥1.5%",
      "低点贴线：当日低点距最近均线 ≤1.5%",
      "缩量到底：当日量能 ≤ 近 6 日峰值的 55%",
    ],
    evidence:
      "传智教育/百花医药型。2026-08 校准：原梯形缩量条件是反指标（保留它 n=18 胜率 56%），移除后半年回测 n=40、剔除案例胜率 65.8%、D+1 均值 +0.45；1 年窗口 n=67、剔案例 58.5%/+0.34（2025 强 regime 段稀释，诚实标注）。代表案例：传智教育 7-23、百花医药 7-31。",
    chartHint: "看三根均线收敛成一团后，一根阳线实体把它们全部穿过，量柱缩到近一周最低",
  },
  {
    ruleKey: "post_wrap_upper_band_reclaim_confirmation",
    family: "oversold_rebound",
    shortLabel: "包裹后上沿回踩站稳",
    tier: "product",
    productTier: "P1.5",
    conditions: [
      "前置（宽口径）：昨日三线包裹 + 低点贴线 ≤2.5% + 量能 ≤6 日峰值 70%",
      "D 日低点回贴昨日三线上沿 ±1.5% 以内",
      "收盘站上当日 MA10/MA20/MA30 三线",
      "小阳 + 振幅平静，换手 1.5%~8%",
    ],
    evidence:
      "百花医药 8-3 型。次日确认本身已是一层过滤，故前置底盘比「三线收敛阳线包裹」宽一档。半年回测 n=43、剔除案例胜率 69.0%、D+1 均值 +0.86；1 年窗口 n=97、剔案例 61.5%/+0.67，双 regime 稳定。代表案例：百花医药 8-3（D+1 涨停 +10.0%）。",
    chartHint: "看包裹阳线之后，价格回踩三线上沿（而非均线）能否站稳，量能保持克制",
  },
  {
    ruleKey: "attack_body_hold_after_ma10_ma20_cross_before_ma30",
    family: "oversold_rebound",
    shortLabel: "攻击实体缩量守住",
    tier: "research",
    conditions: [
      "MA10 已上穿 MA20、仍未越 MA30 的阶段",
      "攻击阳线实体在随后交易日缩量守住，不回吐实体",
    ],
    evidence:
      "研究锚点：国风新材 8-7。半年全市场 145 样本胜率 47.6%、均值 −0.01；regime/换手/缩量/投票各子桶均无独立边——国风案例是强 regime 的 beta 发射（与秦安股份同型），继续留审计不占仓位。",
    chartHint: "看攻击阳线之后的小 K 线如何缩在实体上方横住，量能同步萎缩",
  },
  {
    ruleKey: "ma10_ma20_contact_pre_cross_positive_volume_expand",
    family: "oversold_rebound",
    shortLabel: "MA10/20 预上穿放量",
    tier: "research",
    conditions: [
      "MA10 与 MA20 接触、尚未正式上穿的预备阶段",
      "接触当日出现阳线放量，试探性攻击",
    ],
    evidence:
      "研究锚点：一鸣食品 7-15。半年全市场 1718 样本胜率 42.9%、均值 −0.21，剔除与产品规则重叠后的 1423 样本增量池依然无边缘；其有效子型已被「弱市上穿前加速（X）」与成熟首段两线包裹覆盖（一鸣当日即由后者命中），故不单独产品化。",
    chartHint: "看紫 MA10 贴近蓝 MA20 的瞬间，量能是否温和放大",
  },
  {
    ruleKey: "ma10_ma30_retest_after_actual_cross_two_leg_volume",
    family: "oversold_rebound",
    shortLabel: "MA30 回踩两腿量修复",
    tier: "research",
    conditions: [
      "MA10 已实际上穿 MA30 之后",
      "价格回踩 MA30，量能先缩后放（两腿量），完成修复",
    ],
    evidence:
      "研究锚点：爱丽家居 7-20（D+5 +61.09%）。谓词过严——半年全市场仅命中案例自身；逐步放宽后弱市子集胜率 59%、均值 +0.39 未达产品门槛，恐慌急跌+缩量转放量型暂无成群体证据。",
    chartHint: "看价格回落贴住青色 MA30 时，量柱先缩到极致再重新放大",
  },
];

/**
 * 趋势族评分分量（转录自 daily_picks_scoring.py:128-273，9 个 bonus，
 * 无 gate，直加满分 100）。
 */
const TREND_SCORE_COMPONENTS: GuideScoreComponent[] = [
  {
    key: "candle_quiet_context",
    label: "振幅安静度(语境)",
    maxPoints: 22,
    kind: "bonus",
    gradient:
      "成熟票(MA60≤MA30)：振幅 <3% 满 22 / 3-5% 得 14 / 5-8% 得 4 / ≥8% 得 0；转势票(MA60>MA30)：14 / 20 / 22 / 6",
    rationale:
      "全量 811 日最单调变量：振幅 <3% 组 +0.013% → ≥10% 组 -0.734%。转势票反弹初期中等振幅(5-8%)反而是唯一正收益口袋(+0.018%)，故按语境切换梯度。",
  },
  {
    key: "trend_age",
    label: "趋势年龄",
    maxPoints: 14,
    kind: "bonus",
    gradient: "多头排列 6-10 日满 14 / 3-5 日得 10 / 1-2 日得 7 / 11-20 日得 5 / ≥21 日得 4",
    rationale: "太嫩未验证、太老易衰竭，6-10 日是弹性与可靠性的甜点区。",
  },
  {
    key: "touch_line",
    label: "回踩均线",
    maxPoints: 14,
    kind: "bonus",
    gradient: "低点回踩 MA5 满 14 / 回踩 MA10 得 9 / 未回踩 0",
    rationale: "贴 MA5 的浅回踩趋势更强；回踩 MA10 是过伸后的次优解。",
  },
  {
    key: "turnover_gradient",
    label: "换手率梯度",
    maxPoints: 12,
    kind: "bonus",
    gradient: "<3% 满 12 / <5% 得 8 / <8% 得 4 / 其余 1",
    rationale: "低换手 = 分歧小；趋势族不设门禁（妖股高换手常见，硬门禁误伤研究票）。",
  },
  {
    key: "quiet_streak",
    label: "连续小K线",
    maxPoints: 14,
    kind: "bonus",
    gradient: "连续 ≥5 根满 14 / 4 根 11 / 3 根 8 / 2 根 5（小 K 线 = 振幅 ≤5%）",
    rationale: "连续安静是蓄势的直接证据，比单日安静更可靠。",
  },
  {
    key: "prior_day_down",
    label: "昨日已跌",
    maxPoints: 8,
    kind: "bonus",
    gradient: "昨日 ≤0% 满 8 / ≤+1% 得 4 / 其余 0",
    rationale:
      "昨日已跌 = 分歧已开始释放，才是低吸语境；昨日 ≥5% 组全量均值 -0.867%（追高买首阴）。",
  },
  {
    key: "close_position",
    label: "收盘位置",
    maxPoints: 8,
    kind: "bonus",
    gradient: "收盘距 MA5 ≤0% 满 8 / ≤+1% 得 4 / 其余 0",
    rationale: "收盘贴线说明回踩真实有效，而非盘中假触。",
  },
  {
    key: "dist_excess",
    label: "趋势老嫩",
    maxPoints: 5,
    kind: "bonus",
    gradient: "M5-M10 距离超额 <0 满 5 / <1 得 3 / <2 得 1 / 其余 0",
    rationale:
      "相对本段自己的回踩签名中位数判断老嫩，不用绝对阈值；超额 ≥6pct 组全量均值 -1.049%。",
  },
  {
    key: "volume_shrink",
    label: "缩量",
    maxPoints: 3,
    kind: "bonus",
    gradient: "当日量低于前日 +3",
    rationale: "缩量回踩 = 抛压衰竭的辅助确认，权重刻意低（主证据在形态）。",
  },
];

/**
 * 超跌族评分分量（转录自 daily_picks_scoring.py:276-494）。
 * 口径：raw = 基础 bonus 之和 ×0.4 + P1 两条附加（不折算），门禁失败封顶 39。
 */
const OVERSOLD_SCORE_COMPONENTS: GuideScoreComponent[] = [
  {
    key: "turnover_gate",
    label: "换手率门禁",
    maxPoints: 0,
    kind: "gate",
    gradient: "换手 <8% 通过；≥8% 门禁失败，总分封顶 39",
    rationale: "高换手超跌反弹多是派发而非承接，不改变规则命中但压出前列。",
  },
  {
    key: "turnover_gradient",
    label: "换手率梯度",
    maxPoints: 14,
    kind: "bonus",
    scaled: true,
    gradient: "<3% 满 14 / 3-5% 得 10 / 5-8% 得 4 / ≥8% 得 0",
    rationale: "缩量地基是超跌形态的核心证据。",
  },
  {
    key: "candle_quiet",
    label: "振幅安静度",
    maxPoints: 12,
    kind: "bonus",
    scaled: true,
    gradient: "振幅 <3% 满 12 / <5% 得 8 / <8% 得 2 / 其余 0",
    rationale: "超跌语境不切换梯度——底盘必须安静，嘈杂 K 线的影线是噪音。",
  },
  {
    key: "low_support",
    label: "低点获均线支撑",
    maxPoints: 16,
    kind: "bonus",
    scaled: true,
    gradient: "D 日低点在 MA10/20/30 获实际支撑 满 16",
    rationale: "没有真实均线支撑的「超跌」只是下跌中继，全族最大权重。",
  },
  {
    key: "long_bear_duration",
    label: "空头持续时长",
    maxPoints: 10,
    kind: "bonus",
    scaled: true,
    gradient: "前期空头 ≥20 日满 10 / ≥10 日得 8 / ≥5 日得 4",
    rationale: "跌得足够久，筹码才出清得干净。",
  },
  {
    key: "process_structure",
    label: "上穿过程结构",
    maxPoints: 12,
    kind: "bonus",
    scaled: true,
    gradient: "P1 的 MA10 分阶段上穿结构成立 满 12",
    rationale: "分阶段（先 MA20 后 MA30）比一步到位的大阳线更可持续。",
  },
  {
    key: "capitulation",
    label: "崩盘脱离低点",
    maxPoints: 10,
    kind: "bonus",
    scaled: true,
    gradient: "紧凑反弹(收盘脱离低点 0.3~1.5%) 满 10 / 宽松反弹 得 6",
    rationale: "崩盘后的紧凑脱离是恐慌出清特征；弹太急反而透支。",
  },
  {
    key: "close_reaction",
    label: "收盘支撑反应",
    maxPoints: 8,
    kind: "bonus",
    scaled: true,
    gradient: "收盘守住支撑并脱离低点 ≥0.3% 满 8",
    rationale: "盘中触线不算数，收盘有反应才算支撑有效。",
  },
  {
    key: "volume_shape",
    label: "量能形态",
    maxPoints: 5,
    kind: "bonus",
    scaled: true,
    gradient: "阶梯式缩量(staircase_shrink) 满 5",
    rationale: "一级一级往下缩的量柱是底盘夯实的形态学证据。",
  },
  {
    key: "quiet_streak",
    label: "连续小K线",
    maxPoints: 3,
    kind: "bonus",
    scaled: true,
    gradient: "连续 ≥2 根满 3",
    rationale: "超跌语境只要求初步企稳，权重低于趋势族。",
  },
  {
    key: "vol_trend",
    label: "量能趋势",
    maxPoints: 10,
    kind: "bonus",
    scaled: true,
    gradient: "5/10 日均量比 <0.8 满 10 / <1.0 得 8 / <1.1 得 4 / <1.3 得 2",
    rationale: "骤然缩量(<0.8)是抛压枯竭的最强量能信号。",
  },
  {
    key: "staged_ma30_fast_convergence",
    label: "MA10 向 MA30 快速收敛",
    maxPoints: 2,
    kind: "bonus",
    scaled: false,
    gradient: "仅 P1 命中且 5 日缩差 ≥5% +2",
    rationale: "P1 路径的过程加分，全额计折不缩放。",
  },
  {
    key: "staged_ma30_active_participation",
    label: "收缩后活跃承接",
    maxPoints: 8,
    kind: "bonus",
    scaled: false,
    gradient: "仅 P1 命中且换手 1.5%~8% +8",
    rationale:
      "奖励「缩量但仍有承接」，不让无成交的缩量地基排在前面；非 P1 不得分。",
  },
  {
    key: "attack_votes",
    label: "攻击强度投票",
    maxPoints: 8,
    kind: "bonus",
    scaled: false,
    gradient: "仅 X/Y 命中：gap 快收/放量/MA10 加速/宽开口 四轴每中 1 轴 +2，满 4 票 +8",
    rationale:
      "半年分桶验证：≥3 票组胜率显著高于 2 票组，投票数直接反映攻击强度，按票直加不折算。",
  },
  {
    key: "wrap_quiet_package",
    label: "安静包裹",
    maxPoints: 4,
    kind: "bonus",
    scaled: false,
    gradient: "仅三线包裹（W）命中：信号日振幅 <3% 满 4 / 3~4% 得 2",
    rationale:
      "包裹日振幅是强单调轴：<4% 桶胜率 80.8%（+1.00），4~6% 桶 50.0%，≥6% 桶 0%；安静包裹才是稳定底盘。",
  },
  {
    key: "post_wrap_chain_confirm",
    label: "链式+缩量确认",
    maxPoints: 8,
    kind: "bonus",
    scaled: false,
    gradient: "仅上沿确认（Z）命中：链式确认 +6；确认日 5/10 均量比 <0.9 再 +2",
    rationale:
      "两日链式结构池内胜率 69.0%（+0.86）与 X 同档；缩量确认桶 71.4%（+1.49）显著强于放量桶 60%（+0.37）。",
  },
];

export function buildScoreTable(family: GuideFamilyKey): GuideScoreTable {
  if (family === "trend_pullback") {
    return {
      family,
      components: TREND_SCORE_COMPONENTS,
      maxScoreText: "100",
      formula: "总分 = 9 个梯度分量直加（无门禁），封顶 100",
    };
  }
  return {
    family,
    components: OVERSOLD_SCORE_COMPONENTS,
    maxScoreText: "≈70",
    formula:
      "总分 = 基础分量之和 ×0.4 + P1 附加分 + P1.5 路径附加（X/Y 投票 / W 安静包裹 / Z 链式确认，均不折算）→ 满值约 70；换手率门禁失败封顶 39",
  };
}

/** 超跌诊断分满值口径：基础 100 × 0.4 + P1 附加 10 + 路径附加 12/8（spec 硬断言防转录漂移）。 */
export function oversoldScoreCeiling(): number {
  const scaled = OVERSOLD_SCORE_COMPONENTS.filter(
    (c) => c.kind === "bonus" && c.scaled,
  ).reduce((sum, c) => sum + c.maxPoints, 0);
  const unscaled = OVERSOLD_SCORE_COMPONENTS.filter(
    (c) => c.kind === "bonus" && !c.scaled,
  ).reduce((sum, c) => sum + c.maxPoints, 0);
  return scaled * 0.4 + unscaled;
}

/** 后端案例 → 前端视图模型。 */
function toGuideCase(item: GuideCaseItem): GuideCase {
  return {
    caseId: item.case_id,
    name: item.name,
    vtSymbol: item.vt_symbol,
    signalDate: item.signal_date,
    setupType: item.setup_type,
    narrativeStartDate: item.narrative_start_date,
    expectedLaunchDate: item.expected_launch_date,
    narrativeStatus: item.narrative_status,
    returns: {
      d1: item.returns.d1_close_return_pct,
      d3: item.returns.d3_close_return_pct,
      d5: item.returns.d5_close_return_pct,
      status: item.returns.status,
    },
  };
}

/** 把后端按 rule_key 归组的案例挂到内容节点上（纯函数，输入不可变）。 */
export function mergeCasesIntoRules(
  nodes: GuideRuleNode[],
  payload: GuideCasesPayload,
): MergedGuideRules {
  const casesByRule = new Map<string, GuideCase[]>();
  for (const family of payload.families) {
    for (const rule of family.rules) {
      casesByRule.set(rule.rule_key, rule.cases.map(toGuideCase));
    }
  }
  return {
    nodes: nodes.map((node) => ({
      ...node,
      cases: casesByRule.get(node.ruleKey) ?? [],
    })),
    orphanCases: payload.orphan_cases.map(toGuideCase),
  };
}
