import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Compass,
  Database,
  LayoutDashboard,
  Network,
  Activity,
  Briefcase,
  TrendingUp,
  ChevronLeft,
  ChevronRight,
  Sun,
  Moon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/theme/useTheme";

const NAV_ITEMS = [
  { to: "/", label: "今日市场", icon: LayoutDashboard },
  { to: "/explore", label: "主线探索", icon: Compass },
  { to: "/stocks", label: "全 A 股票", icon: TrendingUp },
  { to: "/quant", label: "量化交易", icon: Activity },
  { to: "/portfolio", label: "持仓", icon: Briefcase },
  { to: "/chain", label: "产业链", icon: Network },
  { to: "/data", label: "数据管理", icon: Database },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const { theme, toggle } = useTheme();

  return (
    <div className="flex min-h-screen bg-background md:h-screen md:overflow-hidden">
      {/* Mobile top nav */}
      <header className="fixed inset-x-0 top-0 z-30 border-b bg-card md:hidden">
        <div className="flex h-14 items-center justify-between px-4">
          <span className="text-lg font-bold tracking-tight">AlphaAgent</span>
          <button
            type="button"
            onClick={toggle}
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            title={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
            aria-label="切换深浅色主题"
          >
            {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
          </button>
        </div>
        <nav className="grid grid-cols-4 gap-1 px-2 pb-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => {
            const active = location.pathname === to ||
              (to !== "/" && location.pathname.startsWith(to));
            return (
              <Link
                key={to}
                to={to}
                className={cn(
                  "flex min-w-0 items-center justify-center gap-1 rounded-md px-1 py-2 text-xs font-medium transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon size={16} />
                <span className="truncate">{label}</span>
              </Link>
            );
          })}
        </nav>
      </header>

      {/* Sidebar */}
      <aside
        className={cn(
          "hidden flex-col border-r bg-card transition-all duration-200 md:flex",
          collapsed ? "w-16" : "w-56",
        )}
      >
        <div className="flex h-14 items-center border-b px-4">
          {!collapsed && (
            <span className="text-lg font-bold tracking-tight">AlphaAgent</span>
          )}
          <button
            type="button"
            className={cn(
              "ml-auto rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground",
              collapsed && "ml-0",
            )}
            onClick={() => setCollapsed((v) => !v)}
            aria-label="折叠/展开侧边栏"
          >
            {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
        </div>
        <nav className="flex-1 space-y-1 p-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => {
            const active = location.pathname === to ||
              (to !== "/" && location.pathname.startsWith(to));
            return (
              <Link
                key={to}
                to={to}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
                title={collapsed ? label : undefined}
              >
                <Icon size={18} />
                {!collapsed && <span>{label}</span>}
              </Link>
            );
          })}
        </nav>
        <div className="border-t p-2">
          <button
            type="button"
            onClick={toggle}
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            title={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            {!collapsed && (
              <span>{theme === "dark" ? "浅色模式" : "深色模式"}</span>
            )}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="min-w-0 flex-1 overflow-auto pt-28 md:pt-0">
        <div className="mx-auto max-w-[1600px] p-4 sm:p-6">{children}</div>
      </main>
    </div>
  );
}
