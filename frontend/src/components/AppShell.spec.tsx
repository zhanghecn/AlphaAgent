import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ADMIN_SESSION_QUERY_KEY } from "@/api/client";
import { AppShell } from "./AppShell";

vi.mock("@/components/MarketPulse", () => ({ MarketPulse: () => null }));
vi.mock("@/theme/useTheme", () => ({
  useTheme: () => ({ theme: "light", toggle: () => undefined }),
}));

describe("AppShell login access", () => {
  it("shows the login action to an anonymous visitor", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(ADMIN_SESSION_QUERY_KEY, { authenticated: false });

    const html = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AppShell>
            <div />
          </AppShell>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(html).toContain('href="/login"');
    expect(html).toContain('aria-label="登录"');
    expect(html).toContain("登录");
    expect(html).not.toContain("退出登录");
  });
});
