import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export function TradingDateSelector({
  label,
  value,
  dates,
  onChange,
  getOptionLabel,
  disabled = false,
  className,
  selectClassName,
}: {
  label: string;
  value: string;
  dates: string[];
  onChange: (tradeDate: string) => void;
  getOptionLabel?: (tradeDate: string) => string;
  disabled?: boolean;
  className?: string;
  selectClassName?: string;
}) {
  const sortedDates = uniqueSortedDates(dates);
  const validDates = new Set(sortedDates);
  const currentIndex = sortedDates.indexOf(value);
  const firstDate = sortedDates[0] ?? "";
  const previousDate = currentIndex > 0 ? sortedDates[currentIndex - 1] : "";
  const nextDate = currentIndex >= 0 && currentIndex < sortedDates.length - 1 ? sortedDates[currentIndex + 1] : "";
  const latestDate = sortedDates[sortedDates.length - 1] ?? "";
  const selectDates = [...sortedDates].reverse();
  const showCurrentFallback = value && currentIndex < 0;
  const isDisabled = disabled || sortedDates.length === 0;
  const adjustedDate = value && currentIndex < 0 ? nearestTradingDate(value, sortedDates) : "";

  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      <span className="text-sm text-muted-foreground">{label}</span>
      <input
        className="h-8 w-36 rounded-md border bg-background px-2 text-sm"
        type="date"
        value={value}
        min={firstDate}
        max={latestDate}
        disabled={isDisabled}
        onChange={(event) => {
          const next = event.target.value;
          if (validDates.has(next)) {
            onChange(next);
            return;
          }
          const adjusted = nearestTradingDate(next, sortedDates);
          if (adjusted) onChange(adjusted);
        }}
      />
      <select
        className={cn("h-8 min-w-44 rounded-md border bg-background px-2 text-sm", selectClassName)}
        value={value}
        disabled={isDisabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {sortedDates.length === 0 && <option value="">暂无交易日</option>}
        {sortedDates.length > 0 && !value && <option value="">请选择交易日</option>}
        {showCurrentFallback && <option value={value}>{value} · 未在交易日列表</option>}
        {selectDates.map((tradeDate) => (
          <option key={tradeDate} value={tradeDate}>
            {getOptionLabel?.(tradeDate) ?? tradeDate}
          </option>
        ))}
      </select>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-8 px-2"
        disabled={isDisabled || value === firstDate}
        onClick={() => firstDate && onChange(firstDate)}
      >
        最早
      </Button>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-8 px-2"
        disabled={isDisabled || !previousDate}
        onClick={() => previousDate && onChange(previousDate)}
      >
        <ChevronLeft size={14} />
        上一交易日
      </Button>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-8 px-2"
        disabled={isDisabled || !nextDate}
        onClick={() => nextDate && onChange(nextDate)}
      >
        下一交易日
        <ChevronRight size={14} />
      </Button>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-8 px-2"
        disabled={isDisabled || value === latestDate}
        onClick={() => latestDate && onChange(latestDate)}
      >
        <CalendarDays size={14} />
        最近交易日
      </Button>
      {adjustedDate && (
        <span className="text-xs text-amber-700 dark:text-amber-300">
          已按交易日对齐到 {adjustedDate}
        </span>
      )}
    </div>
  );
}

function uniqueSortedDates(dates: string[]): string[] {
  return Array.from(new Set(dates.filter((item) => /^\d{4}-\d{2}-\d{2}$/.test(item)))).sort();
}

function nearestTradingDate(value: string, sortedDates: string[]): string {
  if (!value || sortedDates.length === 0) return "";
  for (let index = sortedDates.length - 1; index >= 0; index -= 1) {
    if (sortedDates[index] <= value) return sortedDates[index];
  }
  return sortedDates[0] ?? "";
}
