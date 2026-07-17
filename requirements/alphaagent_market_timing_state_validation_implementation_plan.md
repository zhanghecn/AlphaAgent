# AlphaAgent 金银手指持续状态验证实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立逐日持续金银状态的因果评估，并用同一数据口径比较 v8、v9 和研究用波动迟滞版本。

**Architecture:** `backtest.py` 增加纯状态评估与研究状态构造函数；现有评估脚本负责从真实事件构造三个版本并打印对照；生产 `signal.py`、panel API 和前端均不改动。

**Tech Stack:** Python 3.13、标准库 dataclass/statistics、pytest、PostgreSQL 真实行情、现有 Docker Compose。

---

### Task 1: 固定状态评估指标

**Files:**
- Modify: `tests/alphaagent/services/market_timing/test_market_timing_backtest.py`

- [x] **Step 1: 添加逐日状态桶测试**

用可手算的收盘序列和金银状态断言 `1/3/5` 日收益、方向命中、方向收益、
不利波动和 `adverse_3pct`。测试必须包含金和银，避免只验证方向翻转公式的一侧。

- [x] **Step 2: 添加时间切分测试**

指定 `split_date`，断言 `ALL/EARLY/LATE` 的状态日数和结果来自正确日期，边界日
属于 `LATE`。

- [x] **Step 3: 添加状态区间测试**

构造 `NEUTRAL → GOLD → SILVER → GOLD`，断言覆盖天数、区间数、平均长度、
转换次数和不超过 3 日的短区间数。

- [x] **Step 4: 运行测试确认缺少实现**

```bash
uv run --group server pytest tests/alphaagent/services/market_timing/test_market_timing_backtest.py -q
```

Expected: 新测试因缺少状态评估接口失败。

### Task 2: 实现纯状态评估

**Files:**
- Modify: `alphaagent/server/services/market_timing/backtest.py`

- [x] **Step 1: 增加 `STATE_HORIZONS` 和 `StateBucketStat`**

固定周期为 `(1, 3, 5, 10, 20)`；数据类包含 period、direction、horizon、count、
hit_rate、avg_return、avg_directional_return、avg_adverse_excursion、
worst_adverse_excursion、adverse_3pct_rate。

- [x] **Step 2: 实现 `evaluate_direction_states`**

要求状态和 bar 等长；空输入返回空报告，长度不一致抛 `ValueError`。函数只使用
未来价格生成标签，并输出 `ALL/EARLY/LATE` 桶和 `executable=false`。

- [x] **Step 3: 实现状态运行统计**

忽略首个确认前的中性，按连续金银区间统计覆盖、运行长度、转换和短区间。

- [x] **Step 4: 运行状态评估测试**

Expected: PASS。

### Task 3: 固定研究迟滞版本的因果行为

**Files:**
- Modify: `tests/alphaagent/services/market_timing/test_market_timing_backtest.py`
- Modify: `alphaagent/server/services/market_timing/backtest.py`

- [x] **Step 1: 添加波动冲击与趋势破位测试**

分别构造满足 A、B 分支的金状态日，断言只从该日开始切银。参与度缺失、空头未
反超、动量非负时不得切换。

- [x] **Step 2: 添加确认金恢复和前缀稳定测试**

银状态只在已确认金事件到达时恢复；污染未来 bar 和 factor 后，切分日前状态完全
不变。

- [x] **Step 3: 实现 `build_volatility_hysteresis_directions`**

输入 factors、bars 和 v8 确认事件，验证日期及长度对齐。波动率只使用当前日前
20 日收益；基础确认事件先更新方向，再判断当日金转银保护。

- [x] **Step 4: 运行全部市场择时测试**

```bash
uv run --group server pytest \
  tests/alphaagent/services/market_timing/test_market_timing_backtest.py \
  tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py \
  tests/alphaagent/services/market_timing/test_market_timing_intraday.py -q
```

Expected: PASS。

### Task 4: 扩展真实评估脚本

**Files:**
- Modify: `scripts/market_timing_eval.py`

- [x] **Step 1: 构造三个状态版本**

`v8` 排除 `GOLD_FAILURE_SILVER`，`v9` 使用全部事件，`VOL_HYSTERESIS` 使用 v8
确认事件加研究保护。断言三个状态序列与 bar 等长。

- [x] **Step 2: 打印状态运行摘要和 5 日核心表**

输出各版本 `ALL/EARLY/LATE` 的金银 5 日命中率、平均收益、3% 不利波动率，
以及覆盖天数、转换和短区间数。详细 1/3/5/10/20 日结果保留在返回结构中供报告
提取。

- [x] **Step 3: 运行真实脚本**

```bash
docker compose exec -T alphaagent-api python - < scripts/market_timing_eval.py
```

Expected: 事件报告仍为 v9 的 65 个事件，随后出现三版本状态对照，不修改数据库。

### Task 5: 生成证据与完成回归

**Files:**
- Create: `memory/06_backtests/market_timing_state_validation_2026_07_15.md`
- Modify: `memory/07_market_timing/market_timing_design.md`

- [x] **Step 1: 写入真实对照报告**

报告记录数据区间、三版本定义、完整核心统计、时间切分结果、是否达到决策标准和
样本限制。不得只写结论而省略失败指标。

- [x] **Step 2: 更新概览记忆**

只加入当前结论、验证命令和详细报告链接；生产 v9 若未变，明确写“未修改”。

- [x] **Step 3: 最终验证**

```bash
uv run --group server pytest \
  tests/alphaagent/services/market_timing/test_market_timing_backtest.py \
  tests/alphaagent/services/market_timing/test_market_timing_no_lookahead.py \
  tests/alphaagent/services/market_timing/test_market_timing_intraday.py -q
pnpm --dir frontend test
pnpm --dir frontend run build
git diff --check
```

- [x] **Step 4: 提交**

只暂存市场择时 backtest、测试、评估脚本、requirements 和 memory 文件，不纳入
其他并行需求文件。
