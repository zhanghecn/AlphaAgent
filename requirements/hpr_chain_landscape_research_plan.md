# 高位接力全连板全景研究计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从全体连板链的继续与断板演变中寻找稳定形态规律，再映射为高位接力口诀的扩量、提质、新增、合并或跨行情优化，不再从单条口诀的少量亏损票直接反推条件。

**Architecture:** 使用生产 `backtest.build_events()` 返回的同源日线构建完整连板节点，同时保留继续封板、触板未封、未触板三种次日结果。先在全体样本和近似形态中搜索规律，再在原有触板买入与 E3 口径中验收；2020—2024 发现、2025 验证、2026 最终隔离，任何生产规则与数据库均不写入。

**Tech Stack:** Python、Pandas、NumPy、pytest、现有 AlphaAgent 高位接力回测与生产判定函数。

---

## 一、与既往研究的区别

1. 既有月度“好票坏票清单”只含二接三、三接四的触板事件，且主要看买入后的次日好坏；本研究补齐完整连板链、四板以上节点和未触板的直接断板。
2. 既有 126 个变体只回答“现有条件删掉或放宽会怎样”；本研究先问“全体近似连板形态中，什么稳定地区分继续与断板”，再检查该规律能否迁移回口诀。
3. A2 等二接三口诀不能只选后来成功达到三板的链条倒看二板。节点池必须包含所有达到二板的股票，否则会把未来结果混进样本选择。
4. “次日继续连板”与“触板买入后的 E3 收益”分别报告。只在全体演变中有效、但在触板交易子样本中无效的规律，不用于修改口诀。

## 二、样本与标签

### 2.1 连板节点

每个节点表示：某股票在锚定日收盘已经连续 `N` 板，研究其下一交易日演变。

- 全景重点：`N>=3`；为映射 A/B 类二接三口诀，同时保留所有 `N=2` 节点。
- “全体”沿用生产同源宇宙：当前股票表中的主板、当前名称非 ST/退且具备足够历史位置的股票；它不是包含历史 ST、已退市股票的完整全 A 宇宙，结论不能超出这个数据边界。
- 决策信息：锚定日收盘及此前数据，以及下一交易日开盘涨幅；不得使用下一交易日盘中或收盘数据作为特征。
- 下一交易日必须取同一只股票的下一条日线，不能按自然日或其他股票行移位；另记录日期间隔以识别停牌。没有下一行的右端样本标为 `pending`，不能归入未触板。
- 次日结果三分类：`continue`（收盘继续涨停）、`touch_break`（盘中触板但收盘未封）、`no_touch`（全天未触板）。
- 额外结局标签：当前链条最终高度、距离当前节点还能增加几板；这些只能作为研究目标，不能作为特征。最终高度直接取同一 `chain_id` 的最大 `streak`，不复用旧四进五脚本对炸板事件可能错误的最终高度算法。
- 每个节点记录 `chain_id`，同一股票同一段连续涨停属于同一链条。统计除节点数外，还必须报告独立链条数、股票数和覆盖月份，避免一只长妖股重复贡献多笔而制造假规律。
- 一字、顶格、未触板、静态特征缺失及 E3 未完均不提前从锚点分母删除；它们只作为后续不同研究视图的标记。

### 2.2 交易映射

- 原 `build_events()` 的已完成事件先按同次回放的 `_bar_i` 定位，再用“股票＋买入日”复核；`_bar_i` 只在同次回放内使用，永久业务键为“股票＋买入日”。
- 每笔事件同时保留两种关系：来源锚点为 `(买入日行-1, H=N)`；只有买入日封住时，新达到锚点才为 `(买入日行, H=N+1)`。炸板事件没有新达到锚点，但必须保留在来源链中。
- 关联采用左连接并记录未匹配原因，不能因为锚点缺失而删除原交易；原 6370 个研究事件和原标签必须一致。动态实际出手以当前版本为准：`hpr-v7.21` 为 202 笔，E3 胜率 80.2%、E3 均值 11.96%，不再沿用研究时的 208 笔基线。
- 全景规律映射到现有策略时，只使用正常开盘、触板且非全天一字的真实可交易子集。
- 新规律若改变口诀命中，最终必须重算动态月状态与出手路径，不能只静态剔除或添加后比较收益。

