import { apiClient } from "./client";
import type { ReadyStatus } from "./types";

export function fetchHealth() {
  return apiClient.get<{ status: string }>("/health");
}

export function fetchReady() {
  return apiClient.get<ReadyStatus>("/ready");
}

export function fetchDataStatus() {
  return apiClient.get<Record<string, unknown>>("/data/status");
}
