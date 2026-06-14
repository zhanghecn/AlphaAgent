import { ClipboardCheck, Download, FileUp, RefreshCw, ShieldCheck } from "lucide-react";
import { InfoCell } from "@/components/InfoCell";
import { Button } from "@/components/ui/button";
import type {
  MinuteGapAuditResult,
  MinuteGapProviderImportResult,
  MinuteGapVendorManifest,
} from "@/api/dataSync";
import { formatPct } from "@/lib/utils";
import { type GapProvider, type LoadCsvFile, MinuteStep, type StrictPipelineResult } from "@/features/quant/MinuteDataWizardPanels";

export function StrictMinuteSourcePanel({
  audit,
  sourceBacktestId,
  setSourceBacktestId,
  backtestId,
  minuteGapFilePath,
  preferredProvider,
  setPreferredProvider,
  canAudit,
  auditPending,
  selectedImportPending,
  strictPipelinePending,
  isRunningBacktest,
  canRunStrictPipeline,
  selectedImportResult,
  onAudit,
  onPreferredGapImport,
  onRunStrictPipeline,
}: {
  audit?: MinuteGapAuditResult;
  sourceBacktestId: string;
  setSourceBacktestId: (value: string) => void;
  backtestId?: number | null;
  minuteGapFilePath: string;
  preferredProvider: GapProvider;
  setPreferredProvider: (value: GapProvider) => void;
  canAudit: boolean;
  auditPending: boolean;
  selectedImportPending: boolean;
  strictPipelinePending: boolean;
  isRunningBacktest: boolean;
  canRunStrictPipeline: boolean;
  selectedImportResult?: MinuteGapProviderImportResult;
  onAudit: () => void;
  onPreferredGapImport: (dryRun: boolean) => void;
  onRunStrictPipeline: () => void;
}) {
  return (
    <div className="mt-3 space-y-3 border-t pt-3">
      <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_180px_140px]">
        <label className="text-xs text-muted-foreground">
          回测 ID
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
            value={sourceBacktestId}
            onChange={(event) => setSourceBacktestId(event.target.value)}
            placeholder={backtestId ? `当前回测 ${backtestId}` : "例如 42"}
            disabled={Boolean(minuteGapFilePath.trim())}
          />
        </label>
        <label className="text-xs text-muted-foreground">
          数据源
          <select
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
            value={preferredProvider}
            onChange={(event) => setPreferredProvider(event.target.value as GapProvider)}
          >
            <option value="akshare">AkShare近端</option>
            <option value="tdx">TDX公开源</option>
            <option value="tushare">Tushare Pro</option>
            <option value="vnpy">vn.py本地库</option>
          </select>
        </label>
        <div className="text-xs text-muted-foreground">
          周期
          <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/30 px-2 text-sm">1分钟 / 14:30快照</div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={onAudit} disabled={!canAudit || auditPending}>
          {auditPending ? <RefreshCw size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
          审计缺口
        </Button>
        <Button size="sm" variant="outline" onClick={() => onPreferredGapImport(true)} disabled={!canAudit || selectedImportPending}>
          {selectedImportPending ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
          预检查
        </Button>
        <Button size="sm" variant="outline" onClick={() => onPreferredGapImport(false)} disabled={!canAudit || selectedImportPending}>
          {selectedImportPending ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
          补齐14:30缺口
        </Button>
        <Button size="sm" onClick={onRunStrictPipeline} disabled={!canRunStrictPipeline || strictPipelinePending || isRunningBacktest}>
          {strictPipelinePending ? <RefreshCw size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
          审计并运行严格回测
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <InfoCell label="缺口状态" value={audit?.status ?? "未审计"} />
        <InfoCell label="覆盖率" value={formatPct(audit?.coverage_pct)} />
        <InfoCell label="缺口" value={audit?.gap_count == null ? "--" : `${audit.gap_count}个`} />
        <InfoCell label="缺失" value={audit?.missing_count == null ? "--" : `${audit.missing_count}个`} />
        <InfoCell label="读取" value={selectedImportResult?.rows_read == null ? "--" : `${selectedImportResult.rows_read}行`} />
        <InfoCell label="写入" value={selectedImportResult?.rows_written == null ? "--" : `${selectedImportResult.rows_written}行`} />
        <InfoCell label="导入后覆盖" value={formatPct(selectedImportResult?.audit_after?.coverage_pct)} />
        <InfoCell
          label="导入后缺失"
          value={selectedImportResult?.audit_after?.missing_count == null ? "--" : `${selectedImportResult.audit_after.missing_count}个`}
        />
      </div>
      <div className="text-xs text-muted-foreground">
        优先用回测 ID 生成缺口；AkShare 适合近端交易日，长历史缺口以审计结果为准。CSV 入口在高级区域。
      </div>
      {canAudit && !canRunStrictPipeline ? (
        <div className="text-xs text-amber-700 dark:text-amber-300">
          无回测 ID 的高级来源需要展开并确认后，才允许用默认股票池参数运行严格回测。
        </div>
      ) : null}
    </div>
  );
}

export function AdvancedGapSourcePanel({
  minuteGapCsv,
  setMinuteGapCsv,
  sourceBacktestId,
  minuteGapFilePath,
  setMinuteGapFilePath,
  loadCsvFile,
  canAudit,
  auditPending,
  templatePending,
  manifestPending,
  vendorManifest,
  minuteVendorManifestCsv,
  audit,
  minuteInterval,
  onAudit,
  onGenerateTemplate,
  onPreviewManifest,
  onExportManifestCsv,
}: {
  minuteGapCsv: string;
  setMinuteGapCsv: (value: string) => void;
  sourceBacktestId: string;
  minuteGapFilePath: string;
  setMinuteGapFilePath: (value: string) => void;
  loadCsvFile: LoadCsvFile;
  canAudit: boolean;
  auditPending: boolean;
  templatePending: boolean;
  manifestPending: boolean;
  vendorManifest?: MinuteGapVendorManifest;
  minuteVendorManifestCsv: string;
  audit?: MinuteGapAuditResult;
  minuteInterval: string;
  onAudit: () => void;
  onGenerateTemplate: () => void;
  onPreviewManifest: () => void;
  onExportManifestCsv: () => void;
}) {
  return (
    <>
      <MinuteStep
        number="1"
        title="高级缺口来源"
        description="普通路径只需要回测 ID。下面的 CSV 和服务器文件路径只用于供应商文件或本地历史清单兜底。"
      />
      <label className="block">
        <span className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          高级兜底：严格14:30缺口 CSV
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
          disabled={Boolean(sourceBacktestId.trim() || minuteGapFilePath.trim())}
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
        <Button size="sm" variant="outline" onClick={onAudit} disabled={!canAudit || auditPending}>
          {auditPending ? <RefreshCw size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
          审计缺口
        </Button>
        <Button size="sm" variant="outline" onClick={onGenerateTemplate} disabled={!canAudit || templatePending}>
          {templatePending ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
          生成模板
        </Button>
        <Button size="sm" variant="outline" onClick={onPreviewManifest} disabled={!canAudit || manifestPending}>
          {manifestPending ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
          预览补数清单
        </Button>
        <Button size="sm" variant="outline" onClick={onExportManifestCsv} disabled={!canAudit || manifestPending}>
          {manifestPending ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
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
          <InfoCell label="周期" value={audit.interval ?? minuteInterval} />
          <InfoCell label="覆盖率" value={formatPct(audit.coverage_pct)} />
          <InfoCell label="股票数" value={`${audit.symbol_count ?? 0}只`} />
          <InfoCell label="交易日" value={`${audit.date_count ?? 0}天`} />
        </div>
      )}
    </>
  );
}

export function StrictPipelineResultPanel({
  result,
  minuteInterval,
}: {
  result?: StrictPipelineResult;
  minuteInterval: string;
}) {
  if (!result) return null;

  return (
    <div
      className={
        result.status === "ready"
          ? "rounded-md border border-green-200 bg-green-50 p-3 text-xs text-rise dark:border-green-500/30 dark:bg-green-500/10"
          : "rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300"
      }
    >
      <div className="font-medium">{result.message ?? result.status}</div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-foreground">
        <InfoCell label="状态" value={result.status} />
        <InfoCell label="周期" value={String(result.params?.minute_interval ?? minuteInterval)} />
        <InfoCell label="缺口覆盖" value={formatPct(result.audit?.coverage_pct)} />
        <InfoCell label="缺口" value={`${result.audit?.gap_count ?? 0}个`} />
        <InfoCell label="缺失" value={`${result.audit?.missing_count ?? 0}个`} />
        <InfoCell label="回测ID" value={result.backtest?.backtest_id ?? "--"} />
        <InfoCell label="报告" value={result.csv?.filename ?? "--"} />
      </div>
      {result.next_action && <div className="mt-2">{result.next_action}</div>}
    </div>
  );
}

export function AdvancedStrictRunConfirmation({
  checked,
  onCheckedChange,
  visible,
}: {
  checked: boolean;
  onCheckedChange: (value: boolean) => void;
  visible: boolean;
}) {
  if (!visible) return null;

  return (
    <label className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
      <input
        className="mt-0.5"
        type="checkbox"
        checked={checked}
        onChange={(event) => onCheckedChange(event.target.checked)}
      />
      <span>
        我确认当前使用的是高级 CSV/file_path 来源，严格回测将使用默认股票池参数运行；优先做法仍是输入源回测 ID 复用原始回测参数。
      </span>
    </label>
  );
}

export function MinuteGapTemplatePanel({ template }: { template: string }) {
  if (!template) return null;

  return (
    <label className="block border-t pt-3">
      <span className="text-xs text-muted-foreground">待填分钟线模板</span>
      <textarea className="mt-1 min-h-20 w-full resize-y rounded-md border bg-muted/30 p-2 font-mono text-xs" readOnly value={template} />
    </label>
  );
}
