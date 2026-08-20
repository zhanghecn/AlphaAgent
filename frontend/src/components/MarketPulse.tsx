import { useQuery } from "@tanstack/react-query";
import { fetchMarketOverview, marketQueryKeys } from "@/api/market";
import type { IndexQuote } from "@/api/types";
import { cn } from "@/lib/utils";

/** 脉搏条展示的指数（按名称优先级挑选，找不到则按列表顺序兜底） */
const PULSE_INDEX_NAMES = ["上证指数", "深证成指", "创业板指", "科创50"];

function pickPulseIndices(indices: IndexQuote[]): IndexQuote[] {
  const picked: IndexQuote[] = [];
  for (const name of PULSE_INDEX_NAMES) {
    const hit = indices.find((q) => q.name.includes(name));
    if (hit && !picked.includes(hit)) picked.push(hit);
  }
  for (const q of indices) {
    if (picked.length >= 4) break;
    if (!picked.includes(q)) picked.push(q);
  }
  return picked.slice(0, 4);
}

/** 当前是否处于 A 股连续竞价时段（本地时区判断，仅驱动状态灯） */
function isMarketOpen(now: Date = new Date()): boolean {
  const day = now.getDay();
  if (day === 0 || day === 6) return false;
  const minutes = now.getHours() * 60 + now.getMinutes();
  return (minutes >= 570 && minutes <= 690) || (minutes >= 780 && minutes <= 900);
}

function formatPct(pct: number | null): string {
  if (pct == null) return "--";
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

function formatPrice(price: number | null): string {
  if (price == null) return "--";
  return price.toFixed(2);
}

/**
 * 行情脉搏条：金色终端的全局签名元素。
 * 主内容区顶部常驻的指数 ticker——一眼确认「这是一台交易终端」。
 * 复用 /market/overview（react-query 缓存，与首页同源），60s 轮询。
 */
export function MarketPulse() {
  const { data } = useQuery({
    queryKey: marketQueryKeys.overview,
    queryFn: fetchMarketOverview,
    refetchInterval: 60_000,
  });

  const open = isMarketOpen();
  const indices = data ? pickPulseIndices(data.indices) : [];

  return (
    <div className="glass flex h-9 items-center gap-0 overflow-hidden border-b text-xs">
      {/* 状态灯：盘中金色呼吸，收盘静默 */}
      <div className="flex h-full shrink-0 items-center gap-1.5 border-r border-border/60 px-3">
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            open ? "bg-primary gate-breathe" : "bg-muted-foreground/40",
          )}
        />
        <span className="font-medium text-muted-foreground">
          {open ? "盘中" : "收盘"}
        </span>
      </div>
      {indices.length === 0 ? (
        <span className="px-3 text-muted-foreground">行情加载中…</span>
      ) : (
        indices.map((q) => {
          const pct = q.change_pct;
          const colorClass =
            pct == null
              ? "text-muted-foreground"
              : pct > 0
                ? "text-rise"
                : pct < 0
                  ? "text-fall"
                  : "text-muted-foreground";
          return (
            <div
              key={q.vt_symbol}
              className="flex h-full min-w-0 items-baseline gap-1.5 border-r border-border/60 px-3 last:border-r-0"
            >
              <span className="shrink-0 text-muted-foreground">{q.name}</span>
              <span className="font-num shrink-0 font-medium text-foreground">
                {formatPrice(q.last_price)}
              </span>
              <span className={cn("font-num shrink-0 font-medium", colorClass)}>
                {formatPct(pct)}
              </span>
            </div>
          );
        })
      )}
    </div>
  );
}
