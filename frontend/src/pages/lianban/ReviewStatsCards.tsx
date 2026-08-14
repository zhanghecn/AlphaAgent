import { Fragment } from "react";

import type { LianbanStats } from "@/api/lianban";
import { cn } from "@/lib/utils";

/** 升降语义：rise = 红（暖/强势），fall = 绿（冷/走弱），A 股红涨绿跌惯例。 */
export type Tone = "rise" | "fall" | null;

export interface StatCardSubPart {
  text: string;
  tone?: Tone;
}

export interface StatCardModel {
  key: string;
  title: string;
  big: string;
  /** 大数字着色（仅昨涨停今表现按涨跌着色，其余保持中性） */
  bigTone?: Tone;
  sub: StatCardSubPart[];
}

// ===== 格式化函数（单位注意：seal_rate/rise_ratio 是 0-1 比率；prev_lu_*_change 是百分数数值；
//       total_amount/margin_balance/margin_change 单位为元）=====

/** 元 → "2.55万亿" / "8500亿" / "5000万"；万亿以下用亿/万。 */
export function formatWanYiAmount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)}万亿`;
  if (abs >= 1e8) return `${(value / 1e8).toFixed(0)}亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(0)}万`;
  return value.toFixed(0);
}

/** 带符号的亿级格式化（融资余额变动）：9.5e9 → "+95亿"；0 → "0亿"。 */
export function formatSignedYi(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--";
  if (value === 0) return "0亿";
  const abs = Math.abs(value);
  const sign = value > 0 ? "+" : "-";
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(2)}万亿`;
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(0)}亿`;
  if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(0)}万`;
  return `${sign}${abs.toFixed(0)}`;
}

/** 0-1 比率 → 百分数字符串：0.621 → "62.1%"。 */
export function formatRatioPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--";
  return `${(value * 100).toFixed(1)}%`;
}

/** 百分数数值 → 带符号字符串：1.2 → "+1.2%"；-1.5 → "-1.5%"。 */
export function formatPctPoint(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

/** 千分位整数：4091 → "4,091"。 */
export function formatGroupedInt(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--";
  return Math.round(value).toLocaleString("en-US");
}

/** "2026-08-12" → "08-12"；非 ISO 原样返回。 */
export function formatShortDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "--";
  const match = /^\d{4}-(\d{2})-(\d{2})$/.exec(isoDate);
  return match ? `${match[1]}-${match[2]}` : isoDate;
}

/** 情绪温度取整：40.4 → "40°"。 */
export function formatTemperature(score: number): string {
  return `${Math.round(score)}°`;
}

// ===== 派生逻辑 =====

/**
 * 昨日对比的升降语义色。
 * polarity=positive（涨停/连板/最高板/封板率）：上升=红（强势），下降=绿。
 * polarity=inverse（跌停/炸板）：上升=绿（走弱），下降=红。
 * 持平或任一缺失 → null（不着色）。
 */
export function deltaTone(
  current: number | null,
  prev: number | null,
  polarity: "positive" | "inverse",
): Tone {
  if (current == null || prev == null || current === prev) return null;
  const up = current > prev;
  if (polarity === "positive") return up ? "rise" : "fall";
  return up ? "fall" : "rise";
}

/** 红盘占比：rise/(rise+fall)*100 取整；任一缺失或合计为 0 → null。 */
export function riseRatioPercent(rise: number | null, fall: number | null): number | null {
  if (rise == null || fall == null) return null;
  const total = rise + fall;
  if (total <= 0) return null;
  return Math.round((rise / total) * 100);
}

/** 新高/新低对比文案。 */
export function highLowLabel(high: number, low: number): string {
  if (high > low) return "新高占优";
  if (high < low) return "新低占优";
  return "持平";
}

function signTone(value: number): Tone {
  if (value > 0) return "rise";
  if (value < 0) return "fall";
  return null;
}

interface DeltaCardOptions {
  suffix?: string;
  format?: (value: number) => string;
}

function deltaCard(
  key: string,
  title: string,
  current: number | null,
  prev: number | null,
  polarity: "positive" | "inverse",
  options?: DeltaCardOptions,
): StatCardModel {
  const format = options?.format ?? formatGroupedInt;
  const suffix = options?.suffix ?? "";
  return {
    key,
    title,
    big: current == null ? "--" : `${format(current)}${suffix}`,
    sub:
      prev == null
        ? []
        : [{ text: `昨 ${format(prev)}${suffix}`, tone: deltaTone(current, prev, polarity) }],
  };
}

