import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ShortTermResearchPage } from "./ShortTermResearchPage";

function withProviders(node: React.ReactElement, routerEntries: string[] = ["/short-term"]) {
  return <MemoryRouter initialEntries={routerEntries}>{node}</MemoryRouter>;
}

// ── 短线研究精华化(2026-10-02,主人拍板):默认落地=主线总览,二波反包下线 ──

describe("ShortTermResearchPage 主线总览", () => {
  it("默认落地=主线总览:双主线卡片带定位/月均/分年数字/答题入口", () => {
    const html = renderToStaticMarkup(withProviders(<ShortTermResearchPage />));
    expect(html).toContain("主线总览");
    expect(html).toContain("短线打板 · 双主线");
    expect(html).toContain("高位接力");
    expect(html).not.toContain("N型补涨打板"); // 2026-10-02 终版下线
    expect(html).toContain("断板反包");
    expect(html).toContain("主力");
    expect(html).toContain("补充");
    expect(html).toContain("+482%"); // hpr 2024 年累计
        expect(html).toContain("答题训练"); // hpr/fbb 有入口
    expect(html).not.toContain("答题训练待建"); // 三线答题训练全上线(w2s 2026-10-02 补齐)
  });

  it("二波反包页签已删干净(页签/面板均无)", () => {
    const html = renderToStaticMarkup(withProviders(<ShortTermResearchPage />));
    expect(html).not.toContain("二波反包");
    expect(html).not.toContain("research-tab-erbo");
  });

  it("research=erbo 旧书签回落主线总览(不 404)", () => {
    const html = renderToStaticMarkup(
      withProviders(<ShortTermResearchPage />, ["/short-term?research=erbo"]),
    );
    expect(html).toContain('id="research-tab-overview"');
  });
});
