import { ClipboardCheck, FileUp, RefreshCw, Upload } from "lucide-react";
import { InfoCell } from "@/components/InfoCell";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { MinuteBarsImportResult, MinuteGapAuditResult } from "@/api/dataSync";
import type { LoadCsvFile } from "@/features/quant/MinuteDataWizardPanels";

export function ExternalMinuteCsvFallbackPanel({
  minuteImportCsv,
  setMinuteImportCsv,
  minuteImportFilePath,
  setMinuteImportFilePath,
  loadCsvFile,
  canImport,
  importPending,
  importResult,
  minuteInterval,
  onImport,
}: {
  minuteImportCsv: string;
  setMinuteImportCsv: (value: string) => void;
  minuteImportFilePath: string;
  setMinuteImportFilePath: (value: string) => void;
  loadCsvFile: LoadCsvFile;
  canImport: boolean;
  importPending: boolean;
  importResult?: MinuteBarsImportResult;
  minuteInterval: string;
  onImport: (dryRun: boolean) => void;
}) {
  return (
    <details className="border-t pt-3">
      <summary className="cursor-pointer text-xs text-muted-foreground">高级兜底：外部分钟线 CSV</summary>
      <div className="mt-3 space-y-3">
        <label className="block">
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
          <Button size="sm" variant="outline" onClick={() => onImport(true)} disabled={!canImport || importPending}>
            {importPending ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
            预检查
          </Button>
          <Button size="sm" onClick={() => onImport(false)} disabled={!canImport || importPending}>
            {importPending ? <RefreshCw size={15} className="animate-spin" /> : <Upload size={15} />}
            导入
          </Button>
        </div>

        {importResult && (
          <div className="grid grid-cols-2 gap-2">
            <InfoCell label="状态" value={importResult.status} />
            <InfoCell label="周期" value={importResult.interval ?? minuteInterval} />
            <InfoCell label="预检查" value={importResult.dry_run ? "是" : "否"} />
            <InfoCell label="读取" value={`${importResult.rows_read ?? 0}行`} />
            <InfoCell label="写入" value={`${importResult.rows_written ?? 0}行`} />
            <InfoCell label="跳过" value={`${importResult.rows_skipped ?? 0}行`} />
            <InfoCell label="股票" value={`${importResult.symbol_count ?? 0}只`} />
          </div>
        )}
      </div>
    </details>
  );
}

export function MinuteGapExamplesPanel({ audit }: { audit?: MinuteGapAuditResult }) {
  if (!audit?.missing_examples?.length) return null;

  return (
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
  );
}

export function MinuteWizardMessages({
  fileError,
  error,
}: {
  fileError?: string | null;
  error?: unknown;
}) {
  return (
    <>
      {fileError ? (
        <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-fall dark:border-red-500/30 dark:bg-red-500/10">
          {fileError}
        </div>
      ) : null}
      {error ? (
        <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-fall dark:border-red-500/30 dark:bg-red-500/10">
          {String(error)}
        </div>
      ) : null}
    </>
  );
}
