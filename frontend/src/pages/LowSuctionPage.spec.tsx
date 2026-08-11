import { describe, expect, it } from "vitest";

import { LOW_SUCTION_LIVE_REFRESH_INTERVAL_MS } from "./LowSuctionPage";

describe("LowSuctionPage live refresh cadence", () => {
  it("polls the lightweight persisted snapshot once per minute", () => {
    expect(LOW_SUCTION_LIVE_REFRESH_INTERVAL_MS).toBe(60 * 1000);
  });
});
