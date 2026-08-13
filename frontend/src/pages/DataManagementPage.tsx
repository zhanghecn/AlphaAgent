/**
 * DataManagementPage — 数据管理
 *
 * Merged from DataStatusPage + DataSyncPage.
 * Three tabs: Status, Sync, Sources
 */
import { useState, type ReactNode } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchDataUsage,
  fetchLatestSyncBatch,
  fetchSyncJobs,
  fetchSyncRuns,
  fetchSyncCoverage,
  fetchSyncSources,
  runAllSyncJobs,
  runSyncJob,
  fetchSyncSchedules,
  createSyncSchedule,
  updateSyncSchedule,
  deleteSyncSchedule,
  runSyncSchedule,
} from "@/api/dataSync";
import type {
  DataUsageCapability,
  SyncSourceItem,
  SyncJobItem,
  SyncRunItem,
  SyncBatchStatus,
  SyncBatchJobStatus,
  SyncProgressSample,
  BatchSchedule,
} from "@/api/dataSync";
import { LoadingState } from "@/components/LoadingState";
import DataManagementHealthTab from "./DataManagementHealthTab";
import { cn } from "@/lib/utils";
import {
  Database,
  RefreshCw,
  Play,
  PlayCircle,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  Server,
  Table,
  Activity,
  ChevronDown,
  ChevronRight,
  Plus,
  Save,
  Trash2,
} from "lucide-react";

type TabKey = "health" | "sync" | "status" | "sources";
interface MinuteSyncFormState {
  interval: "1m";
  stockLimit: number;
  limit: number;
  startDate: string;
  endDate: string;
}

const DEFAULT_MINUTE_SYNC_FORM: MinuteSyncFormState = {
  interval: "1m",
  stockLimit: 100,
  limit: 240,
  startDate: "",
  endDate: "",
};

const TABS: { key: TabKey; label: string; icon: typeof Database }[] = [
  { key: "health", label: "数据健康", icon: Activity },
  { key: "sync", label: "同步任务", icon: RefreshCw },
  { key: "status", label: "数据状态", icon: Database },
  { key: "sources", label: "数据源", icon: Server },
];

