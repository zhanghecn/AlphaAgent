import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchLimitUpStrategyGuide } from "@/api/limitUp";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("limit-up strategy guide API", () => {
  it("loads the reviewed guide from the read-only endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      success: true,
      data: {
        guide_version: "limit-up-strategy-guide-v1",
        strategy: { selection_no_lookahead: true },
      },
      error: null,
      request_id: "test",
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchLimitUpStrategyGuide()).resolves.toMatchObject({
      strategy: { selection_no_lookahead: true },
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/limit-up/strategy-guide",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });
});
