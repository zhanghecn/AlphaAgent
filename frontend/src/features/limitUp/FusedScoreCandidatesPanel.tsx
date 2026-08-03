import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Download, ListChecks } from "lucide-react";

import {
  downloadPremarketFusedCandidatesTxt,
  fetchPremarketFusedCandidates,
  type FusedScoreTypeFilter,
  type PremarketFusedCandidate,
} from "@/api/limitUp";
import { cn } from "@/lib/utils";

const TYPE_LABELS: Record<string, string> = {
  lowpos: "低位",
  wave: "波浪",
  both: "双型",
};

const TYPE_FILTERS: Array<{ key: FusedScoreTypeFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "lowpos", label: "低位" },
  { key: "wave", label: "波浪" },
  { key: "both", label: "双型" },
];

const LOWPOS_SUB_LABELS: Record<string, string> = {
  L1_depth: "基底深度",
  L2_duration: "基底时长",
  L3_converge: "收敛时长",
  L4_stage: "穿越阶段",
  L5_stabilize: "企稳",
  L6_volume: "量能梯形",
  L7_recent_touch: "近期触碰",
};

const WAVE_SUB_LABELS: Record<string, string> = {
  W1_bull_duration: "多头时长",
  W2_pullback: "回调深度",
  W3_stabilize: "企稳",
  W4_volume: "量能梯形",
};

