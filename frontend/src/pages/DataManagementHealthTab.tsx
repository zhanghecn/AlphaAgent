/**
 * DataManagementHealthTab — 数据健康仪表盘（/data 默认首页）
 *
 * 进 /data 第一眼看到：整体健康度 + 空库引导 + 6 类数据新鲜度 + 推荐同步清单。
 * 后端依据每种数据的更新节奏（盘后/披露季/龙虎榜18:00后…）动态判定哪些该同步。
 * 复用 DataManagementPage 的 BatchProgress / RunStatusBadge / SummaryCard / DataNotice。
 */
import { useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchDataHealth,
  runAllSyncJobs,
  runSyncJob,
  fetchLatestSyncBatch,
} from "@/api/dataSync";
import type {
  DataHealth,
  DataHealthCategory,
  DataHealthJob,
  SyncBatchStatus,
} from "@/api/dataSync";
import {
  BatchProgress,
  RunStatusBadge,
  SummaryCard,
  DataNotice,
  formatDateTime,
} from "./DataManagementPage";
import { LoadingState } from "@/components/LoadingState";
import { cn } from "@/lib/utils";
import {
  Activity,
  RefreshCw,
  PlayCircle,
  Loader2,
  AlertTriangle,
  Database,
  Zap,
  Play,
} from "lucide-react";

const CADENCE_LABELS: Record<string, string> = {
  intraday: "盘中",
  eod_daily: "盘后",
  quarterly: "披露季",
  lhb: "龙虎榜",
  irregular: "低频",
};

const HEALTH_LABELS: Record<string, string> = {
  green: "健康",
  yellow: "需关注",
  red: "需处理",
};

function healthBadgeClass(health: string): string {
  if (health === "green") return "bg-green-50 text-green-700 dark:bg-green-500/15 dark:text-green-300";
  if (health === "yellow") return "bg-yellow-50 text-yellow-700 dark:bg-yellow-500/15 dark:text-yellow-300";
  return "bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300";
}

/** 把健康度新鲜度 severity 映射到 RunStatusBadge 的视觉（fresh=绿/stale=红/empty=灰）。 */
function severityToRunStatus(severity: string): string {
  if (severity === "fresh") return "succeeded";
  if (severity === "stale") return "failed";
  if (severity === "empty") return "pending";
  if (severity === "partial") return "pending";
  return severity;
}

