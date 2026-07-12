import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchLatestSyncBatch,
  fetchLimitUpThsEvidenceBatch,
  fetchLimitUpEvidenceImportStatus,
  fetchLimitUpEvidenceTemplate,
  importLimitUpEvidenceFromCsv,
  importLimitUpEvidenceFromTushare,
  startLimitUpThsEvidenceImport,
} from "@/api/dataSync";
import type {
  LimitUpEvidenceDataset,
  LimitUpEvidenceImportResult,
  LimitUpEvidenceImportStatus,
  SyncBatchStatus,
} from "@/api/dataSync";
import { LoadingState } from "@/components/LoadingState";
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  DatabaseZap,
  Download,
  FileCheck2,
  Loader2,
  Play,
  Upload,
} from "lucide-react";
import HistoricalMembershipBackfillPanel from "./HistoricalMembershipBackfillPanel";


interface ViewProps {
  status: LimitUpEvidenceImportStatus | undefined;
  result: LimitUpEvidenceImportResult | undefined;
  dataset: LimitUpEvidenceDataset;
  startDate: string;
  endDate: string;
  maxDates: number;
  dryRun: boolean;
  onlyMissing: boolean;
  fileName: string;
  isRunning: boolean;
  thsBatch?: SyncBatchStatus;
  error?: string;
  onDatasetChange: (dataset: LimitUpEvidenceDataset) => void;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onMaxDatesChange: (value: number) => void;
  onDryRunChange: (value: boolean) => void;
  onOnlyMissingChange: (value: boolean) => void;
  onRunTushare: () => void;
  onRunThs: () => void;
  onFileChange: (file: File | null) => void;
  onRunCsv: () => void;
  onDownloadTemplate: () => void;
}


