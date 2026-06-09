import type { ApiResponse } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";

export class ApiClientError extends Error {
  code: string;
  detail: Record<string, unknown>;

  constructor(code: string, message: string, detail: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.detail = detail;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...options,
  });

  if (!res.ok) {
    throw new ApiClientError(
      `HTTP_${res.status}`,
      `请求失败: ${res.status} ${res.statusText}`,
      { status: res.status, url }
    );
  }

  const body: ApiResponse<T> = await res.json();

  if (!body.success || body.data === null) {
    const err = body.error;
    throw new ApiClientError(
      err?.code ?? "UNKNOWN",
      err?.message ?? "未知错误",
      err?.detail ?? {}
    );
  }

  return body.data;
}

export const apiClient = {
  get<T>(path: string) {
    return request<T>(path);
  },
  post<T>(path: string, body?: unknown) {
    return request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  },
};

/**
 * Plain JSON fetch — for endpoints that return raw JSON
 * (not wrapped in {success, data}).
 */
export async function plainGet<T>(path: string): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new ApiClientError(
      `HTTP_${res.status}`,
      `请求失败: ${res.status} ${res.statusText}`,
      { status: res.status, url }
    );
  }
  return res.json() as Promise<T>;
}
