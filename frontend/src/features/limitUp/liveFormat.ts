import type { LimitUpLiveSignal } from "@/api/limitUp";
import type { PresentationTone } from "./nextSessionPlan";

export function presentationToneClass(tone: PresentationTone) {
  return ({
    positive: "text-rise",
    warning: "text-amber-700 dark:text-amber-300",
    negative: "text-fall",
    neutral: "text-foreground",
  } as Record<PresentationTone, string>)[tone];
}

export function entryKindLabel(value: string) {
  return (({
    none: "不执行",
    auction: "竞价",
    momentum: "动能",
    sweep: "扫板",
    reseal: "回封",
    tail_seal: "尾盘封板",
    next_auction: "竞价接力",
    first_touch: "首次触板",
    intraday: "盘中",
    wait: "等待确认",
  } as Record<string, string>)[value] ?? value) || "--";
}

export function sectorRouteLabel(value: string) {
  return ({ realtime_industry: "盘中行业", realtime_concept_launch: "概念启动" } as Record<string, string>)[value] ?? value;
}

export function phaseLabel(value?: string) {
  return ({
    warmup: "预热期",
    earlier_history: "更早历史稳健性",
    design_sample: "前段设计样本",
    time_validation: "后段时间验证",
    expanding_oos: "滚动样本外",
    locked_holdout: "锁定留出",
    post_freeze_forward: "冻结后前向",
  } as Record<string, string>)[value ?? ""] ?? value ?? "阶段未知";
}

export function d1OutcomeLabel(value: string) {
  return ({
    continuation_limit_up: "D+1 连板",
    next_limit_up_after_failed_board: "D+1 涨停",
    d1_premium: "D+1 有溢价",
    direct_breakdown: "D+1 直接砸",
    no_premium: "D+1 无溢价",
    awaiting_d1_bar: "待 D+1",
  } as Record<string, string>)[value] ?? value;
}

export function boardStatusLabel(value: string) {
  return ({ sealed: "封住", failed: "触板后炸板", no_limit: "未触板" } as Record<string, string>)[value] ?? value;
}

export function exitReasonLabel(value: string) {
  return ({
    dynamic_auction_exit: "动态竞价兑现",
    dynamic_tail_exit: "动态尾盘退出",
    planned_open: "开盘退出",
    planned_close: "收盘退出",
    planned_1430: "14:30退出",
    emergency_close: "开盘未成后收盘退出",
    retry_open: "延期至开盘退出",
    retry_close: "延期至收盘退出",
  } as Record<string, string>)[value] ?? value;
}

export function setupTagLabel(value: string) {
  return ({
    weak_market_theme_attack: "弱市题材进攻",
    sandwich_board: "夹板",
    return_board: "回马板",
    weak_to_strong_breakout: "弱转强突破",
    dragon_first_negative_relay: "龙首阴接力",
    dragon_weak_to_strong: "龙头弱转强",
    anti_nuclear_board: "反核板",
  } as Record<string, string>)[value] ?? value;
}

export function skipReasonLabel(value: string) {
  return ({
    position_limit: "持仓已满",
    insufficient_cash: "现金不足",
    below_one_lot: "目标仓位不足一手",
    duplicate_position: "已有同股持仓",
    invalid_entry_price: "买入价无效",
  } as Record<string, string>)[value] ?? value;
}

export function twoToThreeQualityLabel(tier?: "A" | "B" | null, riskCount?: number | null) {
  const quality = tier ?? "B";
  const risks = riskCount ?? 0;
  return `${quality}级${risks > 0 ? ` · 风险${risks}` : ""}`;
}

export function twoToThreeRiskTitle(flags?: string[]) {
  return (flags ?? []).map((flag) => ({
    auction_gap_outside_core: "竞价不在2%-5%核心区",
    prior_turnover_outside_core: "前板换手不在10%-20%核心区",
    prior_amount_ratio_outside_core: "前板量能比不在1.2-2",
    financial_snapshot_missing: "财报快照缺失",
    prior_low_below_zero: "前板最低价翻绿或缺失",
    prior_market_failed_rate_high: "前日炸板率偏高或缺失",
  } as Record<string, string>)[flag] ?? flag).join("；");
}

