# 高位接力隐藏范围特征研究计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不降低现有高位接力口诀质量的前提下，优先寻找能够增加交易数的新口诀，其次寻找能跨年份减少亏损的简单条件，并检验合并与跨行情通用化的可能。

**Architecture:** 研究样本、涨停判定和 E3 收益全部复用 `backtest.build_events()`，不重新实现生产判定。新增特征只使用买入日开盘前或买入时已经知道的数据；2020—2024 年用于发现，2025 年用于验证，2026 年保留为最终测试，最终测试前冻结候选条件。

**Tech Stack:** Python、Pandas、NumPy、PostgreSQL、现有 AlphaAgent 高位接力回测代码。

---

## 研究范围与验收标准

- 研究时基线为 `hpr-v7.20`；现行版本已升级为 `hpr-v7.21`。强市八条、弱市五条、通用组 K5 与 B1·转温均按当前代码判定，历史候选必须按新版本重新回放后才能引用。
- 2024-12 连续四笔亏损只作为研究入口：粤传媒、李子园、北纬科技、国星光电；不拿四笔直接推规则。
- 新增口诀：正常开盘、当前未出手样本中的净新增交易；总样本至少 10 笔，胜率至少 60%，E3 均值至少 5%，剔最高三笔后仍为正；2025 验证段与 2026 测试段都不能由一两笔股票独占，且均值不能为负。
- 改进现有口诀：保留下来的交易胜率与 E3 均值不能同时下降，总收益不能靠删除大赢家换来；被剔除交易必须逐年列明，不能只看 2024-12。
- 合并或通用化：必须用更少或相同的条件表达，并在 2020—2022、2023—2024、2025、2026 四段分别成立；否则不合并。
- 所有候选都要做边界扰动、逐票清单、与现有交易重叠检查。小样本只展示，不下方向结论。

### Task 1: 建立同源研究样本

**Files:**
- Create: `量化因子研究/高位接力/scripts/hpr_hidden_range_research.py`
- Read: `alphaagent/server/services/high_relay/backtest.py`
- Read: `alphaagent/server/services/high_relay/contracts.py`

1. 在 API 容器内调用 `build_events()`，只读数据库，不触发物化重建。
2. 按 `dyn_month_states` 与 `dyn_take_point()` 重建当前实际出手点，核对最新物化报告的总笔数、E3 均值和胜率。
3. 核对四笔指定亏损及 2024-12 全部交易，保存研究数据到 `/tmp`，不把静态快照提交到仓库。
4. 验证买入日之后的数据没有进入任何新增特征。

### Task 2: 计算买入前隐藏特征

**Files:**
- Modify: `量化因子研究/高位接力/scripts/hpr_hidden_range_research.py`

新增特征分五组，每组先单独检查，再做组合：

1. 连板链的精确下影线、振幅、相对量能和换手变化，不再只使用“下影/实体”二分类。
2. 地基日实体、上下影线、收盘位置、相对过去二十日的量能与换手。
3. 连板前路径：波动、回撤、上涨天数、过去涨停与炸板次数、距最近一次炸板天数。
4. 上方成交压力：过去六十日在地基收盘价之上成交的量占比、成交量加权价格位置；用于补足“距六十日新高”只看极值的盲区。
5. 个股自身尺度：股价、由成交量和换手推算的流通市值、连板换手相对地基前二十日正常水平的倍数、今天开盘相对前几板开盘的变化。

### Task 3: 分优先级搜索并冻结候选

**Files:**
- Modify: `量化因子研究/高位接力/scripts/hpr_hidden_range_research.py`
- Create: `/tmp/hpr_hidden_range_candidates.json`

1. 扩量：在 2023—2024 年当前未出手中寻找简单区间组合，2025 年只验证不调整。
2. 提质：在当前实际出手中寻找坏票集中区，再检查同条件是否误删其他年份的大赢家。
3. 合并与通用：对已通过前两步的条件检查跨板位、跨阴阳和跨时代一致性；没有结构证据则不强行合并。
4. 所有阈值从样本分位点和完整分布产生，不围绕四笔亏损手写阈值；冻结候选定义后才能读取 2026 年特征结果。

### Task 4: 最终测试与逐票终审

**Files:**
- Modify: `量化因子研究/高位接力/scripts/hpr_hidden_range_research.py`

1. 对冻结候选读取 2026 年结果，输出训练、验证、最终测试三段样本数、胜率、E3 均值、中位数和剔最高三笔均值。
2. 做阈值邻域扰动，孤立最优点直接否决。
3. 输出新增、删除、保留的逐票清单，特别标明四笔 2024-12 亏损分别被哪条候选处理。
4. 若候选未过门禁，明确记录否决原因，不改生产代码；若通过，也只提交研究结论，等产品修改指令后再接入 `SCHEMES`、镜像匹配和版本号。

## 验证命令

```bash
# 单元测试
uv run pytest -q 量化因子研究/高位接力/scripts/test_hpr_hidden_range_research.py

# 将研究脚本复制到 API 容器后执行；数据库只读
python /tmp/hpr_hidden_range_tests/hpr_hidden_range_research.py dump
python /tmp/hpr_hidden_range_tests/hpr_hidden_range_research.py discover
python /tmp/hpr_hidden_range_tests/hpr_hidden_range_research.py verify
```

`discover` 只生成待人工复核的原始候选；复核后才能写入 `/tmp/hpr_hidden_range_candidates.json`。没有冻结候选时，`verify` 不读取 2026 年新特征结果。

预期：样本总数与实际出手成绩和最新物化报告一致；所有候选均有分段时间结果、剔三结果和逐票明细；不发生生产数据库写入。