/** 融合计分观察池：盘前低位分/波浪分 Top-N（子分全透明，人工复核用，非自动信号）。 */
export function FusedScoreCandidatesPanel() {
  const [scoreType, setScoreType] = useState<FusedScoreTypeFilter>("all");
  const query = useQuery({
    queryKey: ["limit-up", "premarket-fused-candidates", scoreType],
    queryFn: () => fetchPremarketFusedCandidates(scoreType, 100),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const result = query.data;
  const candidates = result?.candidates ?? [];

  const handleDownload = async () => {
    setDownloading(true);
    setDownloadError(null);
    try {
      await downloadPremarketFusedCandidatesTxt(scoreType, 100);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "下载失败");
    } finally {
      setDownloading(false);
    }
  };

  if (query.isLoading && !result) {
    return null; // 首屏不占位，避免盘中榜单跳动
  }
  if (query.isError || !result || result.status !== "ok") {
    return null; // 盘前数据未就绪时静默
  }

  return (
    <div className="mx-3 mb-3 rounded-lg border bg-card sm:mx-4" aria-label="融合计分观察池">
      <div className="flex items-center justify-between gap-3 px-3 py-2.5">
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <ListChecks size={15} className="shrink-0 text-primary" />
          <span className="font-semibold text-foreground">融合计分观察池</span>
          <span className="truncate text-muted-foreground">
            D-1={result.trade_date ?? "-"} · 前 {result.count ?? candidates.length} 只
            {result.qualified_total != null ? ` / 入榜共 ${result.qualified_total} 只` : ""}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div className="flex items-center rounded-md border text-xs">
            {TYPE_FILTERS.map((filter) => (
              <button
                key={filter.key}
                type="button"
                onClick={() => setScoreType(filter.key)}
                className={cn(
                  "px-2 py-1",
                  scoreType === filter.key
                    ? "bg-primary/10 font-medium text-primary"
                    : "text-muted-foreground hover:bg-muted",
                )}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={handleDownload}
            disabled={downloading || candidates.length === 0}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium",
              "text-foreground transition-colors hover:bg-muted",
              (downloading || candidates.length === 0) && "cursor-not-allowed opacity-50",
            )}
            title="下载 txt（每行一个 6 位代码），导入同花顺自定义板块"
          >
            <Download size={13} />
            {downloading ? "下载中…" : "同花顺 txt"}
          </button>
        </div>
      </div>
      {downloadError && (
        <div className="px-3 pb-2 text-xs text-red-500">{downloadError}</div>
      )}
      {candidates.length ? (
        <div className="max-h-72 overflow-y-auto px-3 pb-3">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr className="border-b text-left">
                <th className="py-1.5 pr-1 font-medium" />
                <th className="py-1.5 pr-2 font-medium">代码</th>
                <th className="py-1.5 pr-2 font-medium">名称</th>
                <th className="py-1.5 pr-2 font-medium">类型</th>
                <th className="py-1.5 pr-2 text-right font-medium" title="max(低位分/7, 波浪分/4)">融合分</th>
                <th className="py-1.5 pr-2 text-right font-medium" title="低位分（0-7）">低位</th>
                <th className="py-1.5 pr-2 text-right font-medium" title="波浪分（0-4）">波浪</th>
                <th className="py-1.5 pr-2 text-right font-medium" title="40日内最长空头排列天数">空头</th>
                <th className="py-1.5 pr-2 text-right font-medium" title="穿越阶段：0=未穿/1=MA10上穿MA20/2=MA20也上穿MA30">阶段</th>
                <th className="py-1.5 pr-2 text-center font-medium" title="近20日有过涨停/触碰（三轮研究最强单条件）">触</th>
                <th className="py-1.5 pr-2 text-right font-medium" title="20日乖离率%">乖离</th>
                <th className="py-1.5 font-medium">概念</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((item) => (
                <CandidateRow key={item.vt_symbol} item={item} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="px-3 pb-3 text-xs text-muted-foreground">
          今日入榜为空（无通过低位/波浪资格门的候选）
        </div>
      )}
      <div className="border-t px-3 py-2 text-[10px] leading-4 text-muted-foreground">
        融合分=低位分(0-7)与波浪分(0-4)等权归一取高；点击行展开全部子分。
        研究裁决：计分卡整体未达过滤级（顶桶 lift 1.65），「近20日有触碰」才是三轮最强单条件（lift 2.51）——
        本清单为人工复核观察池，早盘结合题材与竞价人工判断，非自动信号。
      </div>
    </div>
  );
}

function CandidateRow({ item }: { item: PremarketFusedCandidate }) {
  const [expanded, setExpanded] = useState(false);
  const typeLabel = TYPE_LABELS[item.fused_type] ?? item.fused_type;
  return (
    <>
      <tr
        className="cursor-pointer border-b border-border/50 last:border-0 hover:bg-muted/40"
        onClick={() => setExpanded((value) => !value)}
      >
        <td className="py-1.5 pr-1 text-muted-foreground">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </td>
        <td className="py-1.5 pr-2 font-mono text-foreground">{item.code}</td>
        <td className="max-w-20 truncate py-1.5 pr-2 text-foreground">{item.name}</td>
        <td className="py-1.5 pr-2">
          <span
            className={cn(
              "rounded-full px-1.5 py-px text-[10px] font-medium",
              item.fused_type === "lowpos" && "bg-primary/10 text-primary",
              item.fused_type === "wave" && "bg-amber-500/10 text-amber-500",
              item.fused_type === "both" && "bg-violet-500/10 text-violet-500",
            )}
          >
            {typeLabel}
          </span>
        </td>
        <td
          className={cn(
            "py-1.5 pr-2 text-right font-mono",
            item.fused_score >= 0.6 ? "font-semibold text-rise" : "text-foreground",
          )}
        >
          {item.fused_score.toFixed(2)}
        </td>
        <td className="py-1.5 pr-2 text-right font-mono text-foreground">
          {item.lowpos_score.toFixed(1)}
        </td>
        <td className="py-1.5 pr-2 text-right font-mono text-foreground">
          {item.wave_score.toFixed(1)}
        </td>
        <td className="py-1.5 pr-2 text-right font-mono text-foreground">
          {item.bear_run_max_40d ?? "-"}
        </td>
        <td className="py-1.5 pr-2 text-right font-mono text-foreground">
          {item.cross_stage ?? "-"}
        </td>
        <td className="py-1.5 pr-2 text-center">
          {item.pure_20d === false ? (
            <span className="rounded-full bg-rise/10 px-1.5 py-px text-[10px] font-medium text-rise" title="近20日有过涨停/触碰">
              触
            </span>
          ) : (
            <span className="text-muted-foreground">-</span>
          )}
        </td>
        <td className="py-1.5 pr-2 text-right font-mono text-foreground">
          {item.bias_ma20_pct != null ? `${item.bias_ma20_pct.toFixed(1)}%` : "-"}
        </td>
        <td className="max-w-32 truncate py-1.5 text-muted-foreground">
          {item.concepts.join(" / ") || "-"}
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-border/50 bg-muted/20 last:border-0">
          <td colSpan={12} className="px-3 py-2">
            <SubScoreGrid title="低位子分（0-7）" subs={item.lowpos_subs} labels={LOWPOS_SUB_LABELS} max={1} />
            <SubScoreGrid title="波浪子分（0-4）" subs={item.wave_subs} labels={WAVE_SUB_LABELS} max={1} />
            <div className="mt-1 text-[10px] text-muted-foreground">
              收敛天数={item.conv_days ?? "-"} · 均线状态={item.ma_state ?? "-"} ·
              20日纯度={item.pure_20d == null ? "-" : item.pure_20d ? "纯" : "有触碰"}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function SubScoreGrid({
  title,
  subs,
  labels,
  max,
}: {
  title: string;
  subs: Record<string, number>;
  labels: Record<string, string>;
  max: number;
}) {
  const entries = Object.entries(subs ?? {});
  if (!entries.length) {
    return null;
  }
  return (
    <div className="mb-1.5">
      <div className="mb-1 text-[10px] font-medium text-muted-foreground">{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {entries.map(([key, value]) => (
          <span
            key={key}
            className={cn(
              "rounded border px-1.5 py-0.5 font-mono text-[10px]",
              value >= max * 0.99
                ? "border-rise/40 bg-rise/10 text-rise"
                : value > 0
                  ? "border-border text-foreground"
                  : "border-border/50 text-muted-foreground",
            )}
            title={key}
          >
            {labels[key] ?? key} {value.toFixed(2)}
          </span>
        ))}
      </div>
    </div>
  );
}