export function factorLabel(value: string) {
  return ({
    weak_market_theme_attack_setup: "强题材龙一/龙二承接",
    half_year_limit_up_gene: "半年有涨停",
    half_year_strong_touch_gene: "半年触板至少6次",
    low_position_or_cooled_pullback: "低位/充分回调",
    post_ten_first_touch: "10点后首次触板",
    intraday_support_confirmed: "盘中承接通过",
    first_board_seal_gate_confirmed: "封板门通过",
    point_in_time_profit_growth: "已披露净利同比至少10%",
    prior_divergence_repair_setup: "前日分歧修复",
    auction_strength_balanced: "竞价强度适中",
    prior_board_changed_hands_and_resealed: "前板换手回封",
    prior_board_full_turnover_reseal: "前板充分换手回封",
    prior_amount_ratio_balanced: "前板温和放量",
    financial_snapshot_available: "财报证据完整",
    prior_low_held_positive: "前板最低未翻绿",
    prior_market_failed_rate_controlled: "前日炸板率受控",
    prior_market_two_to_three_active: "二进三晋级率活跃",
    third_board_weak_to_strong: "三板弱转强",
    prior_divergence_next_auction_strength: "前日分歧次日转强",
    high_board_weak_to_strong: "高板弱转强",
    sector_core: "板块核心",
  } as Record<string, string>)[value] ?? value;
}

export function liveFactorSummary(signal: LimitUpLiveSignal) {
  const factors = signal.lane_favorable_factors ?? [];
  const priority = signal.board_lane === "first_board"
    ? [
      "weak_market_theme_attack_setup",
      "half_year_strong_touch_gene",
      "point_in_time_profit_growth",
      "prior_divergence_repair_setup",
      "intraday_support_confirmed",
    ]
    : factors.slice(0, 4);
  const visible = priority.filter((factor) => factors.includes(factor));
  return visible.map(factorLabel).join(" · ");
}

export function gateStateLabel(value?: boolean | null) {
  return value === true ? "通过" : value === false ? "未通过" : "待数据";
}

export function formatPct(value?: number | null) {
  return value == null || !Number.isFinite(value) ? "--" : `${value.toFixed(2)}%`;
}

export function formatSignedPct(value?: number | null) {
  return value == null || !Number.isFinite(value) ? "--" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function formatNumber(value?: number | null, digits = 2) {
  return value == null || !Number.isFinite(value) ? "--" : value.toFixed(digits);
}

export function formatPrice(value?: number | null) {
  return value == null || !Number.isFinite(value) ? "--" : `¥${value.toFixed(2)}`;
}

export function formatCurrency(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "--";
  const sign = value < 0 ? "-" : "";
  return `${sign}¥${Math.abs(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatAmount(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "--";
  const absolute = Math.abs(value);
  if (absolute >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (absolute >= 1e4) return `${(value / 1e4).toFixed(0)}万`;
  return value.toFixed(0);
}

export function formatTime(value: string) {
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date(value));
  } catch {
    return value.slice(11, 19);
  }
}

export function formatAge(seconds: number) {
  return seconds < 60 ? `${seconds}秒` : `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
}

export function amountTone(value?: number | null) {
  return value == null || !Number.isFinite(value) ? "text-muted-foreground" : value >= 0 ? "text-rise" : "text-fall";
}

export function rateTone(value?: number | null) {
  return value == null ? "text-muted-foreground" : value >= 50 ? "text-rise" : "text-fall";
}

export function tboxTone(value?: number | null) {
  return value == null ? "text-muted-foreground" : value >= 60 ? "text-rise" : value >= 40 ? "text-amber-700 dark:text-amber-300" : "text-fall";
}
