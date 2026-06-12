import type { ApiResponse } from "./types";

declare global {
  interface Window {
    __ALPHAAGENT_CONFIG__?: {
      API_BASE_URL?: string;
      VITE_API_BASE_URL?: string;
    };
  }
}

const runtimeConfig = typeof window === "undefined" ? undefined : window.__ALPHAAGENT_CONFIG__;
const BASE_URL =
  runtimeConfig?.API_BASE_URL ||
  runtimeConfig?.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  "http://localhost:8000/api";

export function apiUrl(path: string): string {
  return `${BASE_URL}${path}`;
}

export class ApiClientError extends Error {
  code: string;
  detail: Record<string, unknown>;
  status?: number;

  constructor(code: string, message: string, detail: Record<string, unknown> = {}, status?: number) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.detail = detail;
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit, requestOptions?: { allowErrorData?: boolean }): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...options,
  });

  const body: ApiResponse<T> = await res.json().catch(() => ({
    success: false,
    data: null,
    error: null,
    request_id: "",
  }));

  if (!res.ok && !(requestOptions?.allowErrorData && body.data !== null)) {
    const err = body.error;
    throw new ApiClientError(
      err?.code ?? `HTTP_${res.status}`,
      err?.message ?? `请求失败: ${res.status} ${res.statusText}`,
      { ...(err?.detail ?? {}), status: res.status, url },
      res.status
    );
  }

  if (!res.ok && requestOptions?.allowErrorData && body.data !== null) {
    return body.data;
  }

  if (!body.success || body.data === null) {
    const err = body.error;
    throw new ApiClientError(
      err?.code ?? "UNKNOWN",
      err?.message ?? "未知错误",
      err?.detail ?? {},
      res.status
    );
  }

  return body.data;
}

export const apiClient = {
  get<T>(path: string, options?: { allowErrorData?: boolean }) {
    return request<T>(path, undefined, options);
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
      { status: res.status, url },
      res.status
    );
  }
  return res.json() as Promise<T>;
}