export default function LimitUpEvidenceBackfillPanel() {
  const queryClient = useQueryClient();
  const [dataset, setDataset] = useState<LimitUpEvidenceDataset>("events");
  const [startDate, setStartDate] = useState("2024-01-15");
  const [endDate, setEndDate] = useState(shanghaiToday());
  const [maxDates, setMaxDates] = useState(20);
  const [dryRun, setDryRun] = useState(true);
  const [onlyMissing, setOnlyMissing] = useState(true);
  const [fileName, setFileName] = useState("");
  const [csvText, setCsvText] = useState("");
  const [result, setResult] = useState<LimitUpEvidenceImportResult>();
  const [thsBatchId, setThsBatchId] = useState("");

  const statusQuery = useQuery({
    queryKey: ["limitUpEvidenceImportStatus"],
    queryFn: fetchLimitUpEvidenceImportStatus,
    staleTime: 15_000,
  });
  const refreshCoverage = () => {
    void queryClient.invalidateQueries({ queryKey: ["limitUpEvidenceImportStatus"] });
    void queryClient.invalidateQueries({ queryKey: ["limitUpDataQuality"] });
    void queryClient.invalidateQueries({ queryKey: ["syncCoverage"] });
  };
  const tushareMutation = useMutation({
    mutationFn: () => importLimitUpEvidenceFromTushare({
      dataset,
      start_date: startDate,
      end_date: endDate,
      dry_run: dryRun,
      max_dates: maxDates,
      only_missing: onlyMissing,
    }),
    onSuccess: (next) => {
      setResult(next);
      refreshCoverage();
    },
  });
  const csvMutation = useMutation({
    mutationFn: () => importLimitUpEvidenceFromCsv({ dataset, csv_text: csvText, dry_run: dryRun }),
    onSuccess: (next) => {
      setResult(next);
      refreshCoverage();
    },
  });
  const templateMutation = useMutation({
    mutationFn: () => fetchLimitUpEvidenceTemplate(dataset),
    onSuccess: (content) => downloadCsv(content, `alphaagent_limit_up_${dataset}_template.csv`),
  });
  const thsMutation = useMutation({
    mutationFn: () => startLimitUpThsEvidenceImport({ max_dates: 252, only_missing: true }),
    onSuccess: (batch) => setThsBatchId(batch.id),
  });
  const latestBatchQuery = useQuery({
    queryKey: ["latestSyncBatch", "limitUpThsEvidence"],
    queryFn: fetchLatestSyncBatch,
    staleTime: 2_000,
  });
  const recoveredThsBatch = latestBatchQuery.data?.jobs.some(
    (job) => job.job_id === "sync_limit_up_ths_evidence",
  ) ? latestBatchQuery.data : undefined;
  const activeThsBatchId = thsBatchId || recoveredThsBatch?.id || "";
  const thsBatchQuery = useQuery({
    queryKey: ["limitUpThsEvidenceBatch", activeThsBatchId],
    queryFn: () => fetchLimitUpThsEvidenceBatch(activeThsBatchId),
    enabled: Boolean(activeThsBatchId),
    refetchInterval: (query) => query.state.data?.status === "running" ? 2_000 : false,
  });
  const thsBatch = thsBatchQuery.data ?? recoveredThsBatch;
  const thsBatchStatus = thsBatch?.status;
  const thsBatchRunning = thsBatchStatus === "running";
  const isRunning = tushareMutation.isPending
    || csvMutation.isPending
    || templateMutation.isPending
    || thsMutation.isPending
    || thsBatchRunning;
  const error = thsMutation.error
    ?? thsBatchQuery.error
    ?? latestBatchQuery.error
    ?? tushareMutation.error
    ?? csvMutation.error
    ?? templateMutation.error
    ?? statusQuery.error;

  useEffect(() => {
    if (!thsBatchStatus || thsBatchStatus === "running") return;
    void queryClient.invalidateQueries({ queryKey: ["limitUpEvidenceImportStatus"] });
    void queryClient.invalidateQueries({ queryKey: ["limitUpDataQuality"] });
    void queryClient.invalidateQueries({ queryKey: ["syncCoverage"] });
  }, [queryClient, thsBatchStatus]);

  const changeDataset = (next: LimitUpEvidenceDataset) => {
    setDataset(next);
    setResult(undefined);
    if (next === "auction" && startDate < "2025-01-01") setStartDate("2025-01-01");
  };
  const confirmWrite = () => dryRun || window.confirm("将按交易日原子替换已通过覆盖审计的历史证据，确认写入？");
  const runTushare = () => {
    if (confirmWrite()) tushareMutation.mutate();
  };
  const runCsv = () => {
    if (csvText && confirmWrite()) csvMutation.mutate();
  };
  const readFile = (file: File | null) => {
    setFileName(file?.name ?? "");
    setCsvText("");
    if (file) void file.text().then(setCsvText);
  };

  if (statusQuery.isLoading) return <LoadingState rows={4} />;
  return (
    <div className="space-y-6">
      <LimitUpEvidenceBackfillView
        status={statusQuery.data}
        result={result}
        dataset={dataset}
        startDate={startDate}
        endDate={endDate}
        maxDates={maxDates}
        dryRun={dryRun}
        onlyMissing={onlyMissing}
        fileName={fileName}
        isRunning={isRunning}
        thsBatch={thsBatch}
        error={error instanceof Error ? error.message : undefined}
        onDatasetChange={changeDataset}
        onStartDateChange={setStartDate}
        onEndDateChange={setEndDate}
        onMaxDatesChange={setMaxDates}
        onDryRunChange={setDryRun}
        onOnlyMissingChange={setOnlyMissing}
        onRunTushare={runTushare}
        onRunThs={() => thsMutation.mutate()}
        onFileChange={readFile}
        onRunCsv={runCsv}
        onDownloadTemplate={() => templateMutation.mutate()}
      />
      <HistoricalMembershipBackfillPanel />
    </div>
  );
}


