/**
 * DataManagementPage — 数据管理
 *
 * Merged from DataStatusPage + DataSyncPage.
 * Three tabs: Status, Sync, Sources
 */
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchDataUsage,
  fetchSyncJobs,
  fetchSyncRuns,
  fetchSyncCoverage,
  fetchSyncSources,
  runSyncJob,
} from "@/api/dataSync";
import type {
  DataUsageCapability,
  SyncSourceItem,
  SyncJobItem,
  SyncRunItem,
} from "@/api/dataSync";
import { LoadingState } from "@/components/LoadingState";
import { cn } from "@/lib/utils";
import {
  Database,
  RefreshCw,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  Server,
  Table,
} from "lucide-react";

type TabKey = "status" | "sync" | "sources";

const TABS: { key: TabKey; label: string; icon: typeof Database }[] = [
  { key: "status", label: "数据状态", icon: Database },
  { key: "sync", label: "同步管理", icon: RefreshCw },
  { key: "sources", label: "数据源", icon: Server },
];

export default function DataManagementPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("status");

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">数据管理</h1>

      {/* Tab bar */}
      <div className="flex gap-1 border-b">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              className={cn(
                "flex items-center gap-1.5 px-4 py-2 text-sm font-medium transition-colors",
                activeTab === tab.key
                  ? "border-b-2 border-primary text-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
              onClick={() => setActiveTab(tab.key)}
            >
              <Icon size={14} />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {activeTab === "status" && <StatusTab />}
      {activeTab === "sync" && <SyncTab />}
      {activeTab === "sources" && <SourcesTab />}
    </div>
  );
}

// ── Status Tab ──

