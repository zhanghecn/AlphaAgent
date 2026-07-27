import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchLimitUpHistoryStatus,
  startLimitUpHistoryRebuild,
} from "@/api/limitUp";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("limit-up history rebuild API", () => {
  it("reads the current background rebuild status", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      success: true,
      data: { status: "ready", strategy_version: "limit-up-core-abc-v2" },
      error: null,
      request_id: "test",
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchLimitUpHistoryStatus()).resolves.toMatchObject({ status: "ready" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/limit-up/history/status",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it("attaches to an already running rebuild after a 409", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        success: false,
        data: null,
        error: {
          code: "HISTORY_REBUILD_RUNNING",
          message: "全历史打板账本正在构建",
          detail: { status: "building" },
        },
        request_id: "test",
      }, 409))
      .mockResolvedValueOnce(response({
        success: true,
        data: { status: "building", strategy_version: "limit-up-core-abc-v2" },
        error: null,
        request_id: "test",
      }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(startLimitUpHistoryRebuild()).resolves.toMatchObject({
      status: "building",
      already_running: true,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