export default function DataManagementPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("health");

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">数据管理</h1>

      {/* Tab bar */}
      <div className="flex max-w-full gap-1 overflow-x-auto border-b">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              className={cn(
                "flex shrink-0 items-center gap-1.5 px-4 py-2 text-sm font-medium transition-colors",
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
      {activeTab === "health" && <DataManagementHealthTab />}
      {activeTab === "sync" && <SyncTab />}
      {activeTab === "status" && <StatusTab />}
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

  const usage = usageQuery.data;
  const capabilities = usage?.capabilities ?? [];
  const coverage = coverageQuery.data;
  const unavailableCount = capabilities.filter((c) => c.status === "unavailable").length;

  // Compute summary from capabilities
  const readyCount = capabilities.filter((c) => c.status === "ready").length;
  const degradedCount = capabilities.filter((c) => c.status === "degraded" || c.status === "partial").length;

  return (
    <div className="space-y-4">
      {usageQuery.isLoading ? <LoadingState rows={4} /> : null}
      {usageQuery.error ? (
        <DataNotice
          title="数据同步模块未就绪"
          message={(usageQuery.error as Error).message}
          action="先确认 DATABASE_URL/PostgreSQL，再刷新本页。市场页面可能仍会回退公开实时源。"
        />
      ) : null}
      {!usageQuery.error && unavailableCount > 0 ? (
        <DataNotice
          title="本地数据能力不可用"
          message={`${unavailableCount} 项能力暂时不可用，通常是 PostgreSQL 未配置或连接失败。`}
          action="进入 deploy/.env 或根目录 .env 检查 DATABASE_URL，启动数据库后再执行同步任务。"
        />
      ) : null}

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SummaryCard label="数据能力" value={capabilities.length} />
        <SummaryCard label="就绪" value={readyCount} className="text-rise" />
        <SummaryCard label="能力受限/降级" value={degradedCount} className="text-yellow-600" />
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
          {cap.message && <div className="mt-1 text-xs text-amber-700 dark:text-amber-400">{cap.message}</div>}
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
  const [syncProfile, setSyncProfile] = useState<"core" | "all">("core");
  const [minuteSyncForm, setMinuteSyncForm] = useState<MinuteSyncFormState>(DEFAULT_MINUTE_SYNC_FORM);

  const jobsQuery = useQuery({
    queryKey: ["syncJobs"],
    queryFn: fetchSyncJobs,
    staleTime: 30_000,
  });

  const runsQuery = useQuery({
    queryKey: ["syncRuns"],
    queryFn: () => fetchSyncRuns(20),
    staleTime: 10_000,
    refetchInterval: 5_000,
  });

  const coverageQuery = useQuery({
    queryKey: ["syncCoverage"],
    queryFn: fetchSyncCoverage,
    staleTime: 10_000,
    refetchInterval: 8_000,
  });

  const latestBatchQuery = useQuery({
    queryKey: ["syncBatchLatest"],
    queryFn: fetchLatestSyncBatch,
    staleTime: 2_000,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2_000 : 8_000),
  });

  const runMutation = useMutation({
    mutationFn: ({ jobId, params }: { jobId: string; params?: Record<string, unknown> }) => runSyncJob(jobId, params ?? {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["syncRuns"] });
      queryClient.invalidateQueries({ queryKey: ["syncCoverage"] });
      queryClient.invalidateQueries({ queryKey: ["dataUsage"] });
    },
  });

  const runAllMutation = useMutation({
    mutationFn: () => runAllSyncJobs({ profile: syncProfile }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["syncBatchLatest"] });
      queryClient.invalidateQueries({ queryKey: ["syncRuns"] });
    },
  });

  const jobs: SyncJobItem[] = jobsQuery.data ?? [];
  const runs: SyncRunItem[] = runsQuery.data ?? [];
  const disabledJobs = jobs.filter((job) => !job.enabled || job.last_status === "unavailable").length;
  const batch = latestBatchQuery.data;
  const isBatchRunning = batch?.status === "running" || runAllMutation.isPending;
  const coverage = coverageQuery.data;
  const tableEntries = Object.entries(coverage?.tables ?? {});
  const nonEmptyTables = tableEntries.filter(([, info]) => coverageCount(info) > 0);
  const totalRows = tableEntries.reduce((sum, [, info]) => sum + coverageCount(info), 0);

  return (
    <div className="space-y-4">
      {jobsQuery.error ? (
        <DataNotice
          title="同步任务暂时不能执行"
          message={(jobsQuery.error as Error).message}
          action="同步任务依赖 PostgreSQL；数据库恢复后刷新页面即可。"
        />
      ) : null}
      {!jobsQuery.error && disabledJobs > 0 ? (
        <DataNotice
          title="部分同步任务不可执行"
          message={`${disabledJobs} 个任务处于禁用或不可用状态。`}
          action="如果状态是 DATABASE_URL not configured，请先配置数据库连接。"
        />
      ) : null}

      <section className="rounded-lg border bg-card">
        <div className="grid gap-4 p-4 lg:grid-cols-[1.1fr_0.9fr]">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Activity size={16} />
              数据初始化
            </div>
            <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
              新库为空时先跑核心数据：股票清单、板块、日线、资金流和热度。全量数据会继续拉财报、公告、龙虎榜、行业链等，耗时更长。
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <div className="inline-flex rounded-md border bg-background p-1">
                <button
                  className={cn(
                    "rounded px-3 py-1.5 text-sm transition-colors",
                    syncProfile === "core" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                  )}
                  onClick={() => setSyncProfile("core")}
                  disabled={isBatchRunning}
                >
                  核心数据
                </button>
                <button
                  className={cn(
                    "rounded px-3 py-1.5 text-sm transition-colors",
                    syncProfile === "all" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                  )}
                  onClick={() => setSyncProfile("all")}
                  disabled={isBatchRunning}
                >
                  全量数据
                </button>
              </div>
              <button
                className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => runAllMutation.mutate()}
                disabled={isBatchRunning || jobs.length === 0}
              >
                {isBatchRunning ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
                {isBatchRunning ? "同步中" : "一键同步"}
              </button>
              <button
                className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors hover:bg-muted"
                onClick={() => {
                  queryClient.invalidateQueries({ queryKey: ["syncBatchLatest"] });
                  queryClient.invalidateQueries({ queryKey: ["syncRuns"] });
                  queryClient.invalidateQueries({ queryKey: ["syncCoverage"] });
                  queryClient.invalidateQueries({ queryKey: ["dataUsage"] });
                }}
              >
                <RefreshCw size={15} />
                刷新状态
              </button>
            </div>
            {runAllMutation.error ? (
              <div className="mt-3 text-sm text-red-600">{(runAllMutation.error as Error).message}</div>
            ) : null}
          </div>
          <DataHealthPanel totalRows={totalRows} nonEmptyTables={nonEmptyTables.length} tableCount={tableEntries.length} />
        </div>
        <BatchProgress batch={batch} isStarting={runAllMutation.isPending} />
      </section>

      <BatchSchedulesPanel jobs={jobs} />

      {/* Sync jobs */}
      <section className="rounded-lg border">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div>
            <h3 className="text-sm font-semibold">同步任务</h3>
            <div className="text-xs text-muted-foreground">可以单独执行，也可以用上方一键同步按依赖顺序执行。</div>
          </div>
          <span className="text-xs text-muted-foreground">{jobs.length} 个任务</span>
        </div>
        {jobsQuery.isLoading ? (
          <LoadingState rows={3} />
        ) : jobs.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-muted-foreground">暂无同步任务</div>
        ) : (
          <div className="divide-y">
            {jobs.map((job) => (
              <div key={job.id} className="grid gap-3 px-4 py-3 md:grid-cols-[1fr_auto] md:items-center">
                <div className="min-w-0">
                  <div className="font-medium">{job.name}</div>
                  <div className="text-xs text-muted-foreground">{job.description}</div>
                  <div className="mt-1 flex gap-2 text-xs text-muted-foreground">
                    <span>目标: {job.target_table}</span>
                    {job.schedule_cron && <span>计划: {job.schedule_cron}</span>}
                  </div>
                  {job.message && <div className="mt-1 text-xs text-amber-700 dark:text-amber-400">{job.message}</div>}
                </div>
                <div className="flex items-center gap-2 shrink-0 md:justify-end">
                  <RunStatusBadge status={job.last_status} />
                  {job.enabled && (
                    <button
                      className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50"
                      onClick={() => runMutation.mutate({ jobId: job.id, params: job.id === "sync_stock_minute_bars" ? buildMinuteSyncParams(minuteSyncForm) : undefined })}
                      disabled={runMutation.isPending || isBatchRunning}
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
                {job.id === "sync_stock_minute_bars" ? (
                  <div className="md:col-span-2">
                    <MinuteSyncParamsPanel value={minuteSyncForm} onChange={setMinuteSyncForm} disabled={runMutation.isPending || isBatchRunning} />
                  </div>
                ) : null}
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
                  <th className="px-4 py-2 text-left">参数</th>
                  <th className="px-4 py-2 text-right">读取</th>
                  <th className="px-4 py-2 text-right">写入</th>
                  <th className="px-4 py-2 text-right">耗时</th>
                  <th className="px-4 py-2 text-right">开始时间</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 15).map((run) => (
                  <tr key={run.id ?? run.run_id ?? `${run.job_id}-${run.started_at}`} className="border-t hover:bg-muted/30">
                    <td className="px-4 py-2 font-mono text-xs">{run.job_id}</td>
                    <td className="px-4 py-2 text-center">
                      <RunStatusBadge status={run.status} />
                    </td>
                    <td className="max-w-[360px] px-4 py-2 text-xs text-muted-foreground">
                      <div className="truncate">{syncRunParamsText(run)}</div>
                      {run.message ? <div className="mt-1 truncate text-amber-700 dark:text-amber-400">{run.message}</div> : null}
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

function BatchSchedulesPanel({ jobs }: { jobs: SyncJobItem[] }) {
  const queryClient = useQueryClient();
  const schedulesQuery = useQuery({
    queryKey: ["syncSchedules"],
    queryFn: fetchSyncSchedules,
    staleTime: 5_000,
    refetchInterval: 30_000,
  });

  const createMutation = useMutation({
    mutationFn: (payload: Partial<BatchSchedule>) => createSyncSchedule(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["syncSchedules"] }),
  });
  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<BatchSchedule> }) => updateSyncSchedule(id, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["syncSchedules"] }),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSyncSchedule(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["syncSchedules"] }),
  });
  const runMutation = useMutation({
    mutationFn: (id: string) => runSyncSchedule(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["syncBatchLatest"] });
      queryClient.invalidateQueries({ queryKey: ["syncSchedules"] });
    },
  });

  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: "",
    cron: "0 14 * * 1-5",
    concurrency: 8,
    job_ids: [] as string[],
    enabled: true,
  });

  const schedules = schedulesQuery.data ?? [];

  function toggleJob(jobId: string) {
    setForm((f) => ({
      ...f,
      job_ids: f.job_ids.includes(jobId) ? f.job_ids.filter((j) => j !== jobId) : [...f.job_ids, jobId],
    }));
  }

  function submitCreate() {
    if (!form.name.trim() || form.cron.trim().split(/\s+/).length !== 5) return;
    createMutation.mutate(form, { onSuccess: () => setEditing(false) });
  }

  return (
    <section className="rounded-lg border">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold">定时计划</h3>
          <div className="text-xs text-muted-foreground">统一的批量增量同步档，按数据依赖顺序执行；19:00 更新，21:30 补偿重试。</div>
        </div>
        <button
          className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
          onClick={() => setEditing((v) => !v)}
        >
          <Plus size={15} /> {editing ? "取消" : "新增定时"}
        </button>
      </div>

      {editing ? (
        <div className="space-y-3 border-b px-4 py-3">
          <div className="grid gap-3 md:grid-cols-3">
            <Field label="名称">
              <input
                className="w-full rounded-md border bg-background px-3 py-1.5 text-sm"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="如：盘中同步"
              />
            </Field>
            <Field label="Cron（分 时 日 月 周）">
              <input
                className="w-full rounded-md border bg-background px-3 py-1.5 text-sm font-mono"
                value={form.cron}
                onChange={(e) => setForm((f) => ({ ...f, cron: e.target.value }))}
                placeholder="0 14 * * 1-5"
              />
            </Field>
            <Field label="并发度">
              <input
                type="number"
                min={1}
                max={32}
                className="w-full rounded-md border bg-background px-3 py-1.5 text-sm"
                value={form.concurrency}
                onChange={(e) => setForm((f) => ({ ...f, concurrency: Number(e.target.value) || 8 }))}
              />
            </Field>
          </div>
          <Field label="任务（按勾选顺序执行）">
            <div className="flex flex-wrap gap-2">
              {jobs.map((job) => (
                <button
                  key={job.id}
                  type="button"
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-xs transition-colors",
                    form.job_ids.includes(job.id)
                      ? "border-primary bg-primary text-primary-foreground"
                      : "bg-background text-muted-foreground hover:text-foreground"
                  )}
                  onClick={() => toggleJob(job.id)}
                >
                  {job.name}
                </button>
              ))}
            </div>
          </Field>
          <div className="flex items-center gap-2">
            <button
              className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              onClick={submitCreate}
              disabled={createMutation.isPending}
            >
              {createMutation.isPending ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} 保存
            </button>
            {createMutation.error ? (
              <span className="text-xs text-red-600">{(createMutation.error as Error).message}</span>
            ) : null}
          </div>
        </div>
      ) : null}

      {schedulesQuery.isLoading ? (
        <LoadingState rows={2} />
      ) : schedules.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-muted-foreground">暂无定时计划</div>
      ) : (
        <div className="divide-y">
          {schedules.map((schedule) => (
            <div key={schedule.id} className="grid gap-3 px-4 py-3 md:grid-cols-[1fr_auto] md:items-center">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{schedule.name}</span>
                  <StatusBadge status={schedule.last_status ?? "unknown"} />
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className="font-mono">{schedule.cron}</span>
                  <span>{schedule.job_ids.length} 个任务</span>
                  <span>并发 {schedule.concurrency}</span>
                  {schedule.last_finished_at ? (
                    <span>上次 {new Date(schedule.last_finished_at).toLocaleString()}</span>
                  ) : null}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-xs transition-colors",
                    schedule.enabled ? "border-primary text-primary" : "text-muted-foreground"
                  )}
                  onClick={() => updateMutation.mutate({ id: schedule.id, payload: { enabled: !schedule.enabled } })}
                >
                  {schedule.enabled ? "已启用" : "已停用"}
                </button>
                <button
                  className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs hover:bg-muted"
                  onClick={() => runMutation.mutate(schedule.id)}
                  disabled={runMutation.isPending}
                >
                  {runMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <PlayCircle size={13} />} 立即执行
                </button>
                <button
                  className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs text-red-600 hover:bg-red-50"
                  onClick={() => deleteMutation.mutate(schedule.id)}
                >
                  <Trash2 size={13} /> 删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SourcesTab() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["syncSources"],
    queryFn: fetchSyncSources,
    staleTime: 30_000,
  });

  const sources: SyncSourceItem[] = data ?? [];

  return (
    <div className="space-y-3">
      {isLoading ? <LoadingState rows={3} /> : null}
      {error ? (
        <DataNotice
          title="数据源注册表未就绪"
          message={(error as Error).message}
          action="这通常不影响公开行情回退，但同步任务需要 PostgreSQL 可用。"
        />
      ) : null}
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

function MinuteSyncParamsPanel({
  value,
  onChange,
  disabled,
}: {
  value: MinuteSyncFormState;
  onChange: (value: MinuteSyncFormState) => void;
  disabled: boolean;
}) {
  const setValue = <K extends keyof MinuteSyncFormState>(key: K, next: MinuteSyncFormState[K]) => {
    onChange({ ...value, [key]: next });
  };

  return (
    <div className="rounded-md border bg-muted/20 p-3">
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
          <Field label="周期">
            <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/30 px-2 text-sm">1分钟</div>
          </Field>
          <Field label="股票数">
            <input
              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
              type="number"
              min={1}
              max={500}
              value={value.stockLimit}
              onChange={(event) => setValue("stockLimit", Number(event.target.value))}
              disabled={disabled}
            />
          </Field>
          <Field label="每股根数">
            <input
              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
              type="number"
              min={1}
              max={5000}
              value={value.limit}
              onChange={(event) => setValue("limit", Number(event.target.value))}
              disabled={disabled}
            />
          </Field>
          <Field label="开始日期">
            <input
              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
              type="date"
              value={value.startDate}
              onChange={(event) => setValue("startDate", event.target.value)}
              disabled={disabled}
            />
          </Field>
          <Field label="结束日期">
            <input
              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
              type="date"
              value={value.endDate}
              onChange={(event) => setValue("endDate", event.target.value)}
              disabled={disabled}
            />
          </Field>
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        最近分钟线由系统数据源同步；涨停事件历史缺口由夜间任务自动发现并补齐。
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="min-w-0 text-xs text-muted-foreground">
      {label}
      {children}
    </label>
  );
}

function buildMinuteSyncParams(value: MinuteSyncFormState): Record<string, unknown> {
  return compactParams({
    mode: "recent",
    interval: value.interval,
    stock_limit: value.stockLimit,
    limit: value.limit,
    start_date: value.startDate,
    end_date: value.endDate,
    only_missing: true,
  });
}

function compactParams(params: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== "")
  );
}

