import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ADMIN_SESSION_QUERY_KEY, apiClient, authToken } from "@/api/client";

/**
 * 管理员登录页。
 * 视觉延续 AppShell 的「玻璃 + 极光」语言：glass.aurora 卡片 + 金色氛围光晕。
 * 签名元素是标题上方的迷你走势线 mark——量化研究终端独有的视觉记号。
 */
export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    try {
      const data = await apiClient.post<{ token: string; username: string }>("/auth/login", { username, password });
      authToken.set(data.token);
      queryClient.setQueryData(ADMIN_SESSION_QUERY_KEY, {
        authenticated: true,
        username: data.username,
      });
      toast({ title: "已登录", variant: "success" });
      navigate("/", { replace: true });
    } catch (err) {
      toast({
        title: "登录失败",
        description: err instanceof Error ? err.message : "请检查用户名和密码",
        variant: "error",
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background p-4">
      {/* 氛围光晕：两团金色模糊圆，呼应 AppShell 极光语言；primary 跟随主题深浅。 */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[28rem] w-[28rem] -translate-x-1/2 rounded-full blur-3xl"
        style={{ backgroundColor: "hsl(var(--primary) / 0.16)" }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-32 right-[-5rem] h-80 w-80 rounded-full blur-3xl"
        style={{ backgroundColor: "hsl(var(--primary) / 0.08)" }}
      />

      <Card className="glass aurora relative z-10 w-full max-w-sm rounded-2xl">
        <div className="flex flex-col items-center gap-3 px-6 pb-1 pt-8">
          <SparkMark />
          <div className="text-center">
            <h1 className="font-display text-2xl font-bold tracking-tight">AlphaAgent</h1>
            <p className="mt-1 text-sm text-muted-foreground">A 股量化研究终端</p>
          </div>
        </div>

        <CardContent className="pt-5">
          <form onSubmit={handleSubmit} className="space-y-3">
            <div className="space-y-1.5">
              <label htmlFor="login-username" className="text-xs font-medium text-muted-foreground">
                用户名
              </label>
              <Input
                id="login-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="请输入用户名"
                autoComplete="username"
                autoFocus
                required
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="login-password" className="text-xs font-medium text-muted-foreground">
                密码
              </label>
              <Input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="请输入密码"
                autoComplete="current-password"
                required
              />
            </div>
            <Button type="submit" variant="brand" className="mt-1 w-full" disabled={loading}>
              {loading ? "登录中…" : "登录"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

/** 签名元素：迷你走势线 mark。量化系统的视觉记号，brand 渐变描边。 */
function SparkMark() {
  return (
    <div
      className="flex h-12 w-12 items-center justify-center rounded-xl"
      style={{
        backgroundColor: "hsl(var(--primary) / 0.10)",
        boxShadow: "inset 0 0 0 1px hsl(var(--primary) / 0.22)",
      }}
    >
      <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden>
        <path
          d="M2.5 18 L7 14 L11 16 L15 8 L19 11 L23.5 4.5"
          stroke="url(#spark-grad)"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="23.5" cy="4.5" r="2" fill="hsl(var(--primary))" />
        <defs>
          <linearGradient id="spark-grad" x1="2.5" y1="18" x2="23.5" y2="4.5" gradientUnits="userSpaceOnUse">
            <stop stopColor="hsl(var(--primary))" />
            <stop offset="1" stopColor="hsl(var(--primary) / 0.55)" />
          </linearGradient>
        </defs>
      </svg>
    </div>
  );
}