### 2.3 时间隔离

- 发现：2020—2024；在发现段内部按年滚动检查，并分别观察 2020—2022 与 2023—2024。
- 验证：2025；只验证已冻结的形态和阈值，不根据验证结果继续调参。
- 最终：2026；候选冻结、验证通过后才读取。
- 其他 AI 文档已经展示过 C2/K2/C3/A2/B2/K9/C1 某些单腿变体的 2026 结果；这些具体变体不能再宣称拥有独立的 2026 最终验证，只用于提出更一般的特征类别。

## 三、优先搜索的形态家族

1. **板型变化的位置**：一字、实体、下影分别在首板、中间板、末板出现的影响；重点检查“连续锁仓后第一次出现实体分歧”是否比单纯“末板是实体”更稳定。
2. **换手变化的位置**：末板换手相对首板、前一板、链条峰值和地基前正常水平的变化；检查当前单一换手窗是否只是某种更根本的放量或锁仓结构的代理。
3. **开盘强度轨迹**：首板到末板的开盘方向、峰值位置、连续加速或衰减，以及今天开盘相对上一板开盘的变化；用于寻找 A1/A2、B1/B2、C3 等口诀的共同本体。
4. **下影洗盘的位置**：首板下影、末板下影、链条下影次数与精确长度；检验 B2/K9 的“首板下影”是否在全池中具有独立意义，而不是只改善历史胜率。
5. **地基与前波结构**：地基阴阳、前 10/20 日涨幅、前波高度、距前波时间、距新高的组合；重点检查 A2 前 10 日条件和 K5 前波=0 是否属于同一类“首次主升与高位再接力”规律。
6. **跨板位与跨时代迁移**：同一因素只有在多个板位、多个年份、多个独立链条中同向，才进入合并或通用化候选；若方向随时代翻转，则保留为时代专属条件。

其他 AI 文档中的单口诀腿按以下方式使用：C2/K2 末板实体归入第 1 类，A2 前 10 日归入第 5 类，B2/K9 首板下影归入第 4 类，C3 一字分支归入第 1 类。B2、C1 已否决的具体腿不直接翻案，但若全景发现新的组合结构，可按新假说重新验证。

## 四、逐阶段实施

### Task 1：建立完整连板链研究底座

**Files:**
- Create: `量化因子研究/高位接力/scripts/hpr_chain_landscape.py`
- Create: `量化因子研究/高位接力/scripts/test_hpr_chain_landscape.py`
- Read: `alphaagent/server/services/high_relay/backtest.py`
- Read: `alphaagent/server/services/high_relay/pool.py`
- Read: `量化因子研究/高位接力/scripts/hpr_hidden_range_research.py`

- [ ] 先写三分类、链条编号和未来信息隔离测试。

```python
def test_next_outcome_covers_all_three_paths():
    nodes = make_nodes(next_close_limit=[True, False, False], next_touch=[True, True, False])
    assert classify_next_outcome(nodes).tolist() == ["continue", "touch_break", "no_touch"]


def test_feature_window_never_reads_decision_day_after_open():
    before = build_node_features(make_bars(), decision_i=4, n_board=2)
    changed = make_bars()
    changed.loc[4, ["high_price", "low_price", "close_price", "volume", "turnover_rate"]] *= 3
    after = build_node_features(changed, decision_i=4, n_board=2)
    assert before == after
```

- [ ] 补充合成数据测试：连续 1—5 板、断板重起链、跨周末、跨股票、次日一字、无下一行；验证锚点高度、首板/地基行、三分类和 `pending`。另验证一字、顶格、未触板、特征缺失与 E3 未完都保留在全量分母中，左关联不增加原事件行数。
- [ ] 实现最小节点构建接口，所有原始日线和涨停判定来自生产回放。

