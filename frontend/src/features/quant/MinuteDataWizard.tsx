import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck } from "lucide-react";
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
  importMinuteGapsFromAkshare,
  importMinuteGapsFromTdx,
  importMinuteGapsFromTushare,
  type MinuteGapAuditResult,
} from "@/api/dataSync";
import { Button } from "@/components/ui/button";
import { DEFAULT_BACKTEST_START } from "@/features/quant/constants";
import {
  AdvancedStrictRunConfirmation,
  AdvancedGapSourcePanel,
  ExternalMinuteCsvFallbackPanel,
  type GapProvider,
  MinuteGapExamplesPanel,
  MinuteGapTemplatePanel,
  MinuteStep,
  MinuteWizardMessages,
  ProviderMinuteImportPanel,
  StrictMinuteSourcePanel,
  StrictPipelineResultPanel,
  type VnpyMinuteImportParams,
} from "@/features/quant/MinuteDataWizardPanels";
import { cn } from "@/lib/utils";

export interface MinuteDataWizardProps {
  tailEntryStart: string;
  tailEntryEnd: string;
  minuteInterval: string;
  backtestId?: number | null;
  isRunningBacktest: boolean;
  onStrictPipelineComplete: (backtestId: number) => void;
  onAuditChange?: (audit: MinuteGapAuditResult | undefined) => void;
}

