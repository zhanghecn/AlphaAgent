import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchLimitUpMembershipImportStatus,
  importLimitUpMembershipsFromTushare,
} from "@/api/dataSync";
import type {
  LimitUpMembershipCoverage,
  LimitUpMembershipImportResult,
  LimitUpMembershipImportStatus,
} from "@/api/dataSync";
import { LoadingState } from "@/components/LoadingState";
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  Loader2,
  Network,
  Play,
} from "lucide-react";

interface ViewProps {
  status: LimitUpMembershipImportStatus | undefined;
  result: LimitUpMembershipImportResult | undefined;
  startDate: string;
  endDate: string;
  maxDates: number;
  dryRun: boolean;
  onlyMissing: boolean;
  isRunning: boolean;
  error?: string;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onMaxDatesChange: (value: number) => void;
  onDryRunChange: (value: boolean) => void;
  onOnlyMissingChange: (value: boolean) => void;
  onRunTushare: () => void;
}

export default function HistoricalMembershipBackfillPanel() {
  const queryClient = useQueryClient();
  const [startDate, setStartDate] = useState("2024-01-15");
  const [endDate, setEndDate] = useState(shanghaiToday());
  const [maxDates, setMaxDates] = useState(20);
  const [dryRun, setDryRun] = useState(true);
  const [onlyMissing, setOnlyMissing] = useState(true);
  const [result, setResult] = useState<LimitUpMembershipImportResult>();

  const statusQuery = useQuery({
    queryKey: ["limitUpMembershipImportStatus"],
    queryFn: fetchLimitUpMembershipImportStatus,
    staleTime: 15_000,
  });
  const refreshCoverage = () => {
    void queryClient.invalidateQueries({ queryKey: ["limitUpMembershipImportStatus"] });
    void queryClient.invalidateQueries({ queryKey: ["limitUpDataQuality"] });
    void queryClient.invalidateQueries({ queryKey: ["syncCoverage"] });
  };
  const payload = () => ({
    start_date: startDate,
    end_date: endDate,
    dry_run: dryRun,
    max_dates: maxDates,
    only_missing: onlyMissing,
  });
  const tushareMutation = useMutation({
    mutationFn: () => importLimitUpMembershipsFromTushare(payload()),
    onSuccess: (next) => {
      setResult(next);
      refreshCoverage();
    },
  });
  const isRunning = tushareMutation.isPending;
  const error = tushareMutation.error ?? statusQuery.error;
  const confirmWrite = () => dryRun || window.confirm(
    "将只替换通过90%覆盖审计日期的行业成员，概念成员保持不变。确认写入？",
  );
  if (statusQuery.isLoading) return <LoadingState rows={3} />;
  return (
    <HistoricalMembershipBackfillView
      status={statusQuery.data}
      result={result}
      startDate={startDate}
      endDate={endDate}
      maxDates={maxDates}
      dryRun={dryRun}
      onlyMissing={onlyMissing}
      isRunning={isRunning}
      error={error instanceof Error ? error.message : undefined}
      onStartDateChange={setStartDate}
      onEndDateChange={setEndDate}
      onMaxDatesChange={setMaxDates}
      onDryRunChange={setDryRun}
      onOnlyMissingChange={setOnlyMissing}
      onRunTushare={() => {
        if (confirmWrite()) tushareMutation.mutate();
      }}
    />
  );
}

