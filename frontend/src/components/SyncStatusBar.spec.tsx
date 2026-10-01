import { describe, expect, it } from "vitest";
import { poolPhase } from "./SyncStatusBar";

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function tomorrowStr(): string {
  const d = new Date(Date.now() + 86_400_000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

describe("SyncStatusBar.poolPhase 池语义四态", () => {
  it("stale 回退:显示旧池+明日池未算好", () => {
    const r = poolPhase("2026-09-28", true);
    expect(r.label).toContain("2026-09-28 池（最近可用）");
    expect(r.label).toContain("明日池未算好");
    expect(r.tone).toContain("amber");
  });

  it("tradeDate 在今天之后:明日池已就绪(绿)", () => {
    const r = poolPhase(tomorrowStr(), false);
    expect(r.label).toContain("明日池 · 已就绪");
    expect(r.tone).toContain("emerald");
  });

  it("今天+非stale:盘中或今日终态二选一,文案都不含「最近可用」", () => {
    const r = poolPhase(todayStr(), false);
    expect(["今日池 · 盘中每分钟刷新", "今日终态 · 明日池今晚盘后主链算好后切换"]).toContain(r.label);
  });
});
