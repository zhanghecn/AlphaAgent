import { Link } from "react-router-dom";

import type { LianbanReview } from "@/api/lianban";
import { shortSealTime } from "./LadderSection";

type BrokenItem = LianbanReview["broken_list"][number];

// ===== 派生纯函数 =====

/**
 * 炸板行后缀：「09:25封·炸2次」。首封时间 HH:MM:SS → HH:MM；
 * break_count 为 null/0 → 只显时间；时间为 null（rebuild 口径）→ 只显炸板次数；都缺 → null。
 */
export function brokenItemSuffix(item: BrokenItem): string | null {
  const parts: string[] = [];
  const time = shortSealTime(item.first_limit_time);
  if (time) parts.push(`${time}封`);
  if (item.break_count != null && item.break_count > 0) parts.push(`炸${item.break_count}次`);
  return parts.length > 0 ? parts.join("·") : null;
}

// ===== 组件 =====

interface BrokenBoardsSectionProps {
  items: BrokenItem[];
}

/**
 * 炸板列表：封板后掉队个股的紧凑流式排列（对齐 lianban 一整段流式文本的密度）。
 * 名称用简洁链接（比天梯 StockIdentityLink 密度更高），后缀时间走 mono。
 */
export function BrokenBoardsSection({ items }: BrokenBoardsSectionProps) {
  return (
    <section aria-label="炸板列表" className="rounded-lg border">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-2.5 sm:px-4">
        <h2 className="text-sm font-semibold text-foreground">炸板</h2>
        {items.length > 0 && (
          <span className="text-[11px] tabular-nums text-muted-foreground">
            {items.length} 只 · 封板后掉队
          </span>
        )}
      </header>
      {items.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground sm:px-4">
          今日无炸板
        </div>
      ) : (
        <div className="flex flex-wrap gap-x-3 gap-y-1 px-3 py-2.5 sm:px-4">
          {items.map((item) => (
            <BrokenBoardItem key={item.vt_symbol} item={item} />
          ))}
        </div>
      )}
    </section>
  );
}

/** 单只炸板股：名称（简洁链接）+ 首封/炸板次 mono 后缀。 */
function BrokenBoardItem({ item }: { item: BrokenItem }) {
  const suffix = brokenItemSuffix(item);
  return (
    <span className="inline-flex items-baseline gap-1 text-xs">
      <Link
        to={`/stocks/${encodeURIComponent(item.vt_symbol)}`}
        title={`打开 ${item.name}`}
        className="font-medium text-foreground hover:text-primary hover:underline"
      >
        {item.name}
      </Link>
      {suffix && (
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{suffix}</span>
      )}
    </span>
  );
}
