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
// 默认同源相对路径：前端经网关统一入口访问，/api 由 gateway 代理到后端。
const BASE_URL =
  runtimeConfig?.API_BASE_URL ||
  runtimeConfig?.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  "/api";

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

// ===== 认证 token（JWT 经 Authorization 头携带，存 localStorage）=====
const TOKEN_KEY = "alphaagent_token";

export const authToken = {
  get: () => (typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY)),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

// 登录相关端点不触发 401 → /login 跳转（避免登录失败时跳回自己）。
const PUBLIC_API_PATHS = ["/auth/login", "/auth/me", "/auth/logout"];

function isPublicApiPath(path: string): boolean {
  return PUBLIC_API_PATHS.some((p) => path === p || path.startsWith(`${p}/`));
}

function buildHeaders(extra?: HeadersInit): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  const token = authToken.get();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (extra) Object.assign(headers, extra as Record<string, string>);
  return headers;
}

// 收到 401 且非公开端点：清除本地 token 并跳转登录页。
function handleUnauthorized(url: string): never {
  authToken.clear();
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
  throw new ApiClientError("UNAUTHENTICATED", "请先登录", { status: 401, url }, 401);
}

async function request<T>(path: string, options?: RequestInit, requestOptions?: { allowErrorData?: boolean }): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: buildHeaders(options?.headers),
  });

  if (res.status === 401 && !isPublicApiPath(path)) {
    handleUnauthorized(url);
  }

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
  patch<T>(path: string, body?: unknown) {
    return request<T>(path, {
      method: "PATCH",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  },
  del<T>(path: string) {
    return request<T>(path, { method: "DELETE" });
  },
};

/**
 * Plain JSON fetch — for endpoints that return raw JSON
 * (not wrapped in {success, data}).
 */
export async function plainGet<T>(path: string): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, { headers: buildHeaders({ Accept: "application/json" }) });
  if (res.status === 401 && !isPublicApiPath(path)) {
    handleUnauthorized(url);
  }
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
