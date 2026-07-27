import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { PreboardCandidate } from "@/api/limitUp";
import { PreboardRanking } from "./PreboardRanking";

const candidate: PreboardCandidate = {
  vt_symbol: "600009.SSE",
  name: "板前样本",
  decision_state: "observe",
  execution_mode: "research_only",
  strictly_preboard: true,
  last_price: 10.89,
  limit_price: 11,
  change_pct: 8.9,
  distance_to_limit_pct: 1.0,
  quality_priority_tier: "A_industry_expanding",
  public_quality_status: "qualified_waiting_trigger",
  quality_expected_d1_net_return_pct: 2.1,
  quality_win_probability: 0.68,
  expected_d1_net_return_pct: 2.1,
  d1_win_probability: 0.68,
  touch_probability_3m: 0.72,
  eventual_touch_probability: 0.84,
  seal_probability_given_touch: 0.75,
  probability_status: "ready",
  source_quality: "sampled_quote_proxy",
  updated_at: "2026-07-23T10:18:20+08:00",
  dynamic_leader_shadow: {
    policy_version: "dynamic-concept-leader-shadow-v1",
    status: "locked",
    execution_effect: "none_research_only",
    market_gate_passed: false,
    concept_id: "BK0815",
    concept_name: "存储芯片",
    concept_state: "launch",
    concept_leader_rank: 2,
    locked_at: "2026-07-23T10:17:50+08:00",
    observed_frames: 4,
    eligible_frames: 3,
    consecutive_eligible_frames: 2,
    persistence_ratio: 0.75,
    drop_count: 1,
    current_concept_top5: true,
    global_rank: 1,
    global_top5: true,
  },
};

describe("pre-board probability ranking", () => {
  it("shows the fused ranking as research instead of a buy instruction", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PreboardRanking candidates={[candidate]} />
      </MemoryRouter>,
    );

    expect(html).toContain("板前概率排序");
    expect(html).toContain("研究观察，不触发买入提醒");
    expect(html).toContain("D+1预期");
    expect(html).toContain("质量胜率");
    expect(html).toContain("A · 板块扩张");
    expect(html).toContain("3分钟触板");
    expect(html).toContain("72.00%");
    expect(html).toContain("84.00%");
    expect(html).toContain("存储芯片");
    expect(html).toContain("题材第2");
    expect(html).toContain("跟踪 Top 1");
    expect(html).toContain("市场暂停");
    expect(html).not.toContain("买入条件");
  });

  it("renders nothing when no high-quality pre-board row is active", () => {
    expect(renderToStaticMarkup(<PreboardRanking candidates={[]} />)).toBe("");
  });

  it("labels formal mode as an unlimited recommendation source", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PreboardRanking candidates={[{
          ...candidate,
          decision_state: "actionable",
          execution_mode: "formal",
        }]} />
      </MemoryRouter>,
    );

    expect(html).toContain("正式模型运行中，达标买点进入全量推荐");
    expect(html).not.toContain("影子观察");
  });

  it("hides a row as soon as it is no longer strictly pre-board", () => {
    expect(renderToStaticMarkup(
      <PreboardRanking candidates={[{ ...candidate, strictly_preboard: false }]} />,
    )).toBe("");
  });

  it("shows membership but does not claim a leader before theme launch", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PreboardRanking candidates={[{
          ...candidate,
          dynamic_leader_shadow: {
            ...candidate.dynamic_leader_shadow!,
            status: "waiting_theme",
            market_gate_passed: true,
            concept_name: "机器人",
            concept_leader_rank: 3,
            locked_at: null,
            current_concept_top5: false,
            global_rank: null,
            global_top5: false,
          },
        }]} />
      </MemoryRouter>,
    );

    expect(html).toContain("机器人");
    expect(html).toContain("尚未形成龙位");
    expect(html).toContain("题材未启动");
    expect(html).not.toContain("题材待识别");
    expect(html).not.toContain("龙位待定");
  });
});
