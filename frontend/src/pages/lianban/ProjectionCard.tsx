import type { LianbanProjection } from "@/api/lianban";
import { cn } from "@/lib/utils";
import {
  formatPctPoint,
  formatRatioPct,
  formatShortDate,
  type Tone,
} from "./ReviewStatsCards";

/** 0-1 比率 → 整数百分数：0.33 → "33%"（对齐 lianban「33%」整数口径）。 */
export function formatRatioPctInt(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--";
  return `${Math.round(value * 100)}%`;
}

/** 温度变化带符号：4 → "+4°"；-2.5 → "-2.5°"；0 → "0°"。 */
export function formatSignedDegree(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--";
  if (value === 0) return "0°";
  const sign = value > 0 ? "+" : "-";
  const abs = Math.abs(value);
  const digits = Number.isInteger(abs) ? abs.toFixed(0) : abs.toFixed(1);
  return `${sign}${digits}°`;
}

/** phase_label 补"期"字：退潮 → 退潮期；已带期原样。 */
export function phaseLabelWithQi(label: string): string {
  return label.endsWith("期") ? label : `${label}期`;
}

/**
 * 同景日期 chips：与推演信号日同年 → "MM-DD"；跨年 → "YY-MM-DD"（如 24-09-18）。
 * 同景样本跨 2024-2026 多年，不补年份会看起来像同一年内的乱序日期。
 */
export function formatSceneDate(
  isoDate: string,
  baseIsoDate: string | null | undefined,
): string {
  if (!baseIsoDate || isoDate.slice(0, 4) === baseIsoDate.slice(0, 4)) {
    return formatShortDate(isoDate);
  }
  return `${isoDate.slice(2, 4)}-${isoDate.slice(5, 7)}-${isoDate.slice(8, 10)}`;
}

export interface ProjectionCell {
  key: string;
  title: string;
  value: string;
  tone?: Tone;
}

export interface ProjectionChip {
  date: string;
  text: string;
  tone: Tone;
}

export interface ProjectionModel {
  /** 副标题：「08-13 收盘 · 退潮期 第1天 · 🐻年线下方 · 同景 96 次」，缺失段自动省略。 */
  subtitle: string;
  /** 样本不足（insufficient_data）：标题旁降级徽标 + 提示行。 */
  insufficient: boolean;
  /**
   * 滞后提示：复盘页日期晚于推演信号日（live 盘中配昨日情绪）时，
   * 明示推演基于哪天、今日推演何时出，避免两卡日期错位被误读。
   */
  lagNote: string | null;
  cells: ProjectionCell[];
  chips: ProjectionChip[];
}

function signTone(value: number): Tone {
  if (value > 0) return "rise";
  if (value < 0) return "fall";
  return null;
}

/**
 * 明日推演派生模型（纯函数，便于单测格式化/降级路径）。
 * 四格统计：次日上涨概率 | 次日上证均值 | 最可能去向 | 温度平均变化。
 */
export function buildProjectionModel(
  p: LianbanProjection,
  reviewDate?: string | null,
): ProjectionModel {
  const subtitleParts: string[] = [];
  if (p.trade_date) {
    subtitleParts.push(`${formatShortDate(p.trade_date)} 收盘`);
  }
  if (p.phase_label) {
    subtitleParts.push(
      p.phase_day != null
        ? `${phaseLabelWithQi(p.phase_label)} 第${p.phase_day}天`
        : phaseLabelWithQi(p.phase_label),
    );
  }
  if (p.above_ma250 != null) {
    subtitleParts.push(p.above_ma250 ? "🐂年线上方" : "🐻年线下方");
  }
  subtitleParts.push(`同景 ${p.sample_count} 次`);

  const lagNote =
    p.trade_date && reviewDate && reviewDate > p.trade_date
      ? `推演基于 ${formatShortDate(p.trade_date)} 收盘情绪 · ${formatShortDate(reviewDate)} 推演待盘后更新`
      : null;

  const top = p.phase_next[0];
  const cells: ProjectionCell[] = [
    {
      key: "up_prob",
      title: "次日上涨概率",
      value: formatRatioPct(p.next_day.up_prob),
    },
    {
      key: "avg_change",
      title: "次日上证均值",
      value: formatPctPoint(p.next_day.avg_change),
      tone:
        p.next_day.avg_change == null ? null : signTone(p.next_day.avg_change),
    },
    {
      key: "phase_next",
      title: "最可能去向",
      value: top ? `${top.label} ${formatRatioPctInt(top.ratio)}` : "--",
    },
    {
      key: "score_change",
      title: "温度平均变化",
      value: formatSignedDegree(p.score_change_avg),
      tone: p.score_change_avg == null ? null : signTone(p.score_change_avg),
    },
  ];

  const chips: ProjectionChip[] = p.scene_dates.map((entry) => ({
    date: entry.date,
    text: `${formatSceneDate(entry.date, p.trade_date)} ${formatPctPoint(entry.next_change)}`,
    tone: entry.next_change == null ? null : signTone(entry.next_change),
  }));

  return {
    subtitle: subtitleParts.join(" · "),
    insufficient: p.status === "insufficient_data",
    lagNote,
    cells,
    chips,
  };
}

function toneClass(tone: Tone): string | undefined {
  if (tone === "rise") return "text-rise";
  if (tone === "fall") return "text-fall";
  return undefined;
}

/**
 * 「🔮 明日推演」卡：同景（同情绪阶段+同年线位置）历史日的次日统计。
 * 样本不足时降级徽标提示，已有字段照常展示；横滚同景日期 chips 红涨绿跌。
 * reviewDate 为复盘页当前日期：晚于推演信号日（live 盘中配昨日情绪）时
 * 显示滞后提示行，明示推演口径而不是静默错位。
 */
export function ProjectionCard({
  projection,
  reviewDate,
}: {
  projection: LianbanProjection;
  reviewDate?: string | null;
}) {
  const model = buildProjectionModel(projection, reviewDate);
  return (
    <section
      aria-label="明日推演"
      className="rounded-lg border bg-card px-3 py-2.5 sm:px-4"
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <h2 className="text-sm font-semibold text-foreground">🔮 明日推演</h2>
        {model.insufficient && (
          <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-px text-[10px] text-amber-600">
            同景样本不足
          </span>
        )}
        <p className="text-[11px] tabular-nums text-muted-foreground">
          {model.subtitle}
        </p>
      </div>
      {model.lagNote && (
        <p className="mt-1 text-[10px] tabular-nums text-amber-600/90">
          {model.lagNote}
        </p>
      )}
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {model.cells.map((cell) => (
          <div key={cell.key} className="min-w-0">
            <p className="text-[11px] text-muted-foreground">{cell.title}</p>
            <p
              className={cn(
                "mt-0.5 text-base font-semibold tabular-nums",
                cell.tone ? toneClass(cell.tone) : "text-foreground",
              )}
            >
              {cell.value}
            </p>
          </div>
        ))}
      </div>
      {model.chips.length > 0 && (
        <div className="mt-2 flex gap-1 overflow-x-auto pb-0.5">
          {model.chips.map((chip) => (
            <span
              key={chip.date}
              className={cn(
                "shrink-0 rounded border px-1.5 py-0.5 text-[11px] tabular-nums",
                chip.tone ? toneClass(chip.tone) : "text-muted-foreground",
              )}
            >
              {chip.text}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
