import type { Time } from "lightweight-charts";
import type {
  TimingBar,
  TimingDailyEvent,
  TimingDailyState,
} from "@/api/marketTiming";

export interface TimingConfirmation {
  candidateDate: string;
  event: TimingDailyEvent;
}

export interface TimingHoverSummary {
  date: string;
  bar: TimingBar;
  changePct: number | null;
  state: TimingDailyState | null;
  confirmations: TimingConfirmation[];
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
  const confirmationsByDate = new Map<string, TimingConfirmation[]>();
  for (const state of series) {
    const event = state.event;
    if (!event?.confirm_date) continue;
    const confirmDate = event.confirm_date;
    const confirmations = confirmationsByDate.get(confirmDate) ?? [];
    confirmations.push({ candidateDate: state.date, event });
    confirmationsByDate.set(confirmDate, confirmations);
  }

  return new Map(
    bars.map((bar, index) => {
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
          confirmations: confirmationsByDate.get(bar.date) ?? [],
        },
      ];
    }),
  );
}

export function timingZoneLabel(state: TimingDailyState | null): string {
  if (!state) return "因子未就绪";
  if (state.zone_direction === "GOLD") return "金候选区";
  if (state.zone_direction === "SILVER") return "银候选区";
  return "中性";
}

export function timingActiveLabel(state: TimingDailyState | null): string {
  if (!state) return "因子未就绪";
  if (state.active_direction === "GOLD") return "金未反转";
  if (state.active_direction === "SILVER") return "银未反转";
  return "尚无确认";
}

function eventDirectionLabel(event: TimingDailyEvent): string {
  return event.direction === "GOLD" ? "金" : "银";
}

function eventStatusLabel(event: TimingDailyEvent): string {
  if (event.status === "CONFIRMED") return "已确认";
  if (event.status === "INVALIDATED") return "已否决";
  return "待确认";
}

export function timingEventLabel(event: TimingDailyEvent | null): string {
  if (!event) return "无";
  return `${eventDirectionLabel(event)}候选${eventStatusLabel(event)}`;
}

function chineseMonthDay(date: string): string {
  const [, month = "", day = ""] = date.split("-");
  return `${Number(month)}月${Number(day)}日`;
}

export function timingConfirmationLabels(items: TimingConfirmation[]): string[] {
  return [...items]
    .sort((left, right) => left.candidateDate.localeCompare(right.candidateDate))
    .map(
      ({ candidateDate, event }) =>
        `${chineseMonthDay(candidateDate)}${eventDirectionLabel(event)}候选${eventStatusLabel(event)}`,
    );
}
