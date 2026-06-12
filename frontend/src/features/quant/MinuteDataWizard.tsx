import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, Download, FileUp, RefreshCw, ShieldCheck, Upload } from "lucide-react";
import {
  importVnpyMinuteBars,
  importVnpyMinuteBarsForGaps,
  runStrictMinuteBacktestPipeline,
} from "@/api/quant";
import {
  auditMinuteGapCsv,
  fetchMinuteGapImportTemplate,
  fetchMinuteGapVendorManifest,
  fetchMinuteGapVendorManifestCsv,
  importMinuteBarsCsv,
  importMinuteGapsFromTdx,
  importMinuteGapsFromTushare,
  type MinuteGapAuditResult,
} from "@/api/dataSync";
import { DEFAULT_BACKTEST_START } from "@/features/quant/constants";
import { InfoCell } from "@/components/InfoCell";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn, formatPct } from "@/lib/utils";

export interface MinuteDataWizardProps {
  tailEntryStart: string;
  tailEntryEnd: string;
  isRunningBacktest: boolean;
  onStrictPipelineComplete: (backtestId: number) => void;
  onAuditChange?: (audit: MinuteGapAuditResult | undefined) => void;
}

export function MinuteDataWizard({
  tailEntryStart,
  tailEntryEnd,
  isRunningBacktest,
  onStrictPipelineComplete,
  onAuditChange,
}: MinuteDataWizardProps) {
  const queryClient = useQueryClient();

  // ── State (7 + 2 internal) ────────────────────────────────────────────
  const [minuteGapCsv, setMinuteGapCsv] = useState("");
  const [minuteImportCsv, setMinuteImportCsv] = useState("");
  const [minuteGapFilePath, setMinuteGapFilePath] = useState("");
  const [minuteImportFilePath, setMinuteImportFilePath] = useState("");
  const [minuteGapTemplate, setMinuteGapTemplate] = useState("");
  const [minuteVendorManifestCsv, setMinuteVendorManifestCsv] = useState("");
  const [vnpyImportParams, setVnpyImportParams] = useState({
    vt_symbol: "600000.SSE",
    start: DEFAULT_BACKTEST_START,
    end: "",
    dry_run: true,
  });
  const [fileError, setFileError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  // ── Mutations (10) ─────────────────────────────────────────────────────

  const minuteGapAuditMutation = useMutation({
    mutationFn: () =>
      auditMinuteGapCsv({
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        file_path: minuteGapFilePath.trim() || undefined,
        interval: "1m",
        tail_entry_start: tailEntryStart,
        tail_entry_end: tailEntryEnd,
      }),
    onSuccess: (data) => onAuditChange?.(data),
  });

  const minuteGapTemplateMutation = useMutation({
    mutationFn: () => fetchMinuteGapImportTemplate({ gap_csv_text: minuteGapCsv, sample_limit: 200 }),
    onSuccess: (content) => setMinuteGapTemplate(content),
  });

  const minuteVendorManifestMutation = useMutation({
    mutationFn: () =>
      fetchMinuteGapVendorManifest({
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        gap_file_path: minuteGapFilePath.trim() || undefined,
        tail_entry_start: tailEntryStart,
        tail_entry_end: tailEntryEnd,
        sample_limit: 20,
      }),
  });

  const minuteVendorManifestCsvMutation = useMutation({
    mutationFn: () =>
      fetchMinuteGapVendorManifestCsv({
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        gap_file_path: minuteGapFilePath.trim() || undefined,
        tail_entry_start: tailEntryStart,
        tail_entry_end: tailEntryEnd,
      }),
    onSuccess: (content) => setMinuteVendorManifestCsv(content),
  });

  const minuteImportMutation = useMutation({
    mutationFn: (dryRun: boolean) =>
      importMinuteBarsCsv({
        csv_text: minuteImportFilePath.trim() ? undefined : minuteImportCsv,
        file_path: minuteImportFilePath.trim() || undefined,
        interval: "1m",
        source: minuteImportFilePath.trim() ? "manual_csv_file" : "manual_csv",
        dry_run: dryRun,
      }),
    onSuccess: (_result, dryRun) => {
      if (!dryRun) {
        minuteGapAuditMutation.reset();
        onAuditChange?.(undefined);
      }
    },
  });

  const vnpyMinuteImportMutation = useMutation({
    mutationFn: () =>
      importVnpyMinuteBars({
        vt_symbol: vnpyImportParams.vt_symbol,
        start: vnpyImportParams.start,
        end: vnpyImportParams.end || undefined,
        interval: "1m",
        dry_run: vnpyImportParams.dry_run,
      }),
    onSuccess: (result) => {
      if (result.rows_written) {
        minuteGapAuditMutation.reset();
        onAuditChange?.(undefined);
      }
    },
  });

  const vnpyGapImportMutation = useMutation({
    mutationFn: (dryRun: boolean) =>
      importVnpyMinuteBarsForGaps({
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        gap_file_path: minuteGapFilePath.trim() || undefined,
        interval: "1m",
        tail_entry_start: tailEntryStart,
        tail_entry_end: tailEntryEnd,
        dry_run: dryRun,
        max_gaps: 2000,
      }),
    onSuccess: (result, dryRun) => {
      if (!dryRun && result.rows_written) {
        minuteGapAuditMutation.reset();
        onAuditChange?.(undefined);
      }
    },
  });

  const tushareGapImportMutation = useMutation({
    mutationFn: (dryRun: boolean) =>
      importMinuteGapsFromTushare({
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        gap_file_path: minuteGapFilePath.trim() || undefined,
        interval: "1m",
        tail_entry_start: tailEntryStart,
        tail_entry_end: tailEntryEnd,
        dry_run: dryRun,
        max_gaps: 200,
      }),
    onSuccess: (result, dryRun) => {
      if (!dryRun && result.rows_written) {
        minuteGapAuditMutation.reset();
        onAuditChange?.(undefined);
      }
    },
  });

  const tdxGapImportMutation = useMutation({
    mutationFn: (dryRun: boolean) =>
      importMinuteGapsFromTdx({
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        gap_file_path: minuteGapFilePath.trim() || undefined,
        interval: "1m",
        tail_entry_start: tailEntryStart,
        tail_entry_end: tailEntryEnd,
        dry_run: dryRun,
        max_gaps: 2000,
        max_pages_per_symbol: 32,
        timeout_seconds: 2,
      }),
    onSuccess: (result, dryRun) => {
      if (!dryRun && result.rows_written) {
        minuteGapAuditMutation.reset();
        onAuditChange?.(undefined);
      }
    },
  });

  const strictPipelineMutation = useMutation({
    mutationFn: () =>
      runStrictMinuteBacktestPipeline({
        max_symbols: 1500,
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        gap_file_path: minuteGapFilePath.trim() || undefined,
        min_tail_bars: 1,
        trade_limit: 80,
        tail_entry_start: tailEntryStart,
        tail_entry_end: tailEntryEnd,
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["backtests"] });
      const backtestId = result.backtest?.backtest_id;
      if (backtestId) {
        onStrictPipelineComplete(backtestId);
        queryClient.invalidateQueries({ queryKey: ["backtestReport", backtestId] });
      }
    },
  });

  // ── Derived state ──────────────────────────────────────────────────────
  const audit = minuteGapAuditMutation.data;
  const vendorManifest = minuteVendorManifestMutation.data;
  const importResult = minuteImportMutation.data;
  const vnpyImportResult = vnpyMinuteImportMutation.data;
  const vnpyGapImportResult = vnpyGapImportMutation.data;
  const tushareGapImportResult = tushareGapImportMutation.data;
  const tdxGapImportResult = tdxGapImportMutation.data;
  const strictPipelineResult = strictPipelineMutation.data;
  const canAudit = Boolean(minuteGapCsv.trim() || minuteGapFilePath.trim());
  const canImport = Boolean(minuteImportCsv.trim() || minuteImportFilePath.trim());

  const loadCsvFile = (file: File | undefined, onLoad: (value: string) => void) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setFileError(null);
      onLoad(String(reader.result ?? ""));
    };
    reader.onerror = () => setFileError("读取 CSV 文件失败");
    reader.readAsText(file, "utf-8");
  };

  const isGeneratingVendorManifest = minuteVendorManifestMutation.isPending || minuteVendorManifestCsvMutation.isPending;
  const error =
    minuteGapAuditMutation.error ??
    minuteGapTemplateMutation.error ??
    minuteVendorManifestMutation.error ??
    minuteVendorManifestCsvMutation.error ??
    minuteImportMutation.error ??
    vnpyMinuteImportMutation.error ??
    vnpyGapImportMutation.error ??
    tushareGapImportMutation.error ??
    tdxGapImportMutation.error ??
    strictPipelineMutation.error;

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <section className="rounded-lg border p-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ClipboardCheck size={16} />
          <h2 className="text-sm font-semibold">严格分钟补数</h2>
        </div>
        <div className="flex items-center gap-2">
        {audit && (
          <span
            className={cn(
              "rounded-md border px-2 py-1 text-xs",
              audit.status === "ready" ? "border-green-200 bg-green-50 text-rise" : "border-amber-200 bg-amber-50 text-amber-700"
            )}
          >
            {audit.status === "ready" ? "覆盖完成" : "仍有缺口"}
          </span>
        )}
          <Button size="sm" variant="outline" onClick={() => setExpanded((value) => !value)}>
            {expanded ? "收起" : "展开"}
          </Button>
        </div>
      </div>
      {!expanded && (
        <div className="mt-3 grid grid-cols-2 gap-2 border-t pt-3">
          <InfoCell label="缺口状态" value={audit?.status ?? "未审计"} />
          <InfoCell label="覆盖率" value={formatPct(audit?.coverage_pct)} />
          <InfoCell label="缺口" value={audit?.gap_count == null ? "--" : `${audit.gap_count}个`} />
          <InfoCell label="缺失" value={audit?.missing_count == null ? "--" : `${audit.missing_count}个`} />
        </div>
      )}

      {expanded && (

      <div className="mt-3 space-y-3">
        <MinuteStep
          number="1"
          title="先拿到缺口清单"
          description="严格尾盘回测会记录哪些股票在 D+1 尾盘缺少 1 分钟线。这里先导入或填写这份缺口 CSV。"
        />
        <label className="block">
          <span className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            严格尾盘缺口 CSV
            <span className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-foreground">
              <FileUp size={13} />
              读文件
              <input
                className="hidden"
                type="file"
                accept=".csv,text/csv"
                onChange={(event) => loadCsvFile(event.target.files?.[0], setMinuteGapCsv)}
              />
            </span>
          </span>
          <textarea
            className="mt-1 min-h-24 w-full resize-y rounded-md border bg-background p-2 font-mono text-xs"
            value={minuteGapCsv}
            onChange={(event) => setMinuteGapCsv(event.target.value)}
            placeholder="trade_date,vt_symbol,reference_date,window,ma5..."
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">服务器缺口文件路径</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-xs"
            value={minuteGapFilePath}
            onChange={(event) => setMinuteGapFilePath(event.target.value)}
            placeholder="memory/06_backtests/alphaagent_minute_gap_backtest_10_2025-10-14_2026-06-11.csv"
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => minuteGapAuditMutation.mutate()} disabled={!canAudit || minuteGapAuditMutation.isPending}>
            {minuteGapAuditMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
            审计缺口
          </Button>
          <Button size="sm" variant="outline" onClick={() => minuteGapTemplateMutation.mutate()} disabled={!minuteGapCsv.trim() || minuteGapTemplateMutation.isPending}>
            {minuteGapTemplateMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
            生成模板
          </Button>
          <Button size="sm" variant="outline" onClick={() => minuteVendorManifestMutation.mutate()} disabled={!canAudit || isGeneratingVendorManifest}>
            {isGeneratingVendorManifest ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
            预览补数清单
          </Button>
          <Button size="sm" variant="outline" onClick={() => minuteVendorManifestCsvMutation.mutate()} disabled={!canAudit || isGeneratingVendorManifest}>
            {isGeneratingVendorManifest ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
            导出补数清单
          </Button>
        </div>

        {vendorManifest && (
          <div className="grid grid-cols-2 gap-2 rounded-md border p-3 text-xs">
            <InfoCell label="补数请求" value={`${vendorManifest.request_count ?? 0}行`} />
            <InfoCell label="股票" value={`${vendorManifest.symbol_count ?? 0}只`} />
            <InfoCell label="交易日" value={`${vendorManifest.date_count ?? 0}天`} />
            <InfoCell label="窗口" value={vendorManifest.tail_entry_window ?? "--"} />
            <InfoCell label="开始" value={vendorManifest.start_date ?? "--"} />
            <InfoCell label="结束" value={vendorManifest.end_date ?? "--"} />
          </div>
        )}

        {minuteVendorManifestCsv && (
          <label className="block">
            <span className="text-xs text-muted-foreground">供应商补数清单 CSV</span>
            <textarea className="mt-1 min-h-20 w-full resize-y rounded-md border bg-muted/30 p-2 font-mono text-xs" readOnly value={minuteVendorManifestCsv} />
          </label>
        )}

        {audit && (
          <div className="grid grid-cols-2 gap-2 border-t pt-3">
            <InfoCell label="缺口" value={`${audit.gap_count ?? 0}个`} />
            <InfoCell label="已覆盖" value={`${audit.covered_count ?? 0}个`} />
            <InfoCell label="缺失" value={`${audit.missing_count ?? 0}个`} />
            <InfoCell label="覆盖率" value={formatPct(audit.coverage_pct)} />
            <InfoCell label="股票数" value={`${audit.symbol_count ?? 0}只`} />
            <InfoCell label="交易日" value={`${audit.date_count ?? 0}天`} />
          </div>
        )}
        {audit && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => strictPipelineMutation.mutate()} disabled={!canAudit || strictPipelineMutation.isPending || isRunningBacktest}>
              {strictPipelineMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
              审计并运行严格回测
            </Button>
          </div>
        )}
        {strictPipelineResult && (
          <div
            className={cn(
              "rounded-md border p-3 text-xs",
              strictPipelineResult.status === "ready" ? "border-green-200 bg-green-50 text-rise" : "border-amber-200 bg-amber-50 text-amber-700"
            )}
          >
            <div className="font-medium">{strictPipelineResult.message ?? strictPipelineResult.status}</div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-foreground">
              <InfoCell label="状态" value={strictPipelineResult.status} />
              <InfoCell label="缺口覆盖" value={formatPct(strictPipelineResult.audit?.coverage_pct)} />
              <InfoCell label="缺口" value={`${strictPipelineResult.audit?.gap_count ?? 0}个`} />
              <InfoCell label="缺失" value={`${strictPipelineResult.audit?.missing_count ?? 0}个`} />
              <InfoCell label="回测ID" value={strictPipelineResult.backtest?.backtest_id ?? "--"} />
              <InfoCell label="CSV" value={strictPipelineResult.csv?.filename ?? "--"} />
            </div>
            {strictPipelineResult.next_action && <div className="mt-2">{strictPipelineResult.next_action}</div>}
          </div>
        )}

        {minuteGapTemplate && (
          <label className="block border-t pt-3">
            <span className="text-xs text-muted-foreground">待填分钟线模板</span>
            <textarea className="mt-1 min-h-20 w-full resize-y rounded-md border bg-muted/30 p-2 font-mono text-xs" readOnly value={minuteGapTemplate} />
          </label>
        )}

        <MinuteStep
          number="2"
          title="补齐分钟线"
          description="可从外部 CSV、vn.py 数据库、TDX 公开源或 Tushare Pro 回填。建议先预检查，再正式导入。"
        />
        <label className="block border-t pt-3">
          <span className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            外部分钟线 CSV
            <span className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-foreground">
              <FileUp size={13} />
              读文件
              <input
                className="hidden"
                type="file"
                accept=".csv,text/csv"
                onChange={(event) => loadCsvFile(event.target.files?.[0], setMinuteImportCsv)}
              />
            </span>
          </span>
          <textarea
            className="mt-1 min-h-24 w-full resize-y rounded-md border bg-background p-2 font-mono text-xs"
            value={minuteImportCsv}
            onChange={(event) => setMinuteImportCsv(event.target.value)}
            placeholder="vt_symbol,bar_time,open,high,low,close,volume,turnover..."
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">服务器分钟线文件路径</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-xs"
            value={minuteImportFilePath}
            onChange={(event) => setMinuteImportFilePath(event.target.value)}
            placeholder="data/imports/xt_1m_bars.csv"
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => minuteImportMutation.mutate(true)} disabled={!canImport || minuteImportMutation.isPending}>
            {minuteImportMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
            预检查
          </Button>
          <Button size="sm" onClick={() => minuteImportMutation.mutate(false)} disabled={!canImport || minuteImportMutation.isPending}>
            {minuteImportMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <Upload size={15} />}
            导入
          </Button>
        </div>

        {importResult && (
          <div className="grid grid-cols-2 gap-2 border-t pt-3">
            <InfoCell label="状态" value={importResult.status} />
            <InfoCell label="预检查" value={importResult.dry_run ? "是" : "否"} />
            <InfoCell label="读取" value={`${importResult.rows_read ?? 0}行`} />
            <InfoCell label="写入" value={`${importResult.rows_written ?? 0}行`} />
            <InfoCell label="跳过" value={`${importResult.rows_skipped ?? 0}行`} />
            <InfoCell label="股票" value={`${importResult.symbol_count ?? 0}只`} />
          </div>
        )}

        <div className="border-t pt-3">
          <div className="text-xs text-muted-foreground">vn.py 数据库分钟线</div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <input
              className="h-9 rounded-md border bg-background px-2 text-xs"
              value={vnpyImportParams.vt_symbol}
              onChange={(event) => setVnpyImportParams({ ...vnpyImportParams, vt_symbol: event.target.value })}
              placeholder="600000.SSE"
            />
            <input
              className="h-9 rounded-md border bg-background px-2 text-xs"
              type="date"
              value={vnpyImportParams.start}
              onChange={(event) => setVnpyImportParams({ ...vnpyImportParams, start: event.target.value })}
            />
            <input
              className="h-9 rounded-md border bg-background px-2 text-xs"
              type="date"
              value={vnpyImportParams.end}
              onChange={(event) => setVnpyImportParams({ ...vnpyImportParams, end: event.target.value })}
            />
            <label className="flex h-9 items-center gap-2 rounded-md border px-2 text-xs">
              <input
                type="checkbox"
                checked={vnpyImportParams.dry_run}
                onChange={(event) => setVnpyImportParams({ ...vnpyImportParams, dry_run: event.target.checked })}
              />
              预检查
            </label>
          </div>
          <Button
            className="mt-2"
            size="sm"
            variant="outline"
            onClick={() => vnpyMinuteImportMutation.mutate()}
            disabled={!vnpyImportParams.vt_symbol.trim() || !vnpyImportParams.start || vnpyMinuteImportMutation.isPending}
          >
            {vnpyMinuteImportMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
            单标的导入
          </Button>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => vnpyGapImportMutation.mutate(true)}
              disabled={!canAudit || vnpyGapImportMutation.isPending}
            >
              {vnpyGapImportMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
              按缺口预检查
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => vnpyGapImportMutation.mutate(false)}
              disabled={!canAudit || vnpyGapImportMutation.isPending}
            >
              {vnpyGapImportMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
              按缺口导入
            </Button>
          </div>
          {vnpyImportResult && (
            <div className="mt-3 grid grid-cols-2 gap-2">
              <InfoCell label="状态" value={vnpyImportResult.status} />
              <InfoCell label="预检查" value={vnpyImportResult.dry_run ? "是" : "否"} />
              <InfoCell label="读取" value={`${vnpyImportResult.rows_read ?? 0}行`} />
              <InfoCell label="写入" value={`${vnpyImportResult.rows_written ?? 0}行`} />
            </div>
          )}
          {vnpyGapImportResult && (
            <div className="mt-3 grid grid-cols-2 gap-2">
              <InfoCell label="批量状态" value={vnpyGapImportResult.status} />
              <InfoCell label="预检查" value={vnpyGapImportResult.dry_run ? "是" : "否"} />
              <InfoCell label="处理缺口" value={`${vnpyGapImportResult.processed_gap_count ?? 0}个`} />
              <InfoCell label="读取" value={`${vnpyGapImportResult.rows_read ?? 0}行`} />
              <InfoCell label="写入" value={`${vnpyGapImportResult.rows_written ?? 0}行`} />
              <InfoCell label="空请求" value={`${vnpyGapImportResult.empty_request_count ?? 0}个`} />
              <InfoCell label="导入后覆盖" value={formatPct(vnpyGapImportResult.audit_after?.coverage_pct)} />
              <InfoCell label="导入后缺失" value={`${vnpyGapImportResult.audit_after?.missing_count ?? 0}个`} />
            </div>
          )}
        </div>

        <div className="border-t pt-3">
          <div className="text-xs text-muted-foreground">通达信公开行情历史分钟线</div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => tdxGapImportMutation.mutate(true)}
              disabled={!canAudit || tdxGapImportMutation.isPending}
            >
              {tdxGapImportMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
              TDX预检查
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => tdxGapImportMutation.mutate(false)}
              disabled={!canAudit || tdxGapImportMutation.isPending}
            >
              {tdxGapImportMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
              TDX导入
            </Button>
          </div>
          {tdxGapImportResult && (
            <div className="mt-3 grid grid-cols-2 gap-2">
              <InfoCell label="状态" value={tdxGapImportResult.status} />
              <InfoCell label="预检查" value={tdxGapImportResult.dry_run ? "是" : "否"} />
              <InfoCell label="处理缺口" value={`${tdxGapImportResult.processed_gap_count ?? 0}个`} />
              <InfoCell label="读取" value={`${tdxGapImportResult.rows_read ?? 0}行`} />
              <InfoCell label="写入" value={`${tdxGapImportResult.rows_written ?? 0}行`} />
              <InfoCell label="扫描" value={`${tdxGapImportResult.remote_rows_scanned ?? 0}行`} />
              <InfoCell label="预覆盖" value={`${tdxGapImportResult.preview_covered_gap_count ?? 0}个`} />
              <InfoCell label="导入后覆盖" value={formatPct(tdxGapImportResult.audit_after?.coverage_pct)} />
            </div>
          )}
          {tdxGapImportResult?.message && (
            <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
              {tdxGapImportResult.message}
            </div>
          )}
        </div>

        <div className="border-t pt-3">
          <div className="text-xs text-muted-foreground">Tushare Pro 历史分钟线</div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => tushareGapImportMutation.mutate(true)}
              disabled={!canAudit || tushareGapImportMutation.isPending}
            >
              {tushareGapImportMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
              Tushare预检查
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => tushareGapImportMutation.mutate(false)}
              disabled={!canAudit || tushareGapImportMutation.isPending}
            >
              {tushareGapImportMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
              Tushare导入
            </Button>
          </div>
          {tushareGapImportResult && (
            <div className="mt-3 grid grid-cols-2 gap-2">
              <InfoCell label="状态" value={tushareGapImportResult.status} />
              <InfoCell label="预检查" value={tushareGapImportResult.dry_run ? "是" : "否"} />
              <InfoCell label="处理缺口" value={`${tushareGapImportResult.processed_gap_count ?? 0}个`} />
              <InfoCell label="读取" value={`${tushareGapImportResult.rows_read ?? 0}行`} />
              <InfoCell label="写入" value={`${tushareGapImportResult.rows_written ?? 0}行`} />
              <InfoCell label="空请求" value={`${tushareGapImportResult.empty_request_count ?? 0}个`} />
              <InfoCell label="错期过滤" value={`${tushareGapImportResult.wrong_date_row_count ?? 0}行`} />
              <InfoCell label="导入后覆盖" value={formatPct(tushareGapImportResult.audit_after?.coverage_pct)} />
            </div>
          )}
          {tushareGapImportResult?.message && (
            <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
              {tushareGapImportResult.message}
            </div>
          )}
        </div>

        {audit?.missing_examples && audit.missing_examples.length > 0 && (
          <div className="border-t pt-3">
            <div className="text-xs text-muted-foreground">缺口示例</div>
            <div className="mt-2 max-h-28 overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>股票</TableHead>
                    <TableHead>日期</TableHead>
                    <TableHead className="text-right">分钟线</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {audit.missing_examples.slice(0, 8).map((row) => (
                    <TableRow key={`${row.vt_symbol}-${row.trade_date}`}>
                      <TableCell>
                        <StockIdentityLink vtSymbol={row.vt_symbol} />
                      </TableCell>
                      <TableCell>{row.trade_date}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.minute_bar_count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        <MinuteStep
          number="3"
          title="复审后再跑严格回测"
          description="导入后重新审计缺口。只有覆盖率为 100% 时，严格流水线才会生成真实尾盘分钟成交回测。"
        />
        {fileError ? <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-fall">{fileError}</div> : null}
        {error ? <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-fall">{String(error)}</div> : null}
      </div>
      )}
    </section>
  );
}

function MinuteStep({ number, title, description }: { number: string; title: string; description: string }) {
  return (
    <div className="flex gap-3 rounded-lg border bg-muted/20 p-3">
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border bg-background text-xs font-medium">
        {number}
      </div>
      <div className="min-w-0">
        <div className="font-medium">{title}</div>
        <div className="mt-1 text-xs leading-5 text-muted-foreground">{description}</div>
      </div>
    </div>
  );
}
