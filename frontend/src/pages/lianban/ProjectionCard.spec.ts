import { describe, expect, it } from "vitest";

import type { LianbanProjection } from "@/api/lianban";
import {
  buildProjectionModel,
  formatRatioPctInt,
  formatSignedDegree,
  phaseLabelWithQi,
} from "./ProjectionCard";

function makeProjection(
  overrides: Partial<LianbanProjection> = {},
): LianbanProjection {
  return {
    trade_date: "2026-08-13",
    phase: "ebb",
    phase_label: "退潮",
    phase_day: 1,
    above_ma250: false,
    sample_count: 96,
    next_day: { up_prob: 0.51, avg_change: -0.03, median_change: -0.05 },
    phase_next: [
      { phase: "ebb", label: "退潮", count: 32, ratio: 0.33 },
      { phase: "repair", label: "修复", count: 24, ratio: 0.25 },
    ],
    score_change_avg: 4.0,
    scene_dates: [
      { date: "2026-07-22", next_change: 0.2, next_phase: "修复" },
      { date: "2024-09-18", next_change: 0.7, next_phase: "修复" },
      { date: "2024-05-06", next_change: -1.2, next_phase: "退潮" },
    ],
    status: "ready",
    ...overrides,
  };
}

describe("formatRatioPctInt", () => {
  it("rounds to an integer percentage", () => {
    expect(formatRatioPctInt(0.33)).toBe("33%");
    expect(formatRatioPctInt(0.875)).toBe("88%");
    expect(formatRatioPctInt(1)).toBe("100%");
    expect(formatRatioPctInt(0)).toBe("0%");
  });

  it("handles null and NaN", () => {
    expect(formatRatioPctInt(null)).toBe("--");
    expect(formatRatioPctInt(Number.NaN)).toBe("--");
  });
});

describe("formatSignedDegree", () => {
  it("keeps integers without decimals and adds a sign", () => {
    expect(formatSignedDegree(4)).toBe("+4°");
    expect(formatSignedDegree(-3)).toBe("-3°");
  });

  it("keeps one decimal for fractional values", () => {
    expect(formatSignedDegree(4.25)).toBe("+4.3°");
    expect(formatSignedDegree(-2.5)).toBe("-2.5°");
  });

  it("handles zero and null", () => {
    expect(formatSignedDegree(0)).toBe("0°");
    expect(formatSignedDegree(null)).toBe("--");
  });
});

describe("phaseLabelWithQi", () => {
  it("appends 期 when missing", () => {
    expect(phaseLabelWithQi("退潮")).toBe("退潮期");
  });

  it("keeps labels that already end with 期", () => {
    expect(phaseLabelWithQi("退潮期")).toBe("退潮期");
  });
});

describe("buildProjectionModel", () => {
  it("builds subtitle, four cells and chips from a full payload", () => {
    const model = buildProjectionModel(makeProjection());

    expect(model.subtitle).toBe("退潮期 第1天 · 🐻年线下方 · 同景 96 次");
    expect(model.insufficient).toBe(false);

    expect(model.cells).toEqual([
      { key: "up_prob", title: "次日上涨概率", value: "51.0%" },
      {
        key: "avg_change",
        title: "次日上证均值",
        value: "-0.0%",
        tone: "fall",
      },
      { key: "phase_next", title: "最可能去向", value: "退潮 33%" },
      {
        key: "score_change",
        title: "温度平均变化",
        value: "+4°",
        tone: "rise",
      },
    ]);

    expect(model.chips).toEqual([
      { date: "2026-07-22", text: "07-22 +0.2%", tone: "rise" },
      { date: "2024-09-18", text: "09-18 +0.7%", tone: "rise" },
      { date: "2024-05-06", text: "05-06 -1.2%", tone: "fall" },
    ]);
  });

  it("uses 🐂 for above_ma250 and joins partial subtitle parts", () => {
    const model = buildProjectionModel(
      makeProjection({ above_ma250: true, phase_day: null }),
    );
    expect(model.subtitle).toBe("退潮期 · 🐂年线上方 · 同景 96 次");
  });

  it("marks insufficient_data but keeps computed stats visible", () => {
    const model = buildProjectionModel(
      makeProjection({ status: "insufficient_data", sample_count: 3 }),
    );
    expect(model.insufficient).toBe(true);
    expect(model.subtitle).toContain("同景 3 次");
    expect(model.cells[0]?.value).toBe("51.0%");
    expect(model.cells[2]?.value).toBe("退潮 33%");
  });

  it("degrades the empty skeleton to placeholders", () => {
    const model = buildProjectionModel(
      makeProjection({
        trade_date: null,
        phase: null,
        phase_label: null,
        phase_day: null,
        above_ma250: null,
        sample_count: 0,
        next_day: { up_prob: null, avg_change: null, median_change: null },
        phase_next: [],
        score_change_avg: null,
        scene_dates: [],
        status: "insufficient_data",
      }),
    );

    expect(model.insufficient).toBe(true);
    expect(model.subtitle).toBe("同景 0 次");
    for (const cell of model.cells) {
      expect(cell.value).toBe("--");
      expect(cell.tone ?? null).toBeNull();
    }
    expect(model.chips).toEqual([]);
  });

  it("handles null chip change and zero score change as neutral", () => {
    const model = buildProjectionModel(
      makeProjection({
        score_change_avg: 0,
        scene_dates: [{ date: "2024-09-18", next_change: null, next_phase: null }],
      }),
    );
    expect(model.cells[3]?.value).toBe("0°");
    expect(model.cells[3]?.tone ?? null).toBeNull();
    expect(model.chips).toEqual([
      { date: "2024-09-18", text: "09-18 --", tone: null },
    ]);
  });

  it("shows -- for the destination cell when phase_next is empty", () => {
    const model = buildProjectionModel(makeProjection({ phase_next: [] }));
    expect(model.cells[2]?.value).toBe("--");
  });
});
