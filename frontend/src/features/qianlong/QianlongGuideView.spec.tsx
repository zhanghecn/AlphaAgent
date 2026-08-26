import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AuctionMatrixSection, IntradayWindowsTable } from "@/features/qianlong/QianlongGuideView";

const WINDOWS = [
  { level: "gold" as const, start: "09:30", end: "09:50", label: "黄金操作窗",
    advice: "触板率 80%±2——收益核心时段",
    stats: { a: { n: 199, seal: 80.9, streak: 10.6, d1: 1.81, ret: 3.70 },
             b: { n: 65, seal: 80.0, streak: 16.9, d1: 2.45, ret: 4.04 } } },
  { level: "fading" as const, start: "09:50", end: "10:30", label: "动能衰减期",
    advice: "09:50 断崖:触板率骤降、连板率归零",
    stats: { a: { n: 98, seal: 62.2, streak: 8.2, d1: 0.64, ret: 1.69 },
             b: { n: 35, seal: 60.0, streak: 11.4, d1: 1.96, ret: 3.39 } } },
  { level: "weak" as const, start: "10:30", end: "11:30", label: "弱时段",
    advice: "A 类转负,B 类尚有但样本少",
    stats: { a: { n: 78, seal: 41.0, streak: 1.3, d1: -0.74, ret: -0.61 },
             b: { n: 24, seal: 45.8, streak: 8.3, d1: 0.90, ret: 1.64 } } },
  { level: "lunch" as const, start: "11:30", end: "13:00", label: "午间休市",
    advice: "休市" },
];

describe("IntradayWindowsTable 时段窗口表格", () => {
  it("渲染时间窗/级别徽章/操作要点/研究脚注", () => {
    const html = renderToStaticMarkup(
      <IntradayWindowsTable windows={WINDOWS} note="时段质量来自分钟级研究(916 笔)。" />,
    );
    expect(html).toContain("什么时候操作 · 时段质量分层");
    expect(html).toContain("时间窗");
    expect(html).toContain("A类(全新急建仓)");
    expect(html).toContain("B类(小阳建仓)");
    expect(html).toContain("09:30~09:50");
    expect(html).toContain("黄金操作窗");
    expect(html).toContain("09:50 断崖");
    expect(html).toContain("时段质量来自分钟级研究");
  });

  it("A/B 数据列:笔数/收益着色/触板率;无数据窗显示 --", () => {
    const html = renderToStaticMarkup(
      <IntradayWindowsTable windows={WINDOWS} />,
    );
    expect(html).toContain("199 笔");
    expect(html).toContain("+3.70%");
    expect(html).toContain("触板 81%");
    expect(html).toContain("65 笔");
    expect(html).toContain("98 笔");
    expect(html).toContain("text-fall"); // weak 窗 A 类 -0.61 负收益着色
    expect(html).toContain("--");         // lunch 无 stats
  });
});

const AUCTION_MATRIX = {
  caliber: "竞价档 × 首次触及+7% 时段交叉,分钟样本 924 笔,A/B 分开统计。",
  matrix_buckets: ["09:30", "09:35", "09:40", "09:45"],
  gap_rows: [
    { label: "高开 6~8%", n: 23, seal: 87.0, d1_win: 95.7, ret: 6.18, verdict: "best" as const,
      advice: "全场最强,只在前 10 分钟出现",
      a: { n: 22, seal: 86.4, d1_win: 95.5, ret: 6.17 },
      b: { n: 1, seal: 100.0, d1_win: 100.0, ret: 6.40 },
      cells: [{ seal: 86.7, n: 15 }, { seal: 100.0, n: 7 }, null, null],
      cells_a: [{ seal: 86.7, n: 15 }, { seal: 100.0, n: 6 }, null, null],
      cells_b: [null, null, null, null] },
    { label: "低开 <0%", n: 387, seal: 32.6, d1_win: 37.5, ret: 0.06, verdict: "avoid" as const,
      advice: "A 类负期望以 8% 触发为准,B 类尚可",
      a: { n: 302, seal: 30.8, d1_win: 36.4, ret: -0.39 },
      b: { n: 85, seal: 38.8, d1_win: 43.5, ret: 1.17 },
      cells: [{ seal: 37.5, n: 8 }, { seal: 59.3, n: 27 }, { seal: 58.3, n: 24 }, { seal: 52.6, n: 19 }],
      cells_a: [{ seal: 40.0, n: 5 }, { seal: 66.7, n: 21 }, { seal: 65.0, n: 20 }, { seal: 50.0, n: 18 }],
      cells_b: [{ seal: 33.3, n: 3 }, { seal: 44.4, n: 9 }, { seal: 57.1, n: 7 }, null] },
  ],
  note: "不替换 +8% 触发线。",
};

describe("AuctionMatrixSection 竞价决策矩阵", () => {
  it("渲染 A/B 并排总表(判定徽章/着色收益)+ A/B 两张热感矩阵(样本不足显示—)", () => {
    const html = renderToStaticMarkup(<AuctionMatrixSection matrix={AUCTION_MATRIX} />);
    expect(html).toContain("竞价开盘 × 时段 · 7% 直买决策矩阵");
    expect(html).toContain("A类(全新急建仓)");
    expect(html).toContain("B类(小阳建仓)");
    expect(html).toContain("最优");
    expect(html).toContain("不做");
    expect(html).toContain("+6.17%");   // 高开6~8 A 组 ret
    expect(html).toContain("-0.39%");   // 低开 A 组负收益 fall 着色
    expect(html).toContain("+1.17%");   // 低开 B 组
    expect(html).toContain("黄金窗封板率热感");
    expect(html).toContain("100%");     // cells_a 高开6~8 09:35 桶
    expect(html).toContain("—");        // cells null 样本不足
    expect(html).toContain("不替换 +8% 触发线");
  });
});