```python
def build_chain_nodes(bars: pd.DataFrame) -> pd.DataFrame:
    """返回 N>=2 的锚定节点、chain_id、下一交易日开盘及三类结局。"""


def attach_node_features(nodes: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """复用 pool.static_fields 与买入前特征，不读取决策日开盘后的数据。"""


def link_trade_events(nodes: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """左连接原事件，增加 source_anchor_id、reached_anchor_id、chain_id 与匹配状态。"""
```

- [ ] 在 API 容器执行只读构建，只复用同一次 `build_events()` 返回的 `bars`，不二次读取数据库，也不复制旧脚本中的 E3 算法；落盘 `/tmp/hpr_chain_landscape.csv`，2026 单独保存为 `/tmp/hpr_chain_landscape_2026.csv`，分析命令默认只读取 2020—2025 文件。
- [ ] 对账：无重复“股票＋决策日”；三分类覆盖全部已完成节点，尾部为 `pending`；来源锚点满足 `(i-1,H=N)`，封住事件的新达到锚点满足 `(i,H=N+1)`，未封行为空；关联前后原事件行数不膨胀，原标签与 E3 差异为 0。

### Task 2：生成每年每月全连板全景

**Files:**
- Modify: `量化因子研究/高位接力/scripts/hpr_chain_landscape.py`
- Modify: `量化因子研究/高位接力/scripts/test_hpr_chain_landscape.py`

- [ ] 先写链条聚类测试：同一股票同一连续涨停段只能有一个 `chain_id`，断板后的新连板段必须换号。
- [ ] 实现全景汇总，不以单月结果直接生成规则。

```python
def landscape_report(nodes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """按年、月、N、地基阴阳输出节点、独立链条及三类次日结果。"""


def chain_aware_summary(frame: pd.DataFrame, value: str) -> dict[str, object]:
    """同时给出节点数、独立链条数、均值、胜率、去最高三链条均值。"""
```

- [ ] 输出每年、每月的 3+ 链条清单：首板日、锚定日、当前高度、后续最终高度、次日三分类、现有口诀是否命中。
- [ ] 先核对基数最大的形态和季节/时代差异，再进入近似形态研究；月份只用于检查供给与稳定性，不作为外部行情过滤条件。

### Task 3：围绕每条口诀建立近似形态池

**Files:**
- Modify: `量化因子研究/高位接力/scripts/hpr_chain_landscape.py`
- Modify: `量化因子研究/高位接力/scripts/test_hpr_chain_landscape.py`

- [ ] 为每条分支定义可解释的“形态模板”：地基阴阳、首板/末板开盘与换手、今天开盘；辅助质量腿不进入邻域定义。
- [ ] 邻域分四层：同板位同本体、同板位相差一个条件、平移到其他板位、对侧地基阴阳。生产基线仍由原 `tag_scheme()`/`tag_weak()` 计算，模板只用于寻找邻域。
- [ ] 近似票优先在同月、同板位、同今天开盘档内匹配，再跨月、跨时代验证；这样可减少把某段行情整体强弱误判为个股形态效果，但月份本身不进入最终口诀。
- [ ] 对每个因素扫描完整分布，不预设二值阈值；优先寻找相邻区间方向一致、跨年份也一致的结构。保留每个形态家族的完整搜索结果和候选总数，不只展示最佳区间。

```python
def neighbor_pool(nodes: pd.DataFrame, template: dict[str, object], level: str) -> pd.DataFrame:
    """level = core / one_relaxation / shifted_board / opposite_foundation。"""


def factor_spectrum(frame: pd.DataFrame, feature: str) -> pd.DataFrame:
    """按完整分位区间报告继续率、触板未封率、未触板率和独立链条数。"""
```