export function LimitUpEvidenceBackfillView(props: ViewProps) {
  const datasetStatus = props.status?.datasets[props.dataset];
  const providerReady = props.status?.provider.configured === true;
  const thsJob = props.thsBatch?.jobs.find((job) => job.job_id === "sync_limit_up_ths_evidence");
  const thsProgress = Math.min(Math.max(thsJob?.progress_pct ?? 0, 0), 100);
  const thsHistoryDays = props.status?.ths_provider?.history_trade_days ?? 252;
  const thsBatchTerminal = Boolean(props.thsBatch && props.thsBatch.status !== "running");
  const thsProgressLabel = thsBatchTerminal
    ? thsJob?.message || props.thsBatch?.message || "完成"
    : thsJob?.current_label || thsJob?.stage || props.thsBatch?.message || "等待执行";
  const thsProgressCount = (thsJob?.progress_total ?? 0) > 0
    ? `${thsJob?.progress_current ?? 0}/${thsJob?.progress_total ?? 0} · ${thsProgress.toFixed(0)}%`
    : thsBatchTerminal
      ? `写入 ${thsJob?.rows_written ?? props.thsBatch?.rows_written ?? 0} · 100%`
      : "0/0 · 0%";
  return (
    <div className="space-y-4">
      <section className="border bg-card">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold">
              <DatabaseZap size={16} />
              打板历史证据
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {datasetStatus?.label ?? "--"} · {datasetStatus?.api_name ?? "--"} · 官方起始 {datasetStatus?.provider_start ?? "--"}
            </div>
          </div>
          <span className={cn(
            "border px-2 py-1 text-xs",
            providerReady ? "border-emerald-300 text-emerald-700 dark:text-emerald-300" : "border-amber-300 text-amber-700 dark:text-amber-300",
          )}>
            {providerReady ? "Tushare 已配置" : "Tushare 未配置"}
          </span>
        </div>

        <div className="grid gap-0 border-b md:grid-cols-2">
          <CoverageCell label="涨停/炸板路径" status={props.status?.datasets.events} />
          <CoverageCell label="开盘集合竞价" status={props.status?.datasets.auction} className="border-t md:border-l md:border-t-0" />
        </div>

        <div className="flex flex-col gap-3 border-b px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm font-medium">
              <span>同花顺公开历史</span>
              <span className="text-xs font-normal text-muted-foreground">
                {thsHistoryDays} 个交易日 · 覆盖门槛 90%
              </span>
            </div>
            {props.thsBatch ? (
              <div className="mt-2 max-w-2xl">
                <div className={cn(
                  "flex items-center justify-between gap-3 text-xs",
                  props.thsBatch.status === "failed" ? "text-destructive" : "text-muted-foreground",
                )}>
                  <span className="truncate">{thsProgressLabel}</span>
                  <span className="shrink-0 tabular-nums">
                    {thsProgressCount}
                  </span>
                </div>
                <div className="mt-1 h-1 overflow-hidden bg-muted">
                  <div className="h-full bg-primary transition-[width] duration-150" style={{ width: `${thsProgress}%` }} />
                </div>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            className="inline-flex h-9 shrink-0 items-center justify-center gap-2 border bg-primary px-3 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
            onClick={props.onRunThs}
            disabled={props.isRunning}
          >
            {props.thsBatch?.status === "running" || props.isRunning
              ? <Loader2 size={15} className="animate-spin" />
              : <Download size={15} />}
            同花顺近{thsHistoryDays}日
          </button>
        </div>

        <div className="space-y-4 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex border bg-background p-1">
              <ModeButton active={props.dataset === "events"} onClick={() => props.onDatasetChange("events")}>涨停事件</ModeButton>
              <ModeButton active={props.dataset === "auction"} onClick={() => props.onDatasetChange("auction")}>集合竞价</ModeButton>
            </div>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input type="checkbox" checked={props.dryRun} onChange={(event) => props.onDryRunChange(event.target.checked)} />
              预检查
            </label>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input type="checkbox" checked={props.onlyMissing} onChange={(event) => props.onOnlyMissingChange(event.target.checked)} />
              仅缺失日期
            </label>
          </div>

          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-[180px_180px_140px_1fr]">
            <Field label="开始日期">
              <input type="date" value={props.startDate} onChange={(event) => props.onStartDateChange(event.target.value)} disabled={props.isRunning} />
            </Field>
            <Field label="结束日期">
              <input type="date" value={props.endDate} onChange={(event) => props.onEndDateChange(event.target.value)} disabled={props.isRunning} />
            </Field>
            <Field label="每批交易日">
              <input type="number" min={1} max={100} value={props.maxDates} onChange={(event) => props.onMaxDatesChange(Number(event.target.value))} disabled={props.isRunning} />
            </Field>
            <div className="flex items-end">
              <button
                className="inline-flex h-9 items-center gap-2 border bg-primary px-3 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
                onClick={props.onRunTushare}
                disabled={props.isRunning || !providerReady}
              >
                {props.isRunning ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
                {props.dryRun ? "预检查 Tushare" : "写入 Tushare"}
              </button>
            </div>
          </div>

          <div className="grid gap-3 border-t pt-4 lg:grid-cols-[minmax(220px,1fr)_auto_auto] lg:items-end">
            <Field label="CSV 文件">
              <label className="flex h-9 cursor-pointer items-center gap-2 border bg-background px-3 text-sm text-muted-foreground">
                <Upload size={15} />
                <span className="min-w-0 truncate">{props.fileName || "选择完整供应商导出文件"}</span>
                <input className="sr-only" type="file" accept=".csv,text/csv" onChange={(event) => props.onFileChange(event.target.files?.[0] ?? null)} disabled={props.isRunning} />
              </label>
            </Field>
            <button className="inline-flex h-9 items-center justify-center gap-2 border px-3 text-sm hover:bg-muted disabled:opacity-50" onClick={props.onDownloadTemplate} disabled={props.isRunning}>
              <Download size={15} /> 下载模板
            </button>
            <button className="inline-flex h-9 items-center justify-center gap-2 border px-3 text-sm font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50" onClick={props.onRunCsv} disabled={props.isRunning || !props.fileName}>
              <FileCheck2 size={15} /> {props.dryRun ? "预检查 CSV" : "写入 CSV"}
            </button>
          </div>
          {props.error ? <div className="text-sm text-destructive">{props.error}</div> : null}
        </div>
      </section>

      {props.result ? <ImportResultPanel result={props.result} /> : null}

      {props.status?.limitations?.length ? (
        <div className="flex items-start gap-2 border-l-2 border-amber-400 px-3 py-2 text-xs text-muted-foreground">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-600" />
          <span>{props.status.limitations.join(" · ")}</span>
        </div>
      ) : null}
    </div>
  );
}


function CoverageCell({ label, status, className }: { label: string; status: LimitUpEvidenceImportStatus["datasets"][LimitUpEvidenceDataset] | undefined; className?: string }) {
  const coverage = status?.coverage;
  return (
    <div className={cn("grid grid-cols-[1fr_auto] gap-3 px-4 py-3", className)}>
      <div>
        <div className="text-sm font-medium">{label}</div>
        <div className="mt-1 text-xs text-muted-foreground">{coverage?.start ?? "--"} 至 {coverage?.end ?? "--"}</div>
      </div>
      <div className="text-right">
        <div className="text-sm font-semibold tabular-nums">{coverage?.trade_days ?? 0} 日</div>
        <div className="mt-1 text-xs text-muted-foreground">
          {coverage?.rows?.toLocaleString() ?? 0} 行
          {label.includes("竞价") ? ` · 严格 ${coverage?.strict_trade_days ?? 0} 日` : ""}
        </div>
      </div>
    </div>
  );
}


function ImportResultPanel({ result }: { result: LimitUpEvidenceImportResult }) {
  return (
    <section className="border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
        <div className="text-sm font-semibold">逐日导入审计</div>
        <div className="text-xs text-muted-foreground">
          {result.provider} · {result.dry_run ? "预检查" : "写入"} · 读取 {result.rows_read ?? 0} · 写入 {result.rows_written ?? 0}
        </div>
      </div>
      {result.message ? <div className="border-b px-4 py-3 text-sm text-amber-700 dark:text-amber-300">{result.message}</div> : null}
      {result.date_results.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b bg-muted/35 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left">交易日</th>
                <th className="px-4 py-2 text-left">状态</th>
                <th className="px-4 py-2 text-right">读取 / 接受</th>
                <th className="px-4 py-2 text-right">覆盖</th>
                <th className="px-4 py-2 text-right">写入</th>
                <th className="px-4 py-2 text-left">缺失 / 原因</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {result.date_results.map((item) => (
                <tr key={`${item.trade_date}:${item.status}`}>
                  <td className="px-4 py-2 font-mono text-xs">{item.trade_date}</td>
                  <td className="px-4 py-2">{evidenceStatusLabel(item.status)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{item.rows_read ?? 0} / {item.rows_accepted ?? 0}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{item.covered_count ?? 0} / {item.expected_count ?? 0}<div className="text-xs text-muted-foreground">{formatPct(item.coverage_pct)}</div></td>
                  <td className="px-4 py-2 text-right tabular-nums">{(item.rows_written ?? 0) > 0 ? `写入 ${item.rows_written}` : "未写入"}</td>
                  <td className="max-w-[320px] px-4 py-2 text-xs text-muted-foreground">{item.reason || item.missing_symbols?.join("、") || "--"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="px-4 py-6 text-sm text-muted-foreground">没有可处理的交易日。</div>
      )}
      {result.errors?.length ? <div className="border-t px-4 py-3 text-xs text-destructive">{result.errors.join(" · ")}</div> : null}
    </section>
  );
}


function ModeButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return <button type="button" className={cn("px-3 py-1.5 text-xs", active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")} onClick={onClick}>{children}</button>;
}


function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="text-xs text-muted-foreground">{label}<div className="mt-1 [&>input]:h-9 [&>input]:w-full [&>input]:border [&>input]:bg-background [&>input]:px-2 [&>input]:text-sm">{children}</div></label>;
}


function evidenceStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: "通过",
    coverage_incomplete: "覆盖不足",
    reference_missing: "缺少参照",
    provider_error: "供应商错误",
  };
  return labels[status] ?? status;
}


function formatPct(value: number | undefined): string {
  return value == null ? "--" : `${value.toFixed(2)}%`;
}


function shanghaiToday(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}


function downloadCsv(content: string, filename: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