/** 12 张统计卡的派生模型（纯函数，便于单测契约字段与 null 路径）。 */
export function buildStatCards(stats: LianbanStats): StatCardModel[] {
  const cards: StatCardModel[] = [
    deltaCard("limit_up", "涨停", stats.limit_up, stats.limit_up_prev, "positive"),
    deltaCard("lianban", "连板", stats.lianban, stats.lianban_prev, "positive"),
    deltaCard("max_streak", "最高板", stats.max_streak, stats.max_streak_prev, "positive", {
      suffix: "板",
    }),
    deltaCard("limit_down", "跌停", stats.limit_down, stats.limit_down_prev, "inverse"),
    deltaCard("seal_rate", "封板率", stats.seal_rate, stats.seal_rate_prev, "positive", {
      format: formatRatioPct,
    }),
    deltaCard("broken", "炸板", stats.broken, stats.broken_prev, "inverse"),
  ];

  // 昨涨停今表现：大数字 = 平均涨幅（百分数数值），副行 = 中位 + 翻红占比
  const prevLuSub: StatCardSubPart[] = [];
  if (stats.prev_lu_median_change != null) {
    prevLuSub.push({
      text: `中位 ${formatPctPoint(stats.prev_lu_median_change)}`,
      tone: signTone(stats.prev_lu_median_change),
    });
  }
  if (stats.prev_lu_rise_ratio != null) {
    prevLuSub.push({ text: `翻红 ${formatRatioPct(stats.prev_lu_rise_ratio)}` });
  }
  cards.push({
    key: "prev_lu_performance",
    title: "昨涨停今表现",
    big: formatPctPoint(stats.prev_lu_avg_change),
    bigTone: stats.prev_lu_avg_change == null ? null : signTone(stats.prev_lu_avg_change),
    sub: prevLuSub,
  });

  // 情绪周期：大数字 = 阶段，副行 = 温度
  cards.push({
    key: "sentiment",
    title: "情绪周期",
    big: stats.sentiment_phase ?? "--",
    sub:
      stats.sentiment_score == null
        ? []
        : [{ text: `温度 ${formatTemperature(stats.sentiment_score)}` }],
  });

  // 上涨/下跌：大数字 = "1,100/4,091"，副行 = 红盘占比
  const risePct = riseRatioPercent(stats.rise_count, stats.fall_count);
  cards.push({
    key: "rise_fall",
    title: "上涨/下跌",
    big:
      stats.rise_count == null || stats.fall_count == null
        ? "--"
        : `${formatGroupedInt(stats.rise_count)}/${formatGroupedInt(stats.fall_count)}`,
    sub: risePct == null ? [] : [{ text: `红盘 ${risePct}%` }],
  });

  // 新高/新低 63 日
  cards.push({
    key: "high_low_63",
    title: "新高/新低63日",
    big:
      stats.new_high_63 == null || stats.new_low_63 == null
        ? "--"
        : `${formatGroupedInt(stats.new_high_63)}/${formatGroupedInt(stats.new_low_63)}`,
    sub:
      stats.new_high_63 == null || stats.new_low_63 == null
        ? []
        : [{ text: highLowLabel(stats.new_high_63, stats.new_low_63) }],
  });

  // 两市成交（元 → 万亿/亿）
  cards.push({
    key: "total_amount",
    title: "两市成交",
    big: formatWanYiAmount(stats.total_amount),
    sub: [],
  });

  // 融资余额：大数字 = 余额，副行 = 较前日变动 + 数据日期
  const marginSub: StatCardSubPart[] = [];
  if (stats.margin_change != null) {
    marginSub.push({
      text: `较前日 ${formatSignedYi(stats.margin_change)}`,
      tone: signTone(stats.margin_change),
    });
  }
  if (stats.margin_date != null) {
    marginSub.push({ text: formatShortDate(stats.margin_date) });
  }
  cards.push({
    key: "margin_balance",
    title: "融资余额",
    big: formatWanYiAmount(stats.margin_balance),
    sub: marginSub,
  });

  return cards;
}

function toneClass(tone: Tone): string | undefined {
  if (tone === "rise") return "text-rise";
  if (tone === "fall") return "text-fall";
  return undefined;
}

/** 复盘统计卡网格：手机 2 列 / 桌面 4-6 列的紧凑卡片。 */
export function ReviewStatsCards({ stats }: { stats: LianbanStats }) {
  const cards = buildStatCards(stats);
  return (
    <section
      aria-label="复盘统计"
      className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6"
    >
      {cards.map((card) => (
        <div key={card.key} className="rounded-lg border bg-card px-3 py-2.5">
          <p className="text-[11px] text-muted-foreground">{card.title}</p>
          <p
            className={cn(
              "mt-1 text-xl font-semibold tabular-nums",
              card.bigTone ? toneClass(card.bigTone) : "text-foreground",
            )}
          >
            {card.big}
          </p>
          {card.sub.length > 0 && (
            <p className="mt-0.5 text-[11px] tabular-nums text-muted-foreground">
              {card.sub.map((part, index) => (
                <Fragment key={`${card.key}-sub-${index}`}>
                  {index > 0 && <span className="text-muted-foreground/50"> · </span>}
                  <span className={toneClass(part.tone ?? null)}>{part.text}</span>
                </Fragment>
              ))}
            </p>
          )}
        </div>
      ))}
    </section>
  );
}
