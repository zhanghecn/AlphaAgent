import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { BacktestRebuildControl } from "./BacktestRebuildControl";

describe("BacktestRebuildControl", () => {
  it("offers a clear manual rebuild command while idle", () => {
    const html = renderToStaticMarkup(
      <BacktestRebuildControl running={false} error={null} onRebuild={() => undefined} />,
    );

    expect(html).toContain("重新计算");
    expect(html).not.toContain("disabled=\"\"");
    expect(html).not.toContain("当前显示上次结果");
  });

  it("prevents duplicate runs while keeping the previous report readable", () => {
    const html = renderToStaticMarkup(
      <BacktestRebuildControl running error={null} onRebuild={() => undefined} />,
    );

    expect(html).toContain("计算中");
    expect(html).toContain("disabled=\"\"");
    expect(html).toContain("当前显示上次结果");
  });

  it("shows a rebuild failure without hiding the report", () => {
    const html = renderToStaticMarkup(
      <BacktestRebuildControl
        running={false}
        error="历史数据源不可用"
        onRebuild={() => undefined}
      />,
    );

    expect(html).toContain("重算失败：历史数据源不可用");
  });
});
