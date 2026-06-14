import { ClipboardCheck, Download, RefreshCw } from "lucide-react";
import { InfoCell } from "@/components/InfoCell";
import { Button } from "@/components/ui/button";
import type { MinuteGapProviderImportResult } from "@/api/dataSync";
import { formatPct } from "@/lib/utils";
import { MinuteStep, type VnpyMinuteImportParams, type VnpySingleMinuteImportResult } from "@/features/quant/MinuteDataWizardPanels";

export function ProviderMinuteImportPanel({
  minuteInterval,
  canAudit,
  vnpyImportParams,
  setVnpyImportParams,
  vnpyImportPending,
  vnpyGapImportPending,
  tdxGapImportPending,
  tushareGapImportPending,
  vnpyImportResult,
  vnpyGapImportResult,
  tdxGapImportResult,
  tushareGapImportResult,
  onVnpySingleImport,
  onVnpyGapImport,
  onTdxGapImport,
  onTushareGapImport,
}: {
  minuteInterval: string;
  canAudit: boolean;
  vnpyImportParams: VnpyMinuteImportParams;
  setVnpyImportParams: (value: VnpyMinuteImportParams) => void;
  vnpyImportPending: boolean;
  vnpyGapImportPending: boolean;
  tdxGapImportPending: boolean;
  tushareGapImportPending: boolean;
  vnpyImportResult?: VnpySingleMinuteImportResult;
  vnpyGapImportResult?: MinuteGapProviderImportResult;
  tdxGapImportResult?: MinuteGapProviderImportResult;
  tushareGapImportResult?: MinuteGapProviderImportResult;
  onVnpySingleImport: () => void;
  onVnpyGapImport: (dryRun: boolean) => void;
  onTdxGapImport: (dryRun: boolean) => void;
  onTushareGapImport: (dryRun: boolean) => void;
}) {
  return (
    <>
      <MinuteStep
        number="2"
        title="补齐分钟线"
        description="优先用 vn.py 数据库、TDX 公开源或 Tushare Pro 按缺口回填。外部 CSV 只作为供应商文件兜底。"
      />
      <VnpyMinuteImportSection
        minuteInterval={minuteInterval}
        canAudit={canAudit}
        params={vnpyImportParams}
        setParams={setVnpyImportParams}
        importPending={vnpyImportPending}
        gapImportPending={vnpyGapImportPending}
        importResult={vnpyImportResult}
        gapImportResult={vnpyGapImportResult}
        onSingleImport={onVnpySingleImport}
        onGapImport={onVnpyGapImport}
      />
      <GapProviderSection
        title="通达信公开行情历史分钟线"
        primaryLabel="TDX预检查"
        secondaryLabel="TDX导入"
        pending={tdxGapImportPending}
        canAudit={canAudit}
        result={tdxGapImportResult}
        minuteInterval={minuteInterval}
        variant="tdx"
        onImport={onTdxGapImport}
      />
      <GapProviderSection
        title="Tushare Pro 历史分钟线"
        primaryLabel="Tushare预检查"
        secondaryLabel="Tushare导入"
        pending={tushareGapImportPending}
        canAudit={canAudit}
        result={tushareGapImportResult}
        minuteInterval={minuteInterval}
        variant="tushare"
        onImport={onTushareGapImport}
      />
    </>
  );
}

