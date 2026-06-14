export type GapProvider = "akshare" | "tdx" | "tushare" | "vnpy";

export interface VnpyMinuteImportParams {
  vt_symbol: string;
  start: string;
  end: string;
  dry_run: boolean;
}

export interface StrictPipelineResult {
  status: string;
  message?: string;
  audit?: {
    status: string;
    gap_count?: number;
    covered_count?: number;
    missing_count?: number;
    coverage_pct?: number;
    symbol_count?: number;
    date_count?: number;
    next_action?: string;
  };
  backtest?: {
    backtest_id?: number;
  };
  csv?: {
    filename?: string;
  };
  params?: Record<string, unknown>;
  next_action?: string;
}

export interface VnpySingleMinuteImportResult {
  status: string;
  interval?: string;
  dry_run?: boolean;
  rows_read?: number;
  rows_written?: number;
}

export type LoadCsvFile = (file: File | undefined, onLoad: (value: string) => void) => void;

export function MinuteStep({ number, title, description }: { number: string; title: string; description: string }) {
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

export {
  AdvancedGapSourcePanel,
  AdvancedStrictRunConfirmation,
  MinuteGapTemplatePanel,
  StrictMinuteSourcePanel,
  StrictPipelineResultPanel,
} from "@/features/quant/MinuteGapSourcePanels";
export { ProviderMinuteImportPanel } from "@/features/quant/MinuteProviderImportPanel";
export {
  ExternalMinuteCsvFallbackPanel,
  MinuteGapExamplesPanel,
  MinuteWizardMessages,
} from "@/features/quant/MinuteCsvFallbackPanel";
