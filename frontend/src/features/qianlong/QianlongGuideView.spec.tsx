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
  matrix_buckets: ["黄金窗 09:30-09:50", "衰减期 09:50-10:30"],
  gap_rows: [
    { label: "平开 0~2%", n: 440, seal: 36.1, d1_win: 42.7, ret: 0.68, verdict: "neutral" as const,
      advice: "确实要看时段:黄金窗 A +2.86、B +4.72 都强;衰减期 A 仅 +0.11 接近白干",
      a: { n: 335, seal: 34.9, d1_win: 40.3, ret: 0.48 },
      b: { n: 105, seal: 40.0, d1_win: 49.5, ret: 1.34 },
      cells_a: [{ seal: 65.2, n: 112, ret: 2.86 }, { seal: 35.7, n: 70, ret: 0.11 }],
      cells_b: [{ seal: 77.8, n: 36, ret: 4.72 }, { seal: 42.3, n: 26, ret: 0.50 }] },
    { label: "高开 4~6%", n: 41, seal: 63.4, d1_win: 68.3, ret: 2.79, verdict: "good" as const,
      advice: "秒冲型,衰减期几乎不存在",
      a: { n: 39, seal: 64.1, d1_win: 69.2, ret: 2.73 },
      b: { n: 7, seal: 71.4, d1_win: 71.4, ret: 4.49 },
      cells_a: [{ seal: 69.4, n: 36, ret: 3.23 }, { seal: 0.0, n: 1, ret: -4.68 }],
      cells_b: [{ seal: 71.4, n: 7, ret: 4.49 }, null] },
  ],
  note: "不替换 +8% 触发线。",
};

describe("AuctionMatrixSection 竞价决策矩阵", () => {
  it("渲染 A/B 并排总表(判定徽章/着色收益)+ A/B 两张热感矩阵(样本不足显示—)", () => {
    const html = renderToStaticMarkup(<AuctionMatrixSection matrix={AUCTION_MATRIX} />);
    expect(html).toContain("竞价开盘 × 时段 · 7% 直买决策矩阵");
    expect(html).toContain("A类(全新急建仓)");
    expect(html).toContain("B类(小阳建仓)");
    expect(html).toContain("限黄金窗");
    expect(html).toContain("可做");
    expect(html).toContain("确实要看时段");
    expect(html).toContain("黄金窗 09:30-09:50");
    expect(html).toContain("衰减期 09:50-10:30");
    expect(html).toContain("+2.86");    // 平开 A 黄金窗 ret
    expect(html).toContain("+4.72");    // 平开 B 黄金窗 ret
    expect(html).toContain("—");        // cells null / n<3 样本不足
    expect(html).toContain("不替换 +8% 触发线");
  });
});
