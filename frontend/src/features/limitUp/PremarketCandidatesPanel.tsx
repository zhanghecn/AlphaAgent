import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, ListChecks } from "lucide-react";

import {
  downloadPremarketPreludeCandidatesTxt,
  fetchPremarketPreludeCandidates,
  type PremarketPreludeCandidate,
} from "@/api/limitUp";
import { cn } from "@/lib/utils";

/** 盘前低位首板候选面板：主人版低位观察池 + 同花顺 txt 导出（人工核对用，非自动信号）。 */
export function PremarketCandidatesPanel() {
  const query = useQuery({
    queryKey: ["limit-up", "premarket-prelude-candidates"],
    queryFn: () => fetchPremarketPreludeCandidates("all", 100),
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
      await downloadPremarketPreludeCandidatesTxt("all", 100);
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
    return null; // 盘前数据未就绪时静默（实时榜单为主视图）
  }

  return (
    <div className="mx-3 mb-3 rounded-lg border bg-card sm:mx-4" aria-label="盘前低位首板候选">
      <div className="flex items-center justify-between gap-3 px-3 py-2.5">
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <ListChecks size={15} className="shrink-0 text-primary" />
          <span className="font-semibold text-foreground">盘前低位首板候选</span>
          <span className="truncate text-muted-foreground">
            D-1={result.trade_date ?? "-"} · 前 {result.count ?? candidates.length} 只
            {result.total != null && result.total > (result.count ?? 0)
              ? ` / 低位池共 ${result.total} 只`
              : ""}
          </span>
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
      {downloadError && (
        <div className="px-3 pb-2 text-xs text-red-500">{downloadError}</div>
      )}
      {candidates.length ? (
        <div className="max-h-64 overflow-y-auto px-3 pb-3">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr className="border-b text-left">
                <th className="py-1.5 pr-2 font-medium">代码</th>
                <th className="py-1.5 pr-2 font-medium">名称</th>
                <th className="py-1.5 pr-2 text-right font-medium" title="所属概念板块 20 日最大涨幅（低位+题材核心路径）">板块20日</th>
                <th className="py-1.5 pr-2 font-medium">形态</th>
                <th className="py-1.5 pr-2 text-right font-medium">量比</th>
                <th className="py-1.5 pr-2 text-right font-medium">量稳度</th>
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
          今日盘前无符合条件的低位首板候选
        </div>
      )}
      <div className="border-t px-3 py-2 text-[10px] leading-4 text-muted-foreground">
        主人版低位：半年位置≤25% 且距高点回撤≥25%，或距低点反弹≤12%。
        低位首板自动策略为负期望（安全垫厚但弹性小）——本清单为人工核对观察池，
        早盘需人工结合题材与涨幅核对后再打板，非自动信号。
      </div>
    </div>
  );
}

function CandidateRow({ item }: { item: PremarketPreludeCandidate }) {
  const isYang = item.prelude_pattern === "small_yang";
  const isYin = item.prelude_pattern === "small_yin";
  return (
    <tr className="border-b border-border/50 last:border-0">
      <td className="py-1.5 pr-2 font-mono text-foreground">{item.code}</td>
      <td className="max-w-20 truncate py-1.5 pr-2 text-foreground">{item.name}</td>
      <td className={cn(
        "py-1.5 pr-2 text-right font-mono",
        (item.concept_r20 ?? 0) >= 5 ? "font-semibold text-rise" : "text-foreground",
      )}>
        {item.concept_r20 != null ? `${item.concept_r20.toFixed(1)}%` : "-"}
      </td>
      <td className="py-1.5 pr-2">
        {isYang || isYin ? (
          <span
            className={cn(
              "rounded-full px-1.5 py-px text-[10px] font-medium",
              isYang ? "bg-rise/10 text-rise" : "bg-fall/10 text-fall",
            )}
          >
            {isYang ? "小阳" : "小阴"}×{item.streak ?? "-"}
          </span>
        ) : (
          <span className="text-muted-foreground">-</span>
        )}
      </td>
      <td className="py-1.5 pr-2 text-right font-mono text-foreground">
        {item.vol_shift_ratio != null ? item.vol_shift_ratio.toFixed(2) : "-"}
      </td>
      <td className="py-1.5 pr-2 text-right font-mono text-foreground">
        {item.vol_cv_7d != null ? item.vol_cv_7d.toFixed(2) : "-"}
      </td>
      <td className="max-w-32 truncate py-1.5 text-muted-foreground">
        {item.concepts.join(" / ") || "-"}
      </td>
    </tr>
  );
}
