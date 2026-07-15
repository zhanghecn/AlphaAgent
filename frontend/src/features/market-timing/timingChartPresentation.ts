import type { Time } from "lightweight-charts";
import type {
  TimingBar,
  TimingDailyEvent,
  TimingDailyState,
  TimingDirection,
} from "@/api/marketTiming";

export interface TimingHoverSummary {
  date: string;
  bar: TimingBar;
  changePct: number | null;
  state: TimingDailyState | null;
  activeDirection: TimingDirection;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function numericTimeParts(value: number): { year: number; month: number; day: number } {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(value * 1000));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((item) => item.type === type)?.value ?? 0);
  return { year: part("year"), month: part("month"), day: part("day") };
}

function timingDateKey(time: Time): string {
  if (typeof time === "string") return time.slice(0, 10);
  const parts = typeof time === "number" ? numericTimeParts(time) : time;
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}`;
}

export function formatTimingCrosshairDate(time: Time): string {
  return timingDateKey(time);
}

export function formatTimingAxisTick(time: Time): string {
  return timingDateKey(time).slice(5);
}

export function buildTimingHoverSummaries(
  bars: TimingBar[],
  series: TimingDailyState[],
): Map<string, TimingHoverSummary> {
  const stateByDate = new Map(series.map((state) => [state.date, state]));
  const orderedStates = [...series].sort((left, right) => left.date.localeCompare(right.date));
  let stateIndex = 0;
  let activeDirection: TimingDirection = "NEUTRAL";

  return new Map(
    bars.map((bar, index) => {
      while (
        stateIndex < orderedStates.length
        && orderedStates[stateIndex].date <= bar.date
      ) {
        const nextDirection = orderedStates[stateIndex].active_direction;
        if (nextDirection !== "NEUTRAL" || activeDirection === "NEUTRAL") {
          activeDirection = nextDirection;
        }
        stateIndex += 1;
      }
      const previousClose = index > 0 ? bars[index - 1].close : null;
      const changePct = previousClose && previousClose > 0
        ? (bar.close / previousClose - 1) * 100
        : null;
      return [
        bar.date,
        {
          date: bar.date,
          bar,
          changePct,
          state: stateByDate.get(bar.date) ?? null,
          activeDirection,
        },
      ];
    }),
  );
}

export function timingActiveLabel(direction: TimingDirection | null): string {
  if (direction === "GOLD") return "金手指延续";
  if (direction === "SILVER") return "银手指延续";
  return "尚无手指";
}

function eventDirectionLabel(event: TimingDailyEvent): string {
  return event.direction === "GOLD" ? "金" : "银";
}

export function timingEventLabel(event: TimingDailyEvent | null): string {
  if (!event || event.status === "INVALIDATED") return "无";
  const status = event.status === "CONFIRMED" ? "确认" : "待确认";
  return `${eventDirectionLabel(event)}手指${status}`;
}
