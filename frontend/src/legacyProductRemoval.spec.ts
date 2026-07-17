import { describe, expect, it } from "vitest";
import appSource from "./App.tsx?raw";
import shellSource from "./components/AppShell.tsx?raw";


describe("legacy product removal", () => {
  it("uses short-term research as the only short-horizon product entry", () => {
    expect(appSource).toContain('path="/short-term"');
    expect(appSource).not.toContain('path="/quant"');
    expect(appSource).not.toContain('path="/portfolio"');
    expect(shellSource).toContain('label: "短线研究"');
    expect(shellSource).not.toContain('label: "量化交易"');
    expect(shellSource).not.toContain('label: "持仓"');
  });
});
