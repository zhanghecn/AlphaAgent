# AlphaAgent 打板买点涨幅与提醒 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` inline. This repository task must not dispatch subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/limit-up` 实时买点中显示点时涨幅，并提供可启停、可手动测试且不会被轮询重复触发的声音和浏览器通知。

**Architecture:** 后端 `live_policy._signal()` 透传当前价和涨幅。前端用独立纯函数维护“当前触发集合 + 每股最近提醒时间”，React hook 只负责浏览器存储、声音和 Notification 副作用，页面只渲染两个图标控制和点时行情。

**Tech Stack:** Python 3.13、pytest、React 18、TypeScript、Vitest、Web Audio API、Web Notifications、Docker Compose。

---

### Task 1: 透传信号时点行情

**Files:**
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `alphaagent/server/services/limit_up/live_policy.py`
- Modify: `frontend/src/api/limitUp.ts`

- [x] **Step 1: 写失败测试**

在现有实时推荐测试中断言候选当时值原样进入 signal：

```python
assert signal["last_price"] == candidate["last_price"]
assert signal["change_pct"] == candidate["change_pct"]
```

- [x] **Step 2: 验证旧实现失败**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k "point_in_time_quote"
```

Expected: FAIL，旧 `_signal()` 没有 `last_price/change_pct`。

- [x] **Step 3: 最小实现**

在 `_signal()` 的点时字段中增加：

```python
"last_price": _number(candidate.get("last_price")),
"change_pct": _number(candidate.get("change_pct")),
```

并在 `LimitUpLiveSignal` 增加：

```ts
last_price?: number | null;
change_pct?: number | null;
```

- [x] **Step 4: 运行后端定向回归**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k "point_in_time_quote or live_first_board"
```

Expected: PASS。

### Task 2: 提醒状态机与浏览器适配

**Files:**
- Create: `frontend/src/features/limitUp/buyAlert.ts`
- Create: `frontend/src/features/limitUp/buyAlert.spec.ts`
- Create: `frontend/src/features/limitUp/useBuyAlerts.ts`

- [x] **Step 1: 写纯函数失败测试**

覆盖以下固定行为：

```ts
expect(evaluateBuyAlerts(liveSnapshot, emptyState, now, true).alerts).toHaveLength(1);
expect(evaluateBuyAlerts(liveSnapshot, activeState, now + 10_000, true).alerts).toHaveLength(0);
expect(evaluateBuyAlerts(staleSnapshot, emptyState, now, true).alerts).toHaveLength(0);
expect(evaluateBuyAlerts(nextSessionSnapshot, emptyState, now, true).alerts).toHaveLength(0);
expect(evaluateBuyAlerts(reenteredSnapshot, inactiveState, now + 61_000, true).alerts).toHaveLength(1);
```

同时验证通知正文包含股票、现涨、距板和战法，停用时只推进当前触发集合、不产生提醒。

- [x] **Step 2: 验证测试失败**

```bash
pnpm --dir frontend test -- --run frontend/src/features/limitUp/buyAlert.spec.ts
```

Expected: FAIL，模块尚不存在。

- [x] **Step 3: 实现纯状态机**

`buyAlert.ts` 固定导出：

```ts
export const BUY_ALERT_REENTRY_COOLDOWN_MS = 60_000;
export interface BuyAlertState {
  tradeDate: string;
  activeSymbols: string[];
  lastAlertAt: Record<string, number>;
}
export function evaluateBuyAlerts(
  snapshot: LimitUpSignalSnapshot | undefined,
  previous: BuyAlertState,
  now: number,
  enabled: boolean,
): { state: BuyAlertState; alerts: LimitUpLiveSignal[] };
export function buyAlertContent(signal: LimitUpLiveSignal): { title: string; body: string };
```

只有 live、非 stale、`trigger_ready/actionable` 信号进入当前集合；非法全局快照保持旧状态，
合法快照中离开集合的股票才算退出。交易日变化时清空旧日集合和时间。

- [x] **Step 4: 实现浏览器 hook**

`useBuyAlerts.ts` 返回：

```ts
{
  enabled: boolean;
  permission: NotificationPermission | "unsupported";
  toggle: () => Promise<BuyAlertPermission>;
  test: () => Promise<BuyAlertPermission>;
}
```

使用 `localStorage` 保存启停和 `BuyAlertState`；使用 Web Audio API 生成短双音；只有权限
为 `granted` 时创建 Notification。`test()` 与真实买点复用同一个声音/通知发送函数，
Notification 点击时执行 `window.focus()`；所有浏览器能力失败均捕获，不影响页面轮询。

- [x] **Step 5: 运行前端定向测试**

```bash
pnpm --dir frontend test -- --run frontend/src/features/limitUp/buyAlert.spec.ts frontend/src/features/limitUp/livePortfolio.spec.ts
```

Expected: PASS。

### Task 3: 接入精简页面并部署

**Files:**
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`

- [x] **Step 1: 接入提醒控制**

在实时页标题右侧增加 `Bell/BellRing` 启停按钮；启用后显示 `Volume2` 测试按钮。两个按钮
使用现有 36px 图标按钮、`title`、`aria-pressed` 和 `aria-label`，不增加设置卡片。切换和
测试结果使用现有 `useToast()` 明确显示“声音已开启 / 桌面通知已授权或未授权 / 测试已发送”。

- [x] **Step 2: 显示当前涨幅**

在 `LiveSignalRow` 状态列显示：

```tsx
<span className={cn("font-semibold", amountTone(signal.change_pct))}>
  现涨 {formatPct(signal.change_pct)}
</span>
<span>现价 {formatPrice(signal.last_price)}</span>
<span>距板 {formatPct(signal.distance_to_limit_pct)}</span>
```

保持移动端换行，不改变买点卡片高度的固定布局规则，不用最终封板结果补值。

- [x] **Step 3: 更新当前运行事实**

在现有数据流和运行文档中记录：点时涨幅来自实时 signal；提醒是浏览器本地能力；页面关闭
后无后台推送；手动测试不写实时快照、不产生交易或回测记录。

- [x] **Step 4: 完整验证**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_*.py -q
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
python -m compileall -q alphaagent/server/services/limit_up tests/alphaagent
git diff --check
```

Expected: 全部 PASS；生产构建只允许现有 chunk size 警告。

- [x] **Step 5: 部署并验证**

```bash
docker compose up -d --build alphaagent-web
docker compose ps
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8080/limit-up
```

Expected: API/Gateway/PostgreSQL/Redis healthy，Web 已启动，页面返回 200。本任务不提交 Git。

实际结果：扩展后端回归 `614 passed`、前端 `54 passed`；Python 编译、TypeScript/生产
构建和 `git diff --check` 通过。API 与 Web 镜像已重建，服务 healthy，页面返回 200。
Playwright 在桌面与 `390x844` 验证了“现涨/现价/距板”、铃铛、测试按钮和 Toast；
通知权限为 `granted`，手动测试成功且控制台无错误。
