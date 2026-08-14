import { describe, expect, it } from "vitest";

import type { LadderLeaderDay } from "@/api/lianban";
import {
  leaderRunDateLabel,
  leaderRunStreakLabel,
  mergeLeaderRuns,
} from "./LeaderTrackCard";

function makeLeader(
  tradeDate: string,
  name: string,
  streak: number,
  overrides: Partial<LadderLeaderDay> = {},
): LadderLeaderDay {
  return {
    trade_date: tradeDate,
    vt_symbol: overrides.vt_symbol ?? `TEST-${name}`,
    name,
    streak,
    is_one_word: false,
    ...overrides,
  };
}

/** 近60日真实轨迹缩影: 宝鼎科技5板(08-10) → 百花医药6→7板(08-11~08-12) → 秦安股份5板(08-13)。 */
function makeRealTrajectory(): LadderLeaderDay[] {
  return [
    makeLeader("2026-08-10", "宝鼎科技", 5, { vt_symbol: "002552.SZSE" }),
    makeLeader("2026-08-11", "百花医药", 6, { vt_symbol: "600721.SSE" }),
    makeLeader("2026-08-12", "百花医药", 7, { vt_symbol: "600721.SSE" }),
    makeLeader("2026-08-13", "秦安股份", 5, { vt_symbol: "603758.SSE", is_one_word: true }),
  ];
}

describe("mergeLeaderRuns（连续同一只合并为区间行）", () => {
  it("merges consecutive days of the same leader into one run", () => {
    const runs = mergeLeaderRuns(makeRealTrajectory());
    expect(runs).toHaveLength(3);
    const baihua = runs.find((run) => run.name === "百花医药");
    expect(baihua).toMatchObject({
      startDate: "2026-08-11",
      endDate: "2026-08-12",
      startStreak: 6,
      endStreak: 7,
      days: 2,
    });
  });

  it("keeps single-day leaders as unmerged runs", () => {
    const runs = mergeLeaderRuns(makeRealTrajectory());
    const qinan = runs.find((run) => run.name === "秦安股份");
    expect(qinan).toMatchObject({
      startDate: "2026-08-13",
      endDate: "2026-08-13",
      startStreak: 5,
      endStreak: 5,
      days: 1,
    });
  });

  it("orders runs by end date descending (最新在上)", () => {
    const runs = mergeLeaderRuns(makeRealTrajectory());
    expect(runs.map((run) => run.name)).toEqual(["秦安股份", "百花医药", "宝鼎科技"]);
  });

  it("sorts unsorted input by date before merging", () => {
    const shuffled = [...makeRealTrajectory()].reverse();
    const runs = mergeLeaderRuns(shuffled);
    const baihua = runs.find((run) => run.name === "百花医药");
    expect(baihua).toMatchObject({ startDate: "2026-08-11", endDate: "2026-08-12", days: 2 });
  });

  it("starts a new run when the same leader returns after a break", () => {
    const leaders = [
      makeLeader("2026-08-06", "甲", 3, { vt_symbol: "A.SSE" }),
      makeLeader("2026-08-07", "乙", 4, { vt_symbol: "B.SSE" }),
      makeLeader("2026-08-10", "甲", 4, { vt_symbol: "A.SSE" }),
    ];
    const runs = mergeLeaderRuns(leaders);
    expect(runs.filter((run) => run.vtSymbol === "A.SSE")).toHaveLength(2);
  });

  it("flags the run as 一字 if any day in it was a one-word board", () => {
    const leaders = [
      makeLeader("2026-08-11", "百花医药", 6, { vt_symbol: "600721.SSE" }),
      makeLeader("2026-08-12", "百花医药", 7, { vt_symbol: "600721.SSE", is_one_word: true }),
    ];
    expect(mergeLeaderRuns(leaders)[0].isOneWord).toBe(true);
  });

  it("returns an empty array for empty input", () => {
    expect(mergeLeaderRuns([])).toEqual([]);
  });
});

describe("leaderRunDateLabel（区间日期标签）", () => {
  it("renders a single day as MM-DD", () => {
    const [run] = mergeLeaderRuns([makeLeader("2026-08-13", "秦安股份", 5)]);
    expect(leaderRunDateLabel(run)).toBe("08-13");
  });

  it("renders a multi-day run as start~end", () => {
    const runs = mergeLeaderRuns(makeRealTrajectory());
    const baihua = runs.find((run) => run.name === "百花医药");
    expect(baihua && leaderRunDateLabel(baihua)).toBe("08-11~08-12");
  });
});

describe("leaderRunStreakLabel（板数标签）", () => {
  it("renders a single day / unchanged streak as N板", () => {
    const [run] = mergeLeaderRuns([makeLeader("2026-08-13", "秦安股份", 5)]);
    expect(leaderRunStreakLabel(run)).toBe("5板");
  });

  it("renders a progressing run as start→end板", () => {
    const runs = mergeLeaderRuns(makeRealTrajectory());
    const baihua = runs.find((run) => run.name === "百花医药");
    expect(baihua && leaderRunStreakLabel(baihua)).toBe("6→7板");
  });
});
