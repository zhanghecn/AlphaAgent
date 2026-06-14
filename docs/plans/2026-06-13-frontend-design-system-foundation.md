# AlphaAgent 前端设计系统 v2 — 地基方案

> 日期：2026-06-13
> 范围：前端设计系统（Design System）地基，不动业务页面信息架构
> 参考：`~/project/ai/sub2api`（Vue3 SaaS 仪表盘观感，仅借鉴视觉语言，不迁移框架）

## 一、背景与动机

当前 AlphaAgent 前端（React 18 + Tailwind 3.4 + shadcn 风格）视觉偏"素净扁平"：

- 黑白灰、HSL CSS 变量驱动，品牌色是近黑深蓝（`--primary: 222.2 47.4% 11.2%`）
- `src/styles.css` 仅 89 行，自定义视觉很薄
- 深色模式只有 `darkMode:'class'` 开关，**没有完整深色色阶**
- 三套图表库（echarts / lightweight-charts / recharts）主题**散落各组件**，不统一
- 基础组件 `components/ui/` 仅 6 个（button/badge/input/skeleton/table/tabs），缺 card 等核心件

用户希望移植参考项目 `sub2api` 的"精致 SaaS 仪表盘"观感，使界面更直观、更有高级感，同时适配量化前端的数据密度需求。

经勘察确认：sub2api（实际是 AI API 网关平台，非股票产品）的视觉精髓 = 青色(teal)品牌 + 毛玻璃 `glass` 阴影 + `glow` 辉光 + `mesh-gradient` 网格渐变背景 + 丰富动画（shimmer/glow/fade/scale）+ 大圆角。**这些效果完全来自 Tailwind CSS，与 React/Vue 框架无关**，因此无需迁移框架。

## 二、锁定决策

| # | 决策点 | 选择 | 理由 |
|---|---|---|---|
| 1 | 框架 | 保留 React 18 + Tailwind | sub2api 视觉本质是 Tailwind；迁 Vue3 需重写 ~18000 行 + 重对接 API + 丢弃 lightweight-charts(K线)/xyflow(产业链)，得不偿失 |
| 2 | 切入点 | 先建设计系统地基 | 保证全站一致性，避免逐页改返工（DRY） |
| 3 | 品牌主色 | 靛蓝 indigo `#3b82f6 → #6366f1` | 金融科技标配，与 A 股涨红跌绿**零冲突**。sub2api 原青色 `#14b8a6` 偏绿，会与"跌/亏损绿"混淆 |
| 4 | 视觉浓度 | 克制专业 | 量化前端核心是数据可读性，背景太花干扰看盘/读回测数 |

## 三、不可破坏约束（A 股生命线）

- `text-rise`(红 `#ef4444`) / `text-fall`(绿 `#22c55e`) **神圣保留**，indigo 仅做品牌/操作色，绝不侵占涨跌语义
- K 线图（lightweight-charts）涨红跌绿不变
- 圆角统一 lg/xl（0.75~1rem），不上 2rem+ 大圆角（克制）
- 无满屏 `mesh-gradient` / `glow` 呼吸动画；辉光仅用于强调态（选中 / 活跃 / 悬停 KPI）

## 四、五层地基设计

```
┌─ 5. 仪表盘原语层 ─ StatCard(KPI)/SectionCard/DataSkeleton(shimmer) ─┐
├─ 4. 图表主题层 ─── echarts/lightweight-charts/recharts 共享 theme ──┤
├─ 3. 基础组件层 ─── ui/ 重配色 6 个 + 补 card/tooltip/separator ──────┤
├─ 2. 主题切换 ───── ThemeProvider(class+localStorage) + 日夜开关 ─────┤
└─ 1. Design Tokens ─ tailwind.config.ts + styles.css :root/.dark ────┘
```

### 第 1 层：Design Tokens

**`tailwind.config.ts` 扩展**（在现有 shadcn 配置上追加，不改既有结构）：

```ts
colors: {
  brand: {                       // indigo 全色阶（品牌主色）
    50:'#eef2ff',100:'#e0e7ff',200:'#c7d2fe',300:'#a5b4fc',400:'#818cf8',
    500:'#6366f1',600:'#4f46e5',700:'#4338ca',800:'#3730a3',900:'#312e81',950:'#1e1b4b',
  },
  ink: {                         // slate 全色阶（深色模式背景）
    50:'#f8fafc',100:'#f1f5f9',200:'#e2e8f0',300:'#cbd5e1',400:'#94a3b8',
    500:'#64748b',600:'#475569',700:'#334155',800:'#1e293b',900:'#0f172a',950:'#020617',
  },
},
boxShadow: {
  card:         '0 1px 3px rgba(0,0,0,.04), 0 1px 2px rgba(0,0,0,.06)',
  'card-hover': '0 10px 40px rgba(0,0,0,.08)',
  glow:         '0 0 20px rgba(99,102,241,.20)',          // indigo 辉光，强调态用
  'inner-glow': 'inset 0 1px 0 rgba(255,255,255,.06)',
},
backgroundImage: {
  'gradient-brand': 'linear-gradient(135deg,#3b82f6 0%,#6366f1 100%)',
  // 不引入 mesh-gradient 全局背景（克制浓度）
},
animation: { 'fade-in','slide-up','slide-down','slide-in-right','scale-in','shimmer' },
keyframes:  { fadeIn/slideUp/slideDown/slideInRight/scaleIn/shimmer },
borderRadius: { xl:'0.75rem', '2xl':'1rem' },   // 保留 shadcn radius，新增
```

