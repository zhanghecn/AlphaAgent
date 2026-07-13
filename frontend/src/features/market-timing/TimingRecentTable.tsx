import type { TimingDailyEvent, TimingDailyState, TimingDirection } from "@/api/marketTiming";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { recentTimingRows, timingSetupLabel } from "./timingPresentation";

function directionClass(direction: TimingDirection): string {
  if (direction === "GOLD") return "text-amber-500";
  if (direction === "SILVER") return "text-slate-500 dark:text-slate-300";
  return "text-muted-foreground";
}

function eventText(event: TimingDailyEvent): string {
  if (event.status === "CONFIRMED") {
    return event.confirm_date ? `确 ${event.confirm_date.slice(5)}` : "已确认";
  }
  if (event.status === "INVALIDATED") return "已否决";
  return "待确认";
}

export function TimingRecentTable({
  series,
  loading,
}: {
  series: TimingDailyState[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <Card className="flex h-36 items-center justify-center text-sm text-muted-foreground">
        加载最近交易日…
      </Card>
    );
  }

  const rows = recentTimingRows(series);
  if (rows.length === 0) return null;

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="font-display text-base font-semibold">最近交易日状态</h3>
        <span className="text-xs text-muted-foreground">因子截至 {rows[rows.length - 1]?.date}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-[1180px] table-fixed text-xs">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="w-24 px-2 py-2 text-left font-medium">日期</th>
              {rows.map((row) => (
                <th key={row.date} className="w-14 px-1 py-2 text-center font-medium tabular-nums">
                  {row.date.slice(5)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-border/50">
              <th className="px-2 py-2 text-left font-medium text-muted-foreground">多头合力</th>
              {rows.map((row) => (
                <td key={row.date} className="px-1 py-2 text-center tabular-nums">
                  {row.bull_force.toFixed(1)}
                </td>
              ))}
            </tr>
            <tr className="border-b border-border/50">
              <th className="px-2 py-2 text-left font-medium text-muted-foreground">空头合力</th>
              {rows.map((row) => (
                <td key={row.date} className="px-1 py-2 text-center tabular-nums">
                  {row.bear_force.toFixed(1)}
                </td>
              ))}
            </tr>
            <tr className="border-b border-border/50">
              <th className="px-2 py-2 text-left font-medium text-muted-foreground">当日区域</th>
              {rows.map((row) => (
                <td
                  key={row.date}
                  className={cn("px-1 py-2 text-center font-medium", directionClass(row.zone_direction))}
                >
                  {row.zone_direction === "GOLD" ? "金区" : row.zone_direction === "SILVER" ? "银区" : "中性"}
                </td>
              ))}
            </tr>
            <tr>
              <th className="px-2 py-2 text-left font-medium text-muted-foreground">手指事件</th>
              {rows.map((row) => (
                <td key={row.date} className="px-1 py-2 text-center">
                  {row.event ? (
                    <span
                      className={cn("block font-medium leading-4", directionClass(row.event.direction))}
                      title={`${timingSetupLabel(row.event.setup_type)}，候选 ${row.date}${row.event.confirm_date ? `，确认 ${row.event.confirm_date}` : ""}`}
                    >
                      {row.event.direction === "GOLD" ? "金" : "银"}
                      <span className="block text-[10px] font-normal text-muted-foreground">
                        {eventText(row.event)}
                      </span>
                    </span>
                  ) : (
                    <span className="text-muted-foreground/40">—</span>
                  )}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  );
}