export function MinuteDataWizard({
  tailEntryStart,
  tailEntryEnd,
  minuteInterval,
  backtestId,
  isRunningBacktest,
  onStrictPipelineComplete,
  onAuditChange,
}: MinuteDataWizardProps) {
  const queryClient = useQueryClient();

  const [minuteGapCsv, setMinuteGapCsv] = useState("");
  const [minuteImportCsv, setMinuteImportCsv] = useState("");
  const [minuteGapFilePath, setMinuteGapFilePath] = useState("");
  const [sourceBacktestId, setSourceBacktestId] = useState(backtestId ? String(backtestId) : "");
  const [minuteImportFilePath, setMinuteImportFilePath] = useState("");
  const [minuteGapTemplate, setMinuteGapTemplate] = useState("");
  const [minuteVendorManifestCsv, setMinuteVendorManifestCsv] = useState("");
  const [preferredProvider, setPreferredProvider] = useState<GapProvider>("akshare");
  const [vnpyImportParams, setVnpyImportParams] = useState<VnpyMinuteImportParams>({
    vt_symbol: "600000.SSE",
    start: DEFAULT_BACKTEST_START,
    end: "",
    dry_run: true,
  });
  const [fileError, setFileError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [allowAdvancedStrictRun, setAllowAdvancedStrictRun] = useState(false);

  useEffect(() => {
    if (backtestId && !minuteGapFilePath.trim()) {
      setSourceBacktestId(String(backtestId));
    }
  }, [backtestId, minuteGapFilePath]);

  const gapSourcePayload = () => {
    const id = sourceBacktestId.trim();
    const filePath = minuteGapFilePath.trim();
    return {
      backtest_id: filePath || !id ? undefined : id,
      gap_csv_text: filePath || id ? undefined : minuteGapCsv,
      gap_file_path: filePath || undefined,
      file_path: filePath || undefined,
    };
  };

  const hasSourceBacktestId = Boolean(sourceBacktestId.trim() && !minuteGapFilePath.trim());
  const hasAdvancedGapSource = Boolean(minuteGapCsv.trim() || minuteGapFilePath.trim());
  const canRunStrictPipeline = hasSourceBacktestId || (hasAdvancedGapSource && allowAdvancedStrictRun);

  const minuteGapAuditMutation = useMutation({
    mutationFn: () =>
      auditMinuteGapCsv({
        ...gapSourcePayload(),
        interval: minuteInterval,
        tail_entry_start: tailEntryStart,
        tail_entry_end: tailEntryEnd,
      }),
    onSuccess: (data) => onAuditChange?.(data),
  });

  const minuteGapTemplateMutation = useMutation({
    mutationFn: () => fetchMinuteGapImportTemplate({ ...gapSourcePayload(), sample_limit: 200 }),
    onSuccess: (content) => setMinuteGapTemplate(content),
  });

  const minuteVendorManifestMutation = useMutation({
    mutationFn: () =>
      fetchMinuteGapVendorManifest({
        ...gapSourcePayload(),
        tail_entry_start: tailEntryStart,
        tail_entry_end: tailEntryEnd,
        sample_limit: 20,
      }),
  });

  const minuteVendorManifestCsvMutation = useMutation({
    mutationFn: () =>
      fetchMinuteGapVendorManifestCsv({
        ...gapSourcePayload(),
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
        interval: minuteInterval,
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
        interval: minuteInterval,
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
        ...gapSourcePayload(),
        interval: minuteInterval,
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

  const akshareGapImportMutation = useMutation({
    mutationFn: (dryRun: boolean) =>
      importMinuteGapsFromAkshare({
        ...gapSourcePayload(),
        interval: minuteInterval,
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

  const tushareGapImportMutation = useMutation({
    mutationFn: (dryRun: boolean) =>
      importMinuteGapsFromTushare({
        ...gapSourcePayload(),
        interval: minuteInterval,
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
        ...gapSourcePayload(),
        interval: minuteInterval,
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
        ...(hasSourceBacktestId ? {} : { max_symbols: 1500 }),
        ...gapSourcePayload(),
        minute_interval: minuteInterval,
        min_tail_bars: 1,
        trade_limit: 80,
        tail_entry_start: tailEntryStart,
        tail_entry_end: tailEntryEnd,
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["backtests"] });
      const generatedBacktestId = result.backtest?.backtest_id;
      if (generatedBacktestId) {
        onStrictPipelineComplete(generatedBacktestId);
        queryClient.invalidateQueries({ queryKey: ["backtestReport", generatedBacktestId] });
      }
    },
  });

  const audit = minuteGapAuditMutation.data;
  const canAudit = Boolean(sourceBacktestId.trim() || minuteGapCsv.trim() || minuteGapFilePath.trim());
  const canImport = Boolean(minuteImportCsv.trim() || minuteImportFilePath.trim());
  const selectedImportResult = selectedProviderResult(preferredProvider, {
    akshare: akshareGapImportMutation.data,
    tdx: tdxGapImportMutation.data,
    tushare: tushareGapImportMutation.data,
    vnpy: vnpyGapImportMutation.data,
  });
  const selectedImportPending = selectedProviderPending(preferredProvider, {
    akshare: akshareGapImportMutation.isPending,
    tdx: tdxGapImportMutation.isPending,
    tushare: tushareGapImportMutation.isPending,
    vnpy: vnpyGapImportMutation.isPending,
  });
  const isGeneratingVendorManifest = minuteVendorManifestMutation.isPending || minuteVendorManifestCsvMutation.isPending;
  const error =
    minuteGapAuditMutation.error ??
    minuteGapTemplateMutation.error ??
    minuteVendorManifestMutation.error ??
    minuteVendorManifestCsvMutation.error ??
    minuteImportMutation.error ??
    vnpyMinuteImportMutation.error ??
    vnpyGapImportMutation.error ??
    akshareGapImportMutation.error ??
    tushareGapImportMutation.error ??
    tdxGapImportMutation.error ??
    strictPipelineMutation.error;

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

  const runPreferredGapImport = (dryRun: boolean) => {
    if (preferredProvider === "akshare") {
      akshareGapImportMutation.mutate(dryRun);
    } else if (preferredProvider === "tdx") {
      tdxGapImportMutation.mutate(dryRun);
    } else if (preferredProvider === "tushare") {
      tushareGapImportMutation.mutate(dryRun);
    } else {
      vnpyGapImportMutation.mutate(dryRun);
    }
  };

  return (
    <section className="rounded-lg border p-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ClipboardCheck size={16} />
          <h2 className="text-sm font-semibold">严格14:30补数</h2>
        </div>
        <div className="flex items-center gap-2">
          {audit && (
            <span
              className={cn(
                "rounded-md border px-2 py-1 text-xs",
                audit.status === "ready"
                  ? "border-green-200 bg-green-50 text-rise dark:border-green-500/30 dark:bg-green-500/10"
                  : "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300"
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

      <StrictMinuteSourcePanel
        audit={audit}
        sourceBacktestId={sourceBacktestId}
        setSourceBacktestId={setSourceBacktestId}
        backtestId={backtestId}
        minuteGapFilePath={minuteGapFilePath}
        preferredProvider={preferredProvider}
        setPreferredProvider={setPreferredProvider}
        canAudit={canAudit}
        auditPending={minuteGapAuditMutation.isPending}
        selectedImportPending={selectedImportPending}
        strictPipelinePending={strictPipelineMutation.isPending}
        isRunningBacktest={isRunningBacktest}
        canRunStrictPipeline={canRunStrictPipeline}
        selectedImportResult={selectedImportResult}
        onAudit={() => minuteGapAuditMutation.mutate()}
        onPreferredGapImport={runPreferredGapImport}
        onRunStrictPipeline={() => strictPipelineMutation.mutate()}
      />

      {expanded && (
        <div className="mt-3 space-y-3 border-t pt-3">
          <AdvancedGapSourcePanel
            minuteGapCsv={minuteGapCsv}
            setMinuteGapCsv={setMinuteGapCsv}
            sourceBacktestId={sourceBacktestId}
            minuteGapFilePath={minuteGapFilePath}
            setMinuteGapFilePath={setMinuteGapFilePath}
            loadCsvFile={loadCsvFile}
            canAudit={canAudit}
            auditPending={minuteGapAuditMutation.isPending}
            templatePending={minuteGapTemplateMutation.isPending}
            manifestPending={isGeneratingVendorManifest}
            vendorManifest={minuteVendorManifestMutation.data}
            minuteVendorManifestCsv={minuteVendorManifestCsv}
            audit={audit}
            minuteInterval={minuteInterval}
            onAudit={() => minuteGapAuditMutation.mutate()}
            onGenerateTemplate={() => minuteGapTemplateMutation.mutate()}
            onPreviewManifest={() => minuteVendorManifestMutation.mutate()}
            onExportManifestCsv={() => minuteVendorManifestCsvMutation.mutate()}
          />
          <AdvancedStrictRunConfirmation
            checked={allowAdvancedStrictRun}
            onCheckedChange={setAllowAdvancedStrictRun}
            visible={!hasSourceBacktestId && hasAdvancedGapSource}
          />
          <StrictPipelineResultPanel result={strictPipelineMutation.data} minuteInterval={minuteInterval} />
          <MinuteGapTemplatePanel template={minuteGapTemplate} />
          <ProviderMinuteImportPanel
            minuteInterval={minuteInterval}
            canAudit={canAudit}
            vnpyImportParams={vnpyImportParams}
            setVnpyImportParams={setVnpyImportParams}
            vnpyImportPending={vnpyMinuteImportMutation.isPending}
            vnpyGapImportPending={vnpyGapImportMutation.isPending}
            tdxGapImportPending={tdxGapImportMutation.isPending}
            tushareGapImportPending={tushareGapImportMutation.isPending}
            vnpyImportResult={vnpyMinuteImportMutation.data}
            vnpyGapImportResult={vnpyGapImportMutation.data}
            tdxGapImportResult={tdxGapImportMutation.data}
            tushareGapImportResult={tushareGapImportMutation.data}
            onVnpySingleImport={() => vnpyMinuteImportMutation.mutate()}
            onVnpyGapImport={(dryRun) => vnpyGapImportMutation.mutate(dryRun)}
            onTdxGapImport={(dryRun) => tdxGapImportMutation.mutate(dryRun)}
            onTushareGapImport={(dryRun) => tushareGapImportMutation.mutate(dryRun)}
          />
          <ExternalMinuteCsvFallbackPanel
            minuteImportCsv={minuteImportCsv}
            setMinuteImportCsv={setMinuteImportCsv}
            minuteImportFilePath={minuteImportFilePath}
            setMinuteImportFilePath={setMinuteImportFilePath}
            loadCsvFile={loadCsvFile}
            canImport={canImport}
            importPending={minuteImportMutation.isPending}
            importResult={minuteImportMutation.data}
            minuteInterval={minuteInterval}
            onImport={(dryRun) => minuteImportMutation.mutate(dryRun)}
          />
          <MinuteGapExamplesPanel audit={audit} />
          <MinuteStep
            number="3"
            title="复审后再跑严格回测"
            description="导入后重新审计缺口。只有覆盖率为 100% 时，严格流水线才会生成真实尾盘分钟成交回测。"
          />
          <MinuteWizardMessages fileError={fileError} error={error} />
        </div>
      )}
    </section>
  );
}

function selectedProviderResult<T>(provider: GapProvider, values: Record<GapProvider, T>) {
  return values[provider];
}

function selectedProviderPending(provider: GapProvider, values: Record<GapProvider, boolean>) {
  return values[provider];
}