function StatusTab() {
  const usageQuery = useQuery({
    queryKey: ["dataUsage"],
    queryFn: fetchDataUsage,
    staleTime: 30_000,
  });

  const coverageQuery = useQuery({
    queryKey: ["syncCoverage"],
    queryFn: fetchSyncCoverage,
    staleTime: 30_000,
  });

  if (usageQuery.isLoading) return <LoadingState rows={4} />;
  if (usageQuery.error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">
        加载失败: {(usageQuery.error as Error).message}
      </div>
    );
  }

  const usage = usageQuery.data;
  const capabilities = usage?.capabilities ?? [];
  const coverage = coverageQuery.data;

  // Compute summary from capabilities
  const readyCount = capabilities.filter((c) => c.status === "ready").length;
  const degradedCount = capabilities.filter((c) => c.status === "degraded" || c.status === "partial").length;

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SummaryCard label="数据能力" value={capabilities.length} />
        <SummaryCard label="就绪" value={readyCount} className="text-rise" />
        <SummaryCard label="降级/部分" value={degradedCount} className="text-yellow-600" />
        <SummaryCard
          label="覆盖表"
          value={coverage?.tables ? Object.keys(coverage.tables).length : "--"}
        />
      </div>

      {/* Capabilities list */}
      {capabilities.length > 0 && (
        <section className="rounded-lg border">
          <div className="border-b px-4 py-3">
            <h3 className="text-sm font-semibold">数据能力</h3>
          </div>
          <div className="divide-y">
            {capabilities.map((cap) => (
              <CapabilityRow key={cap.name} cap={cap} />
            ))}
          </div>
        </section>
      )}

      {/* Coverage table */}
      {coverage?.tables && Object.keys(coverage.tables).length > 0 && (
        <section className="rounded-lg border">
          <div className="border-b px-4 py-3">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <Table size={14} />
              数据覆盖
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground bg-muted/50">
                <tr>
                  <th className="px-4 py-2 text-left">表名</th>
                  <th className="px-4 py-2 text-right">行数</th>
                  <th className="px-4 py-2 text-right">最新交易日</th>
                  <th className="px-4 py-2 text-right">更新时间</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(coverage.tables).map(([table, info]) => {
                  const rec = info as unknown as Record<string, unknown>;
                  return (
                    <tr key={table} className="border-t hover:bg-muted/30">
                      <td className="px-4 py-2 font-mono text-xs">{table}</td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {((rec.count ?? rec.rows) as number | undefined)?.toLocaleString() ?? "--"}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                        {(rec.latest_trade_date as string | undefined) ?? "--"}
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                        {(rec.last_updated ?? rec.updated_at)
                          ? new Date((rec.last_updated ?? rec.updated_at) as string).toLocaleString("zh-CN")
                          : "--"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function CapabilityRow({ cap }: { cap: DataUsageCapability }) {
  return (
    <div className="flex items-center justify-between px-4 py-3">
      <div className="min-w-0">
        <div className="font-medium">{cap.description || cap.name}</div>
        <div className="text-sm text-muted-foreground">
          {cap.name} · 表: {cap.table}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span className="text-xs text-muted-foreground tabular-nums">
          {cap.count?.toLocaleString() ?? "--"} 条
        </span>
        <StatusBadge status={cap.status} />
      </div>
    </div>
  );
}

// ── Sync Tab ──

function SyncTab() {
  const queryClient = useQueryClient();

  const jobsQuery = useQuery({
    queryKey: ["syncJobs"],
    queryFn: fetchSyncJobs,
    staleTime: 30_000,
  });

  const runsQuery = useQuery({
    queryKey: ["syncRuns"],
    queryFn: () => fetchSyncRuns(20),
    staleTime: 10_000,
  });

  const runMutation = useMutation({
    mutationFn: (jobId: string) => runSyncJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["syncRuns"] });
    },
  });

  const jobs: SyncJobItem[] = jobsQuery.data ?? [];
  const runs: SyncRunItem[] = runsQuery.data ?? [];

  return (
    <div className="space-y-4">
      {/* Sync jobs */}
      <section className="rounded-lg border">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h3 className="text-sm font-semibold">同步任务</h3>
          <span className="text-xs text-muted-foreground">{jobs.length} 个任务</span>
        </div>
        {jobsQuery.isLoading ? (
          <LoadingState rows={3} />
        ) : jobs.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">暂无同步任务</div>
        ) : (
          <div className="divide-y">
            {jobs.map((job) => (
              <div key={job.id} className="flex items-center justify-between px-4 py-3">
                <div className="min-w-0">
                  <div className="font-medium">{job.name}</div>
                  <div className="text-xs text-muted-foreground">{job.description}</div>
                  <div className="mt-1 flex gap-2 text-xs text-muted-foreground">
                    <span>目标: {job.target_table}</span>
                    {job.schedule_cron && <span>计划: {job.schedule_cron}</span>}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <RunStatusBadge status={job.last_status} />
                  {job.enabled && (
                    <button
                      className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50"
                      onClick={() => runMutation.mutate(job.id)}
                      disabled={runMutation.isPending}
                    >
                      {runMutation.isPending ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Play size={12} />
                      )}
                      执行
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Recent runs */}
      <section className="rounded-lg border">
        <div className="border-b px-4 py-3">
          <h3 className="text-sm font-semibold">最近执行记录</h3>
        </div>
        {runsQuery.isLoading ? (
          <LoadingState rows={3} />
        ) : runs.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">暂无执行记录</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground bg-muted/50">
                <tr>
                  <th className="px-4 py-2 text-left">任务</th>
                  <th className="px-4 py-2 text-center">状态</th>
                  <th className="px-4 py-2 text-right">读取</th>
                  <th className="px-4 py-2 text-right">写入</th>
                  <th className="px-4 py-2 text-right">耗时</th>
                  <th className="px-4 py-2 text-right">开始时间</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 15).map((run) => (
                  <tr key={run.id} className="border-t hover:bg-muted/30">
                    <td className="px-4 py-2 font-mono text-xs">{run.job_id}</td>
                    <td className="px-4 py-2 text-center">
                      <RunStatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{run.rows_read.toLocaleString()}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{run.rows_written.toLocaleString()}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                      {formatDuration(run.started_at, run.finished_at)}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                      {new Date(run.started_at).toLocaleString("zh-CN")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

// ── Sources Tab ──

function SourcesTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["syncSources"],
    queryFn: fetchSyncSources,
    staleTime: 30_000,
  });

  if (isLoading) return <LoadingState rows={3} />;
  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">
        加载失败: {(error as Error).message}
      </div>
    );
  }

  const sources: SyncSourceItem[] = data ?? [];

  return (
    <div className="space-y-3">
      {sources.length === 0 ? (
        <div className="py-10 text-center text-sm text-muted-foreground">暂无数据源</div>
      ) : (
        sources.map((src) => (
          <div key={src.id} className="rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">{src.name}</div>
                <div className="text-sm text-muted-foreground">
                  {src.kind}
                  {src.base_url && (
                    <span className="ml-2 font-mono text-xs">{src.base_url}</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  优先级: {src.priority}
                </span>
                <StatusBadge status={src.status === "ok" ? "ready" : src.status} />
              </div>
            </div>
            {src.message && (
              <div className="mt-2 text-xs text-muted-foreground">{src.message}</div>
            )}
            {src.checked_at && (
              <div className="mt-1 text-xs text-muted-foreground">
                最后检查: {new Date(src.checked_at).toLocaleString("zh-CN")}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}

// ── Helper components ──

function SummaryCard({
  label,
  value,
  className,
}: {
  label: string;
  value: string | number | null | undefined;
  className?: string;
}) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className={cn("text-lg font-semibold", className)}>{value ?? "--"}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "ready" || status === "ok" || status === "succeeded"
      ? "bg-green-50 text-green-700"
      : status === "partial"
        ? "bg-yellow-50 text-yellow-700"
        : status === "unknown"
          ? "bg-gray-50 text-gray-500"
          : "bg-red-50 text-red-700";

  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", cls)}>
      {status}
    </span>
  );
}

function RunStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="text-xs text-muted-foreground">--</span>;

  const Icon =
    status === "succeeded" ? CheckCircle2 :
    status === "failed" ? XCircle :
    status === "running" ? Loader2 :
    Clock;

  const colorClass =
    status === "succeeded" ? "text-green-600" :
    status === "failed" ? "text-red-600" :
    status === "running" ? "text-blue-600" :
    "text-muted-foreground";

  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-medium", colorClass)}>
      <Icon size={12} className={status === "running" ? "animate-spin" : ""} />
      {status === "succeeded" ? "成功" : status === "failed" ? "失败" : status === "running" ? "运行中" : status}
    </span>
  );
}

function formatDuration(startAt: string, finishAt: string | null | undefined): string {
  if (!finishAt) return "--";
  const ms = new Date(finishAt).getTime() - new Date(startAt).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}min`;
}
