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
  /** 打板预备徽章：B 涨停弱转强信号日收盘涨停，按打板预备语义理解。 */
  anchorTag?: "board_ready";
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
        "信号日收于涨停的主板票剔除——例外：趋势族两条涨停路径（弱转强/补涨涨停，打板确认语义）专门放行",
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
        "趋势族 2026-08-17 涨停确认制定稿：P1.5 涨停弱转强（段顶 ≤4 日低开拉板）+ P1 补涨涨停 N 字板（段顶 5-30 日平开进攻板，70.7% 跨行情双正）+ 连板回落低吸观察层（进推荐不占仓位），非涨停弱转强为研究锚点不进推荐",
      ],
    },
    {
      key: "scoring",
      no: "03",
      zh: "诊断评分",
      en: "DIAGNOSTIC SCORE",
      note: "同族同层内比较形态完整度，不是收益概率",
      bullets: [
        "趋势族：公共底盘因子满 100 ×0.4（连板高度/距顶甜点/收盘控制/量能枯竭/换手承接）+ 路径组件因子直加（涨停弱转强吃低开深度+拉板力度+高连板，补涨涨停吃平开直接性+换手甜点+量能恢复），满值约 70",
        "超跌族：基础分量 ×0.4 + 路径附加分（P1 两条 / X/Y 攻击强度投票 / W 安静包裹 / Z 链式确认，不折算），满值约 70，两族同量纲",
        "换手率 ≥8% 触发超跌门禁：不改变规则命中，但诊断分封顶 39；趋势族无换手门禁（妖股 20-38% 换手是常态）",
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
        "同层按诊断分降序；P1.5 同分时的换手决胜按族取甜点：超跌接近 3%（中等活跃），趋势妖股接近 25%（承接充分）",
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
 * 趋势族 3 条规则（2026-08 连板后补涨/弱转强重构，十轮研究定稿）。
 * 谓词转录自 daily_factor_extended_discovery.py process_rule_predicates 的
 * LIMIT_UP_* 三条目与常量区 LIMIT_UP_* 阈值。
 */
const TREND_RULE_NODES: GuideRuleNode[] = [
  {
    ruleKey: "limit_up_weak_to_strong_reclaim",
    family: "trend_pullback",
    shortLabel: "涨停弱转强（打板预备）",
    tier: "product",
    productTier: "P1.5",
    anchorTag: "board_ready",
    conditions: [
      "近 60 交易日内存在 ≥4 连板的主段（连板史递推窗口完整）",
      "信号日距主段段顶 ≤4 个交易日（刚破坏、情绪还热）",
      "当日低开：开盘价不高于昨收（open ≤ 0%）",
      "盘中拉回并收盘涨停——唯一放行「信号日收盘涨停」的路径（打板预备）",
    ],
    evidence:
      "两年全市场 n=318 胜率 60.4%/D+1 +1.69，每日前五模拟两年 +173%/回撤 −16%，半年 +38.9%/回撤 −2.0%（胜率 71.9%）。4 个主人案例（双成/国芳/航天 11-24/恒尚）当日全部前五。涨停收盘价买入为探索级口径，实盘按次日打板预备理解。",
    chartHint:
      "看低开大阴预期如何被一根放量阳线直接拉回涨停——「弱转强」的最强确认",
  },
  {
    ruleKey: "limit_up_pullback_rebound",
    family: "trend_pullback",
    shortLabel: "补涨涨停（N 字板）",
    tier: "product",
    productTier: "P1",
    anchorTag: "board_ready",
    conditions: [
      "近 60 交易日内存在 ≥5 连板的主段（窗口完整）",
      "主段段顶后 5~30 个交易日（回落蓄势期，区别于刚破坏的弱转强窗）",
      "D 日收盘涨停——二波启动的确认板（信号日收盘涨停由产品层专门放行）",
      "平开直接进攻：开盘涨跌 0~3%（不低开抢跑也不高开追高）",
      "换手 <20%（10~20% 甜点；≥20% 过热次日崩）",
      "量能恢复到主段峰值的 >30%（30~60% 健康；缩量反抽走不出新高）",
    ],
    evidence:
      "两年全市场 n=157 胜率 70.7%/D+1 +3.00，强市 66.3%/弱市 79.2% 双正（跨行情通用因子）。买入价研究：信号日打板价买（70.7%）优于次日竞价买（57.9%/+1.02）——竞价 gap 2~5% 是备用入场窗（76.9%），gap ≥5% 追高死、低开放弃。案例：华电辽能 4-22（D+1 +9.96）、福达合金 6-15（+10.01）、九牧王 12-18（+9.97）。",
    chartHint:
      "看连板段回落蓄势两周后的第一根平开进攻板：量能恢复到主段三成以上、换手温和不爆",
  },
  {
    ruleKey: "limit_up_pullback_watchlist",
    family: "trend_pullback",
    shortLabel: "连板回落低吸观察",
    tier: "product",
    conditions: [
      "近 60 交易日内存在 ≥5 连板的主段（窗口完整）",
      "主段段顶后 5~30 个交易日的回落蓄势期",
      "D 日小阳企稳：收盘 ≥ 开盘、收盘涨幅 ≥-2.5%（收盘控制）",
      "量能温和：当日量 ≤ 近 5 日均量的 1.15 倍",
      "段顶后日均换手 5~20%（资金还在且未出货的承接区）",
    ],
    evidence:
      "补涨涨停的预备窗口：主人 8 个 A 案例（科森 10-28/伟时/国芳/诺德/九牧王 11-27/航天 12-23/华电 4-20/福达 6-4）的低吸日形态本体——当天买入的 D+1 优势有限（50.8%/+0.23），价值是预告未来数日可能出现 N 字板（科森次日、华电次日、福达 9 日后）。进推荐页展示盯盘用，不占回测仓位。",
    chartHint:
      "对照看低吸观察日与随后出现的补涨涨停板的关系：观察层是雷达，N 字板才是扣扳机",
  },
  {
    ruleKey: "research_weak_to_strong_turnover_no_limit",
    family: "trend_pullback",
    shortLabel: "非涨停弱转强（研究锚点）",
    tier: "research",
    conditions: [
      "近 60 交易日内存在 ≥4 连板的主段",
      "主段段顶后 ≤3 个交易日内（破坏后的承接窗）",
      "换手 ≥8%（承接活跃）且 D 日收盘未涨停",
      "深水承接拉起：收盘脱离当日低点 ≥4pct，或盘中低点深水（≤ 昨收 -6%）",
    ],
    evidence:
      "主人 8 个案例（哈药/航天 11-27/科森 8-26/传智/安记/梦天/锋龙/兴业）的形态本体，但全市场两年验证为负边缘（37~42% 胜率/D+1 −1.3~−2.0，各维度分桶均无正口袋；好/坏票六维度分布完全重叠）——形态有案例价值、统计无边缘，诚实留研究锚点不进推荐。",
    chartHint:
      "对照看案例 K 线：深水拉起的形态确实震撼，但同形态全市场大多次日继续跌",
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
 * 趋势族评分分量（转录自 daily_picks_scoring.py，2026-08 连板后补涨/弱转强
 * 重构版：公共底盘 5 分量满 100 ×0.4 + 路径组件 6 分量 ≤30 直加 = 满 70）。
 */
const TREND_SCORE_COMPONENTS: GuideScoreComponent[] = [
  {
    key: "limit_up_streak_strength",
    label: "连板高度",
    maxPoints: 22,
    kind: "bonus",
    scaled: true,
    gradient: "主段 7-9 连板满 22 / ≥10 得 18 / 4-6 得 16",
    rationale: "两年全市场 7-9 板桶 54%/+0.73 最甜；十板以上情绪透支、四板以下动力不足。",
  },
  {
    key: "pullback_timing",
    label: "距顶甜点",
    maxPoints: 18,
    kind: "bonus",
    scaled: true,
    gradient: "段顶后 ≤4 日满 18（弱转强窗）/ 5-9 得 13 / 10-17 得 11 / 18-24 得 7 / 25-30 得 13",
    rationale: "刚破坏（≤4 日）承接还热；深回落 25-30 日是二次蓄势甜点，18-24 日是中间的无人区。",
  },
  {
    key: "close_control",
    label: "收盘控制",
    maxPoints: 20,
    kind: "bonus",
    scaled: true,
    gradient: "收盘脱离当日低点 ≥8pct 满 20 / 4-8 得 15 / 2-4 得 9 / <2 得 4",
    rationale: "主人文案的「收盘控制价格」：收盘拉离低点越远，控盘越强（A 池 ≥80% 位置桶 51.3%）。",
  },
  {
    key: "volume_dryness",
    label: "量能枯竭",
    maxPoints: 22,
    kind: "bonus",
    scaled: true,
    gradient: "量能为主段峰值 ≤10% 满 22 / ≤20% 得 16 / ≤40% 得 9 / >40% 得 4",
    rationale: "回落期量能萎缩到主段峰值的 5-10% 桶 55.1%/+0.22——抛压枯竭是补涨的地基。",
  },
  {
    key: "turnover_activity",
    label: "换手承接",
    maxPoints: 18,
    kind: "bonus",
    scaled: true,
    gradient: "换手 ≥20% 满 18 / 8-20% 得 13 / 3-8% 得 8 / <3% 得 3",
    rationale: "妖股低吸需要活跃承接；趋势族不设换手门禁（20-38% 换手是常态）。",
  },
  {
    key: "reclaim_open_depth",
    label: "低开深度(B)",
    maxPoints: 10,
    kind: "bonus",
    gradient: "涨停弱转强路径：开盘 ≤-3% 满 10 / ≤0% 得 6",
    rationale: "低开越深，拉板的「弱转强」反差越强（低开拉板池 60.4%/+1.69）。",
  },
  {
    key: "reclaim_magnitude",
    label: "拉板力度(B)",
    maxPoints: 12,
    kind: "bonus",
    gradient: "收盘脱离低点 ≥12pct 满 12 / ≥8 得 8 / ≥4 得 4",
    rationale: "从深水直接拉到涨停的力度是 B 路径核心证据。",
  },
  {
    key: "reclaim_streak_premium",
    label: "高连板加成(B)",
    maxPoints: 8,
    kind: "bonus",
    gradient: "主段 ≥7 连板 +8",
    rationale: "高连板妖股的弱转强反核弹性最强。",
  },
  {
    key: "pullback_flat_open_direct",
    label: "平开直接性(A)",
    maxPoints: 10,
    kind: "bonus",
    gradient: "开盘 0~1% 满 10 / 1~2% 得 7 / 2~3% 得 4",
    rationale: "补涨涨停喜欢从容平开（0~3% 桶 64.6%）：不低开抢跑（那是 B 的逻辑）也不高开追高（>3% 桶 50.8%）。",
  },
  {
    key: "pullback_turnover_sweet",
    label: "换手甜点(A)",
    maxPoints: 12,
    kind: "bonus",
    gradient: "换手 10~20% 满 12 / <10% 得 8",
    rationale: "换手 10~20% 桶 63.5%/+2.16 是甜点；≥20% 过热桶崩到 45.3%/−0.08。",
  },
  {
    key: "pullback_volume_recovery",
    label: "量能恢复(A)",
    maxPoints: 8,
    kind: "bonus",
    gradient: "量能为主段峰值 30~60% 满 8 / >60% 得 4",
    rationale: "量能恢复到主段三到六成最健康（63.5%/+2.32）：地量只是反抽走不出新高，>60% 过热。",
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
      maxScoreText: "≈70",
      formula:
        "总分 = 公共底盘 5 分量之和 ×0.4（连板高度/距顶甜点/收盘控制/量能枯竭/换手承接）+ 路径组件直加（B 低开深度/拉板力度/高连板，或 A 平开直接性/换手甜点/量能恢复，≤30）→ 满值约 70，与超跌族同量纲；无换手门禁",
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

/** 趋势诊断分满值口径：底盘 100 × 0.4 + 单路径组件 30（B/A 互斥，spec 硬断言防转录漂移）。 */
export function trendScoreCeiling(): number {
  const scaled = TREND_SCORE_COMPONENTS.filter(
    (c) => c.kind === "bonus" && c.scaled,
  ).reduce((sum, c) => sum + c.maxPoints, 0);
  const reclaim = TREND_SCORE_COMPONENTS.filter(
    (c) => c.kind === "bonus" && !c.scaled && c.key.startsWith("reclaim_"),
  ).reduce((sum, c) => sum + c.maxPoints, 0);
  const pullback = TREND_SCORE_COMPONENTS.filter(
    (c) => c.kind === "bonus" && !c.scaled && c.key.startsWith("pullback_"),
  ).reduce((sum, c) => sum + c.maxPoints, 0);
  return scaled * 0.4 + Math.max(reclaim, pullback);
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
