import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

const config: Config = {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        rise: "#ef4444",
        fall: "#22c55e",
        // 品牌主色 indigo 全色阶（金融科技，与 A 股涨红跌绿零冲突）
        brand: {
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
          950: "#1e1b4b",
        },
        // 深色模式背景 slate 全色阶
        ink: {
          50: "#f8fafc",
          100: "#f1f5f9",
          200: "#e2e8f0",
          300: "#cbd5e1",
          400: "#94a3b8",
          500: "#64748b",
          600: "#475569",
          700: "#334155",
          800: "#1e293b",
          900: "#0f172a",
          950: "#020617",
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
      },
      // 字体三族：display(标题/KPI数字) / sans(正文) / mono。
      // 中文走系统 fallback（PingFang SC / 微软雅黑 / Noto Sans SC），不打包中文字体。
      fontFamily: {
        sans: [
          '"Inter Variable"',
          '"PingFang SC"',
          '"Microsoft YaHei"',
          '"Noto Sans SC"',
          "system-ui",
          "sans-serif",
        ],
        display: [
          '"Space Grotesk Variable"',
          '"Inter Variable"',
          '"PingFang SC"',
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        xl: "0.75rem",
        "2xl": "1rem",
      },
      boxShadow: {
        card: "0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.06)",
        "card-hover": "0 10px 40px rgba(0, 0, 0, 0.08)",
        glow: "0 0 20px rgba(99, 102, 241, 0.20)",
        "inner-glow": "inset 0 1px 0 rgba(255, 255, 255, 0.06)",
        // 玻璃拟态层：升力 + 内高光（浅色）
        glass:
          "0 8px 32px rgba(15, 23, 42, 0.12), inset 0 1px 0 rgba(255,255,255,0.6)",
        "glass-dark":
          "0 8px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.06)",
        // 涨跌辉光（用于脉冲/强调态，复用涨跌色）
        "rise-glow": "0 0 24px rgba(239,68,68,0.30)",
        "fall-glow": "0 0 24px rgba(34,197,94,0.30)",
        // 品牌聚焦辉光（CTA / 选中态）
        "focus-glow":
          "0 0 0 1px hsl(var(--primary) / 0.18), 0 8px 32px hsl(var(--primary) / 0.18)",
      },
      backgroundImage: {
        "gradient-brand": "linear-gradient(135deg, #3b82f6 0%, #6366f1 100%)",
        // 玻璃表面渐变（叠在 backdrop-blur 上）
        "gradient-glass":
          "linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02))",
        // 顶部极光光晕（AppShell / 卡片头）
        "gradient-aurora":
          "radial-gradient(60% 80% at 50% -20%, hsl(var(--primary) / 0.18), transparent 70%)",
        // 信号扫光（新候选信号出现时一次性掠过）
        "gradient-sweep":
          "linear-gradient(110deg, transparent 30%, rgba(255,255,255,0.45) 50%, transparent 70%)",
      },
      backdropBlur: {
        xs: "2px",
      },
      transitionTimingFunction: {
        spring: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      animation: {
        "fade-in": "fadeIn 0.3s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
        "slide-down": "slideDown 0.3s ease-out",
        "slide-in-right": "slideInRight 0.3s ease-out",
        "scale-in": "scaleIn 0.2s ease-out",
        shimmer: "shimmer 2s linear infinite",
        // 数字滚动定格
        "count-up": "count-up 0.5s cubic-bezier(0.16,1,0.3,1)",
        // 涨跌脉冲（数值变化时短暂高亮，复用涨跌色）
        "pulse-rise": "pulse-rise 1.2s ease-out",
        "pulse-fall": "pulse-fall 1.2s ease-out",
        // 信号扫光一次掠过
        "sweep-shine": "sweep-shine 1.1s ease-out",
        // 聚焦环脉冲（CTA / 强调态）
        "ring-pulse": "ring-pulse 1.6s ease-out",
        // 图标轻浮动（空态/错误态）
        float: "float 3s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideDown: {
          "0%": { opacity: "0", transform: "translateY(-10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          "0%": { opacity: "0", transform: "translateX(20px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        scaleIn: {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "count-up": {
          "0%": { opacity: "0", transform: "translateY(0.4em)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-rise": {
          "0%,100%": { backgroundColor: "transparent" },
          "35%": { backgroundColor: "hsl(0 84% 60% / 0.18)" },
        },
        "pulse-fall": {
          "0%,100%": { backgroundColor: "transparent" },
          "35%": { backgroundColor: "hsl(142 71% 45% / 0.18)" },
        },
        "sweep-shine": {
          "0%": { backgroundPosition: "-150% 0" },
          "100%": { backgroundPosition: "250% 0" },
        },
        "ring-pulse": {
          "0%,100%": { boxShadow: "0 0 0 0 hsl(var(--primary)/0.45)" },
          "70%": { boxShadow: "0 0 0 8px transparent" },
        },
        float: {
          "0%,100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-4px)" },
        },
      },
    },
  },
  plugins: [tailwindcssAnimate],
};

export default config;