**`src/styles.css` 重写 `:root` + 新增 `.dark`**：
- `--primary` 改为 indigo HSL（`243 75% 59%` ≈ `#4f46e5`），`--ring` 同步；其余 shadcn 变量保留
- 新增 `.dark { ... }` 块，给出深色 background/foreground/card/border/muted（slate 系）
- `text-rise`/`text-fall`/`bg-rise`/`bg-fall`/`concept-tag`/`rank-badge` **原样保留**

### 第 2 层：主题切换

- 新增 `src/theme/ThemeProvider.tsx`：`<html class="dark">` 切换 + `localStorage` 持久化 + 首次跟随系统偏好
- 新增 `src/theme/useTheme.ts`（`{ theme, setTheme, toggle }`）
- `main.tsx` 包裹 `<ThemeProvider>`
- `AppShell.tsx` 侧边栏底部加日/夜切换按钮（lucide `Sun`/`Moon`），默认浅色

### 第 3 层：基础组件层 `components/ui/`

- **重配色现有 6 个**（button/badge/input/skeleton/table/tabs）套用 indigo + 新圆角/阴影
- **补全缺失**：`card`（Card/CardHeader/CardTitle/CardContent/CardFooter）、`tooltip`、`separator`
- Button 新增 `brand` 变体：`bg-gradient-brand` + `shadow-card` + `hover:shadow-card-hover` + `active:scale-[.98]`

### 第 4 层：图表主题层 `lib/chart-theme.ts`

抽出统一主题常量，三库各适配一份：
- 主色 `#6366f1`、涨 `#ef4444`、跌 `#22c55e`、网格/文字 slate
- 导出 `echartsTheme`、`lightweightChartOptions()`、`rechartsTheme`
- `useChartColors()` hook：按深浅模式返回对应色
- 改造 `StockKlineChart` / `StockFinanceChart` / `HoldingMiniChart` 接入

### 第 5 层：仪表盘原语层 `components/dashboard/`

- `StatCard`：KPI 卡（标题 + 大数字 + 涨跌徽章 + 可选 sparkline），`hover:-translate-y-0.5` 微抬升
- `SectionCard`：带标题/操作区的区块容器（统一页面骨架）
- `DataSkeleton`：shimmer 加载态
- 作为后续"信息架构仪表盘化"阶段的积木，本轮先建好供页面逐步采用

## 五、改动范围 / 不碰范围

**改**：
- `tailwind.config.ts`、`src/styles.css`
- 新增 `src/theme/`（Provider + hook）
- 补 `src/components/ui/`（card/tooltip/separator）+ 重配色现有 6 个
- 新增 `src/lib/chart-theme.ts`
- 新增 `src/components/dashboard/`（StatCard/SectionCard/DataSkeleton）
- `AppShell.tsx`（加主题按钮）、`main.tsx`（包 Provider）
- 3 个图表组件接入新主题

**不碰**：
- 业务页面与 feature 组件主体（`pages/`、`features/`）—— 靠 token 自动继承新风格
- `vnpy/` 后端、API 层不动
- 信息架构 / 页面布局重构（留作下一阶段，不在本地基范围内）

## 六、验证方式

- `pnpm build`（`tsc -b && vite build`）通过，无类型错误
- 浅/深模式切换正常，刷新后保持
- 首页 / 量化页视觉继承新风格（token 自动生效），涨跌色仍正确（红涨绿跌）
- 三套图表在新主题下颜色一致、深色模式可读
- 关键页面手动抽查：今日市场、量化交易、个股详情、产业链

## 七、风险与边界

- 深色模式全局铺开后，部分已有自定义类（concept-tag/rank-badge/sector-detail-panel）在深色下对比度可能不足 → 本轮先开通深色能力，页面级深色瑕疵留作小修
- 三套图表库配置 API 差异较大，统一主题不强求 API 一致，只保证视觉色一致
- 本地基**不重构页面信息架构**；"仪表盘化布局重构"作为独立的下一阶段推进
