import { describe, expect, it } from "vitest";

import type { GuideCasesPayload } from "@/api/lowSuction";
import {
  buildGuideStages,
  buildRuleNodes,
  buildScoreTable,
  mergeCasesIntoRules,
  oversoldScoreCeiling,
  trendScoreCeiling,
  type GuideRuleNode,
} from "./guideContent";

/** 后端 DISCOVERY_RULES 的权威 key 清单（daily_factor_extended_discovery.py）。 */
const BACKEND_RULE_KEYS = {
  trend_pullback: [
    "limit_up_weak_to_strong_reclaim",
    "limit_up_pullback_rebound",
    "limit_up_pullback_watchlist",
    "research_weak_to_strong_turnover_no_limit",
  ],
  oversold_rebound: [
    "first_leg_two_ma_body_wrap_before_ma30",
    "research_oversold_three_ma_wrap_stable_base",
    "post_wrap_upper_band_reclaim_confirmation",
    "staged_ma10_support_before_ma30_convergence_shrink",
    "attack_body_hold_after_ma10_ma20_cross_before_ma30",
    "pre_cross_acceleration_weak_market",
    "price_first_strong_attack",
    "ma10_ma20_contact_pre_cross_positive_volume_expand",
    "ma10_ma30_retest_after_actual_cross_two_leg_volume",
  ],
} as const;

function fakePayload(): GuideCasesPayload {
  return {
    status: "ok",
    score_version: "low-suction-daily-score-v3.4",
    families: [
      {
        key: "trend_pullback",
        label: "上升趋势低吸",
        rules: [
          {
            rule_key: "limit_up_weak_to_strong_reclaim",
            description: "涨停弱转强（打板预备）",
            tier: "product",
            product_tier: "P1.5",
            cases: [
              {
                case_id: "恒尚节能 超预期拉板",
                name: "恒尚节能 超预期拉板",
                vt_symbol: "603137.SSE",
                signal_date: "2026-07-13",
                setup_type: "trend_pullback",
                narrative_start_date: "2026-06-12",
                expected_launch_date: "2026-07-14",
                source_anchor: "process_only",
                narrative_status: "complete",
                returns: {
                  d1_close_return_pct: 9.99,
                  d3_close_return_pct: 20.0,
                  d5_close_return_pct: 33.0,
                  status: "available",
                },
              },
            ],
          },
        ],
      },
      { key: "oversold_rebound", label: "超跌反弹低吸", rules: [] },
    ],
    orphan_cases: [
      {
        case_id: "秦安股份 MA10 上穿 MA20",
        name: "秦安股份 MA10 上穿 MA20",
        vt_symbol: "603758.SSE",
        signal_date: "2026-08-06",
        setup_type: "oversold_rebound",
        narrative_start_date: null,
        expected_launch_date: null,
        source_anchor: "process_only",
        narrative_status: "research_pending",
        returns: {
          d1_close_return_pct: null,
          d3_close_return_pct: null,
          d5_close_return_pct: null,
          status: "missing_exit_session",
        },
      },
    ],
  };
}

describe("buildGuideStages", () => {
  it("五阶段管道按固定顺序", () => {
    const stages = buildGuideStages();
    expect(stages.map((s) => s.key)).toEqual([
      "filter",
      "admission",
      "scoring",
      "ranking",
      "portfolio",
    ]);
    for (const stage of stages) {
      expect(stage.zh).toBeTruthy();
      expect(stage.en).toBeTruthy();
      expect(stage.bullets.length).toBeGreaterThan(0);
    }
  });
});

describe("buildRuleNodes", () => {
  it("覆盖后端全部 13 条规则且 ruleKey 唯一", () => {
    const nodes = buildRuleNodes();
    const keys = nodes.map((n) => n.ruleKey);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys.sort()).toEqual(
      [...BACKEND_RULE_KEYS.trend_pullback, ...BACKEND_RULE_KEYS.oversold_rebound].sort(),
    );
  });

  it("族属与产品/研究分层正确", () => {
    const nodes = buildRuleNodes();
    const trend = nodes.filter((n) => n.family === "trend_pullback");
    const oversold = nodes.filter((n) => n.family === "oversold_rebound");
    expect(trend).toHaveLength(4);
    expect(oversold).toHaveLength(9);
    // 趋势 4 条产品（P1.5 涨停弱转强 + P1 补涨涨停 + 观察层 + 盘中弱转强预备）
    expect(trend.filter((n) => n.tier === "product").map((n) => n.ruleKey).sort())
      .toEqual([
        "limit_up_pullback_rebound",
        "limit_up_pullback_watchlist",
        "limit_up_weak_to_strong_reclaim",
        "research_weak_to_strong_turnover_no_limit",
      ]);
    expect(
      nodes.find((n) => n.ruleKey === "limit_up_weak_to_strong_reclaim")?.anchorTag,
    ).toBe("board_ready");
    expect(
      nodes.find((n) => n.ruleKey === "limit_up_weak_to_strong_reclaim")?.productTier,
    ).toBe("P1.5");
    expect(
      nodes.find((n) => n.ruleKey === "limit_up_pullback_rebound")
        ?.productTier,
    ).toBe("P1");
    expect(oversold.filter((n) => n.tier === "product").map((n) => n.ruleKey).sort())
      .toEqual([
        "first_leg_two_ma_body_wrap_before_ma30",
        "post_wrap_upper_band_reclaim_confirmation",
        "pre_cross_acceleration_weak_market",
        "price_first_strong_attack",
        "research_oversold_three_ma_wrap_stable_base",
        "staged_ma10_support_before_ma30_convergence_shrink",
      ]);
    for (const p15 of [
      "first_leg_two_ma_body_wrap_before_ma30",
      "post_wrap_upper_band_reclaim_confirmation",
      "pre_cross_acceleration_weak_market",
      "price_first_strong_attack",
      "research_oversold_three_ma_wrap_stable_base",
    ]) {
      expect(nodes.find((n) => n.ruleKey === p15)?.productTier).toBe("P1.5");
    }
    expect(
      nodes.find(
        (n) => n.ruleKey === "staged_ma10_support_before_ma30_convergence_shrink",
      )?.productTier,
    ).toBe("P1");
  });

  it("每个节点都有说明书内容（短名/条件/证据/图表看点）", () => {
    for (const node of buildRuleNodes()) {
      expect(node.shortLabel).toBeTruthy();
      expect(node.conditions.length).toBeGreaterThan(0);
      expect(node.evidence).toBeTruthy();
      expect(node.chartHint).toBeTruthy();
    }
  });
});

