/**
 * 统一时间轴纯函数：合并 live 最新日 + history 评分日，决定某日期走 live 还是 snapshot。
 *
 * 抽成纯函数是为了与 React 组件解耦、便于单测（见 unifiedTimeline.spec.ts）。
 * 组件层只负责把 live.trade_date / timeline.dates 喂进来，再按返回值切换数据源。
 */

/**
 * 合并 live 最新日 + history 日期，去重并降序排列（最新在最前）。
 */
export function buildUnifiedDateList(
  liveDate: string | null | undefined,
  historyDates: readonly string[],
): string[] {
  const all = liveDate ? [liveDate, ...historyDates] : [...historyDates];
  return Array.from(new Set(all)).sort((a, b) => (a < b ? 1 : a > b ? -1 : 0));
}

/**
 * 判断当前选中日期应使用 live 数据源还是 history snapshot。
 * 规则：选中日期等于 liveDate 才用 live；其余（含 liveDate 缺失）走 history。
 */
export function pickDataSource(
  selectedDate: string | null | undefined,
  liveDate: string | null | undefined,
): "live" | "history" {
  if (!selectedDate || !liveDate) return "history";
  return selectedDate === liveDate ? "live" : "history";
}
