import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { fetchFirstBoardLive, type FirstBoardLeader } from "@/api/firstBoard";
import { EmptyState } from "@/components/EmptyState";
import { LoadingState } from "@/components/LoadingState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn, formatAmount, formatPct, formatPrice } from "@/lib/utils";

const FIRST_BOARD_REFRESH_INTERVAL_MS = 30_000;

export function FirstBoardLeaderPage() {
  const query = useQuery({
    queryKey: ["firstBoardLive"],
    queryFn: fetchFirstBoardLive,
    staleTime: 10_000,
    refetchInterval: FIRST_BOARD_REFRESH_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });
  const payload = query.data;

  if (query.isLoading && !payload) return <LoadingState rows={6} />;
  if (query.isError || !payload) {
    return <EmptyState message="潜龙首板实时榜暂时不可用" />;
  }

  const unavailable = payload.status !== "ok";
  const leaders = payload.leaders ?? [];
  return (
    <section aria-label="潜龙首板实时榜" className="rounded-lg border">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-4 py-3 text-xs text-muted-foreground">
        <span className="text-sm font-semibold text-foreground">潜龙首板</span>
        <span>{payload.trade_date}</span>
        <span>{sessionLabel(payload.session_stage)}</span>
        <span>涨停池 {payload.data_quality.pool_total} 只</span>
        <span>主板非 ST 首板 {payload.data_quality.first_board_total} 只</span>
        <span className="ml-auto flex items-center gap-1 tabular-nums">
          <RefreshCw size={13} />
          {formatCapturedAt(payload.captured_at)}
        </span>
      </div>
      {unavailable ? (
        <div className="p-4">
          <EmptyState message={payload.data_quality.message ?? "涨停池暂时不可用"} />
        </div>
      ) : leaders.length === 0 ? (
        <div className="px-4 py-10 text-center text-sm text-muted-foreground">
          当前没有符合条件的主板非 ST 首板
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-medium">排名</th>
                <th className="px-4 py-2 text-left font-medium">股票</th>
                <th className="px-4 py-2 text-right font-medium">现价</th>
                <th className="px-4 py-2 text-right font-medium">涨幅</th>
                <th className="px-4 py-2 text-right font-medium">封单额</th>
                <th className="px-4 py-2 text-right font-medium">封单比</th>
                <th className="px-4 py-2 text-right font-medium">换手</th>
                <th className="px-4 py-2 text-right font-medium">量比</th>
                <th className="px-4 py-2 text-right font-medium">首次封板</th>
                <th className="px-4 py-2 text-right font-medium">开板</th>
              </tr>
            </thead>
            <tbody>
              {leaders.map((leader) => <LeaderRow key={leader.vt_symbol} leader={leader} />)}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function LeaderRow({ leader }: { leader: FirstBoardLeader }) {
  return (
    <tr className="border-b last:border-b-0 hover:bg-muted/30">
      <td className="px-4 py-2.5 font-mono tabular-nums text-muted-foreground">{leader.rank}</td>
      <td className="px-4 py-2.5"><StockIdentityLink name={leader.name} vtSymbol={leader.vt_symbol} /></td>
      <td className="px-4 py-2.5 text-right font-mono tabular-nums">{formatPrice(leader.last_price)}</td>
      <td className={cn("px-4 py-2.5 text-right font-mono tabular-nums", leader.change_pct != null && leader.change_pct >= 0 ? "text-rise" : "text-fall")}>
        {formatPct(leader.change_pct)}
      </td>
      <td className="px-4 py-2.5 text-right font-mono tabular-nums">{formatAmount(leader.seal_amount)}</td>
      <td className="px-4 py-2.5 text-right font-mono tabular-nums">{ratio(leader.seal_to_turnover_ratio)}</td>
      <td className="px-4 py-2.5 text-right font-mono tabular-nums">{percent(leader.turnover_rate)}</td>
      <td className="px-4 py-2.5 text-right font-mono tabular-nums">{number(leader.volume_ratio)}</td>
      <td className="px-4 py-2.5 text-right font-mono tabular-nums">{leader.first_limit_time ?? "--"}</td>
      <td className="px-4 py-2.5 text-right font-mono tabular-nums">{leader.open_times ?? "--"}</td>
    </tr>
  );
}

function sessionLabel(stage: string) {
  return ({ preopen: "盘前", morning: "上午盘", lunch: "午间休市", afternoon: "下午盘", closed: "已收盘" } as Record<string, string>)[stage] ?? stage;
}

export function formatCapturedAt(value: string) {
  const capturedAt = new Date(value);
  if (Number.isNaN(capturedAt.getTime())) return "刚刚更新";
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(capturedAt);
  return `${time} 更新`;
}

function ratio(value: number | null) {
  return value == null ? "--" : `${(value * 100).toFixed(2)}%`;
}

function percent(value: number | null) {
  return value == null ? "--" : `${value.toFixed(2)}%`;
}

function number(value: number | null) {
  return value == null ? "--" : value.toFixed(2);
}
