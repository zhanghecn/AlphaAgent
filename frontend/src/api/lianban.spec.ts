import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "./client";
import { fetchLadderHistory, fetchLianbanDates, fetchLianbanReview } from "./lianban";

describe("lianban api client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("requests the latest review when no date is given", async () => {
    const spy = vi.spyOn(apiClient, "get").mockResolvedValue(null);
    await fetchLianbanReview();
    expect(spy).toHaveBeenCalledWith("/lianban/review");
  });

  it("passes the trade date as a query parameter", async () => {
    const spy = vi.spyOn(apiClient, "get").mockResolvedValue(null);
    await fetchLianbanReview("2026-08-13");
    expect(spy).toHaveBeenCalledWith("/lianban/review?date=2026-08-13");
  });

  it("requests the available review dates", async () => {
    const spy = vi.spyOn(apiClient, "get").mockResolvedValue(null);
    await fetchLianbanDates();
    expect(spy).toHaveBeenCalledWith("/lianban/dates");
  });

  it("requests ladder history with the default 60 日 window", async () => {
    const spy = vi.spyOn(apiClient, "get").mockResolvedValue(null);
    await fetchLadderHistory();
    expect(spy).toHaveBeenCalledWith("/lianban/ladder-history?days=60");
  });

  it("passes the ladder history window as a query parameter", async () => {
    const spy = vi.spyOn(apiClient, "get").mockResolvedValue(null);
    await fetchLadderHistory(120);
    expect(spy).toHaveBeenCalledWith("/lianban/ladder-history?days=120");
  });
});
