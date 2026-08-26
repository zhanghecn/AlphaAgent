import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { IntradayWindowsTable } from "@/features/qianlong/QianlongGuideView";

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