function VnpyMinuteImportSection({
  minuteInterval,
  canAudit,
  params,
  setParams,
  importPending,
  gapImportPending,
  importResult,
  gapImportResult,
  onSingleImport,
  onGapImport,
}: {
  minuteInterval: string;
  canAudit: boolean;
  params: VnpyMinuteImportParams;
  setParams: (value: VnpyMinuteImportParams) => void;
  importPending: boolean;
  gapImportPending: boolean;
  importResult?: VnpySingleMinuteImportResult;
  gapImportResult?: MinuteGapProviderImportResult;
  onSingleImport: () => void;
  onGapImport: (dryRun: boolean) => void;
}) {
  return (
    <div className="border-t pt-3">
      <div className="text-xs text-muted-foreground">vn.py 数据库分钟线</div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <input
          className="h-9 rounded-md border bg-background px-2 text-xs"
          value={params.vt_symbol}
          onChange={(event) => setParams({ ...params, vt_symbol: event.target.value })}
          placeholder="600000.SSE"
        />
        <input
          className="h-9 rounded-md border bg-background px-2 text-xs"
          type="date"
          value={params.start}
          onChange={(event) => setParams({ ...params, start: event.target.value })}
        />
        <input
          className="h-9 rounded-md border bg-background px-2 text-xs"
          type="date"
          value={params.end}
          onChange={(event) => setParams({ ...params, end: event.target.value })}
        />
        <label className="flex h-9 items-center gap-2 rounded-md border px-2 text-xs">
          <input
            type="checkbox"
            checked={params.dry_run}
            onChange={(event) => setParams({ ...params, dry_run: event.target.checked })}
          />
          预检查
        </label>
      </div>
      <Button
        className="mt-2"
        size="sm"
        variant="outline"
        onClick={onSingleImport}
        disabled={!params.vt_symbol.trim() || !params.start || importPending}
      >
        {importPending ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
        单标的导入
      </Button>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => onGapImport(true)} disabled={!canAudit || gapImportPending}>
          {gapImportPending ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
          按缺口预检查
        </Button>
        <Button size="sm" variant="outline" onClick={() => onGapImport(false)} disabled={!canAudit || gapImportPending}>
          {gapImportPending ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
          按缺口导入
        </Button>
      </div>
      <VnpyImportResultGrid result={importResult} minuteInterval={minuteInterval} />
      <GapImportResultGrid result={gapImportResult} minuteInterval={minuteInterval} variant="vnpy" />
    </div>
  );
}

function GapProviderSection({
  title,
  primaryLabel,
  secondaryLabel,
  pending,
  canAudit,
  result,
  minuteInterval,
  variant,
  onImport,
}: {
  title: string;
  primaryLabel: string;
  secondaryLabel: string;
  pending: boolean;
  canAudit: boolean;
  result?: MinuteGapProviderImportResult;
  minuteInterval: string;
  variant: "tdx" | "tushare";
  onImport: (dryRun: boolean) => void;
}) {
  return (
    <div className="border-t pt-3">
      <div className="text-xs text-muted-foreground">{title}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => onImport(true)} disabled={!canAudit || pending}>
          {pending ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
          {primaryLabel}
        </Button>
        <Button size="sm" variant="outline" onClick={() => onImport(false)} disabled={!canAudit || pending}>
          {pending ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
          {secondaryLabel}
        </Button>
      </div>
      <GapImportResultGrid result={result} minuteInterval={minuteInterval} variant={variant} />
      <ProviderMessage message={result?.message} />
    </div>
  );
}

function VnpyImportResultGrid({
  result,
  minuteInterval,
}: {
  result?: VnpySingleMinuteImportResult;
  minuteInterval: string;
}) {
  if (!result) return null;

  return (
    <div className="mt-3 grid grid-cols-2 gap-2">
      <InfoCell label="状态" value={result.status} />
      <InfoCell label="周期" value={result.interval ?? minuteInterval} />
      <InfoCell label="预检查" value={result.dry_run ? "是" : "否"} />
      <InfoCell label="读取" value={`${result.rows_read ?? 0}行`} />
      <InfoCell label="写入" value={`${result.rows_written ?? 0}行`} />
    </div>
  );
}

function GapImportResultGrid({
  result,
  minuteInterval,
  variant,
}: {
  result?: MinuteGapProviderImportResult;
  minuteInterval: string;
  variant: "vnpy" | "tdx" | "tushare";
}) {
  if (!result) return null;

  return (
    <div className="mt-3 grid grid-cols-2 gap-2">
      <InfoCell label={variant === "vnpy" ? "批量状态" : "状态"} value={result.status} />
      <InfoCell label="周期" value={result.interval ?? minuteInterval} />
      <InfoCell label="预检查" value={result.dry_run ? "是" : "否"} />
      <InfoCell label="处理缺口" value={`${result.processed_gap_count ?? 0}个`} />
      <InfoCell label="读取" value={`${result.rows_read ?? 0}行`} />
      <InfoCell label="写入" value={`${result.rows_written ?? 0}行`} />
      {variant === "tdx" ? <InfoCell label="扫描" value={`${result.remote_rows_scanned ?? 0}行`} /> : null}
      {variant === "tdx" ? <InfoCell label="预覆盖" value={`${result.preview_covered_gap_count ?? 0}个`} /> : null}
      {variant !== "tdx" ? <InfoCell label="空请求" value={`${result.empty_request_count ?? 0}个`} /> : null}
      {variant === "tushare" ? <InfoCell label="错期过滤" value={`${result.wrong_date_row_count ?? 0}行`} /> : null}
      <InfoCell label="导入后覆盖" value={formatPct(result.audit_after?.coverage_pct)} />
      {variant === "vnpy" ? <InfoCell label="导入后缺失" value={`${result.audit_after?.missing_count ?? 0}个`} /> : null}
    </div>
  );
}

function ProviderMessage({ message }: { message?: string }) {
  if (!message) return null;

  return (
    <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
      {message}
    </div>
  );
}
