import { describe, expect, it } from "vitest";

import type { LimitUpStrategyGuide } from "@/api/limitUp";
import { STAGE_META, buildRuleFlow } from "./ruleFlow";

const guide = {
  strategy: {
    entry_windows: ["10:00-11:30", "13:00-14:30"],
    max_positions: 2,
  },
  core_quality: {
    contract_version: "limit-up-core-abc-v1",
    prior_limit_window_days: 126,
    minimum_prior_limit_count: 2,
    maximum_prior_limit_count: 6,
    a_tier_industry_turnover_ratio_5d: 1,
    b_tier_is_actionable: true,
    b_first_board_minimum_time: "10:30",
    c_tier_is_actionable: true,
    c_daily_limit: 1,
    priority_rule: "同一时点A优先于C、C优先于B",
  },
  selection_steps: [
    { order: 1, title: "限定可交易范围", rule: "仅主板首板和二进三。", timing: "盘中已知" },
  ],
  preboard_decision: {
    observation_min_change_pct: 3,
    ranking_order: [
      "同股D+1预期净收益",
      "同股D+1胜率",
      "3分钟触板概率",
      "最终触板概率",
    ],
  },
  field_groups: [
    { key: "intraday", label: "盘中实时字段", selection_allowed: true, fields: ["当前价"] },
  ],
} as unknown as LimitUpStrategyGuide;

describe("buildRuleFlow", () => {
  it("生成七步流程：市场门 → 板块筛选 → 雷达 → 动能 → 板块 → 排序 → 成交", () => {
    const nodes = buildRuleFlow(guide);
    expect(nodes).toHaveLength(7);
    expect(nodes.map((node) => node.stage)).toEqual([
      "gate", "filter", "radar", "momentum", "sector", "rank", "fill",
    ]);
  });

  it("第一步固定唯一正式合同", () => {
    const gate = buildRuleFlow(guide)[0];
    expect(gate.title).toContain("唯一正式合同");
    const labels = gate.thresholds.map((t) => t.label);
    expect(labels).toContain("正式合同");
    expect(labels).toContain("缺失字段");
    expect(gate.condition).toContain("失败关闭");
  });

  it("辨识度节点把 126 日 2 到 6 次设为硬门", () => {
    const radar = buildRuleFlow(guide).find((node) => node.stage === "radar")!;
    expect(radar.thresholds).toContainEqual({ label: "统计窗口", value: "126 个交易日" });
    expect(radar.thresholds).toContainEqual({ label: "最少涨停", value: "2 次" });
    expect(radar.thresholds).toContainEqual({ label: "最多涨停", value: "6 次" });
  });

  it("同一时点按 A C B 排序且 B 仍可交易", () => {
    const sector = buildRuleFlow(guide).find((node) => node.stage === "sector")!;

    expect(sector.condition).toContain("A优先于C、C优先于B");
    expect(sector.thresholds).toContainEqual({ label: "B 可交易", value: "是" });
  });

  it("成交节点含买入窗口与 D+1 统一退出", () => {
    const fill = buildRuleFlow(guide).find((node) => node.stage === "fill")!;
    expect(fill.thresholds.some((t) => t.value.includes("10:00-11:30"))).toBe(true);
    expect(fill.thresholds).toContainEqual({ label: "卖出", value: "D+1 官方收盘价" });
    expect(fill.title).toContain("统一口径");
  });

  it("每个节点都有阶段元数据（徽章配色）", () => {
    const nodes = buildRuleFlow(guide);
    for (const node of nodes) {
      expect(STAGE_META[node.stage].label).toBeTruthy();
      expect(STAGE_META[node.stage].tone).toBeTruthy();
    }
  });

  it("文案不含裸露的英文术语", () => {
    const forbidden = ["captured_at", "concept launch", "Top3", "close_price", "result_date", "sweep", "10bp"];
    const nodes = buildRuleFlow(guide);
    for (const node of nodes) {
      const blob = [node.title, node.purpose, node.condition, node.dataNote, node.failHint ?? "",
        ...node.thresholds.flatMap((t) => [t.label, t.value])].join(" ");
      for (const term of forbidden) {
        expect(blob).not.toContain(term);
      }
    }
  });
});
