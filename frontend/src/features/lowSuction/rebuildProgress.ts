/** 低吸回测重建进度的共享展示工具（回测页与交割单页共用，避免两处抄文案）。 */

export function rebuildStageLabel(stage: string | null | undefined): string {
  const labels: Record<string, string> = {
    load_inputs: "加载数据",
    scan_candidates: "扫描全市场候选",
    resolve_names: "补全名称与 ST 筛选",
    build_report: "汇总回测报告",
    persist_report: "写入报告",
    completed: "已完成",
    failed: "执行失败",
    request_rejected: "未新建任务",
  };
  return labels[stage ?? ""] ?? "全量重算中";
}

export function formatElapsed(milliseconds: number): string {
  const seconds = Math.max(Math.floor(milliseconds / 1_000), 0);
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3_600) return `${Math.floor(seconds / 60)} 分`;
  return `${Math.floor(seconds / 3_600)} 时 ${Math.floor((seconds % 3_600) / 60)} 分`;
}

export function elapsedSince(startedAt: string | null | undefined): string {
  if (!startedAt) return "--";
  return formatElapsed(Date.now() - Date.parse(startedAt));
}