function syncRunParamsText(run: SyncRunItem): string {
  const params = run.params ?? {};
  const mode = String(params.mode ?? "");
  if (run.job_id === "sync_stock_minute_bars" && mode === "recent") {
    return [
      "最近分钟线",
      params.interval ? `周期 ${params.interval}` : "",
      params.stock_limit ? `${params.stock_limit} 只` : "",
      params.limit ? `${params.limit} 根` : "",
    ].filter(Boolean).join(" · ");
  }
  const keys = Object.keys(params);
  if (!keys.length) return "--";
  return keys.slice(0, 4).map((key) => `${key}=${String(params[key])}`).join(" · ");
}

export function SummaryCard({
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

function DataHealthPanel({
  totalRows,
  nonEmptyTables,
  tableCount,
}: {
  totalRows: number;
  nonEmptyTables: number;
  tableCount: number;
}) {
  return (
    <div className="grid grid-cols-3 gap-2 rounded-lg bg-muted/40 p-3">
      <div>
        <div className="text-xs text-muted-foreground">总行数</div>
        <div className="mt-1 text-lg font-semibold tabular-nums">{totalRows.toLocaleString()}</div>
      </div>
      <div>
        <div className="text-xs text-muted-foreground">有数据表</div>
        <div className="mt-1 text-lg font-semibold tabular-nums">{nonEmptyTables}/{tableCount || "--"}</div>
      </div>
      <div>
        <div className="text-xs text-muted-foreground">当前状态</div>
        <div className="mt-1 text-lg font-semibold">{totalRows > 0 ? "有数据" : "空库"}</div>
      </div>
    </div>
  );
}

export function BatchProgress({ batch, isStarting }: { batch: SyncBatchStatus | null | undefined; isStarting: boolean }) {
  const [openJobs, setOpenJobs] = useState<Record<string, boolean>>({});

  if (isStarting && !batch) {
    return (
      <div className="border-t px-4 py-3 text-sm text-muted-foreground">
        <Loader2 size={14} className="mr-2 inline animate-spin" />
        正在创建同步批次
      </div>
    );
  }
  if (!batch) {
    return (
      <div className="border-t px-4 py-3 text-sm text-muted-foreground">
        还没有同步批次记录。执行同步后，这里会显示当前任务、进度和写入行数。
      </div>
    );
  }

  const pct = Math.max(0, Math.min(Number(batch.progress_pct ?? 0), 100));
  const current = batch.current_job_id ? batch.jobs.find((job) => job.job_id === batch.current_job_id) : undefined;

  return (
    <div className="border-t px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium">
            <RunStatusBadge status={batch.status} />
            <span>{batchTitle(batch)}</span>
            <span className="text-muted-foreground">#{batch.id.slice(0, 8)}</span>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {batch.message || (current ? jobActivityText(current) : "等待下一步")}
          </div>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <div>{batch.completed_jobs}/{batch.total_jobs} 个任务</div>
          <div>读取 {batch.rows_read.toLocaleString()}，写入 {batch.rows_written.toLocaleString()}</div>
        </div>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            batch.status === "failed" ? "bg-red-500" : "bg-primary"
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-4 divide-y rounded-md border">
        {batch.jobs.map((job) => {
          const hasSamples = (job.sample_items?.length ?? 0) > 0;
          const isOpen = openJobs[job.job_id] ?? job.status === "running";
          return (
            <div key={job.job_id} className="bg-background">
              <div className="grid gap-3 px-3 py-3 md:grid-cols-[minmax(220px,0.9fr)_minmax(260px,1.4fr)_auto] md:items-center">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <RunStatusBadge status={job.status} />
                    <span className="truncate text-sm font-medium">{job.job_id}</span>
                  </div>
                  <div className="mt-1 truncate text-xs text-muted-foreground">
                    {jobActivityText(job)}
                  </div>
                </div>
                <div className="min-w-0">
                  <TaskProgressBar job={job} />
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <span>读取 {Number(job.rows_read ?? 0).toLocaleString()}</span>
                    <span>写入 {Number(job.rows_written ?? 0).toLocaleString()}</span>
                    {progressUnits(job) ? <span>{progressUnits(job)}</span> : null}
                  </div>
                </div>
                <div className="flex justify-end">
                  <button
                    className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                    onClick={() => setOpenJobs((prev) => ({ ...prev, [job.job_id]: !isOpen }))}
                    disabled={!hasSamples}
                  >
                    {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    样本
                  </button>
                </div>
              </div>
              {hasSamples && isOpen ? <ProgressSamples items={job.sample_items ?? []} /> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function batchTitle(batch: SyncBatchStatus): string {
  if (batch.profile === "all") return "全量同步";
  if (batch.profile === "core") return "核心同步";
  return "同步批次";
}

function TaskProgressBar({ job }: { job: SyncBatchJobStatus }) {
  const pct = Math.max(0, Math.min(Number(job.progress_pct ?? 0), 100));
  const color = job.status === "failed" ? "bg-red-500" : job.status === "succeeded" ? "bg-green-600" : "bg-primary";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">{pct.toFixed(0)}%</span>
    </div>
  );
}

function ProgressSamples({ items }: { items: SyncProgressSample[] }) {
  return (
    <div className="border-t bg-muted/20 px-3 py-3">
      <div className="grid gap-2 lg:grid-cols-3">
        {items.map((item, index) => (
          <div key={`${index}-${String(item.vt_symbol ?? item.id ?? item.symbol ?? "")}`} className="rounded-md border bg-card px-3 py-2">
            <div className="truncate text-xs font-medium">{sampleTitle(item)}</div>
            <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
              {sampleFields(item).map(([key, value]) => (
                <div key={key} className="min-w-0">
                  <span className="text-muted-foreground/80">{sampleLabel(key)} </span>
                  <span className="tabular-nums text-foreground">{formatSampleValue(value)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function jobActivityText(job: SyncBatchJobStatus): string {
  const stage = job.stage || (job.status === "pending" ? "等待执行" : "");
  const label = job.current_label || "";
  if (stage && label) return `${stage}：${label}`;
  return stage || label || job.message || "";
}

function progressUnits(job: SyncBatchJobStatus): string {
  const total = Number(job.progress_total ?? 0);
  if (total <= 0) return "";
  const current = Number(job.progress_current ?? 0);
  return `${Math.min(current, total).toLocaleString()}/${total.toLocaleString()}`;
}

function sampleTitle(item: SyncProgressSample): string {
  const vt = item.vt_symbol ?? item.symbol ?? item.id ?? "样本";
  const name = item.name ? ` ${item.name}` : "";
  return `${vt}${name}`;
}

function sampleFields(item: SyncProgressSample): [string, SyncProgressSample[string]][] {
  const priority = [
    "trade_date",
    "bar_time",
    "close",
    "close_price",
    "change_pct",
    "volume",
    "turnover",
    "main_net_inflow",
    "rank",
    "report_date",
    "publish_date",
    "operating_cash_flow",
    "cash_flow_quality",
    "type",
  ];
  return priority
    .filter((key) => item[key] !== undefined && item[key] !== null && item[key] !== "")
    .slice(0, 6)
    .map((key) => [key, item[key]]);
}

function sampleLabel(key: string): string {
  const labels: Record<string, string> = {
    trade_date: "日期",
    bar_time: "时间",
    close: "收盘",
    close_price: "收盘",
    change_pct: "涨跌",
    volume: "成交量",
    turnover: "成交额",
    main_net_inflow: "主力净流入",
    rank: "排名",
    report_date: "报告期",
    publish_date: "披露",
    operating_cash_flow: "经营现金流",
    cash_flow_quality: "现金质量",
    type: "类型",
  };
  return labels[key] ?? key;
}

function formatSampleValue(value: SyncProgressSample[string]): string {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "number") {
    if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿`;
    if (Math.abs(value) >= 10_000) return `${(value / 10_000).toFixed(2)}万`;
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2);
  }
  return String(value ?? "");
}

export function formatDateTime(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("zh-CN");
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "ready" || status === "ok" || status === "succeeded"
      ? "bg-green-50 text-green-700 dark:bg-green-500/15 dark:text-green-300"
      : status === "empty" || status === "pending"
        ? "bg-gray-50 text-gray-600 dark:bg-gray-500/15 dark:text-gray-300"
      : status === "partial"
        ? "bg-yellow-50 text-yellow-700 dark:bg-yellow-500/15 dark:text-yellow-300"
      : status === "unknown"
        ? "bg-gray-50 text-gray-500 dark:bg-gray-500/15 dark:text-gray-400"
          : "bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300";

  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", cls)}>
      {formatStatusLabel(status)}
    </span>
  );
}

function formatStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: "就绪",
    ok: "正常",
    succeeded: "成功",
    empty: "暂无数据",
    pending: "待执行",
    partial: "能力受限",
    degraded: "降级可用",
    unavailable: "不可用",
    unknown: "未知",
    running: "运行中",
    failed: "失败",
  };
  return labels[status] ?? status;
}

export function DataNotice({ title, message, action }: { title: string; message: string; action: string }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm dark:border-amber-500/30 dark:bg-amber-500/10">
      <div className="font-medium text-amber-900 dark:text-amber-200">{title}</div>
      <div className="mt-1 text-amber-800 dark:text-amber-300">{message}</div>
      <div className="mt-2 text-xs text-amber-700 dark:text-amber-400">{action}</div>
    </div>
  );
}

export function RunStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <span className="text-xs text-muted-foreground">--</span>;

  const Icon =
    status === "succeeded" ? CheckCircle2 :
    status === "failed" ? XCircle :
    status === "running" ? Loader2 :
    Clock;

  const colorClass =
    status === "succeeded" ? "text-green-600 dark:text-green-400" :
    status === "failed" ? "text-red-600 dark:text-red-400" :
    status === "running" ? "text-blue-600 dark:text-blue-400" :
    "text-muted-foreground";

  const label =
    status === "succeeded" ? "成功" :
    status === "failed" ? "失败" :
    status === "running" ? "运行中" :
    status === "pending" ? "等待" :
    status === "empty" ? "空" :
    status;

  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-medium", colorClass)}>
      <Icon size={12} className={status === "running" ? "animate-spin" : ""} />
      {label}
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

function coverageCount(info: unknown): number {
  if (!info || typeof info !== "object") return 0;
  const rec = info as { count?: number; rows?: number };
  return Number(rec.count ?? rec.rows ?? 0);
}
