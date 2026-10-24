# B1·转温分支级通用组 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 只让 B1·转温跨行情常开，贯通回测、实时、扫描、答题和规则页；续强及其他口诀判定完全不变。

**Architecture:** `contracts` 增加整点/分支两级通用判定和统一 `dyn_take_point`。回测事件保存强市分支名，实时与扫描复用同一份候选分支及今开窗；B1 的动态成绩和健康度按分支展示。产品契约是唯一事实源，旧研究文档不再作为现行规则。

**Tech Stack:** Python 3.13、pandas、pytest、React/TypeScript、Vitest、Docker Compose。

**约束:** 不改 B1 条件与阈值、不改切换器、不新建分支；先测试后实现，所有数字以 v7.19 已复核事件为基线。全部验收完成后，按主人 2026-10-24 的明确授权提交并 push 到 `master`。

---

### Task 1: 分支级通用判定与失败测试

**Files:**
- Create: `tests/alphaagent/services/high_relay/test_common_schemes.py`
- Modify: `alphaagent/server/services/high_relay/contracts.py`

**Step 1: 写失败测试**

覆盖：
```python
assert contracts.dyn_take_point("weak", "B1", "—", "转温") == "B1"
assert contracts.dyn_take_point("weak", "B1", "—", "续强") == ""
assert contracts.dyn_take_point("strong", "B1", "—", "续强") == "B1"
assert contracts.dyn_take_point("strong", "—", "K5") == "K5"
```
再覆盖候选分支过滤：B1 转温在今开 4 时保留、今开 7 时排除，续强任何行情都不因通用清单放行。

**Step 2: 运行并确认失败**

Run: `uv run pytest tests/alphaagent/services/high_relay/test_common_schemes.py -q`
Expected: FAIL，缺少 `dyn_take_point` / `common_scheme_candidates`。

**Step 3: 最小实现**

新增：
```python
COMMON_POINT_KEYS = ("K5",)
COMMON_BRANCH_KEYS = (("B1", "转温"),)
```
实现 `is_common_scheme`、`common_scheme_candidates`、`common_scheme_labels`、`dyn_take_point`。优先级：通用弱市整点 → 通用强市分支 → 当月 strong/weak/both；不得把 B1 整点视为通用。

**Step 4: 运行测试确认通过**

Run: 同 Step 2。
Expected: 新增判定测试 PASS。

### Task 2: 回测、实时、扫描和答题贯通

**Files:**
- Modify: `alphaagent/server/services/high_relay/backtest.py`
- Modify: `alphaagent/server/services/high_relay/live_scan.py`
- Modify: `alphaagent/server/services/high_relay/service.py`
- Modify: `alphaagent/server/services/high_relay/quiz.py`
- Test: `tests/alphaagent/services/high_relay/test_common_schemes.py`

**Step 1: 写集成边界失败测试**

- 弱市扫描只生成 B1·转温 `today_3_5` 门，今开 7 必须 `skipped_auction`，今开 4 可继续观察。
- 服务实时行在今开 4 时识别转温通用命中，今开 7 不误判为通用命中。
- `get_rules` 的通用区只有 K5 与 B1·转温，强市区保留 B1·续强。
- `get_current_koujue` 的 B1 两分支分别显示成绩与健康组。

**Step 2: 运行并确认失败**

Run: `uv run pytest tests/alphaagent/services/high_relay -q`
Expected: 新增集成断言 FAIL，既有测试不因环境以外原因失败。

**Step 3: 最小实现**

- `build_events` 使用 `tag_scheme` 同时保存 `方案点` 与 `方案子项`。
- `_dyn_trades` 保存强市分支 `s`；月状态计算输入的 m/g/p/r 不变。
- `_dyn_take` 和题库统一调用 `contracts.dyn_take_point`。
- 弱市扫描仅拼接通用分支的今开窗；实时页同样按实际竞价过滤通用分支。
- 规则页通用/强市行按 `(no, sub)` 分区；仅 B1 的动态成绩和健康度按分支计算。
- 版本升 `hpr-v7.20`、`q53`，追加 `KOJUE_CHANGELOG`。

**Step 4: 运行后端测试**

Run: `uv run pytest tests/alphaagent/services/high_relay -q`
Expected: 全部 PASS。

### Task 3: 前端与现行文案

**Files:**
- Modify: `frontend/src/api/highRelay.ts`
- Modify: `frontend/src/features/highRelay/HprGuideView.tsx`
- Modify: `frontend/src/pages/HighRelayPage.spec.tsx`（如需分支健康样例）
- Modify: `alphaagent/server/services/high_relay/contracts.py`（RISK_NOTES 与当前注释）

**Step 1: 更新类型与展示**

- `always_on` 显示 `K5、B1·转温`。
- 通用组说明改为“成绩计入原所属组参与切换”。
- 健康项支持 `sub` 和 `common`，React key 含分支。
- 删除“K5 是唯一跨时代”“198 笔 +11.76”等旧文案；只写最新机制，易漂移数字以回测物化为准。

**Step 2: 验证**

Run: `npm --prefix frontend run test -- --run src/pages/HighRelayPage.spec.tsx`
Run: `npm --prefix frontend run build`
Expected: 测试与构建均 PASS。

### Task 4: 全量物化与产品验收

**Files:**
- Runtime: Docker Compose `alphaagent-api`、`data-sync-worker`、`web`

**Step 1: 同步代码并重建**

通过 Compose 更新本地容器；用 `run_backtest_sync(source="manual")` 全量重建 v7.20 与 q53。

**Step 2: 验证核心数字**

Expected:
- 动态组研究口径：201 → 207 笔；E3 胜率 78.1% → 78.3%；E3 均值 11.61 → 11.38。
- 可执行口径：190 → 196 笔；净增 6 笔全部可执行。
- B1 条件命中数、各分口诀研究锚点、月切换史不变。
- 新增出手：南方精工、征和工业、江苏索普、海联金汇、第一医药、岩山科技。
- 实时/扫描弱市仅放行转温 3～5，续强 6～9 不放行。

**Step 3: API 与页面检查**

检查 `/high-relay/backtest`、`/high-relay/rules`、`/high-relay/koujue/current` 和 Compose 网关页面；版本必须为 v7.20/q53，通用组为 K5+B1·转温。

### Task 5: 旧文档清理

**Files:**
- Review: `requirements/high_position_relay_*.md`
- Review: `requirements/` 与 `量化因子研究/高位接力/` 中的高位接力文档
- Review: `量化因子研究/高位接力/*.md`

**Step 1: 删除已核实的历史/失效文档**

删除含五点旧方案、K7 现役、近12月切换、K5唯一跨时代、指向不存在文件的旧文档；`archive/高位接力/` 顶层与 `汇总/` 的旧规则、旧口诀卡和研究汇总同样删除。研究脚本与 `好差票验证/` 原始案例保留，避免把代码资产、历史证据与误导性规则文档混同。

**Step 2: 保留最新资料**

保留本实施契约及能表达当前验证方法的资料；现行规则以 `contracts.py` 为唯一事实源，不复制一份容易漂移的规则全文。

**Step 3: 最终验证**

运行后端测试、前端测试/构建、物化数字断言和 `git status --short`；交付实际变更、测试输出和删除清单。验收完成后按主人明确授权提交并 push 到 `master`。
