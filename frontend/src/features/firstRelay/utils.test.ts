import { describe, expect, it } from "vitest";

import { formatAuctionGates } from "./utils";

describe("formatAuctionGates", () => {
  it("formats empty, single, merged and union gates", () => {
    expect(formatAuctionGates(null)).toBe("—");
    expect(formatAuctionGates(undefined)).toBe("—");
    expect(formatAuctionGates("7.5_8.5")).toBe("7.5~8.5");
    expect(formatAuctionGates("7.5_9.5")).toBe("7.5~9.5");
    expect(formatAuctionGates("7.5_8.5|9.5_10")).toBe("7.5~8.5 或 9.5~10");
  });
});