export default function DataManagementHealthTab() {
  const queryClient = useQueryClient();

  const healthQuery = useQuery({
    queryKey: ["data-health"],
    queryFn: () => fetchDataHealth(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const latestBatchQuery = useQuery({
    queryKey: ["syncBatchLatest"],
    queryFn: fetchLatestSyncBatch,
    staleTime: 2_000,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2_000 : 8_000),
  });

  // 同步批次完成（running → 非 running）时立即重算健康度
  const prevStatusRef = useRef<string | undefined>(undefined);
  const batchStatus = latestBatchQuery.data?.status;
  useEffect(() => {
    if (prevStatusRef.current === "running" && batchStatus && batchStatus !== "running") {
      queryClient.invalidateQueries({ queryKey: ["data-health"] });
    }
    prevStatusRef.current = batchStatus;
  }, [batchStatus, queryClient]);

  const runRecommendedMutation = useMutation({
    mutationFn: (jobIds: string[]) => runAllSyncJobs({ job_ids: jobIds }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["syncBatchLatest"] }),
  });

  const runCoreMutation = useMutation({
    mutationFn: () => runAllSyncJobs({ profile: "core" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["syncBatchLatest"] }),
  });

  const runJobMutation = useMutation({
    mutationFn: (jobId: string) => runSyncJob(jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["data-health"] }),
  });

  const health = healthQuery.data;
  const batch = latestBatchQuery.data;
  const isBatchRunning =
    batch?.status === "running" || runRecommendedMutation.isPending || runCoreMutation.isPending;

  if (healthQuery.isLoading) {
    return <LoadingState rows={4} />;
  }

  return (
    <div className="space-y-4">
      {healthQuery.error ? (
        <DataNotice
          title="数据健康状态不可用"
          message={(healthQuery.error as Error).message}
          action="先确认 DATABASE_URL / PostgreSQL，再刷新本页。"
        />
      ) : null}

      {health ? (
        <OverallHealthBanner
          health={health}
          onRefresh={async () => {
            // 手动刷新强制绕过服务端缓存，立即重算健康状态
            const fresh = await fetchDataHealth(true);
            queryClient.setQueryData(["data-health"], fresh);
          }}
          isBatchRunning={isBatchRunning}
        />
      ) : null}

      {/* 空库引导：核心表为空时高亮，一键核心初始化 */}
      {health?.bootstrap.needed ? (
        <section className="rounded-lg border border-red-300 bg-red-50/60 p-4 dark:border-red-500/40 dark:bg-red-500/10">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-semibold text-red-800 dark:text-red-200">
                <AlertTriangle size={16} />
                数据库未初始化
              </div>
              <p className="mt-1 text-sm text-red-700 dark:text-red-300">
                核心表为空：{health.overall.empty_core_tables.join("、") || "stocks、stock_daily_bars"}。
                {health.bootstrap.message}
              </p>
            </div>
            <button
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => runCoreMutation.mutate()}
              disabled={isBatchRunning}
            >
              {runCoreMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Database size={16} />}
              一键核心初始化
            </button>
          </div>
        </section>
      ) : null}

      {/* 计数卡 */}
      {health ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <SummaryCard label="需同步" value={health.overall.stale_count} className="text-red-600" />
          <SummaryCard label="新鲜" value={health.overall.fresh_count} className="text-rise" />
          <SummaryCard label="推荐项" value={health.overall.recommended_count} />
          <SummaryCard label="最新交易日" value={health.market_context.latest_trade_date ?? "--"} />
        </div>
      ) : null}

      {/* 6 类数据新鲜度卡片 */}
      {health?.categories?.length ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {health.categories.map((cat) => (
            <CategoryFreshnessCard
              key={cat.key}
              category={cat}
              onRunJob={(jobId) => runJobMutation.mutate(jobId)}
              runningJobId={runJobMutation.isPending ? runJobMutation.variables ?? undefined : undefined}
              disabled={isBatchRunning}
            />
          ))}
        </div>
      ) : null}

      {/* 推荐同步 */}
      {health ? (
        <RecommendedSyncPanel
          health={health}
          batch={batch}
          isStarting={runRecommendedMutation.isPending}
          isBatchRunning={isBatchRunning}
          onRunRecommended={(ids) => runRecommendedMutation.mutate(ids)}
        />
      ) : null}

      {/* 市场上下文小字 */}
      {health ? (
        <div className="text-xs text-muted-foreground">
          当前 {formatDateTime(health.market_context.now) ?? health.generated_at}
          {health.market_context.is_disclosure_season ? " · 财报披露季" : " · 非财报披露季"}
          {health.market_context.trade_calendar_source === "stock_daily_bars"
            ? " · 交易日取自本地日线"
            : " · 交易日历未知，按天数兜底判断"}
          。数据每 60 秒刷新；同步仅在你点击时执行。
        </div>
      ) : null}
    </div>
  );
}