export function HistoricalMembershipBackfillView(props: ViewProps) {
  const coverage = props.status?.dataset.coverage;
  const providerReady = props.status?.provider.configured === true;
  return (
    <div className="space-y-4">
      <section className="border bg-card">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Network size={16} />
              逐日行业成员
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              申万二级 · 合格门槛 {props.status?.dataset.minimum_coverage_pct ?? 90}%
              {coverage?.minimum_daily_symbols ? ` · 可靠日全市场日线 ${coverage.minimum_daily_symbols}+` : ""}
            </div>
          </div>
          <span className={cn(
            "border px-2 py-1 text-xs",
            providerReady
              ? "border-emerald-300 text-emerald-700 dark:text-emerald-300"
              : "border-amber-300 text-amber-700 dark:text-amber-300",
          )}>
            {providerReady ? "Tushare 已配置" : "Tushare 未配置"}
          </span>
        </div>

        <MembershipCoverageBand coverage={coverage} />

        <div className="space-y-4 p-4">
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={props.dryRun}
                onChange={(event) => props.onDryRunChange(event.target.checked)}
              />
              预检查
            </label>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={props.onlyMissing}
                onChange={(event) => props.onOnlyMissingChange(event.target.checked)}
              />
              仅缺失或覆盖不足日期
            </label>
          </div>

          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-[180px_180px_140px_1fr]">
            <Field label="开始日期">
              <input
                type="date"
                value={props.startDate}
                onChange={(event) => props.onStartDateChange(event.target.value)}
                disabled={props.isRunning}
              />
            </Field>
            <Field label="结束日期">
              <input
                type="date"
                value={props.endDate}
                onChange={(event) => props.onEndDateChange(event.target.value)}
                disabled={props.isRunning}
              />
            </Field>
            <Field label="每批交易日">
              <input
                type="number"
                min={1}
                max={100}
                value={props.maxDates}
                onChange={(event) => props.onMaxDatesChange(Number(event.target.value))}
                disabled={props.isRunning}
              />
            </Field>
            <div className="flex items-end">
              <button
                type="button"
                className="inline-flex h-9 items-center gap-2 border bg-primary px-3 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
                onClick={props.onRunTushare}
                disabled={props.isRunning || !providerReady}
              >
                {props.isRunning ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
                {props.dryRun ? "预检查 Tushare" : "写入 Tushare"}
              </button>
            </div>
          </div>

          {props.error ? <div className="text-sm text-destructive">{props.error}</div> : null}
        </div>
      </section>

      {props.result ? <MembershipImportResultPanel result={props.result} /> : null}

      {props.status?.limitations.length ? (
        <div className="flex items-start gap-2 border-l-2 border-amber-400 px-3 py-2 text-xs text-muted-foreground">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-600" />
          <span>{props.status.limitations.join(" · ")}</span>
        </div>
      ) : null}
    </div>
  );
}

function MembershipCoverageBand({ coverage }: { coverage: LimitUpMembershipCoverage | undefined }) {
  const items = [
    ["原始快照", coverage?.raw_snapshot_trade_days ?? 0, coverage?.raw_rows ?? 0],
    ["行业快照", coverage?.industry_snapshot_trade_days ?? 0, coverage?.industry_rows ?? 0],
    ["概念快照", coverage?.concept_snapshot_trade_days ?? 0, coverage?.concept_rows ?? 0],
    ["门禁合格", coverage?.point_in_time_trade_days ?? 0, coverage?.rows ?? 0],
  ] as const;
  return (
    <div className="grid border-b sm:grid-cols-2 lg:grid-cols-4">
      {items.map(([label, days, rows], index) => (
        <div
          key={label}
          className={cn(
            "flex items-center justify-between gap-3 px-4 py-3",
            index > 0 && "sm:border-l",
            index > 1 && "border-t lg:border-t-0",
          )}
        >
          <div className="text-xs text-muted-foreground">{label}</div>
          <div className="text-right">
            <div className="text-sm font-semibold tabular-nums">{days} 日</div>
            <div className="text-xs text-muted-foreground tabular-nums">{rows.toLocaleString()} 行</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function MembershipImportResultPanel({ result }: { result: LimitUpMembershipImportResult }) {
  return (
    <section className="border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
        <div className="text-sm font-semibold">逐日成员审计</div>
        <div className="text-xs text-muted-foreground">
          {result.provider} · {result.dry_run ? "预检查" : "写入"} · 区间 {result.rows_read ?? 0}
          {` · 展开 ${result.expanded_rows ?? 0} · 冲突 ${result.conflict_count ?? 0} · 写入 ${result.rows_written ?? 0}`}
        </div>
      </div>
      {result.message ? (
        <div className="border-b px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
          {result.message}
        </div>
      ) : null}
      {result.date_results.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b bg-muted/35 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left">交易日</th>
                <th className="px-4 py-2 text-left">状态</th>
                <th className="px-4 py-2 text-right">有效成员</th>
                <th className="px-4 py-2 text-right">覆盖</th>
                <th className="px-4 py-2 text-right">写入</th>
                <th className="px-4 py-2 text-left">缺失 / 原因</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {result.date_results.map((item) => (
                <tr key={`${item.trade_date}:${item.status}`}>
                  <td className="px-4 py-2 font-mono text-xs">{item.trade_date}</td>
                  <td className="px-4 py-2">{membershipStatusLabel(item.status)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{item.rows_accepted ?? 0}</td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {item.covered_count ?? 0} / {item.expected_count ?? 0}
                    <div className="text-xs text-muted-foreground">{formatPct(item.coverage_pct)}</div>
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {(item.rows_written ?? 0) > 0 ? `写入 ${item.rows_written}` : "未写入"}
                  </td>
                  <td className="max-w-[320px] px-4 py-2 text-xs text-muted-foreground">
                    {item.reason || item.missing_symbols?.join("、") || "--"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="px-4 py-6 text-sm text-muted-foreground">没有可处理的可靠交易日。</div>
      )}
      {result.errors.length ? (
        <div className="border-t px-4 py-3 text-xs text-destructive">{result.errors.join(" · ")}</div>
      ) : null}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="text-xs text-muted-foreground">
      {label}
      <div className="mt-1 [&>input]:h-9 [&>input]:w-full [&>input]:border [&>input]:bg-background [&>input]:px-2 [&>input]:text-sm">
        {children}
      </div>
    </label>
  );
}

function membershipStatusLabel(status: string): string {
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
