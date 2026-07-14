import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  Database,
  LayoutDashboard,
  Activity,
  Briefcase,
  History,
  TrendingUp,
  Crosshair,
  ChevronLeft,
  ChevronRight,
  Sun,
  Moon,
  LogOut,
  Flame,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/theme/useTheme";
import { apiClient, authToken } from "@/api/client";
import { VersionBadge } from "@/components/VersionBadge";

const NAV_ITEMS = [
  { to: "/", label: "今日市场", icon: LayoutDashboard },
  { to: "/market", label: "大盘择时", icon: Crosshair },
  { to: "/mainline", label: "概念主线", icon: History },
  { to: "/limit-up", label: "打板研究", icon: Flame },
  { to: "/stocks", label: "全 A 股票", icon: TrendingUp },
  { to: "/quant", label: "量化交易", icon: Activity },
  { to: "/portfolio", label: "持仓", icon: Briefcase },
  { to: "/data", label: "数据管理", icon: Database },
];

function isActive(pathname: string, to: string): boolean {
  return pathname === to || (to !== "/" && pathname.startsWith(to));
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const { theme, toggle } = useTheme();

  const handleLogout = async () => {
    try {
      await apiClient.post("/auth/logout");
    } catch {
      // 忽略：前端清除 token 即可完成登出。
    }
    authToken.clear();
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex min-h-screen bg-background md:h-screen md:overflow-hidden">
      {/* Mobile top nav —— 玻璃质感 + 极光顶光晕（视觉保留，无动画） */}
      <header className="glass aurora !fixed inset-x-0 top-0 z-30 border-b md:hidden">
        <div className="flex h-14 items-center justify-between px-4">
          <span className="font-display text-lg font-bold tracking-tight">AlphaAgent</span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={toggle}
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              title={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
              aria-label="切换深浅色主题"
            >
              {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
            </button>
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
              title="退出登录"
              aria-label="退出登录"
            >
              <LogOut size={20} />
            </button>
          </div>
        </div>
        <nav className="grid grid-cols-4 gap-1 px-2 pb-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => {
            const active = isActive(location.pathname, to);
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

      {/* Sidebar —— 宽度折叠用 CSS transition，active 用 className 切换 */}
      <aside
        className={cn(
          "hidden flex-col border-r bg-card transition-[width] duration-300 ease-spring md:flex",
          collapsed ? "w-16" : "w-56",
        )}
      >
        <div className="aurora relative flex h-14 items-center border-b px-4">
          {!collapsed ? (
            <div className="flex flex-col leading-none">
              <span className="font-display text-lg font-bold tracking-tight">AlphaAgent</span>
              <VersionBadge />
            </div>
          ) : (
            <VersionBadge />
          )}
          <button
            type="button"
            className={cn(
              "ml-auto rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
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
            const active = isActive(location.pathname, to);
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
          <button
            type="button"
            onClick={handleLogout}
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
            title="退出登录"
          >
            <LogOut size={18} />
            {!collapsed && <span>退出登录</span>}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="min-w-0 flex-1 overflow-auto pt-36 md:pt-0">
        <div className="mx-auto max-w-[1600px] p-4 sm:p-6">{children}</div>
      </main>
    </div>
  );
}