function OverallHealthBanner({
  health,
  onRefresh,
  isBatchRunning,
}: {
  health: DataHealth;
  onRefresh: () => void;
  isBatchRunning: boolean;
}) {
  const level = health.overall.health;
  return (
    <section
      className={cn(
        "rounded-lg border p-4",
        level === "green" && "border-green-200 bg-green-50/40 dark:border-green-500/30 dark:bg-green-500/5",
        level === "yellow" && "border-yellow-200 bg-yellow-50/40 dark:border-yellow-500/30 dark:bg-yellow-500/5",
        level === "red" && "border-red-200 bg-red-50/40 dark:border-red-500/30 dark:bg-red-500/5",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Activity size={18} />
            <h2 className="text-base font-semibold">数据健康</h2>
            <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", healthBadgeClass(level))}>
              {HEALTH_LABELS[level] ?? level}
            </span>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{health.overall.summary}</p>
        </div>
        <button
          className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
          onClick={onRefresh}
          disabled={isBatchRunning}
        >
          <RefreshCw size={15} className={isBatchRunning ? "animate-spin" : ""} />
          刷新
        </button>
      </div>
    </section>
  );
}

function CategoryFreshnessCard({
  category,
  onRunJob,
  runningJobId,
  disabled,
}: {
  category: DataHealthCategory;
  onRunJob: (jobId: string) => void;
  runningJobId?: string;
  disabled: boolean;
}) {
  return (
    <section className="rounded-lg border">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h3 className="text-sm font-semibold">{category.label}</h3>
        <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", healthBadgeClass(category.health))}>
          {HEALTH_LABELS[category.health] ?? category.health}
        </span>
      </div>
      <div className="divide-y">
        {category.jobs.map((job) => (
          <JobFreshnessRow
            key={job.job_id}
            job={job}
            onRun={() => onRunJob(job.job_id)}
            running={runningJobId === job.job_id}
            disabled={disabled}
          />
        ))}
      </div>
    </section>
  );
}

function JobFreshnessRow({
  job,
  onRun,
  running,
  disabled,
}: {
  job: DataHealthJob;
  onRun: () => void;
  running: boolean;
  disabled: boolean;
}) {
  return (
    <div className="grid gap-2 px-4 py-3 md:grid-cols-[1fr_auto] md:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <RunStatusBadge status={severityToRunStatus(job.severity)} />
          <span className="truncate text-sm font-medium">{job.name}</span>
          <CadenceTag cadence={job.cadence} />
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>{job.reason}</span>
          {job.local_latest ? (
            <span className="tabular-nums">最新 {job.local_latest.slice(0, 16).replace("T", " ")}</span>
          ) : null}
        </div>
      </div>
      <button
        className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
        onClick={onRun}
        disabled={disabled || running}
      >
        {running ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
        同步
      </button>
    </div>
  );
}

function CadenceTag({ cadence }: { cadence: string }) {
  const label = CADENCE_LABELS[cadence] ?? cadence;
  const cls =
    cadence === "intraday"
      ? "bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300"
      : cadence === "eod_daily"
        ? "bg-brand-50 text-brand-700 dark:bg-brand-500/15 dark:text-brand-300"
        : cadence === "quarterly"
          ? "bg-purple-50 text-purple-700 dark:bg-purple-500/15 dark:text-purple-300"
          : cadence === "lhb"
            ? "bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
            : "bg-gray-50 text-gray-600 dark:bg-gray-500/15 dark:text-gray-300";
  return <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", cls)}>{label}</span>;
}

function RecommendedSyncPanel({
  health,
  batch,
  isStarting,
  isBatchRunning,
  onRunRecommended,
}: {
  health: DataHealth;
  batch: SyncBatchStatus | null | undefined;
  isStarting: boolean;
  isBatchRunning: boolean;
  onRunRecommended: (ids: string[]) => void;
}) {
  const ids = health.recommended.job_ids;
  return (
    <section className="rounded-lg border bg-card">
      <div className="grid gap-4 p-4 lg:grid-cols-[1fr_auto] lg:items-start">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Zap size={16} />
            推荐同步
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{health.recommended.rationale}</p>
          {ids.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {ids.map((id) => (
                <span key={id} className="rounded border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                  {id}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="flex lg:justify-end">
          <button
            className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => onRunRecommended(ids)}
            disabled={isBatchRunning || ids.length === 0}
          >
            {isStarting || isBatchRunning ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
            {isBatchRunning ? "同步中" : `一键同步推荐 (${ids.length})`}
          </button>
        </div>
      </div>
      <BatchProgress batch={batch} isStarting={isStarting} />
    </section>
  );
}
