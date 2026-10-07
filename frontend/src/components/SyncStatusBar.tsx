import { useQuery } from "@tanstack/react-query";
import { Activity, RefreshCw } from "lucide-react";

import { fetchLatestSyncBatch } from "@/api/dataSync";
import { cn } from "@/lib/utils";

/**
 * 实时页数据状态条:回答「我现在看的是什么时候的数据、什么时候会更新、更新到哪了」。
 *
 * 三段信息(全部前端组合现成数据,无新后端):
 * 1. 池语义——tradeDate×stale×时段 推出「今日池盘中/今日终态/明日池就绪/回退旧池」;
 * 2. 盘中扫描——last_scan 的相对时间与失败信息(产品各自传入);
 * 3. 盘后主链进度——/data-sync/batches/latest 的 job 级进度(60s 轮询),
 *    找到本产品的 EOD 池计算 job(如 hpr_eod_finalize)给出「算好前/进行中/已就绪」。
 * 盘后主链 19:00 起跑约 2 小时+,EOD 池计算在链尾——凌晨起看到的就是次日池。
 */

export interface ScanStatus {
  finished_at: string | null;
  status: string | null;
  message: string | null;
}

interface SyncStatusBarProps {
  /** 产品自己的盘中扫描状态(live payload 的 last_scan) */
  scan: ScanStatus | null;
  /** 当前池交易日(YYYY-MM-DD) */
  tradeDate: string;
  /** 池非当日(回退最近可用) */
  stale: boolean;
  /** 该产品的 EOD 池计算 job id(如 "hpr_eod_finalize") */
  eodJobId: string;
  /** 盘后回测/题库重算时刻(调度说明用) */
  rebuildAt?: string;
}

// job id → 人话(仅展示;未列出的原样显示)
const JOB_LABELS: Record<string, string> = {
  sync_stock_list: "股票列表",
  sync_sector_list: "板块列表",
  sync_sector_members: "板块成员",
  sync_stock_daily_bars: "全市场日线",
  sync_index_daily_bars: "指数日线",
  sync_stock_minute_bars: "分钟K线",
  sync_stock_auction_snapshots: "竞价快照",
  sync_stock_fund_flows: "个股资金流",
  sync_sector_fund_flows: "板块资金流",
  sync_stock_hot_ranks: "人气榜",
  sync_sector_period_scores: "板块评分",
  refresh_market_timing_panel: "大盘择时面板",
  sync_stock_financial_quarterly: "季报",
  sync_stock_financial_indicators: "财务指标",
  sync_stock_lhb_records: "龙虎榜",
  sync_margin_balance: "两融余额",
  sync_stock_notices: "公告",
  low_suction_eod_finalize: "低吸池定版",
  qianlong_eod_finalize: "潜龙池定版",
  w2s_eod_finalize: "N型池定版",
  fbb_eod_finalize: "反包池定版",
  j12_eod_finalize: "一接二盘后池",
  hpr_eod_finalize: "高位接力池定版",
};

function jobLabel(id: string | null | undefined): string {
  if (!id) return "—";
  return JOB_LABELS[id] ?? id;
}

/** 相对时间:刚刚 / N分钟前 / HH:MM / 昨天 HH:MM */
function relTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diffMin = Math.floor((Date.now() - t) / 60_000);
  if (diffMin < 1) return "刚刚";
  if (diffMin < 60) return `${diffMin}分钟前`;
  const d = new Date(t);
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  if (sameDay) return hm;
  return `昨天 ${hm}`;
}

function isIntraday(): boolean {
  const d = new Date();
  const day = d.getDay();
  if (day === 0 || day === 6) return false;
  const hm = d.getHours() * 100 + d.getMinutes();
  return hm >= 930 && hm <= 1500;
}

/** 池语义:stale/明日池/今日盘中/今日终态 四态(导出供 spec 直测) */
export function poolPhase(tradeDate: string, stale: boolean): { label: string; tone: string } {
  if (stale) {
    return {
      label: `${tradeDate} 池（最近可用）· 明日池未算好`,
      tone: "border-amber-500/40 text-amber-500",
    };
  }
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  if (tradeDate > todayStr) {
    return {
      label: `${tradeDate} 明日池 · 已就绪`,
      tone: "border-emerald-500/40 text-emerald-500",
    };
  }
  if (isIntraday()) {
    return { label: "今日池 · 盘中每分钟刷新", tone: "border-primary/40 text-primary" };
  }
  return {
    label: "今日终态 · 明日池今晚盘后主链算好后切换",
    tone: "border-sky-500/40 text-sky-500",
  };
}

export function SyncStatusBar({ scan, tradeDate, stale, eodJobId, rebuildAt }: SyncStatusBarProps) {
  const batchQuery = useQuery({
    queryKey: ["latestSyncBatch"],
    queryFn: fetchLatestSyncBatch,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
  const batch = batchQuery.data ?? null;

  // 本产品 EOD job 在主链里的状态
  const jobs = batch?.jobs ?? [];
  const eodJob = jobs.find((j) => j.job_id === eodJobId);
  const running = batch?.status === "running";

  let eodLine: { text: string; tone: string } | null = null;
  if (running && jobs.length) {
    if (eodJob?.status === "succeeded") {
      eodLine = { text: `盘后主链 ${batch!.completed_jobs}/${batch!.total_jobs} · 明日池已算好 ✓`, tone: "text-emerald-500" };
    } else if (eodJob?.status === "running") {
      eodLine = { text: `明日池计算中（主链 ${batch!.completed_jobs}/${batch!.total_jobs}）`, tone: "text-primary" };
    } else {
      const pos = eodJob ? jobs.findIndex((j) => j.job_id === eodJobId) + 1 : null;
      const suffix = pos ? `，池定版排在第 ${pos} 位` : "";
      eodLine = {
        text: `盘后主链 ${batch!.completed_jobs}/${batch!.total_jobs}（${batch!.progress_pct ?? 0}%）· 当前「${jobLabel(batch?.current_job_id)}」${suffix}`,
        tone: "text-sky-500",
      };
    }
  } else if (eodJob?.status === "failed") {
    eodLine = { text: `盘后主链里池定版失败:${eodJob.message ?? "见数据同步页"}`, tone: "text-fall" };
  }

  const phase = poolPhase(tradeDate, stale);
  const scanTone =
    scan?.status && scan.status !== "ok" && scan.status !== "succeeded"
      ? "text-fall"
      : "text-muted-foreground";

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b bg-muted/30 px-4 py-1.5 text-[11px] text-muted-foreground">
      <span className="flex items-center gap-1 font-medium">
        <Activity size={12} />
        数据状态
      </span>
      <span className={cn("rounded border px-1.5 py-0.5", phase.tone)}>{phase.label}</span>
      {scan ? (
        <span className={cn("flex items-center gap-1 tabular-nums", scanTone)}>
          <RefreshCw size={11} />
          扫描 {relTime(scan.finished_at)}
          {scan.message && scan.status !== "ok" ? ` · ${scan.message}` : ""}
        </span>
      ) : (
        <span>等待今日首次扫描（工作日 09:30 起）</span>
      )}
      {eodLine ? <span className={cn("tabular-nums", eodLine.tone)}>{eodLine.text}</span> : null}
      <span className="ml-auto hidden sm:inline">
        调度：盘中 09:30~15:00 每分钟 · 盘后主链 19:00 起（约 2 小时+,池定版在链尾）
        {rebuildAt ? ` · 回测/题库重算 ${rebuildAt}` : ""}
      </span>
    </div>
  );
}
