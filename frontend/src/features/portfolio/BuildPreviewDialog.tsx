import { useEffect, useState } from "react";
import { CheckCircle2, RefreshCw, XCircle } from "lucide-react";
import { Modal, ModalBody, ModalFooter, ModalHeader } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AutoBuyResult } from "@/api/quant";

interface BuildPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onBuild: (params: { limit: number }) => void;
  isBuilding: boolean;
  result?: AutoBuyResult;
  error?: Error | null;
}

interface FillItem {
  status: string;
  vt_symbol?: string;
  reason?: string;
}

/**
 * BuildPreviewDialog — quant-candidate build with result feedback.
 */
export function BuildPreviewDialog({
  open,
  onOpenChange,
  onBuild,
  isBuilding,
  result,
  error,
}: BuildPreviewDialogProps) {
  const [limit, setLimit] = useState(5);

  useEffect(() => {
    if (open && !result) {
      setLimit(5);
    }
  }, [open, result]);

  const items = (result?.items ?? []) as unknown as FillItem[];
  const filled = items.filter((item) => item.status === "filled");
  const skipped = items.filter((item) => item.status === "skipped");
  const rejected = items.filter((item) => item.status === "rejected");
  const hasResult = Boolean(result && items.length > 0);

  const handleConfirm = () => {
    onBuild({ limit });
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} className="max-w-lg">
      <ModalHeader title="量化候选模拟建仓" onClose={() => onOpenChange(false)} />
      <ModalBody className="space-y-4">
        {!hasResult ? (
          <>
            <p className="text-sm text-muted-foreground">
              从最新量化候选中按排名取前 N 只，每只按最小整手记录为模拟持仓。已持仓的候选会自动跳过。
            </p>
            <div className="max-w-40">
              <NumberField label="候选数量" value={limit} onChange={setLimit} min={1} max={20} step={1} />
            </div>
            <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              预计最多建仓 <span className="text-foreground tabular-nums">{limit}</span> 只 ·
              每只按 <span className="text-foreground tabular-nums">100</span> 股最小整手记录
            </div>
            {error && <p className="text-xs text-destructive">{error.message}</p>}
          </>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-3 text-center">
              <ResultStat label="成功建仓" value={filled.length} tone="rise" />
              <ResultStat label="跳过(已持仓)" value={skipped.length} tone="muted" />
              <ResultStat label="拒绝" value={rejected.length} tone="fall" />
            </div>
            <div className="max-h-64 space-y-1 overflow-y-auto">
              {items.map((item, index) => (
                <div
                  key={`${item.vt_symbol ?? index}`}
                  className="flex items-center justify-between rounded-md border px-3 py-1.5 text-xs"
                >
                  <span className="font-mono">{item.vt_symbol ?? "--"}</span>
                  <span
                    className={cn(
                      "flex items-center gap-1 font-medium",
                      item.status === "filled" && "text-rise",
                      item.status === "skipped" && "text-muted-foreground",
                      item.status === "rejected" && "text-fall",
                    )}
                  >
                    {item.status === "filled" && <CheckCircle2 size={12} />}
                    {item.status === "rejected" && <XCircle size={12} />}
                    {statusLabel(item.status)}
                    {item.reason && <span className="text-muted-foreground">· {item.reason}</span>}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </ModalBody>
      <ModalFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          {hasResult ? "关闭" : "取消"}
        </Button>
        {!hasResult && (
          <Button variant="brand" onClick={handleConfirm} disabled={isBuilding}>
            {isBuilding ? (
              <>
                <RefreshCw className="mr-1 h-4 w-4 animate-spin" />
                建仓中
              </>
            ) : (
              "确认建仓"
            )}
          </Button>
        )}
      </ModalFooter>
    </Modal>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <div className="space-y-1">
      <label className="block text-xs font-medium text-muted-foreground">{label}</label>
      <input
        type="number"
        className="w-full rounded-md border bg-transparent px-2 py-1.5 text-sm tabular-nums outline-none focus:ring-2 focus:ring-primary/50"
        value={value}
        onChange={(event) => onChange(Number(event.target.value) || 0)}
        min={min}
        max={max}
        step={step}
      />
    </div>
  );
}

function ResultStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "rise" | "fall" | "muted";
}) {
  return (
    <div className="rounded-lg border p-2">
      <div
        className={cn(
          "text-xl font-bold tabular-nums",
          tone === "rise" && "text-rise",
          tone === "fall" && "text-fall",
          tone === "muted" && "text-muted-foreground",
        )}
      >
        {value}
      </div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

function statusLabel(status: string): string {
  if (status === "filled") return "已成交";
  if (status === "skipped") return "跳过";
  if (status === "rejected") return "拒绝";
  return status;
}