- [ ] 每个有希望的规律必须给出具体近似票对：相同核心形态、只有一个主要因素不同，但结果分别继续和断板；列出日期、股票、板位、该因素数值及随后高度。
- [ ] 邻域证据与目标口诀子样本必须同向；只靠其他板位或其他口诀的好结果，不直接修改目标口诀。

### Task 4：从全景规律生成五类优化候选

**Files:**
- Modify: `量化因子研究/高位接力/scripts/hpr_chain_landscape.py`
- Modify: `量化因子研究/高位接力/scripts/test_hpr_chain_landscape.py`

- [ ] **扩量/新增**：在当前全局原始口诀之外寻找净新增，跨组迁移不算新增。
- [ ] **提质**：同时报告保留、删除和新增交易，禁止只展示被删坏票。
- [ ] **合并**：只有相同根本条件能替代两个以上分支且交易集合不降质时才成立。
- [ ] **跨行情**：分别检查弱市时代、强市时代和动态月状态，不能只用合并后的总收益。
- [ ] **简化**：优先选择不超过两条新增条件的表达；复杂模型只用于提出假说，不直接成为口诀。

候选统一接口：

```python
def evaluate_candidate(nodes: pd.DataFrame, candidate: dict[str, object], include_final: bool) -> dict[str, object]:
    """输出发现、验证及按需最终段；包含链条级、交易级、逐年逐月和逐票证据。"""


def replay_dynamic_path(events: pd.DataFrame, candidate: dict[str, object]) -> pd.DataFrame:
    """改变命中后重新计算 dyn_month_states 与 dyn_take_point，保持其他规则不变。"""
```

### Task 5：冻结、验证与最终逐票终审

**Files:**
- Modify: `量化因子研究/高位接力/scripts/hpr_chain_landscape.py`
- Create: `/tmp/hpr_chain_landscape_candidates.json`（仅人工复核后创建）

- [ ] 候选冻结内容必须包括形态本体、因素、阈值、适用板位、适用时代、净新增定义及研究假设。
- [ ] 新增交易沿用现有门禁：至少 10 笔、胜率至少 60%、E3 均值至少 5%、去最高三笔为正；另要求独立链条和月份支持，验证段不能由一两笔决定。
- [ ] 提质要求保留集胜率与 E3 均值均不下降，并列出全部被删大赢家；只看胜率提高但总收益下降仍否决。
- [ ] 做阈值邻域扰动、逐年、逐月、逐链条、跨板位和重叠检查；孤立最优点、单年独撑、单只长妖股独撑均否决。
- [ ] 通过发现与 2025 验证后才读取 2026；若候选与已看过 2026 的旧单腿假说相同，明确标注其最终段不独立。
- [ ] 最终只提交研究结论和具体口诀表达；未经主人确认，不修改 `SCHEMES`、`WEAK_SCHEMES`、动态组、版本号或实时规则。

## 五、复跑与验收命令

```bash
uv run pytest -q 量化因子研究/高位接力/scripts/test_hpr_chain_landscape.py

# 数据构建在 API 容器只读执行
python /tmp/hpr_chain_landscape_tests/hpr_chain_landscape.py build

# 默认只读取 2020—2025，2026 不进入搜索
uv run python 量化因子研究/高位接力/scripts/hpr_chain_landscape.py panorama
uv run python 量化因子研究/高位接力/scripts/hpr_chain_landscape.py neighbors
uv run python 量化因子研究/高位接力/scripts/hpr_chain_landscape.py discover
uv run python 量化因子研究/高位接力/scripts/hpr_chain_landscape.py verify
```

`panorama` 完成样本和月度全景核对后才能进入 `neighbors`；`neighbors` 的具体票对和跨段稳定性核对后才能进入 `discover`；没有人工冻结候选时，`verify` 不读取 2026。

预期产物不是一份复杂模型，而是少量能直接写成口诀的规律，以及每条规律对应的全体样本证据、近似票对、净新增/保留/删除清单和动态路径复跑结果。