describe("buildScoreTable", () => {
  it("趋势族底盘 5 分量（×0.4）+ 路径 6 分量，折算后满值约 70（与超跌同量纲）", () => {
    const table = buildScoreTable("trend_pullback");
    expect(table.components).toHaveLength(11);
    expect(table.components.every((c) => c.kind === "bonus")).toBe(true);
    const scaled = table.components.filter((c) => c.scaled);
    expect(scaled.reduce((sum, c) => sum + c.maxPoints, 0)).toBe(100);
    const reclaim = table.components
      .filter((c) => !c.scaled && c.key.startsWith("reclaim_"))
      .reduce((sum, c) => sum + c.maxPoints, 0);
    const pullback = table.components
      .filter((c) => !c.scaled && c.key.startsWith("pullback_"))
      .reduce((sum, c) => sum + c.maxPoints, 0);
    expect(reclaim).toBe(30);
    expect(pullback).toBe(30);
    expect(trendScoreCeiling()).toBe(70);
    expect(table.maxScoreText).toBe("≈70");
  });

  it("超跌族 1 门禁 + 15 分量，折算后满值约 70（与趋势不同量纲）", () => {
    const table = buildScoreTable("oversold_rebound");
    expect(table.components).toHaveLength(16);
    const gates = table.components.filter((c) => c.kind === "gate");
    expect(gates).toHaveLength(1);
    expect(gates[0].key).toBe("turnover_gate");
    // 基础分量（经 0.4 折算）满值 100 → 折算后 40；P1 附加 +10、
    // P1.5 路径附加（X/Y 投票 8 / W 安静包裹 4 / Z 链式确认 8）不折算
    const scaled = table.components.filter((c) => c.scaled);
    expect(scaled.reduce((sum, c) => sum + c.maxPoints, 0)).toBe(100);
    const unscaled = table.components.filter(
      (c) => c.kind === "bonus" && !c.scaled,
    );
    expect(unscaled.map((c) => c.key).sort()).toEqual([
      "attack_votes",
      "post_wrap_chain_confirm",
      "staged_ma30_active_participation",
      "staged_ma30_fast_convergence",
      "wrap_quiet_package",
    ]);
    expect(unscaled.reduce((sum, c) => sum + c.maxPoints, 0)).toBe(30);
    expect(oversoldScoreCeiling()).toBe(70);
    expect(table.maxScoreText).toBe("≈70");
  });
});

describe("mergeCasesIntoRules", () => {
  it("按 rule_key 把后端案例挂到节点上，孤儿案例原样透传", () => {
    const nodes = buildRuleNodes();
    const merged = mergeCasesIntoRules(nodes, fakePayload());
    const target = merged.nodes.find(
      (n) => n.ruleKey === "limit_up_weak_to_strong_reclaim",
    );
    expect(target?.cases).toHaveLength(1);
    expect(target?.cases[0].caseId).toBe("恒尚节能 超预期拉板");
    expect(target?.cases[0].returns.d5).toBe(33.0);
    expect(target?.cases[0].narrativeStartDate).toBe("2026-06-12");
    expect(merged.orphanCases).toHaveLength(1);
    expect(merged.orphanCases[0].caseId).toBe("秦安股份 MA10 上穿 MA20");
    // 无案例的规则保持空数组而不是 undefined
    const empty = merged.nodes.find(
      (n) => n.ruleKey === "limit_up_pullback_rebound",
    );
    expect(empty?.cases).toEqual([]);
  });

  it("payload 出现未知 rule_key 时忽略但不丢孤儿", () => {
    const payload = fakePayload();
    payload.families[0].rules.push({
      rule_key: "ghost_rule",
      description: "幽灵",
      tier: "research",
      product_tier: null,
      cases: [],
    });
    const merged = mergeCasesIntoRules(buildRuleNodes(), payload);
    expect(merged.nodes.every((n) => n.ruleKey !== "ghost_rule")).toBe(true);
    expect(merged.orphanCases).toHaveLength(1);
  });

  it("输入节点不可变（返回新数组）", () => {
    const nodes = buildRuleNodes();
    const merged = mergeCasesIntoRules(nodes, fakePayload());
    expect(merged.nodes).not.toBe(nodes);
    expect(
      nodes.find((n) => n.ruleKey === "limit_up_weak_to_strong_reclaim"),
    ).not.toHaveProperty("cases");
  });
});

describe("内容转录防漂移", () => {
  it("节点 ruleKey 与后端规则清单一一对应（spec 顶部清单即权威对拍）", () => {
    const nodes: GuideRuleNode[] = buildRuleNodes();
    for (const [family, keys] of Object.entries(BACKEND_RULE_KEYS)) {
      const familyKeys = nodes
        .filter((n) => n.family === family)
        .map((n) => n.ruleKey);
      expect(familyKeys.sort()).toEqual([...keys].sort());
    }
  });
});
