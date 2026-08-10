import { describe, expect, it } from "vitest";

import { LOW_SUCTION_LIVE_REFRESH_INTERVAL_MS } from "./LowSuctionPage";

describe("LowSuctionPage live refresh cadence", () => {
  it("refreshes the live recommendation query every fifteen minutes", () => {
    expect(LOW_SUCTION_LIVE_REFRESH_INTERVAL_MS).toBe(15 * 60 * 1000);
  });
});
