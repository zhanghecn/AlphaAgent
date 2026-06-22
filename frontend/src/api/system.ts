import { apiClient } from "./client";

export interface ReleaseInfo {
  tag: string;
  name: string;
  html_url: string;
  published_at: string;
  body: string;
}

export interface VersionInfo {
  current: string;
  build_type: string;
  latest: string | null;
  has_update: boolean;
  release_info: ReleaseInfo | null;
  error?: string;
}

/** 对比当前版本与 GitHub 最新 release（后端带 5 分钟缓存）。 */
export function checkUpdates(force = false) {
  const path = force ? "/system/check-updates?force=true" : "/system/check-updates";
  return apiClient.get<VersionInfo>(path);
}

/** 一键更新：后端后台执行 docker compose pull && up -d（api 会被重建）。 */
export function performUpdate() {
  return apiClient.post<{ message: string }>("/system/update");
}

/** 重启 api 容器。 */
export function restartService() {
  return apiClient.post<{ message: string }>("/system/restart");
}
