import { describe, expect, it } from "vitest";

import type { LimitUpLiveSignal } from "@/api/limitUp";
import { buyAlertSpeechText, formatSpeechPct } from "./speechAlert";

function buildSignal(overrides: Partial<LimitUpLiveSignal> = {}): LimitUpLiveSignal {
  return {
    vt_symbol: "002636.SZSE",
    name: "金安国纪",
    change_pct: 7.23,
    distance_to_limit_pct: 2.11,
    strategy_name: "弱市题材进攻",
    ...overrides,
  } as LimitUpLiveSignal;
}

describe("buyAlertSpeechText", () => {
  it("朗读股票名、涨幅和距板", () => {
    expect(buyAlertSpeechText(buildSignal())).toBe(
      "买点提醒，金安国纪，现涨 7.2%，距板 2.1%，弱市题材进攻",
    );
  });

  it("缺失数值字段时省略对应片段", () => {
    expect(
      buyAlertSpeechText(buildSignal({ change_pct: null, distance_to_limit_pct: null })),
    ).toBe("买点提醒，金安国纪，弱市题材进攻");
  });

  it("没有股票名时回退到代码", () => {
    expect(buyAlertSpeechText(buildSignal({ name: "" }))).toContain("002636.SZSE");
  });
});

describe("formatSpeechPct", () => {
  it("保留一位小数", () => {
    expect(formatSpeechPct(7.23)).toBe("7.2%");
  });
});
