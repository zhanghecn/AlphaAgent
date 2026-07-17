# AlphaAgent 大盘择时 v9 金手指失效银实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在趋势金再启动被宽基急跌明确否决时，于失败日因果地产生银手指并切换持续方向。

**Architecture:** `signal.py` 先按 v8 生成原始事件，再从已存在的趋势金候选和下一交易日可见数据派生一个优先级更高的 `GOLD_FAILURE_SILVER`。前端只增加 setup 类型与说明，持续金银状态继续复用 `active_direction`，不增加新的公开方向枚举。

**Tech Stack:** Python 3.13、pytest、React 18、TypeScript、Vitest、Docker Compose、Playwright CLI。

---

### Task 1: 用测试固定失败银的因果边界

**Files:**
- Modify: `tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py`
- Modify: `tests/alphaagent/services/market_timing/test_market_timing_intraday.py`

- [ ] **Step 1: 添加趋势金失败生成银手指测试**

构造三天因子：首日 `bull_force=70` 进入趋势金，次日综合指数跌幅不高于
`-2%`、`up_ratio=0`、`bull_force<60` 且 `bear_force>=bull_force`。断言首日
事件为 `TREND_GOLD / INVALIDATED`，次日事件为
`GOLD_FAILURE_SILVER / CONFIRMED`，且 `trade_date == confirm_date`。

- [ ] **Step 2: 添加反转金与弱失败不触发测试**

分别验证 `REVERSAL_GOLD` 否决、参与度缺失、跌幅不足、多头仍高于 60、空头未
反超时都不会生成失败银。

- [ ] **Step 3: 添加前缀稳定和确认截止测试**

截断到候选日时不得存在失败银；加入失败日后才新增失败日事件；篡改再下一日数据
不能改变既有事件。`confirmed_through` 截止候选日时，失败银必须为 `PENDING`
且不能切换 `active_direction`。

- [ ] **Step 4: 运行失败测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py \
  tests/alphaagent/services/market_timing/test_market_timing_intraday.py -q
```

Expected: 新断言因缺少 `GOLD_FAILURE_SILVER` 失败，既有测试继续通过。

### Task 2: 实现最小失败银派生层

**Files:**
- Modify: `alphaagent/server/services/market_timing/signal.py`

- [ ] **Step 1: 增加 setup 和固定门槛**

增加 `SETUP_GOLD_FAILURE_SILVER`、`GOLD_FAILURE_RETURN_MAX=-2.0` 和
`GOLD_FAILURE_UP_RATIO_MAX=0.25`。多头门槛复用 `GOLD_ENTER`，不增加重复常量。

- [ ] **Step 2: 增加纯失败判断函数**

函数只接收候选 setup、候选/失败日收盘、失败日因子和失败日 `up_ratio`。它不读取
失败日之后的数据，并在输入不对齐或参与度缺失时返回 `False`。

- [ ] **Step 3: 在原始事件检测后派生失败银**

只从 `TREND_GOLD` 候选的下一交易日派生失败银。已完成日线输出
`CONFIRMED` 和同日 `confirm_date`；超过 `confirmed_through` 时输出
`PENDING`。失败银覆盖同日其他普通候选事件，随后按日期排序。

- [ ] **Step 4: 运行市场择时后端测试**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/services/market_timing/test_market_timing_backtest.py \
  tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py \
  tests/alphaagent/services/market_timing/test_market_timing_intraday.py -q
```

Expected: PASS。

### Task 3: 补齐前端 setup 类型和文案

**Files:**
- Modify: `frontend/src/api/marketTiming.ts`
- Modify: `frontend/src/features/market-timing/timingPresentation.ts`
- Modify: `frontend/src/features/market-timing/timingPresentation.spec.ts`

- [ ] **Step 1: 先增加失败的 setup 文案断言**

```ts
expect(timingSetupLabel("GOLD_FAILURE_SILVER")).toBe("金手指失效银手指");
```

- [ ] **Step 2: 扩展 `TimingSetupType` 和标签映射**

新增 `GOLD_FAILURE_SILVER`，不修改 `TimingDirection`、图标或金银颜色。

- [ ] **Step 3: 运行前端测试和构建**

Run:

```bash
pnpm --dir frontend test
pnpm --dir frontend run build
```

Expected: 全部测试与生产构建通过。

### Task 4: 真实数据回测和无未来审计

**Files:**
- Modify: `memory/07_market_timing/market_timing_design.md`

- [ ] **Step 1: 在 API 容器运行现有评估脚本**

Run:

```bash
docker compose exec -T alphaagent-api python - < scripts/market_timing_eval.py
```

Expected: 原有 64 个事件保持，只新增 1 个失败银；金候选 55 个不变，银候选变为
10 个。确认和候选表现按真实输出记录，不人工修饰。

- [ ] **Step 2: 核对关键事件签名和日期**

读取真实计算结果，断言 6 月 11 日反转金未变、7 月 1 日趋势金仍被否决、
7 月 2 日新增确认失败银、最新 `active_direction=SILVER`。

- [ ] **Step 3: 更新项目记忆**

在现有市场择时记忆中替换 v8 最新方向和事件统计，记录样本限制、回测口径、测试
命令和新提交，不追加聊天式过程记录。

### Task 5: 重建、刷新和页面验收

**Files:**
- No source changes expected.

- [ ] **Step 1: 重建 API 与 Web**

```bash
docker compose up --build -d alphaagent-api alphaagent-web
```

- [ ] **Step 2: 强制刷新市场择时面板**

```text
POST /api/market-timing/refresh
```

通过本地已配置管理员登录执行，不输出凭据。断言返回 200，随后读取真实 panel。

- [ ] **Step 3: 用 Playwright 验收桌面和手机**

在 `1440x1000` 与 `390x844` 精确悬停 `2026-07-02`，断言：

- 日期为 `2026-07-02`。
- 手指状态为“银手指延续”。
- 当日新手指为“银手指确认”。
- 7 月 2 日画银箭头，不画金箭头。
- 最新 7 月 15 日仍为“银手指延续”。
- 页面无横向溢出，控制台 0 错误、0 警告。

- [ ] **Step 4: 提交相关文件**

只暂存市场择时后端、测试、前端类型/标签、requirements 和 memory 文件，不纳入
涨停提醒等并行未提交改动。
