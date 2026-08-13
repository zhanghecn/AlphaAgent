import { describe, expect, it } from "vitest";

import { formatCapturedAt } from "./FirstBoardLeaderPage";

describe("FirstBoardLeaderPage", () => {
  it("shows the source capture time in the Shanghai trading timezone", () => {
    expect(formatCapturedAt("2026-08-12T02:02:03+00:00")).toBe("10:02:03 更新");
  });
});
