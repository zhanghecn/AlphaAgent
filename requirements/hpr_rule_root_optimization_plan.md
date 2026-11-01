# 高位接力逐口诀寻根优化计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 逐条审计当前 13 条高位接力口诀的形态本体与辅助条件，寻找不降质的扩量、提质、合并与跨行情优化证据。

**Architecture:** 研究时使用 `hpr-v7.20` 同源事件数据和生产 `tag_scheme()`、`tag_weak()` 判定；现行版本为 `hpr-v7.21`，复跑时必须按当前规则重建事件与动态出手。每条口诀先生成当前基线，再做留一条件、边界变化、同链反事实和同今开反事实；任何候选均按对应行情时代验证，不用其他时代的收益证明时代专属口诀。

**Tech Stack:** Python、Pandas、NumPy、scikit-learn、现有 AlphaAgent 高位接力代码、PostgreSQL 只读物化报告。

---

## 当前口诀与研究顺序

- 强市八条：A1（低开等强开/平开等温开）、A2、B1（转温/续强）、B2（双低/承接）、B3、C1、C2、C3（二板一字/三板一字）。
- 弱市五条：K2、K4（缩量承接/一板平开）、K5、K9、K3。
- 通用组：K5 整条与 B1·转温；它们是出手范围，不是额外的新口诀。
- 第一批提质：A2、B2·承接、C3·三板一字、K9。
- 第二批家族寻根：C2/K2、C3、B2/B3、A1/K9、B1/K5。
- 第三批扩量：A1、B1、B3、K5；K4 只在弱市样本内评价。

## 验收纪律

- 强市口诀：2023—2024 发现、2025 验证、2026 最终测试。
- 通用项：2020—2024 发现、2025 验证、2026 最终测试，并分别报告 2020—2022 与 2023 年以后。
- 弱市专属口诀：2020—2021 发现、2022 验证，2023 年以后只作衰退参考；不能用强市年代的好结果证明弱市口诀有效。
- 新分支至少 10 笔、胜率至少 60%、E3 均值至少 5%、去最高三笔后为正；验证段不能由一两笔决定。
- 放宽或合并后，交易数增加时胜率与 E3 均值不能同时下降；提质时保留集胜率与均值均不能下降，且列出删除的大赢家。
- 所有候选做邻域扰动、逐年统计、逐票清单、与现有口诀重叠检查。小样本只展示，不给方向结论。

### Task 1: 建立逐口诀基线与研究审计器

**Files:**
- Create: `量化因子研究/高位接力/scripts/hpr_rule_root_audit.py`
- Create: `量化因子研究/高位接力/scripts/test_hpr_rule_root_audit.py`
- Read: `量化因子研究/高位接力/scripts/hpr_hidden_range_research.py`

1. 先写分支识别、统计口径和缺失值测试，再实现最小审计器。
2. 复用现有 6370 个同源事件；生产版本或事件总数变化时停止并重新构建。
3. 强市按方案子项统计；弱市 K4 分支按缩量承接与一板平开重新识别，不能误用强市子项字段。
4. 输出 18 个分支在各自时代的笔数、胜率、E3 均值、中位数、去最高三笔均值和逐年数据。

### Task 2: 实现形态本体与辅助腿反事实审计

**Files:**
- Modify: `量化因子研究/高位接力/scripts/hpr_rule_root_audit.py`
- Modify: `量化因子研究/高位接力/scripts/test_hpr_rule_root_audit.py`

1. 只临时替换生产规则副本，调用原 `tag_scheme()` 或 `tag_weak()`，不手写另一套判定。
2. 每条分支计算：完整规则、去掉每条辅助腿、单独形态本体、相邻开盘档、相邻换手档、对侧阴阳与相邻板位。
3. 记录每个变体相对基线的新增、删除、保留交易及其收益；重叠交易不重复计为扩量。
4. 对缺失值统一使用最终候选掩码统计，禁止模型填充口径与冻结口径不一致。

### Task 3: 逐条分析坏票与漏网好票

**Files:**
- Modify: `量化因子研究/高位接力/scripts/hpr_rule_root_audit.py`

1. A2、B2·承接、C3·三板一字、K9：先比较同一形态内好票与坏票，再检查辅助腿是否误伤。
2. C2/K2：检验是否能用同一本体加一条时代或地基规则表达，避免只改名称不改记忆负担。
3. A1、B1、B3、K5：重点看当前未命中但同本体的漏网好票，不重复已经否决的简单扩窗。
4. K4、K9：只在 2020—2022 内做发现与验证；2023 年以后只解释为何停用。
5. B2、C1、K4 弱开买点：另建包含未触板交易日的全日事件样本，以真实开盘价重算收益；分别报告触板、未触板和全体开盘买结果，禁止用事后知道会触板的样本证明开盘买有效。

### Task 4: 候选终审与逐口诀结论

**Files:**
- Modify: `量化因子研究/高位接力/scripts/hpr_rule_root_audit.py`

1. 对通过发现与验证的候选冻结定义，最后才读取对应最终测试段。
2. 输出每个候选的基线、变体、保留、新增、删除及逐年逐票证据。
3. 每条口诀归入：可优化、保持现状、样本不足；后两类必须给出具体证据。
4. 未获主人确认前不修改 `SCHEMES`、`WEAK_SCHEMES`、镜像匹配、版本号或实时规则。

## 验证命令

```bash
uv run pytest -q 量化因子研究/高位接力/scripts/test_hpr_rule_root_audit.py

# 数据重建在 API 容器执行；分析命令可复用已生成的 /tmp 数据
python /tmp/hpr_hidden_range_tests/hpr_rule_root_audit.py build
uv run python 量化因子研究/高位接力/scripts/hpr_rule_root_audit.py baseline
uv run python 量化因子研究/高位接力/scripts/hpr_rule_root_audit.py audit
python /tmp/hpr_hidden_range_tests/hpr_rule_root_audit.py build-open-entry
uv run python 量化因子研究/高位接力/scripts/hpr_rule_root_audit.py open-entry
```

原始事件缺失、数量不是 6370 笔或必需字段缺失时，分析命令必须停止并提示 `build`；全日事件不是 13216 笔或触板数不是 6370 笔时，必须提示 `build-open-entry`。

预期：当前规则基线与物化报告一致；所有研究变体均来自生产判定函数；最终测试不被发现阶段读取；生产数据库与生产源码均无写入。
