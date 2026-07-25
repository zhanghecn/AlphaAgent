import { describe, expect, it } from "vitest";

import type { LimitUpStrategyGuide } from "@/api/limitUp";
import { STAGE_META, buildRuleFlow } from "./ruleFlow";

const guide = {
  strategy: {
    entry_windows: ["10:00-11:30", "13:00-14:30"],
    max_positions: 2,
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

  it("第一步固定正式策略不变边界", () => {
    const gate = buildRuleFlow(guide)[0];
    expect(gate.title).toContain("正式策略边界");
    const labels = gate.thresholds.map((t) => t.label);
    expect(labels).toContain("正式首板");
    expect(labels).toContain("二进三");
  });

  it("雷达节点把 3% 定义为观察起点而非固定买点", () => {
    const radar = buildRuleFlow(guide).find((node) => node.stage === "radar")!;
    expect(radar.thresholds.some((t) => t.value.includes("3%"))).toBe(true);
    expect(radar.thresholds).toContainEqual({ label: "固定买点", value: "无" });
    expect(radar.condition).toContain("5%、8%、9% 和 9.5% 都不是固定买点");
  });

  it("概率不可用时不把内部样本公开成观察候选", () => {
    const momentum = buildRuleFlow(guide).find((node) => node.stage === "momentum")!;

    expect(momentum.failHint).toContain("不公开板前候选");
  });

  it("成交节点含买入窗口与仓位动态值", () => {
    const fill = buildRuleFlow(guide).find((node) => node.stage === "fill")!;
    expect(fill.thresholds.some((t) => t.value.includes("10:00-11:30"))).toBe(true);
    expect(fill.thresholds.some((t) => t.value.includes("2 仓"))).toBe(true);
    expect(fill.title).toContain("补充正式板前买点");
    expect(fill.condition).toContain("扫板兜底始终保留");
    expect(fill.condition).not.toContain("整体替换");
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
